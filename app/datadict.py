"""상세 분석(설계 11-2절)용 자료 사전: Claude에게 줄 표 이름·칸·단위·기간 설명(2026-11-13).

- 값은 `data/tables/`에서 실제로 읽어 기간·행 수를 채운다(설명 문장만 손으로 적음).
- 지도·내부용 표(map_dong, map_grid, weather)는 넣지 않는다.
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "data" / "tables"

DESC = {
    "card_month": ("제주관광공사 카드 매출(월 × 행정동 43 × 업종 대분류 5 × 손님 구분). 이미 월 합계라 더 합치지 말고, 동네·업종 전체는 cust까지 합친다",
                   {"ym": "연월 'YYYY-MM'", "dong": "행정동 이름", "biz": "업종 대분류 5개", "cust": "손님 구분(도민·내국인 관광객)",
                    "amt": "카드 매출액(원)", "cnt": "카드 이용 건수(건)"}),
    "card_hour": ("제주관광공사 카드 매출 시간대(월 × 행정동 × 업종 5 × 손님 구분 × 시). 월 매출이 필요하면 hour를 합치거나 card_month를 쓴다. 2024-10부터만 있음",
                  {"ym": "연월", "dong": "행정동", "biz": "업종 대분류", "cust": "손님 구분(도민·내국인 관광객·외국인 관광객)",
                   "hour": "시(0~23)", "amt": "카드 매출액(원)", "cnt": "이용 건수(건)"}),
    "card_foreign": ("외국인 관광객 카드 소비(월 × 업종 5 × 출신지역 7, 제주 전체)",
                     {"ym": "연월", "biz": "업종 대분류", "origin": "출신지역", "amt": "소비 금액(원)", "cnt": "건수"}),
    "card746_month": ("제주데이터허브 746 업종별 카드 매출(월 × 행정동 × 업종 42, 코로나 이전 장기 자료). 관광공사 자료와 카드사가 달라 금액을 이어 붙이지 말 것",
                      {"ym": "연월", "dong": "행정동", "biz": "업종 대분류로 맞춘 값", "biz_certain": "대분류 대응이 확실한지",
                       "biz42": "원래 업종 42개", "cust": "손님 구분(도민·내국인 관광객·외국인 관광객·법인)", "amt": "매출액(원)"}),
    "pop_month": ("제주데이터허브 583 유동인구(월 합계 × 행정동). 집계 단위가 공개되지 않아 사람 수가 아님. 비율·순위·변화율로만 해석",
                  {"dong": "행정동", "ym": "연월", "resd": "거주 인구 지수(월 합)", "work": "직장 인구 지수(월 합)",
                   "visit": "방문 인구 지수(월 합)", "days": "그 달에 자료가 있는 날 수(일평균 = 값 ÷ days)"}),
    "pop_age": ("583 유동인구 연령·성별(연 합계 × 행정동). 사람 수가 아닌 지수",
                {"dong": "행정동", "year": "연도(마지막 해는 덜 찬 해)", "gender": "성별", "ageGroup": "연령대",
                 "resd": "거주 지수", "visit": "방문 지수", "work": "직장 지수"}),
    "bus_month": ("버스 승차(월 × 행정동 × 이용자 유형)",
                  {"dong": "행정동", "ym": "연월", "user_type": "이용자 유형", "n": "승차 건수", "days": "자료 있는 날 수"}),
    "biz": ("상가(상권) 정보 가게 수(기준 2026-09 단면, 행정동 × 업종 대·중·소분류)",
            {"dong": "행정동", "major": "대분류", "middle": "중분류", "minor": "소분류", "count": "가게 수(곳)"}),
    "rest_events": ("음식점 인허가 개업·폐업 건수(연 × 행정동 × 업태)",
                    {"dong": "행정동", "category": "업태(빈 값 있음)", "year": "연도(마지막 해는 덜 찬 해)", "kind": "open 개업 / close 폐업", "count": "건수"}),
    "km": ("음식점 생존율(행정동 × 영업 연수, Kaplan-Meier)",
           {"dong": "행정동", "year": "영업 연수(1~5)", "survival_pct": "생존율(%)", "lo_pct": "95% 구간 하한", "hi_pct": "95% 구간 상한",
            "n": "표본 가게 수", "label": "제주 평균 대비 판정"}),
    "close_3y": ("음식점 최근 3년 폐업률(행정동)",
                 {"dong": "행정동", "closed": "폐업 수", "store_years": "가게-연(분모)", "rate_pct": "폐업률(%)",
                  "lo_pct": "구간 하한", "hi_pct": "구간 상한", "label": "제주 평균 대비 판정"}),
}


@lru_cache(maxsize=1)
def load_tables():
    """이름 → DataFrame. 격리 실행기와 사전이 같은 표를 쓴다."""
    return {n: pd.read_parquet(TABLES / f"{n}.parquet") for n in DESC}


def describe():
    """Claude에게 줄 사전 문자열."""
    out = []
    for n, (title, cols) in DESC.items():
        d = load_tables()[n]
        rng = ""
        for c in ("ym", "year"):
            if c in d:
                rng = f", {c} {d[c].min()}~{d[c].max()}"
                break
        out.append(f"- {n}: {title}. {len(d):,}행{rng}")
        for c, m in cols.items():
            extra = ""
            if d[c].dtype == object and d[c].nunique() <= 12:
                extra = " 값: " + ", ".join(map(str, sorted(d[c].dropna().astype(str).unique())))
            out.append(f"    - {c}: {m}.{extra}")
    return "\n".join(out)
