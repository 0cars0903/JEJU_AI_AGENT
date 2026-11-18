"""W7 검수 시험(오류 주입): 오류 6유형의 되돌릴 곳, '효과 없음', 반출 차단, 템플릿 대체, 재시도 상한.
해석은 규칙 해석기(qparse)로 고정해 Ollama 없이도 같은 결과가 나오게 한다.
실행: .venv/bin/python -m unittest tests.test_verify"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import qparse  # noqa: E402
import verify as V  # noqa: E402


def RULE(q):
    return {"tuple": {k: v for k, v in qparse.parse(q).items() if not k.startswith("_")}}


def review(q, **kw):
    return V.review(q, kw.pop("env", None), interpret=RULE, **kw)


def routes(r):
    return [(x["type"], x["route"]) for x in r["record"]]


def within_limit(tc, r):
    tc.assertLessEqual(r["retries"]["sub"], V.LIMIT["sub"])
    tc.assertLessEqual(r["retries"]["main"], V.LIMIT["main"])
    tc.assertLessEqual(r["retries"]["total"], V.LIMIT["total"])


class Interpret(unittest.TestCase):
    def test_out_of_list_value_goes_to_m1(self):
        r = review("노형동 카페 몇 개야?", tuple_override=lambda t: dict(t, metric=["없는지표"]))
        self.assertIn(("해석", "M1"), routes(r))
        self.assertEqual(r["retries"]["main"], 1)
        self.assertEqual(r["tuple"]["metric"], RULE("노형동 카페 몇 개야?")["tuple"]["metric"])  # 규칙으로 다시 채움
        self.assertEqual(r["status"], "성공")

    def test_missing_dong_refilled(self):
        r = review("노형동 카페 몇 개야?", tuple_override=lambda t: dict(t, space=[]))
        self.assertIn(("해석", "M1"), routes(r))
        self.assertEqual(r["tuple"]["space"], ["노형동"])

    def test_still_empty_asks_back(self):  # 규칙으로도 동네가 비면 되묻기
        r = review("카페 몇 개야?", tuple_override=lambda t: dict(t, type="T1", expect="답함", space=[]))
        self.assertEqual(r["status"], "되묻기")
        within_limit(self, r)


class Plan(unittest.TestCase):
    def test_bad_order_goes_to_m3_and_replans(self):
        def broken(o):
            o["tasks"][-1]["depends_on"] = ["t99"]
            return o
        r = review("노형동 카페 개업 최근 3년 늘었어?", order_hook=broken)
        self.assertIn(("계획", "M2·M3"), routes(r))
        self.assertEqual(r["retries"]["main"], 1)
        self.assertFalse(V.runner.validate(r["order"]))
        self.assertIn(r["status"], ("성공", "no_significant_effect"))

    def test_uncovered_axis_is_plan_error(self):
        t = RULE("노형동 카페 몇 개야?")["tuple"]
        p = V.planner.plan(t, {"center_db": False})
        p["steps"] = [s for s in p["steps"] if s["sub"] != "S1"]
        errs = V.check_plan(t, p, V.runner.build_order(p))
        self.assertTrue(any(f["route"] == "M2·M3" and "점포수" in f["detail"] for f in errs))

    def test_center_route_down_replans_public(self):  # 센터 DB 미연결 → Sub가 아니라 M2로 되돌려 공개 경로
        r = review("노형동 다음주 방문 예측해줘", env={"center_db": True})
        self.assertIn(("계획", "M2·M3"), routes(r))
        self.assertTrue(all(t.get("route") != "center" for t in r["order"]["tasks"]))
        self.assertEqual(r["status"], "성공")
        within_limit(self, r)


class Execute(unittest.TestCase):
    def test_exec_error_retried_once_in_sub(self):
        r = review("노형동 카페 몇 개야?", env={"center_db": False, "inject": {"t1": "실행"}})
        log = {x["task_id"]: x for x in r["run"]["log"]}
        self.assertEqual((log["t1"]["status"], log["t1"]["attempts"]), ("성공", 2))
        self.assertEqual(r["status"], "성공")


class Calc(unittest.TestCase):
    Q = "노형동 카페 개업 최근 3년 늘었어?"  # S1 → S2 → S6 → S4

    def test_calc_error_reruns_failed_and_dependents_only(self):
        r = review(self.Q, env={"center_db": False, "inject": {"t2": "계산"}})
        self.assertIn(("계산", "Sub"), routes(r))
        self.assertEqual(r["retries"]["sub"], 1)
        self.assertIn(r["status"], ("성공", "no_significant_effect"))
        t1 = [x for x in r["run"]["log"] if x["task_id"] == "t1"]
        self.assertEqual(len(t1), 1)  # 성공한 조회(t1)는 다시 돌리지 않음

    def test_persistent_calc_error_gives_partial(self):
        r = review(self.Q, env={"center_db": False, "inject": {"t2": "계산"}, "inject_persist": True})
        self.assertEqual(r["status"], "부분 결과")
        self.assertIn("계산하지 못함", r["answer"])
        within_limit(self, r)

    def test_value_range(self):
        def over(order, res):
            k = order["tasks"][0]["out"]
            res["store"][k]["table"].loc[:, "value"] = 130.0
        r = review("노형동 5년 생존율은?", store_hook=over)
        self.assertTrue(any(x["type"] == "계산" and "0~100" in x["detail"] for x in r["record"]))
        self.assertNotIn("130", r["answer"])  # 재계산으로 정상 값

    def test_forecast_without_gate_record(self):  # 15-6: 모델 수치에는 관문 기록이 있어야 한다
        def drop_gate(order, res):
            for v in res["store"].values():
                if "judgement" in v:
                    v["judgement"] = []
        r = review("노형동 다음주 방문 예측해줘", store_hook=drop_gate)
        self.assertTrue(any("관문 R1 기록 없음" in x["detail"] for x in r["record"]))
        self.assertIn("관문 R1", r["answer"])  # 다시 실행해 관문 판정이 돌아옴


class Express(unittest.TestCase):
    def test_wrong_number_replaced_by_template(self):
        r = review("노형동 카페 몇 개야?", answer_fn=lambda o, res: "노형동 카페는 999곳입니다.")
        self.assertIn(("표현", "검수"), routes(r))
        self.assertNotIn("999", r["answer"])
        self.assertEqual(r["retries"]["total"], 0)  # LLM을 다시 부르지 않는다(재시도 횟수에 넣지 않음)

    def test_claim_without_s6(self):
        r = review("노형동 카페 몇 개야?", answer_fn=lambda o, res: "노형동 카페가 늘었어요.")
        self.assertTrue(any("S6 판정 없는 주장" in x["detail"] for x in r["record"]))

    def test_missing_limit(self):
        r = review("노형동 시간대별 방문 알려줘", answer_fn=lambda o, res: "노형동 방문 결과입니다.")
        if r["run"] and r["run"]["relaxed"]:
            self.assertTrue(any("한계 누락" in x["detail"] for x in r["record"]))
            self.assertIn("한계:", r["answer"])


class Export(unittest.TestCase):
    def test_raw_rows_removed(self):
        def restrict(o):
            o["tasks"][0]["export_restricted"] = True
            return o

        def leak(order, res):
            k = order["tasks"][0]["out"]
            t = res["store"][k]["table"]
            res["store"][k]["table"] = t.assign(card_no="1234-****").loc[t.index.repeat(3)].reset_index(drop=True)
        r = review("노형동 방문 알려줘", order_hook=restrict, store_hook=leak)
        self.assertIn(("반출", "검수"), routes(r))
        tab = r["run"]["store"][r["order"]["tasks"][0]["out"]]["table"]
        self.assertNotIn("card_no", tab.columns)
        self.assertEqual(len(tab), len(tab.drop_duplicates(subset=[c for c in ("dong", "ym") if c in tab])))

    def test_unrestricted_untouched(self):
        r = review("노형동 방문 알려줘")
        self.assertFalse(any(x["type"] == "반출" for x in r["record"]))


class NoEffect(unittest.TestCase):
    def test_gate_fail_is_not_error(self):  # R10 관문 실패(MASE 0.986, p 0.55) → 효과 없음, 재시도 없음(v3: R2 제외)
        from test_result import old_sales_model  # 2026-11-16 감쇠 방식은 관문 통과 → 탈락 경로는 바꾸기 전 방식으로
        with old_sales_model():
            r = review("노형동 음식점 다음 달 매출 예상해줘")
        self.assertEqual(r["status"], "no_significant_effect")
        self.assertEqual(r["retries"]["total"], 0)
        self.assertFalse(any(x["type"] in V.ROUTE for x in r["record"]))


class Limits(unittest.TestCase):
    def test_main_once_total_two(self):  # 해석 오류 + 계획 오류 + 계산 오류가 한 질문에 함께
        def broken(o):
            o["tasks"][-1]["depends_on"] = ["t99"]
            return o
        r = review("노형동 카페 개업 최근 3년 늘었어?", tuple_override=lambda t: dict(t, metric=["없는지표"]), order_hook=broken,
                   env={"center_db": False, "inject": {"t2": "계산"}})
        within_limit(self, r)
        self.assertEqual(r["retries"]["main"], 1)
        self.assertEqual(r["status"], "계획 오류")  # Main 재계획 기회를 해석에 썼으므로 지시서 오류는 고치지 못하고 멈춤

    def test_templates_pass_own_check(self):  # 템플릿 답은 검수 표현 규칙을 스스로 통과해야 한다
        for q in ["노형동 카페 몇 개야?", "노형동이랑 연동 버스 이용 비교해줘", "노형동 카페 개업 최근 3년 늘었어?", "비 오는 날 아라동 방문은?",
                  "노형동 다음주 방문 예측해줘", "탑동 버스 다음달 얼마나 탈까?", "노형동이랑 비슷한 동네는?", "노형동 생활 진단해줘",
                  "센터에 와이파이 자료 있어?", "노형동 카페 5년 생존율은?"]:
            r = review(q)
            if r["run"]:
                self.assertFalse(V.check_answer(r["answer"], r["run"]), q)


if __name__ == "__main__":
    unittest.main()
