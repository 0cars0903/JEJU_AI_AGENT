"""여러 단계·기법 + 일반 질문(Agent 문항)의 단계 처리 측정(2026-11-16).

사용: python tools/eval/agent_steps_eval.py --file 문항.jsonl --mode step|loop [--out 결과.json]
- 문항: 조정용 interaction/gemini_work/047/route_test_100.jsonl, 판정용 data/eval/route_eval_200.jsonl. group a(여러 단계)·b(기법 + 일반)만 쓴다.
- step: 서비스 경로의 단계형 Agent(app/step_agent.serve). loop: 옛 도구 루프(app/expert.ask, mode=escalate, 로컬 모델).
- 채점: 정답 단계(parts)마다, 성공한 도구 호출 가운데 도구 종류·동네·지표 묶음이 맞는 것이 하나라도 있으면 그 단계를 처리한 것으로 본다.
  모든 단계를 처리한 문항만 '성공'이다. 호출 인자(단계형은 단계 답의 해석)를 보므로 답 내용까지 맞는지는 보지 않는다(후한 채점).
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
args = sys.argv[1:]
FILE = Path(args[args.index("--file") + 1])
MODE = args[args.index("--mode") + 1] if "--mode" in args else "step"
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else None

FAM = {"매출": {"매출", "매출성장", "이용건수", "건당금액", "시간대매출", "과거매출", "업종비교", "시장추이"}, "유동인구": {"일평균방문", "시간대방문", "시간대매출", "방문거주비", "청년비중", "고령비중", "방문연령구성"},
       "방문인구": {"일평균방문", "시간대방문", "방문거주비"}, "생존율": {"5년생존율", "조건부생존", "폐업률"}, "폐업률": {"폐업률", "폐업수", "5년생존율"}, "개업수": {"개업수"},
       "점포수": {"점포수", "특화계수"}, "특화계수": {"특화계수", "점포수"}, "인구비중": {"고령비중", "청년비중", "거주연령구성", "방문연령구성"}, "버스이용": {"버스일평균", "정류소일이용"},
       "매출변화": {"매출", "매출성장"}}
PLACEHOLDER = {"선정동", "유사동", "선정업종"}


def covered(part, calls):
    sp = set(part.get("space") or []) - PLACEHOLDER
    ms = part.get("metric_ok") or []
    fam = set().union(*[FAM.get(m, set()) for m in ms]) if any(m in FAM for m in ms) else None
    for tool, a in calls:
        if part.get("type") == "기법분석":
            if tool == "run_technique":
                return True
            continue
        if tool != "answer_topic" and part.get("type") not in ("T15", "T7"):
            continue
        if sp and not (sp & set(a.get("space") or a.get("dongs") or [])):
            continue
        if part.get("type") in ("T8", "T9") and tool == "answer_topic" and a.get("type") != part["type"]:
            continue
        if fam and tool == "answer_topic" and a.get("type") not in ("T10", "T9", "T8") and not (set(a.get("metric") or []) & fam):
            continue
        return True
    return False


def run_step(q):
    import step_agent
    x = step_agent.serve(q, {}, llm_on=False)
    calls = []
    if x.get("status") == "Agent":
        for tp in (x.get("agent") or {}).get("topics") or []:
            calls.append(("answer_topic", tp.get("tuple") or {}))
        for t in (x.get("agent") or {}).get("trace") or []:
            if t.get("tool") == "run_technique" and t.get("ok"):
                calls.append(("run_technique", {}))
    elif (x.get("card") or {}).get("evidence"):
        calls.append(("answer_topic", x.get("tuple") or {}))
    return x, calls


def run_loop(q):
    import expert
    x = expert.ask(q, mode="escalate")
    calls = []
    for t in x.get("trace") or []:
        if t.get("ok") and t.get("tool") in ("answer_topic", "run_technique"):
            try:
                calls.append((t["tool"], json.loads(t.get("args") or "{}")))
            except ValueError:
                calls.append((t["tool"], {}))
    return x, calls


def main():
    if MODE == "loop":
        os.environ["JEJU_ANALYST"] = "0"
    items = [json.loads(x) for x in FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    items = [r for r in items if r.get("group") in ("a", "b")]
    rows = []
    for r in items:
        t0 = time.perf_counter()
        x, calls = (run_loop if MODE == "loop" else run_step)(r["q"])
        cov = [covered(p, calls) for p in r.get("parts") or []]
        row = {"id": r["id"], "group": r["group"], "done": sum(cov), "parts": len(cov), "ok": all(cov), "status": x.get("status"), "sec": round(time.perf_counter() - t0, 1)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summ = {"file": FILE.name, "mode": MODE}
    for g in ("a", "b"):
        gs = [x for x in rows if x["group"] == g]
        summ[f"{g} 모든 단계 처리"] = f"{sum(x['ok'] for x in gs)}/{len(gs)}"
    summ["전체"] = f"{sum(x['ok'] for x in rows)}/{len(rows)}"
    summ["처리한 단계"] = f"{sum(x['done'] for x in rows)}/{sum(x['parts'] for x in rows)}"
    secs = sorted(x["sec"] for x in rows)
    summ["지연 중앙값"] = secs[len(secs) // 2] if secs else None
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if OUT:
        OUT.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
