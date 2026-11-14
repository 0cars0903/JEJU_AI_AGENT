"""질문 담당 Agent(app/question_agent.py, 2026-11-15): 코드가 어긋남과 선택지를 만들고, 모델(가짜)이 번호를 고르면 그대로 실행한다. Ollama 없이 돈다."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import question_agent as A  # noqa: E402


def pick(text_part, seen=None):
    """선택지 중 text_part가 들어간 번호를 고르는 가짜 모델."""
    def chat(model, messages, tools):
        user = messages[-1]["content"]
        if seen is not None:
            seen.append(user)
        line = next((l for l in user.splitlines() if text_part in l and l[:1].isdigit()), "")
        return {"message": {"content": json.dumps({"choice": line.split(".")[0] if line else "0", "reason": "시험"}, ensure_ascii=False)}}
    return chat


class QuestionAgent(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"JEJU_RULE_FIX": "0", "LLM_BACKEND": "rule"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_period_gap_recomputes(self):  # 규칙 보정 없이도 Agent가 '질문 기간으로 다시 계산'을 고르면 그 해 값으로 답한다
        r = A.run("2024년 노형동 카드 매출", {}, llm_on=False, chat=pick("질문의 기간"))
        self.assertEqual(r["tuple"].get("ask_year"), 2024)
        self.assertTrue(r["card"]["conclusion"].startswith("2024년 노형동"))
        self.assertEqual(r["question_agent"]["turns"][0]["action"], "다시 계산")
        self.assertIn("질문 담당 Agent", " ".join(r["understood"]["notes"]))

    def test_model_failure_keeps_answer(self):  # 모델이 엉뚱한 값을 내면 지금 답을 그대로 둔다
        def bad(model, messages, tools):
            return {"message": {"content": "not json"}}
        r = A.run("노형동 카페 몇 개야?", {}, llm_on=False, chat=bad)
        self.assertEqual(r["question_agent"]["turns"][0]["action"], "답하기")
        self.assertIn("노형동", r["card"]["conclusion"])

    def test_no_askback_option_when_dong_given(self):  # 동네가 질문에 있으면 되묻기 선택지를 주지 않는다(코드 검사)
        seen = []
        A.run("아라동에 어르신들 많이 거주하시나요?", {}, llm_on=False, chat=pick("지금 답 그대로", seen))
        self.assertNotIn("되묻기", seen[0].split("선택지:")[1])

    def test_options_only_from_candidates(self):  # 지표 선택지는 주요 지표 목록 안에서만 나온다
        r = {"status": "성공", "tuple": {"type": "T1", "metric": [], "space": ["노형동"]}, "card": {"conclusion": "x"}}
        gs = A.gaps("노형동 장사 잘 돼?", {"tuple": r["tuple"]}, r)
        ops = A.options("노형동 장사 잘 돼?", r, {"tuple": r["tuple"]}, gs)
        ms = [o["change"]["metric"][0] for o in ops if o["change"].get("metric")]
        self.assertIn("매출", ms)
        self.assertTrue(set(ms) <= set(dict(A.MAIN_METRICS)) | {"이용건수"})


if __name__ == "__main__":
    unittest.main()
