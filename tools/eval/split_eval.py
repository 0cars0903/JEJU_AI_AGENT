"""여러 단계 질문 나누기 판정(LLM 없이 코드 + 분류기): data/eval/split_eval_150.jsonl(a 여러 단계 100·b 기법 + 일반 50)
+ 하나짜리 질문 대조 50(test_std150d에서 seed 0으로 고름).

사용: python tools/eval/split_eval.py [--off]   (--off: 나누기를 끈 비교)
판정: a는 답을 받은 일반 조각 수 ≥ 정답 하위 질문 수, b는 기법 조각 ≥1과 일반 조각 ≥ (하위 질문 수 − 1),
대조는 나누지 않고 일반 경로 핵심 칸이 맞음. Claude 키는 쓰지 않는다(ANTHROPIC_API_KEY를 지움).
"""
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["JEJU_SPLIT"] = "0" if "--off" in sys.argv else "1"
import m1  # noqa: E402
import result as R  # noqa: E402
import x1_eval as X  # noqa: E402

M = m1.M1()
multi = [json.loads(l) for l in (ROOT / "data/eval/split_eval_150.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
pool = [json.loads(l) for l in (ROOT / "data/x1/test_std150d_gold.jsonl").read_text(encoding="utf-8").splitlines()]
single = random.Random(0).sample(pool, 50)


def judge(g, o):
    ag = o.get("agent") if o.get("status") == "Agent" else None
    if "parts" not in g:
        return ag is None and bool(X.score(o.get("tuple") or {}, g)["core"])
    if not ag or ag.get("status") != "성공":
        return False
    tr = [t for t in ag.get("trace") or [] if t.get("ok")]
    n_topic = sum(t["tool"] == "answer_topic" for t in tr)
    n_tech = sum(t["tool"] == "run_technique" for t in tr)
    if g["group"] == "a":
        return n_topic >= len(g["parts"])
    return n_tech >= 1 and n_topic >= len(g["parts"]) - 1


res = {"a": 0, "b": 0, "대조": 0}
for g in multi + single:
    o = R.respond(g["q"], {"agent_ok": False}, llm_on=False, interpret=M.interpret)
    res[g.get("group") or "대조"] += judge(g, o)
print(json.dumps({"나누기": "끔" if "--off" in sys.argv else "켬", "a(100)": res["a"], "b(50)": res["b"], "대조(50)": res["대조"]}, ensure_ascii=False))
