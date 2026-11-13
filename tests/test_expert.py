"""전문가 모드: 코드 검사·격리 실행·Claude 없이 흉내 낸 흐름(2026-11-13)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import expert  # noqa: E402
import sandbox as S  # noqa: E402

OK = '''m = T["card_month"]
a = m[m.dong == "노형동"].groupby("ym").amt.sum()
result = {"numbers": {"months": len(a), "max_amt": float(a.max())},
          "series": [{"title": "노형동 월 매출", "kind": "line", "x": list(a.index), "y": [float(v) for v in a]}]}'''

ATTACKS = ["import os", "open('x', 'w')", "T['km'].to_csv('a.csv')", "pd.read_parquet('x')", "x = ().__class__.__bases__",
           "getattr(pd, 'read_csv')", "pd.io.common", "np.load('a.npy')", "s = '__cl' + 'ass__'",
           "try:\n    x = 1\nexcept Exception:\n    pass", "f = lambda: 1", "eval('1')", "T['km'].query('n > 1')",
           "exec('x=1')", "y = __builtins__", "x = [0] * (10 ** 10)", "a = np.zeros(200000000)"]


class SandboxTest(unittest.TestCase):
    def test_ok_runs(self):
        r = S.run(OK)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["numbers"]["months"], 81)

    def test_libs_outside_default_location(self):
        """Vercel처럼 라이브러리가 PYTHONPATH로만 보이는 경우(-I가 무시)에도 하위 프로세스가 numpy를 찾는다(2026-11-13 운영 오류)."""
        import subprocess
        import numpy
        site = str(Path(numpy.__file__).resolve().parents[1])
        app = str(Path(S.__file__).resolve().parent)
        probe = ("import sys; sys.path.insert(0, %r); import sandbox as S\n"
                 "if sys.argv[1] == 'none': S.lib_paths = lambda: []\n"
                 "print(S.run('result = {\"numbers\": {\"n\": float(np.mean([1, 2, 3]))}}')['ok'])") % app
        sysdir = Path(sys.base_prefix) / "bin" / "python3"
        exe = str(sysdir) if sysdir.exists() and sys.prefix != sys.base_prefix else None
        if not exe or subprocess.run([exe, "-I", "-c", "import numpy"], capture_output=True).returncode == 0:
            self.skipTest("기본 위치에 numpy가 없는 파이썬이 필요함(가상환경 밖 파이썬)")
        env = {**os.environ, "PYTHONPATH": site}
        out = {m: subprocess.run([exe, "-c", probe, m], capture_output=True, text=True, env=env, timeout=120).stdout.strip() for m in ("fix", "none")}
        self.assertEqual(out, {"fix": "True", "none": "False"})

    def test_attacks_rejected(self):
        for code in ATTACKS:
            with self.subTest(code=code):
                r = S.run(code, timeout=3)
                self.assertFalse(r["ok"])
                self.assertEqual(r["stage"], "검사")

    def test_timeout_and_shape(self):
        self.assertIn("시간 상한", S.run("while True:\n    x = 1", timeout=2)["error"])
        self.assertEqual(S.run("x = 1", timeout=5)["stage"], "형식")  # result 비어 있음
        self.assertIn("모르는 키", S.run("result = {'html': 1}", timeout=5)["error"])


def fake_chat(answers, seen=None):
    """미리 정한 응답을 차례로 돌려주는 가짜 LLM. 항목: (도구, 인자) / [(도구, 인자), ...](한 번에 여러 도구) / ("text", 글)."""
    it = iter(answers)

    def chat(model, messages, tools):
        if seen is not None:
            seen.append([t["function"]["name"] for t in tools])
        a = next(it)
        if isinstance(a, tuple) and a[0] == "text":
            return {"message": {"role": "assistant", "content": a[1]}, "usage": {"input_tokens": 10, "output_tokens": 5}}
        calls = a if isinstance(a, list) else [a]
        return {"message": {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "function": {"name": n, "arguments": g}} for i, (n, g) in enumerate(calls)]},
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    return chat


PY = lambda code: ("run_python", {"method": "추이", "plan": ["월 합계"], "code": code})  # noqa: E731
CORR_Q = "43개 동네 방문과 매출의 상관 분석해줘"


class ExpertFlowTest(unittest.TestCase):
    """도구 루프(문서 26 안 A): 도구 선택·고치기·단계 상한·시간 예산·로컬 종료·규칙 대체."""
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "LLM_BACKEND", "JEJU_LOCAL_AGENT")}
        os.environ["ANTHROPIC_API_KEY"] = "test"
        os.environ.pop("LLM_BACKEND", None)
        os.environ["JEJU_LOCAL_AGENT"] = "0"
        self.budget, self.backend = expert.BUDGET, expert.backend

    def tearDown(self):
        expert.BUDGET, expert.backend = self.budget, self.backend
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_fix_once_then_submit(self):
        seen = []
        chat = fake_chat([PY("import os"), PY(OK), ("submit_answer", {"lines": ["노형동 월 매출은 81개월 자료예요."]})], seen)
        r = expert.ask("노형동 월 매출 추이", chat=chat)
        self.assertEqual(r["status"], "성공")
        self.assertEqual([a["stage"] for a in r["attempts"]], ["검사", "실행"])
        self.assertEqual(r["by"], "AI")
        self.assertEqual([t["tool"] for t in r["trace"]], ["run_python", "run_python", "submit_answer"])
        self.assertEqual(len(seen[0]), 5)  # Claude에는 도구 5개

    def test_wrong_number_falls_back(self):
        chat = fake_chat([PY(OK), ("submit_answer", {"lines": ["상관계수는 0.92이고 증가율은 12.3%예요."]})])
        r = expert.ask("노형동 월 매출 추이", chat=chat)
        self.assertTrue(r["by"].startswith("프로그램"))
        self.assertIn("months: 81", r["lines"])

    def test_step_limit(self):
        chat = fake_chat([PY("import os")] * 6)
        r = expert.ask("파일 읽어 줘", chat=chat)
        self.assertEqual(r["status"], "실패")
        self.assertEqual(len(r["trace"]), expert.MAX_STEPS)
        self.assertIn("기법 목록", r["hint"])

    def test_choose_technique_then_code_ends(self):
        chat = fake_chat([("run_technique", {"technique": "corr", "dongs": [], "target": ""}), ("text", "끝났어요")])
        r = expert.ask(CORR_Q, chat=chat)
        self.assertEqual(r["status"], "성공", r)
        self.assertEqual(r["trace"][0]["tool"], "run_technique")
        self.assertTrue(r["result"]["numbers"])
        self.assertTrue(r["result"]["series"])  # 기법 그래프를 전문가 화면 형식으로 옮김

    def test_describe_and_catalog_then_python(self):
        chat = fake_chat([[("describe_data", {"table": "card_month"}), ("search_center_catalog", {"keyword": "정류소 시간대"})], PY(OK),
                          ("submit_answer", {"lines": ["노형동 월 매출은 81개월 자료예요."]})])
        r = expert.ask("노형동 월 매출 추이", chat=chat)
        self.assertEqual(r["status"], "성공")
        self.assertEqual([t["tool"] for t in r["trace"]], ["describe_data", "search_center_catalog", "run_python", "submit_answer"])
        self.assertTrue(all(t["ok"] for t in r["trace"]))

    def test_submit_before_result_is_refused(self):
        chat = fake_chat([("submit_answer", {"lines": ["그냥 답"]}), PY(OK), ("submit_answer", {"lines": ["81개월 자료예요."]})])
        r = expert.ask("노형동 월 매출 추이", chat=chat)
        self.assertFalse(r["trace"][0]["ok"])
        self.assertEqual(r["status"], "성공")

    def test_time_budget(self):
        expert.BUDGET = -1
        r = expert.ask("노형동 월 매출 추이", chat=fake_chat([PY(OK)]))
        self.assertEqual(r["status"], "실패")
        self.assertEqual(r["trace"][0]["name"], "시간 예산 초과")

    def test_local_backend_stops_after_result(self):
        expert.backend = lambda: "ollama"
        seen = []
        r = expert.ask(CORR_Q, chat=fake_chat([("run_technique", {"technique": "corr", "dongs": [], "target": ""})], seen))
        self.assertEqual(r["status"], "성공")
        self.assertEqual(len(seen), 1)  # 코드가 루프를 끝냄(로컬 모델은 스스로 끝내지 못함)
        self.assertNotIn("run_python", seen[0])  # 로컬에는 코드 실행 도구를 주지 않음
        self.assertEqual(r["by"], "프로그램(기법 코드의 문장)")

    def test_local_no_tool_rule_picks(self):
        expert.backend = lambda: "ollama"
        r = expert.ask(CORR_Q, chat=fake_chat([("text", "상관을 보면 됩니다")]))
        self.assertEqual(r["status"], "성공")
        self.assertTrue(r["trace"][0]["by"].startswith("규칙"))

    def test_wrong_technique_is_sent_back(self):
        q = "노형동 음식점 매출 변화를 건수와 건당 금액으로 분해해줘"
        chat = fake_chat([("run_technique", {"technique": "decomp", "dongs": ["노형동"], "target": "음식점"}),
                          ("run_technique", {"technique": "change", "dongs": ["노형동"], "target": "음식점"}), ("text", "끝")])
        r = expert.ask(q, chat=chat)
        self.assertFalse(r["trace"][0]["ok"])
        self.assertIn("변화 분해", r["trace"][0]["note"])
        self.assertTrue(r["trace"][1]["ok"])

    def test_local_info_question_ends_with_catalog(self):
        expert.backend = lambda: "ollama"
        r = expert.ask("정류소별 시간대 버스 이용 자료는 센터에 있어?", chat=fake_chat([("search_center_catalog", {"keyword": "정류소 시간대"})]))
        self.assertEqual(r["status"], "성공")
        self.assertEqual([t["tool"] for t in r["trace"]], ["search_center_catalog"])
        self.assertEqual(r["result"]["tables"][0]["title"], "센터 자료 찾기 결과")

    def test_bad_dong_is_dropped(self):
        chat = fake_chat([("run_technique", {"technique": "corr", "dongs": ["43개 동네"], "target": ""}), ("text", "끝")])
        r = expert.ask(CORR_Q, chat=chat)
        self.assertEqual(r["status"], "성공")
        self.assertTrue(any("동네 이름이 아니어서" in n for n in r["result"]["notes"]))

    def test_auth_error_is_reported(self):
        def chat(model, messages, tools):
            raise RuntimeError("Error code: 401 - invalid x-api-key")
        r = expert.ask("아무거나", chat=chat)
        self.assertEqual(r["status"], "오류")
        self.assertIn("인증 실패", r["error"])

    def test_disabled_without_key(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        self.assertEqual(expert.ask("아무거나")["status"], "꺼짐")


if __name__ == "__main__":
    unittest.main()
