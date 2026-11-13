"""API 시험: 질문·해석·자료 탐색 경로가 응답 형식을 지키는지, 잘못된 입력을 안내하는지 본다. 실행: .venv/bin/python -m unittest discover -s tests"""
import os
os.environ.setdefault("JEJU_PLAN_AGENT", "0")  # 실제 키로 계획 선택 Agent(안 C)를 부르지 않는다. 동작은 test_plan_agent에서 시험
import sys
import unittest
import unittest.mock
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


class FeedbackLine(unittest.TestCase):  # 검수·재실행 라인 4·5단계: 사람 확인·고침 기록 → 학습 자료
    def test_feedback_logged_and_converted(self):
        import json, tempfile
        from fastapi.testclient import TestClient
        d = tempfile.mkdtemp()
        with unittest.mock.patch.dict(os.environ, {"JEJU_WRITE_DIR": d}):
            import api
            c = TestClient(api.app)
            slots = {"topic": "openclose", "space": ["노형동"], "target": "카페"}
            self.assertTrue(c.post("/api/feedback", json={"question": "노형동 카페 요즘 어때(시험)", "slots": slots, "before": {"topic": "stores"}, "ok": False}).json()["ok"])
        rec = [json.loads(l) for l in open(Path(d) / "feedback.jsonl", encoding="utf-8")]
        self.assertEqual((rec[0]["kind"], rec[0]["slots"]["topic"]), ("고침", "openclose"))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import feedback_to_train as F
        root = Path(tempfile.mkdtemp()); (root / "data" / "x1").mkdir(parents=True)
        with unittest.mock.patch.object(F, "ROOT", root):
            F.main(Path(d) / "feedback.jsonl")
        rows = [json.loads(l) for l in open(root / "data" / "x1" / "feedback_train.jsonl", encoding="utf-8")]
        self.assertEqual((rows[0]["tuple"]["type"], rows[0]["tuple"]["space"]), ("T4", ["노형동"]))


if __name__ == "__main__":
    unittest.main()
