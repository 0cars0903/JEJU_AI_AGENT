"""지명 해석 회귀 시험(docs/조사/15_지명해석_실험.md): 일상어 함정 문장에서 엉뚱한 동네를 더하지 않고, 짧은 지명·별칭은 그대로 읽는다."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import qparse  # noqa: E402

ROWS = [json.loads(x) for x in (Path(__file__).resolve().parents[1] / "data" / "x1" / "place_traps.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


class Places(unittest.TestCase):
    def test_traps(self):
        for r in ROWS:
            if r["kind"] == "trap":
                self.assertEqual(set(qparse.find_places(r["q"])[0]), set(r["space"]), r["q"])

    def test_short_names(self):
        miss = [r["q"] for r in ROWS if r["kind"] == "legit" and set(qparse.find_places(r["q"])[0]) != set(r["space"])]
        self.assertEqual(miss, ["가시 펜션 몇 개야?"])  # '가시'는 일상어 목록: '가시리'로 써야 인정(알려진 대가)

    def test_no_word_inside_match(self):
        self.assertEqual(qparse.parse("제주 전체에서 점포 많은 동네 순위")["target"], None)  # '에서 점포'를 붙여 읽은 '서점' 아님


if __name__ == "__main__":
    unittest.main()
