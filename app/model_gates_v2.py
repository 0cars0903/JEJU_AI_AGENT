"""모델 착수 관문 v2 (2026-11-11 사용자 승인). 관문 v1(app/model_gates.py)이 너무 단순하다는 지적을 반영한다.

M1 방문 예측 v2
- 과제: 7일 뒤 동네 방문 지수(로그) 예측. 7일 뒤를 고른 이유: 주간 인력·발주 계획 단위이고, 7일 전 값(기준선)을 입력으로 쓸 수 있다.
- 입력: 7·14일 전 값, 요일, 월, 평일 공휴일, 연휴, 명절, 방학[가정], 기온(1·2차), 강풍, 비 강도 3단계, 동네 고정효과.
  날씨는 그날 실제 관측값을 넣는다(완전 예보 가정, 상한 추정). 실제 서비스는 예보 오차가 더해진다.
- 비교: M0(날씨 제외) vs M1(날씨 포함) vs M1d(날씨 + 동네별 비 계수). 릿지, 부스팅. LSTM은 app/lstm_gate.py(별도 가상환경, CPU).
- 검증: 이동 원점 5회(시험 시작 2025-01-01, 04-01, 07-01, 10-01, 2026-01-01, 각 60일, 그 전 전부로 학습). 계절 4개를 모두 지난다.
- 판정: 기준선(7일 전 값) 대비 MASE, M0 대비 짝 비교(동네 × 회차 오차의 부호 검정), 개선 동네 수. 비 효과가 큰 8곳(08 문서)은 따로 본다.
버스 예상 v2
- 3개월 뒤 동네 월 일평균(로그). 이동 원점 6회(2024-07 ~ 2025-07, 2개월 간격).
- 비교: 계절 단순(12개월 전) vs 릿지(시차) vs 릿지(시차 + 그 달 공휴일·연휴·비 온 날 수).
결과: data/interim/gates/gates_v2.json, 패널 data/interim/gates/panel_v2.parquet(LSTM 입력)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from build_dong_tables import IN  # noqa: E402
from rain_test import calendar, daily_visit, daily_weather  # noqa: E402

OUTD = IN / "gates"
FOLDS = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"]
TEST_DAYS = 60
H = 7
BIG8 = ["우도면", "추자면", "남원읍", "봉개동", "대정읍", "한경면", "영천동", "구좌읍"]
CAL = ["holiday", "long_break", "myeongjeol", "vacation"]
WX = ["temp", "temp2", "windy", "r1", "r2", "r3"]


def panel():
    v, _, _ = daily_visit()
    w = daily_weather()
    d = v.merge(w, left_on="date", right_index=True).dropna(subset=["temp", "wind"])
    d = d.join(calendar(d["date"].unique()), on="date").sort_values(["emd", "date"]).reset_index(drop=True)
    d["y"] = np.log(d["visit"])
    g = d.groupby("emd")["y"]
    d["lag7"], d["lag14"] = g.shift(7), g.shift(14)
    d["temp"] = d["temp"] - d["temp"].mean()
    d["temp2"] = d["temp"] ** 2
    d["windy"] = (d["wind"] >= 14).astype(float)
    d["r1"] = d["rain"].between(1, 10, inclusive="left").astype(float)
    d["r2"] = d["rain"].between(10, 30, inclusive="left").astype(float)
    d["r3"] = (d["rain"] >= 30).astype(float)
    d["wet"] = (d["rain"] >= 1).astype(float)
    d["dow"] = d["date"].dt.dayofweek
    d["mon"] = d["date"].dt.month
    return d.dropna(subset=["lag7", "lag14"]).reset_index(drop=True)


def X_ridge(d, kind):
    X = pd.get_dummies(d[["emd"]].assign(dow=d["dow"].astype(str), mon=d["mon"].astype(str)), dtype=float)
    X = X.join(d[["lag7", "lag14", *CAL]].astype(float))
    if kind in ("M1", "M1d"):
        X = X.join(d[WX])
    if kind == "M1d":  # 동네별 비 계수
        for e in d["emd"].unique():
            X[f"wet_{e}"] = d["wet"] * (d["emd"] == e)
    return X


def X_gbm(d, kind):
    cols = ["lag7", "lag14", "dow", "mon", *CAL] + (WX if kind != "M0" else [])
    X = d[cols].astype(float).copy()
    X["dong"] = d["emd"].astype("category").cat.codes
    return X, [X.columns.get_loc("dong")]


def fold_masks(d, start):
    s = pd.Timestamp(start)
    tr = (d["date"] < s - pd.Timedelta(days=H)).to_numpy()  # 시험 시작 7일 전까지만 학습(정보 누수 방지)
    te = ((d["date"] >= s) & (d["date"] < s + pd.Timedelta(days=TEST_DAYS))).to_numpy()
    return tr, te


def run_m1(d):
    y = d["y"].to_numpy()
    preds = {}
    for name in ["ridge_M0", "ridge_M1", "ridge_M1d", "gbm_M0", "gbm_M1"]:
        algo, kind = name.split("_")
        p = np.full(len(d), np.nan)
        if algo == "ridge":
            X = X_ridge(d, kind).to_numpy()
        else:
            X, cat = X_gbm(d, kind)
            X = X.to_numpy()
        for f in FOLDS:
            tr, te = fold_masks(d, f)
            if algo == "ridge":
                m = Ridge(alpha=1.0).fit(X[tr], y[tr])
            else:
                m = HistGradientBoostingRegressor(random_state=0, categorical_features=cat, max_iter=300).fit(X[tr], y[tr])
            p[te] = m.predict(X[te])
        preds[name] = p
    # 하이브리드: 달력 부스팅(M0) + 같은 회차 학습분으로 추정한 동네별 비 계수(릿지 M1d의 wet_동네 계수)
    Xr = X_ridge(d, "M1d")
    wet_cols = [c for c in Xr.columns if c.startswith("wet_")]
    hyb = np.full(len(d), np.nan)
    for f in FOLDS:
        tr, te = fold_masks(d, f)
        m = Ridge(alpha=1.0).fit(Xr.to_numpy()[tr], y[tr])
        coef = dict(zip(Xr.columns, m.coef_))
        adj = np.array([coef.get(f"wet_{e}", 0.0) for e in d["emd"]]) * d["wet"].to_numpy()
        hyb[te] = preds["gbm_M0"][te] + adj[te]
    preds["hybrid_gbmM0+dongrain"] = hyb
    # 08 문서에서 동등성(±10%)을 보이지 못한 8곳에만 비 보정을 적용
    preds["hybrid_big8only"] = np.where(d["emd"].isin(BIG8), hyb, preds["gbm_M0"])
    d = d.copy()
    for k, v in preds.items():
        d[k] = v
    d["fold"] = None
    for f in FOLDS:
        _, te = fold_masks(d, f)
        d.loc[te, "fold"] = f
    t = d.dropna(subset=["fold"])
    t["naive"] = t["lag7"]
    out = {"rows_test": int(len(t))}
    base = np.abs(t["y"] - t["naive"])
    for k in preds:
        e = np.abs(t["y"] - t[k])
        out[f"{k}_MASE"] = round(float(e.mean() / base.mean()), 4)
        out[f"{k}_MASE_by_fold"] = {f: round(float(e[t["fold"] == f].mean() / base[t["fold"] == f].mean()), 4) for f in FOLDS}
        b8 = t["emd"].isin(BIG8)
        out[f"{k}_MASE_big8"] = round(float(e[b8].mean() / base[b8].mean()), 4)
    # 짝 비교: 동네 × 회차 평균 오차, M1 vs M0
    for a, b in [("ridge_M1", "ridge_M0"), ("ridge_M1d", "ridge_M0"), ("gbm_M1", "gbm_M0"), ("hybrid_gbmM0+dongrain", "gbm_M0"), ("hybrid_big8only", "gbm_M0")]:
        g = t.assign(ea=np.abs(t["y"] - t[a]), eb=np.abs(t["y"] - t[b])).groupby(["emd", "fold"])[["ea", "eb"]].mean()
        wins = int((g["ea"] < g["eb"]).sum())
        n = len(g)
        pg = g.groupby(level=0).mean()
        out[f"{a}_vs_{b}"] = {"cells_better": f"{wins}/{n}", "sign_test_p": float(stats.binomtest(wins, n, 0.5).pvalue),
                               "dongs_better": int((pg["ea"] < pg["eb"]).sum()), "mean_err_change_pct": round(float((g["ea"].mean() - g["eb"].mean()) / g["eb"].mean() * 100), 3)}
        # 비 온 날만
        w = t[t["wet"] == 1]
        out[f"{a}_vs_{b}"]["wet_days_err_change_pct"] = round(float((np.abs(w["y"] - w[a]).mean() - np.abs(w["y"] - w[b]).mean()) / np.abs(w["y"] - w[b]).mean() * 100), 3)
        w8 = t[(t["wet"] == 1) & t["emd"].isin(BIG8)]
        out[f"{a}_vs_{b}"]["big8_wet_err_change_pct"] = round(float((np.abs(w8["y"] - w8[a]).mean() - np.abs(w8["y"] - w8[b]).mean()) / np.abs(w8["y"] - w8[b]).mean() * 100), 3)
    # 공휴일·연휴 효과 크기(전체 학습, 릿지 M1 계수)
    X = X_ridge(d, "M1")
    m = Ridge(alpha=1.0).fit(X.to_numpy(), y)
    out["calendar_coef_pct"] = {c: round(float((np.exp(m.coef_[list(X.columns).index(c)]) - 1) * 100), 2) for c in CAL}
    return out, t


def run_bus(wx):
    bm = pd.read_parquet(ROOT / "data" / "tables" / "bus_month.parquet")
    s = bm.groupby(["dong", "ym"]).agg(n=("n", "sum"), days=("days", "first")).reset_index()
    s["ym"] = pd.to_datetime(s["ym"])
    s = s.sort_values(["dong", "ym"])
    s["y"] = np.log(s["n"] / s["days"])
    g = s.groupby("dong")["y"]
    for L in [3, 4, 5, 12, 15]:
        s[f"l{L}"] = g.shift(L)
    # 그 달 달력·비 일수
    days = pd.date_range("2021-01-01", "2026-12-31")
    cal = calendar(days)
    cal["off"] = ((cal.index.dayofweek >= 5) | (cal["holiday"] == 1)).astype(int)
    cal = cal.join(wx[["rain"]]).assign(wet=lambda x: (x["rain"] >= 1).astype(float).where(x["rain"].notna()))
    mc = cal.groupby(cal.index.to_period("M")).agg(hol=("holiday", "sum"), lb=("long_break", "sum"), off=("off", "sum"), wet=("wet", "sum"), wx_days=("wet", "count"))
    mc.index = mc.index.to_timestamp()
    s = s.join(mc, on="ym")
    s = s.dropna(subset=["l3", "l4", "l5", "l12", "l15"])
    s = s[s["wx_days"] >= 20]  # 비 일수를 셀 수 있는 달만(579 시작 2023-04 이후)
    mon = pd.get_dummies(s["ym"].dt.month, prefix="m", dtype=float).set_index(s.index)
    XA = pd.concat([s[["l3", "l4", "l5", "l12", "l15"]], mon], axis=1)
    XB = pd.concat([XA, s[["hol", "lb", "off", "wet"]]], axis=1)
    # 계절 차분: 작년 같은 달 대비 변화(y - l12)를 예측한다. 입력은 최근 변화(l3 - l15)와 달력·비 일수의 작년 대비 차이
    s = s.sort_values(["dong", "ym"])
    for c in ["hol", "lb", "off", "wet"]:
        s[f"d_{c}"] = s[c] - s.groupby("dong")[c].shift(12)
    s["d_recent"] = s["l3"] - s["l15"]
    XC = s[["d_recent"]]
    XD = s[["d_recent", "d_hol", "d_lb", "d_off", "d_wet"]]
    s["dy"] = s["y"] - s["l12"]
    origins = pd.date_range("2024-07-01", "2025-07-01", freq="2MS")
    rows = []
    for o in origins:
        tr = (s["ym"] < o).to_numpy()
        te = ((s["ym"] >= o + pd.DateOffset(months=2)) & (s["ym"] < o + pd.DateOffset(months=3))).to_numpy()  # 3번째 달 = 3개월 뒤
        if te.sum() == 0:
            continue
        for nm, X in [("ridge_lags", XA), ("ridge_lags_cal_wet", XB)]:
            m = Ridge(alpha=1.0).fit(X[tr], s["y"][tr])
            p = m.predict(X[te])
            rows += [{"origin": str(o.date()), "model": nm, "err": abs(np.exp(yy - pp) - 1)} for yy, pp in zip(s["y"][te], p)]
        rows += [{"origin": str(o.date()), "model": "seasonal_naive", "err": abs(np.exp(yy - ll) - 1)} for yy, ll in zip(s["y"][te], s["l12"][te])]
        for nm, X in [("sdiff_recent", XC), ("sdiff_recent_cal_wet", XD)]:
            ok = tr & X.notna().all(axis=1).to_numpy()
            okt = te & X.notna().all(axis=1).to_numpy()
            if okt.sum() == 0 or ok.sum() < 30:
                continue
            m = Ridge(alpha=1.0).fit(X[ok], s["dy"][ok])
            p = s["l12"][okt] + m.predict(X[okt])
            rows += [{"origin": str(o.date()), "model": nm, "err": abs(np.exp(yy - pp) - 1)} for yy, pp in zip(s["y"][okt], p)]
    r = pd.DataFrame(rows)
    out = {"train_from": str(s["ym"].min().date()), "origins": [str(o.date()) for o in origins], "n_test": int((r["model"] == "seasonal_naive").sum())}
    out["median_abs_err_pct"] = {k: round(float(v.median() * 100), 2) for k, v in r.groupby("model")["err"]}
    out["by_origin"] = r.groupby(["origin", "model"])["err"].median().mul(100).round(2).unstack().to_dict(orient="index")
    return out


def main():
    OUTD.mkdir(parents=True, exist_ok=True)
    d = panel()
    d.to_parquet(OUTD / "panel_v2.parquet", index=False)
    d.to_parquet(OUTD.parents[1] / "tables" / "panel_v2.parquet", index=False)  # 제출본·데모가 쓰는 사본(data/interim은 git에 없음, 2026-11-13)
    res = {"panel": {"rows": int(len(d)), "days": int(d["date"].nunique()), "from": str(d["date"].min().date()), "to": str(d["date"].max().date()),
                     "folds": FOLDS, "test_days": TEST_DAYS, "horizon_days": H}}
    res["M1"], _ = run_m1(d)
    res["bus"] = run_bus(daily_weather())
    (OUTD / "gates_v2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
