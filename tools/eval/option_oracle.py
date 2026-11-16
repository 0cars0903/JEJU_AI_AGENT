"""선택지 상한 측정(2026-11-16, 마스터 '진행'): 남은 오답이 '모델의 고르기' 탓인지 '코드가 만든 선택지·계산 경로' 탓인지 가른다.

사용: python tools/eval/option_oracle.py --ids 결과.json [--depth 2] [--out 결과.json]
- --ids: general_answer.py 결과 파일. 그 안의 오답(애매 제외) 문항만 본다(조정용 dev만 쓴다).
- 모델을 부르지 않는다. 질문 담당 Agent의 decide를 바꿔, 차례마다 코드가 만든 선택지를 하나씩 모두 골라 본다(최대 depth 차례, 그 뒤는 '지금 답 그대로').
- 문항마다 판정: 정답 경로 있음(어떤 선택지 순서로든 맞음) / 정답 경로 없음 / 처리 실패(첫 계산이 답을 못 냄 또는 선택지 자체가 없음).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "eval"))
args = sys.argv[1:]
ids_file = Path(args[args.index("--ids") + 1])
depth = int(args[args.index("--depth") + 1]) if "--depth" in args else 2
out = Path(args[args.index("--out") + 1]) if "--out" in args else None
sys.argv = [sys.argv[0], "--split", "dev"]  # general_answer의 인자 읽기가 이 스크립트 인자를 보지 않게 한다

import general_answer as GA  # noqa: E402
import question_agent as A  # noqa: E402

gold = {g["id"]: g for g in map(json.loads, filter(str.strip, (ROOT / "data" / "eval" / "general_answer_v2.jsonl").read_text(encoding="utf-8").splitlines()))
        if g.get("split") == "dev"}
wrong = [r["id"] for r in json.loads(ids_file.read_text(encoding="utf-8"))["rows"] if not r["ambiguous"] and not r["ok"]]

STATE = {"path": [], "seen": []}


def decide(q, r, it, gs, chat=None, done=(), prev=None):
    ops = A.options(q, r, it, gs, done, prev)
    t = len(STATE["seen"])
    STATE["seen"].append([o["text"] for o in ops])
    keep = next((o for o in ops if o["act"] == "답하기"), ops[0])
    if t < len(STATE["path"]):
        i = STATE["path"][t]
        return (ops[i] if i < len(ops) else keep), "선택지 상한 측정"
    return keep, "선택지 상한 측정"


A.decide = decide


def run(q, path):
    STATE.update(path=list(path), seen=[])
    try:
        r = A.run(q, {}, llm_on=False)
    except Exception as e:  # noqa: BLE001
        r = {"status": f"오류:{type(e).__name__}"}
    return r, STATE["seen"]


rows = []
for qid in wrong:
    g = gold[qid]
    r0, seen0 = run(g["q"], [])
    tried = []
    hit = None
    frontier = [[]]
    for d in range(depth):
        nxt = []
        for p in frontier:
            _, seen = run(g["q"], p) if p else (r0, seen0)
            if len(seen) <= len(p):  # 이 경로에서는 더 고를 차례가 없음
                continue
            for i, text in enumerate(seen[len(p)]):
                path = p + [i]
                r, s2 = run(g["q"], path)
                ok = GA.score(r, g)["정답"]
                tried.append({"path": [s2[k][j] if k < len(s2) and j < len(s2[k]) else j for k, j in enumerate(path)], "ok": ok, "status": r.get("status")})
                if ok and hit is None:
                    hit = tried[-1]["path"]
                nxt.append(path)
        frontier = nxt
    first_ok = r0.get("status") not in ("실패",) and not str(r0.get("status", "")).startswith("오류")
    verdict = "정답 경로 있음" if hit else ("처리 실패" if not seen0 or not first_ok else "정답 경로 없음")
    row = {"id": qid, "q": g["q"], "verdict": verdict, "hit": hit, "n_options_first": len(seen0[0]) if seen0 else 0,
           "first_options": seen0[0] if seen0 else [], "status0": r0.get("status"), "tuple0": {k: (r0.get("tuple") or {}).get(k) for k in ("type", "space", "metric", "target", "cond", "order", "ask_year", "ask_month", "ask_recent")},
           "tried": len(tried)}
    rows.append(row)
    print(json.dumps({k: row[k] for k in ("id", "verdict", "n_options_first", "tried")}, ensure_ascii=False), flush=True)

from collections import Counter  # noqa: E402
summ = {"문항": len(rows), "판정": dict(Counter(r["verdict"] for r in rows)), "depth": depth}
print(json.dumps(summ, ensure_ascii=False))
if out:
    out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
