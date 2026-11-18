"""상세 분석 코드 실행의 메모리 상한(2026-11-16 문제 기록 32번).

Windows(센터 PC): Job Object로 프로세스 메모리 상한(JEJU_EXPERT_MEM_MB, 기본 1536MB)을 건다.
macOS는 주소 공간 상한(RLIMIT_AS)이 듣지 않아(개발 PC에서 4GB 할당 성공) 이 시험을 건너뛴다.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import sandbox  # noqa: E402

BIG = "x = [0] * 20000000\nz = [list(x) for i in range(25)]\nresult = {\"notes\": [str(len(z))]}"  # 약 4GB


@unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "macOS는 RLIMIT_AS가 듣지 않음")
class MemoryLimit(unittest.TestCase):
    def test_over_limit_is_stopped(self):
        r = sandbox.run(BIG, timeout=120)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "실행")

    def test_small_code_runs(self):
        r = sandbox.run("x = [0] * 1000\nresult = {\"notes\": [str(len(x))]}", timeout=60)
        self.assertEqual(r.get("stage"), "실행")


if __name__ == "__main__":
    unittest.main()
