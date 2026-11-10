"""비 오는 날 동네 방문 변화의 가설 검정 (2026-11-11 사용자 요청: "비가 와도 변화가 작다"를 검정으로 보인다).

설계(관문 v1의 단순함 지적을 반영)
- 단위: 동네 × 일. 583 방문 지수(성·연령 합계), 연속 수집 구간만(2023-11-04 ~ 연속이 끊기기 전날).
- 통제: 요일, 연·월(계절과 해마다 다른 수준), 공휴일, 연휴(주말·공휴일이 3일 이상 이어진 날), 명절, 방학 기간 [가정: 7/20~8/31, 12/25~2/28],
  기온(2차), 강풍(최대풍속 14m/s 이상). 공휴일은 `holidays` 0.58 KR + 2025-01-27 임시공휴일(패키지에 없어 손으로 추가).
- 처치: 비 온 날(섬 중앙값 일강수 1mm 이상). 강도별 계수(1~10, 10~30, 30mm 이상)도 따로 낸다.
- 기상: 2025-03-30까지 579(산지 관측소 제외 AWS 중앙값), 2025-03-31부터 ASOS 4곳 중앙값. 두 원천이 섞인다(한계).
- 추정: 동네마다 OLS(로그 방문), 표준오차는 Newey-West(시차 7). 동네 간 차이는 동네 고정효과 + 동네별 비 계수 모형으로 따로 검정.
- 검정
  ① 차이 검정: H0 효과 = 0 (양측, BH 보정 q < 0.05)
  ② 동등성 검정(TOST): H0 |효과| ≥ δ, δ = 10%. 두 단측 검정의 큰 p가 0.05 미만이면 "변화가 ±10% 안"을 보인 것(BH 보정)
  ③ 이질성: 43개 동네의 비 계수가 모두 같은가(Cochran Q)
  ④ 상호작용: 비 × (주말·공휴일), 비 × 여름(6~8월) — 관광객이 많은 날 비 효과가 다른가
결과: data/interim/gates/rain_test.json, 표는 docs/조사/08_비효과_가설검정.md
실행: .venv/bin/python app/rain_test.py
"""
import json
import sys
from pathlib import Path

import holidays
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from build_dong_tables import IN, MOUNTAIN, load_api  # noqa: E402
from stats import bh  # noqa: E402

DELTA = 0.10
LAG = 7


def daily_visit():
    pop, files = load_api(583)
    pop["date"] = pd.to_datetime(pop["baseDate"].astype(str))
    v = pop.groupby(["date", "emd"])["visitPop"].sum().rename("visit").reset_index()
    days = pd.Series(sorted(v["date"].unique()))
    gap = days.diff().dt.days.fillna(1)
    end = days[gap.gt(1).idxmax() - 1] if gap.gt(1).any() else days.iloc[-1]  # 첫 끊김 전날까지
    return v[v["date"] <= end], str(days.iloc[0].date()), str(pd.Timestamp(end).date())


def daily_weather():
    wx, _ = load_api(579)
    wx = wx[~wx["observatoryName"].isin(MOUNTAIN)].copy()
    wx["date"] = pd.to_datetime(wx["baseDate"].astype(str))
    for c in ["dailyRainfall", "averageTemperature", "maximumWindSpeed"]:
        wx[c] = pd.to_numeric(wx[c], errors="coerce")
    a = wx.groupby("date").agg(rain=("dailyRainfall", "median"), temp=("averageTemperature", "median"), wind=("maximumWindSpeed", "median"))
    a["rain"] = a["rain"].fillna(0)
    asos = pd.concat([pd.read_parquet(f) for f in (IN / "api" / "asos").glob("*.parquet")])
    asos["date"] = pd.to_datetime(asos["tm"])
    for c in ["sumRn", "avgTa", "maxWs"]:
        asos[c] = pd.to_numeric(asos[c].replace("", np.nan), errors="coerce")
    asos["sumRn"] = asos["sumRn"].fillna(0)
    b = asos.groupby("date").agg(rain=("sumRn", "median"), temp=("avgTa", "median"), wind=("maxWs", "median"))
    b = b[b.index > a.index.max()]
    w = pd.concat([a, b]).sort_index()
    w["source"] = np.where(w.index <= a.index.max(), "579", "ASOS")
    return w


def calendar(dates):
    years = sorted({d.year for d in dates})
    kr = holidays.KR(years=years)
    hol = {pd.Timestamp(d) for d in kr} | {pd.Timestamp("2025-01-27")}
    myeong = {pd.Timestamp(d) for d, n in kr.items() if "New Year" in n and "Korean" in n or "Chuseok" in n}
    full = pd.date_range(min(dates) - pd.Timedelta(days=7), max(dates) + pd.Timedelta(days=7))
    off = pd.Series([d.dayofweek >= 5 or d in hol for d in full], index=full)
    run = off.groupby((~off).cumsum()).transform("sum") * off  # 쉬는 날 연속 길이
    c = pd.DataFrame(index=pd.DatetimeIndex(dates))
    c["holiday"] = [int(d in hol and d.dayofweek < 5) for d in c.index]
    c["long_break"] = [int(run[d] >= 3) for d in c.index]
    c["myeongjeol"] = [int(d in myeong) for d in c.index]
    c["vacation"] = [int((d.month == 7 and d.day >= 20) or d.month == 8 or (d.month == 12 and d.day >= 25) or d.month in (1, 2)) for d in c.index]
    return c


def design(df):
    X = pd.get_dummies(df["date"].dt.dayofweek.astype(str), prefix="dow", drop_first=True, dtype=float)
    X = X.join(pd.get_dummies(df["date"].dt.strftime("%Y-%m"), prefix="ym", drop_first=True, dtype=float))
    X = X.join(df[["holiday", "long_break", "myeongjeol", "vacation", "windy"]].astype(float))
    X["temp"] = df["temp"] - df["temp"].mean()
    X["temp2"] = X["temp"] ** 2
    X.insert(0, "const", 1.0)
    return X


def ols_nw(y, X, lag=LAG):
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    XtX_inv = np.linalg.pinv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    u = X * e[:, None]
    S = u.T @ u
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = u[L:].T @ u[:-L]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return b, np.sqrt(np.diag(V)), len(y) - X.shape[1]


def main():
    v, start, end = daily_visit()
    w = daily_weather()
    d = v.merge(w, left_on="date", right_index=True).dropna(subset=["temp", "wind"])
    d = d.join(calendar(d["date"].unique()), on="date")
    d["wet"] = (d["rain"] >= 1).astype(float)
    d["r1"] = d["rain"].between(1, 10, inclusive="left").astype(float)
    d["r2"] = d["rain"].between(10, 30, inclusive="left").astype(float)
    d["r3"] = (d["rain"] >= 30).astype(float)
    d["windy"] = (d["wind"] >= 14).astype(int)
    d["y"] = np.log(d["visit"])
    d["offday"] = ((d["date"].dt.dayofweek >= 5) | (d["holiday"] == 1)).astype(float)
    d["summer"] = d["date"].dt.month.isin([6, 7, 8]).astype(float)
    days = d.drop_duplicates("date")
    info = {"period": f"{d['date'].min().date()}~{d['date'].max().date()}", "583_continuous": f"{start}~{end}", "days": int(len(days)), "dongs": int(d["emd"].nunique()),
            "wet_days": int(days["wet"].sum()), "r1_days": int(days["r1"].sum()), "r2_days": int(days["r2"].sum()), "r3_days": int(days["r3"].sum()),
            "holidays_weekday": int(days["holiday"].sum()), "long_break_days": int(days["long_break"].sum()),
            "days_579": int((days["source"] == "579").sum()), "days_asos": int((days["source"] == "ASOS").sum())}
    rows = []
    for dong, g in d.groupby("emd"):
        g = g.sort_values("date")
        X = design(g)
        Xw = X.join(g[["wet"]])
        b, se, dof = ols_nw(g["y"], Xw)
        beta, s = b[-1], se[-1]
        p0 = 2 * stats.t.sf(abs(beta / s), dof)
        lo_m, hi_m = np.log(1 - DELTA), np.log(1 + DELTA)  # 비율 ±10%를 로그로
        p_tost = max(stats.t.sf((beta - lo_m) / s, dof), stats.t.cdf((beta - hi_m) / s, dof))
        Xb = X.join(g[["r1", "r2", "r3"]])
        bb, sb, _ = ols_nw(g["y"], Xb)
        rows.append({"dong": dong, "effect_pct": (np.exp(beta) - 1) * 100, "lo95": (np.exp(beta - 1.96 * s) - 1) * 100, "hi95": (np.exp(beta + 1.96 * s) - 1) * 100,
                     "lo90": (np.exp(beta - 1.645 * s) - 1) * 100, "hi90": (np.exp(beta + 1.645 * s) - 1) * 100, "p_zero": p0, "p_tost": p_tost,
                     "beta": beta, "se": s, "r1_pct": (np.exp(bb[-3]) - 1) * 100, "r2_pct": (np.exp(bb[-2]) - 1) * 100, "r3_pct": (np.exp(bb[-1]) - 1) * 100})
    r = pd.DataFrame(rows).set_index("dong")
    sig0 = set(bh(r["p_zero"], 0.05))
    sigeq = set(bh(r["p_tost"], 0.05))
    r["diff_sig"] = r.index.isin(sig0)
    r["equiv_sig"] = r.index.isin(sigeq)

    def cls(x):
        if x.equiv_sig and not x.diff_sig:
            return "작음 확인(±10% 안, 0과 차이 없음)"
        if x.equiv_sig and x.diff_sig:
            return "작지만 0은 아님(±10% 안)"
        if x.diff_sig and (x.lo95 < -10 or x.hi95 > 10):
            return "변화 있음(10% 넘을 수 있음)"
        if x.diff_sig:
            return "변화 있음"
        return "판단 불가(구간이 넓음)"
    r["class"] = r.apply(cls, axis=1)
    # ③ 이질성(Cochran Q)
    wts = 1 / r["se"] ** 2
    pooled = (wts * r["beta"]).sum() / wts.sum()
    Q = float((wts * (r["beta"] - pooled) ** 2).sum())
    het = {"pooled_effect_pct": round((np.exp(pooled) - 1) * 100, 2), "Q": round(Q, 1), "df": len(r) - 1, "p": float(stats.chi2.sf(Q, len(r) - 1)),
           "I2_pct": round(max(0, (Q - (len(r) - 1)) / Q) * 100, 1)}
    # ④ 상호작용(동네 고정효과 통합 모형)
    X = design(d).join(pd.get_dummies(d["emd"], prefix="dong", drop_first=True, dtype=float))
    X["wet"] = d["wet"]
    X["wet_x_offday"] = d["wet"] * d["offday"]
    X["wet_x_summer"] = d["wet"] * d["summer"]
    X["offday"] = d["offday"]
    b, se, dof = ols_nw(d["y"], X, lag=0)  # 동네가 섞여 시차 HAC 대신 이분산 강건(시차 0)
    inter = {k: {"pct": round((np.exp(b[i]) - 1) * 100, 2), "lo95": round((np.exp(b[i] - 1.96 * se[i]) - 1) * 100, 2), "hi95": round((np.exp(b[i] + 1.96 * se[i]) - 1) * 100, 2),
                 "p": float(2 * stats.t.sf(abs(b[i] / se[i]), dof))} for i, k in enumerate(X.columns) if k in ("wet", "wet_x_offday", "wet_x_summer")}
    summary = r["class"].value_counts().to_dict()
    out = {"info": info, "class_counts": summary, "heterogeneity": het, "interaction": inter,
           "per_dong": r.round(4).reset_index().to_dict(orient="records"),
           "median_effect_pct": round(float(r["effect_pct"].median()), 2), "n_diff_sig": int(r["diff_sig"].sum()), "n_equiv_sig": int(r["equiv_sig"].sum()),
           "n_abs_ge10": int((r["effect_pct"].abs() >= 10).sum())}
    (IN / "gates").mkdir(exist_ok=True)
    (IN / "gates" / "rain_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ["info", "class_counts", "heterogeneity", "interaction", "median_effect_pct", "n_diff_sig", "n_equiv_sig", "n_abs_ge10"]}, ensure_ascii=False, indent=1))
    print(r.sort_values("effect_pct")[["effect_pct", "lo95", "hi95", "p_zero", "p_tost", "class", "r1_pct", "r2_pct", "r3_pct"]].round(2).to_string())


if __name__ == "__main__":
    main()
