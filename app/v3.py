"""v3 상권 EDA 계산 (docs/기획/v3_설계.md 2·4·6절, 2026-11-11 구현).

- market     F3 업종 시장 추이: 수요(카드 매출)·공급(가게 수)·손님 구성·성장 기여 동네·두 자료 지수(겹치는 17개월 평균 = 100)
- biz_compare F4 같은 동네의 업종 간 비교(매출은 대분류 5개끼리만)
- rising     뜨는 동네·업종: 최근 12개월 매출이 중간값 이상인 동네 × 업종 조합만 증가율 순위(증가액 함께)
- signals    F2 판단 재료: 수요·경쟁·생존을 43개 동네 중 위치로(위 25% '많음/높음', 아래 25% '적음/낮음')
- r10        업종 월 매출 예상(관문: 같은 달 작년 값 기준선보다 정확해야 사용)
- r11        746 "그때로 돌아가 예상해 보기"(2017~2018로 2019년을 예상하고 실제와 비교)
- money/fmt  금액 표시(억·만 원). 표시값은 코드가 만든 값이라 수치 대조 허용 목록에 넣는다(result.py).
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "data" / "tables"
BIZ5 = ["소매업", "숙박업", "음식점업", "기타서비스업", "예술스포츠여가업"]
KTO = "제주관광공사 카드 소비"
SRC746 = "허브 746 카드 매출(비씨카드)"
OVERLAP = ("2020-01", "2021-05")
MAJOR = {"소매업": "소매", "숙박업": "숙박", "음식점업": "음식", "예술스포츠여가업": "예술·스포츠"}  # 793 상가 대분류
CROSS_FAIL = {"숙박업": "숙박업 도민 계열은 746과의 대조 기준에 미달해(문서 17) 두 자료를 이어 보지 않는 것이 좋습니다."}


FOOD = {"카페", "한식", "일식", "횟집", "중식", "치킨", "분식", "주점", "음식점"}
BIZ_UP = {"숙박": "숙박업", "소매": "소매업", "편의점": "소매업"}
BIZ42 = {"카페": "비알콜 음료점업", "한식": "한식 음식점업", "일식": "일식 음식점업", "중식": "중식 음식점업", "치킨": "피자, 햄버거", "주점": "주점업"}


def biz5_of(tgt):
    """질문 업종 → (관광공사 대분류, 한계 문구 또는 None). 대응이 없으면 (None, None)."""
    if not tgt:
        return None, None
    if tgt in BIZ5:
        return tgt, None
    up = BIZ_UP.get(tgt) or ("음식점업" if tgt in FOOD else None)
    if up is None:
        return None, None
    if tgt in ("음식점", "숙박", "소매"):
        return up, None
    return up, f"카드 매출은 업종 대분류만 있어 {tgt} 대신 {up} 전체 기준입니다. {tgt}만의 최신 매출은 센터 1-08 자료로 볼 수 있습니다."


# ---------- 표시 ----------
def money(v):
    """원 → '105억 원'·'2.8만 원'. (문장, 표시한 숫자) 반환."""
    v = float(v)
    a = abs(v)
    if a >= 1e10:
        n = round(v / 1e8)
        return f"{n:,}억 원", float(n)
    if a >= 1e8:
        n = round(v / 1e8, 1)
        return f"{n:,}억 원", n
    if a >= 1e4:
        n = round(v / 1e4, 1) if a < 1e5 else round(v / 1e4)
        return f"{n:,}만 원", float(n)
    return f"{round(v):,}원", float(round(v))


def fmt(v, unit):
    """값 + 단위 → (문장, 표시한 숫자)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-", None
    v = float(v)
    if unit == "원":
        return money(v)
    if unit in ("%", "%p"):
        n = round(v, 1)
        return f"{n:,}{unit}", n
    if unit in ("지수", "곳", "건", "명/일", "곳/년"):
        n = round(v) if abs(v) >= 100 else round(v, 1)
        n = int(n) if float(n) == int(n) else n
        return f"{n:,} {unit}", float(n)
    n = round(v, 2)
    return f"{n:,} {unit or ''}".strip(), n


# ---------- 공통 자료 ----------
def meta():
    return json.loads((TAB / "meta.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def card():
    return pd.read_parquet(TAB / "card_month.parquet")


@lru_cache(maxsize=1)
def card746():
    c = pd.read_parquet(TAB / "card746_month.parquet")
    return c[c["cust"].isin(["도민", "내국인 관광객"])]  # 관광공사 A와 같은 손님 범위


def _months_back(ym, k):
    p = pd.Period(ym, "M") - k
    return str(p)


def last12(series):
    """월 계열(index=ym) → (최근 12개월 합, 그 전 12개월 합, 끝 월)."""
    s = series.sort_index()
    end = s.index.max()
    cur = s[(s.index > _months_back(end, 12)) & (s.index <= end)].sum()
    prev = s[(s.index > _months_back(end, 24)) & (s.index <= _months_back(end, 12))].sum()
    return float(cur), float(prev), end


def yoy_test(series, log=True):
    """최근 12개월 각 달의 작년 같은 달 대비 변화(로그 비 또는 차) 평균과 t 검정. 계절을 빼고 추세를 본다."""
    s = series.sort_index()
    end = s.index.max()
    d = []
    for k in range(12):
        m, m0 = _months_back(end, k), _months_back(end, k + 12)
        if m in s.index and m0 in s.index and s[m] > 0 and s[m0] > 0:
            d.append(np.log(s[m] / s[m0]) if log else s[m] - s[m0])
    if len(d) < 6:
        return None
    d = np.array(d)
    mean, se = float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d)))
    p = float(2 * stats.t.sf(abs(mean / se), len(d) - 1)) if se > 0 else 0.0
    return {"mean": mean, "se": se, "dof": len(d) - 1, "p": p, "n": len(d), "pct": (float(np.exp(mean) - 1) * 100 if log else mean)}


def claim(test, unit_word="늘었", down_word="줄었"):
    """검정 → (층 꼬리표, 문장 꼬리). 유의수준 0.05."""
    if not test:
        return "구분 못 함", "자료가 짧아 판정하지 못했습니다"
    if test["p"] < 0.05:
        return "자료로 확인됨", f"{unit_word}습니다" if test["mean"] > 0 else f"{down_word}습니다"
    return "구분 못 함", "늘었는지 줄었는지 자료로 구분할 수 없습니다"


# ---------- F3 업종 시장 추이 ----------
def market(biz=None, dongs=None):
    c = card()
    if biz:
        c = c[c["biz"] == biz]
    if dongs:
        c = c[c["dong"].isin(dongs)]
    where = "·".join(dongs) if dongs else "제주 전체"
    s = c.groupby("ym")["amt"].sum()
    cur, prev, end = last12(s)
    test = yoy_test(s)
    # 746 장기 선(지수): 겹치는 17개월 평균 = 100
    b = card746()
    b = b[b["biz_certain"]] if biz else b
    if biz:
        b = b[b["biz"] == biz]
    if dongs:
        b = b[b["dong"].isin(dongs)]
    s746 = b.groupby("ym")["amt"].sum()
    lo, hi = OVERLAP
    idx = []
    for name, ser in ((KTO, s), (SRC746, s746)):
        base = ser[(ser.index >= lo) & (ser.index <= hi)].mean()
        if base and base > 0:
            idx += [{"ym": k, "source": name, "value": round(float(v / base * 100), 1)} for k, v in ser.items()]
    # 손님 구성 추이(연도별 관광객 비중)
    cy = c.assign(year=c["ym"].str[:4]).groupby(["year", "cust"])["amt"].sum().unstack("cust").fillna(0)
    share = (cy.get("내국인 관광객", 0) / cy.sum(axis=1) * 100).round(1)
    # 성장 기여 동네(제주 전체일 때)
    contrib = []
    if not dongs:
        endm = end
        cd = c[(c["ym"] > _months_back(endm, 12))].groupby("dong")["amt"].sum() - c[(c["ym"] > _months_back(endm, 24)) & (c["ym"] <= _months_back(endm, 12))].groupby("dong")["amt"].sum()
        contrib = [{"dong": k, "value": float(v)} for k, v in cd.sort_values(ascending=False).head(5).items()]
    # 공급: 음식점은 영업 중 가게 수를 개업·폐업 누적으로 다시 센다
    supply = None
    if biz == "음식점업":
        e = pd.read_parquet(TAB / "rest_events.parquet")
        if dongs:
            e = e[e["dong"].isin(dongs)]
        g = e.groupby(["year", "kind"])["count"].sum().unstack("kind").fillna(0).sort_index()
        op = (g.get("open", 0).cumsum() - g.get("close", 0).cumsum())
        op = op[op.index >= 2019]
        supply = [{"year": int(k), "value": float(v)} for k, v in op.items()]
    # 외국인(제주 전체, 출신지역)
    f = pd.read_parquet(TAB / "card_foreign.parquet")
    if biz:
        f = f[f["biz"] == biz]
    fend = f["ym"].max()
    fo = f[f["ym"] > _months_back(fend, 12)].groupby("origin")["amt"].sum().sort_values(ascending=False)
    return {"where": where, "biz": biz or "전 업종", "series": s, "cur": cur, "prev": prev, "end": end, "test": test, "index": idx,
            "share_by_year": share.to_dict(), "contrib": contrib, "supply": supply,
            "foreign": [{"origin": k, "value": float(v)} for k, v in fo.items()], "foreign_end": fend, "note": CROSS_FAIL.get(biz)}


# ---------- F4 업종 간 비교 ----------
def biz_compare(dong):
    c = card()
    c = c[c["dong"] == dong]
    end = c["ym"].max()
    rows = []
    b = pd.read_parquet(TAB / "biz.parquet")
    b = b[b["dong"] == dong].groupby("major")["count"].sum()
    for biz in BIZ5:
        s = c[c["biz"] == biz].groupby("ym")["amt"].sum()
        if s.empty:
            continue
        cur, prev, _ = last12(s)
        sh = c[(c["biz"] == biz) & (c["ym"] > _months_back(end, 12))].groupby("cust")["amt"].sum()
        rows.append({"biz": biz, "cur": cur, "growth_pct": (cur / prev - 1) * 100 if prev > 0 else None,
                     "tourist_pct": float(sh.get("내국인 관광객", 0) / sh.sum() * 100) if sh.sum() > 0 else None,
                     "stores": int(b.get(MAJOR.get(biz), 0)) if MAJOR.get(biz) else None})
    return {"dong": dong, "end": end, "rows": sorted(rows, key=lambda r: -r["cur"])}


# ---------- 뜨는 동네·업종 ----------
def rising(biz=None, n=10):
    c = card()
    end = c["ym"].max()
    cur = c[c["ym"] > _months_back(end, 12)].groupby(["dong", "biz"])["amt"].sum()
    prev = c[(c["ym"] > _months_back(end, 24)) & (c["ym"] <= _months_back(end, 12))].groupby(["dong", "biz"])["amt"].sum()
    d = pd.concat([cur, prev], axis=1, keys=["cur", "prev"]).dropna()
    med = float(d["cur"].median())
    d = d[d["cur"] >= med]  # 규모가 작은 조합은 결제 몇 건으로 증가율이 크게 뛴다(031)
    if biz:
        d = d[d.index.get_level_values("biz") == biz]
    d["growth_pct"] = (d["cur"] / d["prev"] - 1) * 100
    d["gain"] = d["cur"] - d["prev"]
    d = d.sort_values("growth_pct", ascending=False).head(n).reset_index()
    return {"end": end, "median": med, "rows": d.to_dict(orient="records"), "combos": int(len(cur))}


# ---------- F2 판단 재료 ----------
def _pos(series, dong):
    s = series.dropna()
    if dong not in s.index or len(s) < 10:
        return None
    pct = float((s < s[dong]).mean() * 100)  # 이 동네보다 작은 동네의 비율
    level = "많음" if pct >= 75 else "적음" if pct < 25 else "보통"
    return {"value": float(s[dong]), "pct": round(pct), "rank": int((s > s[dong]).sum() + 1), "of": int(len(s)), "level": level}


def signals(dong, target=None, biz5=None):
    out = []
    p = pd.read_parquet(TAB / "pop_month.parquet")
    pm = p[p["ym"] > _months_back(p["ym"].max(), 12)]
    visit = (pm.groupby("dong")["visit"].sum() / pm.groupby("dong")["days"].sum())
    v = _pos(visit, dong)
    if v:
        out.append({"kind": "수요", "short": "방문", "name": "하루 평균 방문 인구", "source": "583 유동인구(제주데이터허브)", "as_of": p["ym"].max(), "unit": "지수", **v})
    c = card()
    if biz5:
        c = c[c["biz"] == biz5]
    cm = c[c["ym"] > _months_back(c["ym"].max(), 12)].groupby("dong")["amt"].sum()
    v = _pos(cm, dong)
    if v:
        out.append({"kind": "수요", "short": "매출", "name": f"{biz5 or '전 업종'} 카드 매출(최근 12개월)", "source": KTO, "as_of": c["ym"].max(), "unit": "원", **v})
    b = pd.read_parquet(TAB / "biz.parquet")
    if target:
        b = b[b["minor"].str.contains(target, na=False) | b["middle"].str.contains(target, na=False) | b["major"].str.contains(target, na=False)]
    v = _pos(b.groupby("dong")["count"].sum(), dong)
    if v:
        out.append({"kind": "경쟁", "short": "가게 수(경쟁)", "name": f"{target or '전 업종'} 가게 수", "source": "793 상가(상권) 정보", "as_of": "최신 단면", "unit": "곳", **v})
    k = pd.read_parquet(TAB / "km.parquet")
    dongs = json.loads((TAB / "meta.json").read_text(encoding="utf-8"))["dongs"]
    k5 = k[(k["year"] == 5) & k["dong"].isin(dongs)].set_index("dong")["survival_pct"]
    v = _pos(k5, dong)
    if v:
        v["level"] = {"많음": "높음", "적음": "낮음", "보통": "보통"}[v["level"]]
        out.append({"kind": "생존", "short": "생존율", "name": "음식점 5년 생존율(업종 구분 없음)", "source": "780 음식점 인허가", "as_of": f"개업 {meta().get('km_cohort', '2015-01~2020-08')}", "unit": "%", **v})
    return {"dong": dong, "rule": "43개 동네 가운데 위치: 위 25% 안이면 '많음·높음', 아래 25%면 '적음·낮음', 그 사이는 '보통'", "items": out}


# ---------- R10 업종 월 매출 예상 ----------
def _model_pred(s, m):
    """작년 같은 달 × 최근 3개월의 작년 대비 비율(계절 단순 + 추세 보정)."""
    m12 = _months_back(m, 12)
    if m12 not in s.index:
        return None
    r = []
    for k in (1, 2, 3):
        a, a0 = _months_back(m, k), _months_back(m, k + 12)
        if a in s.index and a0 in s.index and s[a0] > 0:
            r.append(s[a] / s[a0])
    return float(s[m12] * np.median(r)) if r else None


@lru_cache(maxsize=1)
def _r10_gate():
    c = card()
    piv = c.groupby(["ym", "dong", "biz"])["amt"].sum().unstack(["dong", "biz"]).sort_index()
    months = list(piv.index)
    origins = months[-12:]  # 최근 12개월 이동 원점
    em, eb, logerr = [], [], []
    for m in origins:
        y = piv.loc[m]
        for col in piv.columns:
            s = piv[col].loc[:_months_back(m, 1)].dropna()
            s = pd.concat([s, pd.Series({m: y[col]})])
            if not (y[col] > 0):
                continue
            pm = _model_pred(s, m)
            pb = s.get(_months_back(m, 12))
            if pm and pb and pm > 0 and pb > 0:
                em.append(abs(np.log(y[col] / pm)))
                eb.append(abs(np.log(y[col] / pb)))
                logerr.append(np.log(y[col] / pm))
    q10, q90 = np.quantile(logerr, [0.1, 0.9])
    return {"model_err": em, "baseline_err": eb, "mase": round(float(np.mean(em) / np.mean(eb)), 4), "q10": float(q10), "q90": float(q90), "n": len(em)}


def r10(dong, biz):
    g = _r10_gate()
    c = card()
    s = c[(c["dong"] == dong) & (c["biz"] == biz)].groupby("ym")["amt"].sum().sort_index()
    if len(s) < 15:
        raise ValueError("월 자료가 15개월보다 짧음")
    nxt = _months_back(s.index.max(), -1)
    pm = _model_pred(s, nxt)
    ref = _months_back(nxt, 12)
    val = []  # 이 동네·업종의 최근 12개월 검증 기록: 그 달을 예상한 값(모델) · 작년 같은 달 값(기준선) · 실제
    for m in list(s.index)[-12:]:
        past = s.loc[:_months_back(m, 1)]
        mp = _model_pred(pd.concat([past, pd.Series({m: s[m]})]), m)
        b0 = s.get(_months_back(m, 12))
        if mp and b0:
            val.append({"ym": m, "model": round(mp), "baseline": round(float(b0)), "actual": round(float(s[m]))})
    closer = sum(1 for r in val if abs(r["model"] - r["actual"]) < abs(r["baseline"] - r["actual"]))
    fc = [{"dong": dong, "ym": nxt, "value": round(pm), "lo": round(pm * np.exp(g["q10"])), "hi": round(pm * np.exp(g["q90"]))}] if pm else []
    return {"gate_input": {"model_err": g["model_err"], "baseline_err": g["baseline_err"], "mase": g["mase"]}, "forecast": fc,
            "interval": "80% 구간(최근 12개월 이동 원점 오차의 10~90% 분위)", "data_last": s.index.max(), "biz": biz,
            "reference": {"dong": dong, "biz": biz, "next": nxt, "ref_ym": ref, "value": float(s[ref]) if ref in s.index else None},
            "validation": val, "closer": closer}


# ---------- R11 746 그때로 돌아가 예상해 보기 ----------
def r11(dong=None, biz=None, biz42=None):
    """2017~2018년 자료만으로 2019년 12개월을 예상하고 실제와 비교한다. 관문은 전체 동네 × 대분류 3개 계열에서 본다."""
    b = card746()
    b = b[b["biz_certain"]]
    piv = b.groupby(["ym", "dong", "biz"])["amt"].sum().unstack(["dong", "biz"]).sort_index()
    em, eb, logerr = [], [], []
    for m in [f"2019-{i:02d}" for i in range(1, 13)]:
        for col in piv.columns:
            s = piv[col].loc[:"2018-12"].dropna()
            y = piv[col].get(m)
            if not (y and y > 0):
                continue
            # 예측 시점은 2018-12로 고정: 작년 같은 달 × (2018년 하반기 / 2017년 하반기) 비율
            h1, h0 = s.loc["2018-07":"2018-12"].sum(), s.loc["2017-07":"2017-12"].sum()
            base = s.get(_months_back(m, 12))
            if not (base and base > 0 and h0 > 0):
                continue
            pm = base * h1 / h0
            if not pm > 0:
                continue
            em.append(abs(np.log(y / pm)))
            eb.append(abs(np.log(y / base)))
            logerr.append(np.log(y / pm))
    q10, q90 = np.quantile(logerr, [0.1, 0.9])
    sel = b
    if dong:
        sel = sel[sel["dong"] == dong]
    if biz42:
        sel = sel[sel["biz42"].str.contains(biz42, na=False)]
    elif biz:
        sel = sel[sel["biz"] == biz]
    s = sel.groupby("ym")["amt"].sum().sort_index()
    rows = []
    h1, h0 = s.loc["2018-07":"2018-12"].sum(), s.loc["2017-07":"2017-12"].sum()
    for m in [f"2019-{i:02d}" for i in range(1, 13)]:
        base = s.get(_months_back(m, 12))
        if base and h0 > 0:
            pm = base * h1 / h0
            rows.append({"ym": m, "pred": round(pm), "lo": round(pm * np.exp(q10)), "hi": round(pm * np.exp(q90)), "actual": round(float(s.get(m, np.nan))) if m in s.index else None})
    inside = sum(1 for r in rows if r["actual"] is not None and r["lo"] <= r["actual"] <= r["hi"])
    return {"gate_input": {"model_err": em, "baseline_err": eb, "mase": round(float(np.mean(em) / np.mean(eb)), 4)}, "replay": rows,
            "inside": inside, "months": len(rows), "interval": "80% 구간(2019년 전체 동네·업종 오차의 10~90% 분위)",
            "what": f"{dong or '제주 전체'} {biz42 or biz or '3개 업종'}"}


if __name__ == "__main__":
    import sys
    print(json.dumps({k: v for k, v in market("음식점업").items() if k not in ("series", "index")}, ensure_ascii=False, default=str)[:900])
    print(biz_compare("노형동"))
    print({k: v for k, v in rising().items() if k != "rows"}, rising()["rows"][:3])
    print(signals("노형동", "카페", "음식점업"))
    g = _r10_gate()
    print("R10 mase", g["mase"], g["n"])
    r = r11("노형동", biz42="비알콜 음료점업")
    print("R11 mase", r["gate_input"]["mase"], r["inside"], "/", r["months"], r["replay"][:2])
