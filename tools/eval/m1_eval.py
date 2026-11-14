"""질문 해석(M1) 판정: 판정용 300문항(data/x1/test_std150·test_std150d)의 핵심 칸(종류·답할지·동네·업종) 정답 수.

사용: python tools/eval/m1_eval.py [--rule]   (--rule: 임베딩 없이 사전 규칙만)
로컬 Ollama에 bge-m3가 있어야 임베딩 경로를 잰다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import qparse  # noqa: E402
import x1_eval as X  # noqa: E402

gold = [json.loads(l) for n in ["test_std150", "test_std150d"] for l in (ROOT / "data" / "x1" / f"{n}_gold.jsonl").read_text(encoding="utf-8").splitlines()]
if "--rule" in sys.argv:
    got = [qparse.parse(g["q"]) for g in gold]
else:
    import m1
    M = m1.M1()
    got = [M.interpret(g["q"])["tuple"] for g in gold]
ok = sum(X.score(t, g)["core"] for t, g in zip(got, gold))
print(json.dumps({"경로": "사전 규칙" if "--rule" in sys.argv else "임베딩 분류기", "n": len(gold), "핵심 정답": ok}, ensure_ascii=False))
