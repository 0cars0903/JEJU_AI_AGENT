"""가설 H1·H2·H3 판정 자료를 계획(docs/기획/01_개발방향.md 3.3절)대로 계산한다.

입력: data/interim/ (build_tables.py 결과, api 수집 파일). 실행 시점까지 받은 583 날짜만 쓴다.
출력: data/interim/eda/ — dong_metrics.csv(동네 × 지표), weather_effect.csv, summary.json
임계값 판정은 하지 않는다. 판정 수치는 분포를 본 뒤 사용자가 정한다.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stats import effect, km_at, spearman, wilson

ROOT = Path(__file__).resolve().parents[1]
IN, OUT = ROOT / "data" / "interim", ROOT / "data" / "interim" / "eda"
OUT.mkdir(exist_ok=True)
S = {}
MOUNTAIN = {"어리목", "삼각봉", "사제비", "영실", "윗세오름", "한라산남벽", "진달래밭", "성판악", "한라생태숲"}  # 산간 관측소


def load_api(data_id):
    fs = sorted((IN / "api" / str(data_id)).glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True), [f.stem for f in fs]


stores = pd.read_parquet(IN / "stores.parquet")
rest = pd.read_parquet(IN / "restaurants.parquet")
sd = pd.read_parquet(IN / "station_dong.parquet")
pop, pop_days = load_api(583)
wx, wx_days = load_api(579)
wx = wx.drop_duplicates()
DONGS = sorted(stores["행정동명"].unique())
M = pd.DataFrame(index=DONGS)

# ---------- H1 매핑 ----------
cut = pd.Timestamp("2019-01-01")
target = rest[(rest["open_date"] >= cut) | (rest["close_date"] >= cut) | rest["close_date"].isna()]
how = target["dong_how"].value_counts()
one = sd.drop_duplicates("station_name")
_u, _u24 = one["users_total"].sum(), one["users_2024"].sum()
_mapped = one[one["dong"].notna()]
S["H1"] = {
    "583_vs_793_dong_same": set(pop["emd"]) == set(DONGS),
    "780_target_n": int(len(target)),
    "780_by_how_pct": (how / len(target) * 100).round(2).to_dict(),
    "743_names": int(len(one)), "743_mapped_names": int(len(_mapped)),
    "743_mapped_user_pct": round(_mapped["users_total"].sum() / _u * 100, 2),
    "743_mapped_user_pct_2024": round(_mapped["users_2024"].sum() / _u24 * 100, 2),
    "743_by_how": one["how"].value_counts().to_dict(),
    "743_split_names": int(one["ambiguous"].sum()),
    "743_split_user_pct_2024": round(one.loc[one["ambiguous"], "users_2024"].sum() / _u24 * 100, 2),
    "743_unmapped_top20_2024": one[one["dong"].isna()].nlargest(20, "users_2024")[["station_name", "users_2024"]].values.tolist(),
}

# ---------- H2 기간 ----------
bus_days, bus_year = {}, {}
for f in sorted((IN / "bus_daily").glob("*.parquet")):
    b = pd.read_parquet(f, columns=["base_date", "user_count"])
    g = b.groupby("base_date")["user_count"].sum()
    bus_days[f.stem] = int(g.size); bus_year[f.stem] = int(g.sum())
    last_bus = g.index.max()
pdays = pd.to_datetime(pop_days)
maxd = rest[["open_date", "close_date"]].max().max()
S["H2"] = {
    "583_collected_days": len(pop_days), "583_first": pop_days[0], "583_last": pop_days[-1],
    "583_missing_days_in_2y": int(len(pd.date_range(pdays.min(), pdays.max()).difference(pdays))),
    "579_days": len(wx_days), "579_first": wx_days[0], "579_last": wx_days[-1],
    "743_days_by_year": bus_days, "743_users_by_year": bus_year, "743_last": str(last_bus),
    "780_last_event": str(maxd.date()),
    "780_open_by_year": {str(y): int((rest["open_date"].dt.year == y).sum()) for y in range(2022, 2026)},
    "780_close_by_year": {str(y): int((rest["close_date"].dt.year == y).sum()) for y in range(2022, 2026)},
}

# ---------- H3 793 상가 ----------
M["점포수"] = stores.groupby("행정동명").size()
t = stores.pivot_table(index="행정동명", columns="상권업종대분류명", aggfunc="size", fill_value=0)
lq = (t.div(t.sum(1), axis=0)) / (t.sum(0) / t.values.sum())
for c in ["음식", "소매", "숙박", "교육", "보건의료"]:
    M[f"LQ_{c}"] = lq[c]
M["LQ_최대값"] = lq.max(1); M["LQ_최대업종"] = lq.idxmax(1)

# ---------- H3 780 폐업률·생존 ----------
r = rest[rest["admin_dong"].notna() & rest["admin_dong"].isin(DONGS)].copy()
for y in [2022, 2023, 2024]:
    s, e = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
    alive = r[(r["open_date"] < s) & (r["close_date"].isna() | (r["close_date"] >= s))].groupby("admin_dong").size()
    closed = r[(r["open_date"] < s) & (r["close_date"].between(s, e))].groupby("admin_dong").size()
    M[f"연초영업_{y}"] = alive; M[f"폐업_{y}"] = closed
    M[f"폐업_{y}"] = M[f"폐업_{y}"].fillna(0)
    M[f"폐업률_{y}"] = M[f"폐업_{y}"] / M[f"연초영업_{y}"]
    M[f"순증_{y}"] = r[r["open_date"].dt.year == y].groupby("admin_dong").size().reindex(DONGS).fillna(0) - r[r["close_date"].dt.year == y].groupby("admin_dong").size().reindex(DONGS).fillna(0)
base = M["폐업_2024"].sum() / M["연초영업_2024"].sum()
ci = [wilson(k, n) for k, n in zip(M["폐업_2024"], M["연초영업_2024"])]
M["폐업률_2024_하한"], M["폐업률_2024_상한"] = zip(*ci)
cohort = r[r["open_date"] >= "2015-01-01"].copy()
end = maxd
cohort["event"] = cohort["close_date"].notna()
cohort["years"] = ((cohort["close_date"].fillna(end) - cohort["open_date"]).dt.days / 365.25).clip(lower=0)
rows = {}
for dong, g in cohort.groupby("admin_dong"):
    s3, _, _ = km_at(g["years"].to_numpy(), g["event"].to_numpy(), 3)
    s5, se5, n = km_at(g["years"].to_numpy(), g["event"].to_numpy(), 5)
    rows[dong] = (n, s3, s5, se5)
km = pd.DataFrame.from_dict(rows, orient="index", columns=["KM_n", "생존3년", "생존5년", "생존5년_SE"])
M = M.join(km)
all3, _, _ = km_at(cohort["years"].to_numpy(), cohort["event"].to_numpy(), 3)
all5, allse, alln = km_at(cohort["years"].to_numpy(), cohort["event"].to_numpy(), 5)

# ---------- H3 583 유동인구 ----------
pop["date"] = pd.to_datetime(pop["baseDate"])
for c in ["resdPop", "workPop", "visitPop"]:
    pop[c] = pd.to_numeric(pop[c], errors="coerce")
daily = pop.groupby(["emd", "date"])[["resdPop", "workPop", "visitPop"]].sum().reset_index()
prov = daily.groupby("date")[["resdPop", "workPop", "visitPop"]].sum()
A = pop["date"] < "2025-01-01"
def pop_ratios(p):
    g = p.groupby("emd")[["resdPop", "workPop", "visitPop"]].sum()
    return pd.DataFrame({"방문거주비": g["visitPop"] / g["resdPop"], "근무거주비": g["workPop"] / g["resdPop"]})
R = pop_ratios(pop); RA, RB = pop_ratios(pop[A]), pop_ratios(pop[~A])
M = M.join(R)
ages = pop.groupby(["emd", "ageGroup"])["resdPop"].sum().unstack()
M["거주_60대이상비중"] = (ages["60대"] + ages["70대이상"]) / ages.sum(1)
M["거주_20_30대비중"] = (ages["20대"] + ages["30대"]) / ages.sum(1)

# ---------- H3 743 버스 ----------
def bus_dong(year):
    b = pd.read_parquet(IN / "bus_daily" / f"{year}.parquet")
    b = b.merge(sd[["station_name", "dong", "weight", "ambiguous"]], on="station_name", how="left")
    b["user_count"] = b["user_count"] * b["weight"].fillna(1.0)  # 여러 동 후보 이름은 가중치로 나눔
    return b
b24, b23 = bus_dong(2024), bus_dong(2023)
n24 = b24["base_date"].nunique()
bd = b24.groupby("dong")["user_count"].sum() / n24
M["버스일평균"] = bd
ty = b24.pivot_table(index="dong", columns="user_type", values="user_count", aggfunc="sum", fill_value=0)
M["버스_경로비중"] = ty["경로"] / ty.sum(1); M["버스_청소년비중"] = ty["청소년"] / ty.sum(1)
M["버스증감_23_24"] = bd / (b23.groupby("dong")["user_count"].sum() / b23["base_date"].nunique()) - 1
clean = b24[~b24["ambiguous"].fillna(False).astype(bool)].groupby("dong")["user_count"].sum() / n24
M["정류소수_743"] = sd[sd["dong"].notna()].groupby("dong").size()
M["버스증감_23_24"] = M["버스증감_23_24"].round(4)
M["버스일평균_모호제외"] = clean

# ---------- 분포 요약 ----------
NUM = ["점포수", "LQ_음식", "LQ_소매", "LQ_숙박", "LQ_교육", "LQ_보건의료", "폐업률_2023", "폐업률_2024", "순증_2024", "생존3년", "생존5년",
       "방문거주비", "근무거주비", "거주_60대이상비중", "거주_20_30대비중", "버스일평균", "버스_경로비중", "버스_청소년비중", "버스증감_23_24"]
rowsd = []
for c in NUM:
    x = M[c].dropna()
    rowsd.append(dict(지표=c, 동네수=len(x), 최소=x.min(), Q1=x.quantile(.25), 중앙값=x.median(), Q3=x.quantile(.75), 최대=x.max(),
                      CV=x.std() / x.mean() if x.mean() else None,
                      하위=", ".join(x.nsmallest(2).index), 상위=", ".join(x.nlargest(2).index)))
dist = pd.DataFrame(rowsd)
dist.to_csv(OUT / "distribution.csv", index=False, encoding="utf-8-sig")

# 안정성: 기간을 바꿔도 동네 순위가 유지되는가(스피어만)
S["H3_stability"] = {
    "폐업률_2023_vs_2024": spearman(M["폐업률_2023"], M["폐업률_2024"]),
    "폐업률_2022_vs_2023": spearman(M["폐업률_2022"], M["폐업률_2023"]),
    "버스일평균_2023_vs_2024": spearman((b23.groupby("dong")["user_count"].sum()), b24.groupby("dong")["user_count"].sum()),
    "버스일평균_전체_vs_모호제외": spearman(M["버스일평균"], M["버스일평균_모호제외"]),
    "방문거주비_기간A_vs_B": spearman(RA["방문거주비"], RB["방문거주비"]),
    "근무거주비_기간A_vs_B": spearman(RA["근무거주비"], RB["근무거주비"]),
}
S["H3_close_rate"] = {
    "jeju_2024": round(base, 4),
    "dongs_ci_excl_jeju": int(((M["폐업률_2024_하한"] > base) | (M["폐업률_2024_상한"] < base)).sum()),
    "min_base_2024": int(M["연초영업_2024"].min()), "min_base_dong": M["연초영업_2024"].idxmin(),
}
S["H3_km"] = {"cohort_n": int(alln), "jeju_3y": round(all3, 4), "jeju_5y": round(all5, 4),
              "dongs_ci_excl_jeju_5y": int((((M["생존5년"] - 1.96 * M["생존5년_SE"]) > all5) | ((M["생존5년"] + 1.96 * M["생존5년_SE"]) < all5)).sum()),
              "min_n": int(M["KM_n"].min()), "min_n_dong": M["KM_n"].idxmin()}
S["583_scale"] = {"jeju_resd_daily_median": int(prov["resdPop"].median()), "jeju_visit_daily_median": int(prov["visitPop"].median()), "jeju_work_daily_median": int(prov["workPop"].median())}
S["bus_zero_dongs"] = [d for d in DONGS if pd.isna(M.loc[d, "버스일평균"])]

# ---------- 강수일 효과(임시 기준: 산간 제외 관측소 일강수 중앙값 1mm 이상) ----------
wx["rain"] = pd.to_numeric(wx["dailyRainfall"], errors="coerce")
low = wx[~wx["observatoryName"].isin(MOUNTAIN)]
rain = low.groupby("baseDate")["rain"].median()
rain.index = pd.to_datetime(rain.index)
wet = rain >= 1.0
S["weather"] = {"days": int(len(wet)), "wet_days": int(wet.sum()), "wet_pct": round(wet.mean() * 100, 1), "stations_low": int(low["observatoryName"].nunique())}

bw = pd.concat([bus_dong(2023)[lambda x: x["base_date"] >= "20230401"], b24, bus_dong(2025)[lambda x: x["base_date"] <= "20250330"]])
bw = bw.dropna(subset=["dong"]).groupby(["dong", "base_date"])["user_count"].sum().reset_index()
bw["date"] = pd.to_datetime(bw["base_date"]); bw["bus"] = bw["user_count"]
vis = daily.rename(columns={"emd": "dong"})
heavy = rain[(rain >= 10) | (rain < 1)] >= 10  # 민감도: 10mm 이상 ↔ 1mm 미만(그 사이 날은 제외)
E = pd.concat([effect(bw, "bus", "버스", wet), effect(vis, "visitPop", "방문", wet), effect(bw, "bus", "버스10mm", heavy), effect(vis, "visitPop", "방문10mm", heavy)], axis=1)
E.to_csv(OUT / "weather_effect.csv", encoding="utf-8-sig")
S["weather"]["heavy_days"] = int(heavy.sum())
for c in ["버스", "방문", "버스10mm", "방문10mm"]:
    x = E[f"{c}_비"].dropna()
    S["weather"][c] = {"min": round(x.min(), 3), "median": round(x.median(), 3), "max": round(x.max(), 3),
                       "n": int(len(x)), "ci_excl_1": int(((E[f"{c}_하한"] > 1) | (E[f"{c}_상한"] < 1)).sum()),
                       "low2": x.nsmallest(2).round(3).to_dict(), "high2": x.nlargest(2).round(3).to_dict()}
S["weather"]["vis_days"] = int(vis["date"][vis["date"].isin(wet.index)].nunique())

M.round(4).to_csv(OUT / "dong_metrics.csv", encoding="utf-8-sig")
(OUT / "summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps(S, ensure_ascii=False, default=str))
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20); pd.set_option("display.max_colwidth", 30)
print(dist.round(3).to_string(index=False))
