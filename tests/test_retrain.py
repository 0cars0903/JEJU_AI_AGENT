"""질문 해석 분류기 재학습(tools/retrain.py, 2026-11-15): 판정 점수가 같거나 높을 때만 새 모델로 바꾸고, 낮으면 그대로 둔다.
Ollama 없이 돌도록 임베딩·학습·채점을 가짜로 바꾼다. 실제 확인(Mac): 색인 벡터만으로 재학습 248 → 248, 틀린 피드백 300건 248 → 235(바꾸지 않음)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import retrain as R  # noqa: E402


class Retrain(unittest.TestCase):
    def run_main(self, old, new):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            model = d / "m1_intent.json"
            model.write_text(json.dumps({"tag": "old"}), encoding="utf-8")
            scores = iter([(old, 300), (new, 300)])
            with mock.patch.object(R.m1, "MODEL", model), mock.patch.object(R, "CAND", d / "cand.json"), \
                    mock.patch.object(R, "PREV", d / "prev.json"), mock.patch.object(R, "LOG", d / "log.jsonl"), \
                    mock.patch.object(R, "feedback_rows", return_value=[("노형동 카페 몇 개야?", "T1", "답함")]), \
                    mock.patch.object(R, "build", return_value={"tag": "new"}), \
                    mock.patch.object(R, "score", side_effect=lambda p, v: next(scores)), \
                    mock.patch.object(R.m1.M1, "_embed", lambda self, q: [0.0]), \
                    mock.patch("feedback_to_train.main", return_value=0), mock.patch("envfile.load", return_value=[]), \
                    mock.patch("lexicon_candidates.main", return_value=0):
                self.assertEqual(R.main(), 0)
            log = json.loads((d / "log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            return json.loads(model.read_text(encoding="utf-8"))["tag"], (d / "prev.json").exists(), (d / "cand.json").exists(), log

    def test_keep_when_same_or_higher(self):
        tag, prev, cand, log = self.run_main(248, 249)
        self.assertEqual((tag, prev, cand, log["kept"]), ("new", True, False, True))

    def test_rollback_when_lower(self):
        tag, prev, cand, log = self.run_main(248, 235)
        self.assertEqual((tag, prev, cand, log["kept"]), ("old", False, False, False))

    def test_decide(self):
        self.assertTrue(R.decide(248, 248))
        self.assertFalse(R.decide(248, 247))


if __name__ == "__main__":
    unittest.main()
