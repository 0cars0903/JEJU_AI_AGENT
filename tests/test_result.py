"""W8 결과 생성 시험: 답 카드 순서·수치 대조, 판단 과정, 관문 실패 예측 숨김, M1-b·M3-b LLM 대체 규칙, 내려받기, /api/ask.
해석은 규칙 해석기, LLM은 끄거나 가짜 응답으로 바꿔 Ollama 없이도 같은 결과가 나오게 한다.
실행: .venv/bin/python -m unittest tests.test_result"""
import json
import os
os.environ.setdefault("JEJU_PLAN_AGENT", "0")  # 실제 키로 계획 선택 Agent(안 C)를 부르지 않는다. 동작은 test_plan_agent에서 시험
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import qparse  # noqa: E402
import result as R  # noqa: E402

QS = ["노형동이랑 연동 버스 이용 비교해줘", "노형동 카페 개업 최근 3년 늘었어?", "비 오는 날 아라동 방문은?", "노형동 다음주 방문 예측해줘",
      "탑동 버스 다음달 얼마나 탈까?", "노형동이랑 비슷한 동네는?", "노형동 생활 진단해줘", "센터에 와이파이 자료 있어?", "노형동 카페 5년 생존율은?", "노형동 카페 몇 개야?"]


def RULE(q):
    t = qparse.parse(q)
    return {"tuple": {k: v for k, v in t.items() if not k.startswith("_")}, "card": qparse.card(t), "path": "규칙", "confidence": None, "sec": 0.0}


def ask(q, **kw):
    return R.respond(q, kw.pop("env", None), llm_on=kw.pop("llm_on", False), interpret=RULE, **kw)


def fake_llm(text):
    return mock.patch.object(R.llm, "chat", return_value={"message": {"content": text}})


class Card(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {q: ask(q) for q in QS}

    def test_card_fields_and_number_check(self):
        for q, r in self.out.items():
            if "card" not in r or r["status"] == "범위밖":  # 범위 밖은 답을 만들지 않는다(v3: 버스 예상)
                continue
            c = r["card"]
            for k in ("conclusion", "evidence", "intervals", "limits", "next_questions"):
                self.assertIn(k, c, q)
            self.assertEqual(c["number_check"], [], q)  # 결론·근거·구간 수치는 모두 결과 저장소에 있다
            self.assertEqual(len(c["next_questions"]), 3, q)
            self.assertTrue(c["conclusion"], q)

    def test_evidence_has_dataset_and_as_of(self):
        for q, r in self.out.items():
            for e in r.get("card", {}).get("evidence", []):
                if e.get("layer") in (None, "L1"):  # v3: 과거 기록 줄은 자료와 기준 시점을 단다(판정·예상 줄은 근거 출처만)
                    self.assertTrue(e.get("dataset") and e.get("as_of"), (q, e))
                # 판정·예상·판단 재료 줄은 Agent 계산이라 출처를 달지 않는다(내부 이름 노출 제거, 2026-11-12)

    def test_bus_forecast_excluded(self):  # v3: 버스 예상(R2)은 제외하고 범위 밖으로 안내(문서 18)
        r = self.out["탑동 버스 다음달 얼마나 탈까?"]
        self.assertEqual(r["status"], "범위밖")
        self.assertIn("버스 이용 예상은 하지 않아요", r["card"]["conclusion"])

    def test_passed_gate_shows_forecast_and_interval(self):
        c = self.out["노형동 다음주 방문 예측해줘"]["card"]
        self.assertTrue(any(e.get("kind") == "forecast" for e in c["evidence"]))
        self.assertTrue(any("예상 범위" in x for x in c["intervals"]))
        self.assertFalse(any(w in x for x in c["intervals"] for w in ("R1", "관문", "포함률")))  # 내부 용어를 화면에 내지 않는다(문서 20 A2·A10)
        self.assertTrue(any("지수" in x for x in c["limits"]))  # 유동인구는 지수

    def test_conclusions_by_type(self):
        self.assertIn("보다 많아요", self.out["노형동이랑 연동 버스 이용 비교해줘"]["card"]["conclusion"])
        self.assertIn("카페 개업 수", self.out["노형동 카페 개업 최근 3년 늘었어?"]["card"]["conclusion"])  # 판정 결과는 자료 갱신에 따라 바뀜
        self.assertIn("비슷한 동네", self.out["노형동이랑 비슷한 동네는?"]["card"]["conclusion"])
        self.assertTrue(self.out["노형동 카페 5년 생존율은?"]["card"]["conclusion"].startswith("카페 5년 생존율"))
        d = self.out["노형동 생활 진단해줘"]  # v3: 상권 종합 진단은 판단 재료(수요·경쟁·생존) 요약이 결론
        self.assertEqual(d["answer"]["conclusion"]["tag"], "판단할 때 볼 것")
        self.assertIn("guide", [b["id"] for b in d["answer"]["blocks"]])
        self.assertIn("차이", self.out["비 오는 날 아라동 방문은?"]["card"]["conclusion"])

    def test_process(self):
        p = self.out["노형동 다음주 방문 예측해줘"]["process"]
        self.assertEqual([s["sub"] for s in p["steps"]], ["S1", "S2", "S3", "S6", "S4"])
        self.assertTrue(all(s["status"] == "성공" for s in p["steps"]))
        self.assertIn("583 유동인구", p["data"])
        self.assertEqual(p["explain"]["by"], "템플릿")

    def test_downloads_csv(self):
        d = self.out["노형동이랑 연동 버스 이용 비교해줘"]["downloads"]
        csv = next(x for x in d if x["kind"] == "csv")
        self.assertTrue(csv["csv"].startswith("dong,ym,value"))
        self.assertEqual(csv["rows"], len(csv["csv"].strip().splitlines()) - 1)
        b = d[0]  # v3 패턴 I: 이 답의 자료 묶음(긴 형식)이 맨 앞
        self.assertEqual(b["kind"], "bundle")
        self.assertTrue(b["csv"].startswith("자료,지표,대상,시점,값,단위"))

    def test_partial_result_says_what_failed(self):
        r = ask("노형동 카페 개업 최근 3년 늘었어?", env={"center_db": False, "inject": {"t2": "계산"}, "inject_persist": True})
        self.assertEqual(r["status"], "부분 결과")
        self.assertTrue(any("계산하지 못함" in x for x in r["card"]["limits"]))
        self.assertTrue(r["process"]["unused"])


class Understood(unittest.TestCase):
    """되묻기 Loop 방지(2026-11-11 17:25): 추정해서 답하고 '이렇게 이해했어요'를 붙인다. 추정할 수 없을 때만 선택필요."""

    def test_assumes_instead_of_asking(self):
        r = ask("노형동 카페 몇 개야?")
        self.assertEqual(r["status"], "성공")
        self.assertIn("노형동", r["understood"]["text"])
        self.assertEqual(r["understood"]["slots"]["topic"], "stores")

    def test_no_dong_goes_to_choice(self):
        r = ask("카페 몇 개야?")
        self.assertEqual(r["status"], "선택필요")
        self.assertEqual(r["choose"]["step"], "space")
        self.assertIn("동네", r["choose"]["message"])
        nxt = R.respond(None, {"center_db": False}, llm_on=False, slots=dict(r["choose"]["preset"], space=["노형동"]))
        self.assertEqual(nxt["status"], "성공")  # 고른 뒤에는 다시 묻지 않는다

    def test_low_confidence_goes_to_topic_choice(self):  # A: 확신도가 낮으면 추정하지 않는다
        low = lambda q: dict(RULE(q), confidence=0.3)  # noqa: E731
        r = R.respond("노형동 카페 몇 개야?", None, llm_on=False, interpret=low)
        self.assertEqual((r["status"], r["choose"]["step"]), ("선택필요", "topic"))
        self.assertEqual(r["choose"]["preset"]["space"], ["노형동"])

    def test_unsupported_axis_blocked(self):  # A: 답할 수 없는 축(버스 시간대)은 다른 지표로 바꿔 답하지 않는다
        r = ask("노형동 버스 몇 시에 붐벼?")
        self.assertEqual(r["status"], "범위밖")
        self.assertIn("시간대", r["card"]["conclusion"])

    def test_sales_and_hour_answered(self):  # v3: 매출·상권 시간대는 카드 자료로 답한다
        for q in ["노형동 카페 매출은?", "노형동 카페 몇 시에 손님 많아?"]:
            r = ask(q)
            self.assertIn(r["status"], ("성공", "no_significant_effect", "부분 결과"), q)
            self.assertTrue(any("제주관광공사" in str(e.get("dataset")) for e in r["card"]["evidence"]), q)
            self.assertTrue(any("음식점업 전체 기준" in x for x in r["card"]["limits"]), q)

    def test_dong_only_is_diagnosis(self):  # B: 동네 이름만 넣으면 종합 진단
        for q in ["노형동", "노형동 어때?", "탑동"]:
            r = ask(q)
            self.assertEqual(r["tuple"]["type"], "T10", q)
            self.assertTrue(r["understood"]["assumed"], q)

    def test_out_of_scope_blocked(self):
        r = ask("노형동 임대료 얼마야?")
        self.assertEqual(r["status"], "범위밖")
        self.assertNotIn("understood", r)
        self.assertEqual(len(r["suggestions"]), 3)


class Explain(unittest.TestCase):
    Q = "노형동이랑 연동 버스 이용 비교해줘"  # 경로: 조회 → 차트

    def setUp(self):  # 다른 시험이 .env를 읽어 Claude 키가 생겨도 가짜 응답(Ollama 형식)과 맞게 백엔드를 고정한다
        self._b = mock.patch.object(R.llm, "backend", return_value="ollama")
        self._b.start()

    def tearDown(self):
        self._b.stop()

    def test_llm_used_when_valid(self):
        with fake_llm("버스 이용 자료에서 두 동네 값을 모아 그래프로 정리했어요."):  # v3: 해요체
            self.assertEqual(ask(self.Q, llm_on=True)["process"]["explain"]["by"], "LLM")

    def test_rejections(self):
        for bad in ["버스 이용을 비교했습니다. 노형동이 3622명입니다.",  # 숫자
                    "두 동네 차이가 우연인지 판정했습니다.",  # 없는 단계(S6)
                    "모델로 다음 달을 예측했습니다.",  # 없는 단계(S3)
                    "버스 이용을 비교해 보자"]:  # 문체
            with fake_llm(bad):
                e = ask(self.Q, llm_on=True)["process"]["explain"]
            self.assertEqual(e["by"], "템플릿(LLM 대체)", bad)
            self.assertNotIn("3622", e["text"])

    def test_claude_tool_output(self):
        text = "버스 이용 자료에서 두 동네 값을 모아 그래프로 정리했어요."
        reply = {"message": {"content": "", "tool_calls": [{"id": "c", "function": {"name": "submit_plan_text", "arguments": {"text": text}}}]}}
        with mock.patch.object(R.llm, "backend", return_value="claude"), mock.patch.object(R.llm, "chat", return_value=reply) as ch:
            e = ask(self.Q, llm_on=True)["process"]["explain"]
        self.assertEqual((e["by"], e["text"], e["backend"]), ("LLM", text, "claude"))
        self.assertEqual(ch.call_args.kwargs.get("effort"), "low")
        self.assertTrue(ch.call_args.args[2][0]["function"]["strict"])

    def test_ollama_json_output(self):
        with mock.patch.object(R.llm, "backend", return_value="ollama"), \
                fake_llm('{"text": "버스 이용 자료에서 두 동네 값을 모아 그래프로 정리했어요."}') as ch:
            e = ask(self.Q, llm_on=True)["process"]["explain"]
        self.assertEqual(e["by"], "LLM")
        self.assertIn("required", ch.call_args.kwargs["fmt"])

    def test_rewrite_after_rejection(self):  # 안 B(문서 26): 걸린 문장과 이유를 돌려 다시 쓰게 한다
        good = "버스 이용 자료에서 두 동네 값을 모아 그래프로 정리했어요."
        replies = [{"message": {"content": "노형동이 3622명입니다."}}, {"message": {"content": good}}]
        with mock.patch.object(R.llm, "chat", side_effect=replies) as ch:
            e = ask(self.Q, llm_on=True)["process"]["explain"]
        self.assertEqual((e["by"], e["text"], e["rewrites"]), ("LLM", good, 1))
        self.assertIn("검사에서 걸린 이유", ch.call_args_list[1].args[1][-1]["content"])

    def test_rewrite_limit_then_template(self):
        with fake_llm("노형동이 3622명입니다.") as ch:
            e = ask(self.Q, llm_on=True)["process"]["explain"]
        self.assertEqual((e["by"], e["rewrites"]), ("템플릿(LLM 대체)", R.REWRITES))
        self.assertEqual(ch.call_count, R.REWRITES + 1)

    def test_llm_down(self):
        with mock.patch.object(R.llm, "chat", side_effect=OSError("down")):
            self.assertEqual(ask(self.Q, llm_on=True)["process"]["explain"]["by"], "템플릿(LLM 대체)")


class Api(unittest.TestCase):
    def test_ask(self):
        from fastapi.testclient import TestClient
        import api
        with mock.patch.object(api.llm, "backend", return_value="rule"):
            r = TestClient(api.app).post("/api/ask", json={"question": "노형동이랑 연동 버스 이용 비교해줘"})
        self.assertEqual(r.status_code, 200)
        js = r.json()
        self.assertIn("card", js)
        self.assertIn("process", js)


class Escalate(unittest.TestCase):  # 중간안: 일반 경로가 못 풀면 Agent에게 넘긴다
    def _it(self, rule_type):
        t = {"type": "T12", "metric": [], "target": None, "space": ["노형동"], "time": None, "time_year": None, "breakdown": None, "cond": [], "form": "수치", "expect": "범위밖"}
        return lambda q: {"tuple": t, "card": {"text": "지금 자료로는 답할 수 없어요"}, "confidence": 0.4, "needs_confirm": True, "rule_type": rule_type, "path": "B3"}

    def test_classifier_only_out_of_scope_goes_to_agent(self):
        ok = {"status": "성공", "lines": ["센터 자료로 볼 수 있어요."], "trace": []}
        with mock.patch("expert.ask", return_value=ok) as ag:
            r = R.respond("노형동 펫카페 손님 어때", {"agent_ok": True}, llm_on=True, interpret=self._it("T1"))
        self.assertEqual(r["status"], "Agent")
        self.assertEqual(ag.call_args.kwargs.get("mode"), "escalate")

    def test_rule_also_out_of_scope_is_blocked(self):
        with mock.patch("expert.ask") as ag:
            r = R.respond("노형동 펫카페 손님 어때", {"agent_ok": True}, llm_on=True, interpret=self._it("T12"))
        self.assertEqual(r["status"], "범위밖")
        ag.assert_not_called()

    def test_no_agent_without_permission(self):
        with mock.patch("expert.ask") as ag:
            r = R.respond("노형동 펫카페 손님 어때", {}, llm_on=True, interpret=self._it("T1"))
        self.assertEqual(r["status"], "범위밖")
        ag.assert_not_called()


class CheckLine(unittest.TestCase):  # 검수·재실행 라인 3단계: LLM이 풀지 못한 의심 칸을 이해 카드에 쉬운 말로
    def test_expect_disagreement_asks_human(self):
        it = {"tuple": {"type": "T1", "expect": "답함", "space": ["노형동"]}, "rule_type": "T1", "rule_expect": "되묻기", "needs_confirm": False, "confidence": 0.9}
        c = R._to_check("노형동 가게 몇 개", it)
        self.assertEqual([x["field"] for x in c], ["expect"])
        self.assertNotIn("분류기", c[0]["text"])  # 도민 화면에 내부 용어를 쓰지 않는다

    def test_type_disagreement_only_without_agent(self):
        it = {"tuple": {"type": "T1", "expect": "답함"}, "rule_type": "T4", "rule_expect": "답함", "needs_confirm": False, "confidence": 0.9}
        self.assertEqual([x["field"] for x in R._to_check("q", it)], ["type"])
        self.assertEqual(R._to_check("q", dict(it, plan_agent={"kept": True})), [])  # 계획 선택 Agent가 이미 봤으면 묻지 않는다


class RankFix20261115(unittest.TestCase):
    """최종 평가(2026-11-14) 결함: 폐업·개업 순위가 가나다순, '낮은 동네'가 단일 조회, 지표 순서, '잘 돼'가 점포 수, 동네 생존율 결론이 제주 전체."""
    def conc(self, q):
        return R.respond(q, None, llm_on=False)["card"]["conclusion"]

    def test_close_rank_by_value(self):
        c = self.conc("폐업이 가장 많은 동네는?")
        self.assertIn("1위 애월읍", c)
        self.assertNotIn("건입동", c)

    def test_open_rank_low(self):
        self.assertIn("작은 순서", self.conc("개업이 가장 적은 동네"))

    def test_low_without_superlative_is_rank(self):
        c = self.conc("생존율 낮은 동네는?")
        self.assertIn("순위", c)
        self.assertIn("작은 순서", c)

    def test_metric_named_first(self):
        self.assertIn("폐업률 순위", self.conc("폐업률이 제일 높은 동네"))

    def test_jal_dwae_is_sales(self):
        self.assertIn("매출 순위", self.conc("카페 어디가 제일 잘 돼?"))

    def test_dong_survival_conclusion(self):
        self.assertTrue(self.conc("노형동 생존율 낮아?").startswith("노형동"))


class Misfire20261115(unittest.TestCase):
    """최종 내부 평가(2026-11-14)의 오작동 질문 20개: 기간·대체 지표 안내·조건·과차단·자료 찾기."""
    @classmethod
    def setUpClass(cls):
        cls.r = {}

    def ask(self, q):
        if q not in self.r:
            self.r[q] = R.respond(q, None, llm_on=False)
        return self.r[q]

    def conc(self, q):
        return self.ask(q)["card"]["conclusion"]

    def notes(self, q):
        return " ".join((self.ask(q).get("understood") or {}).get("notes", []))

    def test_period(self):
        self.assertTrue(self.conc("2024년 노형동 카드 매출").startswith("2024년 노형동"))
        self.assertTrue(self.conc("작년 노형동 매출").startswith(f"{__import__('datetime').date.today().year - 1}년"))
        self.assertTrue(self.conc("2025년 7월 노형동 매출").startswith("2025년 7월"))
        self.assertIn("7월", self.conc("7월 연동 방문객"))
        self.assertIn("자료는 없어요", self.conc("2019년 노형동 매출"))
        self.assertTrue(self.conc("2024년 노형동 폐업").startswith("2024년"))

    def test_catalog(self):
        self.assertIn("6종", self.conc("센터에 와이파이 자료 있어?"))
        self.assertIn("업종 칸", self.conc("센터에 숙박 자료 있어?"))
        self.assertIn("찾지 못했어요", self.conc("센터에 주차장 자료 있어?"))
        self.assertEqual(self.ask("버스 자료 뭐 있어?")["tuple"]["type"], "T11")

    def test_substitute_metric_with_note(self):
        self.assertIn("1건당 금액", self.conc("비싼 식당 많은 동네"))
        self.assertIn("메뉴 가격", self.notes("비싼 식당 많은 동네"))
        self.assertIn("연령", self.conc("노형동 인구"))
        self.assertIn("인구 수", self.notes("노형동 인구"))
        self.assertIn("관광객 매출 비중 순위", self.conc("관광객 많은 동네 순위"))
        self.assertIn("15시", self.conc("오후 3시에 노형동 사람 많아?"))
        self.assertIn("센터 유동인구", self.notes("오후 3시에 노형동 사람 많아?"))

    def test_conditions(self):
        self.assertIn("눈 온 날", self.notes("눈 오는 날 매출 많은 동네"))
        self.assertNotIn("비", self.ask("눈 오는 날 매출 많은 동네")["tuple"].get("cond") or [])
        self.assertTrue(self.conc("비가 올 때 노형동 매출").startswith("비에 따른 노형동"))
        self.assertIn("하루 단위 매출", self.notes("비가 올 때 노형동 매출"))

    def test_recent_months(self):  # '최근 3개월'은 마지막 3개월 합계(2026-11-15)
        c = self.conc("노형동 최근 3개월 매출")
        self.assertTrue(c.startswith("최근 3개월"))
        self.assertIn("합계", c)

    def test_not_overblocked(self):
        self.assertNotIn("제주 밖", self.conc("대구탕 집 많은 동네"))
        self.assertNotIn("제주 밖", self.conc("광주광역시 말고 제주 노형동 매출"))
        self.assertIn("노형동", self.conc("광주광역시 말고 제주 노형동 매출"))


if __name__ == "__main__":
    unittest.main()


class LayersV3(unittest.TestCase):  # v3 답 구조(docs/기획/v3_설계.md 6절)
    @classmethod
    def setUpClass(cls):
        cls.value = ask("노형동에 카페 차려도 될까?")
        cls.market = R.respond(slots={"topic": "market", "target": "음식점"}, llm_on=False)
        cls.sales_fc = R.respond(slots={"topic": "forecast", "space": ["노형동"], "target": "음식점", "variant": "sales"}, llm_on=False)

    def test_value_question_gives_materials_not_refusal(self):  # L5: 첫 문장이 거절이 아니고 신호를 먼저, 판단은 직접
        a = self.value["answer"]
        self.assertEqual(a["conclusion"]["layer"], "L5")
        self.assertFalse(a["conclusion"]["text"].startswith(("판단하지", "답할 수")))
        g = next(b for b in a["blocks"] if b["id"] == "guide")
        self.assertIn("직접 판단", g["closing"])
        self.assertTrue(any("43곳 중" in x["text"] for x in g["lines"]))

    def test_money_is_readable_and_checked(self):  # 금액은 억 원, 수치 대조 통과
        txt = " ".join(x["text"] for b in self.market["answer"]["blocks"] for x in b["lines"])
        self.assertIn("억 원", txt)
        self.assertEqual(self.market["card"]["number_check"], [])

    def test_market_views_default_three_plus_more(self):
        v = [x["id"] for x in self.market["answer"]["views"]]
        self.assertGreaterEqual(len(v), 4)
        self.assertIn("index", v)  # 두 자료 지수(겹치는 17개월 평균 = 100)
        self.assertEqual(self.market["answer"]["default_views"], 3)

    def test_failed_gate_shows_reference_not_forecast(self):  # R10 관문 실패: 예상 수치 없음, 작년 같은 달 비교 값·최근 검증 기록·갱신 요청
        a = self.sales_fc["answer"]
        lines = [x for b in a["blocks"] for x in b["lines"]]
        self.assertFalse(any(x.get("kind") == "forecast" for x in lines))
        self.assertTrue(any(x.get("kind") == "reference" and "예상 아님" in x["text"] for x in lines))
        self.assertTrue(any(x["tag"] == "검증 기록" for x in lines))
        self.assertIn("validation", [v["id"] for v in a["views"]])
        self.assertTrue(any(r["kind"] == "update" for r in a["requests"]))
        self.assertEqual(self.sales_fc["card"]["number_check"], [])

    def test_freshness_listed(self):
        self.assertTrue(all("months_old" in f for f in self.market["answer"]["freshness"]))



class Persona20(unittest.TestCase):  # 페르소나 사용성 점검 지적의 수정 확인(docs/조사/20_페르소나_사용성점검.md)
    def lines(self, r):
        return [x for b in r["answer"]["blocks"] for x in b["lines"]]

    def test_suggested_sentence_is_read_back(self):  # A1: 제안 문장을 그대로 넣으면 같은 뜻으로 답한다
        r = ask("노형동 숙박 카드 매출 흐름은?")
        self.assertNotEqual(r["status"], "선택필요")
        self.assertEqual(r["understood"]["slots"]["topic"], "sales")

    def test_forecast_says_which_days(self):  # A2: 예상이 어느 날짜 값인지와 범위의 뜻을 쉬운 말로 알린다
        r = ask("노형동 다음주 방문 예측해줘")
        self.assertIn("오늘 기준 다음 주가 아니에요", r["answer"]["conclusion"]["text"])
        self.assertTrue(any(x["kind"] == "update" and "유동인구" in x["title"] for x in r["answer"]["requests"]))
        self.assertEqual(r["card"]["number_check"], [])

    def test_detail_business_counted_by_minor_class(self):  # A3: 국수집은 '국수/칼국수' 분류로 세고, 그 사실을 알린다
        r = ask("애월읍 국수집 몇 개야?")
        self.assertIn("애월읍 국수 점포 수", r["answer"]["conclusion"]["text"])
        self.assertTrue(any("국수/칼국수" in n for n in r["understood"]["notes"]))
        self.assertTrue(all(x["tag"] is None or "최신 단면" not in x["tag"] for x in self.lines(r)))  # A10: 날짜 없는 기준 표기를 쓰지 않는다

    def test_detail_businesses_compared_in_one_dong(self):  # A9: 한 동네 안에서 세부 업종끼리는 점포 수로 견주고, 매출은 받을 곳을 알린다
        r = ask("노형동 카페와 디저트 비교")
        self.assertEqual(r["understood"]["slots"]["details"], ["디저트", "카페"])
        self.assertIn("노형동에서는", r["answer"]["conclusion"]["text"])
        self.assertTrue(any(x["kind"] == "center" for x in r["answer"]["requests"]))
        self.assertEqual(r["card"]["number_check"], [])
        again = R.respond(None, None, llm_on=False, slots=r["understood"]["slots"])  # 주소·다시 계산에서도 같은 답
        self.assertEqual(again["answer"]["conclusion"]["text"], r["answer"]["conclusion"]["text"])

    def test_my_dong_asks_for_a_dong(self):  # A9: '우리 동네'는 위치를 모른다고 알리고 동네를 고르게 한다
        r = ask("우리 동네 카페 몇 개야")
        self.assertEqual(r["status"], "선택필요")
        self.assertIn("위치 정보를 쓰지 않아서", r["choose"]["message"])

    def test_foreign_spending_is_consistent(self):  # A9: 외국인 소비는 물을 때마다 같은 자료(제주 전체 출신지역)로 답하고 동네별 값은 받을 곳을 알린다
        cs = [ask(q)["answer"]["conclusion"]["text"] for q in ("외국인 소비 많은 동네", "연동 외국인 매출 알려줘", "외국인 관광객은 어디서 많이 써?")]
        self.assertTrue(cs[1].startswith("연동만 따로 센 자료는 없어 제주 전체 값이에요. "))  # 동네를 물었으면 결론 앞에 밝힌다(문서 20 7.5절 11번)
        self.assertEqual(len({c.replace("연동만 따로 센 자료는 없어 제주 전체 값이에요. ", "") for c in cs}), 1)
        self.assertIn("출신지역", cs[0])
        self.assertTrue(any(x["kind"] == "center" and "외국인" in x["title"] for x in ask("연동 외국인 매출 알려줘")["answer"]["requests"]))

    def test_rank_conclusion_names_the_rank(self):  # A9: 순위 질문의 결론은 1위 한 곳의 값이 아니라 1~3위를 밝힌다
        r = ask("기념품 소매점 납품할 동네 순위")
        self.assertIn("1위 애월읍", r["answer"]["conclusion"]["text"])
        self.assertIn("3위", r["answer"]["conclusion"]["text"])
        self.assertEqual(r["card"]["number_check"], [])

    def test_five_businesses_answer_store_count_only(self):  # 7.5절 3번: 미용실·약국·학원·병원·부동산중개는 가게 수만 답한다
        import pandas as pd
        b = pd.read_parquet(ROOT / "data" / "tables" / "biz.parquet")
        for w in ("미용실", "약국", "학원", "병원", "부동산중개", "치과"):
            self.assertTrue(set(qparse.DETAIL[w]["names"]) <= set(b["minor"]), w)  # 세는 분류 이름이 상가 정보 표에 있다
        self.assertNotIn("동물병원", qparse.DETAIL["병원"]["names"])
        n = int(b[(b["dong"] == "노형동") & (b["minor"] == "미용실")]["count"].sum())
        r = ask("노형동 미용실 몇 곳이야?")
        self.assertEqual(r["status"], "성공")
        self.assertIn(f"노형동 미용실 점포 수는 {n}곳", r["answer"]["conclusion"]["text"])
        self.assertTrue(any("'미용실' 분류" in x for x in r["understood"]["notes"]))
        self.assertTrue(any("동물병원 제외" in x for x in ask("이도2동 병원은 몇 곳?")["understood"]["notes"]))  # 어느 분류로 셌는지 알린다
        self.assertEqual(ask("노형동 학원 수 알려줘")["tuple"]["metric"], ["점포수"])
        self.assertEqual(ask("노형동 부동산 몇 곳")["tuple"]["detail"], "부동산중개")
        self.assertEqual(ask("노형동 동물병원 몇 곳")["tuple"]["detail"], "동물병원")  # '병원'으로 세지 않는다
        self.assertIsNone(qparse.parse("노형동 부동산 가격 오를까").get("detail"))  # 가게 수를 묻지 않은 '부동산'은 중개업소로 읽지 않는다
        for q, why in [("노형동 미용실 카드 매출 알려줘", "42개 업종"), ("연동 미용실 개업 추이", "음식점 인허가")]:
            r = ask(q)
            self.assertEqual(r["status"], "범위밖", q)
            self.assertIn("가게 수만 볼 수 있어요", r["card"]["conclusion"], q)
            self.assertIn(why, r["card"]["conclusion"], q)
            self.assertEqual(r["suggestions"][0]["slots"]["detail"], "미용실", q)  # 대신 볼 수 있는 가게 수 질문을 준다
        nxt = R.respond(slots=ask("노형동 미용실 카드 매출 알려줘")["suggestions"][0]["slots"], llm_on=False)
        self.assertIn(f"{n}곳", nxt["answer"]["conclusion"]["text"])
        self.assertNotEqual(ask("노형동 병원 가는 버스 이용 얼마나 돼")["card"]["conclusion"][:12], "병원은 가게 수만 볼")  # 버스·방문 질문은 막지 않는다

    def test_views_carry_unit_and_plain_block_name(self):  # A10: 그래프·표에 단위를 싣고, 묶음 이름은 쉬운 말로 쓴다
        units = {v["id"]: v.get("unit") for v in R.respond(slots={"topic": "visit", "space": ["노형동"]}, llm_on=False)["answer"]["views"]}
        self.assertEqual(units.get("monthly"), "지수")
        d = ask("노형동에 카페 차려도 될까?")["answer"]
        self.assertEqual(d["blocks"][-1]["title"], "판단할 때 볼 것")
        self.assertNotIn("판단 재료", json.dumps(d, ensure_ascii=False))


class Report21(unittest.TestCase):  # 보고서 개편(docs/조사/21_보고서_조건패널_개편_조사와계획.md 6.1절)
    @classmethod
    def setUpClass(cls):
        cls.r = ask("노형동 카페 차려도 될까?")
        cls.lines = [x for b in cls.r["answer"]["blocks"] for x in b["lines"]]

    def text(self, word):
        return next(x["text"] for x in self.lines if word in x["text"])

    def test_diagnosis_carries_model_lines(self):  # 1단계: 종합 진단에 모델 결과(L4)가 붙고, 순서는 생존 → 방문 예상 → 닮은 동네 → 매출 예상
        ana = [x for x in self.lines if x["block"] == "analysis"]
        self.assertGreaterEqual(sum(x["layer"] == "L4" for x in ana), 5)
        idx = [next(i for i, x in enumerate(ana) if w in x["text"]) for w in ("영업 중이었어요", "하루 방문 예상", "닮은 동네", "예상하지 않아요")]
        self.assertEqual(idx, sorted(idx))
        self.assertIn("survcurve", [v["id"] for v in self.r["answer"]["views"]])

    def test_forecast_range_and_gate_fail_wording(self):  # 3단계: 예상 범위·포함률, 관문 탈락은 예상하지 않고 작년 같은 달 값
        self.assertRegex(self.text("하루 방문 예상"), r"예상 범위까지 보면 [\d,]+ 지수~[\d,]+ 지수")
        self.assertIn("100번 중 78~83번", self.text("검증 기록"))  # 문서 22: 검증 회차 오차로 범위 보정(이전 66~74번)
        no = self.text("예상하지 않아요")
        self.assertIn("작년 같은 달", no)
        self.assertIn("(예상 아님)", no)
        body = " ".join(x["text"] for x in self.lines)
        for w in ("MASE", "R1", "R10", "레시피"):  # 본문에 내부 문구를 쓰지 않는다
            self.assertNotIn(w, body)

    def test_side_step_failure_does_not_block(self):  # 곁가지 단계가 실패해도 다른 줄은 나온다
        import recipes
        with mock.patch.object(recipes, "r5", side_effect=RuntimeError("x")):
            r = ask("노형동 카페 차려도 될까?")
        ls = [x["text"] for b in r["answer"]["blocks"] for x in b["lines"]]
        self.assertFalse(any("닮은 동네" in x for x in ls))
        self.assertTrue(any("영업 중이었어요" in x for x in ls))
        self.assertIn("card", r)

    def test_composite_values_match_tables(self):  # 2단계: 복합 지표를 표에서 다시 계산해 대조한다
        import pandas as pd
        import places
        import v3
        T = ROOT / "data" / "tables"
        x = v3.composite("노형동", "카페", "음식점업", cats=places.REST_MAP["카페"])
        c = pd.read_parquet(T / "card_month.parquet")
        c = c[(c["biz"] == "음식점업") & (c["dong"] == "노형동")]
        m = c[c["ym"] == c["ym"].max()].set_index("cust")
        for cust in ("도민", "내국인 관광객"):
            self.assertAlmostEqual(x["ticket"]["by"][cust]["value"], m.loc[cust, "amt"] / m.loc[cust, "cnt"], places=6)
        b = pd.read_parquet(T / "biz.parquet")
        b = b[b["dong"].isin(v3.meta()["dongs"])]
        cafe = b[(b["major"] == "음식") & (b["minor"].str.contains("카페") | b["middle"].str.contains("카페"))]
        n = cafe[cafe["dong"] == "노형동"]["count"].sum()
        pm = pd.read_parquet(T / "pop_month.parquet")
        pm = pm[(pm["dong"] == "노형동")].sort_values("ym").tail(12)
        self.assertAlmostEqual(x["density"]["value"], n / (pm["visit"].sum() / pm["days"].sum() / 1e4), places=6)
        lq = (n / b[b["dong"] == "노형동"]["count"].sum()) / (cafe["count"].sum() / b["count"].sum())
        self.assertAlmostEqual(x["lq"]["value"], lq, places=6)
        h = pd.read_parquet(T / "card_hour.parquet")
        h = h[(h["dong"] == "노형동") & (h["biz"] == "음식점업") & (h["ym"] >= "2025-10")]
        self.assertAlmostEqual(x["hours"]["peak_pct"], (h.groupby("hour")["amt"].sum() / h["amt"].sum() * 100).max(), places=6)
        self.assertAlmostEqual(sum(p[1] for p in x["hours"]["points"]), 100, places=0)
        e = pd.read_parquet(T / "rest_events.parquet")
        e = e[(e["dong"] == "노형동") & e["category"].isin(places.REST_MAP["카페"]) & (e["year"] == 2025)].groupby("kind")["count"].sum()
        self.assertEqual((x["net"]["rows"][-1]["year"], x["net"]["rows"][-1]["net"]), (2025, int(e["open"] - e["close"])))
        y = c[c["ym"].str[:4] == "2025"]["amt"].sum()
        self.assertAlmostEqual(x["yearly"]["rows"][-1]["amt"], y, places=0)

    def test_composite_lines_shown_with_basis(self):  # 복합 지표 줄은 계산식을 출처에 적고, 유동인구는 '명'으로 쓰지 않는다
        kinds = {x.get("kind"): x for x in self.lines}
        for k in ("ticket", "density", "lq", "hours", "net", "yearly3"):
            self.assertIn(k, kinds, k)
        self.assertIn("÷", kinds["ticket"]["source"])
        self.assertIn("÷", kinds["density"]["source"])
        self.assertNotRegex(kinds["density"]["text"], r"\d명")
        self.assertIn("hour", [v["id"] for v in self.r["answer"]["views"]])


    def test_rent_is_reference_only(self):
        """임대료는 시도 단위 참고값만, 권리금은 값 없이 현장 확인으로 남긴다(사용자 승인 2026-11-12)."""
        a = ask("노형동에 카페 차려도 될까?")["answer"]
        g = next(b for b in a["blocks"] if b["id"] == "guide")
        line = next(x for x in g["lines"] if "임대료·권리금" in x["text"])
        self.assertIn("119만 원", line["text"])
        self.assertIn("현장에서 확인", line["text"])
        self.assertTrue(any("임대료·권리금" in q["title"] for q in a["requests"]))
        self.assertFalse(any("임대료" in q["title"] for q in ask("노형동 카페 수")["answer"]["requests"]))

    def test_methods_explain_each_model(self):  # 4단계: 모델마다 방법·검증·쓸 수 없는 경우가 있고 내부 이름을 쓰지 않는다
        ms = {m["kind"]: m for m in self.r["answer"]["methods"]}
        self.assertLessEqual({"forecast", "salesfc", "survival", "similar", "season", "anomaly", "rain"}, set(ms))
        for m in ms.values():
            self.assertTrue(m["how"] and m["check"] and m["limit"], m["kind"])
            self.assertNotRegex(" ".join(m.values()), r"MASE|ARI|R\d+\b|레시피|관문|fallback")
        self.assertRegex(ms["forecast"]["result"], r"기준의 약 \d+%.*100번 중 \d+~\d+번")
        self.assertIn("보여 주지 않아요", ms["salesfc"]["result"])
        # 문서 22: 단순 주제에도 곁가지 모델(생존·비슷한 동네 위치)이 붙어 그 설명만 나온다
        self.assertEqual({m["kind"] for m in ask("노형동 카페 수")["answer"]["methods"]}, {"survival", "similar"})


class Fix21(unittest.TestCase):  # 문서 21 6.1절 6단계: 오동작 수정과 넘어온 결정(문서 20 7.5절 11번, 정답 세트 B138·B141·B142)
    def lines(self, q):
        r = ask(q)
        self.assertEqual(r["status"], "성공", q)
        return r, [x for b in r["answer"]["blocks"] for x in b["lines"]]

    def test_season_similar_uses_monthly_curve(self):  # '계절 흐름이 비슷한 동네'는 월별 방문 곡선으로 찾는다
        r, ls = self.lines("노형동이랑 계절 흐름 비슷한 동네는?")
        self.assertIn("R6", [s.get("recipe") for s in r["process"]["steps"]])
        self.assertIn("월별 방문 흐름이 가까운 동네", r["answer"]["conclusion"]["text"])
        r2, _ = self.lines("노형동이랑 비슷한 동네는?")  # 기준을 말하지 않으면 기존대로 업종·연령·방문·버스 유사도
        self.assertIn("R5", [s.get("recipe") for s in r2["process"]["steps"]])

    def test_survival_without_dong_answers_jeju_wide(self):  # 업종 생존율은 제주 전체 값이라 동네를 되묻지 않는다
        r, _ = self.lines("카페 5년 생존율")
        self.assertRegex(r["answer"]["conclusion"]["text"], r"카페 5년 생존율 [\d.]+%.*제주 전체")

    def test_anomaly_by_business(self):  # '올해 폐업 이상한 업종'은 업종 묶음별 이례로 답한다(동네가 없으면 제주 전체)
        r, ls = self.lines("올해 폐업 이상한 업종")
        c = r["answer"]["conclusion"]["text"]
        self.assertIn("제주 전체 폐업이 앞선 3년 평균보다 뚜렷이 많은 음식 업종", c)
        r, _ = self.lines("노형동 올해 폐업 이상한 업종 있어?")
        self.assertIn("노형동 폐업이 앞선 3년 평균보다", r["answer"]["conclusion"]["text"])
        import recipes
        out = recipes.r7({"by": "업종", "dong": "전체"}, {"ok": ["전체"]})
        a = next(x for x in out["anomaly"] if x["biz"] == "한식")
        self.assertEqual(a["flag"], "많음" if a["z"] > 2 else "적음" if a["z"] < -2 else "보통 범위")
        self.assertAlmostEqual(a["z"], (a["count"] - a["expected"]) / max(a["expected"], 0.5) ** 0.5, delta=0.02)

    def test_tourist_count_answers_customer_mix(self):  # 방문자 수 자료가 없으므로 손님 구성으로 답하고 그 사실을 알린다
        r, _ = self.lines("성산읍 관광객이 얼마나 와?")
        self.assertEqual(r["tuple"]["metric"], ["관광객비중"])
        self.assertIn(R.TOUR_NOTE, r["understood"]["notes"])
        self.assertIn("관광객 매출 비중", r["answer"]["conclusion"]["text"])

    def test_foreign_sales_says_jeju_wide_first(self):
        r, _ = self.lines("노형동 외국인 매출")
        self.assertTrue(r["answer"]["conclusion"]["text"].startswith("노형동만 따로 센 자료는 없어 제주 전체 값이에요."))

    def test_gold_three(self):  # B138·B141은 상가 정보 분류로 답하고, B142(애견미용실)는 사람 미용실 수로 바꿔 답하지 않는다
        gold = {json.loads(x)["id"]: json.loads(x) for x in (ROOT / "data" / "x1" / "test_std150b_gold.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
        for k, word in (("X1-B138", "조천읍 미용실"), ("X1-B141", "남원읍 병원")):
            self.assertEqual(gold[k]["expect"], "답함")
            r = ask(gold[k]["q"])
            self.assertEqual(r["status"], "성공")
            self.assertIn(word, r["answer"]["conclusion"]["text"])
        self.assertEqual(gold["X1-B142"]["expect"], "범위밖")
        self.assertEqual(ask(gold["X1-B142"]["q"])["status"], "범위밖")
        self.assertEqual(ask("노형동 동물병원 몇 곳")["status"], "성공")  # 동물병원은 상가 정보에 분류가 있다


class M1Rules(unittest.TestCase):
    """분류기 결과보다 사전 해석을 따르는 예외(문서 20 7.5절 1·3번). 임베딩·분류기는 가짜 값으로 바꿔 Ollama 없이 확인한다."""

    def interp(self, q, typ, conf, expect="답함"):
        import m1
        m = m1.M1.__new__(m1.M1)
        m.ok, m.low_conf = True, 0.5
        m._embed = lambda q: None
        m._predict = lambda head, v: (typ, conf) if head == "type" else (expect, 1.0)
        return m.interpret

    def test_low_confidence_condition_effect_without_condition_word(self):  # 1번: 조건 낱말 없는 문장의 낮은 확신도 '조건 효과'
        q = "애월읍 관광객 손님이 줄었어?"
        base = qparse.parse(q)
        self.assertEqual((base["cond"], base["type"] != "T6"), ([], True))
        self.assertEqual(self.interp(q, "T6", 0.49)(q)["tuple"]["type"], base["type"])
        self.assertEqual(self.interp(q, "T6", 0.6)(q)["tuple"]["type"], "T6")  # 확신도 0.5 이상은 분류기를 따른다
        rainy = "비 오는 날 아라동 방문은?"
        self.assertEqual(self.interp(rainy, "T6", 0.4)(rainy)["tuple"]["type"], "T6")  # 조건 낱말이 있으면 그대로
        r = R.respond(q, None, llm_on=False, interpret=self.interp(q, "T6", 0.49))
        self.assertNotEqual(r["status"], "선택필요")  # 한 번에 답한다

    def test_five_businesses_store_count_follows_dictionary(self):  # 3번: 분류기는 5개 업종을 범위 밖으로 배웠다
        q = "노형동 미용실 몇 곳이야?"
        t = self.interp(q, "T12", 0.82, "범위밖")(q)["tuple"]
        self.assertEqual((t["type"], t["expect"], t["detail"]), ("T1", "답함", "미용실"))
        q2 = "노형동 미용실 카드 매출 알려줘"
        self.assertEqual(self.interp(q2, "T12", 0.4, "범위밖")(q2)["tuple"]["expect"], "범위밖")
        r = R.respond(q2, None, llm_on=False, interpret=self.interp(q2, "T12", 0.4, "범위밖"))
        self.assertIn("가게 수만 볼 수 있어요", r["card"]["conclusion"])


class Deep22(unittest.TestCase):  # 문서 22: 업종 탭, 단순 주제의 모델 분석, 모델 보완, 동네 비교
    @staticmethod
    def slots(s):
        return R.respond(None, {"center_db": False}, llm_on=False, slots=s)

    @staticmethod
    def ana(r):
        return [x for b in r["answer"]["blocks"] if b["id"] == "analysis" for x in b["lines"]]

    def test_every_topic_has_analysis(self):  # 3단계: 주제 14개 모두 분석 줄 1개 이상, 곁가지 줄은 결론이 아니다
        cases = [{"topic": "stores", "space": ["노형동"], "target": "카페"}, {"topic": "openclose", "space": ["노형동"], "target": "카페"},
                 {"topic": "market", "space": ["노형동"], "target": "음식점"}, {"topic": "sales", "space": ["노형동"], "target": "카페"},
                 {"topic": "customers", "space": ["노형동"], "target": "카페"}, {"topic": "hourly", "space": ["노형동"], "target": "카페"},
                 {"topic": "visit", "space": ["노형동"]}, {"topic": "rain", "space": ["노형동"]}, {"topic": "bizcompare", "space": ["노형동"]},
                 {"topic": "compare", "space": ["노형동", "연동"], "target": "카페"}, {"topic": "rank", "metric": "매출", "target": "음식점"},
                 {"topic": "similar", "space": ["노형동"]}, {"topic": "forecast", "space": ["노형동"]}, {"topic": "diagnose", "space": ["노형동"], "target": "카페"}]
        for s in cases:
            r = self.slots(s)
            if s["topic"] == "compare":  # 비교 요약 줄은 결론으로 올라가고 분석은 5절 표가 맡는다
                self.assertTrue(r["answer"]["compare"]["sections"])
            else:
                self.assertGreaterEqual(len(self.ana(r)), 1, s["topic"])
            self.assertEqual(r["card"]["number_check"], [], s["topic"])
            side = {x["text"] for x in self.ana(r) if x.get("side")}
            self.assertNotIn(r["answer"]["conclusion"]["text"], side, s["topic"])

    def test_position_against_neighbors(self):
        r = self.slots({"topic": "stores", "space": ["노형동"], "target": "카페"})
        self.assertEqual(r["answer"]["conclusion"]["text"], "노형동 카페 점포 수는 175곳이에요.")
        pos = next(x["text"] for x in self.ana(r) if x["kind"] == "position")
        self.assertRegex(pos, r"43곳 중 4위.*비슷한 동네 5곳의 평균 105곳보다 66.0% 많아요\(아라동, 연동, 외도동, 이도2동, 화북동\)")

    def test_r1_interval_calibrated_and_dong_accuracy(self):  # 4단계 R1: 포함률 78~82, 동네별 정확도, 비 보정 8곳
        txt = " ".join(x["text"] for x in self.ana(self.slots({"topic": "visit", "space": ["구좌읍"]})))
        self.assertIn("100번 중 78~83번", txt)
        self.assertRegex(txt, r"구좌읍만 보면 오차가 단순 예상의 약 \d+%")
        self.assertIn("비가 오면 위 값보다 약", txt)

    def test_r4_dong_yearly_pass_rate(self):  # 4단계 R4: 손계산 노형동 2년차 91.7%
        txt = " ".join(x["text"] for x in self.ana(self.slots({"topic": "openclose", "space": ["노형동"], "target": "카페"})))
        self.assertIn("2년차 91.7%", txt)
        self.assertNotIn("안정", txt)

    def test_biz_tabs_only_with_stores(self):  # 2단계: 업종 탭, 숙박은 생존 자료 없음 안내
        tabs = self.slots({"topic": "diagnose", "space": ["노형동"], "target": "카페"})["answer"]["biz_tabs"]
        cur = [x for x in tabs if x["current"]]
        self.assertEqual([x["label"] for x in cur], ["카페"])
        self.assertTrue(all(x["stores"] > 0 for x in tabs))
        self.assertIn("음식점만", next(x["note"] for x in tabs if x["label"] == "숙박"))

    def test_compare_table_matches_hand_check(self):  # 5단계: 노형동·연동 손계산 대조
        r = self.slots({"topic": "compare", "space": ["노형동", "연동"], "target": "카페"})
        rows = {x["label"]: x for s in r["answer"]["compare"]["sections"] for x in s["rows"]}
        self.assertEqual([round(v) for v in rows["하루 평균 방문(최근 365일)"]["values"]], [226861, 254725])
        self.assertEqual(rows["카페 가게 수"]["values"], [175.0, 118.0])
        self.assertEqual(rows["카페 가게 수"]["verdict"], "순위로만 비교")
        self.assertEqual(rows["음식점 5년 생존율(업종 구분 없음)"]["verdict"], "차이 확인 안 됨")
        self.assertIn("지표로 견줬어요", r["answer"]["conclusion"]["text"])
        self.assertNotRegex(r["answer"]["conclusion"]["text"], r"유망|추천|유리")
        cw = self.slots({"topic": "diagnose", "space": ["노형동"], "target": "카페"})["answer"]["compare_with"]
        self.assertEqual([c["dong"] for c in cw["candidates"]], ["아라동", "연동", "외도동", "이도2동", "화북동"])


class RankOrder(unittest.TestCase):
    def test_lowest_rank_is_ascending(self):  # '가장 적은' 순위는 작은 순서(2026-11-14)
        r = R.respond("카페가 가장 적은 동네는?", None, llm_on=False)
        self.assertIn("작은 순서", r["card"]["conclusion"])
        self.assertIn("1위 추자면", r["card"]["conclusion"])


class Persona20261114(unittest.TestCase):
    """현 시점 약점 A1~A7(2026-11-14 페르소나·Gemini 재평가): 도민 질문 정확성."""
    def lines(self, r):
        return [l for l in ((r.get("agent") or {}).get("lines") or []) if not l.startswith("   ")]

    def test_a1_parallel_superlatives(self):
        r = R.respond("방문이 가장 적은 동네와 가장 많은 동네 알려줘", None, llm_on=False)
        ls = self.lines(r)
        self.assertIn("작은 순서", ls[0])
        self.assertIn("큰 순서", ls[1])

    def test_a1_ellipsis_follow_up(self):
        r = R.respond("연동 매출 늘었어? 그리고 노형동은?", None, llm_on=False)
        ls = self.lines(r)
        self.assertTrue(ls[0].startswith("1. 연동") and "2. 노형동" in ls[1], ls)

    def test_a1_rank_then_ref(self):
        r = R.respond("관광객 비중 1위 동네 알려주고 거기 카페 폐업은", None, llm_on=False)
        ls = self.lines(r)
        self.assertEqual(len(ls), 2)
        self.assertIn("순위", ls[0])

    def test_a2_extreme_month_and_reason(self):
        r = R.respond("한림읍 음식점 매출이 가장 적은 달과 이유", None, llm_on=False)
        self.assertIn("가장 적은 달", r["card"]["conclusion"])
        self.assertTrue(any("원인은 자료만으로" in n for n in r["understood"]["notes"]))

    def test_a3_compare_has_both_dongs(self):
        r = R.respond("노형동 카페 생존율 연동이랑 비교해줘", None, llm_on=False)
        self.assertIn("노형동", r["card"]["conclusion"])
        self.assertIn("연동", r["card"]["conclusion"])

    def test_a4_rain_rank(self):
        r = R.respond("비 오는 날 매출이 가장 많이 줄어드는 동네는?", None, llm_on=False)
        self.assertIn("1위", r["card"]["conclusion"])
        self.assertTrue(any("방문" in x for x in r["card"]["limits"]))

    def test_a5_city_notice(self):
        r = R.respond("제주시 음식점 매출 추이 알려줘", None, llm_on=False)
        self.assertIn("시 단위", r["choose"]["message"])

    def test_a6_stop_notice(self):
        r = R.respond("연동 버스 정류소 중 승객이 제일 많은 곳", None, llm_on=False)
        self.assertTrue(any("정류소별 자료" in n for n in r["understood"]["notes"]))

    def test_a7_matjip_and_near_suggestions(self):
        r = R.respond("서귀포 맛집 추천해줘", None, llm_on=False)
        self.assertEqual(r["status"], "범위밖")
        self.assertIn("맛·후기", r["card"]["conclusion"])
        self.assertTrue(all("노형동" not in x["text"] for x in r["suggestions"]))


class Pending20261114(unittest.TestCase):
    """미처리 결함 D1~D7(2026-11-14)."""
    def test_d1_sales_change_rank(self):
        r = R.respond("최근 매출이 급증한 동네는?", None, llm_on=False)
        self.assertIn("카드 매출", r["card"]["conclusion"])
        self.assertNotIn("폐업", r["card"]["conclusion"])
        self.assertIn("1위 서홍동(+11.9%)", r["card"]["conclusion"])

    def test_d2_outside_jeju(self):
        r = R.respond("부산 해운대 카페 몇 개야?", None, llm_on=False)
        self.assertEqual(r["status"], "범위밖")
        self.assertIn("제주 밖", r["card"]["conclusion"])

    def test_d3_metric_inherited(self):
        r = R.respond("노형동 방문 추이 확인하고 연동이랑도 비교해줘", None, llm_on=False)
        ls = [l for l in r["agent"]["lines"] if not l.startswith("   ")]
        self.assertIn("방문", ls[1])
        self.assertNotIn("11개 지표", ls[1])

    def test_d4_rain_rank_states_basis(self):
        r = R.respond("비 올 때 버스 이용이 가장 줄어드는 동네는?", None, llm_on=False)
        self.assertTrue(r["card"]["conclusion"].startswith("버스 이용의 동네별 비 효과는 계산하지 않아"))

    def test_d5_overlapping_ci_not_asserted(self):
        r = R.respond("노형동 음식점 생존율 연동이랑 비교해줘", None, llm_on=False)
        self.assertIn("확인되지 않아요", r["card"]["conclusion"])

    def test_d6_store_count_label(self):
        r = R.respond("대정읍 치킨집 창업 어때?", None, llm_on=False)
        self.assertIn("치킨 가게 수", r["answer"]["conclusion"]["text"])


class FinalEvalRegressions(unittest.TestCase):
    """최종 평가(2026-11-14)에서 찾은 회귀: 특수 규칙이 일상어에 걸리던 결함."""
    def test_bigyo_bijung_not_rain(self):
        for q in ["관광객 비중이 제일 높은 곳 어디야?", "업종별로 비교해서 가게가 가장 많은 곳은?"]:
            r = R.respond(q, None, llm_on=False)
            self.assertNotIn("비 오는 날", (r.get("card") or {}).get("conclusion") or "", q)

    def test_gyeonggi_economy_not_outside(self):
        r = R.respond("요즘 제주 경기 어때?", None, llm_on=False)
        self.assertNotIn("제주 밖", (r.get("card") or {}).get("conclusion") or "")

    def test_business_recommend_message(self):
        r = R.respond("창업할 업종 추천해줘", None, llm_on=False)
        self.assertIn("추천하거나 정하지 않아요", r["card"]["conclusion"])

    def test_city_rank_scoped(self):
        r = R.respond("서귀포시 동네 중 카페 가장 많은 곳은?", None, llm_on=False)
        self.assertIn("17곳", r["card"]["conclusion"])
        self.assertNotIn("애월읍", r["card"]["conclusion"])
