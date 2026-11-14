"""검수·재실행 라인 5단계(재학습): 사람이 확인([맞아요])하거나 고친([조건 바꾸기]) 해석 기록을 분류기 학습 자료로 바꾼다.

실행: .venv/bin/python tools/feedback_to_train.py [기록 파일] → data/x1/feedback_train.jsonl
- 기록: /api/feedback이 쌓은 data/interim/feedback.jsonl(또는 JEJU_WRITE_DIR/feedback.jsonl). 질문 문장과 버튼 값만 있다.
- '답할지' 기록(expect, 2026-11-15): 범위 밖 안내의 [맞아요]→범위밖, [답할 수 있는 질문이에요]→답함(종류 없음), 되묻기 뒤 조건 고름→되묻기(질문에 동네가 있으면 뺌).
- 같은 질문이 여러 번이면 마지막 기록을 쓴다(고침이 확인보다 뒤면 고침).
- 시험 세트(data/x1/test_*_gold.jsonl)와 같은 문장은 넣지 않는다(평가 오염 방지).
- 재학습: x1_embed.training_rows가 feedback_train.jsonl을 읽게 한 뒤 .venv/bin/python -c "import sys; sys.path.insert(0,'app'); import m1; print(m1.train_and_save())"
  재학습 전후로 app/x1_eval.py로 평가용 세트 점수를 비교하고, 떨어지면 되돌린다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import guide as G  # noqa: E402


def slots_ok(r):
    try:
        G.to_tuple(r.get("slots") or {})
        return bool(r.get("slots"))
    except Exception:
        return False


def main(src=None):
    import os
    src = Path(src or (Path(os.environ["JEJU_WRITE_DIR"]) if os.environ.get("JEJU_WRITE_DIR") else ROOT / "data" / "interim") / "feedback.jsonl")  # 서버(api._log_feedback)와 같은 곳
    if not src.exists():
        print(f"기록 없음: {src}")
        return 0
    test = {json.loads(l)["q"] for f in (ROOT / "data" / "x1").glob("test_*_gold.jsonl") for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}
    last = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        q, slots = (r.get("question") or "").strip(), r.get("slots")
        if q and (slots or r.get("expect")) and q not in test:
            last[q] = r
    import qparse
    rows = []
    for q, r in last.items():
        e = r.get("expect")
        if e in ("범위밖", "답함") and not (e == "답함" and slots_ok(r)):  # 범위 밖 안내 확인: '답할지'만 알려 준 기록(종류 없음)
            rows.append({"q": q, "tuple": {"expect": e}, "src": f"feedback:답할지:{e}:{r.get('at')}"})
            continue
        if e == "되묻기":  # 되묻기 뒤 조건을 고름. 질문에 동네가 이미 있었으면 되묻기가 맞았다고 볼 수 없어 뺀다
            if not qparse.parse(q)["space"]:
                rows.append({"q": q, "tuple": {"expect": "되묻기"}, "src": f"feedback:답할지:되묻기:{r.get('at')}"})
            continue
        try:
            t = G.to_tuple(r["slots"])
        except Exception:  # 버튼 값이 지금 구조와 맞지 않으면 건너뛴다
            continue
        rows.append({"q": q, "tuple": {**t, "expect": "답함"}, "src": f"feedback:{r.get('kind')}:{r.get('at')}"})
    out = ROOT / "data" / "x1" / "feedback_train.jsonl"
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    print(f"{out}: {len(rows)}문항(확인 {sum('확인' in x['src'] for x in rows)}, 고침 {sum('고침' in x['src'] for x in rows)}, 답할지만 {sum('답할지' in x['src'] for x in rows)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
