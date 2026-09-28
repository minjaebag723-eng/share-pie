"""Kiln API 키를 받으면 가장 먼저 실행: python scripts/check_kiln.py

확인 항목
 1) 기본 chat/completions 호출 + usage(토큰) 반환 여부
 2) tools + tool_choice(특정 함수 강제) 지원 여부  → 안 되면 .env 에 KILN_TOOL_MODE=json
 3) reasoning_effort 파라미터 지원 여부            → 안 되면 KILN_REASONING_EFFORT= (빈 값)
"""
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config  # noqa: E402

if not config.KILN_API_KEY:
    sys.exit("✗ .env 에 KILN_API_KEY 가 없어요")

URL = f"{config.KILN_BASE_URL}/chat/completions"
print(f"주소 {URL}\n모델 {config.KILN_MODEL}\n키 {config.KILN_API_KEY[:8]}…{config.KILN_API_KEY[-4:]} (길이 {len(config.KILN_API_KEY)})\n")
H = {"Authorization": f"Bearer {config.KILN_API_KEY}"}
TOOL = {"type": "function", "function": {"name": "set_split_rule", "description": "분담 조건 구조화", "parameters": {
    "type": "object", "properties": {"less_name": {"type": "string"}, "less_value": {"type": "integer"}},
    "required": ["less_name", "less_value"]}}}


def call(label, body):
    t = time.perf_counter()
    try:
        r = httpx.post(URL, json={"model": config.KILN_MODEL, **body}, headers=H, timeout=60)
    except httpx.HTTPError as e:
        print(f"✗ {label}: 연결 실패 {e}")
        return None
    ms = int((time.perf_counter() - t) * 1000)
    if r.status_code >= 400:
        print(f"✗ {label}: HTTP {r.status_code} {r.text[:200]}")
        return None
    d = r.json()
    print(f"✓ {label}: {ms}ms usage={d.get('usage')}")
    return d


try:
    r = httpx.get(f"{config.KILN_BASE_URL}/models", headers=H, timeout=15)
    d = r.json()
    ids = [m.get("id") for m in (d.get("data") if isinstance(d, dict) else d) or [] if isinstance(m, dict)]
    print(f"이 키로 쓸 수 있는 모델 (HTTP {r.status_code}): {ids if ids else r.text[:300]}")
    from agent.llm import pick_model, same_model  # noqa: E402
    if config.KILN_MODEL_STRICT:
        exact = same_model(ids, config.KILN_MODEL) if ids else config.KILN_MODEL
        if exact:
            print(f"✓ {config.KILN_MODEL} 사용 가능 → '{exact}' 로 호출해요\n")
            config.KILN_MODEL = exact
        else:
            print(f"✗ 이 키로는 {config.KILN_MODEL} 을 쓸 수 없어요. Kiln 콘솔에서 이 모델 권한을 켜 주세요 "
                  f"(다른 모델로 자동 교체는 KILN_MODEL_STRICT=0 일 때만)\n")
    best = config.KILN_MODEL if config.KILN_MODEL_STRICT else pick_model(ids, config.KILN_MODEL)
    if best and best != config.KILN_MODEL:
        print(f"→ '{config.KILN_MODEL}' 대신 '{best}' 로 테스트해요. .env 에 KILN_MODEL={best} 로 고정하세요\n")
        config.KILN_MODEL = best
    elif not best:
        from agent.llm import client  # noqa: E402
        best = client.find_model()
        if best:
            print(f"→ 시험 호출로 찾은 모델: '{best}'. .env 에 KILN_MODEL={best} 로 고정하세요\n")
            config.KILN_MODEL = best
        else:
            print("→ 쓸 수 있는 모델을 못 찾았어요. 키 발급처에 모델 이름을 물어보고 .env 에 KILN_MODEL=... 로 넣어주세요\n")
except Exception as e:  # noqa: BLE001
    print("모델 목록 조회 실패:", e, "\n")

msgs = [{"role": "user", "content": "진주는 5천원 적게 내고 나머지 세 명이 나눠줘."}]
d = call("1) 기본 호출", {"messages": [{"role": "user", "content": "안녕! 한 문장으로 답해줘."}], "max_tokens": 300})
if d:
    print("   →", (d["choices"][0]["message"].get("content") or "")[:80])
else:
    print("\n→ 기본 호출부터 안 돼서 2)·3)은 건너뜀. 코드 문제가 아니라 이 키에 모델 권한이 없는 거예요 (Kiln 콘솔·운영진 확인)")
    sys.exit(1)

d = call("2) tool calling", {"messages": msgs, "tools": [TOOL],
                             "tool_choice": {"type": "function", "function": {"name": "set_split_rule"}}, "max_tokens": 600})
if d:
    tc = d["choices"][0]["message"].get("tool_calls")
    print("   → tool_calls:", json.dumps(tc, ensure_ascii=False)[:200] if tc else "없음 (content로 응답) → KILN_TOOL_MODE=json 권장")

d = call("3) reasoning_effort=low", {"messages": msgs, "reasoning_effort": "low", "max_tokens": 300})
if not d:
    print("   → .env 에서 KILN_REASONING_EFFORT= 로 비워 주세요")
