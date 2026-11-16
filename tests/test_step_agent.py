"""단계형 Agent(app/step_agent.py, 2026-11-16): 모델은 가짜로 바꿔 끼워 코드 쪽 장치만 시험한다."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import step_agent as S  # noqa: E402


def call(name, args):
    return {"message": {"tool_calls": [{"function": {"name": name, "arguments": args}}]}}


class StepAgent(unittest.TestCase):
    def test_normalize_args(self):  # ③ 같은 뜻 낱말을 목록 값으로
        self.assertEqual(S._target("한식당", ""), "한식")
        self.assertEqual(S._target("외식업", ""), "음식점")
        self.assertEqual(S._space(["대정읍 모슬포"], "", {}, False), ["대정읍"])
        self.assertEqual(S._space(["안덕면 사계리"], "", {}, False), ["안덕면"])
        self.assertEqual(S._space(["1위 동네"], "1위 동네의 카페 점포 수", {"dongs": ["애월읍", "조천읍"]}, True), ["애월읍"])
        self.assertEqual(S._metric(["점포수", "조건부생존"], "애월읍 카페 점포 수"), ["점포수"])  # ⑥ 단계 문장에 없는 지표는 뺀다

    def test_tools_narrowed(self):  # ② 기법을 뜻하는 말이 없으면 통계 기법 도구를 보이지 않는다
        self.assertFalse(S._tech_ok("앞으로 3개월간 방문객 수요가 늘어날지 예측합니다."))
        self.assertFalse(S._tech_ok("1위 동네의 카페 점포 수"))
        self.assertTrue(S._tech_ok("노형동 매출과 방문의 상관분석"))

    def test_multi_guard(self):  # 여러 일을 잇는 표지가 없으면 단계 하나
        self.assertFalse(S._multi_ok("노형동 카페 가게는 몇 곳이야?"))
        self.assertTrue(S._multi_ok("청년 유동인구가 가장 많은 동네 3곳을 뽑고, 1위 동네의 카페 점포 수를 알려줘."))

    def test_simple_question_goes_to_question_agent(self):
        plan = {"steps": [{"do": "노형동", "uses_prev": False}, {"do": "카페", "uses_prev": False}, {"do": "가게 수", "uses_prev": False}]}
        with mock.patch("analyst._ask", return_value=plan), mock.patch("question_agent.run", return_value={"status": "성공", "card": {"conclusion": "x"}}) as qa:
            r = S.serve("노형동 카페 가게는 몇 곳이야?", {}, llm_on=False)
        qa.assert_called_once()
        self.assertEqual(qa.call_args[0][0], "노형동 카페 가게는 몇 곳이야?")
        self.assertIn("1단계로 봄", r["step_agent"]["trace"][0]["note"])

    def test_steps_and_prev_result(self):  # ① 남은 단계 ⑤ 앞 결과의 1위 동네
        q = "청년 유동인구가 가장 많은 동네 3곳을 뽑고, 1위 동네의 카페 점포 수를 알려줘."
        plan = {"steps": [{"do": "청년 유동인구가 가장 많은 동네 3곳 순위", "uses_prev": False}, {"do": "1위 동네의 카페 점포 수", "uses_prev": True}]}
        answers = iter([call("answer_question", {"question": "청년 유동인구가 가장 많은 동네 3곳은?"}),
                        call("answer_question", {"question": "구좌읍 카페 점포 수는?"})])  # 모델이 앞 결과와 다른 동네를 적음
        asked = []

        def fake_run(question, env=None, llm_on=False, **k):
            asked.append(question)
            if "청년" in question:
                return {"status": "성공", "tuple": {"type": "T3", "space": []}, "result_dongs": ["애월읍", "조천읍"],
                        "card": {"conclusion": "청년 비중 순위는 1위 애월읍(1%), 2위 조천읍(1%)이에요.", "evidence": [{"text": "a"}]}}
            return {"status": "성공", "tuple": {"type": "T1", "space": ["애월읍"]}, "card": {"conclusion": f"{question} 답", "evidence": [{"text": "b"}]}}
        with mock.patch("analyst._ask", return_value=plan), mock.patch.object(S, "_chat", return_value=lambda m, msgs, tools: next(answers)), \
                mock.patch("question_agent.run", side_effect=fake_run):
            r = S.serve(q, {}, llm_on=False)
        self.assertEqual(r["status"], "Agent")
        self.assertEqual(len(asked), 2)
        self.assertIn("애월읍", asked[1])  # 앞 결과의 1위 동네로 바뀜
        self.assertNotIn("구좌읍", asked[1])
        self.assertEqual(r["agent"]["status"], "성공")
        self.assertEqual(len([t for t in r["agent"]["trace"] if t["tool"] == "answer_question"]), 2)

    def test_state_shows_remaining(self):
        steps = [{"do": "가", "state": "끝남", "result": "A 결과"}, {"do": "나", "state": "남음", "result": None}, {"do": "다", "state": "남음", "result": None}]
        st = S._state("질문", steps, 1, {"text": "앞 단계에서 나온 동네: 애월읍"}, None)
        self.assertIn("1. [끝남] 가 → 결과: A 결과", st)
        self.assertIn("2. [지금] 나", st)
        self.assertIn("남은 단계: 지금 단계 말고 1개", st)
        self.assertIn("애월읍", st)


if __name__ == "__main__":
    unittest.main()


class AnalystRepair(unittest.TestCase):
    """분석 담당 Agent ② 대안(2026-11-16 조정용 tech_dev_alt_8): 같은 기법을 고르면 조건에 맞게 인자를 고쳐 다시 계산한다."""

    def test_repair_args(self):
        import analyst
        fix, note = analyst._repair("제주 43개 동네를 10개 그룹으로 묶어서 보여줘", "cluster")
        self.assertEqual(fix, {"k": 6})
        self.assertIn("10개", note)
        fix, _ = analyst._repair("동네별 매출을 방문·가게 수·생존율·관광객 비중 네 가지로 회귀분석해줘", "regress")
        self.assertEqual(len(fix["metrics"]), 4)  # 매출 + 설명 변수 3개
        self.assertEqual(analyst._repair("입지계수 분석해줘", "lq"), ({}, ""))

    def test_refused_reason_when_cannot_fix(self):
        import analyst
        U = lambda k: {"kind": k, "dongs": [], "target": "", "keyword": "", "reason": ""}  # noqa: E731
        answers = iter([U("lq"), {"kind": "lq", "reason": "같은 기법"}])

        def chat(model, msgs, tools):
            return {"message": {"content": json.dumps(next(answers), ensure_ascii=False)}}
        with mock.patch.object(analyst, "RAG_ON", False):
            r = analyst.run("입지계수 분석해줘", chat=chat)
        self.assertIn("입지계수 분석을 하지 않았어요", r["lines"][0])
        self.assertIn("조건 확인에서 멈춤", r["method"])
