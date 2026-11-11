"""F9 센터 자료 불러오기(app/center_csv.py, /api/dataset, dataset_id로 다시 계산). 746 일부로 칸 구성을 시험한다(센터 실자료 아님)."""
import glob
import json
import io
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import center_csv  # noqa: E402

KO2EN = {"년월": "base_year_month", "읍면동명": "bjd", "업종명": "biz_nm", "이용자 구분": "user_type", "이용금액": "use_amt"}


def sample(english=False):
    f = sorted(glob.glob(str(ROOT / "data" / "raw" / "*주제1*_21.csv")))[0]
    d = center_csv._read(Path(f).read_bytes())  # 원본 인코딩(UTF-8 또는 CP949)을 앱과 같은 방식으로 읽는다
    d = d[d["읍면동명"] == "노형동"]
    if english:  # 센터 명세의 영문 칸(1-08)처럼 바꾸고 746 전용 칸은 뺀다
        d = d.rename(columns=KO2EN)[list(KO2EN.values())]
    b = io.BytesIO()
    d.to_csv(b, index=False, encoding="utf-8-sig")
    return b.getvalue()


class Load(unittest.TestCase):
    def test_korean_columns_746(self):
        m = center_csv.load(sample(), "746.csv")
        self.assertEqual(m["dataset"], "P746")  # 746 전용 칸(매장수)이 있으면 시험용 표시
        self.assertIn("노형동", m["dongs"])
        self.assertEqual(center_csv.check_request(m, "노형동", "비알콜 음료점업"), [])

    def test_english_columns_center(self):
        m = center_csv.load(sample(english=True), "center.csv")
        self.assertIn(m["dataset"], ("C1-07", "C1-08"))
        self.assertEqual(m["columns"]["amt"], "use_amt")

    def test_missing_request_condition(self):
        m = center_csv.load(sample(), "746.csv")
        p = center_csv.check_request(m, "연동", None)
        self.assertTrue(p and "연동" in p[0])

    def test_wrong_file(self):
        with self.assertRaises(center_csv.CsvError) as e:
            center_csv.load("a,b\n1,2\n".encode(), "x.csv")
        self.assertIn("다시 받아", str(e.exception))
        with self.assertRaises(center_csv.CsvError):
            center_csv.load(b"x", "x.xlsx")


class Api(unittest.TestCase):
    def test_upload_and_recompute(self):
        from fastapi.testclient import TestClient
        import api
        c = TestClient(api.app, raise_server_exceptions=False)
        r = c.post("/api/dataset", content=sample(), headers={"X-Filename": "746.csv"})
        self.assertEqual(r.status_code, 200)
        q = c.post("/api/ask", json={"slots": {"topic": "sales", "space": ["노형동"], "target": "카페"}, "dataset_id": r.json()["id"], "dataset_key": r.json()["key"]}).json()
        lines = [x for b in q["answer"]["blocks"] for x in b["lines"]]
        self.assertTrue(any("이용자 불러옴" in str(x["source"]) for x in lines))
        self.assertTrue(any("비알콜 음료점업" in x["text"] for x in lines))
        self.assertFalse(any(x["kind"] == "center" for x in q["answer"]["requests"]))  # 이미 센터 자료로 답했으면 다시 요청하지 않음
        self.assertEqual(q["card"]["number_check"], [])
        bad = c.post("/api/ask", json={"slots": {"topic": "sales", "space": ["노형동"]}, "dataset_id": "nope0000"})
        self.assertEqual(bad.status_code, 422)
        for key in (None, "wrong"):  # 번호만 아는 다른 브라우저는 결과를 보지 못한다(문서 20 A7)
            other = c.post("/api/ask", json={"slots": {"topic": "sales", "space": ["노형동"], "target": "카페"}, "dataset_id": r.json()["id"], "dataset_key": key})
            self.assertEqual(other.status_code, 422)
            self.assertIn("다시 넣어", other.json()["detail"])
        self.assertNotIn(r.json()["key"], json.dumps(q, ensure_ascii=False))  # 답에는 열쇠를 싣지 않는다

    def test_flow_question_compares_first_and_last_month(self):  # 문서 20 A6: 센터 자료로 '흐름'을 물으면 넣은 기간의 처음과 끝을 견준 줄이 결론이다
        from fastapi.testclient import TestClient
        import api
        c = TestClient(api.app, raise_server_exceptions=False)
        r = c.post("/api/dataset", content=sample(), headers={"X-Filename": "746.csv"}).json()
        q = c.post("/api/ask", json={"question": "노형동 카페 카드 매출 흐름은?", "dataset_id": r["id"], "dataset_key": r["key"]}).json()
        self.assertEqual(q["question"], "노형동 카페 카드 매출 흐름은?")
        self.assertRegex(q["answer"]["conclusion"]["text"], r"에서 .+(늘었어요|줄었어요|변화가 없어요)\(넣은 자료 \d+개월\)")
        self.assertEqual(q["card"]["number_check"], [])


if __name__ == "__main__":
    unittest.main()
