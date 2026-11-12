"""데모 로그인: 해시·서명 쿠키·시도 제한, 로그인해야 Claude 기능이 켜지는지(2026-11-13)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ.setdefault("LLM_BACKEND", "rule")
import auth  # noqa: E402


class AuthUnit(unittest.TestCase):
    def setUp(self):
        self.h = auth.make_hash("비번-1234")
        self.env = mock.patch.dict(os.environ, {"JEJU_ACCOUNTS": f"judge1:{self.h},judge2:{auth.make_hash('x')}", "JEJU_SESSION_SECRET": "s3cret"})
        self.env.start()
        auth._fails.clear()

    def tearDown(self):
        self.env.stop()

    def test_hash_and_accounts(self):
        self.assertTrue(auth.check_password("비번-1234", self.h))
        self.assertFalse(auth.check_password("틀림", self.h))
        self.assertNotIn("비번", self.h)
        self.assertEqual(set(auth.accounts()), {"judge1", "judge2"})
        self.assertTrue(auth.required())

    def test_token(self):
        t = auth.sign("judge1", now=1000)
        self.assertEqual(auth.verify(t, now=1001), "judge1")
        self.assertIsNone(auth.verify(t, now=1000 + auth.TTL + 1))  # 만료
        self.assertIsNone(auth.verify(t.replace("judge1", "judge2"), now=1001))  # 위조
        self.assertIsNone(auth.verify("아무거나"))
        with mock.patch.dict(os.environ, {"JEJU_SESSION_SECRET": "다른값"}):
            self.assertIsNone(auth.verify(t, now=1001))

    def test_rate_limit(self):
        for _ in range(5):
            self.assertEqual(auth.login("judge1", "틀림", ip="1.2.3.4")[0], None)
        token, why = auth.login("judge1", "비번-1234", ip="1.2.3.4")
        self.assertIsNone(token)
        self.assertIn("10분", why)
        self.assertIsNotNone(auth.login("judge1", "비번-1234", ip="5.6.7.8")[0])

    def test_local_needs_no_login(self):
        with mock.patch.dict(os.environ, {"JEJU_ACCOUNTS": ""}):
            self.assertFalse(auth.required())


class AuthApi(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import api
        self.api = api
        self.env = mock.patch.dict(os.environ, {"JEJU_ACCOUNTS": f"judge1:{auth.make_hash('pw-1')}", "JEJU_SESSION_SECRET": "s3cret",
                                                "ANTHROPIC_API_KEY": "test"})
        self.env.start()
        os.environ.pop("LLM_BACKEND", None)
        auth._fails.clear()
        self.c = TestClient(api.app)

    def tearDown(self):
        self.env.stop()
        os.environ["LLM_BACKEND"] = "rule"

    def test_gate(self):
        st = self.c.get("/api/expert/status").json()
        self.assertEqual((st["enabled"], st["login_required"]), (False, True))
        self.assertEqual(self.c.post("/api/expert", json={"question": "x"}).status_code, 401)
        self.assertEqual(self.c.post("/api/login", json={"id": "judge1", "password": "틀림"}).status_code, 401)
        r = self.c.post("/api/login", json={"id": "judge1", "password": "pw-1"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.c.get("/api/me").json()["logged_in"])
        self.assertTrue(self.c.get("/api/expert/status").json()["enabled"])
        with mock.patch("expert.ask", return_value={"status": "성공"}) as ex:
            self.assertEqual(self.c.post("/api/expert", json={"question": "상관"}).json()["status"], "성공")
        self.assertEqual(ex.call_args.kwargs["user"], "judge1")
        self.c.post("/api/logout")
        self.assertFalse(self.c.get("/api/me").json()["logged_in"])

    def test_ask_uses_claude_only_after_login(self):
        seen = []
        real = self.api.result.respond if hasattr(self.api, "result") else None  # noqa: F841
        import result
        with mock.patch.object(result, "respond", side_effect=lambda *a, **k: seen.append(k["llm_on"]) or {"status": "성공"}):
            self.c.post("/api/ask", json={"slots": {"topic": "stores", "space": ["노형동"]}})
            self.c.post("/api/login", json={"id": "judge1", "password": "pw-1"})
            self.c.post("/api/ask", json={"slots": {"topic": "stores", "space": ["노형동"]}})
        self.assertEqual(seen, [False, True])


if __name__ == "__main__":
    unittest.main()
