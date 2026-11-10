"""X1 시험 문항(Gemini c2g 021, 사전을 보지 않고 작성)의 자유 문장 정답 의도를 질문 Tuple 값으로 정규화한다.

- 원본: interaction/gemini_work/021/x1_test.jsonl (고치지 않음)
- 산출: data/x1/test_gold.jsonl. 칸마다 '허용 값 집합'을 둔다. 의도가 둘로 읽히는 문항(예: 거주·방문 연령)은 둘 다 정답으로 본다.
- 채점 핵심 칸: type, expect, space, target. metric은 허용 집합과 겹치면 정답. time·breakdown·cond는 보조 지표.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

FINAL = "--final" in sys.argv  # 022 최종 시험 문항: Claude는 내용을 출력하지 않는다
STD = "--std150" in sys.argv  # 023 표준어 150문항(블라인드)
STDB = "--std150b" in sys.argv  # 024 표준어 150문항(최종 블라인드)
STDC = "--std150c" in sys.argv  # 025 표준어 150문항(보완 뒤 최종 확인)
SRC = Q.ROOT / "interaction" / "gemini_work" / ("025/x1_test_std150c.jsonl" if STDC else "024/x1_test_std150b.jsonl" if STDB else "023/x1_test_std150.jsonl" if STD else "022/x1_test_final.jsonl" if FINAL else "021/x1_test.jsonl")
OUT = Q.ROOT / "data" / "x1" / ("test_std150c_gold.jsonl" if STDC else "test_std150b_gold.jsonl" if STDB else "test_std150_gold.jsonl" if STD else "test_final_gold.jsonl" if FINAL else "test_gold.jsonl")
SKIP = None  # 채점하지 않는 칸
METRIC = {"점포 수": {"점포수", "특화계수"}, "유동인구": {"일평균방문", "방문거주비"}, "방문인구": {"일평균방문", "방문거주비"}, "유동인구/방문": {"일평균방문", "방문거주비"},
          "거주인구": {"거주연령구성", "고령비중", "청년비중"}, "폐업률": {"폐업률"}, "고령인구 비중": {"고령비중"}, "버스 이용량": {"버스일평균"},
          "개업 수": {"개업수"}, "폐업 수": {"폐업수"}, "경로 버스 이용량": {"경로일평균", "경로비중"}, "생존율": {"5년생존율", "조건부생존"},
          "점포 수/매출": {"점포수", "매출"}, "연령비율": {"거주연령구성", "방문연령구성"}, "자료 목록": {"자료목록"}, "청년인구 비중": {"청년비중"},
          "버스 정류소 수/이용량": {"버스일평균"}, "폐업 급증(잔차)": {"폐업수"}, "폐업 급증": {"폐업수"}, "개업 급증(잔차)": {"개업수"}}
TARGET = {"한식": {"한식"}, "카페": {"카페"}, "치킨": {"치킨"}, "음식점": {"음식점"}, "어르신": {"어르신"}, "일식": {"일식"}, "청년": {"청년"}, "주점": {"주점"},
          "음식점, 어르신": {"음식점", "어르신"}, "한식, 어르신": {"한식", "어르신"}, "청년, 카페": {"청년", "카페"}, "-": {None}, "전체": {None, "음식점"}}
TIME = {"최근 1년": "최근1년", "최근 3년": "최근3년", "최근 2년": "최근3년", "다음 분기": "다음분기", "다음 달": "다음달", "실시간": "지금", "실시간/당일 저녁": "지금"}
COND = {"비": ["비"], "비, 주말": ["비", "주말"], "평일": ["평일"]}
# 022 최종 문항의 값 표기(정답 칸 값 목록만 보고 작성, 질문 문장은 보지 않음)
METRIC.update({"유동인구": {"일평균방문", "방문거주비"}, "관광객방문": {"일평균방문", "방문거주비"}, "방문변화": {"일평균방문"},
               "카페폐업률": {"폐업률"}, "버스이용": {"버스일평균", "경로일평균", "정류소일이용", "시간대버스"}, "버스이용급감": {"버스일평균", "경로일평균"},
               "음식점생존율": {"5년생존율", "조건부생존"}, "어르신인구": {"고령비중", "거주연령구성"}, "어르신비율": {"고령비중", "경로비중"},
               "청년유동인구비중": {"청년비중", "방문연령구성"}, "폐업급증": {"폐업수"}, "창업현황": {"개업수", "점포수"}, "자료탐색": {"자료목록"}, "점포수": {"점포수", "특화계수"}})
TARGET.update({"고기집": {"한식"}, "베이커리": {"카페"}, "식당": {"음식점"}, "식음료": {"음식점", "카페"}, "치킨_주점": {"치킨", "주점"}, "분식": {"분식"}, "횟집": {"횟집"},
               "상가": {None, "소매", "음식점"}, "None": {None}, "버스정류장": {None}, "교통": {None}})
# 023 표준어 150문항의 값 표기(정답 칸 값 목록만 보고 작성)
METRIC.update({"관광객비율": {"방문거주비", "일평균방문"}, "청년유동인구": {"청년비중", "방문연령구성"}, "유동인구배율": {"방문거주비"}, "체류인구배율": {"방문거주비"},
               "청년인구": {"청년비중", "거주연령구성"}, "폐업추이": {"폐업수"}, "방문객비율": {"방문거주비"}, "외지인비중": {"방문거주비"}, "폐업률급증": {"폐업률", "폐업수"},
               "방문인구급감": {"일평균방문"}, "폐업비율악화": {"폐업률"}, "방문감소": {"일평균방문"}, "생존율": {"5년생존율", "조건부생존"}})
TARGET.update({"관광객": {None}, "숙박": {"숙박"}, "편의점": {"편의점"}})
# 024 값 표기(정답 칸 값 목록만 보고 작성)
METRIC.update({"인구구성": {"거주연령구성", "방문연령구성", "고령비중", "청년비중"}, "자료보유": {"자료목록"}, "시간대방문": {"시간대방문"},
               "시간대버스": {"시간대버스", "버스일평균"}, "버스급감": {"버스일평균"}, "방문급감": {"일평균방문"}, "폐업급증": {"폐업수"}})
TARGET.update({"양식": {"음식점", None}, "고깃집": {"한식"}, "국수": {"한식", "분식", "음식점"}, "피자": {"음식점", None}, "중식": {"중식"}})
NONFOOD = {"미용실", "학원", "독서실", "병원", "동물병원"}
# 025 값 표기(정답 칸 값 목록만 보고 작성)
METRIC.update({"폐업수": {"폐업수"}, "개업수": {"개업수"}, "방문객": {"일평균방문", "방문거주비"}, "어르신비중": {"고령비중", "경로비중"},
               "시간대유동인구": {"시간대방문"}, "시간대방문객": {"시간대방문"}, "주말효과": {"일평균방문", "버스일평균"}, "강수효과": {"일평균방문", "버스일평균"},
               "개업급감": {"개업수"}, "버스급락": {"버스일평균"}, "폐업률급등": {"폐업률", "폐업수"}, "폐업집중": {"폐업수", "폐업률"},
               "폐업배율": {"폐업률", "폐업수"}, "관광객급감": {"일평균방문"}, "매출액": {"매출"}})


def norm(r):
    it = r["intent"]
    expect = {"답함": "답함", "되묻기": "되묻기", "범위 밖": "범위밖"}[r["expect"]]
    typ = r["type"] if r["type"] in Q.TYPES else SKIP
    it = {k: (v if v != "None" else None) for k, v in it.items()}  # 되묻기 문항은 유형을 채점하지 않는다
    ms = set()
    for m in it.get("지표") or []:
        ms |= METRIC.get(m, set())
    tgt = str(it.get("대상", "-"))
    # 대상 = 업종 또는 인구 집단(05 문서 3-1절). T11 자료 탐색·범위 밖의 대상은 채점하지 않는다(Fable 2차 주석 일치도 분석 2026-11-11)
    tgt_ok = TARGET.get(tgt, SKIP) if expect != "범위밖" and r["type"] != "T11" else SKIP
    sub = str(it.get("세분"))
    if tgt_ok is not SKIP and sub in ("어르신", "청년"):  # 인구 집단을 세분에 적은 경우 대상으로도 인정
        tgt_ok = set(tgt_ok) | {sub}
    # 비외식 업종의 점포 수는 상가(793)로 답할 수 있다 → 범위 밖·답함 둘 다 인정(자료 실제와 정답 기준의 차이)
    alt = expect == "범위밖" and any("점포" in str(m) for m in (it.get("지표") or [])) and str(it.get("대상")) in NONFOOD
    return {"id": r["id"], "q": r["q"], "type": typ, "expect": expect, "expect_alt": ["답함"] if alt else [], "space": sorted(x for x in (it.get("공간") if isinstance(it.get("공간"), list) else [it.get("공간")]) if x in Q.DONGS),
            "metric_ok": sorted(ms) or SKIP, "target_ok": None if tgt_ok is SKIP else sorted(x or "" for x in tgt_ok),
            "time": TIME.get(it.get("시간")), "breakdown": None if it.get("세분") in (None, "-") else it["세분"].split(",")[0].strip(),
            "cond": COND.get(it.get("조건"), []) if isinstance(it.get("조건"), str) else []}


def main():
    rows = [json.loads(x) for x in SRC.read_text(encoding="utf-8").splitlines() if x.strip()]
    gold = [norm(r) for r in rows]
    bad = [g["id"] for g in gold if any(s not in Q.DONGS for s in g["space"])]
    assert not bad, bad
    OUT.write_text("\n".join(json.dumps(g, ensure_ascii=False) for g in gold) + "\n", encoding="utf-8")
    unmapped = sorted({m for r in rows for m in r["intent"].get("지표") or [] if m not in METRIC})
    print(len(gold), "문항 저장. 정규화 못 한 지표 이름 수:", len(unmapped))  # 이름은 출력하지 않는다(최종 문항 비공개)


if __name__ == "__main__":
    main()
