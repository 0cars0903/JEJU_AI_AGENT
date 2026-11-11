"""질문 유도 시험(2026-11-11 17:25 사용자 결정): 버튼 값(slots)은 해석 없이 답하고, 빠진 칸은 선택필요로 넘기며, 잘못된 값은 거절한다.
실행: .venv/bin/python -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("LLM_BACKEND", "rule")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import guide as G  # noqa: E402
import result as R  # noqa: E402

OK = ("성공", "no_significant_effect")  # '효과 없음'도 정상 답이다


def run(slots):
    return R.respond(None, {"center_db": False}, llm_on=False, slots=slots)


class Slots(unittest.TestCase):
    def test_each_topic_answers(self):
        for tp in G.TOPICS:
            s = {"topic": tp["id"]}
            if "space" in tp.get("need", []):
                s["space"] = ["노형동", "연동"] if tp.get("min_space") == 2 else ["노형동"]
            if tp["id"] == "rank":
                s["metric"] = "점포수"
            if tp["id"] == "catalog":
                s["keyword"] = "버스"
            r = run(s)
            self.assertIn(r["status"], OK, s)
            self.assertEqual(r["understood"]["by"], "버튼 선택", s)
            self.assertNotIn("choose", r, s)

    def test_representative_and_suggestions_answer(self):
        for x in G.representative():
            r = run(x["slots"])
            self.assertIn(r["status"], OK, x)
            self.assertEqual(len(r["suggestions"]), 3)
        for x in run({"topic": "stores", "space": ["아라동"], "target": "카페"})["suggestions"]:
            self.assertIn(run(x["slots"])["status"], OK, x)

    def test_missing_slot_asks_choice(self):
        r = run({"topic": "stores"})
        self.assertEqual((r["status"], r["choose"]["step"]), ("선택필요", "space"))
        r = run({"topic": "compare", "space": ["노형동"]})
        self.assertEqual(r["choose"]["step"], "space")

    def test_bad_values_rejected(self):
        for s in [{"topic": "없는주제"}, {"topic": "stores", "space": ["없는동"]}, {"topic": "stores", "space": ["노형동"], "target": "어르신"},
                  {"topic": "rank", "metric": "폐업률"}]:
            with self.assertRaises(ValueError, msg=str(s)):
                G.to_tuple(s)

    def test_rank_sorted_desc(self):
        ev = run({"topic": "rank", "metric": "점포수"})["card"]["evidence"]
        vals = [e["value"] for e in ev if "value" in e]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_slots_round_trip(self):
        for s in [{"topic": "stores", "space": ["노형동"], "target": "카페"}, {"topic": "openclose", "space": ["아라동"], "target": "카페", "variant": "survival"},
                  {"topic": "rank", "metric": "버스일평균"}]:
            self.assertEqual(G.to_slots(G.to_tuple(s)), s)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(api.app, raise_server_exceptions=False)

    def test_guide(self):
        g = self.c.get("/api/guide").json()
        self.assertEqual(len(g["topics"]), len(G.TOPICS))
        self.assertEqual(len(g["dongs"]), 43)
        self.assertTrue(all("slots" in x and "text" in x for x in g["representative"]))

    def test_ask_with_slots(self):
        r = self.c.post("/api/ask", json={"slots": {"topic": "stores", "space": ["노형동"], "target": "카페"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "성공")
        self.assertEqual(self.c.post("/api/ask", json={"slots": {"topic": "stores", "space": ["없는동"]}}).status_code, 422)
        self.assertEqual(self.c.post("/api/ask", json={}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
