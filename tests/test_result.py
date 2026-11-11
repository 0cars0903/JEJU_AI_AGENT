"""W8 결과 생성 시험: 답 카드 순서·수치 대조, 판단 과정, 관문 실패 예측 숨김, M1-b·M3-b LLM 대체 규칙, 내려받기, /api/ask.
해석은 규칙 해석기, LLM은 끄거나 가짜 응답으로 바꿔 Ollama 없이도 같은 결과가 나오게 한다.
실행: .venv/bin/python -m unittest tests.test_result"""
import json
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
        self.assertEqual(len(set(cs)), 1)
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
        self.assertIn(f"노형동 미용실 점포 수는 {n} 곳", r["answer"]["conclusion"]["text"])
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
        self.assertIn(f"{n} 곳", nxt["answer"]["conclusion"]["text"])
        self.assertNotEqual(ask("노형동 병원 가는 버스 이용 얼마나 돼")["card"]["conclusion"][:12], "병원은 가게 수만 볼")  # 버스·방문 질문은 막지 않는다

    def test_views_carry_unit_and_plain_block_name(self):  # A10: 그래프·표에 단위를 싣고, 묶음 이름은 쉬운 말로 쓴다
        units = {v["id"]: v.get("unit") for v in R.respond(slots={"topic": "visit", "space": ["노형동"]}, llm_on=False)["answer"]["views"]}
        self.assertEqual(units.get("monthly"), "지수")
        d = ask("노형동에 카페 차려도 될까?")["answer"]
        self.assertEqual(d["blocks"][-1]["title"], "판단할 때 볼 것")
        self.assertNotIn("판단 재료", json.dumps(d, ensure_ascii=False))


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
