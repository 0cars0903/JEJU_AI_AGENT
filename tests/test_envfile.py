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
        off = check_env.report(None, False)
        self.assertIn("사전 규칙", off[0])
        self.assertIn("템플릿", off[1])
        full = check_env.report({"bge-m3", "qwen3:1.7b"}, False)
        self.assertIn("임베딩", full[0])
        self.assertIn("qwen3:1.7b", full[1])
        no_embed = check_env.report({"qwen3:1.7b"}, True)
        self.assertIn("ollama pull bge-m3", no_embed[0])
        self.assertIn("Claude", " ".join(no_embed))  # 키가 있으면 요청 단위 Claude 안내(2026-11-14)
        self.assertIn("템플릿", check_env.report({"bge-m3"}, True, "rule")[1])


if __name__ == "__main__":
    unittest.main()
