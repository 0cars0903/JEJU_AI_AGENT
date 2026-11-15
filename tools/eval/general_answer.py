"""일반 질문 판정(질문 담당 Agent 측정). 정답 기준: data/eval/answer_rubric.md(마스터 승인 2026-11-15, A안).

문항: data/eval/general_answer_v2.jsonl(생성 모델 5종: Gemini 060 300 + Opus·Fable·Sonnet·Haiku 각 80, 정답은 만든 모델이 아닌 두 모델이 붙임)
사용: python tools/eval/general_answer.py [--split dev|judge] [--mode workflow|agent] [--no-rule-fix] [--out 결과.json] [--file 문항.jsonl]
- workflow: 계획 표 경로(result.respond). agent: 질문 담당 Agent(app/question_agent.py, 기본 구성).
- --no-rule-fix: 정규식 보정 규칙(2026-11-15 P1)을 끈다(Agent만으로 되는지 비교할 때. 서비스는 늘 켬).
채점 네 층: ① 처리가 허용 집합(accept) 안 ② 요소(동네·지표·업종·기간·조건·순위) 맞은 비율 ③ 안내 정직성(notice가 답에 밝혀졌나) ④ 완전 정답(①②③ 모두).
애매 문항(ambiguous)은 ④ 주 점수에서 빼고 따로 센다.
"""
import json
import re
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
FILE = Path(args[args.index("--file") + 1]) if "--file" in args else ROOT / "data" / "eval" / "general_answer_v2.jsonl"
# ③ 안내 정직성: notice 종류마다 답(결론·안내·한계·근거 문장)에 있어야 하는 말
NOTICE = {"대체 지표": r"대신|가까운|없어(요)?[.,]?|봤어요|기준으로", "제주 전체 값": r"제주 전체", "자료 없음": r"없어|없습니다|없고",
          "센터 자료 필요": r"센터", "방문으로 대신": r"방문"}


COND_GROUP = {"비": "비", "주말": "주말", "평일": "주말", "봄": "계절", "여름": "계절", "가을": "계절", "겨울": "계절", "계절": "계절",
              "성수기": "성수기", "비수기": "성수기"}


def status_of(r):
    st = r.get("status")
    if st == "범위밖":
        return "범위밖"
    if st in ("선택필요", "되묻기"):
        return "되묻기"
    return "답함" if (r.get("card") or r.get("agent")) else "되묻기"


def said(r):
    """답에 쓰인 문장 전체(안내 정직성 대조용)."""
    c = r.get("card") or {}
    parts = [c.get("conclusion") or "", " ".join(c.get("limits") or []), " ".join(x.get("text", "") for x in c.get("evidence") or [])]
    parts += list((r.get("understood") or {}).get("notes") or [])
    for b in ((r.get("answer") or {}).get("blocks") or []):
        parts += [x.get("text", "") for x in b.get("lines") or []]
    return " ".join(parts)


def score(r, g):
    t = r.get("tuple") or {}
    st = status_of(r)
    s = {"처리": st in (g.get("accept") or [])}
    el = {}
    if st == "답함" and s["처리"]:
        if g.get("space") is not None:
            got, want = sorted(t.get("space") or []), sorted(g.get("space") or [])
            # 한 지명이 행정동 둘에 걸치면(일도동 → 일도1동·일도2동) 정답 동네가 여럿이다. 답한 동네가 그 후보 안이면 맞음
            el["동네"] = got == want or (len(want) > 1 and bool(got) and set(got) <= set(want) and not g.get("order"))
        if g.get("metric_ok"):
            el["지표"] = bool(set(t.get("metric") or []) & set(g["metric_ok"]))
        if g.get("target_ok"):
            el["업종"] = t.get("target") in g["target_ok"]
        if g.get("cond"):  # 조건은 네 묶음(비·주말·계절·성수기)으로 비교(정답 라벨과 같은 기준)
            el["조건"] = {COND_GROUP.get(c, c) for c in g["cond"]} <= {COND_GROUP.get(c, c) for c in (t.get("cond") or [])}
        p = g.get("period") or {}
        if p:
            el["기간"] = (not p.get("year") or t.get("ask_year") == p["year"]) and (not p.get("month") or t.get("ask_month") == p["month"]) \
                and (not p.get("recent_months") or t.get("ask_recent") == p["recent_months"])
        if g.get("order"):
            el["순위"] = t.get("type") in ("T3", "T14") and (g["order"] != "asc" or t.get("order") == "asc")
        text = said(r)
        need = [n for n in (g.get("notice") or []) if n in NOTICE]
        s["안내"] = all(re.search(NOTICE[n], text) for n in need) if need else None
    s["요소"] = el
    s["요소 비율"] = round(sum(el.values()) / len(el), 3) if el else (1.0 if s["처리"] else 0.0)
    s["정답"] = s["처리"] and all(el.values()) and s.get("안내") is not False
    return s


def main():
    import result
    if "--no-rule-fix" in args:
        result.RULE_FIX = False
    items = [json.loads(l) for l in FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    items = [g for g in items if g.get("split") == split]
    if mode == "agent":
        import question_agent as A
        ask = lambda q: A.run(q, {}, llm_on=False)  # noqa: E731
    else:
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
        rows.append({"id": g["id"], "gen": g.get("gen"), "ambiguous": bool(g.get("ambiguous")), "ok": s["정답"], "cells": s, "hard": g.get("hard") or [],
                     "sec": round(time.perf_counter() - t0, 2), "status": r.get("status"),
                     "turns": [{k: x.get(k) for k in ("gaps", "choice", "action", "change", "note")} for x in qa.get("turns", [])], "calls": len(qa.get("turns", []))})
        print(json.dumps({k: rows[-1][k] for k in ("id", "ok", "status", "sec", "calls")}, ensure_ascii=False), flush=True)
    main_rows = [r for r in rows if not r["ambiguous"]]

    def grp(key):
        out_ = {}
        for r in main_rows:
            for k in (key(r) if isinstance(key(r), list) else [key(r)]) or ["(일반)"]:
                out_.setdefault(k, [0, 0])
                out_[k][0] += r["ok"]
                out_[k][1] += 1
        return {k: f"{a}/{b}" for k, (a, b) in sorted(out_.items())}
    secs = [r["sec"] for r in rows]
    honest = [r["cells"].get("안내") for r in main_rows if r["cells"].get("안내") is not None]
    summ = {"file": FILE.name, "split": split, "mode": mode, "rule_fix": result.RULE_FIX, "n": len(rows), "애매 제외 n": len(main_rows),
            "④ 완전 정답": sum(r["ok"] for r in main_rows), "① 처리": sum(r["cells"]["처리"] for r in main_rows),
            "② 요소 비율 평균": round(statistics.mean(r["cells"]["요소 비율"] for r in main_rows), 3) if main_rows else None,
            "③ 안내 정직성": f"{sum(honest)}/{len(honest)}", "애매 문항 정답": f"{sum(r['ok'] for r in rows if r['ambiguous'])}/{sum(r['ambiguous'] for r in rows)}",
            "생성 모델별": grp(lambda r: r["gen"]), "유형별": grp(lambda r: r["hard"] or ["(일반)"]),
            "요소별 오답": {k: sum(1 for r in main_rows if r["cells"]["요소"].get(k) is False) for k in ("동네", "지표", "업종", "조건", "기간", "순위")},
            "지연 중앙값": statistics.median(secs) if secs else None, "지연 90%": sorted(secs)[int(len(secs) * 0.9)] if secs else None,
            "모델 판단 평균 횟수": round(statistics.mean(r["calls"] for r in rows), 2) if rows else 0}
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if out:
        out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
