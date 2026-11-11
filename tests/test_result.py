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
            if "card" not in r:
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
                self.assertTrue(e.get("dataset") and e.get("as_of"), (q, e))

    def test_failed_gate_hides_forecast(self):  # R2 관문 실패 → 예측 수치를 쓰지 않음(15-6)
        c = self.out["탑동 버스 다음달 얼마나 탈까?"]["card"]
        self.assertFalse(any(e.get("kind") == "forecast" for e in c["evidence"]))
        self.assertIn("낫지 않아", c["conclusion"])

    def test_passed_gate_shows_forecast_and_interval(self):
        c = self.out["노형동 다음주 방문 예측해줘"]["card"]
        self.assertTrue(any(e.get("kind") == "forecast" for e in c["evidence"]))
        self.assertTrue(any("R1" in x for x in c["intervals"]))
        self.assertTrue(any("지수" in x for x in c["limits"]))  # 유동인구는 지수

    def test_conclusions_by_type(self):
        self.assertIn("보다 많습니다", self.out["노형동이랑 연동 버스 이용 비교해줘"]["card"]["conclusion"])
        self.assertIn("의미 있는 변화는 확인하지 못했습니다", self.out["노형동 카페 개업 최근 3년 늘었어?"]["card"]["conclusion"])
        self.assertIn("비슷한 동네", self.out["노형동이랑 비슷한 동네는?"]["card"]["conclusion"])
        self.assertTrue(self.out["노형동 카페 5년 생존율은?"]["card"]["conclusion"].startswith("카페 5년 생존율"))
        self.assertIn("개업 수", self.out["노형동 생활 진단해줘"]["card"]["conclusion"])  # 추세 판정은 개업 수에 대한 것
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


class Clarify(unittest.TestCase):
    def test_template_buttons(self):
        r = ask("카페 몇 개야?")
        self.assertEqual(r["status"], "되묻기")
        self.assertEqual(len(r["clarify"]["buttons"]), 3)

    def test_llm_buttons_used_when_valid(self):
        with fake_llm('{"ask": "어느 동네 카페를 볼까요?", "buttons": ["노형동 카페 보기", "연동 카페 보기", "아라동 카페 보기"]}'):
            r = ask("카페 몇 개야?", llm_on=True)
        self.assertEqual(r["clarify"]["by"], "LLM")

    def test_llm_buttons_rejected(self):
        for bad in ['{"ask": "동네를 골라 주세요.", "buttons": ["노형동", "애월읍", "아라동"]}',  # 후보 밖 값
                    '{"ask": "카페 몇 개야", "buttons": ["노형동", "연동", "아라동"]}',  # 질문 되풀이
                    "노형동 연동 아라동"]:  # JSON 아님
            with fake_llm(bad):
                r = ask("카페 몇 개야?", llm_on=True)
            self.assertEqual(r["clarify"]["by"], "템플릿(LLM 대체)", bad)


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
