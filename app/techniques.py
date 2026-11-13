"""(가) 기법 목록 7종(설계 11-1절, 2026-11-13): 질문에 분석 기법 이름이 있으면 정해진 코드로 계산한다.

- 기존 주제 15개의 절차는 그대로 두고, 기법을 지정한 질문만 이 경로로 보낸다(LLM 없음, 오프라인, 같은 입력이면 같은 결과).
- 거부 조건과 화면 경고문은 이중 검토 039(요청 2 표)를 따른다. 거부되면 이유와 대신 할 수 있는 것을 답한다.
- 자료는 제출본 표(`data/tables/`)만 쓴다. 모두 월·연 단위다.
- 답은 기존 답 화면 형식(answer: 결론·3블록·나눠 보기·방법과 검증·출처)으로 돌려준다.
"""
import re
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import stats

import datadict
import qtuple as Q
from layers import _cop, _josa, _ro

# ---------------------------------------------------------------- 기법·지표 사전
TECH = {  # 이름 → (보이는 이름, 질문에서 찾을 말)
    "corr": ("상관", r"상관|연관성|같이 움직|관계가 있"),
    "cluster": ("군집", r"군집|클러스터|유형으로 나눠|그룹으로 나눠|끼리 묶"),
    "change": ("변화 분해", r"(건수|건당|단가|객단가).*(분해|나눠)|변화 ?분해|(분해|나눠).*(건수|건당|단가)"),
    "decomp": ("시계열 분해", r"시계열 ?분해|추세와 계절|계절성"),
    "regress": ("회귀", r"회귀|영향을 미치|미치는 영향|설명하는 요인"),
    "test": ("두 집단 검정", r"검정|유의한 차이|유의미한 차이|통계적으로 차이|통계적으로 다른"),
    "dist": ("분포", r"분포|히스토그램|사분위|치우쳐"),
    "outlier": ("이상치", r"이상치|이상값|튀는 달|특이한 달|이상한 달"),
}
METRIC = {  # 지표 → (이름, 질문에서 찾을 말, 단위)
    "sales": ("카드 매출", r"매출|카드|소비", "원"),
    "visit": ("하루 방문", r"방문|유동|인구|사람", "지수"),
    "stores": ("가게 수", r"가게|점포|업체|업소", "곳"),
    "surv": ("5년 생존율", r"생존|폐업", "%"),
    "tour": ("관광객 매출 비중", r"관광객", "%"),
}
CARD_BIZ = {"음식점": "음식점업", "카페": "음식점업", "한식": "음식점업", "일식": "음식점업", "횟집": "음식점업", "중식": "음식점업",
            "치킨": "음식점업", "분식": "음식점업", "주점": "음식점업", "숙박": "숙박업", "소매": "소매업", "편의점": "소매업"}
STORE_MAJOR = {"음식점업": "음식", "숙박업": "숙박", "소매업": "소매"}
SRC = {"sales": ("제주관광공사 카드 소비", "card_month"), "visit": ("유동인구(제주데이터허브 583)", "pop_month"),
       "stores": ("상가 정보(공공데이터포털)", "biz"), "surv": ("음식점 인허가(행정안전부)", "km"), "tour": ("제주관광공사 카드 소비", "card_month")}
NEXT = {"sales": "매달", "visit": "매달", "stores": "분기마다", "surv": "매년", "tour": "매달"}


def detect(question):
    """기법 이름이 있으면 기법 키, 없으면 None."""
    q = question or ""
    for k, (_, pat) in TECH.items():
        if re.search(pat, q):
            return k
    return None


def parse(question):
    """기법·동네·업종·지표·k를 질문에서 뽑는다. 정해진 사전만 쓴다(LLM 없음)."""
    q = question or ""
    dongs = sorted({d for d in Q.DONGS if d in q}, key=q.index)
    target = next((t for t in Q.TARGETS_BIZ if t in q), None)
    metrics = sorted({m for m, (_, pat, _) in METRIC.items() if re.search(pat, q)}, key=lambda m: re.search(METRIC[m][1], q).start())
    k = re.search(r"(\d)\s*개\s*(?:군집|그룹|유형|묶음)", q)
    return {"tech": detect(q), "dongs": dongs, "target": target, "metrics": metrics, "k": int(k.group(1)) if k else None}


# ---------------------------------------------------------------- 자료
@lru_cache(maxsize=1)
def _T():
    return datadict.load_tables()


def _biz(target):
    return CARD_BIZ.get(target or "", None)


def sales_monthly(dong=None, target=None):
    """월 카드 매출(원). 동네가 없으면 제주 43곳 합."""
    d = _T()["card_month"]
    b = _biz(target)
    if b:
        d = d[d.biz == b]
    if dong:
        d = d[d.dong == dong]
    return d.groupby("ym").amt.sum().sort_index()


def visit_monthly(dong=None):
    """월 하루 평균 방문 지수(월 합 ÷ 자료 있는 날 수). 동네가 없으면 43곳의 하루 평균을 더한다."""
    d = _T()["pop_month"]
    if dong:
        d = d[d.dong == dong]
    d = d.assign(v=d.visit / d.days.replace(0, np.nan))
    return d.groupby("ym").v.sum().sort_index()


def monthly(metric, dong=None, target=None):
    return visit_monthly(dong) if metric == "visit" else sales_monthly(dong, target)


def cross(metric, target=None):
    """43개 동네 단면 값(최근 12개월 기준). 이름 → 값."""
    T = _T()
    if metric == "sales":
        d = T["card_month"]
        b = _biz(target)
        d = d[d.biz == b] if b else d
        last = sorted(d.ym.unique())[-12:]
        return d[d.ym.isin(last)].groupby("dong").amt.sum()
    if metric == "visit":
        d = T["pop_month"]
        last = sorted(d.ym.unique())[-12:]
        g = d[d.ym.isin(last)].groupby("dong")[["visit", "days"]].sum()
        return g.visit / g.days
    if metric == "stores":
        d = T["biz"]
        m = STORE_MAJOR.get(_biz(target) or "")
        if target == "카페":
            d = d[d.minor.astype(str).str.contains("카페")]
        elif m:
            d = d[d.major == m]
        return d.groupby("dong")["count"].sum().astype(float)
    if metric == "surv":
        d = T["km"]
        return d[(d.year == 5) & d.dong.isin(Q.DONGS)].set_index("dong").survival_pct.astype(float)
    if metric == "tour":
        d = T["card_month"]
        b = _biz(target)
        d = d[d.biz == b] if b else d
        last = sorted(d.ym.unique())[-12:]
        d = d[d.ym.isin(last)]
        tot = d.groupby("dong").amt.sum()
        tour = d[d.cust.str.contains("관광객")].groupby("dong").amt.sum()
        return (tour / tot * 100).fillna(0)
    raise ValueError(metric)


def as_of(metric):
    T = _T()
    if metric in ("sales", "tour"):
        return str(T["card_month"].ym.max())
    if metric == "visit":
        return str(T["pop_month"].ym.max())
    if metric == "stores":
        return "2026-09 단면"
    return "2015~2021 개업 기준"


# ---------------------------------------------------------------- 숫자 표기
def fmt(v, metric):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    u = METRIC[metric][2]
    if u == "원":
        return f"{v / 1e8:,.1f}억 원"
    if u == "지수":
        return f"{v / 1e4:,.1f}만" if abs(v) >= 1e4 else f"{v:,.0f}"
    if u == "곳":
        return f"{v:,.0f}곳"
    return f"{v:.1f}%"


def r2(x, n=2):
    return float(round(float(x), n))


def pfmt(p):
    return "0.001 미만" if p < 0.001 else f"{p:.3f}"


# ---------------------------------------------------------------- 결과 묶음
class Reject(Exception):
    """거부 조건(039 요청 2): 이유와 대신 할 수 있는 것."""

    def __init__(self, why, instead):
        super().__init__(why)
        self.why, self.instead = why, instead


def _line(text, tag, block="facts", layer="L2", source=None, as_of_=None):
    return {"layer": layer, "block": block, "tag": tag, "text": text, "source": source, "as_of": as_of_, "kind": None}


def _view(vid, label, kind, points_by_series, summary, unit=None, x="x", values=None, highlight=None):
    v = {"id": vid, "label": label, "kind": kind, "x": x, "summary": summary, "definition": None,
         "series": [{"name": n, "points": [[a, (None if b is None or (isinstance(b, float) and np.isnan(b)) else float(b))] for a, b in pts]} for n, pts in points_by_series.items()]}
    if unit:
        v["unit"] = unit
    if values is not None:
        v["values"] = {k: float(x_) for k, x_ in values.items()}
        v["highlight"] = highlight or []
    return v


# ---------------------------------------------------------------- 기법 7종
def t_corr(p):
    m = (p["metrics"] + ["visit", "sales"])
    a, b = m[0], next(x for x in m[1:] if x != m[0])
    warn = ["추세와 계절성이 있는 월별 값끼리의 단순 상관은 겉보기 연관성(허위 상관)일 수 있어요. 전달 대비 변화량끼리의 상관도 함께 보여 드려요.",
            "상관은 같이 움직이는 정도일 뿐 원인과 결과를 뜻하지 않아요."]
    if len(p["dongs"]) == 1:  # 한 동네의 월별 시계열
        dong = p["dongs"][0]
        if "visit" not in (a, b):
            a, b = "visit", "sales"
        s1, s2 = monthly("visit", dong), monthly("sales", dong, p["target"])
        df = pd.concat([s1.rename("x"), s2.rename("y")], axis=1).dropna()
        if len(df) < 12:
            raise Reject(f"두 자료가 겹치는 달이 {len(df)}개월이라 12개월보다 적어요.", "43개 동네를 견주는 상관(동네 이름 없이 질문)을 해 보세요.")
        r, pr = stats.pearsonr(df.x, df.y)
        rs, ps = stats.spearmanr(df.x, df.y)
        dd = df.diff().dropna()
        rd, pd_ = stats.pearsonr(dd.x, dd.y)
        who = f"{dong} 월별 방문과 {p['target'] or ''} 카드 매출".replace("  ", " ")
        concl = f"{who}의 상관계수는 {r:.2f}이고, 전달 대비 변화량끼리는 {rd:.2f}{_cop(f'{rd:.2f}')}."
        lines = [_line(f"겹치는 {len(df)}개월({df.index[0]}~{df.index[-1]})로 계산했어요.", "표본"),
                 _line(f"Pearson 상관계수 {r:.2f}(p값 {pfmt(pr)}), 순위 상관(Spearman) {rs:.2f}(p값 {pfmt(ps)}).", "상관"),
                 _line(f"추세를 뺀 전달 대비 변화량끼리의 상관은 {rd:.2f}(p값 {pfmt(pd_)}){_cop(f'{rd:.2f}')}. 이 값이 원래 값보다 많이 낮으면 둘이 같은 계절·추세를 탄 영향이 커요.", "차분 상관")]
        nums = {"n": len(df), "pearson": r2(r, 4), "spearman": r2(rs, 4), "diff_pearson": r2(rd, 4)}
        view = _view("scatter", "방문과 매출(달마다 한 점)", "scatter", {f"{dong}": list(zip(df.x, df.y))}, f"{len(df)}개월", unit=None)
        src = ["visit", "sales"]
    else:  # 43개 동네 단면
        xa, xb = cross(a, p["target"]), cross(b, p["target"])
        df = pd.concat([xa.rename("x"), xb.rename("y")], axis=1).dropna()
        if len(df) < 10:
            raise Reject(f"두 값이 함께 있는 동네가 {len(df)}곳이라 10곳보다 적어요.", "다른 지표 짝으로 다시 물어보세요.")
        r, pr = stats.pearsonr(df.x, df.y)
        rs, ps = stats.spearmanr(df.x, df.y)
        big = (df.x.rank(ascending=False) <= 2) & (df.y.rank(ascending=False) <= 2)
        wo = df[~big]
        rw = stats.pearsonr(wo.x, wo.y)[0] if len(wo) >= 10 else float("nan")
        na, nb = METRIC[a][0], METRIC[b][0]
        concl = f"제주 {len(df)}개 동네의 {_josa(na, '과', '와')} {nb} 상관계수는 {r:.2f}, 순위 상관은 {rs:.2f}{_cop(f'{rs:.2f}')}."
        lines = [_line(f"동네 {len(df)}곳의 최근 12개월 값으로 계산했어요(가게 수는 2026-09 단면).", "표본"),
                 _line(f"Pearson 상관계수 {r:.2f}(p값 {pfmt(pr)}), 순위 상관(Spearman) {rs:.2f}(p값 {pfmt(ps)}).", "상관")]
        if big.any():
            lines.append(_line(f"두 값이 모두 상위 2위 안인 동네({', '.join(df.index[big])})를 빼면 Pearson {rw:.2f}{_cop(f'{rw:.2f}')}. 큰 상권 한두 곳이 계수를 끌어올릴 수 있어요.", "극단값 점검"))
        nums = {"n": len(df), "pearson": r2(r, 4), "spearman": r2(rs, 4)}
        view = _view("scatter", f"{_josa(na, '과', '와')} {nb}(동네마다 한 점)", "scatter", {"동네": list(zip(df.x, df.y))}, f"{len(df)}곳")
        view["names"] = list(df.index)
        warn = ["노형동·연동처럼 큰 상권 한두 곳이 Pearson 계수를 끌어올릴 수 있어 순위 상관(Spearman)을 함께 보여 드려요.",
                "상관은 같이 움직이는 정도일 뿐 원인과 결과를 뜻하지 않아요."]
        src = [a, b]
    view["axes"] = [METRIC[src[0]][0], METRIC[src[1]][0]]
    return concl, lines, warn, [view], nums, src, ("Pearson·Spearman 상관", "두 값이 같이 커지고 작아지는 정도를 -1~1로 재요.",
                                                  "표본 수, p값, 순위 상관, 극단값을 뺀 값·차분 상관을 함께 봐요.",
                                                  "표본이 10곳(또는 12개월)보다 적으면 계산하지 않아요.")


def _std(df):
    return (df - df.mean()) / df.std(ddof=0)


def t_cluster(p):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    cols = ["visit", "sales", "stores", "surv", "tour"]
    df = pd.concat([cross(c, p["target"]).rename(c) for c in cols], axis=1).loc[list(Q.DONGS)]
    df = df.dropna()
    if len(df) < 20:
        raise Reject(f"모든 지표가 있는 동네가 {len(df)}곳뿐이에요.", "지표를 줄여 분포나 상관으로 보세요.")
    X = _std(np.log1p(df[["visit", "sales", "stores"]])).join(_std(df[["surv", "tour"]]))
    if p["k"] is not None and not 2 <= p["k"] <= 6:
        raise Reject(f"군집 수 {p['k']}개는 계산하지 않아요. 동네가 43곳이라 2~6개만 써요.", "군집 수를 2~6 사이로 다시 물어보세요.")
    sil = {}
    labels = {}
    for k in range(2, 7):
        km = KMeans(n_clusters=k, n_init=20, random_state=0).fit(X)
        labels[k], sil[k] = km.labels_, silhouette_score(X, km.labels_)
    k = p["k"] or max(sil, key=sil.get)
    lab = pd.Series(labels[k], index=df.index)
    order = df.groupby(lab).sales.mean().sort_values(ascending=False).index  # 매출 큰 군집을 1번으로
    ren = {o: i + 1 for i, o in enumerate(order)}
    lab = lab.map(ren)
    g = df.groupby(lab).agg(["mean"])
    g.columns = [c for c, _ in g.columns]
    cnt = lab.value_counts().sort_index()
    corr = df[["visit", "sales", "stores"]].corr().abs().where(~np.eye(3, dtype=bool)).max().max()
    concl = f"제주 {len(df)}개 동네를 방문·매출·가게 수·생존율·관광객 비중으로 {k}개 군집으로 나눴어요(실루엣 {sil[k]:.2f})."
    lines = [_line(f"군집 수는 2~6개를 모두 계산해 실루엣 계수가 가장 높은 {k}개를 골랐어요." if not p["k"] else f"요청한 군집 수 {k}개로 나눴어요(실루엣 {sil[k]:.2f}).", "군집 수")]
    for c in cnt.index:
        mem = list(lab[lab == c].index)
        lines.append(_line(f"군집 {c}({cnt[c]}곳): 평균 방문 {fmt(g.loc[c, 'visit'], 'visit')}, 매출 {fmt(g.loc[c, 'sales'], 'sales')}, "
                           f"가게 {fmt(g.loc[c, 'stores'], 'stores')}, 5년 생존 {g.loc[c, 'surv']:.1f}%, 관광객 비중 {g.loc[c, 'tour']:.1f}%. "
                           f"{', '.join(mem[:8])}{' 등' if len(mem) > 8 else ''}.", f"군집 {c}"))
    hl = p["dongs"][:1]
    if hl and hl[0] in lab.index:
        lines.append(_line(f"{_josa(hl[0])} 군집 {lab[hl[0]]}에 들어가요.", "고른 동네", block="analysis", layer="L3"))
    warn = ["동네가 43곳뿐이라 시작값에 따라 경계에 있는 동네의 군집이 바뀔 수 있어요(20번 다시 시작해 가장 나은 것을 씀).",
            f"방문·매출·가게 수는 서로 상관이 높아(최대 |r| {corr:.2f}) 상권 크기가 군집을 주로 가를 수 있어요. 크기 지표는 로그를 씌운 뒤 표준화했어요."]
    view = _view("clustermap", "군집(지도 색 = 군집 번호)", "map", {}, f"{k}개 군집", unit="군집", values=lab.to_dict(), highlight=hl)
    sil_view = _view("silhouette", "군집 수별 실루엣 계수", "bar", {"실루엣": [(f"{kk}개", v) for kk, v in sil.items()]}, "높을수록 잘 나뉨")
    nums = {"n": len(df), "k": int(k), "silhouette": r2(sil[k], 4)}
    return concl, lines, warn, [view, sil_view], nums, ["visit", "sales", "stores", "surv", "tour"], (
        "k-means 군집", "지표를 표준화(크기 지표는 로그)한 뒤 거리가 가까운 동네끼리 묶어요.",
        "군집 수 2~6개의 실루엣 계수를 비교해 고르고, 20번 다시 시작해 가장 나은 결과를 써요.",
        "군집 수가 2~6개 밖이거나 지표가 있는 동네가 20곳보다 적으면 계산하지 않아요.")


def decompose(s):
    """고전 분해(곱셈): 12개월 중심 이동평균 추세, 달별 계절지수, 나머지."""
    s = s.astype(float)
    trend = s.rolling(12, center=True).mean().rolling(2, center=True).mean().shift(-1)
    ratio = s / trend
    month = pd.Series([int(x[5:7]) for x in s.index], index=s.index)
    si = ratio.groupby(month).mean()
    si = si / si.mean()
    seas = month.map(si)
    resid = s / (trend * seas)
    return trend, si, seas, resid


def _pick_series(p):
    dong = p["dongs"][0] if p["dongs"] else None
    metric = "visit" if (p["metrics"][:1] == ["visit"]) else "sales"
    s = monthly(metric, dong, p["target"])
    name = f"{dong or '제주 전체'} {(p['target'] + ' ') if p['target'] and metric == 'sales' else ''}{METRIC[metric][0]}"
    return s, metric, name, dong


def t_decomp(p):
    s, metric, name, dong = _pick_series(p)
    if len(s) < 24:
        raise Reject(f"{name} 자료가 {len(s)}개월이라 계절을 두 번 보려면 필요한 24개월보다 적어요.", "카드 매출(2020-01부터)로 다시 물어보세요.")
    trend, si, seas, resid = decompose(s)
    tv = trend.dropna()
    ch = (tv.iloc[-1] / tv.iloc[0] - 1) * 100
    hi, lo = si.idxmax(), si.idxmin()
    concl = f"{name}의 계절지수는 {hi}월이 {si[hi] * 100:.1f}%로 가장 높고 {lo}월이 {si[lo] * 100:.1f}%로 가장 낮아요."
    lines = [_line(f"{len(s)}개월({s.index[0]}~{s.index[-1]})을 추세·계절·나머지로 나눴어요.", "표본"),
             _line(f"추세는 {tv.index[0]} {fmt(tv.iloc[0], metric)}에서 {tv.index[-1]} {fmt(tv.iloc[-1], metric)}로 {ch:+.1f}% 변했어요.", "추세"),
             _line(f"계절지수(평균 100%): {hi}월 {si[hi] * 100:.1f}%, {lo}월 {si[lo] * 100:.1f}%.", "계절"),
             _line(f"나머지(불규칙) 성분의 표준편차는 {resid.std() * 100:.1f}%p예요.", "나머지")]
    warn = ["12개월 이동평균으로 추세를 구해 처음 6개월과 최근 6개월의 추세는 계산되지 않아요.",
            "2020~2022년 코로나 충격으로 그 시기의 계절 모양이 달랐을 수 있어요."]
    v1 = _view("decomp", "실제 값과 추세", "line", {"실제": list(zip(s.index, s)), "추세": list(zip(trend.index, trend))}, name, unit=METRIC[metric][2])
    v2 = _view("season", "달별 계절지수(%)", "bar", {"계절지수": [(f"{m}월", si[m] * 100) for m in si.index]}, "100%가 평균", unit="%")
    nums = {"months": len(s), "trend_change_pct": r2(ch, 1), "season_max": r2(si[hi] * 100, 1), "season_min": r2(si[lo] * 100, 1)}
    return concl, lines, warn, [v1, v2], nums, [metric], (
        "고전 시계열 분해(곱셈)", "12개월 중심 이동평균으로 추세를 구하고, 실제 값 ÷ 추세를 달마다 평균해 계절지수를 만들어요.",
        "계절지수 평균을 100%로 맞추고, 나머지 성분의 흩어짐을 함께 봐요.",
        "24개월보다 짧은 자료는 계산하지 않아요.")


def t_regress(p):
    ys = "sales"
    xs = [m for m in p["metrics"] if m not in (ys,)] or ["visit", "stores"]
    xs = list(dict.fromkeys(xs))
    if len(xs) > 3:
        raise Reject(f"설명 변수가 {len(xs)}개예요. 동네가 43곳뿐이라 3개까지만 써요.", "설명 변수를 3개 이하로 줄여 다시 물어보세요.")
    df = pd.concat([cross(ys, p["target"]).rename("y")] + [cross(x, p["target"]).rename(x) for x in xs], axis=1).loc[list(Q.DONGS)].dropna()
    df = df[(df > 0).all(axis=1)]
    logc = [c for c in ["y"] + xs if c in ("y", "visit", "sales", "stores")]
    Z = df.copy()
    Z[logc] = np.log(Z[logc])
    X = np.column_stack([np.ones(len(Z))] + [Z[x] for x in xs])
    y = Z.y.values
    if len(xs) > 1:
        vif = {x: 1 / (1 - _r2(Z[x].values, np.column_stack([np.ones(len(Z))] + [Z[o] for o in xs if o != x]))) for x in xs}
        bad = [x for x, v in vif.items() if v > 10]
        if bad:
            raise Reject(f"{', '.join(METRIC[b][0] for b in bad)}의 VIF가 10을 넘어 계수를 믿을 수 없어요.", "겹치는 변수를 빼고 다시 물어보세요.")
    else:
        vif = {xs[0]: 1.0}
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    n, k = X.shape
    s2 = res @ res / (n - k)
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    tval = beta / se
    pval = 2 * stats.t.sf(np.abs(tval), n - k)
    r2_ = 1 - res @ res / ((y - y.mean()) @ (y - y.mean()))
    Qm, _ = np.linalg.qr(X)  # 지렛대 값 = 모자 행렬의 대각(QR로 구해 역행렬 경고를 피함)
    lev = pd.Series((Qm ** 2).sum(axis=1), index=Z.index)
    top = lev.idxmax()
    names = {x: METRIC[x][0] for x in xs}
    concl = f"동네 {n}곳의 {p['target'] or ''} 카드 매출을 {'·'.join(names.values())}로 설명하는 회귀의 R²는 {r2_:.2f}{_cop(f'{r2_:.2f}')}.".replace("  ", " ")
    lines = [_line(f"최근 12개월 매출과 {', '.join(names.values())}(크기 지표는 로그)로 최소제곱 회귀를 했어요. 표본 {n}곳.", "표본")]
    for i, x in enumerate(xs, 1):
        el = "탄력성" if x in logc else "계수"
        lines.append(_line(f"{names[x]} {el} {beta[i]:.2f}(표준오차 {se[i]:.2f}, p값 {pfmt(pval[i])}, VIF {vif[x]:.1f}).", "계수"))
    lines.append(_line(f"지렛대 값이 가장 큰 동네는 {top}({lev[top]:.2f}){_cop(top)}. 이 동네 하나가 기울기에 큰 영향을 줄 수 있어요.", "지렛대 점검", block="analysis", layer="L3"))
    warn = ["동네가 43곳뿐이라 노형동·연동 같은 큰 상권 1~2곳이 회귀선에 큰 영향을 줄 수 있어요(지렛대 효과).",
            "붙어 있는 동네끼리 값이 비슷해(공간 상관) p값이 실제보다 작게 나올 수 있어요. 원인이 아니라 연관으로만 보세요."]
    fit = X @ beta
    view = _view("resid", "실제 값과 회귀 예측(로그 매출, 동네마다 한 점)", "scatter", {"동네": list(zip(fit, y))}, f"R² {r2_:.2f}")
    view["names"] = list(Z.index)
    view["axes"] = ["회귀 예측", "실제"]
    nums = {"n": n, "r2": r2(r2_, 4), **{f"b_{x}": r2(beta[i], 4) for i, x in enumerate(xs, 1)}}
    return concl, lines, warn, [view], nums, ["sales"] + xs, (
        "최소제곱 회귀(로그)", "동네별 매출을 설명 변수로 직선 관계에 맞춰요. 크기 지표는 로그를 씌워 계수를 탄력성(1% 차이당 %)으로 읽어요.",
        "계수의 표준오차·p값, R², VIF(변수 겹침), 지렛대 값을 함께 봐요.",
        "설명 변수가 3개를 넘거나 VIF가 10을 넘으면 계산하지 않아요.")


def _r2(y, X):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ b
    return 1 - (r @ r) / ((y - y.mean()) @ (y - y.mean()))


def t_test(p):
    metric = "visit" if p["metrics"][:1] == ["visit"] else "sales"
    if len(p["dongs"]) >= 2:
        a, b = p["dongs"][:2]
        s1, s2 = monthly(metric, a, p["target"]), monthly(metric, b, p["target"])
        df = pd.concat([s1.rename("a"), s2.rename("b")], axis=1).dropna().iloc[-24:]
        la, lb = a, b
        what = f"{_josa(a, '과', '와')} {b}의 최근 {len(df)}개월 {METRIC[metric][0]}"
    else:
        dong = p["dongs"][0] if p["dongs"] else None
        s = monthly(metric, dong, p["target"])
        if len(s) < 24:
            raise Reject(f"자료가 {len(s)}개월이라 최근 12개월과 그 전 12개월을 짝지을 수 없어요.", "카드 매출로 다시 물어보세요.")
        cur, prev = s.iloc[-12:], s.iloc[-24:-12]
        df = pd.DataFrame({"a": cur.values, "b": prev.values}, index=cur.index)
        la, lb = "최근 12개월", "그 전 12개월"
        what = f"{dong or '제주 전체'} {METRIC[metric][0]}의 {_josa(la, '과', '와')} {lb}(같은 달끼리 짝)"
    if len(df) < 6:
        raise Reject(f"짝지은 달이 {len(df)}개라 6개보다 적어요.", "기간을 늘려 다시 물어보세요.")
    diff = df.a - df.b
    w = stats.wilcoxon(df.a, df.b)
    pos = (diff > 0).sum()
    rb = (pos - (diff < 0).sum()) / len(diff)  # 부호 기준 효과 크기(-1~1)
    med = (df.a / df.b - 1).median() * 100
    sig = w.pvalue < 0.05
    concl = f"{_josa(what)} {'차이가 있어요' if sig else '차이가 있다고 보기 어려워요'}(Wilcoxon p값 {pfmt(w.pvalue)}, 중간 차이 {med:+.1f}%)."
    lines = [_line(f"같은 달끼리 짝지은 {len(df)}쌍으로 Wilcoxon 부호순위 검정을 했어요.", "표본"),
             _line(f"{la}가 더 큰 달 {pos}개 / {len(df)}개, 차이의 중간값 {med:+.1f}%, 효과 크기 {rb:+.2f}(-1~1).", "차이"),
             _line(f"p값 {pfmt(w.pvalue)}: {'우연만으로는 드문 차이예요' if sig else '우연으로도 생길 수 있는 크기예요'}(기준 0.05).", "판정", block="analysis", layer="L3")]
    if re.search(r"t ?검정|티검정", p.get("q", "")):
        sh = stats.shapiro(diff)
        tt = stats.ttest_rel(df.a, df.b)
        lines.append(_line(f"요청한 짝 t검정: p값 {pfmt(tt.pvalue)}. 차이의 정규성 검정(Shapiro) p값 {pfmt(sh.pvalue)}"
                           f"{' — 정규성이 의심돼 Wilcoxon 결과를 기준으로 봐요' if sh.pvalue < 0.05 else ''}.", "t검정"))
    warn = ["이웃한 달끼리 값이 비슷해(자기상관) p값이 실제보다 작게 나올 수 있어요. 그래서 t검정 대신 비모수 검정(Wilcoxon)을 기본으로 써요."]
    v = _view("pair", f"{_josa(la, '과', '와')} {lb}", "line", {la: list(zip(df.index, df.a)), lb: list(zip(df.index, df.b))}, f"{len(df)}쌍", unit=METRIC[metric][2])
    nums = {"n": len(df), "p": r2(w.pvalue, 6), "median_diff_pct": r2(med, 1), "effect": r2(rb, 3)}
    return concl, lines, warn, [v], nums, [metric], (
        "Wilcoxon 부호순위 검정", "같은 달끼리 짝지은 두 값의 차이가 0을 중심으로 대칭인지 순위로 검정해요(정규분포 가정 없음).",
        "차이의 중간값, 효과 크기(큰 쪽 달 비율), p값을 함께 봐요. t검정을 요청하면 정규성을 확인한 뒤 같이 보여 드려요.",
        "짝이 6개보다 적으면 계산하지 않아요.")


def t_dist(p):
    metric = p["metrics"][0] if p["metrics"] else "sales"
    s = cross(metric, p["target"]).reindex(list(Q.DONGS)).dropna()
    if s.nunique() < 5:
        raise Reject("서로 다른 값이 5개보다 적어 분포를 그릴 수 없어요.", "다른 지표로 물어보세요.")
    q1, md, q3 = s.quantile([0.25, 0.5, 0.75])
    sk = stats.skew(s)
    name = f"{(p['target'] + ' ') if p['target'] and metric in ('sales', 'stores', 'tour') else ''}{METRIC[metric][0]}"
    concl = f"제주 {len(s)}개 동네 {name}의 중간값은 {fmt(md, metric)}, 평균은 {fmt(s.mean(), metric)}{_cop(fmt(s.mean(), metric))}(왜도 {sk:.2f})."
    lines = [_line(f"사분위: 아래 25% {fmt(q1, metric)}, 중간 {fmt(md, metric)}, 위 25% {fmt(q3, metric)}. 최소 {fmt(s.min(), metric)}({s.idxmin()}), 최대 {fmt(s.max(), metric)}({s.idxmax()}).", "사분위"),
             _line(f"평균보다 작은 동네가 {(s < s.mean()).sum()}곳 / {len(s)}곳이에요.", "평균과 중간값")]
    for d in p["dongs"][:1]:
        if d in s.index:
            pct = (s < s[d]).mean() * 100
            lines.append(_line(f"{_josa(d)} {fmt(s[d], metric)}{_ro(fmt(s[d], metric))} 아래에서 {pct:.0f}% 위치(43곳 중 {int(s.rank(ascending=False)[d])}위)예요.", "고른 동네", block="analysis", layer="L3"))
    warn = ["제주 상권 지표는 상위 동네로 쏠린 비대칭 분포라 평균보다 중간값과 사분위로 읽어야 착시를 피해요."] if sk > 1 else []
    edges = np.quantile(s, np.linspace(0, 1, 7)) if metric not in ("surv", "tour") else np.linspace(s.min(), s.max(), 7)
    bins = pd.cut(s, bins=np.unique(edges), include_lowest=True)
    hist = s.groupby(bins, observed=False).size()
    v = _view("hist", f"{name} 구간별 동네 수", "bar", {"동네 수": [(f"{fmt(iv.left, metric)}~{fmt(iv.right, metric)}", c) for iv, c in hist.items()]}, f"{len(s)}곳")
    vm = _view("distmap", f"{name} 지도", "map", {}, f"{len(s)}곳", unit=METRIC[metric][2], values=s.to_dict(), highlight=p["dongs"][:1])
    nums = {"n": len(s), "median": r2(md, 2), "mean": r2(s.mean(), 2), "skew": r2(sk, 3)}
    return concl, lines, warn, [v, vm], nums, [metric], (
        "기술통계·분포", "43개 동네 값의 사분위, 평균과 중간값, 왜도(쏠림)를 구해요.",
        "구간별 동네 수와 지도를 함께 봐요.",
        "서로 다른 값이 5개보다 적으면 계산하지 않아요.")


def t_outlier(p):
    s, metric, name, dong = _pick_series(p)
    if len(s) < 12:
        raise Reject(f"{name} 자료가 {len(s)}개월이라 12개월보다 짧아요.", "카드 매출로 다시 물어보세요.")
    if len(s) >= 24:
        trend, si, seas, resid = decompose(s)
        r = resid.dropna()
        how = "계절과 추세를 뺀 나머지"
    else:
        r = s / s.rolling(3, center=True).median()
        r = r.dropna()
        how = "앞뒤 달 중간값 대비 비율"
    q1, q3 = r.quantile([0.25, 0.75])
    lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    out = r[(r < lo) | (r > hi)]
    concl = f"{name}에서 튀는 달은 {len(out)}개예요." + (f" {', '.join(f'{m}({(v - 1) * 100:+.0f}%)' for m, v in out.items())}." if len(out) else "")
    lines = [_line(f"{len(s)}개월을 {how}로 보고, 사분위 범위(IQR)의 1.5배 밖을 튀는 달로 봤어요.", "기준"),
             _line(f"보통 범위: 예상의 {(lo - 1) * 100:+.1f}% ~ {(hi - 1) * 100:+.1f}%.", "범위")]
    for m, v in out.items():
        lines.append(_line(f"{m}: 실제 {fmt(s[m], metric)}, 예상보다 {(v - 1) * 100:+.1f}%.", "튀는 달"))
    warn = ["튀는 달은 자료 오류 말고도 거리두기·태풍·카드사 집계 변경 같은 바깥 사건일 수 있어 그 달의 사정을 함께 확인해야 해요."]
    pts = {"실제": list(zip(s.index, s)), "튀는 달": [(m, (s[m] if m in out.index else None)) for m in s.index]}
    v = _view("outlier", "실제 값과 튀는 달", "line", pts, name, unit=METRIC[metric][2])
    nums = {"months": len(s), "outliers": len(out)}
    return concl, lines, warn, [v], nums, [metric], (
        "IQR 이상치", f"{how}를 구해 사분위 범위의 1.5배 밖에 있는 달을 골라요.",
        "보통 범위와 튀는 달의 실제 값을 함께 봐요.", "12개월보다 짧은 자료는 계산하지 않아요.")


def t_change(p):
    """매출 변화 = 결제 건수 변화 × 건당 금액 변화. 로그로 나눠 두 효과의 몫을 구한다(최근 12개월 vs 그 전 12개월)."""
    dong = p["dongs"][0] if p["dongs"] else None
    d = _T()["card_month"]
    b = _biz(p["target"])
    d = d[d.biz == b] if b else d
    d = d[d.dong == dong] if dong else d
    g = d.groupby("ym")[["amt", "cnt"]].sum().sort_index()
    if len(g) < 24:
        raise Reject(f"자료가 {len(g)}개월이라 최근 12개월과 그 전 12개월을 견줄 수 없어요.", "기간이 긴 업종으로 다시 물어보세요.")
    cur, prev = g.iloc[-12:].sum(), g.iloc[-24:-12].sum()
    ta, tc = cur.amt / prev.amt, cur.cnt / prev.cnt
    tt = ta / tc  # 건당 금액 비율
    la, lc, lt = np.log(ta), np.log(tc), np.log(tt)
    sc = lc / la * 100 if la else 0.0
    st = lt / la * 100 if la else 0.0
    name = f"{dong or '제주 전체'} {(p['target'] + ' ') if p['target'] else ''}카드 매출"
    span = f"{g.index[-12]}~{g.index[-1]}"
    concl = (f"{name}은 그 전 12개월보다 {(ta - 1) * 100:+.1f}% 변했고, 결제 건수가 {(tc - 1) * 100:+.1f}%, "
             f"건당 금액이 {(tt - 1) * 100:+.1f}% 바뀐 결과예요.")
    lines = [_line(f"최근 12개월({span}) 매출 {fmt(cur.amt, 'sales')}, 그 전 12개월 {fmt(prev.amt, 'sales')}.", "매출"),
             _line(f"결제 건수 {cur.cnt:,.0f}건(그 전 {prev.cnt:,.0f}건), 건당 금액 {cur.amt / cur.cnt:,.0f}원(그 전 {prev.amt / prev.cnt:,.0f}원).", "건수·건당 금액"),
             _line(f"로그로 나눈 몫: 건수 효과 {sc:.0f}%, 건당 금액 효과 {st:.0f}%(합 100%). 두 효과가 반대 방향이면 한쪽 몫이 100%를 넘어요.", "변화의 몫", block="analysis", layer="L3")]
    warn = ["건당 금액은 물가가 오르면 함께 오르므로, 건당 금액 효과에는 물가 상승분이 섞여 있어요.",
            "카드 결제만 센 값이라 현금·간편결제 비중이 바뀌면 건수가 달라 보일 수 있어요."]
    m = g.assign(t=g.amt / g.cnt)
    v1 = _view("cnt", "월 결제 건수", "line", {"건수": list(zip(m.index, m.cnt))}, name, unit="건")
    v2 = _view("ticket", "월 건당 금액(원)", "line", {"건당 금액": list(zip(m.index, m.t))}, name, unit="원")
    nums = {"sales_change_pct": r2((ta - 1) * 100, 1), "count_change_pct": r2((tc - 1) * 100, 1), "ticket_change_pct": r2((tt - 1) * 100, 1),
            "count_share_pct": r2(sc, 0), "ticket_share_pct": r2(st, 0)}
    return concl, lines, warn, [v1, v2], nums, ["sales"], (
        "매출 변화 분해(건수 × 건당 금액)", "매출 = 결제 건수 × 건당 금액이라, 두 기간의 비율을 로그로 나눠 각 요인의 몫을 구해요.",
        "두 기간의 건수·건당 금액과 몫의 합이 100%인지 함께 봐요.", "24개월보다 짧은 자료는 계산하지 않아요.")


RUN = {"change": t_change, "corr": t_corr, "cluster": t_cluster, "decomp": t_decomp, "regress": t_regress, "test": t_test, "dist": t_dist, "outlier": t_outlier}
EXAMPLES = {"change": "노형동 음식점 매출 변화를 건수와 건당 금액으로 분해해줘", "corr": "43개 동네 방문과 매출의 상관 분석해줘", "cluster": "43개 동네를 군집분석 해줘", "decomp": "노형동 음식점 월 매출 시계열 분해해줘",
            "regress": "동네별 매출에 방문과 가게 수가 미치는 영향 회귀분석해줘", "test": "노형동과 연동 음식점 매출이 통계적으로 차이 있어?",
            "dist": "43개 동네 음식점 매출 분포 보여줘", "outlier": "제주 전체 음식점 매출에서 튀는 달 찾아줘"}


# ---------------------------------------------------------------- 답 묶기
def answer(question, slots=None):
    """기법 질문 하나의 답(기존 /api/ask 응답 형식)."""
    p = parse(question)
    if slots and slots.get("method") in RUN:
        p["tech"] = slots["method"]
        p["dongs"] = slots.get("space") or p["dongs"]
        p["target"] = slots.get("target") or p["target"]
    p["q"] = question or ""
    tech = p["tech"]
    tname = TECH[tech][0]
    who = " · ".join(x for x in [", ".join(p["dongs"]) or None, p["target"], "·".join(METRIC[m][0] for m in p["metrics"]) or None] if x)
    understood = {"text": f"이렇게 이해했어요: {tname} 분석{(' — ' + who) if who else ''}", "by": "기법 사전", "assumed": False,
                  "slots": {"topic": "technique", "method": tech, "space": p["dongs"], "target": p["target"]}, "notes": []}
    others = [k for k in RUN if k != tech][:3]
    sugg = [{"text": EXAMPLES[k], "slots": {"topic": "technique", "method": k}} for k in others]
    try:
        concl, lines, warn, views, nums, used, (mtitle, how, check, limit) = RUN[tech](p)
    except Reject as e:
        text = f"{tname} 분석을 하지 않았어요: {e.why}"
        a = {"conclusion": {"text": text, "layer": "L3", "tag": "계산하지 않음"},
             "blocks": [{"id": "facts", "title": "사실·비교", "lines": [_line(e.why, "거부 조건"), _line(e.instead, "대신 할 수 있는 것", block="facts", layer="L5")]}],
             "views": [], "default_views": 0, "value_question": False, "footer": [], "freshness": [], "requests": [], "methods": []}
        return {"question": question, "status": "성공", "tuple": None, "interpret": None, "understood": understood, "suggestions": sugg,
                "card": {"conclusion": text, "evidence": [], "intervals": [], "limits": [e.why]}, "answer": a,
                "process": {"type": "기법 분석", "steps": [{"id": "t1", "sub": "S2", "name": f"{tname} 조건 확인", "op": "검사", "status": "거부"}], "data": {}, "unused": []},
                "downloads": []}
    srcs = []
    for m in used:
        nm = SRC[m][0]
        if nm not in [s["source"] for s in srcs]:
            srcs.append({"source": nm, "as_of": as_of(m), "next": NEXT[m]})
    first = srcs[0]["source"] if srcs else None
    for l_ in lines:
        l_["source"] = l_["source"] or first
    warn_lines = [_line(w, "주의", block="analysis", layer="L5") for w in warn]
    blocks = [{"id": "facts", "title": "계산 결과", "lines": [x for x in lines if x["block"] == "facts"]},
              {"id": "analysis", "title": "읽는 법과 주의", "lines": [x for x in lines if x["block"] == "analysis"] + warn_lines}]
    method = {"kind": f"tech_{tech}", "title": mtitle, "how": how, "check": check, "result": ", ".join(f"{k} {v}" for k, v in nums.items()), "limit": limit}
    a = {"conclusion": {"text": concl, "layer": "L3", "tag": f"Agent 계산 · {tname}"}, "blocks": blocks, "views": views, "default_views": len(views),
         "value_question": False, "footer": srcs, "freshness": [{"source": s["source"], "as_of": s["as_of"], "months_old": 0, "stale": False} for s in srcs],
         "requests": [], "methods": [method]}
    rows = [["지표", "값"]] + [[k, v] for k, v in nums.items()]
    csv = "\n".join(",".join(map(str, r)) for r in rows)
    return {"question": question, "status": "성공", "tuple": None, "interpret": None, "understood": understood, "suggestions": sugg,
            "card": {"conclusion": concl, "evidence": [{"text": x["text"], "tag": x["tag"], "layer": x["layer"], "dataset": x["source"], "as_of": None, "kind": None} for x in lines],
                     "intervals": [], "limits": warn},
            "answer": a,
            "process": {"type": "기법 분석", "steps": [{"id": "t1", "sub": "S1", "name": "자료 조회", "op": "조회", "status": "성공"},
                                                      {"id": "t2", "sub": "S2", "name": f"{tname} 조건 확인", "op": "검사", "status": "통과"},
                                                      {"id": "t3", "sub": "S4", "name": f"{tname} 계산", "op": "통계", "status": "성공"}],
                        "data": {s["source"]: s["as_of"] for s in srcs}, "unused": [],
                        "explain": {"text": f"질문에서 '{tname}' 기법을 찾아, 정해진 {mtitle} 코드로 제출본 자료를 계산했어요.", "by": "템플릿"}},
            "downloads": [{"kind": "bundle", "name": "이 답의 계산값.csv", "rows": len(rows) - 1, "export": "집계", "csv": csv}]}
