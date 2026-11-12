"""동네 비교 (docs/조사/22_EDA고도화_동네비교_모델심화_계획.md 3절, 2026-11-12 구현).

두 동네의 종합 진단 지표를 수요·매출 흐름·경쟁·생존·앞으로 5절 표로 나란히 놓는다. 어느 쪽이 낫다는 판단은 하지 않는다.
- 차이 판정(이중 검토 035 반영): 방문은 주 단위 평균을 짝 지은 Wilcoxon(날짜끼리 비슷해 일 단위는 p가 지나치게 작다),
  월 지표 4개는 같은 달 짝 Wilcoxon + Holm 보정, 생존율은 95% 구간에서 표준오차를 되살린 2표본 Z 검정,
  방문 예상은 7일 평균의 로그 차이를 검증 오차 폭으로 판정, 가게 수는 검정 없이 43곳 중 순위.
- 열: 동네 A · 동네 B · 제주 43곳 중간값.
진입점: table(dongs, target)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deep  # noqa: E402
import v3  # noqa: E402

PANEL = next((p for p in (v3.ROOT / "data" / "tables" / "panel_v2.parquet", v3.ROOT / "data" / "interim" / "gates" / "panel_v2.parquet") if p.exists()),
             v3.ROOT / "data" / "tables" / "panel_v2.parquet")  # 제출본 사본 먼저(2026-11-13)
ALPHA = 0.05
SAME, DIFF, RANK = "차이 확인 안 됨", "차이 있음", "순위로만 비교"


def _wilcoxon(a, b):
    """짝 지은 두 계열(같은 날짜·달)의 Wilcoxon 부호순위 검정. (p, 짝 수). 짝이 6개 미만이거나 차이가 모두 0이면 p=None."""
    d = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(d) < 6 or (d.iloc[:, 0] - d.iloc[:, 1]).abs().sum() == 0:
        return None, len(d)
    return float(stats.wilcoxon(d.iloc[:, 0], d.iloc[:, 1]).pvalue), len(d)


def _holm(rows):
    """여러 지표를 함께 판정할 때의 Holm 보정: p가 작은 순으로 0.05/k, 0.05/(k−1) … 와 견주고, 한 번 넘으면 그 뒤는 모두 '차이 확인 안 됨'."""
    k, stop = len(rows), False
    for i, r in enumerate(sorted((r for r in rows if r.get("p") is not None), key=lambda r: r["p"])):
        stop = stop or r["p"] >= ALPHA / (k - i)
        r["verdict"] = SAME if stop else DIFF
    for r in rows:
        if r.get("p") is None:
            r["verdict"] = SAME
        r["method"] += f", {k}개 지표 함께 보정(Holm)"


def _verdict(p):
    return SAME if p is None or p >= ALPHA else DIFF


def _row(label, unit, a, b, med, verdict, method, p=None, n=None, ranks=None):
    r = {"label": label, "unit": unit, "values": [a, b], "median": med, "verdict": verdict, "method": method}
    if p is not None:
        r["p"] = round(p, 4)
    if n is not None:
        r["n"] = int(n)
    if ranks:
        r["ranks"] = ranks
    r["texts"] = [v3.fmt(x, unit)[0] if x is not None and x == x else "자료 없음" for x in (a, b, med)]
    return r


def _card_monthly(biz):
    c = v3.card()
    if biz:
        c = c[c["biz"] == biz]
    return c


def table(dongs, target=None):
    a, b = dongs[:2]
    biz, _ = v3.biz5_of(target)
    rest = not target or target in v3.FOOD
    sections = []

    # 1. 수요: 하루 방문(최근 365일, 같은 날짜 짝) · 카드 매출(최근 12개월, 같은 달 짝)
    d = pd.read_parquet(PANEL, columns=["date", "emd", "visit"])
    d = d[d["date"] > d["date"].max() - pd.Timedelta(days=365)]
    pv = d.pivot_table(index="date", columns="emd", values="visit")
    rows = []
    if a in pv and b in pv:
        wk = pv[[a, b]].resample("W-MON").mean().dropna()
        p, n = _wilcoxon(wk[a], wk[b])
        gap = (pv[a].mean() / pv[b].mean() - 1) * 100
        rows.append(_row("하루 평균 방문(최근 365일)", "지수", float(pv[a].mean()), float(pv[b].mean()), float(pv.mean().median()), _verdict(p),
                         f"주 평균끼리 짝 지은 Wilcoxon 검정({n}주), {a} 값이 {b}보다 {abs(gap):.1f}% {'많음' if gap > 0 else '적음'}", p, n))
    c = _card_monthly(biz)
    end = c["ym"].max()
    c12 = c[c["ym"] > v3._months_back(end, 12)]
    m = c12.groupby(["ym", "dong"])["amt"].sum().unstack()
    if a in m and b in m:
        p, n = _wilcoxon(m[a], m[b])
        rows.append(_row(f"{biz or '전 업종'} 카드 매출(최근 12개월 합계)", "원", float(m[a].sum()), float(m[b].sum()), float(m.sum().median()), _verdict(p),
                         "같은 달끼리 짝 지은 Wilcoxon 검정(12개월)", p, n))
    sections.append({"id": "demand", "title": "수요", "rows": rows})

    # 2. 매출 흐름: 작년 같은 달 대비 증감률 · 관광객 비중 · 결제 1건당 금액(최근 12개월, 같은 달 짝)
    rows = []
    allm = c.groupby(["ym", "dong"])["amt"].sum().unstack().sort_index()
    yoy = (allm / allm.shift(12) - 1) * 100
    yoy = yoy[yoy.index > v3._months_back(end, 12)]
    if a in yoy and b in yoy:
        p, n = _wilcoxon(yoy[a], yoy[b])
        rows.append(_row("매출 증감률(달마다 작년 같은 달 대비, 최근 12개월 평균)", "%", float(yoy[a].mean()), float(yoy[b].mean()), float(yoy.mean().median()),
                         _verdict(p), "같은 달끼리 짝 지은 Wilcoxon 검정(12개월)", p, n))
    tour = c12[c12["cust"] == "내국인 관광객"].groupby(["ym", "dong"])["amt"].sum().unstack()
    share = (tour / m * 100)
    if a in share and b in share:
        p, n = _wilcoxon(share[a], share[b])
        tot = c12.groupby("dong")["amt"].sum()
        sh12 = c12[c12["cust"] == "내국인 관광객"].groupby("dong")["amt"].sum() / tot * 100
        rows.append(_row("관광객 매출 비중(최근 12개월)", "%", float(sh12.get(a, np.nan)), float(sh12.get(b, np.nan)), float(sh12.median()), _verdict(p),
                         "같은 달끼리 짝 지은 Wilcoxon 검정(12개월)", p, n))
    cnt = c12.groupby(["ym", "dong"])["cnt"].sum().unstack()
    tk = m / cnt
    if a in tk and b in tk:
        p, n = _wilcoxon(tk[a], tk[b])
        g = c12.groupby("dong")[["amt", "cnt"]].sum()
        t12 = g["amt"] / g["cnt"]
        rows.append(_row("결제 1건당 금액(최근 12개월)", "원", float(t12.get(a, np.nan)), float(t12.get(b, np.nan)), float(t12.median()), _verdict(p),
                         "같은 달끼리 짝 지은 Wilcoxon 검정(12개월)", p, n))
    sections.append({"id": "sales", "title": "매출 흐름", "rows": rows})
    _holm([r for s in sections for r in s["rows"] if "Wilcoxon 검정(12개월)" in r["method"]])

    # 3. 경쟁: 가게 수 · 방문 1만 지수당 가게 수(한 시점 값이라 검정 없이 순위)
    rows = []
    s, unit, _ = deep.series("점포수", target)
    if a in s and b in s:
        rk = [int((s > s[x]).sum() + 1) for x in (a, b)]
        rows.append(_row(f"{target or '전 업종'} 가게 수", "곳", float(s[a]), float(s[b]), float(s.median()), RANK, f"{len(s)}곳 중 순위(한 시점 값이라 검정하지 않음)", ranks=rk))
        visit, _, _ = v3.dong_values("visit")
        dens = (s / (visit.reindex(s.index) / 1e4)).dropna()
        if a in dens and b in dens:
            rk = [int((dens > dens[x]).sum() + 1) for x in (a, b)]
            rows.append(_row(f"하루 방문 1만 지수당 {target or '전 업종'} 가게 수", "곳", float(dens[a]), float(dens[b]), float(dens.median()), RANK,
                             f"{len(dens)}곳 중 순위(한 시점 값이라 검정하지 않음)", ranks=rk))
    sections.append({"id": "compete", "title": "경쟁", "rows": rows})

    # 4. 생존: 동네별 음식점(업종 구분 없음) 1·3·5년 생존율, 95% 구간이 겹치지 않으면 '차이 있음'
    rows = []
    if rest:
        k = pd.read_parquet(v3.TAB / "km.parquet")
        ka, kb = (k[k["dong"] == x].set_index("year") for x in (a, b))
        med = k.groupby("year")["survival_pct"].median()
        for y in (1, 3, 5):
            if y in ka.index and y in kb.index:
                se = [(x.loc[y, "hi_pct"] - x.loc[y, "lo_pct"]) / (2 * 1.96) for x in (ka, kb)]  # 95% 구간 폭에서 표준오차를 되살린다(근사)
                z = abs(ka.loc[y, "survival_pct"] - kb.loc[y, "survival_pct"]) / np.hypot(*se)
                p = float(2 * stats.norm.sf(z))
                r = _row(f"음식점 {y}년 생존율(업종 구분 없음)", "%", float(ka.loc[y, "survival_pct"]), float(kb.loc[y, "survival_pct"]), float(med[y]),
                         _verdict(p), f"두 생존율 차이의 Z 검정(Z {z:.2f})", p)
                r["ci"] = [[round(float(ka.loc[y, "lo_pct"]), 1), round(float(ka.loc[y, "hi_pct"]), 1)], [round(float(kb.loc[y, "lo_pct"]), 1), round(float(kb.loc[y, "hi_pct"]), 1)]]
                rows.append(r)
    sections.append({"id": "survival", "title": "생존", "rows": rows, "note": None if rest else "생존 자료는 음식점 인허가뿐이라 이 업종에서는 비교하지 않아요."})

    # 5. 앞으로: 방문 예상 7일(R1) 평균과 예상 범위. 범위가 겹치지 않는 날 수로 판정
    rows, fc_view = [], None
    try:
        import recipes
        fc = pd.DataFrame(recipes.r1({"dong": [a, b]})["forecast"])
        if set(fc["dong"]) >= {a, b}:
            fa, fb = (fc[fc["dong"] == x].set_index("date") for x in (a, b))
            q = recipes.r1(None)["interval_q"]
            sd = (q["hi"] - q["lo"]) / (2 * 1.2816)  # 80% 범위(10%·90% 분위) 폭 → 하루 오차의 표준편차(로그, 정규 근사)
            z = abs(np.log(fa["visit"].mean() / fb["visit"].mean())) / (sd * np.sqrt(2 / len(fa)))
            p = float(2 * stats.norm.sf(z))
            r = _row("다음 7일 하루 방문 예상(평균)", "지수", float(fa["visit"].mean()), float(fb["visit"].mean()), None,
                     _verdict(p), f"7일 평균 차이를 검증 오차 폭과 견줌(Z {z:.2f}, 날마다 오차가 따로 생긴다고 가정)", p)
            r["texts"][2] = "-"
            rows.append(r)
            fc_view = {"dates": list(fa.index), a: fa[["visit", "lo", "hi"]].to_dict("list"), b: fb[["visit", "lo", "hi"]].to_dict("list")}
    except Exception:  # 예상 캐시를 못 읽어도 비교의 다른 절은 낸다
        pass
    sections.append({"id": "future", "title": "앞으로", "rows": rows})
    return {"dongs": [a, b], "target": target, "biz": biz, "sections": [x for x in sections if x["rows"] or x.get("note")], "forecast": fc_view,
            "rule": f"차이 판정: 같은 주·같은 달끼리 짝 지어 검정해 틀릴 가능성이 {int(ALPHA * 100)}% 미만이면 '차이 있음'이에요. 매출 흐름 지표는 함께 판정한 만큼 기준을 엄격하게 잡았어요. 어느 쪽이 낫다는 판단은 하지 않아요."}
