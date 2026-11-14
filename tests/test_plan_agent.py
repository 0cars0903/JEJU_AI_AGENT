"""계획 선택 Agent(문서 26 안 C): 범위·선택지 제한·저장(재현성)·검사·대체."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import plan_agent as PA  # noqa: E402


def it_of(type_, rule_type, needs_confirm=False, space=("노형동",)):
    t = {"type": type_, "metric": ["점포수"], "target": "카페", "space": list(space), "time": None, "time_year": None,
         "breakdown": None, "cond": [], "form": "수치", "expect": "답함"}
    return {"tuple": t, "card": {"text": "x"}, "confidence": 0.3 if needs_confirm else 0.9, "needs_confirm": needs_confirm,
            "rule_type": rule_type, "path": "B3(임베딩 + 분류기)"}


def chooser(type_, calls=None):
    def chat(model, messages, tools):
        if calls is not None:
            calls.append(messages[-1]["content"])
        return {"message": {"content": "", "tool_calls": [{"id": "c", "function": {"name": "choose_plan", "arguments": {"type": type_, "reason": "흐름을 묻는 질문"}}}]}}
    return chat


class PlanAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache, PA.CACHE = PA.CACHE, Path(self.tmp.name) / "plan_cache.json"
        PA._mem.clear()

    def tearDown(self):
        PA.CACHE = self.cache
        PA._mem.clear()
        self.tmp.cleanup()

    def test_confident_question_is_untouched(self):
        it = it_of("T1", "T1")
        calls = []
        self.assertIs(PA.adjust("노형동 카페 몇 곳", it, chat=chooser("T4", calls)), it)
        self.assertEqual(calls, [])

    def test_ambiguous_question_llm_chooses(self):
        r = PA.adjust("노형동 카페 요즘 어때", it_of("T1", "T4", needs_confirm=True), chat=chooser("T4"))
        self.assertEqual(r["tuple"]["type"], "T4")
        self.assertEqual((r["plan_agent"]["from"], r["plan_agent"]["to"], r["plan_agent"]["kept"]), ("T1", "T4", False))
        self.assertIn("계획 선택", r["path"])

    def test_disagreement_triggers(self):
        self.assertTrue(PA.needed(it_of("T1", "T4")))
        self.assertFalse(PA.needed(it_of("T1", "T12")))  # 범위 밖 규칙 판단은 후보가 아니다

    def test_choice_failing_review_is_kept(self):
        r = PA.adjust("카페 요즘 어때", it_of("T3", "T4", needs_confirm=True, space=()), chat=chooser("T4"))  # 추세는 동네가 필요한데 없음
        self.assertEqual(r["tuple"]["type"], "T3")
        self.assertTrue(r["plan_agent"]["kept"])

    def test_llm_error_keeps_classifier(self):
        def boom(model, messages, tools):
            raise OSError("down")
        r = PA.adjust("노형동 카페 요즘 어때", it_of("T1", "T4", needs_confirm=True), chat=boom)
        self.assertEqual(r["tuple"]["type"], "T1")
        self.assertIn("AI 호출 실패", r["plan_agent"]["why"])

    def test_same_question_same_plan_from_cache(self):  # 재현성: 두 번째는 LLM을 부르지 않고 저장된 결정을 쓴다
        reply = {"message": {"content": "", "tool_calls": [{"id": "c", "function": {"name": "choose_plan", "arguments": {"type": "T4", "reason": "흐름"}}}]}}
        with mock.patch.object(PA, "_backend", return_value="claude"), mock.patch.object(PA.llm, "chat", return_value=reply) as ch:
            a = PA.adjust("노형동 카페 요즘 어때", it_of("T1", "T4", needs_confirm=True))
            PA._mem.clear()  # 다시 시작한 것처럼 파일에서 읽는다
            b = PA.adjust("노형동  카페 요즘 어때", it_of("T1", "T4", needs_confirm=True))
        self.assertEqual(ch.call_count, 1)
        self.assertEqual((a["tuple"]["type"], b["tuple"]["type"], b["plan_agent"]["cached"]), ("T4", "T4", True))

    def test_agent_choice_escalates(self):
        r = PA.adjust("노형동 카페 요즘 어때 연동이랑 비교하면", it_of("T1", "T4", needs_confirm=True), chat=chooser("AGENT"))
        self.assertTrue(r.get("escalate"))
        self.assertEqual(r["tuple"]["type"], "T1")

    def test_off_switch(self):
        with mock.patch.dict("os.environ", {"JEJU_PLAN_AGENT": "0"}):
            self.assertIsNone(PA._backend())

    def test_local_model_not_used(self):  # 로컬 계획 선택은 측정에서 해로워 쓰지 않는다(246→242)
        import expert
        with mock.patch.object(expert, "backend", return_value="ollama"), mock.patch.dict("os.environ", {"JEJU_PLAN_AGENT": "1", "LLM_BACKEND": ""}):
            self.assertIsNone(PA._backend())


def judge(route, calls=None):
    def chat(model, messages, tools):
        if calls is not None:
            calls.append(messages[-1]["content"])
        return {"message": {"content": "", "tool_calls": [{"id": "c", "function": {"name": "judge_route", "arguments": {"route": route, "reason": "하위 질문이 둘"}}}]}}
    return chat


class RouteCheckTest(unittest.TestCase):
    """(다) 넘김 판정: 일반 경로가 정한 처리를 보고 Claude만 판정한다."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache, PA.CACHE = PA.CACHE, Path(self.tmp.name) / "plan_cache.json"
        PA._mem.clear()

    def tearDown(self):
        PA.CACHE = self.cache
        PA._mem.clear()
        self.tmp.cleanup()

    def test_agent_judgement_escalates(self):
        calls = []
        esc, rec = PA.route_check("노형동 카페 추세 보고 연동이랑 비교해줘", it_of("T4", "T4"), "성공", chat=judge("Agent", calls))
        self.assertTrue(esc)
        self.assertEqual(rec["route"], "Agent")
        self.assertIn("일반 경로의 이해", calls[0])

    def test_enough_keeps_general_path(self):
        esc, rec = PA.route_check("노형동 카페 몇 개야", it_of("T1", "T1"), "성공", chat=judge("충분"))
        self.assertFalse(esc)
        self.assertEqual(rec["route"], "충분")

    def test_local_model_does_not_judge(self):  # 로컬 모델 라우터는 200문항 비교에서 해로웠다(73 < 83)
        with mock.patch.object(PA, "_backend", return_value="ollama"):
            self.assertEqual(PA.route_check("노형동 카페 몇 개야", it_of("T1", "T1"), "성공"), (False, None))

    def test_off_switch_and_error(self):
        with mock.patch.dict("os.environ", {"JEJU_ROUTE_CHECK": "0"}):
            self.assertEqual(PA.route_check("q", it_of("T1", "T1"), "성공", chat=judge("Agent")), (False, None))

        def broken(*a):
            raise RuntimeError("x")
        self.assertEqual(PA.route_check("q", it_of("T1", "T1"), "성공", chat=broken), (False, None))


if __name__ == "__main__":
    unittest.main()
