"""관문 v3: 파생변수·구간 손실·학습 창 실험 (2026-11-11 사용자 지시 "추천 순서대로 즉시 실행").

과적합 방지: 설정은 앞 3회차(2025-01·04·07, '선택')로만 고르고, 뒤 2회차(2025-10, 2026-01, '보고')는 최종 보고에만 쓴다.
기준 설정 B0 = 관문 v2의 하이브리드(부스팅 달력 M0 + 비 효과 큰 8곳 비 보정). 과제·기준선은 v2와 같다(7일 뒤, 7일 전 값).
실험
  1. 파생변수: 연휴 구조(쉬는 날 연속 길이, 연휴 첫날·마지막날, 징검다리 평일), 섬 전체 방문 7일 전 값, 364일 전 값, 동네 유형(M2 k=2) × 달력
  2. 구간: 분위수 손실(q10·q90) 부스팅 vs 점 예측 + 잔차 분위수(conformal) — 80% 포함률·평균 폭·pinball
  3. 학습 창: 누적 vs 최근 365일 vs 최근 540일
  (4. LSTM 입력 창은 app/lstm_gate.py --windows 로 따로 돈다)
결과: data/interim/gates/gates_v3.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import model_gates_v2 as V2  # noqa: E402
from rain_test import calendar  # noqa: E402

SEL, REP = V2.FOLDS[:3], V2.FOLDS[3:]
BASE_COLS = ["lag7", "lag14", "dow", "mon", *V2.CAL]


def add_features(d):
    d = d.copy()
    days = pd.date_range(d["date"].min() - pd.Timedelta(days=10), d["date"].max() + pd.Timedelta(days=10))
    cal = calendar(days)
    off = pd.Series((days.dayofweek >= 5) | (cal["holiday"].to_numpy() == 1), index=days)
    grp = (~off).cumsum()
    run_len = off.groupby(grp).transform("sum").where(off, 0)
    prev_off, next_off = off.shift(1, fill_value=False), off.shift(-1, fill_value=False)
    first = (off & ~prev_off).astype(int)
    last = (off & ~next_off).astype(int)
    bridge = ((~off) & prev_off & next_off).astype(int)  # 쉬는 날 사이에 낀 평일 하루
    f = pd.DataFrame({"break_len": run_len.clip(upper=6), "break_first": first.where(run_len >= 3, 0), "break_last": last.where(run_len >= 3, 0),
                      "bridge": bridge}, index=days)
    d = d.join(f, on="date")
    isl = d.groupby("date")["visit"].sum().apply(np.log)
    d["island_lag7"] = d["date"].map(isl.shift(7, freq="D"))
    d["lag364"] = d.groupby("emd")["y"].shift(364)
    # 동네 유형: 월 방문 곡선 k=2(관문 v1 M2와 같은 방법)
    pm = pd.read_parquet(ROOT / "data" / "tables" / "pop_month.parquet")
    pm["v"] = pm["visit"] / pm["days"]
    pm["mon"] = pd.to_datetime(pm["ym"]).dt.month
    c = pm.pivot_table(index="dong", columns="mon", values="v", aggfunc="mean")
    c = c.div(c.mean(axis=1), axis=0)
    lab = pd.Series(KMeans(2, n_init=20, random_state=0).fit_predict(c), index=c.index)
    amp = c.max(axis=1) - c.min(axis=1)  # 계절 진폭이 큰 쪽을 '관광형'(1)으로 둔다
    tour = lab.groupby(lab).apply(lambda s: amp[s.index].mean()).idxmax()
    d["tour_type"] = (d["emd"].map(lab) == tour).astype(int)
    for c_ in ["holiday", "long_break", "vacation", "myeongjeol"]:
        d[f"tour_x_{c_}"] = d["tour_type"] * d[c_]
    return d, sorted(lab[lab == tour].index)


def gbm_fit_predict(d, cols, tr, te, loss="squared_error", q=None):
    X = d[cols].astype(float).to_numpy()
    X = np.column_stack([X, d["emd"].astype("category").cat.codes.to_numpy()])
    kw = {"loss": loss, "random_state": 0, "categorical_features": [X.shape[1] - 1], "max_iter": 300}
    if q is not None:
        kw["quantile"] = q
    m = HistGradientBoostingRegressor(**kw).fit(X[tr], d["y"].to_numpy()[tr])
    return m.predict(X[te])


def rain_adj(d, tr):
    """v2 하이브리드와 같은 8곳 비 보정량(같은 회차 학습분으로 릿지 M1d 적합)."""
    Xr = V2.X_ridge(d, "M1d")
    m = Ridge(alpha=1.0).fit(Xr.to_numpy()[tr], d["y"].to_numpy()[tr])
    coef = dict(zip(Xr.columns, m.coef_))
    adj = np.array([coef.get(f"wet_{e}", 0.0) for e in d["emd"]]) * d["wet"].to_numpy()
    return np.where(d["emd"].isin(V2.BIG8), adj, 0.0)


def masks(d, f, window=None):
    tr, te = V2.fold_masks(d, f)
    if window:
        tr = tr & (d["date"] >= pd.Timestamp(f) - pd.Timedelta(days=V2.H + window)).to_numpy()
    return tr, te


def evaluate(d, cols, window=None):
    p = np.full(len(d), np.nan)
    for f in V2.FOLDS:
        tr, te = masks(d, f, window)
        p[te] = gbm_fit_predict(d, cols, tr, te) + rain_adj(d, tr)[te]
    return p


def summarize(d, preds):
    t = d.assign(fold=None)
    for f in V2.FOLDS:
        _, te = V2.fold_masks(d, f)
        t.loc[te, "fold"] = f
    t = t.dropna(subset=["fold"])
    base = (t["y"] - t["lag7"]).abs()
    out = {}
    for k, p in preds.items():
        e = (t["y"] - p[t.index]).abs()
        sel, rep = t["fold"].isin(SEL), t["fold"].isin(REP)
        out[k] = {"MASE_select": round(float(e[sel].mean() / base[sel].mean()), 4), "MASE_report": round(float(e[rep].mean() / base[rep].mean()), 4),
                  "MASE_all": round(float(e.mean() / base.mean()), 4)}
    return out, t


def paired(t, pa, pb, folds):
    s = t[t["fold"].isin(folds)]
    g = pd.DataFrame({"emd": s["emd"], "fold": s["fold"], "ea": (s["y"] - pa[s.index]).abs(), "eb": (s["y"] - pb[s.index]).abs()}).groupby(["emd", "fold"]).mean()
    w, n = int((g["ea"] < g["eb"]).sum()), int((g["ea"] != g["eb"]).sum())
    return {"better": f"{w}/{n}", "sign_p": float(stats.binomtest(w, n, 0.5).pvalue) if n else 1.0, "wilcoxon_p": float(stats.wilcoxon(g["ea"], g["eb"]).pvalue) if n else 1.0}


def main():
    d = V2.panel()
    d, tour_dongs = add_features(d)
    d = d.reset_index(drop=True)
    res = {"design": {"select_folds": SEL, "report_folds": REP, "tour_type_dongs": tour_dongs}}
    # 1. 파생변수
    F_BREAK = ["break_len", "break_first", "break_last", "bridge"]
    F_TOUR = ["tour_type", "tour_x_holiday", "tour_x_long_break", "tour_x_vacation", "tour_x_myeongjeol"]
    sets = {"B0": BASE_COLS, "B0+break": BASE_COLS + F_BREAK, "B0+island": BASE_COLS + ["island_lag7"], "B0+lag364": BASE_COLS + ["lag364"],
            "B0+tour": BASE_COLS + F_TOUR, "B0+all": BASE_COLS + F_BREAK + ["island_lag7", "lag364"] + F_TOUR}
    preds = {k: evaluate(d, c) for k, c in sets.items()}
    s1, t = summarize(d, preds)
    best = min((k for k in sets if k != "B0"), key=lambda k: s1[k]["MASE_select"])
    res["1_features"] = s1
    res["1_best_by_select"] = best
    res["1_best_vs_B0_report"] = paired(t, preds[best], preds["B0"], REP)
    res["1_best_vs_B0_select"] = paired(t, preds[best], preds["B0"], SEL)
    cols = sets[best] if s1[best]["MASE_select"] < s1["B0"]["MASE_select"] else sets["B0"]
    # 2. 구간: 분위수 손실 vs conformal(선택 회차의 마지막 직전 60일 잔차로 보정)
    lo_q, hi_q, lo_c, hi_c, pt = (np.full(len(d), np.nan) for _ in range(5))
    for f in V2.FOLDS:
        tr, te = masks(d, f)
        adj = rain_adj(d, tr)
        lo_q[te] = gbm_fit_predict(d, cols, tr, te, "quantile", 0.1) + adj[te]
        hi_q[te] = gbm_fit_predict(d, cols, tr, te, "quantile", 0.9) + adj[te]
        # conformal: 학습 구간 마지막 60일을 보정용으로 떼어 잔차 분위수
        cal_start = pd.Timestamp(f) - pd.Timedelta(days=V2.H + 60)
        tr2 = tr & (d["date"] < cal_start).to_numpy()
        ca = tr & (d["date"] >= cal_start).to_numpy()
        both = ca | te
        p_both = gbm_fit_predict(d, cols, tr2, both) + adj[both]
        pc = np.full(len(d), np.nan)
        pc[both] = p_both
        r = d["y"].to_numpy()[ca] - pc[ca]
        lo_c[te], hi_c[te] = pc[te] + np.quantile(r, 0.1), pc[te] + np.quantile(r, 0.9)
        pt[te] = pc[te]
    y = d["y"].to_numpy()
    iv = {}
    for nm, lo, hi in [("quantile_loss", lo_q, hi_q), ("conformal", lo_c, hi_c)]:
        for part, folds in [("select", SEL), ("report", REP)]:
            m = t[t["fold"].isin(folds)].index
            cov = float(np.mean((y[m] >= lo[m]) & (y[m] <= hi[m])))
            width = float(np.mean(np.exp(hi[m] - lo[m]) - 1) * 100)
            pin = float(np.mean([max(0.1 * (y_ - l), (0.1 - 1) * (y_ - l)) + max(0.9 * (y_ - h), (0.9 - 1) * (y_ - h)) for y_, l, h in zip(y[m], lo[m], hi[m])]))
            iv[f"{nm}_{part}"] = {"coverage80": round(cov, 3), "mean_width_pct": round(width, 1), "pinball": round(pin, 5)}
    res["2_intervals"] = iv
    # 3. 학습 창
    win = {"expanding": None, "sliding365": 365, "sliding540": 540}
    pw = {k: evaluate(d, cols, w) for k, w in win.items()}
    s3, t3 = summarize(d, pw)
    res["3_window"] = s3
    bw = min((k for k in win if k != "expanding"), key=lambda k: s3[k]["MASE_select"])
    res["3_best_vs_expanding_report"] = paired(t3, pw[bw], pw["expanding"], REP)
    res["3_best_by_select"] = bw
    out = ROOT / "data" / "interim" / "gates" / "gates_v3.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
