"""질문 해석(M1) 판정: 판정용 300문항(data/x1/test_std150·test_std150d)의 핵심 칸(종류·답할지·동네·업종) 정답 수.

사용: python tools/eval/m1_eval.py [--rule | --rag]   (--rule: 임베딩 없이 사전 규칙만, --rag: 질문 기록 대조 켬)
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
    M = m1.M1(rag_on="--rag" in sys.argv)  # --rag: 질문 기록 찾기(RAG) 켬(서비스 기본은 끔)
    res = [M.interpret(g["q"]) for g in gold]
    got = [r["tuple"] for r in res]
ok = sum(X.score(t, g)["core"] for t, g in zip(got, gold))
out = {"경로": "사전 규칙" if "--rule" in sys.argv else "임베딩 분류기" + (" + 질문 기록(RAG)" if "--rag" in sys.argv else ""), "n": len(gold), "핵심 정답": ok}
if "--rag" in sys.argv:  # 기록과 어긋난 문항: 모델이 바꾼 것이 맞게·틀리게 바뀌었는지
    fire = [(r, t, g) for r, t, g in zip(res, got, gold) if (r.get("rag") or {}).get("differ")]
    ch = [(r, t, g) for r, t, g in fire if r["rag"].get("chosen") and r["rag"]["chosen"] != r["rag"]["first"]]
    good = sum(X.score(t, g)["core"] and not X.score(dict(t, type=r["rag"]["first"]), g)["core"] for r, t, g in ch)
    bad = sum(not X.score(t, g)["core"] and X.score(dict(t, type=r["rag"]["first"]), g)["core"] for r, t, g in ch)
    out.update({"기록과 어긋남": len(fire), "모델이 바꿈": len(ch), "맞게 바뀜": good, "틀리게 바뀜": bad,
                "어긋남 문항": [{"q": g["q"], "정답": g.get("type"), "처음": r["rag"]["first"], "기록": r["rag"]["vote"], "모델": r["rag"].get("chosen")} for r, t, g in fire]})
print(json.dumps(out, ensure_ascii=False))
