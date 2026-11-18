"""흐름 기법(문제 기록 56번)과 두 업종 견주기(57·58번) 시험. 모델 호출 없음(코드 표·자료 계산만)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import biz_compare  # noqa: E402
import more  # noqa: E402


class BizCompare(unittest.TestCase):
    Q57 = "노형동에서 음식점 수와 매출이 카페 수와 매출과 비교했을 때 어떤 결과가 있나요?"

    def test_reads_both(self):
        self.assertEqual(biz_compare.find_bizs(self.Q57), ["음식점", "카페"])
        self.assertTrue(biz_compare.detect(self.Q57))

    def test_single_or_no_compare(self):
        self.assertFalse(biz_compare.detect("노형동 카페 몇 개야?"))
        self.assertFalse(biz_compare.detect("노형동이랑 연동 카페 수 비교해줘"))  # 동네 둘 = 동네 비교 경로

    def test_answer(self):
        r = biz_compare.answer(self.Q57)
        text = " ".join([r["card"]["conclusion"]] + [e["text"] for e in r["card"]["evidence"]] + r["card"]["limits"])
        self.assertIn("1,089곳", text)  # 카페를 뺀 음식점
        self.assertIn("175곳", text)
        self.assertIn("746", text)  # 카페 매출은 세부 업종이 있는 746 자료로
        self.assertIn("한 곳당 매출은 계산하지 않았어요", text)
        self.assertNotIn("배예요.", r["card"]["evidence"][2]["text"])  # 매출 금액 배수를 만들지 않음


class More(unittest.TestCase):
    def test_code_pick(self):
        s = more.slots_of("애월읍 식당 몇 월이 대목이야?")
        self.assertEqual(more.pick_code("애월읍 식당 몇 월이 대목이야?", s)[0], "decomp")
        s = more.slots_of("식당 차리면 오래 버틸까?")
        self.assertIsNone(more.pick_code("식당 차리면 오래 버틸까?", s)[0])  # 생존분석은 동네가 있어야 함

    def test_attach_off(self):
        r = {"status": "성공", "answer": {"blocks": []}}
        self.assertEqual(more.attach(r, "노형동 카페", how="off"), r)
        self.assertNotIn("more", r)


if __name__ == "__main__":
    unittest.main()
