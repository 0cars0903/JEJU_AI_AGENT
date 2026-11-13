"""(가) 기법 목록 7종(설계 11-1절, 2026-11-13): 기법 찾기, 계산, 거부 조건(이중 검토 039), API 연결."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ.setdefault("LLM_BACKEND", "rule")
import techniques as T  # noqa: E402


class Detect(unittest.TestCase):
    def test_finds_technique_only_when_named(self):
        self.assertEqual(T.detect("43개 동네 방문과 매출의 상관 분석해줘"), "corr")
        self.assertEqual(T.detect("동네를 4개 군집으로 나눠줘"), "cluster")
        self.assertEqual(T.detect("노형동 매출 시계열 분해해줘"), "decomp")
        self.assertEqual(T.detect("매출에 방문이 미치는 영향 회귀분석"), "regress")
        self.assertEqual(T.detect("노형동과 연동 매출 t검정"), "test")
        self.assertEqual(T.detect("음식점 매출 분포 보여줘"), "dist")
        self.assertEqual(T.detect("튀는 달 찾아줘"), "outlier")
        for q in ["노형동 카페 몇 개야?", "노형동과 비슷한 동네는?", "애월읍 음식점 몇 시에 손님이 많아?", "노형동 카페 차려도 될까?"]:
            self.assertIsNone(T.detect(q), q)


class Answers(unittest.TestCase):
    def test_all_seven_answer_with_warning_and_method(self):
        for k, q in T.EXAMPLES.items():
            r = T.answer(q)
            a = r["answer"]
            self.assertEqual(r["status"], "성공", q)
            self.assertNotEqual(a["conclusion"]["tag"], "계산하지 않음", q)
            self.assertTrue(a["views"], q)
            self.assertEqual(a["methods"][0]["kind"], f"tech_{k}")
            warn = [l for b in a["blocks"] for l in b["lines"] if l["tag"] == "주의"]
            self.assertTrue(warn or k == "dist", q)  # 분포는 쏠림이 클 때만 경고
            self.assertEqual(r["understood"]["slots"]["method"], k)

    def test_known_values(self):
        # 노형동 음식점 월 매출 계절지수: 전문가 모드(Claude 코드, 11/13)와 같은 값
        a = T.answer("노형동 음식점 월 매출 시계열 분해해줘")["answer"]
        self.assertIn("5월이 107.8%", a["conclusion"]["text"])
        self.assertIn("2월이 88.7%", a["conclusion"]["text"])

    def test_reject_conditions(self):
        for q, why in [("43개 동네를 9개 군집으로 나눠줘", "2~6개"),
                       ("매출에 방문, 가게 수, 생존율, 관광객 비중이 미치는 영향 회귀분석", "3개까지")]:
            a = T.answer(q)["answer"]
            self.assertEqual(a["conclusion"]["tag"], "계산하지 않음", q)
            self.assertIn(why, a["conclusion"]["text"])
            self.assertEqual(a["blocks"][0]["lines"][1]["tag"], "대신 할 수 있는 것")

    def test_particles(self):
        texts = [T.answer(q)["answer"]["conclusion"]["text"] for q in T.EXAMPLES.values()]
        for bad in ["와 카드", "방문와", "동와 ", "매출는", "원예요"]:
            self.assertFalse(any(bad in t for t in texts), bad)


class Api(unittest.TestCase):
    def test_route(self):
        from fastapi.testclient import TestClient
        import api
        c = TestClient(api.app)
        r = c.post("/api/ask", json={"question": "43개 동네 방문과 매출의 상관 분석해줘"}).json()
        self.assertEqual(r["understood"]["by"], "기법 사전")
        self.assertEqual(r["answer"]["views"][0]["kind"], "scatter")
        r = c.post("/api/ask", json={"slots": {"topic": "technique", "method": "decomp"}}).json()
        self.assertEqual(r["answer"]["methods"][0]["kind"], "tech_decomp")
        r = c.post("/api/ask", json={"question": "노형동 카페 몇 개야?"}).json()
        self.assertNotEqual(r["understood"]["by"], "기법 사전")


if __name__ == "__main__":
    unittest.main()
