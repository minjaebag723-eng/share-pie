"""계산 조건 해석 평가 (Pie mate 학습 가이드라인 ⑥) — 문장 → 코드가 낸 분담표가 기대값과 1원까지 같은지,
되묻기 문제는 계산하지 않고 되묻는지 채점한다 (채점은 코드 · 0 tokens).

코드 안전망만 (Kiln 없이 · 반드시 100%):
  DATA_DIR=/tmp/sp-calc LLM_MODE=mock KILN_API_KEY= python tests/calc_check.py
실제 Kiln (목표: 분담표 일치 95% 이상 · 되묻기 100%):
  DATA_DIR=/tmp/sp-calc LLM_MODE=live python tests/calc_check.py          # .env의 KILN 키·모델 사용
옵션: --only ce-05,ce-06   --save (tests/results/에 결과 JSON)   -v (틀린 문제의 해석 JSON까지 출력)
문제는 tests/calc_eval.jsonl (실제 대화에서 틀렸던 문장을 계속 추가) · 예시는 agent/pie_brain/calc_examples.jsonl.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config, llm, settlement  # noqa: E402

HERE = Path(__file__).resolve().parent


def load(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            sys.exit(f"{path.name}:{i} JSON 오류: {e}")
    return rows


def grade(case: dict, r: dict) -> tuple[bool, str]:
    exp = case["expect"]
    if exp.get("ask"):
        return r["status"] == "need_info", f"{r['status']}: {(r.get('question') or '')[:60]}"
    if r["status"] != "ok":
        return False, f"{r['status']}: {(r.get('question') or '')[:70]}"
    got = {n: a for n, a in r["shares"]}
    why = []
    if r["total"] != exp["total"]:
        why.append(f"총액 {r['total']:,} ≠ {exp['total']:,}")
    if got != exp["shares"]:
        why.append("분담 " + ", ".join(f"{n} {a:,}" for n, a in got.items()))
    if exp.get("payer") and r["payer"] != exp["payer"]:
        why.append(f"결제자 {r['payer']} ≠ {exp['payer']}")
    if exp.get("warn") and not any(w["code"] == exp["warn"] for w in r["warnings"]):
        why.append(f"경고 {exp['warn']} 없음")
    return not why, " · ".join(why) or ", ".join(f"{n} {a:,}" for n, a in got.items())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    cases = load(HERE / "calc_eval.jsonl")
    if a.only:
        want = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in want]
    mode = llm.client.mode
    print(f"[계산 조건 해석 평가] {len(cases)}문제 · 모드 {mode}" + (f" · 모델 {config.KILN_MODEL}" if mode == "live" else " (코드 안전망만)"))
    rows, t0 = [], time.time()
    for c in cases:
        r = settlement.calculate(text=c["text"], members=c.get("members") or [], total=c.get("total"),
                                 payer=c.get("payer"), flow=f"calc-eval-{c['id']}")
        ok, detail = grade(c, r)
        metas = r.get("metas") or []
        ai = [m for m in metas if m.get("mode") in ("tools", "json", "text")]
        fixed = [m.get("note", "") for m in metas if m.get("mode") == "code" and "AI가 놓친" in (m.get("note") or "")]
        fb = any(m.get("mode") == "fallback" for m in metas)
        rows.append({"id": c["id"], "type": c.get("type"), "ask": bool(c["expect"].get("ask")), "ok": ok, "detail": detail,
                     "tokens": sum(m.get("total_tokens", 0) for m in ai), "fixed": fixed, "fallback": fb})
        mark = "✓" if ok else "✗"
        extra = (" [코드 보정]" if fixed and mode == "live" else "") + (" [Kiln 실패→규칙]" if fb else "")
        print(f"  {mark} {c['id']} {c['text'][:34]:<34} → {detail}{extra}")
        if a.verbose and not ok:
            print("      rule:", json.dumps(r.get("rule"), ensure_ascii=False)[:400])
    calc = [x for x in rows if not x["ask"]]
    ask = [x for x in rows if x["ask"]]
    rate = lambda xs: (100.0 * sum(x["ok"] for x in xs) / len(xs)) if xs else 100.0   # noqa: E731
    called = [x for x in rows if x["tokens"]]
    avg = sum(x["tokens"] for x in called) / len(called) if called else 0
    print(f"\n분담표 일치 {sum(x['ok'] for x in calc)}/{len(calc)} ({rate(calc):.1f}%) · 되묻기 {sum(x['ok'] for x in ask)}/{len(ask)} ({rate(ask):.1f}%)"
          + (f" · 호출당 평균 {avg:,.0f} 토큰 · 코드 보정 {sum(1 for x in rows if x['fixed'])}건 · Kiln 실패 {sum(x['fallback'] for x in rows)}건"
             if mode == "live" else "") + f" · {time.time() - t0:.1f}초")
    need_calc, need_ask = (100.0, 100.0) if mode != "live" else (95.0, 100.0)
    passed = rate(calc) >= need_calc and rate(ask) >= need_ask
    print(("✓ 목표 달성" if passed else "✗ 목표 미달") + f" (분담표 {need_calc:g}% 이상 · 되묻기 {need_ask:g}%)")
    if a.save:
        out = HERE / "results"
        out.mkdir(exist_ok=True)
        p = out / f"calc_eval_{time.strftime('%Y%m%d-%H%M')}_{mode}.json"
        p.write_text(json.dumps({"mode": mode, "model": config.KILN_MODEL if mode == "live" else None,
                                 "calc_rate": rate(calc), "ask_rate": rate(ask), "avg_tokens": avg, "rows": rows},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        print("저장:", p)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
