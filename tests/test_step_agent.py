"""단계형 Agent(app/step_agent.py, 2026-11-16): 모델은 가짜로 바꿔 끼워 코드 쪽 장치만 시험한다."""
import json
import sys
import os
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


class SixImprovements(unittest.TestCase):
    """1번 문제(도민 질문 경로가 Workflow)의 남은 6가지(2026-11-16): 모델은 가짜로 바꿔 코드 쪽 장치만 시험한다."""

    def test_compare_values(self):  # ① 비교·종합: 같은 단위만 견주고, 단위가 다르면 견주지 않는다
        a = S.values_of("2026년 9월 노형동 카드 매출은 105억 원이에요.", "노형동")
        b = S.values_of("2026년 9월 애월읍 카드 매출은 78.3억 원이에요.", "애월읍")
        ok, line = S.compare([a, b])
        self.assertTrue(ok)
        self.assertIn("노형동이 105억 원으로 애월읍(78.3억 원)보다 26.7억 원 많아요", line)
        ok, line = S.compare([a, S.values_of("애월읍 카페 221곳이에요.", "애월읍")])
        self.assertIn("견주지 않았어요", line)
        self.assertFalse(S.compare([a])[0])

    def test_rank_industries_gives_top(self):  # ② 업종 순위의 1위 업종을 돌려준다
        ok, line, top = S.rank_industries("애월읍", "가게 수")
        self.assertTrue(ok)
        self.assertIn("1위", line)
        self.assertIn(top, S.BIZ_ITEMS)
        self.assertFalse(S.rank_industries("없는동", "가게 수")[0])

    def test_merge_follow(self):  # ⑥ 이어지는 질문을 앞 질문과 합친다
        h = [{"question": "노형동 카페 매출은?", "conclusion": "105억 원", "space": ["노형동"]}]
        self.assertEqual(S.merge_follow("그럼 애월읍은?", h), "애월읍 카페 매출은?")
        self.assertEqual(S.merge_follow("그럼 가게 수는?", h), "노형동 가게 수는?")
        self.assertIsNone(S.merge_follow("노형동 카페 몇 곳?", h))
        self.assertIsNone(S.merge_follow("그럼 애월읍은?", []))

    def _run_steps(self, plan, calls, fake_run, asks=None, history=None):
        answers = iter(calls)
        asks = iter(asks or [])
        with mock.patch("analyst._ask", side_effect=lambda chat, sys_, user, schema, **k: next(asks, {})), \
                mock.patch.object(S, "_chat", return_value=lambda m, msgs, tools: next(answers)), \
                mock.patch("question_agent.run", side_effect=fake_run):
            return S._serve_steps("질문", {}, False, lambda i, d: None, plan, {"step": 1, "tool": "plan"}, __import__("time").perf_counter(), history)

    def test_biz_inherited_and_compare_tool(self):  # ② 1위 업종 이어받기 ① 비교 도구
        asked = []

        def fake_run(q, env=None, llm_on=False, **k):
            asked.append(q)
            return {"status": "성공", "tuple": {"space": ["애월읍"]}, "card": {"conclusion": f"애월읍 {q} 210곳이에요.", "evidence": [{"text": "e"}]}}
        plan = [{"do": "애월읍에서 가게가 가장 많은 업종", "uses_prev": False}, {"do": "그 업종의 가게 수", "uses_prev": True}]
        top = S.rank_industries("애월읍", "가게 수")[2]
        r = self._run_steps(plan, [call("rank_industries", {"dong": "애월읍", "by": "가게 수"}), call("answer_question", {"question": "1위 업종 가게 수는?"})],
                            fake_run, asks=[{"missing": ""}])
        self.assertIn(top, asked[0])
        self.assertEqual(r["agent"]["status"], "성공")
        self.assertIn("rank_industries", [t["tool"] for t in r["agent"]["trace"]])

    def test_replan_after_failure(self):  # ③ 실패 뒤 남은 단계를 다시 쓴다
        def fake_run(q, env=None, llm_on=False, **k):
            if "숙박" in q:
                return {"status": "범위밖", "card": {"conclusion": "음식점만 볼 수 있어요.", "evidence": []}}
            return {"status": "성공", "tuple": {"space": ["애월읍"]}, "card": {"conclusion": f"{q} 답 10곳이에요.", "evidence": [{"text": "e"}]}}
        plan = [{"do": "애월읍 숙박 폐업률", "uses_prev": False}, {"do": "그 업종의 매출", "uses_prev": True}]
        r = self._run_steps(plan, [call("answer_question", {"question": "애월읍 숙박 폐업률은?"}), call("answer_question", {"question": "애월읍 음식점 가게 수는?"})],
                            fake_run, asks=[{"steps": [{"do": "애월읍 음식점 가게 수", "uses_prev": False}]}, {"missing": ""}])
        tools = [t["tool"] for t in r["agent"]["trace"]]
        self.assertIn("replan", tools)
        self.assertIn("skip_step", tools)  # 범위 밖은 다시 시도하지 않고 넘긴다
        self.assertIn("애월읍 음식점 가게 수", r["step_agent"]["plan"])

    def test_self_check_adds_missing_once(self):  # ④ 빠진 요청을 한 번 더한다(질문에 있는 동네·지표만)
        def fake_run(q, env=None, llm_on=False, **k):
            return {"status": "성공", "tuple": {"space": ["노형동"], "metric": []}, "card": {"conclusion": f"{q} 10곳이에요.", "evidence": [{"text": "e"}]}}
        plan = [{"do": "노형동 카페 가게 수", "uses_prev": False}]
        with mock.patch.object(S, "_self_check", wraps=S._self_check):
            answers = iter([call("answer_question", {"question": "노형동 카페 가게 수는?"}), call("answer_question", {"question": "노형동 카페 폐업률은?"})])
            asks = iter([{"missing": "노형동 카페 폐업률은?"}])
            with mock.patch("analyst._ask", side_effect=lambda *a, **k: next(asks, {})), mock.patch.object(S, "_chat", return_value=lambda m, msgs, tools: next(answers)), \
                    mock.patch("question_agent.run", side_effect=fake_run), mock.patch("qparse.parse", side_effect=lambda q: {"metric": ["폐업률"] if "폐업" in q else ["점포수"]}):
                r = S._serve_steps("노형동 카페 가게 수와 폐업률", {}, False, lambda i, d: None, plan, {"step": 1, "tool": "plan"}, __import__("time").perf_counter())
        self.assertEqual(len(r["step_agent"]["plan"]), 2)
        self.assertEqual([t["tool"] for t in r["agent"]["trace"]].count("self_check"), 1)

    def test_history_compare(self):  # ⑥ 앞 대화 두 답을 비교
        h = [{"question": "노형동 카페 매출은?", "conclusion": "노형동 매출은 105억 원이에요.", "space": ["노형동"]},
             {"question": "애월읍 카페 매출은?", "conclusion": "애월읍 매출은 78.3억 원이에요.", "space": ["애월읍"]}]
        r = self._run_steps([{"do": "둘 중 어디가 더 많아?", "uses_prev": True}], [call("compare_steps", {"steps": ["D1", "D2"]})], lambda *a, **k: {}, asks=[{"missing": ""}], history=h)
        self.assertIn("노형동이 105억 원으로", r["agent"]["lines"][0])

    def test_confirm_card_and_one_step(self):  # ⑤ 여러 가지일 확률이 낮으면 멈춤, '한 가지 질문으로'를 고르면 질문 담당 Agent로
        plan = {"steps": [{"do": "청년 유동인구가 가장 많은 동네 3곳 순위", "uses_prev": False}, {"do": "1위 동네의 카페 점포 수", "uses_prev": True}]}
        q = "청년 유동인구가 가장 많은 동네 3곳을 뽑고, 1위 동네의 카페 점포 수를 알려줘."
        fake = {"question": q, "status": "Agent", "agent": {"lines": []}, "card": {"limits": []}, "step_agent": {"plan": ["a", "b"], "trace": []}}
        with mock.patch("analyst._ask", return_value=plan), mock.patch("question_agent._ask_choice", return_value=({}, {"1": 0.8, "2": 0.2})), \
                mock.patch.object(S, "_serve_steps", return_value=fake), mock.patch.object(S, "clauses", return_value=[]):  # 모델 계획 경로를 검사(쉼표 뒤 연결은 2026-11-18부터 코드가 구절로 나눔)
            r = S.serve(q, {}, llm_on=False)
        self.assertTrue(r["confirm"]["pause"])
        self.assertEqual(r["confirm"]["options"][0]["pick"], S.ONE_STEP)
        with mock.patch("question_agent.run", return_value={"status": "성공", "card": {}}) as qa:
            r = S.serve(q, {}, llm_on=False, forced=S.ONE_STEP)
        qa.assert_called_once()
        self.assertEqual(r["confirm"]["forced"], S.ONE_STEP)


class ForeignDong(unittest.TestCase):
    def test_foreign_dong_replaced(self):  # 질문·앞 결과에 없는 동네를 모델이 적으면 질문의 동네로(조정용 R075)
        asked = []

        def fake_run(q, env=None, llm_on=False, **k):
            asked.append(q)
            return {"status": "성공", "tuple": {"space": ["아라동"]}, "card": {"conclusion": "x 10곳이에요.", "evidence": [{"text": "e"}]}}
        s = {"do": "아라동 업종의 입지계수", "uses_prev": False, "state": "남음", "result": None, "tries": 0}
        with mock.patch("question_agent.run", side_effect=fake_run):
            S._ask_step({"question": "노형동 각 업종의 입지계수는?"}, s, {"q": "아라동 입지계수와 1순위 업종 점포 수"}, {}, False)
        self.assertIn("아라동", asked[0])
        self.assertNotIn("노형동", asked[0])


class Clauses(unittest.TestCase):  # 원문 구절 나누기(2026-11-17 문제 기록 51번, 초보 말투 두 가지 질문)
    def test_two_questions_same_dong(self):
        c = S.clauses("노형동 카페 몇 개나 있고 한 달에 얼마나 벌어?")
        self.assertEqual([x["do"] for x in c], ["노형동 카페 몇 개나 있어?", "노형동 카페 한 달에 얼마나 벌어?"])
        self.assertFalse(any(x["uses_prev"] for x in c))

    def test_compare_keeps_two_dongs(self):
        c = S.clauses("애월이랑 조천 둘 중 어디가 식당 장사 더 잘되고 손님 많아?")
        self.assertEqual(c[1]["do"], "애월읍과 조천읍 중 어디가 식당 손님 많아?")

    def test_rank_then_there(self):  # 순위·비슷한 동네 뒤 구절은 앞 결과를 이어받는다
        c = S.clauses("카페 새로 제일 많이 생긴 동네 어디야? 문 닫는 비율은?")
        self.assertTrue(c[1]["uses_prev"])
        self.assertEqual(c[1]["do"], "거기 카페 문 닫는 비율은?")
        self.assertTrue(S.clauses("연동이랑 닮은 동네 어디야? 거기 식당들 매출은 어때?")[1]["uses_prev"])

    def test_single_question_not_split(self):  # 한 가지 질문·묻는 말이 없는 조각은 나누지 않는다
        self.assertEqual(S.clauses("노형이랑 연동 중에 카페 하기 어디가 좋아? 사람 많은 데로"), [])
        self.assertEqual(S.clauses("한림이랑 한경 중에 식당 차리면 어디가 더 오래 버텨?"), [])
        self.assertEqual(S.clauses("노형동과 이도2동 두 동네의 30대 청년층 유동인구 규모를 비교해서 보여주세요."), [])

    def test_there_replaced_with_similar_dongs(self):  # '거기'는 앞 단계가 찾은 비슷한 동네 모두로
        facts = {"q": "연동이랑 닮은 동네 어디야? 거기 식당들 매출은 어때?", "dongs": ["삼도1동", "아라동"], "similar": True, "history": []}
        seen = {}

        def fake(q, env, llm_on=True):
            seen["q"] = q
            return {"status": "성공", "card": {"conclusion": "x", "evidence": [{"text": "x"}]}, "tuple": {"type": "T2"}}
        with mock.patch("question_agent.run", fake):
            S._ask_step({"question": "거기 식당들 매출은 어때?"}, {"do": "거기 식당들 매출은 어때?", "uses_prev": True}, facts, {}, False)
        self.assertTrue(seen["q"].startswith("삼도1동·아라동 식당들"))

    def test_step_model_claude_with_fallback(self):  # 60번 A안: 키가 있고 심사용 계정 로그인이면 Sonnet, 실패하면 그 뒤로 7B
        import expert
        import llm_claude
        local_calls = []
        local = lambda model, messages, tools: local_calls.append(1) or call("skip_step", {})  # noqa: E731
        with mock.patch.object(expert, "_chat_fn", lambda name: local), mock.patch.object(expert, "claude_key", lambda: False):
            S._chat()(None, [], [])
        self.assertEqual(len(local_calls), 1)  # 키 없음 → 7B
        seen = []
        with mock.patch.object(expert, "_chat_fn", lambda name: local), mock.patch.object(expert, "claude_key", lambda: True), \
                mock.patch.object(llm_claude, "chat", lambda m, msgs, tools, effort=None: seen.append(m) or call("ask", {})):
            S._chat()(None, [], [])
            self.assertEqual((seen, len(local_calls)), ([], 2))  # 키 있음·로그인 안 함 → 7B(마스터 2026-11-18 '평가자만')
            c = S._chat(True)
            c(None, [], [])
            self.assertEqual(S._who(c), S.BY_CLAUDE)  # 표시: Claude가 답했으면 Claude(2026-11-18)
        self.assertEqual(seen, [S.STEP_CLAUDE_MODEL])  # 키 있음·로그인 → Sonnet
        self.assertEqual(S._who(S._chat()), S.BY)  # 표시: 아직 부르지 않았거나 로컬이면 로컬 모델
        with mock.patch.dict("os.environ", {"JEJU_STEP_CLAUDE": "off"}), mock.patch.object(expert, "_chat_fn", lambda name: local), \
                mock.patch.object(expert, "claude_key", lambda: True):
            S._chat(True)(None, [], [])
        self.assertEqual(len(local_calls), 3)  # 끄면 로그인해도 7B
        tries = []

        def boom(m, msgs, tools, effort=None):
            tries.append(1)
            raise RuntimeError("연결 끊김")
        with mock.patch.object(expert, "_chat_fn", lambda name: local), mock.patch.object(expert, "claude_key", lambda: True), \
                mock.patch.object(llm_claude, "chat", boom):
            c = S._chat(True)
            c(None, [], [])
            c(None, [], [])
        self.assertEqual((len(tries), len(local_calls)), (1, 5))  # 한 번 실패하면 그 질문 동안 다시 부르지 않고 7B

    def test_serve_passes_staff_flag(self):  # env['staff'](api가 로그인 여부로 채움)가 단계별 도구 고르기까지 간다
        got = []
        plan = {"steps": [{"do": "노형동 카페 수"}, {"do": "연동 카페 수"}]}
        with mock.patch.object(S, "clauses", return_value=plan["steps"]), mock.patch.object(S, "_serve_steps", lambda *a, **k: got.append(a[-1]) or {"status": "Agent", "step_agent": {"plan": ["가", "나"]}, "card": {}}):
            S.serve("노형동 카페 수랑 연동 카페 수 알려줘", {"staff": True})
            S.serve("노형동 카페 수랑 연동 카페 수 알려줘", {})
        self.assertEqual(got, [True, False])


class ClauseConfirm(unittest.TestCase):
    def test_confirm_then_compare(self):  # 2026-11-18 데모(영상 장면 2): '먼저 확인하고, 그 다음 …'을 두 구절로, 순서 말은 뗌
        q = "노형동 카페의 최근 1년 매출 흐름을 먼저 확인하고, 그 다음 연동 카페 매출과 비교 분석해줘."
        steps = [x["do"] for x in S.clauses(q)]
        self.assertEqual(len(steps), 2)
        self.assertIn("확인해줘", steps[0])
        self.assertNotIn("그 다음", steps[1])
        self.assertIn("연동", steps[1])

    def test_nested_question_arg(self):  # 모델이 인자를 {'question': {'question': …}}로 감싼 경우 안쪽 문장으로 묻는다
        asked = []
        with mock.patch("question_agent.run", side_effect=lambda q, *a, **k: asked.append(q) or {"status": "성공", "card": {"conclusion": "x"}}):
            s = {"do": "노형동 카페 매출", "uses_prev": False, "state": "남음", "result": None, "tries": 0}
            S._ask_step({"question": {"question": "노형동 카페 매출 알려줘"}}, s, {}, {}, False)
        self.assertEqual(asked[0], "노형동 카페 매출 알려줘")


class StepClaudeMode(unittest.TestCase):
    def test_modes(self):  # 2026-11-18 마스터 '(나)': 센터 운영 always는 로그인 없이 Sonnet, 제출본·데모 login은 로그인만, 공개 서버는 always를 login으로
        import expert
        import llm_claude
        seen, local_calls = [], []

        def local(model, msgs, tools):
            local_calls.append(1)
            return {"message": {"content": ""}}
        base = [mock.patch.object(expert, "_chat_fn", lambda name: local), mock.patch.object(expert, "claude_key", lambda: True),
                mock.patch.object(llm_claude, "chat", lambda m, msgs, tools, effort=None: seen.append(m) or {"message": {"content": ""}})]
        for p in base:
            p.start()
        try:
            for env, staff, want in [({"JEJU_STEP_CLAUDE": "always"}, False, "claude"), ({"JEJU_STEP_CLAUDE": "login"}, False, "local"),
                                     ({"JEJU_STEP_CLAUDE": "on"}, True, "claude"), ({"JEJU_STEP_CLAUDE": "always", "VERCEL": "1"}, False, "local"),
                                     ({"JEJU_STEP_CLAUDE": "off"}, True, "local")]:
                with mock.patch.dict("os.environ", env):
                    if "VERCEL" not in env:
                        os.environ.pop("VERCEL", None)
                    c = S._chat(staff)
                    c(None, [], [])
                    self.assertEqual("claude" if getattr(c, "last", None) == "claude" else "local", want, (env, staff))
        finally:
            for p in base:
                p.stop()
