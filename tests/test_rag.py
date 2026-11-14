"""질문 기록 찾기(app/rag.py, 2026-11-15): 색인이 판정 문항을 담지 않는지, 투표·어긋남 판정이 기준값대로 도는지(모델·Ollama 없이)."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import rag  # noqa: E402


@unittest.skipUnless(rag.INDEX.exists(), "models/rag_index.npz 없음")
class Rag(unittest.TestCase):
    def test_no_judge_items_in_library(self):
        meta = json.loads(rag.ROWS.read_text(encoding="utf-8"))
        judge = set()
        for p in [ROOT / "data" / "eval" / n for n in ("route_eval_200.jsonl", "split_eval_150.jsonl", "tech_route_eval_120.jsonl")] + \
                 [ROOT / "data" / "x1" / n for n in ("test_std150_gold.jsonl", "test_std150d_gold.jsonl")]:
            judge |= {rag.norm(json.loads(l)["q"]) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}
        for name, lib in meta["libs"].items():
            self.assertEqual(len({rag.norm(q) for q in lib["q"]} & judge), 0, name)

    def test_self_lookup_agrees(self):
        lib = rag.load()["tech"]
        v = lib["vec"][0]
        chk = rag.check(v, lib["label"][0], "tech")
        self.assertTrue(chk["used"])
        self.assertFalse(chk["differ"])  # 자기 문장(유사도 1)이 이웃에 있으면 어긋나지 않는다

    def test_vote_threshold(self):
        nb = [("a", "corr", 0.9), ("b", "dist", 0.5), ("c", "corr", 0.85)]
        top, share, best = rag.vote(nb, 0.6)
        self.assertEqual(top, "corr")
        self.assertEqual(share, 1.0)
        self.assertIsNone(rag.vote(nb, 0.95)[0])


if __name__ == "__main__":
    unittest.main()
