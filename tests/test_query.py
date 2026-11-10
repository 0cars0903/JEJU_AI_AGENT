"""W1·W2 시험: 자료 목록, 지표 사전, 사전 해석기(A2′), M1 해석(임베딩이 없으면 규칙 대체).
실행: .venv/bin/python -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402


class Catalog(unittest.TestCase):
    def test_catalog_79_unique(self):
        rows = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 79)
        self.assertEqual(len({r["id"] for r in rows}), 79)
        self.assertTrue(all(r["space"] and r["time"] for r in rows))

    def test_metric_dict_covers_schema(self):
        md = json.loads((ROOT / "data" / "metric_dict.json").read_text(encoding="utf-8"))
        self.assertEqual(set(md), set(Q.METRICS))


class Parser(unittest.TestCase):
    def test_places(self):
        self.assertEqual(qparse.parse("모슬포 카페 몇 개야?")["space"], ["대정읍"])
        self.assertEqual(qparse.parse("강정 쪽 동네 종합해서 알려줘")["space"], ["대천동"])
        self.assertEqual(qparse.parse("구좌읍 해안가 비 오면 버스 줄어?")["space"], ["구좌읍"])  # '해안'은 일반 명사

    def test_scope(self):
        self.assertEqual(qparse.parse("노형동 임대료 얼마야?")["expect"], "범위밖")
        self.assertEqual(qparse.parse("이도2동 미용실 폐업률 얼마야?")["expect"], "범위밖")  # 폐업은 음식점 자료만
        self.assertEqual(qparse.parse("연동 미용실 몇 군데야?")["expect"], "답함")  # 점포 수는 상가 전 업종

    def test_valid_tuple(self):
        for q in ["중문 카페 개업 요즘 늘어나는 중이야?", "비 오는 날 아라동 방문은?", "청년 비중 높고 카페 폐업률 낮은 동네 찾아줘"]:
            t = {k: v for k, v in qparse.parse(q).items() if not k.startswith("_")}
            self.assertEqual(Q.validate(t), [], q)


class M1Fallback(unittest.TestCase):
    def test_rule_fallback_without_model(self):
        import m1
        r = m1.M1(path=ROOT / "models" / "없는파일.json").interpret("노형동 카페 개업 늘었어?")
        self.assertTrue(r["path"].startswith("A2"))
        self.assertEqual(r["tuple"]["space"], ["노형동"])
        self.assertIn("이렇게 이해했어요", r["card"]["text"])


if __name__ == "__main__":
    unittest.main()


class S6Policy(unittest.TestCase):
    def test_claims(self):
        import s6
        rows = [{"name": "작음", "beta": 0.001, "se": 0.005, "dof": 800}, {"name": "큼", "beta": -0.40, "se": 0.03, "dof": 800},
                {"name": "넓음", "beta": -0.05, "se": 0.2, "dof": 800}]
        got = {r["name"]: r["claim"] for r in s6.judge_effects(rows)}
        self.assertEqual(got["작음"], "작음 확인")
        self.assertEqual(got["큼"], "효과 있음")
        self.assertEqual(got["넓음"], "판단 불가")

    def test_gate(self):
        import s6
        import numpy as np
        rng = np.random.default_rng(0)
        base = rng.uniform(1, 2, 200)
        self.assertTrue(s6.gate(base * 0.7, base, 0.7)["pass"])
        self.assertFalse(s6.gate(base * 1.1, base, 1.1)["pass"])

    def test_rain_policy_matches_08(self):
        """08 문서 결과(우도면 효과 있음, 연동 작음 확인)를 같은 정책으로 재현하는지 확인한다."""
        import s6
        path = ROOT / "data" / "interim" / "gates" / "rain_test.json"
        if not path.exists():
            self.skipTest("rain_test.json 없음")
        rows = [{"name": r["dong"], "beta": r["beta"], "se": r["se"], "dof": 800} for r in json.loads(path.read_text(encoding="utf-8"))["per_dong"]]
        got = {r["name"]: r["claim"] for r in s6.judge_effects(rows)}
        self.assertEqual(got["우도면"], "효과 있음")
        self.assertEqual(got["연동"], "작음 확인")


class Planner(unittest.TestCase):
    def _p(self, q, center):
        import planner
        return planner.plan(qparse.parse(q), {"center_db": center})

    def test_time_of_day_relaxed_on_public(self):
        p = self._p("노형동 카페 손님 가장 붐비는 시간이 언제야?", False)
        self.assertEqual(p["status"], "ok")
        self.assertTrue(any("시간대 → 일 단위" in r for r in p["relaxed"]))
        self.assertEqual(self._p("노형동 카페 손님 가장 붐비는 시간이 언제야?", True)["steps"][0]["metric"], "시간대방문")

    def test_bus_hour_maps_to_bus(self):
        self.assertEqual(self._p("탑동 버스 몇시에 제일 많이 타?", True)["steps"][0]["metric"], "시간대버스")

    def test_sales_center_only(self):
        self.assertEqual(self._p("노형동 매출 어때?", False)["status"], "센터에서만 가능")
        self.assertEqual(self._p("노형동 매출 어때?", True)["steps"][0]["route"], "center")

    def test_recipe_steps(self):
        p = self._p("비 오는 날 아라동 방문은?", False)
        self.assertIn("R3", [s.get("recipe") for s in p["steps"]])
        self.assertIn("S6", [s["sub"] for s in p["steps"]])

    def test_no_space_relaxation_and_scope(self):
        self.assertEqual(self._p("노형동 임대료 얼마야?", False)["status"], "범위밖")


class RunnerX2(unittest.TestCase):
    """실험 X2 연결 시험의 기본 경로(05 문서 11-2절)."""
    def _order(self, q="비 오는 날 아라동 방문은?"):
        import planner
        import runner
        return runner.build_order(planner.plan(qparse.parse(q), {"center_db": False}))

    def test_schema_and_success(self):
        import runner
        o = self._order()
        self.assertEqual(runner.validate(o), [])
        r = runner.run(o, {"question": "비 오는 날 아라동 방문은?"})
        self.assertEqual(r["status"], "성공")
        judged = next(v for v in r["store"].values() if "judgement" in v)["judgement"]
        self.assertEqual([j["name"] for j in judged], ["아라동"])  # 동네 필터 전달

    def test_schema_error(self):
        import runner
        o = self._order()
        o["tasks"][1]["depends_on"] = ["t9"]
        self.assertTrue(runner.validate(o))
        o2 = self._order()
        o2["tasks"][1]["out"] = o2["tasks"][0]["out"]  # 저장소 키 충돌
        self.assertTrue(any("충돌" in e for e in runner.validate(o2)))

    def test_retry_then_success(self):
        import runner
        r = runner.run(self._order(), {"inject": {"t1": "실행"}})  # 실행 오류는 1회 재시도로 회복
        self.assertEqual(r["status"], "성공")
        self.assertEqual(next(x for x in r["log"] if x["task_id"] == "t1")["attempts"], 2)

    def test_dependency_skip_partial(self):
        import runner
        r = runner.run(self._order(), {"inject": {"t3": "계산"}})  # S3 실패 → 의존 작업만 건너뜀
        self.assertEqual(r["status"], "부분 결과")
        st = {x["task_id"]: x["status"] for x in r["log"]}
        self.assertEqual(st["t1"], "성공")
        self.assertEqual(st["t3"], "실패")
        self.assertIn("건너뜀", [st["t4"], st["t5"]])

    def test_timeout(self):
        import runner
        o = self._order()
        o["policy"]["timeout_ms"] = 0
        r = runner.run(o, {})
        self.assertTrue(any(x.get("reason") == "시간 초과" for x in r["log"]))

    def test_parallel_same_result(self):
        import runner
        o = self._order("노형동 생활 진단해줘")
        a, b = runner.run(o, {}), runner.run(o, {"parallel": True})
        self.assertEqual(sorted(a["store"]), sorted(b["store"]))
