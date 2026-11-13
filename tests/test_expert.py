"""전문가 모드: 코드 검사·격리 실행·Claude 없이 흉내 낸 흐름(2026-11-13)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import expert  # noqa: E402
import sandbox as S  # noqa: E402

OK = '''m = T["card_month"]
a = m[m.dong == "노형동"].groupby("ym").amt.sum()
result = {"numbers": {"months": len(a), "max_amt": float(a.max())},
          "series": [{"title": "노형동 월 매출", "kind": "line", "x": list(a.index), "y": [float(v) for v in a]}]}'''

ATTACKS = ["import os", "open('x', 'w')", "T['km'].to_csv('a.csv')", "pd.read_parquet('x')", "x = ().__class__.__bases__",
           "getattr(pd, 'read_csv')", "pd.io.common", "np.load('a.npy')", "s = '__cl' + 'ass__'",
           "try:\n    x = 1\nexcept Exception:\n    pass", "f = lambda: 1", "eval('1')", "T['km'].query('n > 1')",
           "exec('x=1')", "y = __builtins__", "x = [0] * (10 ** 10)", "a = np.zeros(200000000)"]


class SandboxTest(unittest.TestCase):
    def test_ok_runs(self):
        r = S.run(OK)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["numbers"]["months"], 81)

    def test_libs_outside_default_location(self):
        """Vercel처럼 라이브러리가 PYTHONPATH로만 보이는 경우(-I가 무시)에도 하위 프로세스가 numpy를 찾는다(2026-11-13 운영 오류)."""
        import subprocess
        import numpy
        site = str(Path(numpy.__file__).resolve().parents[1])
        app = str(Path(S.__file__).resolve().parent)
        probe = ("import sys; sys.path.insert(0, %r); import sandbox as S\n"
                 "if sys.argv[1] == 'none': S.lib_paths = lambda: []\n"
                 "print(S.run('result = {\"numbers\": {\"n\": float(np.mean([1, 2, 3]))}}')['ok'])") % app
        sysdir = Path(sys.base_prefix) / "bin" / "python3"
        exe = str(sysdir) if sysdir.exists() and sys.prefix != sys.base_prefix else None
        if not exe or subprocess.run([exe, "-I", "-c", "import numpy"], capture_output=True).returncode == 0:
            self.skipTest("기본 위치에 numpy가 없는 파이썬이 필요함(가상환경 밖 파이썬)")
        env = {**os.environ, "PYTHONPATH": site}
        out = {m: subprocess.run([exe, "-c", probe, m], capture_output=True, text=True, env=env, timeout=120).stdout.strip() for m in ("fix", "none")}
        self.assertEqual(out, {"fix": "True", "none": "False"})

    def test_attacks_rejected(self):
        for code in ATTACKS:
            with self.subTest(code=code):
                r = S.run(code, timeout=3)
                self.assertFalse(r["ok"])
                self.assertEqual(r["stage"], "검사")

    def test_timeout_and_shape(self):
        self.assertIn("시간 상한", S.run("while True:\n    x = 1", timeout=2)["error"])
        self.assertEqual(S.run("x = 1", timeout=5)["stage"], "형식")  # result 비어 있음
        self.assertIn("모르는 키", S.run("result = {'html': 1}", timeout=5)["error"])


def fake_chat(answers):
    """미리 정한 도구 호출을 차례로 돌려주는 가짜 Claude."""
    it = iter(answers)

    def chat(model, messages, tools):
        name, args = next(it)
        return {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": args}}]},
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    return chat


class ExpertFlowTest(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "LLM_BACKEND")}
        os.environ["ANTHROPIC_API_KEY"] = "test"
        os.environ.pop("LLM_BACKEND", None)

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_fix_once_then_explain(self):
        chat = fake_chat([("submit_analysis", {"method": "추이", "plan": ["월 합계"], "code": "import os"}),
                          ("submit_analysis", {"method": "추이", "plan": ["월 합계"], "code": OK}),
                          ("submit_explanation", {"lines": ["노형동 월 매출은 81개월 자료입니다."]})])
        r = expert.ask("노형동 월 매출 추이", chat=chat)
        self.assertEqual(r["status"], "성공")
        self.assertEqual([a["stage"] for a in r["attempts"]], ["검사", "실행"])
        self.assertEqual(r["by"], "AI")

    def test_wrong_number_falls_back(self):
        chat = fake_chat([("submit_analysis", {"method": "추이", "plan": ["월 합계"], "code": OK}),
                          ("submit_explanation", {"lines": ["상관계수는 0.92이고 증가율은 12.3%입니다."]})])
        r = expert.ask("노형동 월 매출 추이", chat=chat)
        self.assertTrue(r["by"].startswith("프로그램"))
        self.assertIn("months: 81", r["lines"])

    def test_two_failures(self):
        chat = fake_chat([("submit_analysis", {"method": "x", "plan": [], "code": "import os"}),
                          ("submit_analysis", {"method": "x", "plan": [], "code": "open('a')"})])
        r = expert.ask("파일 읽어 줘", chat=chat)
        self.assertEqual(r["status"], "실패")
        self.assertIn("기법 목록", r["hint"])

    def test_auth_error_is_reported(self):
        def chat(model, messages, tools):
            raise RuntimeError("Error code: 401 - invalid x-api-key")
        r = expert.ask("아무거나", chat=chat)
        self.assertEqual(r["status"], "오류")
        self.assertIn("인증 실패", r["error"])

    def test_disabled_without_key(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        self.assertEqual(expert.ask("아무거나")["status"], "꺼짐")


if __name__ == "__main__":
    unittest.main()
