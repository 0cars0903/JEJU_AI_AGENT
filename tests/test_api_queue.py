"""동시 질문 상한(2026-11-17 문제 기록 52번): 겹친 질문은 차례를 기다리며 순번을 받고, 한 번에 하나씩 계산한다."""
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import api  # noqa: E402


class AskQueue(unittest.TestCase):
    def test_second_question_waits_and_gets_position(self):
        log, says = [], []
        orig = api._ask_work

        def fake(body, request, say):
            log.append(("start", body))
            time.sleep(0.3)
            log.append(("end", body))
            return {"ok": body}

        api._ask_work = fake
        try:
            t1 = threading.Thread(target=api._ask_core, args=("A", None, lambda i, d, n=None: says.append(("A", d))))
            t1.start()
            time.sleep(0.05)
            t2 = threading.Thread(target=api._ask_core, args=("B", None, lambda i, d, n=None: says.append(("B", d))))
            t2.start()
            t1.join()
            t2.join()
        finally:
            api._ask_work = orig
        self.assertEqual([x[0] for x in log], ["start", "end", "start", "end"])  # 겹치지 않고 하나씩
        self.assertTrue(any(w == "B" and "앞에 질문 1개" in d for w, d in says))
        self.assertFalse(any(w == "A" for w, _ in says))  # 첫 질문은 기다리지 않는다


if __name__ == "__main__":
    unittest.main()
