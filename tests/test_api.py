"""API 시험: 화면이 쓰는 경로가 도구 수치를 그대로 전달하는지, 잘못된 입력을 안내하는지 본다. 실행: .venv/bin/python -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("LLM_BACKEND", "rule")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import tools as tl  # noqa: E402


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(api.app, raise_server_exceptions=False)

    def test_meta(self):
        m = self.c.get("/api/meta").json()
        self.assertEqual(len(m["dongs"]), 43)
        self.assertEqual(len(m["jeju_survival"]), 5)

    def test_map_values_match_tools(self):
        d = self.c.get("/api/map").json()
        self.assertEqual(len(d["dongs"]), 43)
        row = next(x for x in d["dongs"] if x["dong"] == "노형동")
        self.assertEqual(row["values"]["점포수"], int(tl._metric("점포수")["노형동"]))

    def test_dong_values_match_tools(self):
        d = self.c.get("/api/dong/노형동").json()
        self.assertEqual(d["profile"]["summary"], tl.dong_profile("노형동")["summary"])
        self.assertEqual(d["biz"]["values"]["restaurant_years"][0]["year"], 2019)

    def test_category(self):
        d = self.c.get("/api/dong/애월읍", params={"category": "카페"}).json()
        self.assertEqual(d["category_biz"]["values"]["stores"], tl.biz_diagnostic("애월읍", "카페")["values"]["stores"])

    def test_unknown_inputs(self):
        self.assertEqual(self.c.get("/api/dong/없는동").status_code, 404)
        self.assertEqual(self.c.get("/api/dong/노형동", params={"category": "없는업종"}).status_code, 404)
        self.assertEqual(self.c.get("/api/compare", params={"dongs": ["아라동"]}).status_code, 422)
        self.assertEqual(self.c.get("/api/compare", params={"dongs": ["아라동", "연동", "노형동", "애월읍", "한림읍"]}).status_code, 422)
        self.assertEqual(self.c.post("/api/ask", json={"question": ""}).status_code, 422)
        self.assertEqual(self.c.post("/api/ask", json={"question": "가" * 201}).status_code, 422)
        self.assertEqual(self.c.post("/api/ask", json={"question": "   "}).status_code, 422)

    def test_compare_table(self):
        d = self.c.get("/api/compare", params={"dongs": ["아라동", "이도2동"]}).json()
        row = next(x for x in d["rows"] if x["label"] == "점포 수(곳)")
        self.assertEqual(row["values"]["아라동"], f"{tl.dong_profile('아라동')['values']['stores']:,}")

    def test_follow_up_carries_dong_and_says_so(self):
        r = self.c.post("/api/ask", json={"question": "버스는 어때?", "context_dongs": ["노형동"]}).json()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["carried_dongs"], ["노형동"])
        self.assertEqual(r["question"], "버스는 어때?")

    def test_follow_up_does_not_override(self):
        cases = {"연동 버스는 어때?": "ok", "비슷한 동네와 비교해 줘": "clarify", "내일 매출은?": "out_of_scope"}
        for q, status in cases.items():
            r = self.c.post("/api/ask", json={"question": q, "context_dongs": ["노형동"]}).json()
            self.assertEqual(r["status"], status, q)
            self.assertEqual(r["carried_dongs"], [], q)

    def test_follow_up_compare_adds_context(self):
        r = self.c.post("/api/ask", json={"question": "이도2동과 비교해 줘", "context_dongs": ["아라동"]}).json()
        self.assertEqual(r["carried_dongs"], ["아라동"])
        self.assertEqual(sorted(t["dong"] for t in r["tool_results"]), ["아라동", "이도2동"])

    def test_follow_up_other_place_not_carried(self):
        for q in ["다른 동네는 어때?", "주변 동네는?", "제주 전체 통계는?"]:
            r = self.c.post("/api/ask", json={"question": q, "context_dongs": ["노형동"]}).json()
            self.assertEqual((r["status"], r["carried_dongs"]), ("clarify", []), q)

    def test_follow_up_rank(self):
        two = self.c.post("/api/ask", json={"question": "카페는 어디가 더 많아?", "context_dongs": ["아라동", "이도2동"]}).json()
        self.assertEqual(sorted(t["dong"] for t in two["tool_results"]), ["아라동", "이도2동"])
        one = self.c.post("/api/ask", json={"question": "카페는 어디가 더 많아?", "context_dongs": ["아라동"]}).json()
        self.assertEqual(one["carried_dongs"], [])
        self.assertEqual(one["tool_results"][0]["tool"], "compare_rank")

    def test_unknown_context_ignored(self):
        r = self.c.post("/api/ask", json={"question": "버스는 어때?", "context_dongs": ["없는동"]}).json()
        self.assertEqual(r["status"], "clarify")

    def test_case_flow_status(self):
        for q, status in {"애월읍에 카페가 많은 편이야?": "ok", "서귀동 상권 어때?": "clarify", "내일 동문시장 매출 얼마나 나올까?": "out_of_scope"}.items():
            self.assertEqual(self.c.post("/api/ask", json={"question": q}).json()["status"], status)


if __name__ == "__main__":
    unittest.main()
