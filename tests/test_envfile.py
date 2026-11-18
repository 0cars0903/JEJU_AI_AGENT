"""`.env` 읽기와 실행 경로 안내(2026-11-13)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import check_env  # noqa: E402
import envfile  # noqa: E402


class EnvFileTest(unittest.TestCase):
    def setUp(self):
        self.keys = ["JEJU_T_A", "JEJU_T_B", "JEJU_T_C", "JEJU_T_D"]
        for k in self.keys:
            os.environ.pop(k, None)

    def tearDown(self):
        for k in self.keys:
            os.environ.pop(k, None)

    def test_load_rules(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# 주석\nJEJU_T_A=one\nexport JEJU_T_B=\"two\"\nJEJU_T_C=\nJEJU_T_D=new\n잘못된 줄\n", encoding="utf-8")
            os.environ["JEJU_T_D"] = "old"
            names = envfile.load(p)
        self.assertEqual(os.environ["JEJU_T_A"], "one")
        self.assertEqual(os.environ["JEJU_T_B"], "two")
        self.assertNotIn("JEJU_T_C", os.environ)  # 빈 값은 건너뜀
        self.assertEqual(os.environ["JEJU_T_D"], "old")  # 이미 있는 값이 우선
        self.assertEqual(names, ["JEJU_T_A", "JEJU_T_B"])

    def test_missing_file(self):
        self.assertEqual(envfile.load("/없는/경로/.env"), [])


class ReportTest(unittest.TestCase):
    def test_paths(self):
        def tag(lines, t):  # 줄 순서 대신 머리말로 찾는다(질문 담당 Agent 줄 추가, 2026-11-16)
            return next(x for x in lines if x.startswith(t))
        off = check_env.report(None, False)
        self.assertIn("사전 규칙", off[0])
        self.assertIn("템플릿", tag(off, "[설명 문장]"))
        full = check_env.report({"bge-m3", "qwen3:1.7b"}, False)
        self.assertIn("임베딩", full[0])
        self.assertIn("qwen3:1.7b", tag(full, "[설명 문장]"))
        self.assertIn("꺼져", tag(full, "[질문 담당 Agent]"))
        self.assertIn("확인 카드", tag(check_env.report({"qwen2.5:7b"}, False), "[질문 담당 Agent]"))
        no_embed = check_env.report({"qwen3:1.7b"}, True)
        self.assertIn("ollama pull bge-m3", no_embed[0])
        self.assertIn("Claude", " ".join(no_embed))  # 키가 있으면 요청 단위 Claude 안내(2026-11-14)
        self.assertIn("템플릿", tag(check_env.report({"bge-m3"}, True, "rule"), "[설명 문장]"))


if __name__ == "__main__":
    unittest.main()


class ModelVersion(unittest.TestCase):
    """정확도를 잰 모델 판과 다르면 실행 창에 알린다(check_env.PINNED, 2026-11-15)."""
    def test_mismatch_reported(self):
        import check_env as C
        self.assertEqual(C.version_lines(dict(C.PINNED)), [])
        lines = C.version_lines({"qwen2.5:7b": "000000000000"})
        self.assertEqual(len(lines), 1)
        self.assertIn("qwen2.5:7b", lines[0])

    def test_ollama_token_header(self):
        """OLLAMA_TOKEN이 있으면 Ollama 요청에 공유 토큰을 붙이고, 없으면 붙이지 않는다(Vercel 데모 터널, 2026-11-18)."""
        import llm
        old = os.environ.pop("OLLAMA_TOKEN", None)
        try:
            self.assertNotIn("Authorization", llm.ollama_headers())
            self.assertEqual(check_env._req("http://x/api/tags").headers, {})
            os.environ["OLLAMA_TOKEN"] = "t-123"
            self.assertEqual(llm.ollama_headers()["Authorization"], "Bearer t-123")
            self.assertEqual(check_env._req("http://x/api/tags").get_header("Authorization"), "Bearer t-123")
        finally:
            os.environ.pop("OLLAMA_TOKEN", None)
            if old is not None:
                os.environ["OLLAMA_TOKEN"] = old
