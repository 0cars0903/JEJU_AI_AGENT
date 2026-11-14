"""일반 질문 '답 요소' 판정(질문 담당 Agent 측정, 2026-11-15). 문항: data/eval/general_answer_300.jsonl(Gemini 060, dev 150 · judge 150).

사용: python tools/eval/general_answer.py [--split dev|judge] [--mode workflow|agent] [--out 결과.json]
- workflow: 지금 일반 경로(result.respond). agent: 질문 담당 Agent(app/question_agent.py).
- 정규식 보정 규칙(2026-11-15 P1)은 JEJU_RULE_FIX=0으로 끈다(Agent만으로 되는지 보려고).
채점(코드, 문항 하나 = 정답/오답):
- 처리: 답함(답이 나옴) / 되묻기(조건을 고르게 함) / 범위밖이 정답 expect와 같다.
- 답함이면 모두 맞아야 정답: 동네 집합, 지표(metric_ok 중 하나가 계산 지표에 있음), 업종(target_ok가 있으면), 조건(정답 cond가 계산 조건에 있음),
  기간(정답 period의 해·달·최근 N개월이 계산에 반영됨), 순위 방향(order가 asc면 작은 순서, 순위 질문이면 종류가 순위·조건 탐색).
"""
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

args = sys.argv[1:]
split = args[args.index("--split") + 1] if "--split" in args else "dev"
mode = args[args.index("--mode") + 1] if "--mode" in args else "workflow"
out = Path(args[args.index("--out") + 1]) if "--out" in args else None
FILE = ROOT / "data" / "eval" / "general_answer_300.jsonl"


def status_of(r):
    st = r.get("status")
    if st == "범위밖":
        return "범위밖"
    if st in ("선택필요", "되묻기"):
        return "되묻기"
    return "답함" if (r.get("card") or r.get("agent")) else "되묻기"


def score(r, g):
    t = r.get("tuple") or {}
    s = {"처리": status_of(r) == g["expect"]}
    if g["expect"] == "답함" and s["처리"]:
        s["동네"] = sorted(t.get("space") or []) == sorted(g.get("space") or [])
        s["지표"] = not g.get("metric_ok") or bool(set(t.get("metric") or []) & set(g["metric_ok"]))
        s["업종"] = not g.get("target_ok") or (t.get("target") in g["target_ok"])
        s["조건"] = set(g.get("cond") or []) <= set(t.get("cond") or [])
        p = g.get("period") or {}
        s["기간"] = (not p.get("year") or t.get("ask_year") == p["year"]) and (not p.get("month") or t.get("ask_month") == p["month"]) \
            and (not p.get("recent_months") or t.get("ask_recent") == p["recent_months"])
        s["순위"] = (not g.get("order") or t.get("type") in ("T3", "T14")) and (g.get("order") != "asc" or t.get("order") == "asc")
    s["정답"] = all(s.values())
    return s


def main():
    import os
    items = [json.loads(l) for l in FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    items = [g for g in items if g.get("split") == split]
    if mode == "agent":
        import question_agent as A
        ask = lambda q: A.run(q, {}, llm_on=False)  # noqa: E731
    else:
        import result
        ask = lambda q: result.respond(q, {}, llm_on=False)  # noqa: E731
    rows = []
    for g in items:
        t0 = time.perf_counter()
        try:
            r = ask(g["q"])
        except Exception as e:  # 한 문항의 오류로 전체를 멈추지 않는다
            r = {"status": f"오류:{type(e).__name__}"}
        s = score(r, g)
        qa = r.get("question_agent") or {}
        rows.append({"id": g["id"], "ok": s["정답"], "cells": s, "hard": g.get("hard") or [], "sec": round(time.perf_counter() - t0, 2),
                     "turns": [{k: x.get(k) for k in ("gaps", "choice", "action", "change", "note")} for x in qa.get("turns", [])],
                     "calls": len(qa.get("turns", [])), "status": r.get("status")})
        print(json.dumps({k: rows[-1][k] for k in ("id", "ok", "status", "sec", "calls")}, ensure_ascii=False), flush=True)
    by = {}
    for r in rows:
        for h in r["hard"] or ["(일반)"]:
            by.setdefault(h, [0, 0])
            by[h][0] += r["ok"]
            by[h][1] += 1
    secs = [r["sec"] for r in rows]
    summ = {"file": FILE.name, "split": split, "mode": mode, "rule_fix": os.environ.get("JEJU_RULE_FIX", "1"), "n": len(rows), "정답": sum(r["ok"] for r in rows),
            "유형별": {k: f"{a}/{b}" for k, (a, b) in sorted(by.items())}, "칸별 오답": {k: sum(1 for r in rows if r["cells"].get(k) is False) for k in ("처리", "동네", "지표", "업종", "조건", "기간", "순위")},
            "지연 중앙값": statistics.median(secs) if secs else None, "지연 90%": sorted(secs)[int(len(secs) * 0.9)] if secs else None,
            "모델 판단 평균 횟수": round(statistics.mean(r["calls"] for r in rows), 2) if rows else 0,
            "다시 계산 건수": sum(1 for r in rows for x in r["turns"] if x["action"] == "다시 계산")}
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if out:
        out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
