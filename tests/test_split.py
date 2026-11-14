"""질문 나누기(app/split.py): 자를 자리, 자르지 않는 경우, 맥락 물려주기, 앞 결과 참조, 실패 처리."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import split  # noqa: E402


def fake_interpret(q):
    t = "T3" if ("가장" in q or "1위" in q) and "그 동네" not in q else "T2" if "비교" in q else "T4" if "추이" in q or "흐름" in q else "T1"
    return {"tuple": {"type": t, "expect": "답함", "space": [], "metric": [], "target": None}}


class SplitTest(unittest.TestCase):
    def test_cut_at_markers_and_comma_verbs(self):
        self.assertEqual(len(split.pieces("노형동 카페 매출 추이 확인해줘. 연동 카페 매출이랑도 비교해줘.")), 2)
        self.assertEqual(len(split.pieces("표선면 베이커리 점포 수를 확인한 후, 남원읍 베이커리 매출과 비교해봐.")), 2)

    def test_no_cut(self):  # 시점의 '다음', '-고 싶다', '및', '~부터 ~까지', 짧은 동사 조각
        for q in ["애월읍 다음 분기 버스 수요 예측치를 계산해줄 수 있나요?", "카페를 새로 창업하고 싶은데 어느 동네가 좋을까요?",
                  "노형동과 상권 구조 및 업종 분포가 비슷한 동네를 찾아주세요", "버스 승하차가 많은 곳 1위부터 5위까지 순위 보여줘"]:
            self.assertEqual(split.pieces(q), [q], q)
        self.assertEqual(len(split.pieces("조천읍 카페 점포 수 얼마야? 비 오는 날 매출 감소폭도 함께 분석해줘")), 2)

    def test_inherit_dong_and_target(self):
        ps = split.plan("노형동 카페 매출 흐름을 확인하고 연동 매출이랑도 비교해줘", fake_interpret)
        self.assertEqual(ps[1]["dongs"], ["노형동", "연동"])  # 비교 조각에 앞 동네를 더함
        self.assertEqual(ps[1]["target"], "카페")

    def test_ref_previous_result(self):
        ps = split.plan("청년 유동인구가 가장 많은 동네 알려줘. 그 동네의 카페 점포 수도 알려줘", fake_interpret)
        self.assertEqual(ps[1]["ref"], 0)
        self.assertEqual(split.top_dong({"card": {"conclusion": "순위는 1위 애월읍(221 곳), 2위 구좌읍"}}), ("애월읍", False))

    def test_failed_first_part_skips_dependent(self):
        import result
        calls = []

        def fake_respond(text, env=None, llm_on=True, interpret=None, slots=None, path=None):
            calls.append(text)
            return {"status": "범위밖", "card": {"conclusion": "답할 수 없어요", "evidence": []}}
        with mock.patch.object(result, "respond", fake_respond):
            ag = split.answer("청년 유동인구가 가장 많은 동네 알려줘. 그 동네의 카페 점포 수도 알려줘", fake_interpret)
        self.assertEqual(len(calls), 1)  # 앞 결과가 없으면 뒤 조각은 계산하지 않는다
        self.assertEqual(ag["status"], "실패")
        self.assertIn("계산하지 않았어요", ag["lines"][1])

    def test_short_first_of_two_does_not_crash(self):  # 페르소나 평가 2026-11-14: 조각 2개 중 첫 조각이 짧으면 IndexError
        self.assertEqual(len(split.pieces("오후에 하고 거기 음식점 수도 알려줘")), 1)

    def test_cut_after_jugo(self):  # '알려주고 거기 ~도'처럼 '-주고'로 이은 질문
        self.assertEqual(len(split.pieces("방문이 가장 많은 동네 알려주고 거기 음식점 수도 알려줘")), 2)

    def test_top_dong_from_values(self):  # 순위는 결론 문장이 아니라 계산값에서, '적은'이면 가장 작은 값
        out = {"tuple": {"type": "T3"}, "card": {"conclusion": "1위 애월읍"},
               "answer": {"views": [{"kind": "map", "values": {"애월읍": 9.0, "연동": 5.0, "노형동": 1.0}}]}}
        self.assertEqual(split.top_dong(out, text="방문이 가장 많은 동네"), ("애월읍", False))
        self.assertEqual(split.top_dong(out, text="방문이 가장 적은 동네"), ("노형동", False))

    def test_top_dong_from_result_dongs(self):  # 비슷한 동네·이례 변화는 계산 결과의 동네 목록에서(B6)
        out = {"tuple": {"type": "T9"}, "result_dongs": ["아라동", "연동"], "card": {"conclusion": "노형동과 비슷한 동네는 아라동"}}
        self.assertEqual(split.top_dong(out), ("아라동", False))

    def test_off_switch(self):
        with mock.patch.dict("os.environ", {"JEJU_SPLIT": "0"}):
            self.assertIsNone(split.answer("노형동 카페 추이 보고 연동이랑 비교해줘", fake_interpret))


if __name__ == "__main__":
    unittest.main()
