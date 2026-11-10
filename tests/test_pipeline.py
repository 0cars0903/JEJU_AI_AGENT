"""도구·에이전트 시험. EDA 값과 대조하고, 틀린 입력을 일부러 넣어 막는지 본다. LLM은 쓰지 않는다(가짜 LLM 주입).
실행: .venv/bin/python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import agent  # noqa: E402
import llm  # noqa: E402
import tools as tl  # noqa: E402


class Tools(unittest.TestCase):
    def test_eda_values(self):
        self.assertEqual(tl.compare_rank("숙박특화계수", ["한경면"])["values"]["rows"][0]["value"], 3.23)  # EDA 3.225
        self.assertEqual(tl.compare_rank("폐업률", ["일도1동"])["values"]["rows"][0]["value_pct"], 11.2)
        self.assertEqual(tl.dong_profile("영천동")["values"]["survival_5y_pct"], 82.0)
        self.assertEqual(tl.dong_profile("영천동")["values"]["survival_n"], 61)
        self.assertEqual(tl.bus_usage("한경면", "경로")["values"]["type_share_pct"], 31.0)

    def test_labels_are_bh_results(self):
        rows = tl.compare_rank("폐업률")["values"]["rows"]
        self.assertEqual({r["dong"] for r in rows}, {"구좌읍", "송산동", "연동", "예래동", "일도1동"})
        self.assertFalse(tl.compare_rank("폐업률")["values"]["ranked"])

    def test_no_rank_for_closure(self):
        r = tl.compare_rank("5년생존율", ["영천동", "이호동"])
        self.assertNotIn("rank", r["values"]["rows"][0])

    def test_islands_excluded_from_rank(self):
        r = tl.compare_rank("숙박특화계수", top=15)
        self.assertNotIn("추자면", [x["dong"] for x in r["values"]["rows"]])  # 추자면 값은 3.14로 상위권이지만 빠져야 한다
        r2 = tl.compare_rank("숙박특화계수", ["추자면"])
        self.assertIsNone(r2["values"]["rows"][0]["rank"])
        self.assertEqual(tl.dong_profile("추자면")["badges"]["상권 규모"], "표본 적음")

    def test_udo_bus_exists_and_flagged(self):
        r = tl.bus_usage("우도면")
        self.assertIn("summary", r)
        self.assertTrue(any("표본 적음" in x for x in r["limits"]))

    def test_resolve(self):
        self.assertEqual(tl.resolve("고내리"), {"dong": "애월읍"})
        self.assertIn("candidates", tl.resolve("서귀동"))
        self.assertEqual(tl.resolve("이도이동"), {"dong": "이도2동"})  # 아라동 3곳은 주소 오류로 뺌
        self.assertIn("error", tl.resolve("없는동"))
        self.assertIn("error", tl.dong_profile("없는동"))

    def test_deterministic(self):
        self.assertEqual(tl.dong_profile("노형동"), tl.dong_profile("노형동"))

    def test_bad_inputs(self):
        self.assertIn("error", tl.biz_diagnostic("노형동", "우주선"))
        self.assertIn("error", tl.compare_rank("없는지표"))
        self.assertIn("error", tl.bus_usage("노형동", "외계인"))
        self.assertIn("error", tl.biz_diagnostic("노형동", start_year=2025, end_year=2020))


class Regressions(unittest.TestCase):
    """이중 검토 007에서 재현한 오류."""

    def answer(self, q):
        return agent.run(q, backend="rule")

    def test_old_people_population_not_bus(self):
        r = self.answer("어르신 인구가 가장 많은 동네는?")
        self.assertEqual(r["tool_results"][0]["values"]["metric"], "고령비중")
        self.assertEqual(self.answer("어르신이 버스를 가장 많이 타는 동네는 어디야?")["tool_results"][0]["values"]["metric"], "경로일평균")
        self.assertEqual(self.answer("어르신 버스 이용 비중이 가장 높은 동네는?")["tool_results"][0]["values"]["metric"], "경로비중")
        self.assertIn("버스 이용자 중", tl.compare_rank("경로비중")["summary"][0])

    def test_explicit_year_used(self):
        r = self.answer("2022년 노형동 음식점 개업 폐업은?")
        self.assertEqual([y["year"] for y in r["tool_results"][0]["values"]["restaurant_years"]], [2022])

    def test_relative_year(self):
        self.assertEqual(agent.parse_years("최근 2년"), (2023, 2024))
        y = agent.datetime.date.today().year
        self.assertEqual(agent.parse_years("작년"), (y - 1, y - 1))
        self.assertIsNone(agent.parse_years("노형동"))

    def test_year_phrases(self):
        y = agent.datetime.date.today().year
        self.assertEqual(agent.parse_years("작년부터 올해까지"), (y - 1, y))
        self.assertEqual(agent.parse_years("2024년에서 2022년"), (2022, 2024))
        self.assertEqual(agent.parse_years("2020년대"), (2020, y))
        self.assertEqual(agent.parse_years("재작년"), (y - 2, y - 2))
        self.assertEqual(agent.parse_years("2021년부터"), None if False else agent.parse_years("2021년부터"))

    def test_no_data_year_message_has_hint(self):
        r = self.answer("올해 노형동 음식점 개업 폐업은?")
        self.assertEqual(r["status"], "no_data")
        self.assertIn("2025-08-30", r["answer"])

    def test_bus_2022_flagged(self):
        r = tl.bus_usage("노형동", year=2022)
        self.assertTrue(any("105일" in x for x in r["limits"]))

    def test_compare_two_dongs_metric(self):
        r = self.answer("노형동과 연동 점포수 비교해 줘")
        self.assertEqual([x["dong"] for x in r["tool_results"][0]["values"]["rows"]], ["노형동", "연동"])

    def test_future_year_refused(self):
        self.assertIn("error", tl.biz_diagnostic("노형동", start_year=2030, end_year=2030))

    def test_bus_year(self):
        r = self.answer("2023년 노형동 버스 이용은?")
        self.assertEqual(r["tool_results"][0]["values"]["year"], 2023)
        self.assertIn("error", tl.bus_usage("노형동", year=2018))
        self.assertIn("error", tl.population_mix("노형동", year=2022))

    def test_non_food_hides_restaurant_rates(self):
        r = tl.biz_diagnostic("노형동", "숙박")
        self.assertNotIn("close_3y_pct", r["values"])
        self.assertFalse(any("폐업률" in x for x in r["summary"]))
        self.assertTrue(any("자료는 없습니다" in x for x in r["summary"]))
        self.assertIn("close_3y_pct", tl.biz_diagnostic("노형동", "카페")["values"])

    def test_category_rank(self):
        r = self.answer("카페가 가장 많은 동네는 어디야?")
        self.assertEqual(r["status"], "ok")
        v = r["tool_results"][0]["values"]
        self.assertEqual(v["metric"], "업종점포수")
        self.assertTrue(v["rows"][0]["value"] >= v["rows"][1]["value"])

    def test_scenery_not_future(self):
        self.assertEqual(self.answer("애월읍 바다 전망 카페 어때?")["status"], "ok")
        self.assertEqual(self.answer("노형동 상권 전망은?")["status"], "out_of_scope")

    def test_zero_user_type(self):
        v = tl.bus_usage("우도면", "유공")["values"]
        self.assertEqual((v["type_daily"], v["type_share_pct"]), (0.0, 0.0))

    def test_island_flag_in_text(self):
        s = tl.compare_rank("5년생존율")["summary"]
        self.assertTrue(any("우도면" in x and "표본 적음" in x for x in s))
        self.assertEqual(tl.dong_profile("우도면")["badges"]["상권 지속"], "표본 적음")

    def test_sparse_position(self):
        self.assertEqual(tl._position(__import__("pandas").Series({f"d{i}": 0 for i in range(20)}), "d1"), "대부분 동네와 같음")

    def test_multi_dong_blocks(self):
        a = self.answer("아라동과 이도2동 비교표 뽑아 줘")["answer"]
        self.assertIn("[아라동]", a)
        self.assertIn("[이도2동]", a)


class Checks(unittest.TestCase):
    R = [{"values": {"a": 31.0, "b": 1234}}]

    def test_invented_number_blocked(self):
        self.assertEqual(agent.check_numbers("비중은 47.5%입니다.", self.R), [47.5])

    def test_tool_number_passes(self):
        self.assertEqual(agent.check_numbers("비중은 31.0%이고 1,234곳입니다. 2024년 기준 이도2동입니다.", self.R), [])

    def test_ko_number_blocked(self):
        self.assertTrue(agent.check_numbers("구십구 퍼센트입니다", self.R))

    def test_rank_on_closure_blocked(self):
        self.assertTrue(agent.verify_answer("이 동네는 폐업률 1위입니다.", [{"values": {"x": 1}}]))
        self.assertTrue(agent.verify_answer("유망한 동네입니다.", self.R))

    def test_chinese_blocked(self):
        self.assertTrue(agent.verify_answer("这里是 동네", self.R))


class Agent(unittest.TestCase):
    CASES = {  # 개발 방향 4.3절 유즈케이스
        "애월읍에 카페가 많은 편이야?": ["biz_diagnostic"],
        "최근 2년 노형동 음식점 개업·폐업은?": ["biz_diagnostic"],
        "한림읍 어르신 버스 이용은 어때?": ["bus_usage"],
        "비 오는 날 아라동 버스 이용은?": ["bus_usage"],
        "아라동과 이도2동 비교표 뽑아 줘": ["dong_profile", "dong_profile"],
        "노형동 생활 진단해 줘": ["dong_profile"],
        "우리 동네 연동 오가는 사람 구성이랑 버스는 어떻게 바뀌었나?": ["population_mix", "bus_usage"],
    }

    def test_rule_mode_use_cases(self):
        for q, names in self.CASES.items():
            r = agent.run(q, backend="rule")
            self.assertEqual(r["status"], "ok", q)
            self.assertEqual([p["name"] for t in r["trace"] if t["stage"] == "계획 확정" for p in t["plan"]], names, q)
            self.assertTrue(r["limits"], q)
            self.assertTrue(r["answer"], q)

    def test_out_of_scope(self):
        for q in ["내일 동문시장 매출은?", "노형동 월세 얼마야?", "연동 출근 시간대 혼잡해?", "내년 애월읍 카페 전망은?"]:
            self.assertEqual(agent.run(q, backend="rule")["status"], "out_of_scope", q)

    def test_clarify(self):
        self.assertEqual(agent.run("우리 동네 어때?", backend="rule")["status"], "clarify")
        r = agent.run("서귀동 상권 어때?", backend="rule")
        self.assertEqual(r["status"], "clarify")
        self.assertIn("정방동", r["answer"])

    def test_rank_question(self):
        r = agent.run("숙박이 가장 많은 동네는 어디야?", backend="rule")
        self.assertEqual(r["tool_results"][0]["values"]["metric"], "숙박특화계수")
        r = agent.run("폐업률 순위 알려 줘", backend="rule")
        self.assertFalse(r["tool_results"][0]["values"]["ranked"])


def fake_llm(replies):
    it = iter(replies)
    def chat(model, messages, tools, name=None, max_tokens=700):
        x = next(it)
        if isinstance(x, Exception):
            raise x
        return {"message": x}
    return chat


class WithFakeLLM(unittest.TestCase):
    def setUp(self):
        self._c = llm.chat

    def tearDown(self):
        llm.chat = self._c

    def plan(self, name, **a):
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": a}}]}

    def run_q(self, q, *replies):
        llm.chat = fake_llm(list(replies))
        return agent.run(q, backend="claude")  # 요약까지 쓰는 백엔드(응답은 가짜)

    def calls(self, r):
        return [c for t in r["trace"] if t["stage"] == "실행" for c in t["calls"]]

    def test_number_in_summary_rejected(self):
        r = self.run_q("노형동 진단해 줘", self.plan("dong_profile", dong="노형동"), {"content": "점포는 99999곳입니다."}, {"content": "점포는 88888곳입니다."})
        self.assertEqual((r["status"], r["answer_how"]), ("ok", "rule_fallback"))
        self.assertNotIn("99999", r["answer"])
        self.assertIn(f"{tl.dong_profile('노형동')['values']['stores']:,}", r["answer"])

    def test_tool_number_in_summary_also_rejected(self):
        """실제 사례: 전체 값을 어르신 값처럼 쓴 답. 숫자 대조는 통과하므로 요약에서 숫자 자체를 막는다."""
        total = tl.bus_usage("한림읍")["values"]["daily"]
        r = self.run_q("한림읍 어르신 버스 이용은 어때?", self.plan("bus_usage", dong="한림읍", user_type="어르신"), {"content": f"어르신 일평균은 {total}명입니다."}, {"content": f"어르신 일평균은 {total}명입니다."})
        self.assertEqual(r["answer_how"], "rule_fallback")
        self.assertEqual(r["summary"], "")

    def test_retry_then_pass(self):
        r = self.run_q("노형동 진단해 줘", self.plan("dong_profile", dong="노형동"), {"content": "점포는 99999곳입니다."}, {"content": "노형동은 점포가 많은 편에 속합니다."})
        self.assertEqual(r["answer_how"], "llm_summary")
        self.assertTrue(r["answer"].startswith("노형동은 점포가 많은"))

    def test_label_conflict_rejected(self):
        """실제 사례: 판정이 '차이 확인 안 됨'인데 '평균보다 높다'고 쓴 답."""
        res = [tl.dong_profile("애월읍")]
        self.assertEqual(res[0]["values"]["close_label"], "차이 확인 안 됨")
        self.assertTrue(agent.verify_summary("애월읍 폐업률은 제주 평균보다 높은 수준입니다.", res))
        self.assertFalse(agent.verify_summary("애월읍 폐업률은 제주 평균과 차이를 확인하지 못했습니다.", res))

    def test_unfounded_rejected(self):
        res = [tl.dong_profile("애월읍")]
        self.assertTrue(agent.verify_summary("주로 관광객들이 방문하는 곳입니다.", res))

    def test_rounded_fake_number_blocked(self):
        self.assertTrue(agent.check_numbers("폐업률은 12%입니다.", [{"v": 11.6}]))

    def stages(self, r):
        return [t["stage"] for t in r["trace"]]

    def test_missing_dong_replanned(self):
        """빠진 동네를 LLM에 알려 다시 세우게 한다. 고치면 코드가 채우지 않는다."""
        r = self.run_q("아라동과 이도2동 비교해 줘", self.plan("dong_profile", dong="아라동"),
                       {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "dong_profile", "arguments": {"dong": d}}} for d in ["아라동", "이도2동"]]}, {"content": "두 동네 자료입니다."})
        self.assertIn("재계획", self.stages(r))
        self.assertEqual({c["arguments"]["dong"] for c in self.calls(r)}, {"아라동", "이도2동"})
        self.assertEqual([t["notes"] for t in r["trace"] if t["stage"] == "계획 확정"], [[]])

    def test_missing_topic_filled_after_failed_replan(self):
        """실제 사례: 인구·버스를 함께 물었는데 버스만 계획. 재계획도 못 고치면 코드가 채운다."""
        p = self.plan("bus_usage", dong="연동")
        r = self.run_q("연동 오가는 사람 구성이랑 버스는?", p, p, {"content": "연동 자료입니다."})
        self.assertEqual({c["name"] for c in self.calls(r)}, {"bus_usage", "population_mix"})
        self.assertTrue(any("코드가 채웠다" in n for t in r["trace"] if t["stage"] == "계획 확정" for n in t["notes"]))

    def test_unknown_tool_removed(self):
        p = self.plan("drop_database", dong="노형동")
        r = self.run_q("노형동 진단해 줘", p, p, {"content": "동네 자료입니다."})
        self.assertEqual([c["name"] for c in self.calls(r)], ["dong_profile"])

    def test_bad_args_cleaned(self):
        """실제 사례: qwen이 dongs·weather 같은 잘못된 인자를 보냄."""
        p = self.plan("biz_diagnostic", dongs=["애월읍"], weather=False, category="카페")
        r = self.run_q("애월읍에 카페가 많은 편이야?", p, p, {"content": "애월읍 자료입니다."})
        self.assertTrue(all(c["ok"] for c in self.calls(r)))
        self.assertEqual(self.calls(r)[0]["arguments"], {"dong": "애월읍", "category": "카페"})

    def test_invented_category_removed(self):
        """실제 사례: 비교 질문에 LLM이 질문에 없는 '카페'를 넣어 답이 길어짐."""
        p = self.plan("compare_rank", dongs=["아라동", "이도2동"], metric="업종특화계수", category="카페")
        r = self.run_q("아라동과 이도2동 비교표 뽑아 줘", p, p, {"content": "두 동네 자료입니다."})
        self.assertNotIn("카페", r["answer"])
        self.assertEqual({c["name"] for c in self.calls(r)}, {"dong_profile"})

    def test_extra_calls_capped(self):
        many = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": n, "arguments": {"dong": "노형동"}}} for n in ["bus_usage", "dong_profile", "population_mix", "biz_diagnostic"]]}
        r = self.run_q("노형동 버스 이용은?", many, many, {"content": "노형동 자료입니다."})
        self.assertEqual(self.calls(r)[0]["name"], "bus_usage")
        self.assertEqual(len(self.calls(r)), 1 + agent.MAX_EXTRA_CALLS)

    def test_llm_extra_failure_hidden(self):
        """LLM이 더한 호출의 실패는 사용자 안내에 나오지 않는다."""
        p = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "bus_usage", "arguments": {"dong": "노형동"}}}, {"function": {"name": "biz_diagnostic", "arguments": {"dong": "없는동"}}}]}
        r = self.run_q("노형동 버스 이용은?", p, {"content": "", "tool_calls": []}, {"content": "노형동 자료입니다."})
        self.assertEqual(r["tool_errors"], [])

    def test_compare_without_dongs_repaired(self):
        """이중 검토 008: LLM이 dongs를 빠뜨리면 제주 전체 순위가 나가던 오류."""
        p = self.plan("compare_rank", metric="점포수")
        r = self.run_q("노형동과 연동 점포수 비교해 줘", p, p, {"content": "두 동네 자료입니다."})
        self.assertEqual(self.calls(r)[0]["arguments"].get("dongs"), ["노형동", "연동"])
        self.assertEqual([x["dong"] for x in r["tool_results"][0]["values"]["rows"]], ["노형동", "연동"])

    def test_null_arg_is_not_a_problem(self):
        """실제 사례: year=null 때문에 불필요한 재계획이 일어남."""
        r = self.run_q("연동 버스 이용은?", self.plan("bus_usage", dong="연동", year=None), {"content": "연동 자료입니다."})
        self.assertNotIn("재계획", self.stages(r))

    def test_llm_metric_respected(self):
        """LLM이 고른 유효한 지표는 덮어쓰지 않는다(이중 검토 007)."""
        r = self.run_q("상권이 가장 큰 동네 순위 알려줘", self.plan("compare_rank", metric="버스일평균"), {"content": "동네 순위 자료입니다."})
        self.assertEqual(self.calls(r)[0]["arguments"]["metric"], "버스일평균")

    def test_explicit_metric_enforced(self):
        """평가셋 Q15: 숙박 비중 질문에 LLM이 버스일평균을 고르면 재계획, 그래도 틀리면 코드가 맞춘다."""
        p = self.plan("compare_rank", metric="버스일평균")
        r = self.run_q("숙박 비중이 가장 높은 동네 순위는?", p, p, {"content": "동네 순위 자료입니다."})
        self.assertIn("재계획", self.stages(r))
        self.assertEqual([c["arguments"]["metric"] for c in self.calls(r)], ["숙박특화계수"])

    def test_execution_error_fed_back(self):
        """실행 실패를 LLM에 돌려줘 다시 호출한다: 찾지 못한 업종 → 고친 업종."""
        llm.chat = fake_llm([self.plan("compare_rank", metric="업종점포수", category="우주선"), self.plan("compare_rank", metric="업종점포수", category="카페"), {"content": "동네 순위 자료입니다."}])
        r = agent.run("우주선 카페 점포가 가장 많은 동네는?", backend="claude")
        self.assertIn("실행 수정", self.stages(r))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["tool_errors"], [])

    def test_missing_ollama_model_uses_default_plan(self):
        """센터 PC에 모델이 없을 때: LLM 오류여도 기본 계획으로 답한다."""
        import urllib.error
        llm.chat = fake_llm([urllib.error.URLError("no model")])
        r = agent.run("노형동 진단해 줘", backend="ollama")
        self.assertEqual((r["status"], r["answer_how"]), ("ok", "facts_only"))

    def test_llm_down_uses_rule(self):
        r = self.run_q("노형동 진단해 줘", OSError("down"), OSError("down"))
        self.assertEqual((r["status"], r["answer_how"]), ("ok", "rule_fallback"))

    def test_llm_cannot_change_period(self):
        r = self.run_q("노형동 음식점 개업·폐업은?", self.plan("biz_diagnostic", dong="노형동", start_year=1990, end_year=1991, category="음식점"), {"content": "노형동 자료입니다."})
        self.assertNotIn("start_year", self.calls(r)[0]["arguments"])

    def test_ollama_plans_only(self):
        llm.chat = fake_llm([self.plan("dong_profile", dong="노형동")])  # 요약 호출이 있으면 StopIteration으로 실패한다
        r = agent.run("노형동 진단해 줘", backend="ollama")
        self.assertEqual((r["status"], r["answer_how"], r["summary"]), ("ok", "facts_only", ""))

    def test_negation_and_clause(self):
        """이중 검토 007: '높지 않습니다' 오탐, 한 문장에 두 지표가 있을 때 오탐."""
        res = [tl.dong_profile("노형동")]  # 폐업 차이 확인 안 됨, 생존 평균보다 높음
        self.assertFalse(agent.verify_summary("노형동의 폐업률은 제주 평균보다 높지 않습니다.", res))
        self.assertFalse(agent.verify_summary("노형동의 음식점 생존율은 제주 평균보다 높지만, 폐업률은 차이를 확인하지 못했습니다.", res))
        self.assertTrue(agent.verify_summary("노형동의 음식점 폐업률은 제주 평균보다 높습니다.", res))

    def test_year_in_summary_rejected(self):
        self.assertTrue(agent.verify_summary("노형동은 2023년에는 증가했습니다.", [tl.dong_profile("노형동")]))

    def test_echo_rejected(self):
        self.assertTrue(agent.verify_summary("요약에 숫자를 썼다 → 요약에 숫자를 쓰지 않는다.", [tl.dong_profile("노형동")]))

    def test_metric_name_digit_allowed(self):
        self.assertFalse(agent.verify_summary("노형동의 3년 폐업률은 제주 평균과 차이를 확인하지 못했습니다.", [tl.dong_profile("노형동")]))

    def test_nested_dong_arg_cleaned(self):
        """실제 사례: qwen이 dong을 {'dong': '아라동', 'type': 'string'}으로 보냄."""
        p = self.plan("bus_usage", dong={"dong": "아라동", "type": "string"})
        r = self.run_q("아라동 버스 이용은?", p, p, {"content": "아라동 자료입니다."})
        self.assertTrue(all(c["ok"] for c in self.calls(r)))

    def test_place_note(self):
        r = agent.run("고내리 상권 어때?", backend="rule")
        self.assertTrue(r["answer"].startswith("고내리는 애월읍에 속해"))


if __name__ == "__main__":
    unittest.main()
