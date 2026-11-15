"""실험 X1·X2(2026-11-15): Claude 전용 판단(계획 선택·넘김 판정)을 로컬 소형 모델로 바꿀 수 있는지 잰다.

사용:
  python tools/eval/local_judge_eval.py plan  --split dev|judge --model qwen2.5:7b [--out 결과.json]
  python tools/eval/local_judge_eval.py route --split dev|judge --model qwen2.5:7b [--out 결과.json]
- plan: 조정용 std150b·c 300, 판정용 std150·std150d 300(질문 해석 판정과 같은 세트). 계획 선택이 필요한 문항(plan_agent.needed)만 모델에 묻는다.
  채점은 핵심 칸(종류·답할지·동네·업종, app/x1_eval.score). 'AGENT'(넘김)를 고른 문항은 종류 하나로 답하지 않으므로 틀림으로 센다(보수적).
- route: 조정용 047 100(interaction/gemini_work/047), 판정용 048 200(data/eval/route_eval_200.jsonl). 일반 경로 처리(규칙 백엔드)를 본 뒤 넘길지 묻는다.
- 문항마다 선택지 확률을 남긴다. 확신도 조건(1·2위 확률 차가 기준값 이상일 때만 받아들임)은 이 기록으로 나중에 계산한다(모델마다 한 번만 실행).
- Claude 결정 저장 파일(plan_cache)은 쓰지 않는다.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
args = sys.argv[1:]
task = args[0]
split = args[args.index("--split") + 1] if "--split" in args else "dev"
model = args[args.index("--model") + 1] if "--model" in args else "qwen2.5:7b"
out = Path(args[args.index("--out") + 1]) if "--out" in args else ROOT / "data" / "eval" / f"result_local_{task}_{split}_{model.replace(':', '-')}.json"

import m1  # noqa: E402
import plan_agent as P  # noqa: E402

M = m1.M1()


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def margin(probs):
    v = sorted((x for x in probs.values() if x is not None), reverse=True) + [0.0, 0.0]
    return round(v[0] - v[1], 4)


rows = []
if task == "plan":
    import verify
    import x1_eval as X
    names = ["test_std150b", "test_std150c"] if split == "dev" else ["test_std150", "test_std150d"]
    gold = [g for n in names for g in jl(ROOT / "data" / "x1" / f"{n}_gold.jsonl")]
    for i, g in enumerate(gold):
        it = M.interpret(g["q"])
        t = it["tuple"]
        base = bool(X.score(t, g)["core"])
        row = {"i": i, "base": base, "asked": False}
        if P.needed(it, g["q"]):
            t0 = time.perf_counter()
            pick, probs = P.local_plan(g["q"], it, model)
            row.update(asked=True, pick=pick, probs=probs, margin=margin(probs) if probs else None, sec=round(time.perf_counter() - t0, 2))
            if pick == "AGENT":
                row["new"] = False
            elif pick in P.CHOICES:
                t2 = dict(t, type=pick)
                row["new"] = base if verify.check_tuple(t2) else bool(X.score(t2, g)["core"])  # 검수 규칙에 걸리면 분류기 결과 유지(서비스와 같음)
            else:
                row["new"] = base
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    asked = [r for r in rows if r["asked"]]
    summ = {"분류기 핵심 정답": sum(r["base"] for r in rows), "모델 그대로 받음": sum(r.get("new", r["base"]) for r in rows),
            "모델에 물음": len(asked), "고침": sum(r["new"] and not r["base"] for r in asked), "망침": sum(r["base"] and not r["new"] for r in asked),
            "AGENT 고름": sum(r.get("pick") == "AGENT" for r in asked)}
    for th in (0.5, 0.7, 0.8, 0.9, 0.95):  # 확신도 조건: 확률 차가 th 이상일 때만 받아들임
        acc = [r for r in asked if r.get("margin") is not None and r["margin"] >= th]
        summ[f"확률 차 {th} 이상만"] = {"받아들임": len(acc), "고침": sum(r["new"] and not r["base"] for r in acc), "망침": sum(r["base"] and not r["new"] for r in acc),
                                    "핵심 정답": sum(r["base"] for r in rows) + sum(r["new"] and not r["base"] for r in acc) - sum(r["base"] and not r["new"] for r in acc)}
else:
    import result
    os.environ.setdefault("LLM_BACKEND", "rule")
    items = jl(ROOT / "interaction" / "gemini_work" / "047" / "route_test_100.jsonl") if split == "dev" else jl(ROOT / "data" / "eval" / "route_eval_200.jsonl")
    for i, g in enumerate(items):
        it = M.interpret(g["q"])
        r = result.respond(g["q"], {}, llm_on=False, interpret=lambda q, _it=it: _it)
        said = (r.get("choose") or {}).get("message") or (r.get("card") or {}).get("conclusion")
        t0 = time.perf_counter()
        esc, probs = P.local_route(g["q"], it, r.get("status"), model, said)
        gold_esc = g["route"] == "Agent"
        row = {"i": i, "gold": g["route"], "esc": esc, "p_agent": probs.get("Agent"), "margin": margin(probs) if probs.get("Agent") is not None else None,
               "ok": esc == gold_esc, "sec": round(time.perf_counter() - t0, 2)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    gen = [r for r in rows if r["gold"] == "일반"]
    ag = [r for r in rows if r["gold"] == "Agent"]
    summ = {"정답": sum(r["ok"] for r in rows), "n": len(rows), "Agent 문항 넘김": f"{sum(bool(r['esc']) for r in ag)}/{len(ag)}",
            "일반 문항 잘못 넘김": f"{sum(bool(r['esc']) for r in gen)}/{len(gen)}"}
    for th in (0.5, 0.7, 0.9, 0.95, 0.99):  # 넘김 확률이 th 이상일 때만 넘김
        e = [bool(r["p_agent"] is not None and r["p_agent"] >= th) for r in rows]
        summ[f"넘김 확률 {th} 이상만"] = {"정답": sum(x == (r["gold"] == "Agent") for x, r in zip(e, rows)),
                                    "Agent 넘김": sum(x for x, r in zip(e, rows) if r["gold"] == "Agent"), "일반 잘못 넘김": sum(x for x, r in zip(e, rows) if r["gold"] == "일반")}
summ.update(task=task, split=split, model=model, 지연_중앙값=sorted(r["sec"] for r in rows if r.get("sec") is not None)[len([r for r in rows if r.get("sec") is not None]) // 2] if any(r.get("sec") is not None for r in rows) else None)
out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(summ, ensure_ascii=False))
