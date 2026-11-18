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
        line = next((l for l in user.splitlines() if text_part in l and l[:1].isascii() and l[:1].isalpha() and l[1:3] == ". "), "")
        return {"message": {"content": json.dumps({"choice": line.split(".")[0] if line else "0", "reason": "시험"}, ensure_ascii=False)}}
    return chat


class QuestionAgent(unittest.TestCase):
    def setUp(self):
        import result
        self.env = mock.patch.dict(os.environ, {"LLM_BACKEND": "rule"})
        self.env.start()
        self.fix = mock.patch.object(result, "RULE_FIX", False)  # 보정 규칙 없이 Agent가 고치는지 본다
        self.fix.start()

    def tearDown(self):
        self.env.stop()
        self.fix.stop()

    def test_period_gap_recomputes(self):  # 규칙 보정 없이도 Agent가 '질문 기간으로 다시 계산'을 고르면 그 해 값으로 답한다
        r = A.run("2024년 노형동 카드 매출", {}, llm_on=False, chat=pick("질문의 기간"))
        self.assertEqual(r["tuple"].get("ask_year"), 2024)
        self.assertTrue(r["card"]["conclusion"].startswith("2024년 노형동"))
        self.assertEqual(r["question_agent"]["turns"][0]["action"], "다시 계산")
        self.assertIn("질문을 다시 확인해", " ".join(r["understood"]["notes"]))

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


class Honesty20261115(unittest.TestCase):
    """새 정답 기준 ③ 안내 정직성: 대신 쓴 지표·업종 구분 없음·없는 시점을 코드가 밝히고, 질문에 적힌 지표는 바꾸는 선택지를 내지 않는다."""
    def test_honest_notes(self):
        import result as R
        n = R.honest_notes("삼양동 분식집 폐업률", {"metric": ["폐업률"], "target": "분식", "space": ["삼양동"]})
        self.assertTrue(any("음식점 전체" in x and "대신" in x for x in n))
        n = R.honest_notes("노형동 카페 매출", {"metric": ["매출"], "target": "카페", "space": ["노형동"]})
        self.assertTrue(any("세부 업종" in x and "센터" in x for x in n))
        self.assertEqual(R.honest_notes("노형동 카페 매출", {"metric": ["매출"], "target": "카페", "space": ["노형동"]}, center_used=True), [])
        n = R.honest_notes("아라동 편의점 2024년 몇 곳", {"metric": ["점포수"], "target": "편의점", "space": ["아라동"], "ask_year": 2024})
        self.assertTrue(any("2024년 값은 없어요" in x for x in n))
        self.assertEqual(R.honest_notes("노형동 음식점 매출", {"metric": ["매출"], "target": "음식점", "space": ["노형동"]}), [])

    def test_evidenced(self):
        self.assertTrue(A.evidenced("공항 근처 숙박업소 매출 궁금해요", "매출"))
        self.assertTrue(A.evidenced("고령비중 제일 높은 동네", "고령비중"))
        self.assertFalse(A.evidenced("연동은 요즘 발길 많수과?", "점포수"))


class Verify061(unittest.TestCase):
    """결과 검증 넓히기(061): 다시 계산이 질문의 기간·조건·지표 근거를 잃으면 앞 답을 유지한다."""
    def test_lost(self):
        q = "2024년 노형동 매출 알려줘"
        self.assertEqual(A._lost(q, {"ask_year": 2024, "metric": ["매출"]}, {"ask_year": None, "metric": ["매출"]}), "기간")
        self.assertEqual(A._lost(q, {"ask_year": 2024, "metric": ["매출"]}, {"ask_year": 2024, "metric": ["점포수"]}), "지표")
        self.assertEqual(A._lost(q, {"ask_year": 2024, "metric": ["매출"]}, {"ask_year": 2024, "metric": ["매출"]}), "")
        self.assertEqual(A._lost("비 오는 날 연동 방문", {"cond": ["비"], "metric": ["일평균방문"]}, {"cond": [], "metric": ["일평균방문"]}), "조건")


class Stage20261115(unittest.TestCase):
    """마스터 2026-11-15: 기다리는 사람에게 지금 단계·남은 단계를 알린다. 모델 없이(llm 실패 → 지금 답 유지) 단계 순서만 본다."""

    def test_progress_order(self):
        seen = []
        with mock.patch.object(A, "_ask_choice", return_value=({}, None)):
            A.run("노형동 카페 몇 곳이야?", {}, llm_on=False, progress=lambda i, d: seen.append(i))
        self.assertEqual(seen[0], 1)
        self.assertEqual(seen[-1], 4)
        self.assertEqual(seen, sorted(seen))
        self.assertIn(3, seen)

    def test_new_evidence(self):
        self.assertEqual(A.out_evidence("애월읍 해안가 카페 매매가 얼마야?"), "매매가")
        self.assertEqual(A.out_evidence("노형동 카페 몇 곳?"), "")
        self.assertTrue(A.evidenced("화북동 치킨집들 문 많이 닫나요?", "폐업수"))
        self.assertTrue(A.evidenced("오라동 한식집 새로 창업 활발해요?", "개업수"))


class StreamApi20261115(unittest.TestCase):
    def test_stream_lines(self):
        from fastapi.testclient import TestClient
        import api
        with TestClient(api.app).stream("POST", "/api/ask/stream", json={"question": "노형동 카페 몇 곳이야?"}) as r:
            rows = [json.loads(x) for x in r.iter_lines() if x.strip()]
        self.assertIn("ndjson", r.headers["content-type"])
        self.assertTrue(all("stage" in x and x["stage"] <= x["total"] for x in rows[:-1]))
        self.assertIn("result", rows[-1])
        self.assertIn("card", rows[-1]["result"])


class Confirm20261115(unittest.TestCase):
    """사용자 확인 카드(마스터 2026-11-15): 1차 결정·대안·멈춤, 고른 선택지로 다시 계산."""

    def test_card_rules(self):
        rule = {"id": "1", "text": "사전 규칙 해석('현황')대로 답해 보기", "act": "다시 계산", "change": {"rule": True}}
        keep = {"id": "2", "text": "지금 처리 그대로(되묻기·범위 밖 안내)", "act": "답하기", "change": {}}
        c = A.confirm_card(rule, [rule, keep], [{"kind": "범위 밖 판단"}], [{"action": "다시 계산"}], {"status": "범위밖"}, {"status": "성공"})
        self.assertTrue(c["pause"])  # 범위 밖 → 답함으로 바뀜
        self.assertEqual(c["first"]["text"], "질문을 '현황' 질문으로 다시 읽어 계산했어요.")
        self.assertEqual(c["options"][0]["text"], "처음 처리(범위 밖 안내) 그대로 보기")
        c = A.confirm_card(keep, [rule, keep], [{"kind": "범위 밖 판단"}], [{"action": "답하기"}], {"status": "범위밖"}, {"status": "범위밖"})
        self.assertTrue(c["pause"])  # 코드 규칙(첫 다시 계산)과 모델 선택이 다름
        self.assertIn("코드 규칙", c["why"])

    def test_forced(self):
        q = "노형동 카페 몇 곳이야?"
        r2 = A.run(q, {}, llm_on=False, forced="지금 답 그대로")
        self.assertEqual([t["by"] for t in r2["question_agent"]["turns"]], ["사용자"])
        self.assertEqual(r2["confirm"]["forced"], "지금 답 그대로")
        with self.assertRaises(ValueError):
            A.run(q, {}, llm_on=False, forced="없는 선택지")

    def test_no_pause_when_agree(self):
        with mock.patch.object(A, "_ask_choice", return_value=({}, None)):
            c = A.run("노형동 카페 몇 곳이야?", {}, llm_on=False)["confirm"]
        self.assertFalse(c["pause"])


class ChoiceProbs20261115(unittest.TestCase):
    """실험 A: Ollama logprobs에서 선택지 글자 확률을 읽는다(Jev Choice와 같은 모양)."""

    def test_parse(self):
        import math
        lp = lambda tok, alts: {"token": tok, "logprob": math.log(alts[0][1]), "top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in alts]}  # noqa: E731
        lps = [lp("{\n", [("{\n", 1.0)]), lp(' "', [(' "', 1.0)]), lp("choice", [("choice", 1.0)]), lp('":', [('":', 1.0)]), lp(' "', [(' "', 0.97), (" A", 0.03)]),
               lp("A", [("A", 0.8), ("C", 0.15), ("D", 0.05)]), lp('",\n', [('",\n', 1.0)])]
        p = A.choice_probs(lps, ["A", "B", "C"])
        self.assertAlmostEqual(p["A"], 0.8 / 0.95, places=3)  # 선택지에 없는 D는 빼고 정규화
        self.assertEqual(list(p)[0], "A")
        self.assertIsNone(A.choice_probs([], ["A"]))

    def test_letter_ids(self):
        ops = A.options("노형동 카페 몇 곳?", {"status": "성공", "tuple": {"space": ["노형동"], "metric": ["점포수"], "type": "T1"}}, {"tuple": {}}, [])
        self.assertEqual(ops[0]["id"], "A")

    def test_margin_pause(self):
        keep = {"id": "A", "text": "지금 답 그대로", "act": "답하기", "change": {}}
        other = {"id": "B", "text": "지표를 '카드 매출'(으)로 바꿔 다시 계산", "act": "다시 계산", "change": {}}
        c = A.confirm_card(keep, [keep, other], [{"kind": "지표 없음"}], [{"action": "답하기", "margin": 0.3}], {"status": "성공"}, {"status": "성공"})
        self.assertTrue(c["pause"])
        self.assertIn("갈렸어요", c["why"])
        c = A.confirm_card(other, [keep, other], [{"kind": "지표 없음"}], [{"action": "범위 밖", "margin": 0.95}], {"status": "성공"}, {"status": "범위밖"})
        self.assertFalse(c["pause"])  # 확신도가 있으면 확신도로만 정한다


class ClaudeChoice20261116(unittest.TestCase):
    """Claude 키 실험: 모델 이름이 claude-로 시작하면 구조화 출력으로 선택지를 받고 확률은 None."""

    def test_claude_branch(self):
        import llm_claude
        blk = mock.Mock(type="text", text='{"choice": "B"}')
        cl = mock.Mock()
        cl.messages.create.return_value = mock.Mock(content=[blk])
        with mock.patch.object(llm_claude, "client", return_value=cl):
            d, p = A._ask_choice(None, "s", "u", {"type": "object"}, ["A", "B"], model="claude-haiku-5-5")
        self.assertEqual((d, p), ({"choice": "B"}, None))
        self.assertEqual(cl.messages.create.call_args.kwargs["output_config"]["format"]["type"], "json_schema")

    def test_claude_error(self):
        import llm_claude
        with mock.patch.object(llm_claude, "client", side_effect=RuntimeError("no key")):
            self.assertEqual(A._ask_choice(None, "s", "u", {}, ["A"], model="claude-sonnet-5-5"), ({}, None))


class Status20261116(unittest.TestCase):
    """Windows 시험(2026-11-16): Ollama만 있고 qwen2.5:7b가 없으면 질문 담당 Agent를 끄고 까닭을 알린다."""

    def setUp(self):
        A._STATUS.clear()

    def tearDown(self):
        A._STATUS.clear()

    def test_model_missing(self):
        import check_env
        import llm
        with mock.patch.dict(os.environ, {"LLM_BACKEND": "ollama", "JEJU_QUESTION_AGENT": "1"}), \
                mock.patch.object(llm, "_ollama_alive", return_value=True), \
                mock.patch.object(check_env, "ollama_models", return_value={"bge-m3", "qwen3:1.7b"}):
            os.environ.pop("VERCEL", None)
            self.assertEqual(A.status(), (False, "qwen2.5:7b 모델 없음"))

    def test_model_present(self):
        import check_env
        import llm
        with mock.patch.dict(os.environ, {"LLM_BACKEND": "ollama", "JEJU_QUESTION_AGENT": "1"}), \
                mock.patch.object(llm, "_ollama_alive", return_value=True), \
                mock.patch.object(check_env, "ollama_models", return_value={"qwen2.5:7b"}):
            os.environ.pop("VERCEL", None)
            self.assertEqual(A.status(), (True, None))

    def test_vercel_needs_ollama_url(self):
        """Vercel 데모: OLLAMA_URL(Mac mini 터널)이 없으면 끄고, 있으면 Ollama 확인으로 넘어간다(2026-11-18)."""
        import check_env
        import llm
        with mock.patch.dict(os.environ, {"VERCEL": "1", "JEJU_QUESTION_AGENT": "1"}):
            os.environ.pop("OLLAMA_URL", None)
            self.assertEqual(A.status(), (False, "웹 데모(로컬 모델 없음)"))
        A._STATUS.clear()
        with mock.patch.dict(os.environ, {"VERCEL": "1", "JEJU_QUESTION_AGENT": "1", "LLM_BACKEND": "ollama", "OLLAMA_URL": "https://x.ts.net/api/chat"}), \
                mock.patch.object(llm, "_ollama_alive", return_value=True), \
                mock.patch.object(check_env, "ollama_models", return_value={"qwen2.5:7b"}):
            self.assertEqual(A.status(), (True, None))

    def test_missing_lines(self):
        import check_env
        lines = check_env.missing_lines({"bge-m3"})
        self.assertTrue(any("ollama pull qwen2.5:7b" in x for x in lines))
        self.assertEqual(check_env.missing_lines({"bge-m3", "qwen3:1.7b", "qwen2.5:7b"}), [])
        self.assertTrue(any("Ollama가 꺼져" in x for x in check_env.missing_lines(None)))
