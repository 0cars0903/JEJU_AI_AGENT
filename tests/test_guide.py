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
            if "target" in tp.get("need", []):
                s["target"] = tp["options"]["target"][0]
            if tp["id"] == "rank":
                s["metric"] = "점포수"
            r = run(s)
            if tp.get("center_only"):  # 센터 전용 주제는 센터 밖에서 차단하고 대신 볼 질문을 준다
                self.assertEqual(r["status"], "범위밖", s)
                self.assertEqual(len(r["suggestions"]), 2, s)
                continue
            self.assertIn(r["status"], OK, s)
            self.assertEqual(r["understood"]["by"], "버튼 선택", s)
            self.assertNotIn("choose", r, s)

    def test_representative_and_suggestions_answer(self):
        for x in G.representative():
            if x["slots"]["topic"] == "technique":  # 기법 분석은 /api/ask가 techniques로 보낸다(tests/test_techniques.py)
                continue
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

    def test_missing_messages(self):  # C: 빠진 칸마다 알맞은 안내
        self.assertEqual(run({"topic": "compare", "space": ["노형동"]})["choose"]["message"], "비교할 동네를 하나 더 골라 주세요.")
        self.assertEqual(run({"topic": "rank"})["choose"]["message"], "순위 기준을 골라 주세요.")
        self.assertEqual(run({"topic": "stores"})["choose"]["message"], "동네를 골라 주세요.")

    def test_visit_age_variant(self):  # E: 사는 사람 연령대
        r = run({"topic": "visit", "space": ["노형동"], "variant": "age"})
        self.assertIn(r["status"], OK)
        self.assertIn("연령대", r["card"]["evidence"][0]["text"])

    def test_bad_values_rejected(self):
        for s in [{"topic": "없는주제"}, {"topic": "stores", "space": ["없는동"]}, {"topic": "stores", "space": ["노형동"], "target": "어르신"},
                  {"topic": "rank", "metric": "조건부생존"}, {"topic": "rank", "metric": "점포수", "order": "옆"}]:
            with self.assertRaises(ValueError, msg=str(s)):
                G.to_tuple(s)

    def test_rank_sorted_desc(self):
        ev = run({"topic": "rank", "metric": "점포수"})["card"]["evidence"]
        vals = [e["value"] for e in ev if "value" in e]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_slots_round_trip(self):
        for s in [{"topic": "stores", "space": ["노형동"], "target": "카페"}, {"topic": "openclose", "space": ["아라동"], "target": "카페", "variant": "survival"},
                  {"topic": "visit", "space": ["노형동"], "variant": "age"},
                  {"topic": "rank", "metric": "매출", "target": "숙박"}, {"topic": "sales", "space": ["노형동"], "target": "카페", "variant": "unit"},
                  {"topic": "sales", "space": ["연동"], "target": "음식점"}, {"topic": "customers", "space": ["성산읍"], "target": "숙박"},
                  {"topic": "hourly", "space": ["애월읍"], "target": "음식점"}]:
            self.assertEqual(G.to_slots(G.to_tuple(s)), s)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(api.app, raise_server_exceptions=False)

    def test_groups_cover_every_topic_once(self):
        """문서 21 6.2절 3단계: 주제 14개가 빠짐없이 한 묶음에만 들어가고, 첫 단계 선택지는 6개 이하."""
        g = self.c.get("/api/guide").json()
        ids = [t["id"] for t in g["topics"]]
        grouped = [t for gr in g["groups"] for t in gr["topics"]]
        self.assertEqual(sorted(grouped), sorted(ids))
        self.assertEqual(len(grouped), len(set(grouped)))
        self.assertLessEqual(len(g["groups"]), 6)
        self.assertEqual([gr["label"] for gr in g["groups"]], ["가게", "손님·매출", "비교·순위", "진단·예상"])

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
        bad = self.c.post("/api/ask", json={"question": "가" * 201})  # F: 형식 오류도 detail은 문자열
        self.assertEqual(bad.status_code, 422)
        self.assertIsInstance(bad.json()["detail"], str)


if __name__ == "__main__":
    unittest.main()
