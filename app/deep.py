"""단순 주제의 심화 계산 (docs/조사/22_EDA고도화_동네비교_모델심화_계획.md 4절 공통 작업, 2026-11-12 구현).

주제 하나만 골라도 관련 모델 결과와 위치를 붙인다. 숫자는 모두 여기서 계산하고, 문장은 app/layers.py가 만든다.
- series    지표 키 → 43개 동네 값(Series), 단위, 기준 시점
- position  그 동네의 43곳 중 순위·백분위 + 비슷한 동네 5곳(R5) 평균과의 차이
- decomp    카드 매출 변화 = 결제 건수 변화 × 건당 금액 변화(최근 12개월 vs 그 전 12개월)
- swing     도민·관광객 매출의 달마다 오르내림 폭(최근 36개월, 계절 포함)
- hour_vs   그 동네 시간대 비중과 제주 전체 같은 업종의 시간대 비중 차이
- spread    순위 질문의 분포(상위 5곳 집중도, 1위 ÷ 중간값)
- rain_rank 비 효과(R3)의 43곳 중 순위와 판정 등급
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v3  # noqa: E402

TAB = v3.TAB
BANDS = {"낮(11~14시)": range(11, 15), "저녁(17~21시)": range(17, 22), "밤(22~다음 날 4시)": [22, 23, 0, 1, 2, 3, 4]}


def _last12(c):
    end = c["ym"].max()
    return c[c["ym"] > v3._months_back(end, 12)], end


def series(key, target=None, names=None):
    """지표 키 → (43곳 값, 단위, 기준 시점). 지원하지 않는 지표는 None."""
    biz, _ = v3.biz5_of(target)
    if key == "일평균방문":
        return v3.dong_values("visit")
    if key in ("매출", "시장추이"):
        return v3.dong_values("sales", biz)
    if key == "점포수":
        s, u, a = v3.dong_values("stores", target=target, names=names)
        every = sorted(pd.read_parquet(TAB / "biz.parquet")["dong"].unique())
        return s.reindex(every, fill_value=0), u, a
    if key in ("5년생존율", "조건부생존"):
        return v3.dong_values("survival")
    if key in ("관광객비중", "건당금액", "이용건수", "매출증감"):
        c = v3.card()
        if biz:
            c = c[c["biz"] == biz]
        if key == "매출증감":
            end = c["ym"].max()
            cur = c[c["ym"] > v3._months_back(end, 12)].groupby("dong")["amt"].sum()
            prev = c[(c["ym"] > v3._months_back(end, 24)) & (c["ym"] <= v3._months_back(end, 12))].groupby("dong")["amt"].sum()
            return ((cur / prev - 1) * 100).replace([np.inf, -np.inf], np.nan).dropna(), "%", end
        c, end = _last12(c)
        g = c.groupby("dong")
        if key == "관광객비중":
            tour = c[c["cust"] == "내국인 관광객"].groupby("dong")["amt"].sum()
            return (tour.reindex(g["amt"].sum().index, fill_value=0) / g["amt"].sum() * 100), "%", end
        if key == "건당금액":
            return g["amt"].sum() / g["cnt"].sum(), "원", end
        return g["cnt"].sum(), "건", end
    if key in ("개업수", "폐업수"):
        import places
        e = pd.read_parquet(TAB / "rest_events.parquet")
        e = e[e["kind"] == ("open" if key == "개업수" else "close")]
        if target and target != "음식점" and places.REST_MAP.get(target):
            e = e[e["category"].isin(places.REST_MAP[target])]
        last = v3.meta().get("rest_last", "")
        full = int(last[:4]) - (0 if last.endswith("12-31") else 1)
        s = e[e["year"] == full].groupby("dong")["count"].sum()
        every = sorted(pd.read_parquet(TAB / "rest_events.parquet")["dong"].unique())
        return s.reindex(every, fill_value=0).astype(float), "곳", f"{full}년"
    if key == "시간대매출":  # 매출이 많은 상위 3개 시간대가 하루 매출에서 차지하는 비중(높을수록 몇 시간에 몰림)
        h = pd.read_parquet(TAB / "card_hour.parquet")
        if biz:
            h = h[h["biz"] == biz]
        h = h[h["ym"] > sorted(h["ym"].unique())[-13]]
        g = h.groupby(["dong", "hour"])["amt"].sum()
        top3 = g.groupby(level=0).apply(lambda x: x.nlargest(3).sum() / x.sum() * 100 if x.sum() > 0 else np.nan)
        return top3.dropna(), "%", h["ym"].max()
    return None


def position(dong, key, target=None, names=None, neighbors=None):
    """43곳 중 위치와 비슷한 동네 5곳(R5) 대비 차이. %로 된 지표는 %p 차이로 낸다."""
    got = series(key, target, names)
    if not got:
        return None
    s, unit, asof = got
    s = s.dropna()
    if dong not in s.index or len(s) < 10:
        return None
    v = float(s[dong])
    out = {"key": key, "value": v, "unit": unit, "as_of": asof, "rank": int((s > v).sum() + 1), "of": int(len(s)),
           "top_pct": round(float((s > v).sum() + 1) / len(s) * 100), "median": float(s.median())}
    nb = [d for d in (neighbors or []) if d in s.index]
    if len(nb) >= 3:
        avg = float(s[nb].mean())
        out.update(nb=nb, nb_avg=avg, nb_values={d: float(s[d]) for d in nb})
        if unit == "%":
            out["diff"], out["diff_unit"] = round(v - avg, 1), "%p"
        elif avg > 0:
            out["diff"], out["diff_unit"] = round((v / avg - 1) * 100, 1), "%"
    return out


def decomp(dong, biz5=None):
    """카드 매출 변화의 분해: (1 + 매출 변화) = (1 + 건수 변화) × (1 + 건당 금액 변화). 최근 12개월 vs 그 전 12개월."""
    c = v3.card()
    c = c[c["dong"] == dong]
    if biz5:
        c = c[c["biz"] == biz5]
    if c.empty:
        return None
    end = c["ym"].max()
    cur = c[c["ym"] > v3._months_back(end, 12)][["amt", "cnt"]].sum()
    prev = c[(c["ym"] > v3._months_back(end, 24)) & (c["ym"] <= v3._months_back(end, 12))][["amt", "cnt"]].sum()
    if prev["amt"] <= 0 or prev["cnt"] <= 0 or cur["cnt"] <= 0:
        return None
    a, n = cur["amt"] / prev["amt"], cur["cnt"] / prev["cnt"]
    k = a / n
    return {"end": end, "amt_pct": round((a - 1) * 100, 1), "cnt_pct": round((n - 1) * 100, 1), "ticket_pct": round((k - 1) * 100, 1),
            "ticket_cur": float(cur["amt"] / cur["cnt"]), "ticket_prev": float(prev["amt"] / prev["cnt"]),
            "driver": "건수" if abs(np.log(n)) >= abs(np.log(k)) else "건당 금액"}


def swing(dong, biz5=None, months=36):
    """도민·관광객 카드 매출의 달마다 오르내림 폭 = 최근 36개월 월 매출의 변동계수(표준편차 ÷ 평균). 계절 차이가 그대로 들어간다."""
    c = v3.card()
    c = c[c["dong"] == dong]
    if biz5:
        c = c[c["biz"] == biz5]
    keep = sorted(c["ym"].unique())[-months:]
    c = c[c["ym"].isin(keep)]
    out = {}
    for cust in ("도민", "내국인 관광객"):
        m = c[c["cust"] == cust].groupby("ym")["amt"].sum()
        if len(m) >= 12 and m.mean() > 0:
            out[cust] = {"cv_pct": round(float(m.std(ddof=1) / m.mean() * 100), 1), "hi_ym": str(m.idxmax()), "lo_ym": str(m.idxmin()),
                         "hi_lo": round(float(m.max() / m.min()), 1) if m.min() > 0 else None}
    if len(out) < 2:
        return None
    return {"by": out, "months": len(keep), "from": keep[0], "to": keep[-1]}


def hour_vs(dong, biz5=None):
    """시간대 묶음별 매출 비중: 그 동네 vs 제주 전체(같은 업종), 최근 12개월."""
    h = pd.read_parquet(TAB / "card_hour.parquet")
    if biz5:
        h = h[h["biz"] == biz5]
    h = h[h["ym"] > sorted(h["ym"].unique())[-13]]
    def bands(x):
        g = x.groupby("hour")["amt"].sum()
        if g.sum() <= 0:
            return None
        p = g / g.sum() * 100
        return {k: float(p.reindex(list(v)).fillna(0).sum()) for k, v in BANDS.items()}
    a, b = bands(h[h["dong"] == dong]), bands(h)
    if not a or not b:
        return None
    gap = {k: round(a[k] - b[k], 1) for k in BANDS}
    big = max(gap, key=lambda k: abs(gap[k]))
    return {"dong": a, "jeju": b, "gap": gap, "biggest": big, "from": h["ym"].min(), "to": h["ym"].max()}


def spread(values):
    """순위 질문의 분포: 상위 5곳이 합계에서 차지하는 비중, 1위 ÷ 중간값."""
    s = pd.Series(values).dropna().sort_values(ascending=False)
    if len(s) < 10 or s.sum() <= 0 or s.median() <= 0:
        return None
    return {"n": int(len(s)), "top5_pct": round(float(s.head(5).sum() / s.sum() * 100), 1), "first_vs_median": round(float(s.iloc[0] / s.median()), 1),
            "median": float(s.median())}


def rain_rank(dong):
    """비 효과(R3, 08 문서 검정 결과)의 43곳 중 순위(감소가 큰 순)와 판정 등급."""
    f = v3.ROOT / "data" / "interim" / "gates" / "rain_test.json"
    if not f.exists():
        return None
    rows = json.loads(f.read_text(encoding="utf-8"))["per_dong"]
    me = next((r for r in rows if r["dong"] == dong), None)
    if not me:
        return None
    eff = sorted(rows, key=lambda r: r["effect_pct"])
    return {"rank": [r["dong"] for r in eff].index(dong) + 1, "of": len(rows), "effect_pct": round(me["effect_pct"], 1),
            "n_sig": sum(bool(r["diff_sig"]) for r in rows), "sig": bool(me["diff_sig"]), "class": me["class"]}
