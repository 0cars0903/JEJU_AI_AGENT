"""모델 착수 관문(G1 자료 충분성, G2 신호 존재, G3 단순 모델 상한) 사전 점검 — 2026-11-11 사용자 승인.

모델링 전에 30분 안팎의 계산으로 진행 / 축소 / 서술 전환을 정한다(docs/기획/05_Agent구조_v2.md 12절).
CPU만 쓴다(GPU는 GA_KSL 학습이 사용 중). 결과: data/interim/gates/gates.json, 표는 docs/조사/07_모델관문.md.

실행: .venv/bin/python app/model_gates.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from build_dong_tables import IN, MOUNTAIN, KM_START, KM_END, load_api  # noqa: E402
from stats import km_at  # noqa: E402
from places import REST_MAP  # noqa: E402

TAB = ROOT / "data" / "tables"
OUTD = IN / "gates"
WX_START, WX_END = pd.Timestamp("2023-11-04"), pd.Timestamp("2025-03-30")
SEED = 0


def mase(y, p, naive):
    return float(np.mean(np.abs(y - p)) / np.mean(np.abs(y - naive)))


def gate_m1():
    """M1 날씨 → 동네 일 방문: 날씨 제외(M0) vs 날씨 포함(M1), 릿지·부스팅. 시간 순 80/20 분할."""
    pop, _ = load_api(583)
    pop["date"] = pd.to_datetime(pop["baseDate"].astype(str))
    v = pop.groupby(["date", "emd"])["visitPop"].sum().rename("visit").reset_index()
    wx, _ = load_api(579)
    wx = wx[~wx["observatoryName"].isin(MOUNTAIN)].copy()
    wx["date"] = pd.to_datetime(wx["baseDate"].astype(str))
    for c in ["dailyRainfall", "averageTemperature", "maximumWindSpeed"]:
        wx[c] = pd.to_numeric(wx[c], errors="coerce")
    w = wx.groupby("date")[["dailyRainfall", "averageTemperature", "maximumWindSpeed"]].median().fillna({"dailyRainfall": 0})
    d = v.merge(w, left_on="date", right_index=True)
    d = d[(d["date"] >= WX_START) & (d["date"] <= WX_END)].sort_values(["emd", "date"])
    d["y"] = np.log(d["visit"])
    d["naive"] = d.groupby("emd")["y"].shift(7)  # 기준선: 지난주 같은 요일
    d = d.dropna(subset=["naive", "averageTemperature", "maximumWindSpeed"])
    d["rain"] = np.log1p(d["dailyRainfall"])
    d["heavy"] = (d["dailyRainfall"] >= 30).astype(int)
    d["windy"] = (d["maximumWindSpeed"] >= 14).astype(int)
    d["island"] = np.log(d.groupby("date")["visit"].transform("sum"))
    cal = pd.get_dummies(d[["emd"]].assign(dow=d["date"].dt.dayofweek.astype(str), mon=d["date"].dt.month.astype(str)), dtype=float)
    wcols = d[["rain", "heavy", "windy", "averageTemperature"]].astype(float)
    days = np.sort(d["date"].unique())
    cut = days[int(len(days) * 0.8)]
    tr, te = (d["date"] < cut).to_numpy(), (d["date"] >= cut).to_numpy()
    y, naive = d["y"].to_numpy(), d["naive"].to_numpy()
    res = {"days": int(len(days)), "dongs": int(d["emd"].nunique()), "test_from": str(pd.Timestamp(cut).date()),
           "heavy_days": int(d.drop_duplicates("date")["heavy"].sum()), "windy_days": int(d.drop_duplicates("date")["windy"].sum())}
    feats = {"M0_calendar": cal, "M1_calendar+weather": pd.concat([cal, wcols], axis=1)}
    for name, X in feats.items():
        X = X.to_numpy()
        p = Ridge(alpha=1.0).fit(X[tr], y[tr]).predict(X[te])
        res[f"ridge_{name}_MASE"] = round(mase(y[te], p, naive[te]), 3)
    Xg = pd.concat([d[["averageTemperature", "rain", "heavy", "windy"]], d["date"].dt.dayofweek.rename("dow"), d["date"].dt.month.rename("mon"),
                    d["emd"].astype("category").cat.codes.rename("dong")], axis=1).to_numpy(float)
    for name, cols in {"M0_calendar": [4, 5, 6], "M1_calendar+weather": [0, 1, 2, 3, 4, 5, 6]}.items():
        m = HistGradientBoostingRegressor(random_state=SEED, categorical_features=[cols.index(6)]).fit(Xg[tr][:, cols], y[tr])
        res[f"gbm_{name}_MASE"] = round(mase(y[te], m.predict(Xg[te][:, cols]), naive[te]), 3)
    # 날씨 기여: 동네별로 M1 릿지가 M0 릿지보다 오차가 작은 비율
    X0, X1 = feats["M0_calendar"].to_numpy(), feats["M1_calendar+weather"].to_numpy()
    p0 = Ridge(alpha=1.0).fit(X0[tr], y[tr]).predict(X0[te])
    p1 = Ridge(alpha=1.0).fit(X1[tr], y[tr]).predict(X1[te])
    e = pd.DataFrame({"emd": d["emd"].to_numpy()[te], "e0": np.abs(y[te] - p0), "e1": np.abs(y[te] - p1)}).groupby("emd").mean()
    res["dongs_M1_better"] = int((e["e1"] < e["e0"]).sum())
    res["median_err_reduction_pct"] = round(float(((e["e0"] - e["e1"]) / e["e0"]).median() * 100), 2)
    # 섬 전체 총량을 통제한 날씨 계수(동네 간 재배치 신호)
    Xc = pd.concat([cal, wcols, d[["island"]]], axis=1).to_numpy()
    res["rain_coef_with_island_control"] = round(float(Ridge(alpha=1.0).fit(Xc, y).coef_[-5]), 4)
    return res


def gate_m2():
    """M2 계절 유형: 동네별 월 방문 곡선(평균으로 정규화) 군집. 실루엣과 두 해 사이 안정성(ARI)."""
    pm = pd.read_parquet(TAB / "pop_month.parquet")
    pm["v"] = pm["visit"] / pm["days"]
    pm["ym"] = pd.to_datetime(pm["ym"])
    pm["mon"] = pm["ym"].dt.month
    pm["half"] = np.where(pm["ym"] < pd.Timestamp("2024-11-01"), "y1", "y2")

    def curve(g):
        c = g.pivot_table(index="dong", columns="mon", values="v", aggfunc="mean")
        return c.div(c.mean(axis=1), axis=0).dropna(axis=1)

    all_c = curve(pm)
    out = {"months": int(pm["ym"].nunique())}
    for k in range(2, 6):
        lab = KMeans(k, n_init=20, random_state=SEED).fit_predict(all_c)
        a = curve(pm[pm["half"] == "y1"]).reindex(all_c.index)
        b = curve(pm[pm["half"] == "y2"]).reindex(all_c.index)
        cols = a.columns.intersection(b.columns)
        la = KMeans(k, n_init=20, random_state=SEED).fit_predict(a[cols])
        lb = KMeans(k, n_init=20, random_state=SEED).fit_predict(b[cols])
        out[f"k{k}"] = {"silhouette": round(float(silhouette_score(all_c, lab)), 3), "ARI_year1_vs_year2": round(float(adjusted_rand_score(la, lb)), 3),
                        "sizes": sorted(np.bincount(lab).tolist(), reverse=True)}
    return out


def m4_features(year_pop=None, year_bus=None):
    biz = pd.read_parquet(TAB / "biz.parquet").pivot_table(index="dong", columns="major", values="count", aggfunc="sum").fillna(0)
    biz = biz.div(biz.sum(axis=1), axis=0).add_prefix("biz_")
    pa = pd.read_parquet(TAB / "pop_age.parquet")
    if year_pop:
        pa = pa[pa["year"] == year_pop]
    age = pa.pivot_table(index="dong", columns="ageGroup", values="resd", aggfunc="sum")
    age = age.div(age.sum(axis=1), axis=0).add_prefix("age_")
    pm = pd.read_parquet(TAB / "pop_month.parquet")
    if year_pop:
        pm = pm[pm["ym"].astype(str).str[:4] == str(year_pop)]
    r = pm.groupby("dong")[["visit", "work", "resd"]].sum()
    ratio = pd.DataFrame({"visit_resd": np.log(r["visit"] / r["resd"]), "work_resd": np.log(r["work"] / r["resd"])})
    bm = pd.read_parquet(TAB / "bus_month.parquet")
    if year_bus:
        bm = bm[bm["ym"].astype(str).str[:4] == str(year_bus)]
    b = bm.groupby("dong").agg(n=("n", "sum"))
    days = bm.drop_duplicates(["dong", "ym"]).groupby("dong")["days"].sum()
    bus = np.log(b["n"] / days).rename("bus_per_day").to_frame()
    return pd.concat([biz, age, ratio, bus], axis=1).dropna()


def neighbors(F, k=5):
    Z = StandardScaler().fit_transform(F)
    D = np.linalg.norm(Z[:, None] - Z[None], axis=2)
    np.fill_diagonal(D, np.inf)
    return {d: set(F.index[np.argsort(D[i])[:k]]) for i, d in enumerate(F.index)}


def gate_m4():
    """M4 동네 유사도: 해마다 다시 계산해도 이웃 5곳이 유지되나(2024 vs 2025 인구·버스)."""
    F = m4_features()
    a, b = m4_features(2024, 2024), m4_features(2025, 2025)
    idx = a.index.intersection(b.index)
    na, nb = neighbors(a.loc[idx]), neighbors(b.loc[idx])
    jac = [len(na[d] & nb[d]) / len(na[d] | nb[d]) for d in idx]
    # 특성 묶음 하나씩 빼기
    groups = {"biz": [c for c in F if c.startswith("biz_")], "age": [c for c in F if c.startswith("age_")], "ratio": ["visit_resd", "work_resd"], "bus": ["bus_per_day"]}
    base = neighbors(F)
    drop = {}
    for g, cols in groups.items():
        nn = neighbors(F.drop(columns=cols))
        drop[g] = round(float(np.mean([len(base[d] & nn[d]) / 5 for d in F.index])), 3)
    # 무작위 기준: 이웃 5곳이 우연히 겹칠 기대 비율
    rnd = 5 / (len(F) - 1)
    return {"dongs": int(len(F)), "features": int(F.shape[1]), "jaccard_2024_vs_2025_median": round(float(np.median(jac)), 3),
            "overlap_share_2024_vs_2025_mean": round(float(np.mean([len(na[d] & nb[d]) / 5 for d in idx])), 3),
            "random_overlap_expected": round(rnd, 3), "overlap_after_dropping_group": drop}


def gate_m5():
    """M5 급변 탐지: 단위별 표본(G1)과, 포아송 기대보다 큰 변동이 다음 해에도 이어지나(G2)."""
    ev = pd.read_parquet(TAB / "rest_events.parquet")
    inv = {}
    for g, cats in REST_MAP.items():
        if cats:
            for c in cats:
                inv.setdefault(c, g)
    ev["group"] = ev["category"].map(inv).fillna("기타")
    out = {}
    for unit, keys in {"동네x세부업종": ["dong", "category"], "동네x업종묶음": ["dong", "group"], "동네": ["dong"]}.items():
        for kind in ["open", "close"]:
            e = ev[ev["kind"] == kind].groupby(keys + ["year"])["count"].sum().unstack("year").fillna(0)
            yrs = [y for y in range(2016, 2025) if y in e.columns]
            c24 = e[2024]
            # z: 직전 3년 평균 대비 포아송 표준화 잔차
            zs = {}
            for y in yrs[3:]:
                mu = e[[y - 1, y - 2, y - 3]].mean(axis=1)
                zs[y] = ((e[y] - mu) / np.sqrt(mu.clip(lower=0.5)))
            z = pd.DataFrame(zs)
            flag = (z.abs() > 2)
            # 지속성: y년 경보 셀이 y+1년에도 같은 방향 경보인 비율 vs 전체 경보 비율
            pers, base = [], []
            for y in list(z.columns)[:-1]:
                f = flag[y] & (np.sign(z[y]) == np.sign(z[y + 1])) & flag[y + 1]
                pers.append(f.sum() / max(flag[y].sum(), 1))
                base.append(flag[y + 1].mean())
            out[f"{unit}_{kind}"] = {"cells": int(len(e)), "median_2024": float(c24.median()), "cells_ge10_2024": int((c24 >= 10).sum()),
                                     "flag_rate": round(float(flag.values.mean()), 3), "persist_rate": round(float(np.mean(pers)), 3),
                                     "base_rate": round(float(np.mean(base)), 3)}
    return out


def gate_m6():
    """M6 업종별 생존: 5년 추적 가능 코호트에서 업종 묶음별 표본과 5년 생존율 구간 폭."""
    rest = pd.read_parquet(IN / "restaurants.parquet")
    inv = {c: g for g, cats in REST_MAP.items() if cats for c in cats}
    rest["group"] = rest["업종구분소분류"].map(inv).fillna("기타")
    end = rest[["open_date", "close_date"]].max().max()
    co = rest[(rest["open_date"] >= KM_START) & (rest["open_date"] <= KM_END)].copy()
    co["event"] = co["close_date"].notna()
    co["y"] = ((co["close_date"].fillna(end) - co["open_date"]).dt.days / 365.25).clip(lower=0)
    out = {}
    for g, x in co.groupby("group"):
        s5, se5, _ = km_at(x["y"].to_numpy(), x["event"].to_numpy(), 5)
        s2, _, _ = km_at(x["y"].to_numpy(), x["event"].to_numpy(), 2)
        out[g] = {"n": int(len(x)), "surv5_pct": round(s5 * 100, 1), "ci95_halfwidth_pp": round(1.96 * se5 * 100, 1),
                  "cond_2to5_pct": round(s5 / s2 * 100, 1) if s2 > 0 else None}
    return out


def gate_bus():
    """버스 수준 예상: 3개월 뒤 동네 월 일평균(로그), 릿지 + split conformal 80% 구간 포함률."""
    bm = pd.read_parquet(TAB / "bus_month.parquet")
    s = bm.groupby(["dong", "ym"]).agg(n=("n", "sum"), days=("days", "first")).reset_index()
    s["ym"] = pd.to_datetime(s["ym"])
    s = s[s["ym"] >= "2022-01-01"].sort_values(["dong", "ym"])
    s["y"] = np.log(s["n"] / s["days"])
    g = s.groupby("dong")["y"]
    for L in [3, 4, 5, 12, 15]:
        s[f"l{L}"] = g.shift(L)
    s["target"] = s["y"]
    s = s.dropna()
    X = s[["l3", "l4", "l5", "l12", "l15"]].to_numpy()
    X = np.column_stack([X, pd.get_dummies(s["ym"].dt.month, dtype=float).to_numpy()])
    t = s["ym"]
    tr, ca, te = t < "2024-01-01", (t >= "2024-01-01") & (t < "2024-07-01"), t >= "2024-07-01"
    m = Ridge(alpha=1.0).fit(X[tr.to_numpy()], s["target"][tr])
    q = np.quantile(np.abs(s["target"][ca] - m.predict(X[ca.to_numpy()])), 0.8)
    p = m.predict(X[te.to_numpy()])
    yt = s["target"][te].to_numpy()
    snaive = s["l12"][te].to_numpy()
    return {"test_months": f"{t[te].min().date()}~{t[te].max().date()}", "n_test": int(te.sum()),
            "coverage80": round(float(np.mean(np.abs(yt - p) <= q)), 3), "halfwidth_pct": round(float((np.exp(q) - 1) * 100), 1),
            "median_abs_err_pct": round(float(np.median(np.abs(np.exp(yt - p) - 1)) * 100), 1),
            "seasonal_naive_median_abs_err_pct": round(float(np.median(np.abs(np.exp(yt - snaive) - 1)) * 100), 1)}


def main():
    OUTD.mkdir(parents=True, exist_ok=True)
    res = {}
    for name, fn in [("M1", gate_m1), ("M2", gate_m2), ("M4", gate_m4), ("M5", gate_m5), ("M6", gate_m6), ("bus", gate_bus)]:
        try:
            res[name] = fn()
        except Exception as e:  # 한 관문이 실패해도 나머지는 계산한다
            res[name] = {"error": f"{type(e).__name__}: {e}"}
        print(name, json.dumps(res[name], ensure_ascii=False))
    (OUTD / "gates.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
