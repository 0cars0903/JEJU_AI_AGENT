"""EDA와 표준 테이블이 함께 쓰는 통계 함수. scipy 없이 numpy·pandas만 쓴다."""
from math import erfc, sqrt

import numpy as np
import pandas as pd


def km_at(dur, event, t):
    """Kaplan–Meier: 시점 t의 생존 확률, Greenwood 표준오차, 표본 수."""
    order = np.argsort(dur)
    dur, event = dur[order], event[order]
    s, g = 1.0, 0.0
    for u in np.unique(dur[event & (dur <= t)]):
        at_risk = (dur >= u).sum()
        d = ((dur == u) & event).sum()
        s *= 1 - d / at_risk
        if at_risk > d:
            g += d / (at_risk * (at_risk - d))
    return s, s * np.sqrt(g), len(dur)


def loglog_ci(s, se, z=1.96):
    """생존율 95% 구간(log-log 변환). 구간이 0~1을 벗어나지 않는다."""
    if s <= 0 or s >= 1 or se == 0:
        return s, s
    h = z * se / (s * abs(np.log(s)))
    return s ** np.exp(h), s ** np.exp(-h)


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def spearman(a, b):
    d = pd.concat([a, b], axis=1).dropna()
    return round(d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank()), 3)


def two_sided_p(z):
    return erfc(abs(z) / sqrt(2))


def bh(p, q):
    """Benjamini–Hochberg: q에서 유의한 항목의 색인 목록."""
    p = p.dropna().sort_values()
    m = len(p)
    ok = p.values <= q * np.arange(1, m + 1) / m
    return list(p.index[:np.where(ok)[0].max() + 1]) if ok.any() else []


def effect(df, value, name, flag):
    """강수일 효과. 동네별로 연월 × 요일 칸 안에서 로그값과 강수 여부를 평균 차감한 뒤 회귀한다.
    강수일·무강수일이 함께 있는 칸만 추정에 기여한다(이중 검토 006)."""
    d = df[df["date"].isin(flag.index)].copy()
    d = d[d[value] > 0]
    d["w"] = d["date"].map(flag).astype(float)
    d["lv"] = np.log(d[value])
    d["ym"] = d["date"].dt.to_period("M").astype(str)
    d["dow"] = d["date"].dt.dayofweek
    out = {}
    for dong, g in d.groupby("dong"):
        k = g.groupby(["ym", "dow"])
        y, x = g["lv"] - k["lv"].transform("mean"), g["w"] - k["w"].transform("mean")
        sxx = (x ** 2).sum()
        dof = len(g) - k.ngroups - 1
        if sxx == 0 or dof <= 0:
            continue
        beta = (x * y).sum() / sxx
        se = np.sqrt(((y - beta * x) ** 2).sum() / dof / sxx)
        out[dong] = (np.exp(beta), np.exp(beta - 1.96 * se), np.exp(beta + 1.96 * se))
    return pd.DataFrame.from_dict(out, orient="index", columns=[f"{name}_비", f"{name}_하한", f"{name}_상한"])
