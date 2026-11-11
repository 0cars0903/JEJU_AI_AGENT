"""API 시험: 질문·해석·자료 탐색 경로가 응답 형식을 지키는지, 잘못된 입력을 안내하는지 본다. 실행: .venv/bin/python -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("LLM_BACKEND", "rule")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(api.app, raise_server_exceptions=False)

    def test_bad_inputs(self):
        for path in ["/api/ask", "/api/interpret"]:
            self.assertEqual(self.c.post(path, json={"question": ""}).status_code, 422, path)
            self.assertEqual(self.c.post(path, json={"question": "   "}).status_code, 422, path)
        self.assertEqual(self.c.post("/api/ask", json={"question": "가" * 201}).status_code, 422)

    def test_interpret(self):
        r = self.c.post("/api/interpret", json={"question": "노형동 버스 이용 알려줘"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("노형동", str(r.json()))

    def test_catalog(self):
        d = self.c.get("/api/catalog", params={"q": "버스"}).json()
        self.assertGreater(d["count"], 0)

    def test_health(self):
        self.assertEqual(self.c.get("/api/health").json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
