"""Kiln 없이 live 경로를 검증하는 가짜 OpenAI 호환 서버 (테스트 전용).
FAKE_TOOLS=1 → tool_calls 로 응답 / 0 → tools 파라미터를 400으로 거절 (JSON 모드 전환 검증)
FAKE_REJECT_REASONING=1 → reasoning_effort 를 400으로 거절 (파라미터 자동 제거 검증)
"""
import asyncio
import random
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent import dispute, settlement, shopping

TOOLS = os.environ.get("FAKE_TOOLS", "1") == "1"
REJECT_REASONING = os.environ.get("FAKE_REJECT_REASONING", "1") == "1"
CALLS = []
FORCED = [False]


def _args_for(tool_name, user):
    req = re.search(r"요청: (.*)", user)
    text = req.group(1) if req else user
    prev = re.search(r"이전 대화: (.*)", user)
    if tool_name == "set_split_rule":
        mem = re.search(r"참여자: (.*)", user).group(1)
        members = [] if "모름" in mem else [m.strip() for m in mem.split(",")]
        r = settlement._mock_rule(text, members, None, None)
        r["purpose"] = "공동구매 분담금(주문자 진주 5천원 감면)"  # 일부러 실명 포함 → sanitize 검증
        return r
    if tool_name == "set_shopping_query":
        return shopping._mock_query(((prev.group(1) + " ") if prev else "") + text)
    if tool_name == "set_dispute_verdict":
        reason = re.search(r"이의 사유: (.*)", user).group(1)
        state = re.search(r"이의 제기자: .*\(체인 상태: (\w+)\)", user)
        return dispute._mock_judge(reason, state.group(1) if state else None, "[error]" in user)
    if tool_name == "route":
        return {"intent": "ask"}
    if tool_name == "plan_menu_combos":  # 일부러 틀린 조합 섞기 → 코드 검증 확인
        return {"combos": [{"label": "파티", "reason": "치킨과 피자", "items": [{"id": "d1", "qty": 1}, {"id": "d2", "qty": 1}]},
                           {"label": "환각", "items": [{"id": "zz9", "qty": 2}]},
                           {"label": "초과", "items": [{"id": "d3", "qty": 6}, {"id": "d1", "qty": 6}]}]}
    if tool_name == "answer_plan":
        if "한정선" in text or "한정선" in user[-40:]:
            return {"need_search": True, "search_query": "한정선 찹쌀떡", "answer": ""}
        return {"need_search": False, "answer": "앞의 가격은 검색한 판매가 기준이에요."}
    return {}


def _agent_decide(msgs):
    """대화형 에이전트 흉내: 도구 결과를 보고 다음 행동 결정."""
    user = next(m["content"] for m in reversed(msgs) if m["role"] == "user" and not m["content"].startswith(("[도구 결과", "[앱]")))
    done = [m.get("name") or re.search(r"\[도구 결과 (\w+)", m["content"]).group(1) for m in msgs
            if m["role"] == "tool" or (m["role"] == "user" and m["content"].startswith("[도구 결과"))]
    ppl = int((re.search(r"(\d+)\s*명", user) or [0, 4])[1])
    if "아까" in user:   # 다음 턴: 이전에 찾은 메뉴를 이름으로 다시 씀
        if "check_delivery_combos" not in done:
            return "tool", "check_delivery_combos", {"people": 6, "budget_total": 90000, "combos": [
                {"label": "허니콤보 3", "items": [{"id": "교촌치킨 허니콤보", "qty": 3, "serves": 2}]}]}
        return "answer", "허니콤보 3마리로 바꿨어요.", None
    if "교촌" in user:
        if "menu_price_search" not in done:
            return "tool", "menu_price_search", {"food": "치킨", "brands": ["교촌"]}
        if "check_delivery_combos" not in done:
            return "tool", "check_delivery_combos", {"people": ppl, "budget_total": 60000, "combos": [
                {"label": "허니콤보 2", "items": [{"id": "m1", "qty": 2, "serves": 2}]}]}
        return "answer", "교촌 허니콤보 2마리 조합이에요. 가격은 카카오톡 선물하기 판매가 기준이에요.", None
    if "배달" in user or "이츠" in user:
        if "menu_price_search" not in done:
            return "tool", "menu_price_search", {"food": "치킨", "brands": ["교촌"]}
        if "check_delivery_combos" not in done and "대가족" in user and not FORCED[0]:
            return "answer", "1. **치킨+피자 조합** - 총 179,800원 (검증 안 한 숫자)", None
        if "check_delivery_combos" not in done:
            k = max(1, -(-ppl // 8))
            return "tool", "check_delivery_combos", {"people": ppl, "budget_total": 250000 if ppl > 8 else 200000, "combos": [
                {"label": "파티", "reason": "허니콤보 넉넉하게", "items": [{"id": "m1", "qty": max(2, -(-ppl // 2)), "serves": 2}]},
                {"label": "환각", "items": [{"id": "zz9", "qty": 1}]},
                {"label": "든든", "items": [{"id": "m1", "qty": max(2, -(-ppl // 2)), "serves": 2}, {"id": "m2", "qty": 1, "serves": 2}]}]}
        return "answer", f"{ppl}명이면 치킨+피자 ‘파티’ 조합을 추천해요. 예산은 20만원으로 가정했어요.", None
    if "한정선" in user and "search_products" not in done and "뭐야" not in user:
        return "tool", "search_products", {"query": "한정선 찹쌀떡", "must_include": ["한정선"], "budget_total": 200000}
    if ("브랜드" in user or "뭐야" in user) and "web_search" not in done:
        return "tool", "web_search", {"query": "한정선 찹쌀떡"}
    return "answer", "검색 결과를 보면 한정선은 성수 디저트 브랜드예요." if done else "안녕하세요! 무엇을 도와드릴까요?", None


DELAY = float(os.environ.get("FAKE_KILN_DELAY") or 0)     # 부하 테스트: 실제 Kiln처럼 응답에 걸리는 시간(초)


async def completions(request):
    b = await request.json()
    if DELAY:
        await asyncio.sleep(DELAY * (0.6 + 0.8 * random.random()))
    CALLS.append({k: (v if k != "messages" else len(v)) for k, v in b.items()})
    if REJECT_REASONING and "reasoning_effort" in b:
        return JSONResponse({"error": {"message": "Unknown parameter: reasoning_effort"}}, status_code=400)
    usage = {"prompt_tokens": 420, "completion_tokens": 96, "total_tokens": 516}
    sys_msg, user = b["messages"][0]["content"], b["messages"][-1]["content"]
    agent = ("tools" in b and len(b["tools"]) > 1) or "도구 목록" in sys_msg
    if agent:
        if "tools" in b and not TOOLS:
            return JSONResponse({"error": {"message": "tools is not supported"}}, status_code=400)
        FORCED[0] = isinstance(b.get("tool_choice"), dict) or "[앱]" in str(b["messages"][-1].get("content"))
        kind, name, args = _agent_decide(b["messages"])
        if "tools" in b:
            msg = ({"role": "assistant", "content": None, "tool_calls": [{"id": f"call_{len(CALLS)}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]} if kind == "tool"
                   else {"role": "assistant", "content": "<think>생각</think>" + name})
        else:
            msg = {"role": "assistant", "content": json.dumps({"tool": name, "args": args} if kind == "tool" else {"answer": name}, ensure_ascii=False)}
        return JSONResponse({"choices": [{"message": msg}], "usage": usage})
    if "tools" in b:
        if not TOOLS:
            return JSONResponse({"error": {"message": "tools is not supported"}}, status_code=400)
        name = b["tools"][0]["function"]["name"]
        args = _args_for(name, user)
        return JSONResponse({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}}],
            "usage": usage})
    m = re.search(r"스키마\((\w+)\)", sys_msg)
    if m:
        content = "다음은 결과입니다:\n```json\n" + json.dumps(_args_for(m.group(1), user), ensure_ascii=False) + "\n```"
    elif "목록에 없다" in sys_msg:
        content = "찾으시는 품목은 Share Pie 공동구매 목록에 없어요. 1인 예산 안에서 고르시고, 메뉴와 금액이 정해지면 정산방을 만들어 드릴게요."
    elif "정산 설명" in sys_msg:
        content = "코드가 계산한 금액 그대로, 조건에 맞춰 나눴어요."
    else:
        content = "B 상품이 예산 안에서 양이 가장 넉넉해 추천해요. A는 마감이 임박했고, C는 예산을 조금 넘어요."
    return JSONResponse({"choices": [{"message": {"role": "assistant", "content": content}}], "usage": usage})


async def calls(_):
    return JSONResponse(CALLS)


app = Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"]), Route("/calls", calls)])
