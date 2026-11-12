"""W5 레시피 실행(S3 학습·검증·추론)과 학습 전 점검(S2) (docs/기획/05_Agent구조_v2.md 15절, 2026-11-11 구현).

- 등록부: models/recipes.json. S3는 등록된 레시피의 허용 변수·검증 방식 안에서만 학습한다.
- 순서(사용자 결정 2026-11-11): S1 조회 → S2 학습 전 점검(check) → S3 학습·검증·추론(run) → S6 관문 판정(s6.gate) → S4.
  · 점검에서 떨어진 동네는 학습·추론에서 뺀다. 모두 떨어지면 학습하지 않고 fallback으로 답한다.
  · S3는 검증 오차(gate_input)와 추론 결과를 함께 낸다. 추론 결과를 답에 쓸지는 S6 관문이 정한다.
- 캐시: (레시피, 자료 판, 설정)이 같으면 학습을 건너뛴다. models/cache/<레시피>_<키>.json. 학습 기록은 models/registry.json에 덧붙인다.
- 재사용: 관문 코드(app/model_gates.py v1, app/model_gates_v2.py v2)의 특성·이웃·군집 함수를 그대로 쓴다.
"""
import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

REG = json.loads((Q.ROOT / "models" / "recipes.json").read_text(encoding="utf-8"))
_WRITE = Path(os.environ["JEJU_WRITE_DIR"]) if os.environ.get("JEJU_WRITE_DIR") else Q.ROOT  # 데모(Vercel)는 /tmp만 쓸 수 있다
CACHE_RO = Q.ROOT / "models" / "cache"  # 저장소에 든 캐시(읽기)
CACHE = _WRITE / "models" / "cache"
REGISTRY = _WRITE / "models" / "registry.json"
# 방문 패널: 제출본에 든 data/tables 사본을 먼저 쓴다(data/interim은 git·ZIP에 없음, 2026-11-13)
PANEL = next((p for p in (Q.ROOT / "data" / "tables" / "panel_v2.parquet", Q.ROOT / "data" / "interim" / "gates" / "panel_v2.parquet") if p.exists()),
             Q.ROOT / "data" / "tables" / "panel_v2.parquet")
TAB = Q.ROOT / "data" / "tables"
CENTER_ONLY = {"R8", "R9"}
NO_CHECK = {"R3", "R8", "R9", "R10", "R11"}


class RecipeError(Exception):
    pass


def _fingerprint(*paths):
    """자료 판 표시: 이름·크기·내용 해시. 수정 시각을 쓰지 않아 git·ZIP으로 옮겨도 같은 캐시를 쓴다(2026-11-13)."""
    return [f"{p.name}:{p.stat().st_size}:{hashlib.sha1(p.read_bytes()).hexdigest()[:12]}" for p in paths]


def _key(rid, fp, cfg):
    return hashlib.sha1(json.dumps([rid, fp, cfg], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def _cached(rid, fp, cfg, build):
    """캐시가 있으면 읽고, 없으면 build()로 학습해 저장하고 등록부에 기록한다."""
    k = _key(rid, fp, cfg)
    f = CACHE / f"{rid}_{k}.json"
    for c in (f, CACHE_RO / f.name):
        if c.exists():
            return dict(json.loads(c.read_text(encoding="utf-8")), cache="hit")
    t0 = time.perf_counter()
    res = build()
    res["train_sec"] = round(time.perf_counter() - t0, 2)
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(res, ensure_ascii=False, default=str), encoding="utf-8")
    reg = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else []
    reg.append({"recipe": rid, "key": k, "trained_at": time.strftime("%Y-%m-%d %H:%M"), "data": fp, "config": cfg,
                "train_sec": res["train_sec"], "mase": (res.get("gate_input") or {}).get("mase")})
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(res, cache="miss")


def _dongs(flt):
    d = (flt or {}).get("dong")
    return d if isinstance(d, list) and d else None


# ---------- S2 학습 전 점검 ----------
def check(rid, flt, tables=()):
    """레시피 자료가 학습할 만한지 동네별로 본다. 반환: {"pass": bool, "ok": [동네], "fail": {동네: 이유}, "rule": 기준}."""
    if rid in NO_CHECK or rid not in REG:
        return {"pass": True, "ok": _dongs(flt), "fail": {}, "rule": None}
    rule, dongs = REG[rid]["check"], _dongs(flt)
    ok, fail = [], {}
    if rid == "R1":
        d = pd.read_parquet(PANEL, columns=["date", "emd", "visit"])
        for e, g in d.groupby("emd"):
            if dongs and e not in dongs:
                continue
            span = (g["date"].max() - g["date"].min()).days + 1
            miss = 1 - g["date"].nunique() / span
            zero = float((g["visit"] <= 0).mean())
            why = [x for x, bad in [(f"기간 {span}일 < {rule['min_days']}일", span < rule["min_days"]),
                                    (f"결측 {miss:.0%} > {rule['max_missing_ratio']:.0%}", miss > rule["max_missing_ratio"]),
                                    (f"0값 {zero:.0%} > {rule['max_zero_ratio']:.0%}", zero > rule["max_zero_ratio"])] if bad]
            (fail.__setitem__(e, "; ".join(why)) if why else ok.append(e))
    elif rid == "R2":
        t = next((x for x in tables if "ym" in x), None)
        if t is None:
            raise RecipeError("R2 점검: 월 단위 입력 표 없음")
        for e, g in t.groupby("dong"):
            n = g["ym"].nunique()
            (fail.__setitem__(e, f"{n}개월 < {rule['min_months']}개월") if n < rule["min_months"] else ok.append(e))
    elif rid == "R4":
        n = len(_cohort((flt or {}).get("target")))
        ok, fail = (["전체"], {}) if n >= rule["min_n"] else ([], {"전체": f"표본 {n} < {rule['min_n']}"})
    elif rid in ("R5", "R6"):
        idx = _features().index if rid == "R5" else _curves().index
        for e in (dongs or list(idx)):
            (ok.append(e) if e in idx else fail.__setitem__(e, "특성 표에 없음"))
    elif rid == "R7":
        e = pd.read_parquet(TAB / "rest_events.parquet")
        n = e["year"].nunique()
        for x in (dongs or sorted(e["dong"].unique())):
            (ok.append(x) if n >= rule["min_years"] and x in set(e["dong"]) else fail.__setitem__(x, "연도 수 부족 또는 동네 없음"))
    return {"pass": bool(ok), "ok": ok, "fail": fail, "rule": rule}


# ---------- R1 방문 예측 ----------
def _r1_build(cfg):
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="sklearn")  # numpy 2.0 + Accelerate의 거짓 행렬곱 경고(m1.py와 같은 사유)
    import model_gates_v2 as G
    from rain_test import calendar
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    d = pd.read_parquet(PANEL).sort_values(["emd", "date"]).reset_index(drop=True)
    y = d["y"].to_numpy()
    cats = d["emd"].astype("category").cat.categories
    Xg, cat = G.X_gbm(d, "M0")
    Xr = G.X_ridge(d, "M1d")
    wet_cols = [c for c in Xr.columns if c.startswith("wet_")]

    def fit(tr):
        g = HistGradientBoostingRegressor(random_state=0, categorical_features=cat, max_iter=300).fit(Xg.to_numpy()[tr], y[tr])
        r = Ridge(alpha=1.0).fit(Xr.to_numpy()[tr], y[tr])
        coef = {c[4:]: float(v) for c, v in zip(Xr.columns, r.coef_) if c in wet_cols and c[4:] in G.BIG8}
        return g, coef
    pred = np.full(len(d), np.nan)
    fold = np.full(len(d), None, dtype=object)
    for f in cfg["folds"]:
        s = pd.Timestamp(f)
        tr = (d["date"] < s - pd.Timedelta(days=cfg["horizon"])).to_numpy()
        te = ((d["date"] >= s) & (d["date"] < s + pd.Timedelta(days=cfg["test_days"]))).to_numpy()
        g, coef = fit(tr)
        adj = np.array([coef.get(e, 0.0) for e in d["emd"]]) * d["wet"].to_numpy()
        pred[te] = g.predict(Xg.to_numpy()[te]) + adj[te]
        fold[te] = f
    t = d.assign(pred=pred, fold=fold).dropna(subset=["pred"])
    cell = t.assign(em=np.abs(t["y"] - t["pred"]), eb=np.abs(t["y"] - t["lag7"])).groupby(["emd", "fold"])[["em", "eb"]].mean()
    mase = float(np.abs(t["y"] - t["pred"]).mean() / np.abs(t["y"] - t["lag7"]).mean())
    mase_dong = (cell.groupby(level=0)["em"].mean() / cell.groupby(level=0)["eb"].mean()).round(4).to_dict()
    # 추론: 전체 자료로 다시 학습, 마지막 날 다음 7일. 7·14일 전 값은 이미 관측된 값이다.
    g, coef = fit(np.ones(len(d), bool))
    last = d["date"].max()
    # 예상 범위(문서 22 4절 R1 ①): 검증 3회차(각 60일)에서 빗나간 크기(로그 차이)의 10%·90% 분위로 폭을 정한다. 모델은 다시 학습하지 않는다.
    # 확인: 한 회차를 빼고 나머지 두 회차로 잡은 폭이 뺀 회차에서 실제 값을 몇 % 담는지(목표 80%).
    # 폭 후보 셋(전체 하나 · 동/읍면 두 묶음 · 동네별) 가운데, 전체 포함률과 동·읍면 묶음별 포함률이 모두 80%에 가까운 쪽을 쓴다(이중 검토 035: 읍면이 좁았다).
    t["r"] = t["y"] - t["pred"]
    t["grp"] = np.where(t["emd"].astype(str).str.endswith("동"), "동", "읍면")
    t["day"] = (t["date"] - pd.to_datetime(t["fold"])).dt.days
    keys = {"pooled": None, "by_group": "grp", "by_dong": "emd"}
    hit = {k: [] for k in keys}
    for f in cfg["folds"]:
        tr_, te_ = t[t["fold"] != f], t[t["fold"] == f]
        for k, col in keys.items():
            if col is None:
                lo, hi = tr_["r"].quantile(0.1), tr_["r"].quantile(0.9)
                ok = te_["r"].between(lo, hi)
            else:
                m = te_.join(tr_.groupby(col)["r"].quantile([0.1, 0.9]).unstack(), on=col)
                ok = (m["r"] >= m[0.1]) & (m["r"] <= m[0.9])
            hit[k].append(te_.assign(ok=ok.to_numpy()))
    cover, score = {}, {}
    for k, parts in hit.items():
        h = pd.concat(parts)
        pc = lambda x: round(float(x.mean() * 100), 1)
        cover[k] = {"folds": {f: pc(g["ok"]) for f, g in h.groupby("fold")}, "groups": {g: pc(x["ok"]) for g, x in h.groupby("grp")},
                    "first7": pc(h[h["day"] < 7]["ok"])}
        score[k] = abs(np.mean(list(cover[k]["folds"].values())) - 80) + max(abs(v - 80) for v in cover[k]["groups"].values())
    how = min(score, key=score.get)
    q_all = (float(t["r"].quantile(0.1)), float(t["r"].quantile(0.9)))
    col = keys[how]
    qg = t.groupby(col)["r"].quantile([0.1, 0.9]).unstack() if col else None
    key_of = lambda e: (e if col == "emd" else ("동" if str(e).endswith("동") else "읍면"))
    qd_map = {e: (float(qg.loc[key_of(e), 0.1]), float(qg.loc[key_of(e), 0.9])) if col and key_of(e) in qg.index else q_all for e in cats}
    q_lo, q_hi = q_all
    days = pd.date_range(last + pd.Timedelta(days=1), periods=cfg["horizon"])
    cal = calendar(days)
    ylog = d.set_index(["emd", "date"])["y"]
    rows = []
    for e in cats:
        for day in days:
            rows.append({"emd": e, "date": day, "lag7": ylog.get((e, day - pd.Timedelta(days=7)), np.nan), "lag14": ylog.get((e, day - pd.Timedelta(days=14)), np.nan),
                         "dow": day.dayofweek, "mon": day.month, **cal.loc[day, G.CAL].to_dict()})
    fu = pd.DataFrame(rows).dropna(subset=["lag7", "lag14"])
    Xf = fu[["lag7", "lag14", "dow", "mon", *G.CAL]].astype(float).copy()
    Xf["dong"] = pd.Categorical(fu["emd"], categories=cats).codes
    fu["visit"] = np.exp(g.predict(Xf.to_numpy()))
    fu["rain_pct"] = [round((np.exp(coef[e]) - 1) * 100, 1) if e in coef else None for e in fu["emd"]]
    return {"gate_input": {"model_err": cell["em"].round(6).tolist(), "baseline_err": cell["eb"].round(6).tolist(), "mase": round(mase, 4),
                           "cells": [f"{a}|{b}" for a, b in cell.index]},
            "mase_by_dong": mase_dong,
            "interval_q": {"lo": round(q_lo, 5), "hi": round(q_hi, 5), "method": how, "coverage_lofo": cover,
                           "by": {k: [round(v[0], 5), round(v[1], 5)] for k, v in ({g: (float(qg.loc[g, 0.1]), float(qg.loc[g, 0.9])) for g in qg.index} if col == "grp" else {}).items()}},
            "forecast": [{"dong": r.emd, "date": str(r.date.date()), "visit": round(float(r.visit), 1),
                          "lo": round(float(r.visit * np.exp(qd_map[r.emd][0])), 1), "hi": round(float(r.visit * np.exp(qd_map[r.emd][1])), 1), "rain_effect_pct": None if pd.isna(r.rain_pct) else float(r.rain_pct), **{c: int(getattr(r, c)) for c in G.CAL}} for r in fu.itertuples()],
            "data_last": str(last.date())}


def r1(flt):
    spec = REG["R1"]
    cfg = {"folds": spec["validation"]["folds"], "test_days": spec["validation"]["test_days"], "horizon": spec["horizon_days"], "model": "gbm_M0+big8rain", "interval": "cv_folds_q10_q90_pick_group"}
    res = _cached("R1", _fingerprint(PANEL), cfg, lambda: _r1_build(cfg))
    return _limit(res, flt, ("forecast",), "mase_by_dong")


def _limit(res, flt, keys, dict_key=None):
    dongs = _dongs(flt)
    if not dongs:
        return res
    out = dict(res)
    for k in keys:
        out[k] = [r for r in res.get(k, []) if r.get("dong") in dongs]
    if dict_key:
        out[dict_key] = {k: v for k, v in res.get(dict_key, {}).items() if k in dongs}
    return out


# ---------- R2 버스 수준 예상 ----------
def _bus_all():
    bm = pd.read_parquet(TAB / "bus_month.parquet")
    g = bm.groupby(["dong", "ym"]).agg(n=("n", "sum"), days=("days", "first")).reset_index()
    return g.assign(value=g["n"] / g["days"])[["dong", "ym", "value"]]


def r2(flt, table):
    t = _bus_all()  # 관문은 레시피 단위로 전체 동네 × 최근 6개월에서 본다(R1과 같은 원칙). 답은 질문 동네만
    t["ym"] = pd.to_datetime(t["ym"])
    piv = t.pivot_table(index="ym", columns="dong", values="value")
    months = piv.index.sort_values()
    origins = months[-6:]
    em, eb = [], []
    for m in origins:  # 이동 원점: 그 달을 12개월 전 같은 달(모델)과 3개월 전 값(기준선)으로 맞힌다
        a, b = m - pd.DateOffset(years=1), m - pd.DateOffset(months=3)
        if a in piv.index and b in piv.index:
            y = piv.loc[m]
            em += list(np.abs(np.log(y) - np.log(piv.loc[a])).dropna())
            eb += list(np.abs(np.log(y) - np.log(piv.loc[b])).dropna())
    n = min(len(em), len(eb))
    em, eb = em[:n], eb[:n]
    nxt = months.max() + pd.DateOffset(months=1)
    base = piv.loc[nxt - pd.DateOffset(years=1)] if nxt - pd.DateOffset(years=1) in piv.index else pd.Series(dtype=float)
    fc = [{"dong": k, "ym": str(nxt.date()), "value": round(float(v), 1)} for k, v in base.dropna().items()]
    res = {"gate_input": {"model_err": em, "baseline_err": eb, "mase": round(float(np.mean(em) / np.mean(eb)), 4) if n else None},
           "forecast": fc, "interval": REG["R2"]["interval"]}
    return _limit(res, flt, ("forecast",))


# ---------- R4 업종별 생존 ----------
def _cohort(target):
    from build_dong_tables import IN, KM_END, KM_START
    from places import REST_MAP
    rest = pd.read_parquet(IN / "restaurants.parquet")
    end = rest[["open_date", "close_date"]].max().max()
    km_end = KM_END or str((end - pd.DateOffset(years=5)).date())  # v3: 관측 끝 − 5년(build_dong_tables와 같은 규칙)
    co = rest[(rest["open_date"] >= KM_START) & (rest["open_date"] <= km_end)].copy()
    co.attrs["cohort"] = f"{KM_START[:7]}~{km_end[:7]}"
    if target and REST_MAP.get(target):
        co = co[co["업종구분소분류"].isin(REST_MAP[target])]
    co["event"] = co["close_date"].notna()
    co["y"] = ((co["close_date"].fillna(end) - co["open_date"]).dt.days / 365.25).clip(lower=0)
    return co


def r4(flt, chk):
    from stats import km_at
    tgt = (flt or {}).get("target")
    use = tgt if chk.get("pass") else None  # 표본 부족이면 제주 전체 음식점으로 대신 답한다(fallback)
    co = _cohort(use)
    s5, se5, n = km_at(co["y"].to_numpy(), co["event"].to_numpy(), 5)
    s2, _, _ = km_at(co["y"].to_numpy(), co["event"].to_numpy(), 2)
    curve = [{"year": k, "pct": round(float(km_at(co["y"].to_numpy(), co["event"].to_numpy(), k)[0]) * 100, 1)} for k in (1, 2, 3, 4, 5)]
    return {"survival": {"group": use or "음식점 전체", "n": int(len(co)), "surv5_pct": round(s5 * 100, 1), "ci95_pp": round(1.96 * se5 * 100, 1),
                         "cond_2to5_pct": round(s5 / s2 * 100, 1) if s2 > 0 else None, "space": "제주 전체(동네별 표본이 작아 업종 묶음 단위)", "cohort": co.attrs.get("cohort"), "curve": curve},
            "fallback": None if use == tgt else f"{tgt} 표본 부족 → 음식점 전체"}


# ---------- R5 동네 유사도 / R6 계절 유형 ----------
def _features():
    import model_gates as G1
    return G1.m4_features()


def r5(flt, chk):
    import model_gates as G1
    F = _features()
    nb = G1.neighbors(F)
    # 닮은 이유: 그 동네와 이웃 5곳이 함께 43곳 평균에서 같은 쪽으로 벗어난 특성 3개(표준화 값이 큰 순)
    Z = (F - F.mean()) / F.std(ddof=0)
    why = {}
    for d in chk["ok"]:
        m = Z.loc[sorted(nb[d])].mean()
        c = [k for k in Z.columns if Z.loc[d, k] * m[k] > 0 and abs(m[k]) >= 0.3]
        top = sorted(c, key=lambda k: -min(abs(Z.loc[d, k]), abs(m[k])))[:3]
        why[d] = [{"feature": k, "high": bool(Z.loc[d, k] > 0), "value": round(float(F.loc[d, k]), 4), "nb_mean": round(float(F.loc[sorted(nb[d]), k].mean()), 4),
                   "all_mean": round(float(F[k].mean()), 4)} for k in top]  # 문서 22 4절 R5 ①: 닮은 특성을 수치로
    return {"neighbors": {d: sorted(nb[d]) for d in chk["ok"]}, "why": why, "gate": REG["R5"]["pass"]}


def _curves():
    pm = pd.read_parquet(TAB / "pop_month.parquet")
    pm["v"] = pm["visit"] / pm["days"]
    pm["mon"] = pd.to_datetime(pm["ym"]).dt.month
    c = pm.pivot_table(index="dong", columns="mon", values="v", aggfunc="mean")
    return c.div(c.mean(axis=1), axis=0).dropna(axis=1)


def r6(flt, chk):
    from sklearn.cluster import KMeans
    c = _curves()
    lab = pd.Series(KMeans(2, n_init=20, random_state=0).fit_predict(c), index=c.index)
    peak = {k: int(c[lab == k].mean().idxmax()) for k in (0, 1)}
    near = {}
    for d in chk["ok"]:  # 월별 곡선(그 동네 평균 = 1)의 유클리드 거리가 가까운 5곳
        dist = np.sqrt(((c - c.loc[d]) ** 2).sum(axis=1)).drop(d).sort_values()
        near[d] = {"dongs": list(dist.index[:5]), "peak": int(c.loc[d].idxmax()), "low": int(c.loc[d].idxmin()),
                   "peak_ratio": round(float(c.loc[d].max()), 2), "low_ratio": round(float(c.loc[d].min()), 2), "months": int(c.shape[1])}
    return {"season_type": {d: {"group": f"{peak[lab[d]]}월 정점형", "same_type": sorted(set(lab[lab == lab[d]].index) - {d})} for d in chk["ok"]}, "nearest": near,
            "gate": REG["R6"]["pass"]}


# ---------- R7 올해 이례 변화 ----------
def r7(flt, chk, kind="close"):
    from build_dong_tables import IN
    from places import REST_MAP
    ev = pd.read_parquet(TAB / "rest_events.parquet")
    ev = ev[ev["kind"] == kind]
    tgt = (flt or {}).get("target")
    if tgt and REST_MAP.get(tgt):
        ev = ev[ev["category"].isin(REST_MAP[tgt])]
    end = pd.read_parquet(IN / "restaurants.parquet", columns=["open_date", "close_date"]).max().max()
    year = end.year if end.month == 12 else end.year - 1  # 관측이 끝난 해가 12월 전이면 그 해는 덜 찼다 → 마지막 완전 연도
    kind_ko = "폐업" if kind == "close" else "개업"
    note = f"관측 종료 {end.date()}, 마지막 완전 연도 {year}년 기준"
    if (flt or {}).get("by") == "업종":  # 업종별 이례: 고른 동네(없으면 제주 전체) 안에서 음식 업종 묶음별로 같은 계산을 한다(문서 21)
        dongs = (flt or {}).get("dong")
        one = isinstance(dongs, list) and len(dongs) == 1
        if one:
            ev = ev[ev["dong"] == dongs[0]]
        rows = []
        for g, cats in REST_MAP.items():
            if not cats or g == "횟집":  # 횟집은 일식 묶음에 들어 있다
                continue
            s = ev[ev["category"].isin(cats)].groupby("year")["count"].sum()
            cnt, mu = float(s.get(year, 0)), float(np.mean([s.get(year - k, 0) for k in (1, 2, 3)]))
            z = (cnt - mu) / np.sqrt(max(mu, 0.5))
            rows.append({"dong": dongs[0] if one else "제주 전체", "biz": g, "year": int(year), "count": int(cnt), "expected": round(mu, 1), "z": round(float(z), 2),
                         "flag": "많음" if z > 2 else "적음" if z < -2 else "보통 범위"})
        return {"anomaly": rows, "kind": kind_ko, "by": "업종", "note": note, "end_year": int(end.year)}
    e = ev.groupby(["dong", "year"])["count"].sum().unstack("year").fillna(0)
    mu = e[[year - 1, year - 2, year - 3]].mean(axis=1)
    z = (e[year] - mu) / np.sqrt(mu.clip(lower=0.5))
    rows = [{"dong": d, "year": int(year), "count": int(e.loc[d, year]), "expected": round(float(mu[d]), 1), "z": round(float(z[d]), 2),
             "flag": "많음" if z[d] > 2 else "적음" if z[d] < -2 else "보통 범위"} for d in chk["ok"] if d in e.index]
    return {"anomaly": rows, "kind": kind_ko, "by": "동네", "note": note, "end_year": int(end.year)}


WARM = {"R1": "대기"}


def warm():
    """서버 시작 때 R1 캐시를 미리 채운다(첫 예측 답변이 전체 답변 5초 기준을 넘지 않도록, 05 문서 17절). 캐시가 있으면 바로 끝난다."""
    t0 = time.perf_counter()
    WARM["R1"] = "학습 중"
    try:
        r = r1(None)
        WARM["R1"] = f"준비됨(cache {r['cache']}, {time.perf_counter() - t0:.1f}초)"
    except Exception as e:  # 캐시를 못 채워도 서버는 뜬다(질문 때 학습)
        WARM["R1"] = f"실패: {type(e).__name__}"
    try:  # 종합 진단이 쓰는 매출 예상 검증(43개 동네 × 5개 업종, 약 1초)도 미리 계산한다(문서 21: 수치 답 4초 안)
        import v3
        v3._r10_gate()
    except Exception:
        pass
    return WARM["R1"]


def run(rid, flt, tables=(), chk=None, metric=None):
    """S3 진입점. chk는 S2 점검 결과(없으면 여기서 점검)."""
    if rid in CENTER_ONLY:
        raise RecipeError(f"{rid}는 센터 DB 경로 전용(미연결)")
    if rid in ("R10", "R11"):  # v3 카드 매출 레시피(app/v3.py). 관문 판정은 S6
        import v3
        f = flt or {}
        dong = (f.get("dong") or [None])[0] if isinstance(f.get("dong"), list) else None
        biz, _ = v3.biz5_of(f.get("target"))
        try:
            out = v3.r10(dong, biz or "음식점업") if rid == "R10" else v3.r11(dong, biz, v3.BIZ42.get(f.get("target")))
        except ValueError as e:
            raise RecipeError(str(e))
        return {"recipe": rid, "trained": True, **out}
    chk = chk or check(rid, flt, tables)
    if not chk["pass"] and rid != "R4":
        return {"recipe": rid, "check": chk, "fallback": REG[rid]["fallback"], "trained": False}
    flt2 = dict(flt or {}, dong=chk["ok"]) if chk.get("ok") and rid not in ("R4",) and chk["ok"] != ["전체"] else flt
    if rid == "R1":
        out = r1(flt2)
    elif rid == "R2":
        t = next((x for x in tables if "ym" in x), None)
        out = r2(flt2, t)
    elif rid == "R4":
        out = r4(flt, chk)
    elif rid == "R5":
        out = r5(flt2, chk)
    elif rid == "R6":
        out = r6(flt2, chk)
    elif rid == "R7":
        out = r7(flt2, chk, "open" if metric == "개업수" else "close")
    else:
        raise RecipeError(f"레시피 {rid} 미구현")
    return {"recipe": rid, "check": chk, "trained": True, **out}


if __name__ == "__main__":
    for rid in sys.argv[1:]:
        t0 = time.perf_counter()
        r = run(rid, {"dong": ["노형동"], "target": "카페"})
        print(rid, round(time.perf_counter() - t0, 2), "s", json.dumps({k: v for k, v in r.items() if k not in ("gate_input",)}, ensure_ascii=False, default=str)[:600])
