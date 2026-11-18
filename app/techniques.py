"""(가) 기법 목록 7종(설계 11-1절, 2026-11-13): 질문에 분석 기법 이름이 있으면 정해진 코드로 계산한다.

- 기존 주제 15개의 절차는 그대로 두고, 기법을 지정한 질문만 이 경로로 보낸다(LLM 없음, 오프라인, 같은 입력이면 같은 결과).
- 거부 조건과 화면 경고문은 이중 검토 039(요청 2 표)를 따른다. 거부되면 이유와 대신 할 수 있는 것을 답한다.
- 자료는 제출본 표(`data/tables/`)만 쓴다. 모두 월·연 단위다.
- 답은 기존 답 화면 형식(answer: 결론·3블록·나눠 보기·방법과 검증·출처)으로 돌려준다.
"""
import re
from pathlib import Path
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import stats

import datadict
import qtuple as Q
from layers import _cop, _josa, _ro

# ---------------------------------------------------------------- 기법·지표 사전
TECH = {  # 이름 → (보이는 이름, 질문에서 찾을 말)
    "corr": ("상관", r"상관|연관성|같이 움직|관계가 있|(?<![A-Za-z])CCF(?![A-Za-z])"),  # CCF·교차상관: 두 동네 시계열(2026-11-17 조정용 R080)
    "cluster": ("군집", r"군집|클러스터|유형으로 나눠|그룹으로 나눠|끼리 묶"),
    "change": ("변화 분해", r"(건수|건당|단가|객단가).*(분해|나눠)|변화 ?분해|(분해|나눠).*(건수|건당|단가)"),
    "decomp": ("시계열 분해", r"시계열 ?분해|추세와 계절|계절성|계절 ?분해|(?<![A-Za-z])STL(?![A-Za-z])"),  # STL·계절분해(2026-11-17 조정용 R076)
    "regress": ("회귀", r"회귀|영향을 미치|미치는 영향|설명하는 요인|(?i:newey)"),
    "test": ("두 집단 검정", r"검정|유의한 차이|유의미한 차이|통계적으로 차이|통계적으로 다른"),
    "dist": ("분포", r"(?<!업종 )(?<!업종)분포|히스토그램|사분위|치우쳐"),  # '업종 분포'는 동네 안 업종 구성이라 업종 다양성(hhi)으로(2026-11-17 실패 검토 ②)
    "outlier": ("이상치", r"이상치|이상값|튀는 달|특이한 달|이상한 달"),
    # 2026-11-14 추가(마스터 지시 '추가 기법 조사·반영'): 상권 연구에서 쓰는 기법 중 제출본 자료로 계산할 수 있는 것
    "lq": ("입지계수", r"입지 ?계수|(?<![A-Za-z])LQ(?![A-Za-z])|특화 ?계수|특화 ?업종|특화도|집적도|(평균|전체) ?비중과 ?비교|비중에 비해"),  # 비중 비교는 과밀(sat)보다 lq(2026-11-18 60번 진단)
    "surv": ("생존분석", r"생존 ?분석|생존 ?곡선|생존 ?함수|카플란|(?i:kaplan)|수명표|생존 ?확률"),
    "hhi": ("업종 다양성", r"다양성 ?지수|업종 ?다양성|허핀달|(?<![A-Za-z])HHI(?![A-Za-z])|집중도 ?지수|엔트로피|업종 ?(별 ?)?(분포|구성)"),
    "shift": ("변이할당", r"변이 ?할당|(?i:shift.?share)|성장 ?요인 ?분해|지역 ?경쟁 ?효과|(산업|업종) ?구성 ?(효과|덕분)|몫으로 나눠"),
    # 2026-11-17 실패 검토 ⑤(마스터 '포화도의 정의 수립'): 소매 포화 지수(IRS, LaLonde 1961) = 수요 ÷ 공급
    "sat": ("포화도", r"포화|과포화|레드 ?오션|과밀|가게가 ?너무 ?많|경쟁이 ?(심|치열)"),
}
PLAIN = {  # 기법 → 도민용 쉬운 말(사이드바와 같은 말, 2026-11-14 평가 지적 '도민에게 어려운 통계 용어')
    "corr": "같이 움직이는 정도", "cluster": "비슷한 동네끼리 묶기", "change": "건수와 건당 금액으로 나누기", "decomp": "추세와 계절 나누기",
    "regress": "매출에 미치는 영향", "test": "차이가 우연인지", "dist": "동네 값의 흩어짐", "outlier": "튀는 달 찾기",
    "lq": "이 동네에 몰린 업종", "surv": "몇 년 버티는지", "hhi": "업종이 고르게 섞였는지", "shift": "성장 원인 나누기", "sat": "가게가 넘치는지",
}
METRIC = {  # 지표 → (이름, 질문에서 찾을 말, 단위)
    "sales": ("카드 매출", r"매출|카드|소비", "원"),
    "visit": ("하루 방문", r"방문|유동|인구|사람", "지수"),
    "stores": ("가게 수", r"가게|점포|업체|업소", "곳"),
    "surv": ("5년 생존율", r"생존|폐업", "%"),
    "tour": ("관광객 매출 비중", r"관광객", "%"),
    "sales746": ("카드 매출(746, 2017~2021)", r"$^", "원"),
    # 2026-11-17 실패 검토: 한 동네 안에서 거주 인구와 매출의 상관을 물어도 지표가 없어 다른 상관으로 가던 결함(유동인구 583의 거주·직장 인구)
    "resd": ("거주 인구", r"거주|주민|사는\s*사람|상주", "지수"),
    "work": ("직장 인구", r"직장\s*인구|직장인|근무\s*인구|출근", "지수"),
}
CARD_BIZ = {"음식점": "음식점업", "카페": "음식점업", "한식": "음식점업", "일식": "음식점업", "횟집": "음식점업", "중식": "음식점업",
            "치킨": "음식점업", "분식": "음식점업", "주점": "음식점업", "숙박": "숙박업", "소매": "소매업", "편의점": "소매업"}
STORE_MAJOR = {"음식점업": "음식", "숙박업": "숙박", "소매업": "소매"}
SRC = {"sales": ("제주관광공사 카드 소비", "card_month"), "visit": ("유동인구(제주데이터허브 583)", "pop_month"),
       "stores": ("상가 정보(공공데이터포털)", "biz"), "surv": ("음식점 인허가(행정안전부)", "km"), "tour": ("제주관광공사 카드 소비", "card_month"),
       "sales746": ("제주데이터허브 746 업종별 카드 매출", "card746_month"),
       "resd": ("유동인구(제주데이터허브 583)", "pop_month"), "work": ("유동인구(제주데이터허브 583)", "pop_month")}
NEXT = {"sales": "매달", "visit": "매달", "stores": "분기마다", "surv": "매년", "tour": "매달", "sales746": "갱신 끝남(2021-05)", "resd": "매달", "work": "매달"}


UNAVAIL = re.compile(r"임대료|월세|권리금|평점|리뷰|별점|후기|매장별|점포별|가게별|개별\s*(점포|가게|매장)|단일\s*매장|골목|청년\s*인구|연령|나이|성별|인과|일별\s*(카드\s*)?매출|시간대별\s*매출")


def detect(question):
    """기법 이름이 있으면 기법 키, 없으면 None."""
    q = question or ""
    # 변이할당은 '업종 구성'을 낱말로 품어 업종 다양성(hhi)보다 먼저 본다(2026-11-18 60번 진단: Shift-Share 질문을 hhi로 바꾼 결함)
    for k, (_, pat) in sorted(TECH.items(), key=lambda kv: kv[0] != "shift"):
        if re.search(pat, q):
            return k
    return None


def parse(question):
    """기법·동네·업종·지표·k를 질문에서 뽑는다. 정해진 사전만 쓴다(LLM 없음)."""
    q = question or ""
    dongs = sorted({d for d in Q.DONGS if d in q}, key=q.index)
    target = next((t for t in Q.TARGETS_BIZ if t in q), None)
    metrics = sorted({m for m, (_, pat, _) in METRIC.items() if re.search(pat, q)}, key=lambda m: re.search(METRIC[m][1], q).start())
    if {"resd", "work"} & set(metrics) and "visit" in metrics and not re.search(r"방문|유동|발길|붐비", q):
        metrics.remove("visit")  # '거주 인구'의 '인구'를 방문으로 읽지 않는다
    k = re.search(r"(\d{1,2})\s*개\s*(?:군집|그룹|유형|묶음)", q)
    return {"tech": detect(q), "dongs": dongs, "target": target, "metrics": metrics, "k": int(k.group(1)) if k else None, "q": q}


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
    if metric in ("resd", "work"):  # 거주·직장 인구: 월 합 ÷ 자료 있는 날 수(방문과 같은 하루 평균 지수)
        d = _T()["pop_month"]
        if dong:
            d = d[d.dong == dong]
        d = d.assign(v=d[metric] / d.days.replace(0, np.nan))
        return d.groupby("ym").v.sum().sort_index()
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
    if metric in ("visit", "resd", "work"):
        d = T["pop_month"]
        last = sorted(d.ym.unique())[-12:]
        g = d[d.ym.isin(last)].groupby("dong")[[metric, "days"]].sum()
        return g[metric] / g.days
    if metric == "stores":
        d = T["biz"]
        m = STORE_MAJOR.get(_biz(target) or "")
        if target and target not in ("음식점", "숙박", "소매"):  # 세부 업종(카페·치킨·편의점 등)은 그 분류의 가게만 센다(2026-11-17 쓸모 판정: '치킨 가게 수 중간값 339곳'이 음식점 전체 값이던 결함)
            import v3
            sub = v3.biz_rows(d, target)
            d = sub if len(sub) else (d[d.major == m] if m else d)
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
    if metric in ("visit", "resd", "work"):
        return str(T["pop_month"].ym.max())
    if metric == "stores":
        return "2026-09 단면"
    if metric == "sales746":
        return str(T["card746_month"].ym.max())
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
    if len(p["dongs"]) == 2 and re.search(r"교차|CCF|시계열|월별|시차", p.get("q") or ""):  # 두 동네 월별 시계열의 교차상관(2026-11-17 조정용 R080: 43개 동네 단면 상관으로 답하던 결함)
        return _ccf(p)
    if len(p["dongs"]) == 1:  # 한 동네의 월별 시계열
        dong = p["dongs"][0]
        mm = [x for x in dict.fromkeys(p["metrics"]) if x in ("visit", "sales", "resd", "work")]
        a, b = (mm + [x for x in ("visit", "sales") if x not in mm])[:2]  # 질문이 고른 두 월별 지표(없으면 방문과 매출)
        s1, s2 = monthly(a, dong, p["target"]), monthly(b, dong, p["target"])
        df = pd.concat([s1.rename("x"), s2.rename("y")], axis=1).dropna()
        if len(df) < 12:
            raise Reject(f"두 자료가 겹치는 달이 {len(df)}개월이라 12개월보다 적어요.", "43개 동네를 견주는 상관(동네 이름 없이 질문)을 해 보세요.")
        r, pr = stats.pearsonr(df.x, df.y)
        rs, ps = stats.spearmanr(df.x, df.y)
        dd = df.diff().dropna()
        rd, pd_ = stats.pearsonr(dd.x, dd.y)
        nm = lambda x: (f"{p['target'] or ''} " if x == "sales" else "") + METRIC[x][0]  # noqa: E731
        who = f"{dong} 월별 {nm(a)}{'과' if (ord(nm(a)[-1]) - 0xAC00) % 28 else '와'} {nm(b)}".replace("  ", " ")
        concl = f"{who}의 상관계수는 {r:.2f}이고, 전달 대비 변화량끼리는 {rd:.2f}{_cop(f'{rd:.2f}')}."
        lines = [_line(f"겹치는 {len(df)}개월({df.index[0]}~{df.index[-1]})로 계산했어요.", "표본"),
                 _line(f"Pearson 상관계수 {r:.2f}(p값 {pfmt(pr)}), 순위 상관(Spearman) {rs:.2f}(p값 {pfmt(ps)}).", "상관"),
                 _line(f"추세를 뺀 전달 대비 변화량끼리의 상관은 {rd:.2f}(p값 {pfmt(pd_)}){_cop(f'{rd:.2f}')}. 이 값이 원래 값보다 많이 낮으면 둘이 같은 계절·추세를 탄 영향이 커요.", "차분 상관")]
        nums = {"n": len(df), "pearson": r2(r, 4), "spearman": r2(rs, 4), "diff_pearson": r2(rd, 4)}
        view = _view("scatter", f"{METRIC[a][0]}과 {METRIC[b][0]}(달마다 한 점)", "scatter", {f"{dong}": list(zip(df.x, df.y))}, f"{len(df)}개월", unit=None)
        src = [a, b]
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


def _ccf(p):
    """두 동네의 같은 월별 값(카드 매출·이용 건수·하루 방문)을 전달 대비 변화율로 바꾼 뒤 시차 −3~+3개월의 상관을 잰다."""
    d1, d2 = p["dongs"][:2]
    cnt = bool(re.search(r"건수", p.get("q") or ""))
    metric = "visit" if p["metrics"][:1] == ["visit"] else "sales"
    if cnt:
        cm = _T()["card_month"]
        s1, s2 = (cm[cm.dong == d].groupby("ym").cnt.sum().sort_index() for d in (d1, d2))
        what = "카드 이용 건수"
    else:
        s1, s2 = monthly(metric, d1, p["target"]), monthly(metric, d2, p["target"])
        what = METRIC[metric][0]
    df = pd.concat([s1.rename("a"), s2.rename("b")], axis=1).dropna().astype(float)
    if len(df) < 24:
        raise Reject(f"두 동네 자료가 겹치는 달이 {len(df)}개월이라 24개월보다 적어요.", "두 동네의 값을 비교해 보세요.")
    g = df.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    res = {}
    for k in range(-3, 4):  # k > 0: d1이 k개월 먼저 움직이고 d2가 따라옴
        x, y = g["a"].shift(k), g["b"]
        m = pd.concat([x, y], axis=1).dropna()
        res[k] = stats.pearsonr(m.iloc[:, 0], m.iloc[:, 1]) + (len(m),)
    r0, p0, n0 = res[0]
    kb = max(res, key=lambda k: abs(res[k][0]))
    rb, pb, nb = res[kb]
    lead = "같은 달" if kb == 0 else (f"{d1}이(가) {kb}개월 먼저" if kb > 0 else f"{d2}이(가) {-kb}개월 먼저")
    concl = (f"{d1}과(와) {d2}의 월별 {what} 변화율은 같은 달 상관계수가 {r0:.2f}이고, 몇 달 앞서거나 늦게 따라 움직이는 관계는 이보다 약해요." if kb == 0 else
             f"{d1}과(와) {d2}의 월별 {what} 변화율은 같은 달 상관계수가 {r0:.2f}이고, 가장 큰 상관은 {lead} 움직일 때 {rb:.2f}{_cop(f'{rb:.2f}')}.")
    concl = concl.replace(f"{d1}과(와)", _josa(d1, "과", "와")).replace(f"{d1}이(가)", _josa(d1, "이", "가")).replace(f"{d2}이(가)", _josa(d2, "이", "가"))
    lines = [_line(f"겹치는 {len(df)}개월({df.index[0]}~{df.index[-1]})의 {_josa(what, '을', '를')} 전달 대비 변화율로 바꿔 계산했어요(추세 때문에 생기는 겉보기 상관을 줄이려고).", "표본"),
             _line("시차별 상관(앞 동네가 n개월 먼저): " + ", ".join(f"{k:+d}개월 {res[k][0]:.2f}" for k in res) + ".", "교차상관"),
             _line(f"같은 달 상관의 p값(우연만으로 이만한 결과가 나올 확률, 0.05보다 작으면 우연이 아니라고 봐요)은 {pfmt(p0)}" + ("" if kb == 0 else f", 가장 큰 시차의 p값은 {pfmt(pb)}") + ("이에요." if pfmt(p0 if kb == 0 else pb).endswith("미만") else "예요."), "검정")]
    warn = ["시차 7개를 함께 보면 그중 하나가 우연히 커 보일 수 있어요. 같은 달 값을 먼저 보세요.",
            "상관은 같이 움직이는 정도일 뿐 한 동네가 다른 동네를 움직인다는 뜻이 아니에요. 제주 전체 경기·관광 계절이 두 동네를 함께 움직였을 수 있어요."]
    view = _view("ccf", "시차별 상관", "bar", {"상관계수": [(f"{k:+d}개월", res[k][0]) for k in res]}, f"{d1}·{d2}", unit=None)
    nums = {"n_months": len(df), "r_lag0": r2(r0, 4), "best_lag": kb, "r_best": r2(rb, 4)}
    return concl, lines, warn, [view], nums, ["visit" if metric == "visit" and not cnt else "sales"], (
        "교차상관(CCF)", "두 동네의 월별 값을 전달 대비 변화율로 바꾸고, 한쪽을 −3~+3개월 밀어 가며 상관계수를 재요.",
        "같은 달 상관과 가장 큰 시차의 상관, 각각의 p값을 함께 봐요.",
        "겹치는 달이 24개월보다 적으면 계산하지 않아요.")


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


def _weather_reg(p):
    """비 오는 날 하루 방문 변화(Newey-West 회귀, 2026-11-17 실패 검토 ⑥). app/rain_test.py와 같은 설계:
    동네 × 일 로그 방문 = 비 온 날(1mm 이상) + 요일·연월·공휴일·연휴·명절·방학·강풍·기온(2차) 통제, 표준오차 Newey-West(시차 7).
    카드 매출은 월 단위라 날씨 효과를 계산할 수 없다고 밝힌다."""
    import rain_test as RT
    d = pd.read_parquet(Path(__file__).resolve().parents[1] / "data" / "tables" / "panel_v2.parquet")
    dong = p["dongs"][0] if p["dongs"] else None
    if dong:
        d = d[d.emd == dong].copy()
        who = dong
    else:  # 제주 전체: 날마다 43개 동 방문 합
        g = d.groupby("date").agg(visit=("visit", "sum"), rain=("rain", "first"), temp=("temp", "first"), windy=("windy", "first"), holiday=("holiday", "first"),
                                  long_break=("long_break", "first"), myeongjeol=("myeongjeol", "first"), vacation=("vacation", "first")).reset_index()
        d, who = g.assign(y=np.log(g.visit)), "제주 전체"
    d = d.sort_values("date").reset_index(drop=True)
    d["date"] = pd.to_datetime(d["date"])
    if len(d) < 200:
        raise Reject(f"{who}의 일별 방문 자료가 {len(d)}일이라 날씨 효과를 가리기에 적어요.", "다른 동네로 다시 물어보세요.")
    X = RT.design(d)
    lines, eff = [], {}
    for name, cols in (("wet", [(d["rain"] >= 1).astype(float).rename("wet")]),
                       ("bins", [d["rain"].between(1, 10, inclusive="left").astype(float).rename("r1"), d["rain"].between(10, 30, inclusive="left").astype(float).rename("r2"),
                                 (d["rain"] >= 30).astype(float).rename("r3")])):
        Xi = pd.concat([X] + cols, axis=1)
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore")
            b, se, dfree = RT.ols_nw(d["y"], Xi, lag=RT.LAG)
        for c in cols:
            k = list(Xi.columns).index(c.name)
            pv = stats.norm.sf(abs(b[k] / se[k])) * 2 if se[k] > 0 else 1.0
            eff[c.name] = ((np.exp(b[k]) - 1) * 100, (np.exp(b[k] - 1.96 * se[k]) - 1) * 100, (np.exp(b[k] + 1.96 * se[k]) - 1) * 100, pv, int(c.sum()))
    e, lo, hi, pv, nw = eff["wet"]
    sig = pv < 0.05
    concl = (f"{who} 하루 방문은 비 온 날(1mm 이상, {nw}일) 평소보다 {e:+.1f}%(95% 구간 {lo:+.1f}%~{hi:+.1f}%, p값 {pfmt(pv)})"
             + ("로, 우연으로 보기 어려운 차이예요." if sig else "로, 차이가 있다고 보기 어려워요."))
    if re.search(r"매출|카드|소비|장사", p.get("q") or ""):  # 매출을 물었으면 할 수 없다는 것을 먼저 밝힌다
        concl = "카드 매출은 일별 자료가 없어 날씨가 매출에 주는 영향은 계산할 수 없어요. 대신 하루 방문으로 보면, " + concl
    names = {"r1": "1~10mm", "r2": "10~30mm", "r3": "30mm 이상"}
    lines.append(_line("비의 양별: " + ", ".join(f"{names[k]} {eff[k][0]:+.1f}%(p값 {pfmt(eff[k][3])}, {eff[k][4]}일)" for k in ("r1", "r2", "r3")) + ".", "강수량별"))
    lines.append(_line(f"{len(d)}일({str(d['date'].min().date())}~{str(d['date'].max().date())})로 요일·연월·공휴일·연휴·명절·방학·강풍·기온을 함께 넣어 계산했어요. "
                       "날마다 값이 이어져 생기는 오차는 Newey-West 표준오차(시차 7일)로 바로잡았어요.", "방법", block="analysis", layer="L3"))
    warn = ["카드 매출은 월 단위라 날씨가 매출에 주는 영향은 계산할 수 없어요(일별 카드 매출은 공개 자료에 없음). 위 결과는 하루 방문 지수예요.",
            "강수는 관측소 값의 중앙값이라 동네마다 실제 비와 다를 수 있어요."]
    v = _view("rain", f"{who} 비의 양별 방문 변화(%)", "bar", {"방문 변화(%)": [(names[k], float(eff[k][0])) for k in ("r1", "r2", "r3")]}, "평소(비 안 온 날) 대비")
    nums = {"n_days": len(d), "wet_days": nw, "effect_pct": r2(e, 1), "lo_pct": r2(lo, 1), "hi_pct": r2(hi, 1), "p": r2(pv, 4)}
    return concl, lines, warn, [v], nums, ["visit"], (
        "날씨 회귀(Newey-West)", "동네 × 일 로그 방문을 비 온 날 여부와 달력·기온 통제 변수로 설명하는 최소제곱 회귀", "표준오차는 Newey-West(시차 7일)", "기상 관측과 방문 지수의 측정 한계")


def t_regress(p):
    if re.search(r"강수|강우|비\s*(가\s*)?(오|올|온)|날씨|기온|기상|맑은", p.get("q") or ""):  # 날씨 회귀: 일별 방문으로 계산(2026-11-17 실패 검토 ⑥, 전에는 거절)
        return _weather_reg(p)
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


# ---------------------------------------------------------------- 상권 기법 4종(2026-11-14 추가)
def _biz_shares(dong=None):
    """상가 정보 중분류별 가게 수(동네 또는 제주 전체)."""
    d = _T()["biz"]
    d = d[d.dong == dong] if dong else d
    return d.groupby(["major", "middle"])["count"].sum()


def _want_dong(p, why):
    if not p["dongs"]:
        raise Reject(f"{why} 동네를 정해야 계산할 수 있어요.", "동네 이름을 넣어 다시 물어보세요(예: 노형동 입지계수).")
    return p["dongs"][0]


def _ida(w):
    """받침이 있으면 '이에요', 없으면 '예요'(숫자·괄호로 끝나면 앞 낱말 기준)."""
    c = re.sub(r"[^가-힣]", "", w or "")[-1:] or "가"
    return "이에요" if (ord(c) - 0xAC00) % 28 else "예요"


def t_lq(p):
    """입지계수 LQ = (동네에서 그 업종이 차지하는 비중) ÷ (제주 전체에서 그 업종이 차지하는 비중). 1보다 크면 그 동네에 몰려 있다."""
    dong = _want_dong(p, "입지계수는 한 동네의 업종 구성을 제주 전체와 견주는 값이라")
    loc, tot = _biz_shares(dong), _biz_shares()
    if loc.sum() < 30:
        raise Reject(f"{dong} 가게가 {int(loc.sum())}곳뿐이라 업종 비중이 흔들려요.", "가게가 더 많은 동네로 다시 물어보세요.")
    lq = (loc / loc.sum()) / (tot / tot.sum())
    lq = lq.dropna()
    ok = lq[loc.reindex(lq.index).fillna(0) >= 5]  # 5곳 미만 업종은 한두 곳 차이로 값이 크게 바뀌어 순위에서 뺀다
    top = ok.sort_values(ascending=False).head(5)
    lq_t = None
    if p["target"]:  # 업종을 물었으면 그 업종(상가 정보 기준, cross와 같은 묶음)의 입지계수
        c = cross("stores", p["target"])
        if dong in c.index and c.sum() > 0:
            lq_t = (c[dong] / loc.sum()) / (c.sum() / tot.sum())
    name = f"{dong} 업종 입지계수"
    first = top.index[0]
    concl = f"{dong}에서 제주 전체보다 가장 몰려 있는 업종은 {first[1]}{_ida(first[1])}(입지계수 {top.iloc[0]:.2f})."
    if lq_t is not None:
        eun = "은" if _ida(p["target"]) == "이에요" else "는"
        r_ = round(lq_t, 2)  # 보이는 값과 같은 기준으로 판단한다
        state = "제주 전체보다 몰려 있어요" if r_ > 1.1 else "제주 전체보다 적어요" if r_ < 0.9 else "제주 전체와 비슷해요"
        concl = f"{dong} {p['target']}{eun} {state}(입지계수 {lq_t:.2f}). " + concl
    lines = [_line(f"{dong} 가게 {int(loc.sum()):,}곳, 제주 전체 {int(tot.sum()):,}곳을 업종 중분류 {len(tot)}개로 나눠 비중을 견줬어요.", "기준")]
    for (maj, mid), v in top.items():
        lines.append(_line(f"{mid}: 입지계수 {v:.2f}({dong} {int(loc[(maj, mid)])}곳, 비중 {loc[(maj, mid)] / loc.sum() * 100:.1f}% · 제주 {tot[(maj, mid)] / tot.sum() * 100:.1f}%).", "몰린 업종"))
    warn = ["입지계수는 가게 수 비중만 보므로 매출이나 손님이 많다는 뜻은 아니에요.",
            "1보다 크면 그 동네에 상대적으로 몰려 있다는 뜻이고, 경쟁이 심한지 특화됐는지는 매출·폐업과 함께 봐야 해요.",
            "가게가 5곳 미만인 업종은 순위에서 뺐어요."]
    v = _view("lq", "입지계수 상위 업종", "bar", {"입지계수": [(i[1], x) for i, x in top.items()]}, name)
    nums = {"stores_dong": int(loc.sum()), "lq_top": r2(top.iloc[0])} | ({"lq_target": r2(lq_t)} if lq_t is not None else {})
    return concl, lines, warn, [v], nums, ["stores"], (
        "입지계수(LQ)", "업종별로 (동네 비중) ÷ (제주 전체 비중)을 구해요. 1보다 크면 그 동네에 몰려 있어요.",
        "동네·제주 전체의 가게 수와 비중을 함께 봐요.", "가게가 30곳 미만인 동네는 계산하지 않아요.")


def t_sat(p):
    """포화도: 가게 1곳당 수요(소매 포화 지수 IRS = 수요 ÷ 공급)를 43개 동네 중간값과 견준다. 1보다 작을수록 가게가 수요보다 많다(포화 쪽).
    수요: 카드 매출을 업종으로 나눌 수 있는 대분류(음식점·소매·숙박, 전 업종)는 최근 12개월 카드 매출, 세부 업종(카페 등)은 하루 방문(대리값)."""
    import v3
    tgt = p.get("target")
    sub_ok = bool(tgt) and tgt not in ("음식점", "숙박", "소매")
    stores = cross("stores", tgt)
    if sub_ok:
        dem, dname, unit = cross("visit"), "하루 방문", "지수"
    else:
        dem, dname, unit = cross("sales", tgt), "최근 12개월 카드 매출", "원"
    df = pd.concat([dem.rename("d"), stores.rename("s")], axis=1).dropna()
    df = df[(df.s >= 5) & ~df.index.isin(["우도면", "추자면"])]  # 가게가 5곳 미만인 동네와 섬 2곳(표본 적음, 사용자 확정 2026-11-06 6번)은 뺀다
    if len(df) < 10:
        raise Reject(f"가게가 5곳 이상인 동네가 {len(df)}곳뿐이라 견줄 수 없어요.", "업종 없이 다시 물어보세요.")
    df["per"] = df.d / df.s
    med = df.per.median()
    df["idx"] = df.per / med
    df = df.sort_values("idx")
    word = lambda x: "포화 쪽(가게에 비해 수요가 적음)" if x < 0.8 else ("여유 쪽(가게에 비해 수요가 많음)" if x > 1.25 else "중간")  # noqa: E731
    who = tgt or "전 업종"
    per_txt = lambda v: f"{v / 1e8:,.2f}억 원" if unit == "원" else f"{v:,.0f}"  # noqa: E731
    lines, nums = [], {"n": len(df), "median_per": r2(med, 2)}
    if p["dongs"]:
        d = p["dongs"][0]
        if d not in df.index:
            raise Reject(f"{d} {who} 가게가 5곳보다 적거나 자료가 없어요.", "다른 동네로 다시 물어보세요.")
        r = df.loc[d]
        rank = int((df.idx < r.idx).sum() + 1)
        concl = f"{d} {who} 포화도 지수는 {r.idx:.2f}로 {word(r.idx)}이에요(제주 {len(df)}개 동네 중 포화가 심한 순서로 {rank}위)."
        lines.append(_line(f"{d} {who} 가게 {int(r.s):,}곳, 가게 1곳당 {dname} {per_txt(r.per)}(43개 동네 중간값 {per_txt(med)}).", "포화도"))
        nums.update({"dong_idx": r2(r.idx, 2), "rank": rank})
    else:
        top = df.head(3)
        concl = f"{who} 포화도 지수가 가장 낮은(가게에 비해 수요가 적은) 동네는 " + ", ".join(f"{i}({v:.2f})" for i, v in top.idx.items()) + "예요."
        nums.update({"min_idx": r2(df.idx.iloc[0], 2)})
    lines.append(_line(f"포화도 지수 = (가게 1곳당 {dname}) ÷ (43개 동네 중간값). 1보다 작으면 수요에 비해 가게가 많은 편이에요.", "읽는 법", block="analysis", layer="L3"))
    warn = ["소매 포화 지수(IRS = 수요 ÷ 매장 공급)를 공개 자료로 근사한 값이에요. 매장 면적 대신 가게 수를 썼어요."]
    if sub_ok:
        warn.append(f"{tgt}만의 카드 매출 자료가 없어 수요는 하루 방문 지수로 대신 봤어요. 방문은 지출이 아니라 수요의 대리값이에요.")
    v = _view("sat", f"{who} 포화도 지수(낮을수록 포화)", "bar", {"포화도 지수": [(i, float(x)) for i, x in df.idx.head(10).items()]}, "1보다 작으면 포화 쪽")
    return concl, lines, warn, [v], nums, (["stores", "visit"] if sub_ok else ["stores", "sales"]), (
        "포화도(소매 포화 지수 근사)", f"동네마다 '{dname} ÷ {who} 가게 수'를 구하고 43개 동네 중간값으로 나눠요.",
        "가게가 5곳 미만인 동네와 우도면·추자면은 빼요.", "가게 수는 2025 단면, 수요는 최근 12개월 값이라 시점이 조금 달라요.")


def t_hhi(p):
    """업종 다양성 = 1 − Σ(업종 비중²)(허핀달 지수를 뒤집은 값). 클수록 여러 업종이 고르게 섞여 있다."""
    d = _T()["biz"].groupby(["dong", "middle"])["count"].sum()
    share = d / d.groupby(level=0).transform("sum")
    hhi = (share ** 2).groupby(level=0).sum()
    div = (1 - hhi) * 100
    eff = 1 / hhi
    rank = div.rank(ascending=False).astype(int)
    if p["dongs"]:
        dong = p["dongs"][0]
        if dong not in div.index:
            raise Reject(f"{dong} 상가 자료가 없어요.", "다른 동네로 다시 물어보세요.")
        concl = f"{dong}의 업종 다양성은 {div[dong]:.1f}점(43곳 중 {rank[dong]}위)이고, 고르게 섞였다면 업종 {eff[dong]:.0f}개에 해당하는 구성이에요."
        hl = [dong]
    else:
        top = div.sort_values(ascending=False)
        concl = f"업종이 가장 고르게 섞인 동네는 {top.index[0]}({top.iloc[0]:.1f}점), 가장 쏠린 동네는 {top.index[-1]}({top.iloc[-1]:.1f}점)이에요."
        hl, dong = [top.index[0], top.index[-1]], None
    lines = [_line(f"업종 중분류별 가게 비중의 제곱합(허핀달 지수)을 1에서 빼 100점으로 바꿨어요. 43곳 중간값 {div.median():.1f}점.", "기준")]
    if dong:
        sub = share[dong].sort_values(ascending=False).head(3)
        lines.append(_line(f"{dong}에서 비중이 큰 업종: " + ", ".join(f"{k} {v * 100:.1f}%" for k, v in sub.items()) + ".", "쏠린 업종"))
    warn = ["중분류가 많아 대부분 동네가 높은 점수에 몰려 있으니, 점수 자체보다 동네끼리 견주는 데 쓰세요.",
            "다양성이 높다고 상권이 좋다는 뜻은 아니에요. 관광지처럼 한두 업종에 특화된 곳은 점수가 낮게 나와요."]
    v = _view("hhi", "동네별 업종 다양성(점)", "bar", {"다양성": sorted(div.items(), key=lambda x: -x[1])}, "43개 동네", values=div.to_dict(), highlight=hl)
    nums = {"diversity": r2(div[dong], 1) if dong else r2(div.max(), 1), "median": r2(div.median(), 1)} | ({"rank": int(rank[dong])} if dong else {})
    return concl, lines, warn, [v], nums, ["stores"], (
        "업종 다양성(허핀달 지수 역수)", "업종 중분류 비중의 제곱합(HHI)을 구해 1에서 빼고 100을 곱해요.",
        "43개 동네의 중간값과 순위를 함께 봐요.", "상가 정보 단면(2026-09) 한 시점만 써요.")


def t_surv(p):
    """카플란-마이어 생존 곡선(음식점 인허가, 개업 뒤 1~5년 영업을 이어 간 비율과 95% 신뢰구간)."""
    k = _T()["km"]
    dongs = p["dongs"][:2] or []
    names = dongs + ["제주 전체"] if "제주 전체" in set(k.dong) else dongs
    if not dongs:
        names = ["제주 전체"]
    have = [n for n in names if n in set(k.dong)]
    if not have:
        raise Reject("생존 곡선 자료가 없는 동네예요.", "다른 동네로 다시 물어보세요.")
    pts, lines = {}, []
    for n in have:
        g = k[k.dong == n].sort_values("year")
        pts[n] = list(zip(g.year.astype(str) + "년", g.survival_pct))
        y5 = g[g.year == g.year.max()].iloc[0]
        lab = f" · {y5.label}" if y5.label else ""
        lines.append(_line(f"{n}: 1년 {g.survival_pct.iloc[0]:.1f}% → {int(y5.year)}년 {y5.survival_pct:.1f}%(95% 구간 {y5.lo_pct:.1f}~{y5.hi_pct:.1f}%, 개업 {int(y5.n):,}곳){lab}.", "생존율"))
    main = have[0]
    g = k[(k.dong == main) & (k.year == k.year.max())].iloc[0]
    concl = f"{main} 음식점은 개업 뒤 {int(g.year)}년까지 {g.survival_pct:.1f}%가 영업을 이어 갔어요(카플란-마이어 추정)."
    warn = ["음식점 인허가 자료라 카페·주점 등 음식점 업태만 포함해요. 다른 업종의 생존율은 아니에요.",
            "자료 기간 안에 문을 닫지 않은 가게는 '아직 영업 중'으로 처리해(중도 절단) 생존 곡선에 반영했어요.",
            "구간이 서로 겹치면 두 동네의 차이를 확인하지 못한 거예요."]
    v = _view("surv", "개업 뒤 영업을 이어 간 비율(%)", "line", pts, " · ".join(have), unit="%")
    nums = {"surv_last_pct": r2(g.survival_pct, 1), "lo_pct": r2(g.lo_pct, 1), "hi_pct": r2(g.hi_pct, 1), "n": int(g.n)}
    return concl, lines, warn, [v], nums, ["surv"], (
        "카플란-마이어 생존분석", "해마다 '그해 초 영업 중인 가게 가운데 그해를 넘긴 비율'을 곱해 생존 곡선을 구하고, 95% 신뢰구간을 붙여요.",
        "제주 전체 곡선과 신뢰구간이 겹치는지 봐요.", "음식점 인허가 자료만 써요.")


def t_shift(p):
    """변이할당 분석: 동네 매출 변화 = 제주 전체 성장 효과 + 업종 구성 효과 + 동네 고유 효과(746 카드, 업종 42)."""
    dong = _want_dong(p, "변이할당은 한 동네의 성장을 제주 전체와 견주어 나누는 기법이라")
    d = _T()["card746_month"]
    d = d.assign(y=d.ym.str[:4])
    full = d[d.y.isin(["2017", "2019"])].groupby("y").amt.sum()  # 제주 전체 성장률 G는 업종을 한정해도 모든 업종으로 잰다
    tgt, scope = p.get("target"), ""
    import qparse as _qp
    det = _qp.find_detail(p.get("q") or "")
    if det and not tgt:  # '베이커리'처럼 업종 칸에 없는 세부 업종: 동네 전체로 계산하지 않고 밝힌다(2026-11-17 067)
        raise Reject(f"746 카드 자료에는 {det['word'] if isinstance(det, dict) else det}만 따로 나뉜 업종이 없어요(카페·한식·일식·중식·주점 등만 있음).", "업종 없이 동네 전체로, 또는 음식점 전체로 다시 물어보세요.")
    if tgt:  # 업종 한정(2026-11-17 실패 검토: 업종을 물었는데 동네 전체로 계산하던 결함). 세부 업종은 746의 해당 분류, 대분류는 그 대분류 전체
        import v3
        if tgt in v3.BIZ42:
            d = d[d.biz42.str.startswith(v3.BIZ42[tgt])]
        elif tgt in ("음식점", "소매", "숙박") and _biz(tgt):
            d = d[d.biz == _biz(tgt)]
        else:
            raise Reject(f"746 카드 자료에는 {tgt}만 따로 나뉜 업종이 없어요(카페·한식·일식·중식·주점 등만 있음).", "업종 없이 동네 전체로, 또는 음식점 전체로 다시 물어보세요.")
        if d.empty:
            raise Reject(f"{tgt}만의 746 카드 자료가 없어요.", "업종 없이 동네 전체로 다시 물어보세요.")
        scope = f" {tgt}"
    y0, y1 = "2017", "2019"  # 1년 단위 완결 자료 중 코로나 이전 처음과 끝(2020년 이후는 코로나 충격이라 기본값에서 뺌)
    g = d[d.y.isin([y0, y1])].groupby(["y", "dong", "biz42"]).amt.sum()
    jeju = g.groupby(level=["y", "biz42"]).sum()
    if (y0, dong) not in g.index.droplevel(2):
        raise Reject(f"{dong}의 746 카드 자료가 없어요.", "다른 동네로 다시 물어보세요.")
    e0, e1 = g[y0][dong], g[y1][dong].reindex(g[y0][dong].index).fillna(0)
    j0, j1 = jeju[y0], jeju[y1].reindex(jeju[y0].index).fillna(0)
    G = full["2019"] / full["2017"] - 1
    gi = (j1 / j0 - 1).reindex(e0.index)
    ri = (e1 / e0.replace(0, np.nan) - 1).fillna(0)
    ns, im, rs = (e0 * G).sum(), (e0 * (gi - G)).sum(), (e0 * (ri - gi)).sum()
    tot = e1.sum() - e0.sum()
    rs_i = (e0 * (ri - gi)).sort_values()
    concl = (f"{dong}{scope} 카드 매출은 {y0}→{y1}년 {fmt(tot, 'sales746')} 변했어요. 나눠 보면 {dong}{scope}의 제주 전체 성장 효과 {fmt(ns, 'sales746')}, "
             f"업종 구성 효과 {fmt(im, 'sales746')}, 동네 고유 효과 {fmt(rs, 'sales746')}이에요.")
    lines = [_line(f"{y0}년 {fmt(e0.sum(), 'sales746')} → {y1}년 {fmt(e1.sum(), 'sales746')}. 같은 기간 제주 전체 {G * 100:+.1f}%.", "매출 변화"),
             _line(f"동네 고유 효과가 가장 큰 업종: {rs_i.index[-1]}({fmt(rs_i.iloc[-1], 'sales746')}), 가장 작은 업종: {rs_i.index[0]}({fmt(rs_i.iloc[0], 'sales746')}).", "업종별 고유 효과", block="analysis", layer="L3")]
    warn = ["746 카드 자료는 2021-05에 갱신이 끝났고, 관광공사 카드 자료와 카드사가 달라 금액을 이어 붙이지 않았어요.",
            "동네 고유 효과는 '업종 구성으로 설명되지 않는 나머지'라 원인(입지·상권 변화 등)은 따로 확인해야 해요.",
            "코로나 충격을 피하려고 2017년과 2019년을 견줬어요."]
    v = _view("shift", "매출 변화의 세 효과", "bar", {"효과": [("제주 전체 성장", ns), ("업종 구성", im), ("동네 고유", rs)]}, dong, unit="원")
    nums = {"total": r2(tot, 0), "national": r2(ns, 0), "mix": r2(im, 0), "local": r2(rs, 0), "jeju_growth_pct": r2(G * 100, 1)}
    return concl, lines, warn, [v], nums, ["sales746"], (
        "변이할당 분석(shift-share)", "업종별로 '기준 매출 × 제주 전체 성장률', '기준 매출 × (업종 성장률 − 제주 성장률)', '기준 매출 × (동네 업종 성장률 − 제주 업종 성장률)'을 더해요.",
        "세 효과의 합이 실제 변화와 같은지 봐요.", "2017·2019년 두 해만 견줘요.")


RUN = {"change": t_change, "corr": t_corr, "cluster": t_cluster, "decomp": t_decomp, "regress": t_regress, "test": t_test, "dist": t_dist, "outlier": t_outlier,
       "lq": t_lq, "surv": t_surv, "hhi": t_hhi, "shift": t_shift, "sat": t_sat}
EXAMPLES = {"change": "노형동 음식점 매출 변화를 건수와 건당 금액으로 분해해줘", "corr": "43개 동네 방문과 매출의 상관 분석해줘", "cluster": "43개 동네를 군집분석 해줘", "decomp": "노형동 음식점 월 매출 시계열 분해해줘",
            "regress": "동네별 매출에 방문과 가게 수가 미치는 영향 회귀분석해줘", "test": "노형동과 연동 음식점 매출이 통계적으로 차이 있어?",
            "dist": "43개 동네 음식점 매출 분포 보여줘", "outlier": "제주 전체 음식점 매출에서 튀는 달 찾아줘",
            "lq": "노형동 업종별 입지계수 구해줘", "surv": "노형동 음식점 생존 곡선 분석해줘", "hhi": "노형동 업종 다양성 지수 알려줘",
            "shift": "노형동 카드 매출 변이할당 분석해줘", "sat": "노형동 카페 포화도 알려줘"}


# ---------------------------------------------------------------- 답 묶기
# 전문 용어 풀이(2026-11-16 문제 기록 18번, 057 2-4 'p값·Z점수 같은 전문 용어'): 답에서 처음 나올 때 한 번만 괄호로 쉬운 말을 붙인다.
GLOSS = [("p값", "우연만으로 이만한 결과가 나올 확률, 0.05보다 작으면 우연이 아니라고 봐요"),
         ("Pearson 상관계수", "두 값이 함께 커지고 작아지는 정도, -1~1"),
         ("R²", "동네 사이 차이 가운데 고른 변수로 설명되는 몫, 0~1"),
         ("VIF", "설명 변수끼리 겹치는 정도, 10을 넘으면 믿기 어려워요"),
         ("실루엣", "묶음이 잘 나뉜 정도, 1에 가까울수록 잘 나뉨"),
         ("Wilcoxon", "짝 지은 두 값의 차이가 한쪽으로 쏠렸는지 보는 검정"),
         ("표준오차", "계수가 흔들리는 폭"),
         ("입지계수", "제주 전체보다 몰린 정도, 1보다 크면 더 몰림"),
         ("왜도", "한쪽으로 쏠린 정도, 0이면 좌우 대칭"),
         ("카플란-마이어", "아직 영업 중인 가게도 반영하는 생존율 계산법"),
         ("허핀달 지수", "업종이 한쪽에 몰린 정도"),
         ("Shapiro", "값이 종 모양 분포인지 보는 검정")]


def gloss(texts):
    """문장 목록에서 용어가 처음 나온 자리에만 '(풀이)'를 붙인다. 이미 괄호 풀이가 붙어 있으면 건너뛴다."""
    done, out = set(), []
    for t in texts:
        for term, plain in GLOSS:
            if term in done or term not in t:
                continue
            i = t.index(term) + len(term)
            if not t[i:i + 1] == "(":
                t = t[:i] + f"({plain})" + t[i:]
            done.add(term)
        out.append(t)
    return out


def answer(question, slots=None):
    """기법 질문 하나의 답(기존 /api/ask 응답 형식)."""
    p = parse(question)
    if slots and slots.get("method") in RUN:
        p["tech"] = slots["method"]
        p["dongs"] = slots.get("space") or p["dongs"]
        p["target"] = slots.get("target") or p["target"]
        if "k" in slots:  # 조건에 맞게 고친 군집 수(분석 담당 Agent ② 대안, 2026-11-16)
            p["k"] = slots["k"]
        if slots.get("metrics"):  # 조건에 맞게 줄인 지표(회귀 설명 변수 3개 이하)
            p["metrics"] = list(slots["metrics"])
    p["q"] = question or ""
    tech = p["tech"]
    tname = TECH[tech][0]
    who = " · ".join(x for x in [", ".join(p["dongs"]) or None, p["target"], "·".join(METRIC[m][0] for m in p["metrics"]) or None] if x)
    understood = {"text": f"이렇게 이해했어요: {tname}({PLAIN[tech]}) 분석{(' — ' + who) if who else ''}", "by": "기법 사전", "assumed": False,
                  "slots": {"topic": "technique", "method": tech, "space": p["dongs"], "target": p["target"]}, "notes": []}
    others = [k for k in RUN if k != tech][:3]
    sugg = [{"text": EXAMPLES[k], "slots": {"topic": "technique", "method": k}} for k in others]
    try:
        miss = UNAVAIL.search(p["q"] or "")
        if miss:  # 공개 자료에 없는 변수를 넣어 달라는 요청은 다른 변수로 바꿔 계산하지 않는다(2026-11-17 새 문항 067 조정용)
            raise Reject(f"공개 자료에는 '{miss.group(0)}' 값이 없어 이 변수로는 {tname} 분석을 할 수 없어요.",
                         "동네 단위의 가게 수·카드 매출·하루 방문·생존율로 바꿔 다시 물어보세요.")
        concl, lines, warn, views, nums, used, (mtitle, how, check, limit) = RUN[tech](p)
        g = gloss([concl] + [x["text"] for x in lines] + list(warn))
        concl, warn = g[0], g[1 + len(lines):]
        for x, t in zip(lines, g[1:1 + len(lines)]):
            x["text"] = t
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
    a = {"conclusion": {"text": concl, "layer": "L3", "tag": f"Agent 계산 · {tname}({PLAIN[tech]})"}, "blocks": blocks, "views": views, "default_views": len(views),
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
            "downloads": [{"kind": "bundle", "name": "이 답의 계산값.csv", "rows": len(rows) - 1, "export": "집계", "csv": csv}],
            "numbers": nums}  # 상세 분석 도구(run_technique)가 숫자 대조에 쓴다
