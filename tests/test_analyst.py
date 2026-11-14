"""로컬 분석 담당 Agent(app/analyst.py): 단계마다 모델이 판단하고 코드가 검사한다."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import analyst  # noqa: E402


def fake(answers, seen=None):
    """단계마다 미리 정한 JSON 본문을 돌려주는 가짜 모델."""
    it = iter(answers)

    def chat(model, messages, tools):
        if seen is not None:
            seen.append(messages[0]["content"][:20])
        return {"message": {"content": json.dumps(next(it), ensure_ascii=False)}}
    return chat


U = lambda kind, dongs=(), target="": {"kind": kind, "dongs": list(dongs), "target": target, "keyword": "", "reason": "요청 뜻"}  # noqa: E731
EX = {"lines": ["방문이 많은 동네일수록 매출도 높은 편이에요.", "다만 같이 움직인다고 원인이라는 뜻은 아니에요."]}
NX = {"next": ["regress"], "reason": "어떤 요인이 매출을 설명하는지 보면 좋아요"}


class AnalystTest(unittest.TestCase):
    def test_model_maps_plain_request_to_technique(self):  # 기법 이름 없는 요청을 모델이 기법과 연결
        r = analyst.run("동네별로 사람이 많이 오는 곳이 장사도 잘 되는지 보여줘", chat=fake([U("corr"), EX, NX]))
        self.assertEqual(r["status"], "성공")
        self.assertIn("상관", r["method"])
        self.assertEqual([t["by"] for t in r["trace"]][0], "AI(로컬 모델)")
        self.assertTrue(any("다음으로 볼 만한 분석" in x for x in r["lines"]))

    def test_named_mismatch_is_asked_again_then_fixed_by_code(self):
        r = analyst.run("노형동 음식점 매출 시계열 분해해줘", chat=fake([U("outlier", ["노형동"]), U("outlier", ["노형동"]), EX, NX]))
        self.assertIn("시계열 분해", r["method"])
        self.assertTrue(any(t["by"] == "코드" and "바로잡음" in t["note"] for t in r["trace"]))

    def test_explain_with_numbers_is_replaced(self):  # 해석 문장에 숫자가 있으면 버린다
        bad = {"lines": ["상관계수는 0.9예요."]}
        r = analyst.run("43개 동네 방문과 매출의 상관 분석해줘", chat=fake([U("corr"), bad, NX]))
        ex = next(t for t in r["trace"] if t["tool"] == "explain")
        self.assertFalse(ex["ok"])
        self.assertNotIn("상관계수는 0.9예요.", r["lines"])

    def test_rejected_technique_gets_alternative(self):  # 조건이 안 맞으면 모델이 대안을 고른다(입지계수는 동네가 필요)
        r = analyst.run("업종이 어디에 몰려 있는지 알려줘", chat=fake([U("lq"), {"kind": "hhi", "reason": "동네 없이 볼 수 있어요"}, EX, NX]))
        self.assertTrue(any(t["tool"] == "alternative" for t in r["trace"]))
        self.assertIn("업종 다양성", r["method"])

    def test_general_question_uses_general_path(self):
        r = analyst.run("노형동 카페 몇 개야?", chat=fake([U("general", ["노형동"], "카페")]))
        self.assertEqual(r["method"], "일반 답 경로")
        self.assertIn("노형동", r["lines"][0])

    def test_unknown_dong_dropped_and_filled_from_question(self):
        u, log = analyst.understand("노형동 업종 입지계수", chat=fake([U("lq", ["노형시"])]))
        self.assertEqual(u["dongs"], ["노형동"])
        self.assertTrue(any("채움" in x["note"] for x in log))


if __name__ == "__main__":
    unittest.main()
