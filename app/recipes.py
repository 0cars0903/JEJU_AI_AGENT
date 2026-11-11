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
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

REG = json.loads((Q.ROOT / "models" / "recipes.json").read_text(encoding="utf-8"))
CACHE = Q.ROOT / "models" / "cache"
REGISTRY = Q.ROOT / "models" / "registry.json"
PANEL = Q.ROOT / "data" / "interim" / "gates" / "panel_v2.parquet"
TAB = Q.ROOT / "data" / "tables"
CENTER_ONLY = {"R8", "R9"}
NO_CHECK = {"R3", "R8", "R9"}


class RecipeError(Exception):
    pass


def _fingerprint(*paths):
    return [f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}" for p in paths]


def _key(rid, fp, cfg):
    return hashlib.sha1(json.dumps([rid, fp, cfg], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def _cached(rid, fp, cfg, build):
    """캐시가 있으면 읽고, 없으면 build()로 학습해 저장하고 등록부에 기록한다."""
    k = _key(rid, fp, cfg)
    f = CACHE / f"{rid}_{k}.json"
    if f.exists():
        return dict(json.loads(f.read_text(encoding="utf-8")), cache="hit")
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
            "forecast": [{"dong": r.emd, "date": str(r.date.date()), "visit": round(float(r.visit), 1), "rain_effect_pct": None if pd.isna(r.rain_pct) else float(r.rain_pct), **{c: int(getattr(r, c)) for c in G.CAL}} for r in fu.itertuples()],
            "data_last": str(last.date())}


def r1(flt):
    spec = REG["R1"]
    cfg = {"folds": spec["validation"]["folds"], "test_days": spec["validation"]["test_days"], "horizon": spec["horizon_days"], "model": "gbm_M0+big8rain"}
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
    from tools import REST_MAP
    rest = pd.read_parquet(IN / "restaurants.parquet")
    end = rest[["open_date", "close_date"]].max().max()
    co = rest[(rest["open_date"] >= KM_START) & (rest["open_date"] <= KM_END)].copy()
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
    return {"survival": {"group": use or "음식점 전체", "n": int(len(co)), "surv5_pct": round(s5 * 100, 1), "ci95_pp": round(1.96 * se5 * 100, 1),
                         "cond_2to5_pct": round(s5 / s2 * 100, 1) if s2 > 0 else None, "space": "제주 전체(동네별 표본이 작아 업종 묶음 단위)"},
            "fallback": None if use == tgt else f"{tgt} 표본 부족 → 음식점 전체"}


# ---------- R5 동네 유사도 / R6 계절 유형 ----------
def _features():
    import model_gates as G1
    return G1.m4_features()


def r5(flt, chk):
    import model_gates as G1
    F = _features()
    nb = G1.neighbors(F)
    return {"neighbors": {d: sorted(nb[d]) for d in chk["ok"]}, "gate": REG["R5"]["pass"]}


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
    return {"season_type": {d: {"group": f"{peak[lab[d]]}월 정점형", "same_type": sorted(set(lab[lab == lab[d]].index) - {d})} for d in chk["ok"]},
            "gate": REG["R6"]["pass"]}


# ---------- R7 올해 이례 변화 ----------
def r7(flt, chk, kind="close"):
    from build_dong_tables import IN
    from tools import REST_MAP
    ev = pd.read_parquet(TAB / "rest_events.parquet")
    ev = ev[ev["kind"] == kind]
    tgt = (flt or {}).get("target")
    if tgt and REST_MAP.get(tgt):
        ev = ev[ev["category"].isin(REST_MAP[tgt])]
    end = pd.read_parquet(IN / "restaurants.parquet", columns=["open_date", "close_date"]).max().max()
    year = end.year if end.month == 12 else end.year - 1  # 관측이 끝난 해가 12월 전이면 그 해는 덜 찼다 → 마지막 완전 연도
    e = ev.groupby(["dong", "year"])["count"].sum().unstack("year").fillna(0)
    mu = e[[year - 1, year - 2, year - 3]].mean(axis=1)
    z = (e[year] - mu) / np.sqrt(mu.clip(lower=0.5))
    rows = [{"dong": d, "year": int(year), "count": int(e.loc[d, year]), "expected": round(float(mu[d]), 1), "z": round(float(z[d]), 2),
             "flag": "많음" if z[d] > 2 else "적음" if z[d] < -2 else "보통 범위"} for d in chk["ok"] if d in e.index]
    return {"anomaly": rows, "kind": "폐업" if kind == "close" else "개업", "note": f"관측 종료 {end.date()}, 마지막 완전 연도 {year}년 기준"}


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
    return WARM["R1"]


def run(rid, flt, tables=(), chk=None, metric=None):
    """S3 진입점. chk는 S2 점검 결과(없으면 여기서 점검)."""
    if rid in CENTER_ONLY:
        raise RecipeError(f"{rid}는 센터 DB 경로 전용(미연결)")
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
