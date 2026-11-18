"""동네 × 업종 생존율·폐업률 표(문제 기록 4번 실패 검토 ④, 마스터 2026-11-17 '업종별 생존을 셀 개업 기간을 수립').

기준은 기존 동네 음식점 전체(build_dong_tables.build_restaurants)와 같게 둔다.
- 5년 생존율: 카플란-마이어, 개업 코호트 2015-01-01 ~ (관측 끝 − 5년). 모든 가게를 5년 동안 따라갈 수 있는 구간이다.
- 3년 폐업률: 관측 끝 직전 완전한 3년, 해마다 연초에 영업 중이던 가게 중 그해 폐업한 비율의 합.
- 업종 묶음: places.REST_MAP(카페 = 커피숍·까페·다방 등). '음식'(전체)은 기존 표가 맡는다.
- 표본: 동네 × 업종 개업 코호트가 50곳 미만이면 값은 남기되 label을 '표본 부족'으로 두고 비교·순위에서 뺀다(사용자 확정 2026-11-06 3번과 같은 기준).
- 판정: 같은 업종의 제주 전체 값과 견줘 BH 보정(q = 0.10) 뒤에도 차이가 남는 동네만 '제주 평균보다 높음·낮음'.
입력: data/tables/rest_cohort.parquet(제출본에 있음). 출력: data/tables/km_biz.parquet, data/tables/close_biz.parquet
사용: python app/build_biz_survival.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from places import REST_MAP
from stats import bh, km_at, loglog_ci, two_sided_p, wilson

TAB = Path(__file__).resolve().parents[1] / "data" / "tables"
Q, MIN_N, KM_START = 0.10, 50, "2015-01-01"


def main():
    rest = pd.read_parquet(TAB / "rest_cohort.parquet")
    dongs = sorted(pd.read_parquet(TAB / "km.parquet").query("dong != '제주 전체'")["dong"].unique())
    end = rest[["open_date", "close_date"]].max().max()
    km_end = end - pd.DateOffset(years=5)
    years = [end.year - 3, end.year - 2, end.year - 1]
    r = rest[rest["admin_dong"].isin(dongs)]
    km_rows, cl_rows = [], []
    for grp, cats in REST_MAP.items():
        if not cats:
            continue
        g = r[r["업종구분소분류"].isin(cats)]
        # 5년 생존(KM)
        co = g[(g["open_date"] >= KM_START) & (g["open_date"] <= km_end)].copy()
        co["event"] = co["close_date"].notna()
        co["y"] = ((co["close_date"].fillna(end) - co["open_date"]).dt.days / 365.25).clip(lower=0)
        j5, jse, jn = km_at(co["y"].to_numpy(), co["event"].to_numpy(), 5)
        p5, cells = {}, []
        for d in dongs:
            x = co[co["admin_dong"] == d]
            if len(x) == 0:
                continue
            s, se, n = km_at(x["y"].to_numpy(), x["event"].to_numpy(), 5)
            lo, hi = loglog_ci(s, se)
            cells.append([d, grp, 5, s * 100, lo * 100, hi * 100, len(x)])
            if len(x) >= MIN_N and se > 0:
                p5[d] = two_sided_p((s - j5) / se)
        sig = set(bh(pd.Series(p5, dtype=float), Q)) if p5 else set()
        for c in cells:
            c.append("표본 부족" if c[6] < MIN_N else ("차이 확인 안 됨" if c[0] not in sig else ("제주 평균보다 높음" if c[3] > j5 * 100 else "제주 평균보다 낮음")))
        km_rows += cells
        km_rows.append(["제주 전체", grp, 5, j5 * 100, *(v * 100 for v in loglog_ci(j5, jse)), len(co), ""])
        # 3년 폐업률
        k, n = pd.Series(0.0, index=dongs), pd.Series(0.0, index=dongs)
        for yy in years:
            s_, e_ = pd.Timestamp(f"{yy}-01-01"), pd.Timestamp(f"{yy}-12-31")
            alive = g[(g["open_date"] < s_) & (g["close_date"].isna() | (g["close_date"] >= s_))]
            n += alive.groupby("admin_dong").size().reindex(dongs).fillna(0)
            k += alive[alive["close_date"].between(s_, e_)].groupby("admin_dong").size().reindex(dongs).fillna(0)
        base = k.sum() / n.sum() if n.sum() else np.nan
        pc = {d: two_sided_p((k[d] / n[d] - base) / np.sqrt(base * (1 - base) / n[d])) for d in dongs if n[d] >= MIN_N}
        sigc = set(bh(pd.Series(pc, dtype=float), Q)) if pc else set()
        for d in dongs:
            if n[d] == 0:
                continue
            lo, hi = wilson(k[d], n[d])
            rate = k[d] / n[d]
            lab = "표본 부족" if n[d] < MIN_N else ("차이 확인 안 됨" if d not in sigc else ("제주 평균보다 높음" if rate > base else "제주 평균보다 낮음"))
            cl_rows.append([d, grp, int(k[d]), int(n[d]), rate * 100, lo * 100, hi * 100, lab])
        cl_rows.append(["제주 전체", grp, int(k.sum()), int(n.sum()), base * 100, np.nan, np.nan, ""])
    km = pd.DataFrame(km_rows, columns=["dong", "group", "year", "survival_pct", "lo_pct", "hi_pct", "n", "label"])
    cl = pd.DataFrame(cl_rows, columns=["dong", "group", "closed", "store_years", "rate_pct", "lo_pct", "hi_pct", "label"])
    km.to_parquet(TAB / "km_biz.parquet", index=False)
    cl.to_parquet(TAB / "close_biz.parquet", index=False)
    print("km_biz", len(km), "close_biz", len(cl), "코호트", f"{KM_START[:7]}~{str(km_end.date())[:7]}", "폐업 연도", f"{years[0]}~{years[-1]}")
    print(km[(km["year"] == 5) & (km["n"] >= MIN_N)].groupby("group").size().to_dict())


if __name__ == "__main__":
    main()
