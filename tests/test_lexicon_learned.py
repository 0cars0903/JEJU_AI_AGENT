"""동네·업종 낱말 사전 보강(tools/lexicon_candidates.py)과 '답할지' 기록 변환(tools/feedback_to_train.py), 2026-11-15."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import lexicon_candidates as L  # noqa: E402


class Candidates(unittest.TestCase):
    def test_unknown_word_from_correction(self):
        rec = {"kind": "고침", "question": "도두동 카페 말고 해물라면 파는 집 몇 곳?", "before": {"space": ["도두동"], "target": "카페"},
               "slots": {"space": ["도두동"], "target": "분식"}}
        rows = L.candidates([rec])
        got = {(r["낱말"], r["종류"], r["값"]): r["추천"] for r in rows}
        self.assertEqual(got.get(("해물라면", "업종", "분식")), "O")
        self.assertNotIn(("카페", "업종", "분식"), got)  # 이미 아는 낱말은 후보가 아니다
        self.assertFalse(any(w in ("몇", "곳") for w, _, _ in got))

    def test_confirm_records_ignored(self):
        self.assertEqual(L.candidates([{"kind": "확인", "question": "해물라면집 몇 곳", "slots": {"target": "분식"}}]), [])

    def test_apply_only_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "learned.json"
            n = L.apply([{"채택": "O", "낱말": "해물라면", "종류": "업종", "값": "분식"}, {"채택": "", "낱말": "보쌈", "종류": "업종", "값": "한식"},
                         {"채택": "O", "낱말": "누웨마루", "종류": "동네", "값": "연동"}, {"채택": "O", "낱말": "엉뚱", "종류": "동네", "값": "서울"}], p)
            self.assertEqual(n, 2)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"places": {"누웨마루": "연동"}, "targets": {"해물라면": "분식"}})


class LearnedLoaded(unittest.TestCase):
    def test_qparse_reads_learned(self):  # 해석기는 시작할 때 learned.json을 읽는다(파일을 지우면 원래대로)
        f = ROOT / "data" / "lexicon" / "learned.json"
        if f.exists():
            self.skipTest("이미 채택한 사전이 있음")
        code = "import sys; sys.path.insert(0,'app'); import qparse; print(qparse.parse('노형동 해물라면집 몇 곳')['target'])"
        try:
            f.write_text(json.dumps({"places": {}, "targets": {"해물라면": "분식"}}), encoding="utf-8")
            on = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        finally:
            f.unlink()
        off = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        self.assertEqual(on, "분식")
        self.assertNotEqual(off, "분식")


class ExpectFeedback(unittest.TestCase):
    def test_expect_rows(self):
        import feedback_to_train as F
        recs = [{"kind": "확인", "question": "서울 강남 카페 매출", "expect": "범위밖"},
                {"kind": "고침", "question": "미용실 창업 대출 알려줘", "expect": "답함"},
                {"kind": "확인", "question": "카페 몇 개야?", "expect": "되묻기", "slots": {"topic": "stores", "space": ["연동"], "target": "카페"}},
                {"kind": "확인", "question": "노형동 카페 몇 개야?", "expect": "되묻기", "slots": {"topic": "stores", "space": ["노형동"], "target": "카페"}}]
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "feedback.jsonl"
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
            out = ROOT / "data" / "x1" / "feedback_train.jsonl"
            keep = out.read_text(encoding="utf-8") if out.exists() else None
            try:
                F.main(str(src))
                rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
            finally:
                out.write_text(keep, encoding="utf-8") if keep is not None else out.unlink()
        got = {r["q"]: r["tuple"] for r in rows}
        self.assertEqual(got["서울 강남 카페 매출"], {"expect": "범위밖"})
        self.assertEqual(got["미용실 창업 대출 알려줘"], {"expect": "답함"})
        self.assertEqual(got["카페 몇 개야?"], {"expect": "되묻기"})
        self.assertNotIn("노형동 카페 몇 개야?", got)  # 동네가 이미 있으면 되묻기가 맞았다고 볼 수 없다


class FeedbackApi(unittest.TestCase):
    def test_expect_validated(self):
        os.environ.setdefault("LLM_BACKEND", "rule")
        from fastapi.testclient import TestClient
        import api
        c = TestClient(api.app)
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(os.environ, {"JEJU_WRITE_DIR": d}):
            self.assertEqual(c.post("/api/feedback", json={"question": "서울 카페", "ok": True, "expect": "범위밖"}).status_code, 200)
            self.assertEqual(c.post("/api/feedback", json={"question": "서울 카페", "ok": True, "expect": "아무거나"}).status_code, 422)
            rec = json.loads((Path(d) / "feedback.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(rec["expect"], "범위밖")


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
