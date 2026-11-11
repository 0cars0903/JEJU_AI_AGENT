"""동네 표준 테이블을 만든다. 에이전트 도구는 data/tables/만 읽으며, 이 폴더를 앱에 동봉한다.

입력: data/interim/ (build_tables.py 결과, api 수집 파일)
확정 사항(docs/조사/06_EDA_H1H3.md, 사용자 2026-11-06):
  동네 지표 2024년 · 추이 2023-11 ~ 2025-10 · 날씨 2023-11 ~ 2025-03
  폐업·생존: 값 + 95% 구간 + 표본 수, BH q=0.10 뒤에도 차이가 남는 동네만 높음/낮음
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stats import bh, effect, km_at, loglog_ci, two_sided_p, wilson

ROOT = Path(__file__).resolve().parents[1]
IN, OUT = ROOT / "data" / "interim", ROOT / "data" / "tables"
Q = 0.10
TREND_START, TREND_END = "2023-11", None  # v3: 끝은 583의 마지막 완전한 달(자료를 받는 대로 따라감)
WX_START, WX_END = pd.Timestamp("2023-11-01"), pd.Timestamp("2025-03-31")
CLOSE_YEARS = None  # v3: 관측 끝 직전 완전한 3년(예: 관측 2026-11 → 2023~2025)
KM_START, KM_END = "2015-01-01", None  # v3: 5년 추적이 가능한 개업 코호트 = 관측 끝 − 5년
MOUNTAIN = {"어리목", "삼각봉", "사제비", "영실", "윗세오름", "한라산남벽", "진달래밭", "성판악", "한라생태숲"}


def load_api(data_id):
    fs = sorted((IN / "api" / str(data_id)).glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True), [f.stem for f in fs]


def label(dong, sig, value, base):
    if dong not in sig:
        return "차이 확인 안 됨"
    return "제주 평균보다 높음" if value > base else "제주 평균보다 낮음"


def build_biz(stores):
    g = stores.groupby(["행정동명", "상권업종대분류명", "상권업종중분류명", "상권업종소분류명"]).size().rename("count").reset_index()
    g.columns = ["dong", "major", "middle", "minor", "count"]
    g.to_parquet(OUT / "biz.parquet", index=False)


def build_restaurants(rest, dongs):
    end0 = rest[["open_date", "close_date"]].max().max()
    close_years = CLOSE_YEARS or [end0.year - 3, end0.year - 2, end0.year - 1]
    km_end = KM_END or str((end0 - pd.DateOffset(years=5)).date())
    r = rest[rest["admin_dong"].isin(dongs)]
    o = r.dropna(subset=["open_date"]).assign(year=lambda x: x["open_date"].dt.year, kind="open")
    c = r.dropna(subset=["close_date"]).assign(year=lambda x: x["close_date"].dt.year, kind="close")
    ev = pd.concat([o, c]).groupby(["admin_dong", "업종구분소분류", "year", "kind"]).size().rename("count").reset_index()
    ev.columns = ["dong", "category", "year", "kind", "count"]
    ev.to_parquet(OUT / "rest_events.parquet", index=False)
    # 3년 묶음 폐업률
    k, n = pd.Series(0.0, index=dongs), pd.Series(0.0, index=dongs)
    for y in close_years:
        s, e = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
        alive = r[(r["open_date"] < s) & (r["close_date"].isna() | (r["close_date"] >= s))]
        n += alive.groupby("admin_dong").size().reindex(dongs).fillna(0)
        k += alive[alive["close_date"].between(s, e)].groupby("admin_dong").size().reindex(dongs).fillna(0)
    base = k.sum() / n.sum()
    rate = k / n
    p = pd.Series({d: two_sided_p((rate[d] - base) / np.sqrt(base * (1 - base) / n[d])) for d in dongs})
    sig = set(bh(p, Q))
    rows = []
    for d in dongs:
        lo, hi = wilson(k[d], n[d])
        rows.append((d, int(k[d]), int(n[d]), rate[d] * 100, lo * 100, hi * 100, label(d, sig, rate[d], base)))
    close = pd.DataFrame(rows, columns=["dong", "closed", "store_years", "rate_pct", "lo_pct", "hi_pct", "label"])
    close.to_parquet(OUT / "close_3y.parquet", index=False)
    # 영업 지속 곡선
    end = rest[["open_date", "close_date"]].max().max()
    co = r[(r["open_date"] >= KM_START) & (r["open_date"] <= km_end)].copy()
    co["event"] = co["close_date"].notna()
    co["y"] = ((co["close_date"].fillna(end) - co["open_date"]).dt.days / 365.25).clip(lower=0)
    du, ev_ = co["y"].to_numpy(), co["event"].to_numpy()
    jeju5 = km_at(du, ev_, 5)[0]
    cells, p5 = [], {}
    for d in dongs + ["제주 전체"]:
        g = co if d == "제주 전체" else co[co["admin_dong"] == d]
        for t in range(1, 6):
            s, se, m = km_at(g["y"].to_numpy(), g["event"].to_numpy(), t)
            lo, hi = loglog_ci(s, se)
            cells.append((d, t, s * 100, lo * 100, hi * 100, m))
            if t == 5 and d != "제주 전체":
                p5[d] = two_sided_p((s - jeju5) / se) if se > 0 else np.nan
    km = pd.DataFrame(cells, columns=["dong", "year", "survival_pct", "lo_pct", "hi_pct", "n"])
    sig5 = set(bh(pd.Series(p5), Q))
    five = km[km["year"] == 5].set_index("dong")["survival_pct"]
    km["label"] = [label(d, sig5, five[d], jeju5 * 100) if d != "제주 전체" else "" for d in km["dong"]]
    km.to_parquet(OUT / "km.parquet", index=False)
    return {"close_base_pct": round(base * 100, 2), "km5_jeju_pct": round(jeju5 * 100, 1), "km_cohort_n": int(len(co)),
            "close_sig": sorted(sig), "km_sig": sorted(sig5), "rest_last": str(end.date()),
            "close_years": f"{close_years[0]}~{close_years[-1]}", "km_cohort": f"{KM_START[:7]}~{km_end[:7]}"}


def build_pop(pop):
    pop["date"] = pd.to_datetime(pop["baseDate"])
    pop["ym"] = pop["date"].dt.strftime("%Y-%m")
    for c in ["resdPop", "workPop", "visitPop"]:
        pop[c] = pd.to_numeric(pop[c], errors="coerce")
    full = pop.groupby("ym")["date"].nunique()
    full = full[[d == pd.Period(m).days_in_month for m, d in full.items()]]
    trend_end = TREND_END or full.index.max()  # 날짜가 다 있는 마지막 달
    t = pop[pop["ym"].between(TREND_START, trend_end)]
    m = t.groupby(["emd", "ym"]).agg(resd=("resdPop", "sum"), work=("workPop", "sum"), visit=("visitPop", "sum"), days=("date", "nunique")).reset_index()
    m = m.rename(columns={"emd": "dong"})
    m.to_parquet(OUT / "pop_month.parquet", index=False)
    a = pop.assign(year=pop["date"].dt.year).groupby(["emd", "year", "gender", "ageGroup"]).agg(resd=("resdPop", "sum"), visit=("visitPop", "sum"), work=("workPop", "sum")).reset_index()
    a = a.rename(columns={"emd": "dong"})
    a.to_parquet(OUT / "pop_age.parquet", index=False)
    by_year = pop.groupby(pop["date"].dt.year)["date"].nunique()
    return {"pop_trend_end": trend_end, "pop_days": int(pop["date"].nunique()), "pop_days_by_year": {str(k): int(v) for k, v in by_year.items()}, "pop_first": str(pop["date"].min().date()), "pop_last": str(pop["date"].max().date())}


BUS_FILES = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]


def build_bus(sd):
    fr, days = [], {}
    for y in BUS_FILES:
        raw = pd.read_parquet(IN / "bus_daily" / f"{y}.parquet")
        x = raw["base_date"].drop_duplicates()
        days.update((x.str[:4] + "-" + x.str[4:6]).value_counts().to_dict())  # 달별 실제 자료 일수(2022년 빠진 날 반영)
        b = raw.merge(sd[["station_name", "dong", "weight"]], on="station_name")
        b = b[b["dong"].notna()]
        b["n"] = b["user_count"] * b["weight"]
        b["ym"] = b["base_date"].str[:4] + "-" + b["base_date"].str[4:6]
        fr.append(b.groupby(["dong", "ym", "user_type"])["n"].sum().reset_index())
    m = pd.concat(fr, ignore_index=True)
    m["days"] = m["ym"].map(days)
    m.to_parquet(OUT / "bus_month.parquet", index=False)
    return {"bus_last": "2025-10-25"}


def build_weather(wx, sd, pop):
    wx = wx.drop_duplicates()
    wx["rain"] = pd.to_numeric(wx["dailyRainfall"], errors="coerce")
    rain = wx[~wx["observatoryName"].isin(MOUNTAIN)].groupby("baseDate")["rain"].median()
    rain.index = pd.to_datetime(rain.index)
    rain = rain[(rain.index >= WX_START) & (rain.index <= WX_END)]
    wet = rain >= 1.0
    fr = []
    for y in ["2023", "2024", "2025"]:
        b = pd.read_parquet(IN / "bus_daily" / f"{y}.parquet").merge(sd[["station_name", "dong", "weight"]], on="station_name")
        b = b[b["dong"].notna()]
        b["bus"] = b["user_count"] * b["weight"]
        fr.append(b.groupby(["dong", "base_date"])["bus"].sum().reset_index())
    bus = pd.concat(fr)
    bus["date"] = pd.to_datetime(bus["base_date"])
    vis = pop.groupby(["emd", "date"])["visitPop"].sum().reset_index().rename(columns={"emd": "dong"})
    e = pd.concat([effect(bus, "bus", "bus", wet), effect(vis, "visitPop", "visit", wet)], axis=1).rename_axis("dong").reset_index()
    for c in e.columns[1:]:
        e[c] = (e[c] - 1) * 100  # 무강수일 대비 변화(%)
    e.to_parquet(OUT / "weather.parquet", index=False)
    return {"wx_days": int(len(wet)), "wx_wet_days": int(wet.sum()), "wx_start": str(WX_START.date()), "wx_end": str(rain.index.max().date()),
            "wx_visit_days": int(vis["date"][vis["date"].isin(wet.index)].nunique())}


def build_places(stores):
    """법정동·리 → 행정동. 비중 1% 미만 후보는 주소 오류로 보고 뺀다(이도이동: 이도2동 3,625곳, 아라동 3곳)."""
    def cands(g):
        v = g.value_counts()
        return sorted(v[v / v.sum() >= 0.01].index)
    legal = stores.groupby("법정동명")["행정동명"].apply(cands).to_dict()
    # 읍면의 리 이름 → 행정동: 지번주소 '제주특별자치도 제주시 애월읍 고내리 123'의 넷째 토큰
    ri = stores["지번주소"].fillna("").str.split().str[3]
    x = stores[ri.fillna("").str.endswith("리")].assign(ri=ri)
    for name, g in x.groupby("ri")["행정동명"]:
        legal.setdefault(name, cands(g))
    (OUT / "places.json").write_text(json.dumps(legal, ensure_ascii=False, indent=0), encoding="utf-8")


def build_map(stores):
    """지도 자료: 동네 대표 좌표(점포 좌표 중앙값)와 제주 윤곽용 격자(점포가 있는 칸). 지도 타일 없이 그린다."""
    pts = stores.groupby("행정동명")[["경도", "위도"]].median().rename_axis("dong").reset_index()
    pts.columns = ["dong", "lon", "lat"]
    pts.to_parquet(OUT / "map_dong.parquet", index=False)
    g = stores.assign(lon=(stores["경도"] / 0.008).round() * 0.008, lat=(stores["위도"] / 0.008).round() * 0.008)
    g.groupby(["lon", "lat"]).size().rename("n").reset_index().to_parquet(OUT / "map_grid.parquet", index=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stores = pd.read_parquet(IN / "stores.parquet")
    rest = pd.read_parquet(IN / "restaurants.parquet")
    sd = pd.read_parquet(IN / "station_dong.parquet")
    pop, _ = load_api(583)
    wx, _ = load_api(579)
    dongs = sorted(stores["행정동명"].unique())
    meta = {}
    build_biz(stores)
    meta.update(build_restaurants(rest, dongs))
    meta.update(build_pop(pop))
    meta.update(build_bus(sd))
    meta.update(build_weather(wx, sd, pop))
    build_places(stores)
    build_map(stores)
    one = sd.drop_duplicates("station_name")
    meta["bus_mapped_pct_2024"] = round(one.loc[one["dong"].notna(), "users_2024"].sum() / one["users_2024"].sum() * 100, 2)
    meta["dongs"] = dongs
    old = json.loads((OUT / "meta.json").read_text(encoding="utf-8")) if (OUT / "meta.json").exists() else {}
    meta = {**{k: v for k, v in old.items() if k.startswith("card")}, **meta}  # v3 카드 키(build_v3_tables.py)는 남긴다
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: v for k, v in meta.items() if k != "dongs"})


if __name__ == "__main__":
    main()
