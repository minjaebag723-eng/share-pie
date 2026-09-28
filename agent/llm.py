"""Kiln API (OpenAI 호환, qwen3-32b on FuriosaAI RNGD) 클라이언트.

설계 원칙
- LLM은 '해석'과 '설명'만 한다. 계산·검증·지출 통제는 코드가 한다.
- tool calling(openai parser)을 먼저 쓰고, Kiln이 tools를 거절하면 JSON 프롬프트로 자동 전환한다.
- 모든 호출은 usage.jsonl 에 단계(stage)별로 기록된다.
- Kiln 장애 시 규칙 기반 대체 응답(mock)으로 떨어져 데모가 멈추지 않는다 (응답에 degraded 표시).
"""
from __future__ import annotations

import re
import json
import threading
import time
from typing import Any, Callable

import httpx

from . import quota, config, usage


_NOT_CHAT = ("embed", "rerank", "whisper", "tts", "speech", "audio", "moderation", "dall-e", "image", "clip", "ocr")
_PREFER = ("gpt-oss-120b", "gpt-oss", "qwen", "llama", "exaone", "deepseek", "gemma", "mistral", "gpt", "claude")
FALLBACK_NAMES = ["qwen3-32b", "Qwen/Qwen3-32B", "gpt-oss-120b", "openai/gpt-oss-120b", "furiosa-ai/gpt-oss-120b", "gpt-oss-20b", "openai/gpt-oss-20b",
                  "Qwen/Qwen2.5-32B-Instruct", "meta-llama/Llama-3.1-8B-Instruct", "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct"]


def pick_model(ids: list[str], want: str) -> str | None:
    """서버가 가진 모델 중 쓸 모델 고르기: 원하는 모델 → gpt-oss 계열 → 다른 대화용 모델 아무거나."""
    if not ids:
        return None
    w = want.lower().split("/")[-1]
    for i in ids:
        if i.lower() == want.lower() or i.lower().split("/")[-1] == w:
            return i
    chat = [i for i in ids if not any(x in i.lower() for x in _NOT_CHAT)] or ids
    for key in _PREFER:
        for i in chat:
            if key in i.lower():
                return i
    return chat[0]


def same_model(ids: list[str], want: str) -> str | None:
    """같은 모델의 다른 표기만 허용 (예: gpt-oss-120b = openai/gpt-oss-120b)."""
    w = want.lower().split("/")[-1]
    return next((i for i in ids if i.lower() == want.lower() or i.lower().split("/")[-1] == w), None)


def list_models() -> list[str]:
    r = httpx.get(f"{config.KILN_BASE_URL}/models", headers={"Authorization": f"Bearer {config.KILN_API_KEY}"}, timeout=15)
    r.raise_for_status()
    d = r.json()
    return [m.get("id") for m in (d.get("data") if isinstance(d, dict) else d) or [] if isinstance(m, dict) and m.get("id")]


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


THINK_STAGES = ("shopping.plan", "dispute.investigate")  # 사고가 필요한 단계만 추론 허용


def strip_think(text: str) -> str:
    """추론 모델이 본문에 섞는 <think>…</think> 블록 제거."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return re.sub(r"^.*?</think>", "", text, flags=re.S).strip()


def extract_json(text: str) -> dict[str, Any]:
    """모델 출력에서 첫 번째 JSON 객체를 꺼낸다 (```json 블록, 앞뒤 설명문 허용)."""
    text = strip_think(text)
    if not text:
        raise LLMError("LLM_BAD_OUTPUT", "빈 응답")
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise LLMError("LLM_BAD_OUTPUT", "JSON을 찾지 못함")


class KilnClient:
    def __init__(self) -> None:
        self.mode = config.LLM_MODE
        self.tools_supported: bool | None = None if config.KILN_TOOL_MODE == "auto" else config.KILN_TOOL_MODE == "tools"
        # reasoning_effort는 gpt-oss 계열 파라미터 — qwen3는 /no_think(사고 끄기)로 토큰을 줄인다
        self.send_reasoning = bool(config.KILN_REASONING_EFFORT) and "gpt-oss" in config.KILN_MODEL.lower()
        self._http = httpx.Client(timeout=config.KILN_TIMEOUT)

    # ── 공개 API ──
    def call_tool(self, stage: str, system: str, user: str, tool: dict[str, Any], *,
                  mock: Callable[[], dict[str, Any]], flow: str | None = None,
                  max_tokens: int = 700) -> tuple[dict[str, Any], dict[str, Any]]:
        """구조화 추출. 반환: (arguments dict, meta)"""
        if self.mode != "live":
            return self._mock(stage, flow, mock, "mock")
        try:
            if self.tools_supported is not False:
                try:
                    return self._tool_call(stage, system, user, tool, flow, max_tokens)
                except LLMError as e:
                    if e.code != "TOOLS_UNSUPPORTED":
                        raise
                    self.tools_supported = False
            return self._json_call(stage, system, user, tool, flow, max_tokens)
        except LLMError as e:
            return self._mock(stage, flow, mock, "fallback", note=f"{e.code}: {e.message}"[:200])
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError, AttributeError) as e:  # 잘린·이상한 출력
            return self._mock(stage, flow, mock, "fallback", note=f"LLM_BAD_OUTPUT: {type(e).__name__} {e}"[:200])

    def call_text(self, stage: str, system: str, user: str, *, mock: Callable[[], str],
                  flow: str | None = None, max_tokens: int = 600) -> tuple[str, dict[str, Any]]:
        """짧은 설명문 생성."""
        if self.mode != "live":
            out, meta = self._mock(stage, flow, lambda: {"text": mock()}, "mock")
            return out["text"], meta
        try:
            data, meta = self._post(stage, flow, {
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens,
            })
            text = strip_think(data["choices"][0]["message"].get("content") or "")
            if not text:
                raise LLMError("LLM_BAD_OUTPUT", "빈 content (max_tokens 부족 가능)")
            return text, meta
        except (LLMError, KeyError, IndexError, TypeError, AttributeError) as e:
            code = e.code if isinstance(e, LLMError) else "LLM_BAD_OUTPUT"
            out, meta = self._mock(stage, flow, lambda: {"text": mock()}, "fallback", note=f"{code}: {e}"[:200])
            return out["text"], meta

    def agent_step(self, stage: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                   flow: str | None = None, max_tokens: int = 1500, force: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """대화형 에이전트 한 걸음: 모델이 도구를 부를지(tool_calls) 답할지(content) 스스로 정한다.
        tools 미지원 서버면 JSON 약속({"tool","args"} / {"answer"})으로 같은 동작. 실패 시 LLMError."""
        if self.mode != "live":
            raise LLMError("LLM_OFFLINE", "Kiln 키 없음")
        if self.tools_supported is not False:
            try:
                data, meta = self._post(stage, flow, {"messages": messages, "max_tokens": max_tokens,
                                                      "tools": [{"type": "function", "function": t} for t in tools],
                                                      "tool_choice": {"type": "function", "function": {"name": force}} if force else "auto"},
                                        mode="tools")
                try:
                    msg = data["choices"][0]["message"]
                except (KeyError, IndexError, TypeError) as e:
                    raise LLMError("LLM_BAD_OUTPUT", f"choices 없음: {e}") from e
                calls = []
                for c in msg.get("tool_calls") or []:
                    if not isinstance(c, dict) or not isinstance(c.get("function"), dict) or not c["function"].get("name"):
                        continue
                    a = c["function"].get("arguments") or "{}"
                    try:
                        a = json.loads(a) if isinstance(a, str) else a
                    except json.JSONDecodeError:
                        a = {}
                    if not isinstance(a, dict):
                        a = {}
                    calls.append({"id": c.get("id") or f"call_{len(calls)}", "name": c["function"]["name"], "args": a})
                return {"content": strip_think(msg.get("content") or ""), "tool_calls": calls, "raw": msg}, meta
            except LLMError as e:
                if e.code != "TOOLS_UNSUPPORTED":
                    raise
                self.tools_supported = False
        # JSON 약속 모드
        spec = "\n".join(f"- {t['name']}: {t['description']} 인자 {json.dumps(t['parameters'].get('properties', {}), ensure_ascii=False)}"
                         for t in tools)
        sys0 = messages[0]["content"] + ("\n\n도구가 필요하면 JSON 하나만 출력: {\"tool\": 이름, \"args\": {...}}\n"
                                         "답할 준비가 됐으면 JSON 하나만 출력: {\"answer\": \"사용자에게 할 말\"}\n도구 목록:\n" + spec)
        conv = [{"role": "system", "content": sys0}]
        for m in messages[1:]:
            if m["role"] == "tool":
                conv.append({"role": "user", "content": f"[도구 결과 {m.get('name', '')}] {m['content']}"})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                tc = m["tool_calls"][0]["function"]
                conv.append({"role": "assistant", "content": json.dumps({"tool": tc["name"], "args": json.loads(tc["arguments"])}, ensure_ascii=False)})
            else:
                conv.append({"role": m["role"], "content": m.get("content") or ""})
        data, meta = self._post(stage, flow, {"messages": conv, "max_tokens": max_tokens}, mode="json")
        try:
            text = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("LLM_BAD_OUTPUT", f"choices 없음: {e}") from e
        try:
            j = extract_json(text)
        except LLMError:
            return {"content": strip_think(text), "tool_calls": []}, meta
        if j.get("tool"):
            args = j.get("args") if isinstance(j.get("args"), dict) else {}
            return {"content": "", "tool_calls": [{"id": "call_json", "name": str(j["tool"]), "args": args}]}, meta
        return {"content": str(j.get("answer") or strip_think(text)), "tool_calls": []}, meta

    # ── 내부 ──
    def _tool_call(self, stage, system, user, tool, flow, max_tokens):
        payload = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "tools": [{"type": "function", "function": tool}],
            "tool_choice": {"type": "function", "function": {"name": tool["name"]}},
            "max_tokens": max_tokens,
        }
        data, meta = self._post(stage, flow, payload, mode="tools")
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if calls:
            args = calls[0]["function"].get("arguments") or "{}"
            self.tools_supported = True
            return (json.loads(args) if isinstance(args, str) else args), meta
        # tools 파라미터는 받았지만 tool_call 대신 본문에 JSON을 쓴 경우
        return extract_json(msg.get("content") or ""), meta

    def _json_call(self, stage, system, user, tool, flow, max_tokens):
        schema = json.dumps(tool["parameters"], ensure_ascii=False, separators=(",", ":"))
        sys2 = (f"{system}\n\n반드시 아래 JSON 스키마를 만족하는 JSON 객체 하나만 출력하라. 설명·코드블록 금지.\n"
                f"스키마({tool['name']}): {schema}")
        data, meta = self._post(stage, flow, {
            "messages": [{"role": "system", "content": sys2}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }, mode="json")
        return extract_json(data["choices"][0]["message"].get("content") or ""), meta

    def _post(self, stage: str, flow: str | None, payload: dict[str, Any], mode: str = "text"):
        """동시 호출 상한(KILN_MAX_CONCURRENCY): 자리가 날 때까지 KILN_QUEUE_WAIT초 기다리고, 넘으면 KILN_BUSY →
        부른 쪽이 규칙 기반으로 먼저 답한다 (100명이 한꺼번에 불러도 서버·Kiln 키가 버티게)."""
        over = quota.check(stage)
        if over:
            raise LLMError("AI_LIMIT", quota.limit_text(over))
        if _SLOTS is None:
            return self._post_kiln(stage, flow, payload, mode)
        if not _SLOTS.acquire(timeout=config.KILN_QUEUE_WAIT):
            raise LLMError("KILN_BUSY", f"지금 Pie를 부르는 사람이 많아요 (동시 {config.KILN_MAX_CONCURRENCY}건). 규칙 기반으로 먼저 답해요")
        try:
            return self._post_kiln(stage, flow, payload, mode)
        finally:
            _SLOTS.release()

    def _post_kiln(self, stage: str, flow: str | None, payload: dict[str, Any], mode: str = "text"):
        over = quota.check(stage)            # 구독 한도(5시간·주간)를 넘었으면 Kiln을 부르지 않는다 (0 토큰 → 규칙 기반)
        if over:
            raise LLMError("AI_LIMIT", quota.limit_text(over))
        body = {"model": config.KILN_MODEL, "temperature": 0.1, **payload}
        if "qwen3" in config.KILN_MODEL.lower() and body.get("messages") and stage not in THINK_STAGES:  # Qwen3: 긴 사고 끄기 → 토큰 절약
            msgs = [dict(m) for m in body["messages"]]
            idx = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=None)
            if idx is not None and isinstance(msgs[idx].get("content"), str) and "/no_think" not in msgs[idx]["content"]:
                msgs[idx]["content"] = f"{msgs[idx]['content']} /no_think"
            body["messages"] = msgs
        if self.send_reasoning:   # gpt-oss: 평소엔 low(토큰 절약), 판정처럼 어려운 단계만 medium
            body["reasoning_effort"] = (config.KILN_REASONING_EFFORT_THINK if stage in THINK_STAGES and config.KILN_REASONING_EFFORT_THINK
                                        else config.KILN_REASONING_EFFORT)
        headers = {"Authorization": f"Bearer {config.KILN_API_KEY}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        for attempt in range(3):
            try:
                r = self._http.post(f"{config.KILN_BASE_URL}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise LLMError("LLM_UNAVAILABLE", f"Kiln 연결 실패: {e}") from e
                time.sleep(0.8 * (attempt + 1))
                continue
            if r.status_code == 404 and "model" in r.text.lower():
                if not getattr(self, "_model_probed", False):
                    self._model_probed = True
                    found = self.find_model()
                    if found and found != body["model"]:
                        body["model"] = found
                        continue
                raise LLMError("MODEL_UNAVAILABLE", f"Kiln에서 {config.KILN_MODEL} 모델을 이 키로 쓸 수 없어요 (HTTP 404) — "
                               "Kiln 콘솔에서 모델 권한을 확인해 주세요" if config.KILN_MODEL_STRICT else
                               "HTTP 404 이 키로 쓸 수 있는 모델을 찾지 못했어요")
            if r.status_code == 400:
                text = r.text.lower()
                if "reasoning" in text and "reasoning_effort" in body:
                    self.send_reasoning = False
                    body.pop("reasoning_effort", None)
                    continue
                if "tools" in body and isinstance(body.get("tool_choice"), dict) and "tool_choice" in text:
                    raise LLMError("FORCE_REJECTED", r.text[:300])   # 강제 도구 선택만 거절 → 전체 tools 모드는 유지
                if "tools" in body and re.search(r"(not|n't|un)\s*support|tools? (is|are) not|unknown (field|param\w*).{0,20}tool|"
                                                 r"extra (fields|inputs).{0,40}tool", text):
                    raise LLMError("TOOLS_UNSUPPORTED", r.text[:300])
                raise LLMError("LLM_BAD_REQUEST", r.text[:300])
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise LLMError("LLM_UNAVAILABLE", f"HTTP {r.status_code}: {r.text[:200]}")
            try:
                data = r.json()
                if not isinstance(data, dict) or not data.get("choices"):
                    raise ValueError("choices 없음")
            except ValueError as e:
                raise LLMError("LLM_BAD_OUTPUT", f"응답 형식 오류: {e} {r.text[:120]}") from e
            ch0 = (data["choices"][0] or {})
            msg0 = ch0.get("message") or {}
            if (ch0.get("finish_reason") == "length" and not (msg0.get("content") or "").strip() and not msg0.get("tool_calls")
                    and body.get("max_tokens", 0) < 4000 and attempt < 2):
                # gpt-oss는 답 전에 추론 토큰을 쓰므로, 추론만 하다 한도에 걸리면 한도를 늘려 한 번 더 (쓴 토큰도 기록)
                u0 = data.get("usage") or {}
                usage.record(stage, flow=flow, prompt_tokens=u0.get("prompt_tokens", 0), completion_tokens=u0.get("completion_tokens", 0),
                             latency_ms=int((time.perf_counter() - t0) * 1000), mode=mode, cost=u0.get("cost"), model=body["model"],
                             note=f"추론 중 max_tokens {body.get('max_tokens')} 도달 → 한도 늘려 재시도")
                body["max_tokens"] = min(4000, max(800, int(body.get("max_tokens") or 600) * 2))
                continue
            u = data.get("usage") or {}
            latency = int((time.perf_counter() - t0) * 1000)
            row = usage.record(stage, flow=flow, prompt_tokens=u.get("prompt_tokens", 0),
                               completion_tokens=u.get("completion_tokens", 0), latency_ms=latency, mode=mode,
                               cost=u.get("cost"), model=body["model"])
            return data, _meta(row)
        raise LLMError("LLM_UNAVAILABLE", "재시도 초과")

    def find_model(self) -> str | None:
        """① 서버 모델 목록에서 고르기 ② 목록 조회가 안 되면 흔한 이름을 1토큰 호출로 차례로 시험."""
        try:
            ids = list_models()
        except Exception:  # noqa: BLE001
            ids = []
        if config.KILN_MODEL_STRICT:   # 고정 모델: 같은 모델의 다른 표기(openai/gpt-oss-120b 등)만 찾고, 다른 모델로는 안 바꿈
            found = same_model(ids, config.KILN_MODEL)
            if not found and not ids:
                h = {"Authorization": f"Bearer {config.KILN_API_KEY}"}
                for name in [n for n in FALLBACK_NAMES if n.lower().split("/")[-1] == config.KILN_MODEL.lower().split("/")[-1]]:
                    try:
                        r = self._http.post(f"{config.KILN_BASE_URL}/chat/completions", headers=h, json={
                            "model": name, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
                    except httpx.HTTPError:
                        continue
                    if r.status_code < 400:
                        found = name
                        break
            print(f"[Kiln] 모델 '{config.KILN_MODEL}' → " + (f"'{found}' 표기로 연결" if found else
                  f"이 키로 쓸 수 없음 (쓸 수 있는 모델: {ids[:15]}) · 다른 모델로 바꾸지 않고 규칙 기반 응답으로 대체해요"), flush=True)
            if found:
                config.KILN_MODEL = found
            return found
        found = pick_model(ids, config.KILN_MODEL)
        if not found:
            h = {"Authorization": f"Bearer {config.KILN_API_KEY}"}
            for name in FALLBACK_NAMES:
                try:
                    r = self._http.post(f"{config.KILN_BASE_URL}/chat/completions", headers=h, json={
                        "model": name, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
                except httpx.HTTPError:
                    continue
                try:
                    u = (r.json().get("usage") or {}) if r.status_code < 400 else {}
                except ValueError:
                    u = {}
                usage.record("kiln.probe", flow="setup", prompt_tokens=u.get("prompt_tokens", 0),
                             completion_tokens=u.get("completion_tokens", 0), latency_ms=0, mode="text", note=f"모델 탐색 {name}",
                             model=name)
                if r.status_code < 400:
                    found = name
                    break
        print(f"[Kiln] 모델 '{config.KILN_MODEL}' 없음 → 사용 가능 {ids[:15]} → 선택: {found}", flush=True)
        if found:
            config.KILN_MODEL = found
        return found

    def _mock(self, stage, flow, fn, mode, note=""):
        if mode == "fallback" and note:
            print(f"[{'AI 한도' if note.startswith('AI_LIMIT') else 'Kiln 실패'}] {stage}: {note[:120]}", flush=True)  # 서버 창에서 원인 확인
        t0 = time.perf_counter()
        out = fn()
        row = usage.record(stage, flow=flow, prompt_tokens=0, completion_tokens=0,
                           latency_ms=int((time.perf_counter() - t0) * 1000), mode=mode, note=note)
        return out, _meta(row)


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    m = {k: row[k] for k in ("stage", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "mode")}
    if row.get("note"):
        m["note"] = row["note"]
    return m


def _reason(note: str) -> str:
    """실패 원인을 말풍선용 짧은 한국어로."""
    n = note or ""
    if "AI_LIMIT" in n:
        return "AI 사용 한도 도달"
    if "MODEL_UNAVAILABLE" in n:
        return f"{config.KILN_MODEL} 사용 권한 없음(404)"
    for code, ko in (("401", "키 인증 실패(401)"), ("403", "접근 거부(403)"), ("404", "주소/모델 없음(404)"),
                     ("429", "호출 한도 초과(429)"), ("TOOLS_UNSUPPORTED", "tool calling 미지원")):
        if code in n:
            return ko
    if "연결 실패" in n or "LLM_UNAVAILABLE" in n:
        m = re.search(r"HTTP (\d{3})", n)
        return f"서버 오류(HTTP {m.group(1)})" if m else "서버에 연결 안 됨"
    if "LLM_BAD_REQUEST" in n:
        return "요청 거부(400)"
    return "응답 오류"


def code_step(stage: str, flow: str | None, note: str = "") -> dict[str, Any]:
    """LLM 없이 코드로 처리한 단계도 기록 → '불필요한 추론을 줄였다'는 증거."""
    return _meta(usage.record(stage, flow=flow, prompt_tokens=0, completion_tokens=0, latency_ms=0, mode="code", note=note))


def decision(stage: str, flow: str | None, note: str) -> dict[str, Any]:
    """Kiln 응답이 에이전트의 다음 행동을 어떻게 바꿨는지 (0 토큰 기록). 심사 기준: 'API 응답이 의사결정·행동에 반영되는 방식'.
    예: assistant.step → "도구 menu_price_search 호출", settlement.analyze → "규칙 해석 → 코드 계산으로"."""
    return _meta(usage.record(stage, flow=flow, prompt_tokens=0, completion_tokens=0, latency_ms=0, mode="decision", note=note[:240]))


def meta_line(metas: list[dict[str, Any]]) -> str:
    """채팅 말풍선 아래에 붙는 한 줄 (예: 'AI 2회 · 812 토큰 · 1.9초')."""
    llm = [m for m in metas if m["mode"] in ("tools", "json", "text")]
    if not llm:
        if any(m["mode"] == "fallback" for m in metas):
            fb = next(m for m in metas if m["mode"] == "fallback")
            if "AI_LIMIT" in (fb.get("note") or ""):
                return "AI 사용 한도 도달 → 규칙 기반 응답 · AI 호출 0회 · 0 토큰"
            return f"Kiln 연결 실패: {_reason(fb.get('note', ''))} → 규칙 기반 응답"
        if any(m["mode"] == "mock" for m in metas):
            return "오프라인 규칙 모드 (Kiln 키 없음)"
        return "코드 처리 · AI 호출 0회 · 0 토큰"
    toks = sum(m["total_tokens"] for m in llm)
    sec = sum(m["latency_ms"] for m in llm) / 1000
    return f"{model_label()} {len(llm)}회 · {toks:,} 토큰 · {sec:.1f}초"


def model_label() -> str:
    """말풍선 표시용 — 실제 연결된 서버·모델 그대로 (Kiln이 아니면 Kiln이라고 쓰지 않는다)."""
    if "bricksum" in config.KILN_BASE_URL:
        return f"Kiln {config.KILN_MODEL}"
    if "anthropic" in config.KILN_BASE_URL:
        return f"Claude {config.KILN_MODEL} (임시·Kiln 아님)"
    return config.KILN_MODEL


_SLOTS = threading.BoundedSemaphore(config.KILN_MAX_CONCURRENCY) if config.KILN_MAX_CONCURRENCY > 0 else None
client = KilnClient()
