"""W8 결과 생성 시험: 답 카드 순서·수치 대조, 판단 과정, 관문 실패 예측 숨김, M1-b·M3-b LLM 대체 규칙, 내려받기, /api/ask.
해석은 규칙 해석기, LLM은 끄거나 가짜 응답으로 바꿔 Ollama 없이도 같은 결과가 나오게 한다.
실행: .venv/bin/python -m unittest tests.test_result"""
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
                else:
                    self.assertTrue(e.get("dataset"), (q, e))

    def test_bus_forecast_excluded(self):  # v3: 버스 예상(R2)은 제외하고 범위 밖으로 안내(문서 18)
        r = self.out["탑동 버스 다음달 얼마나 탈까?"]
        self.assertEqual(r["status"], "범위밖")
        self.assertIn("버스 이용 예상은 하지 않아요", r["card"]["conclusion"])

    def test_passed_gate_shows_forecast_and_interval(self):
        c = self.out["노형동 다음주 방문 예측해줘"]["card"]
        self.assertTrue(any(e.get("kind") == "forecast" for e in c["evidence"]))
        self.assertTrue(any("R1" in x for x in c["intervals"]))
        self.assertTrue(any("지수" in x for x in c["limits"]))  # 유동인구는 지수

    def test_conclusions_by_type(self):
        self.assertIn("보다 많습니다", self.out["노형동이랑 연동 버스 이용 비교해줘"]["card"]["conclusion"])
        self.assertIn("카페 개업 수", self.out["노형동 카페 개업 최근 3년 늘었어?"]["card"]["conclusion"])  # 판정 결과는 자료 갱신에 따라 바뀜
        self.assertIn("비슷한 동네", self.out["노형동이랑 비슷한 동네는?"]["card"]["conclusion"])
        self.assertTrue(self.out["노형동 카페 5년 생존율은?"]["card"]["conclusion"].startswith("카페 5년 생존율"))
        d = self.out["노형동 생활 진단해줘"]  # v3: 상권 종합 진단은 판단 재료(수요·경쟁·생존) 요약이 결론
        self.assertIn("판단 재료", d["card"]["conclusion"])
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
        csv = next(x for x in d if x["name"].endswith(".csv"))
        self.assertTrue(csv["csv"].startswith("dong,ym,value"))
        self.assertEqual(csv["rows"], len(csv["csv"].strip().splitlines()) - 1)

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
        with fake_llm("버스 이용 자료에서 두 동네 값을 모아 그래프로 정리했습니다."):
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

