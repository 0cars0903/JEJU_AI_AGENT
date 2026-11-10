"""S6 통계 검정 Sub (docs/기획/05_Agent구조_v2.md 15-5절, 2026-11-11 구현).

수치가 '주장'이 되기 전에 판정한다. 정책 값은 바꿀 수 없다(코드 상수). S2의 결과 주장(T6·T7·T15)과 S3 레시피 관문이 같은 규칙을 쓴다.
판정 등급
  - 작음 확인: 동등성 검정(TOST)으로 |효과| < δ, 그리고 0과 차이 없음
  - 작지만 0은 아님: |효과| < δ, 0과 차이 있음
  - 효과 있음: 0과 차이 있음, δ 안이라고 보일 수 없음
  - 판단 불가: 둘 다 보일 수 없음(구간이 넓음)
출력 형식: {"claim", "test", "p", "p_tost", "ci95", "correction", "n"} — 결과 생성 Agent는 claim 문구만 쓴다.
근거 코드: app/rain_test.py(가설 검정 08 문서), app/model_gates_v2.py(짝 비교).
"""
from math import comb

import numpy as np
from scipy import stats

ALPHA = 0.05      # 유의수준
DELTA = 0.10      # 동등성 범위 ±10%(비율 효과)
FDR = "BH"        # 다중 비교 보정(Benjamini-Hochberg)


def bh(pvals, q=ALPHA):
    """BH 보정: 기각되는 위치의 불리언 배열."""
    p = np.asarray(pvals, float)
    n = len(p)
    order = np.argsort(p)
    thr = q * (np.arange(1, n + 1) / n)
    passed = p[order] <= thr
    k = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(n, bool)
    out[order[:k]] = True
    return out


def ratio_effect(beta, se, dof):
    """로그 회귀계수 β와 표준오차 → 비율 효과의 차이 검정 p와 TOST p, 95% 구간(%)."""
    p0 = float(2 * stats.t.sf(abs(beta / se), dof))
    lo, hi = np.log(1 - DELTA), np.log(1 + DELTA)
    p_tost = float(max(stats.t.sf((beta - lo) / se, dof), stats.t.cdf((beta - hi) / se, dof)))
    ci = [float((np.exp(beta - 1.96 * se) - 1) * 100), float((np.exp(beta + 1.96 * se) - 1) * 100)]
    return p0, p_tost, ci


def claim(diff_sig, equiv_sig):
    if equiv_sig and not diff_sig:
        return "작음 확인"
    if equiv_sig and diff_sig:
        return "작지만 0은 아님"
    if diff_sig:
        return "효과 있음"
    return "판단 불가"


def judge_effects(rows):
    """rows: [{"name", "beta", "se", "dof"}...] → 이름별 판정(BH 보정 포함)."""
    res = [dict(r, **dict(zip(["p", "p_tost", "ci95"], ratio_effect(r["beta"], r["se"], r["dof"])))) for r in rows]
    d = bh([r["p"] for r in res])
    e = bh([r["p_tost"] for r in res])
    for r, ds, es in zip(res, d, e):
        r.update(claim=claim(bool(ds), bool(es)), test="차이 검정 + TOST(±10%)", correction=FDR, effect_pct=float((np.exp(r["beta"]) - 1) * 100))
    return res


def paired(err_a, err_b):
    """같은 단위(동네 × 회차 등)의 오차 짝 비교: a가 나은 칸 수, 부호 검정 p, Wilcoxon p. 관문(S3)의 '기준선보다 낫다' 판정에 쓴다."""
    a, b = np.asarray(err_a, float), np.asarray(err_b, float)
    better, ties = int((a < b).sum()), int((a == b).sum())
    n = len(a) - ties
    p_sign = float(stats.binomtest(better, n, 0.5).pvalue) if n else 1.0
    p_w = float(stats.wilcoxon(a, b).pvalue) if n else 1.0
    return {"better": better, "n": n, "p_sign": p_sign, "p_wilcoxon": p_w, "pass": better > n / 2 and p_sign < ALPHA}


def mcnemar(ok_a, ok_b):
    """정답·오답 짝 비교(질의 해석 실험 등): 정확 이항 검정."""
    n10 = sum(x and not y for x, y in zip(ok_a, ok_b))
    n01 = sum(y and not x for x, y in zip(ok_a, ok_b))
    n = n10 + n01
    p = 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(n10, n01) + 1)) / 2 ** n)
    return {"a_only": n10, "b_only": n01, "p": p}


def gate(model_err, baseline_err, mase):
    """S3 레시피 관문: MASE < 1 그리고 기준선과 짝 비교에서 유의하게 나음."""
    pr = paired(model_err, baseline_err)
    return {"mase": float(mase), **pr, "pass": bool(mase < 1 and pr["pass"])}
