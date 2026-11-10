"""고정 도구 5종. 입력이 같으면 항상 같은 결과를 낸다. LLM은 도구 이름과 파라미터만 고른다.

data/tables/만 읽는다. 각 도구는 summary(문장 목록, 규칙 모드 답변에도 씀), values, period, sources, limits를 돌려준다.
표시 규칙(docs/조사/06_EDA_H1H3.md 사용자 확정): 폐업·생존은 순위 없이 값 + 95% 구간 + 표본 수,
우도면·추자면은 순위에서 빼고 표본 적음 표시, 583 값은 사람 수가 아니라 지수.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

TABLES = Path(__file__).resolve().parents[1] / "data" / "tables"
ISLANDS = {"우도면", "추자면"}
SMALL_NOTE = "표본 적음: 섬 지역이라 순위에서 뺐다."
L_793 = "상가 793은 단일 시점 자료다."
L_780 = "음식점 780은 음식점만 담고, 인허가 자료라 실제 영업 여부와 다를 수 있다."
L_583 = "유동인구 583은 API 문서에도 값의 집계 단위 설명이 없어 사람 수가 아니라 비율 지수로만 쓴다. 손님 수가 아니다."
L_743 = "버스 743은 정류소 이름으로 동네를 연결했다. 2024년 이용자의 0.37%는 연결되지 않아 빠졌고, 7.06%는 동 경계·같은 이름이라 후보 동네에 나눠 배분했다."
L_WX = "날씨는 제주 전체 관측소 중앙값 기준 과거 패턴이다. 예측이 아니며, 국지성 비는 반영하지 못한다."
SYNONYM = {"커피": "카페", "커피숍": "카페", "까페": "카페", "찻집": "카페", "다방": "카페", "식당": "음식", "음식점": "음식", "숙소": "숙박", "호텔": "숙박",
           "펜션": "숙박", "치킨": "치킨", "횟집": "횟집", "미용": "미용", "약국": "약국", "병원": "의원", "학원": "학원", "편의점": "편의점"}
REST_MAP = {"카페": ["커피숍", "까페", "다방", "전통찻집", "키즈카페", "떡카페", "라이브카페"], "한식": ["한식", "식육(숯불구이)", "탕류(보신용)", "냉면집"],
            "일식": ["일식", "횟집", "복어취급"], "횟집": ["횟집"], "중식": ["중국식"], "치킨": ["통닭(치킨)", "호프/통닭"], "분식": ["분식", "김밥(도시락)"],
            "주점": ["호프/통닭", "정종/대포집/소주방", "감성주점"], "편의점": ["편의점"], "음식": None}
METRIC_LABEL = {"점포수": "점포 수(곳)", "숙박특화계수": "숙박 특화계수", "음식특화계수": "음식 특화계수", "소매특화계수": "소매 특화계수", "방문거주비": "방문/거주 지수", "근무거주비": "근무/거주 지수",
                "고령비중": "거주 인구 지수 중 60대 이상 비중(%)", "청년비중": "거주 인구 지수 중 20~30대 비중(%)", "버스일평균": "버스 일평균 이용(명)", "경로비중": "버스 이용자 중 경로 비중(%)", "경로일평균": "버스 경로 이용 일평균(명)",
                "업종점포수": "점포 수(곳)", "업종특화계수": "특화계수"}
CATEGORY_METRICS = {"업종점포수", "업종특화계수"}
RANK_METRICS = {"업종점포수", "업종특화계수", "점포수", "숙박특화계수", "음식특화계수", "소매특화계수", "방문거주비", "근무거주비", "고령비중", "청년비중", "버스일평균", "경로비중", "경로일평균"}
NO_RANK = {"폐업률", "5년생존율"}


@lru_cache(maxsize=None)
def T(name):
    return pd.read_parquet(TABLES / f"{name}.parquet")


@lru_cache(maxsize=None)
def meta():
    return json.loads((TABLES / "meta.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def places():
    return json.loads((TABLES / "places.json").read_text(encoding="utf-8"))


def dongs():
    return meta()["dongs"]


def resolve(name):
    """지명 → 행정동. 돌려주는 값: {"dong": 이름} 또는 {"candidates": [...]} 또는 {"error": ...}."""
    n = re.sub(r"\s", "", str(name or ""))
    if n in dongs():
        return {"dong": n}
    if n in places():
        c = places()[n]
        return {"dong": c[0]} if len(c) == 1 else {"candidates": c}
    return {"error": f"지명을 찾지 못함: {name}"}


def find_places(text):
    """질문에서 지명을 찾는다. 긴 이름부터 찾아 지운다('이도2동' 안의 짧은 이름 오인 방지)."""
    names = sorted(set(dongs()) | set(places()), key=len, reverse=True)
    t, found = str(text), []
    for n in names:
        if len(n) >= 2 and n in t:
            found.append((t.index(n), n))
            t = t.replace(n, " " * len(n))
    return [n for _, n in sorted(found)]


def _one(x, d=1):
    return round(float(x), d)


LABEL_TEXT = {"차이 확인 안 됨": "제주 평균과 뚜렷한 차이가 확인되지 않았습니다", "제주 평균보다 높음": "제주 평균보다 높습니다", "제주 평균보다 낮음": "제주 평균보다 낮습니다"}


def _change(pct):
    return f"{abs(pct)}% 늘었습니다" if pct > 0 else (f"{abs(pct)}% 줄었습니다" if pct < 0 else "같습니다")


def _position(series, dong):
    """동네 분포상 위치(섬 제외 사분위). 고정 임계값이 아니다."""
    s = series.drop(labels=[d for d in ISLANDS if d in series.index]).dropna()
    if dong in ISLANDS or dong not in s.index:
        return "표본 적음"
    q1, q3 = s.quantile(.25), s.quantile(.75)
    if q1 == q3:  # 드문 업종처럼 대부분 값이 같으면 사분위로 나눌 수 없다(값이 0인 동네가 상위로 잡히던 오류)
        return "상위 25%" if s[dong] > q3 else ("하위 25%" if s[dong] < q1 else "대부분 동네와 같음")
    if s[dong] >= q3:
        return "상위 25%"
    return "하위 25%" if s[dong] <= q1 else "중간 50%"


def _lq_major():
    b = T("biz").pivot_table(index="dong", columns="major", values="count", aggfunc="sum", fill_value=0)
    return b.div(b.sum(1), axis=0) / (b.sum(0) / b.values.sum())


def _store_count():
    return T("biz").groupby("dong")["count"].sum()


POP_YEARS = (2023, 2024, 2025)  # 583 수집 연도
BUS_YEARS = tuple(range(2019, 2026))  # 743 제공 연도


def _pop_ratio(year=2024):
    a = T("pop_age")
    g = a[a["year"] == year].groupby("dong")[["resd", "visit", "work"]].sum()
    return pd.DataFrame({"visit": g["visit"] / g["resd"], "work": g["work"] / g["resd"]})


def _age_share(year=2024):
    a = T("pop_age")
    t = a[a["year"] == year].pivot_table(index="dong", columns="ageGroup", values="resd", aggfunc="sum")
    return pd.DataFrame({"old": (t["60대"] + t["70대이상"]) / t.sum(1) * 100, "young": (t["20대"] + t["30대"]) / t.sum(1) * 100})


def _bus_year(year):
    m = T("bus_month")
    m = m[m["ym"].str[:4] == str(year)]
    days = m.drop_duplicates("ym")["days"].sum()
    return m, days


def _bus_daily(year=2024):
    m, days = _bus_year(year)
    return m.groupby("dong")["n"].sum() / days


def _pop_span(year):
    """583이 그해 일부만 있으면 (첫날, 끝날, 일수)를, 1년 전체면 None을 돌려준다. 기간은 meta의 pop_first·pop_last로 자른다."""
    m = meta()
    n = m["pop_days_by_year"].get(str(year), 0)
    if n >= (366 if year % 4 == 0 else 365):
        return None
    first = max(pd.Timestamp(m["pop_first"]), pd.Timestamp(year, 1, 1))
    last = min(pd.Timestamp(m["pop_last"]), pd.Timestamp(year, 12, 31))
    return first, last, n


def _md(t):
    return f"{t.month}월 {t.day}일"


def _pop_note(year=2024):
    """1년 전체가 아닌 해는 답변 한계에 기간과 그 이유를 밝힌다."""
    span = _pop_span(year)
    if span is None:
        return ""
    first, last, n = span
    why = f"583은 {meta()['pop_last']}까지 제공되어" if last.year == year and last.month < 12 else f"583은 {meta()['pop_first']}부터 수집해"
    return f"{why} {year}년 값은 {_md(first)}~{_md(last)}({n}일) 기준이다."


def _pop_year(year=2024):
    """1년 전체가 아닌 해는 문장 안에 기간을 밝힌다(접힘 상자의 한계만으로는 놓친다, 이중 검토 009)."""
    span = _pop_span(year)
    return f"{year}년" if span is None else f"{year}년({_md(span[0])}~{_md(span[1])})"


def _small(d):
    return " (표본 적음)" if d in ISLANDS else ""


def _result(tool, dong, summary, values, period, sources, limits, **extra):
    return {"tool": tool, "dong": dong, "summary": summary, "values": values, "period": period, "sources": sources, "limits": [x for x in limits if x], **extra}


def _need_dong(name):
    r = resolve(name)
    if "dong" in r:
        return r["dong"], None
    if "candidates" in r:
        return None, {"error": f"{name}은 행정동 여러 곳에 걸쳐 있다", "candidates": r["candidates"]}
    return None, {"error": r["error"], "hint": "제주 행정동 43곳 또는 법정동·리 이름으로 물어보세요"}


def dong_profile(dong):
    """동네 요약 카드: 상권·생존·인구·교통."""
    d, err = _need_dong(dong)
    if err:
        return err
    stores = _store_count()
    lq = _lq_major().loc[d].sort_values(ascending=False)
    top = [{"major": k, "lq": _one(v, 2)} for k, v in lq.head(2).items()]
    close = T("close_3y").set_index("dong").loc[d]
    km = T("km").query("year == 5").set_index("dong")
    k5 = km.loc[d]
    ratio, age = _pop_ratio(), _age_share()
    bus = _bus_daily()
    has_bus = d in bus.index
    m24, days = _bus_year(2024)
    badges = {"상권 규모": _position(stores, d), "상권 지속": "표본 적음" if d in ISLANDS else k5["label"], "거주 대비 방문": _position(ratio["visit"], d),
              "대중교통": _position(bus, d) if has_bus else "자료 없음"}
    s = [f"{d}의 점포는 {int(stores[d]):,}곳이고, 특화계수(제주 평균 = 1)가 가장 높은 업종은 {top[0]['major']}({top[0]['lq']})입니다.",
         f"음식점 3년 폐업률(2022~2024)은 {_one(close['rate_pct'])}%(95% 구간 {_one(close['lo_pct'])}~{_one(close['hi_pct'])}%)이고, {LABEL_TEXT[close['label']]}{_small(d)}.",
         f"음식점 5년 생존율은 {_one(k5['survival_pct'])}%(95% 구간 {_one(k5['lo_pct'])}~{_one(k5['hi_pct'])}%, 표본 {int(k5['n'])}건)이고, {LABEL_TEXT[k5['label']]}{_small(d)}.",
         f"{_pop_year()} 방문/거주 지수는 {_one(ratio.loc[d, 'visit'], 2)}, 거주 60대 이상 비중은 {_one(age.loc[d, 'old'])}%입니다."]
    if has_bus:
        s.append(f"2024년 버스 일평균 이용은 {_one(bus[d]):,}명입니다.")
    limits = [L_793, L_780, L_583, _pop_note(), L_743, SMALL_NOTE if d in ISLANDS else ""]
    values = {"stores": int(stores[d]), "top_lq": top, "close_3y_pct": _one(close["rate_pct"]), "close_3y_lo": _one(close["lo_pct"]), "close_3y_hi": _one(close["hi_pct"]),
              "close_3y_n": int(close["store_years"]), "close_label": close["label"], "survival_5y_pct": _one(k5["survival_pct"]), "survival_lo": _one(k5["lo_pct"]),
              "survival_hi": _one(k5["hi_pct"]), "survival_n": int(k5["n"]), "survival_label": k5["label"], "visit_index": _one(ratio.loc[d, "visit"], 2),
              "work_index": _one(ratio.loc[d, "work"], 2), "old_pct": _one(age.loc[d, "old"]), "young_pct": _one(age.loc[d, "young"]), "bus_daily": _one(bus[d]) if has_bus else None}
    return _result("dong_profile", d, s, values, {"상권": "2025-09 단면", "폐업": "2022~2024", "생존": "2015-01~2020-08 개업", "인구·버스": "2024"},
                   ["793", "780", "583", "743+612"], limits, badges=badges)


def _match_biz(category):
    c = str(category or "").strip()
    c = SYNONYM.get(c, c)
    b = T("biz")
    for level in ["minor", "middle", "major"]:
        exact = b[b[level] == c]
        if len(exact):
            return exact, level, c
    for level in ["minor", "middle", "major"]:
        part = b[b[level].str.contains(re.escape(c), regex=True)]
        if len(part) and c:
            return part, level, c
    return None, None, c


def biz_diagnostic(dong, category=None, start_year=2023, end_year=2024):
    """업종 점포 수·특화계수 + 음식점 개업·폐업·영업 지속."""
    d, err = _need_dong(dong)
    if err:
        return err
    start_year, end_year = int(start_year), int(end_year)
    if start_year > end_year:
        return {"error": "시작 연도가 끝 연도보다 늦다"}
    if end_year > int(meta()["rest_last"][:4]):
        return {"error": f"{end_year}년 개업·폐업 자료 없음", "hint": f"음식점 이력은 {meta()['rest_last']}까지 있습니다"}
    biz = T("biz")
    all_dong, all_jeju = biz[biz["dong"] == d]["count"].sum(), biz["count"].sum()
    s, values, limits = [], {"stores_all": int(all_dong)}, [L_793, L_780]
    key = None
    if category:
        hit, level, key = _match_biz(category)
        if hit is None:
            return {"error": f"업종을 찾지 못함: {category}", "hint": "카페, 한식, 숙박, 소매 같은 업종으로 물어보세요"}
        n, nj = int(hit[hit["dong"] == d]["count"].sum()), int(hit["count"].sum())
        share = n / all_dong * 100
        lq = (n / all_dong) / (nj / all_jeju)
        byd = hit.groupby("dong")["count"].sum().reindex(dongs()).fillna(0) / biz.groupby("dong")["count"].sum().reindex(dongs())
        pos = _position(byd, d)
        values.update(category=key, stores=n, share_pct=_one(share), lq=_one(lq, 2), jeju_share_pct=_one(nj / all_jeju * 100), position=pos)
        s.append(f"{d}의 {key} 점포는 {n:,}곳으로 동네 전체 점포의 {_one(share)}%입니다(제주 전체 {_one(nj / all_jeju * 100)}%).")
        side = "크고" if lq > 1 else ("작고" if lq < 1 else "같고")
        s.append(f"특화계수(제주 평균 = 1)는 {_one(lq, 2)}로 제주 평균보다 업종 비중이 {side}, 동네 분포에서는 {pos}에 있습니다.")
    else:
        s.append(f"{d}의 점포는 전체 {int(all_dong):,}곳입니다.")
    ev = T("rest_events")
    ev = ev[(ev["dong"] == d) & ev["year"].between(start_year, end_year)]
    food_all = key is None or key in REST_MAP
    if food_all:
        cats = REST_MAP.get(key) if key else None
        if cats:
            ev = ev[ev["category"].isin(cats)]
        yr = ev.pivot_table(index="year", columns="kind", values="count", aggfunc="sum", fill_value=0).reindex(range(start_year, end_year + 1), fill_value=0)
        for c in ["open", "close"]:
            if c not in yr:
                yr[c] = 0
        years = [{"year": int(y), "open": int(r["open"]), "close": int(r["close"]), "net": int(r["open"] - r["close"])} for y, r in yr.iterrows()]
        values["restaurant_years"] = years
        label_ = key if key and key != "음식" else "음식점"
        for y in years:
            s.append(f"{y['year']}년 {label_} 개업 {y['open']}건, 폐업 {y['close']}건입니다.")
    else:
        limits.append(f"{key} 업종은 780 개업·폐업 이력이 없어 점포 수만 보여 준다.")
    period = {"점포": "2025-09 단면"}
    if food_all:
        close = T("close_3y").set_index("dong").loc[d]
        k5 = T("km").query("year == 5").set_index("dong").loc[d]
        curve = T("km").query("dong == @d").sort_values("year")
        values.update(close_3y_pct=_one(close["rate_pct"]), close_3y_lo=_one(close["lo_pct"]), close_3y_hi=_one(close["hi_pct"]), close_3y_n=int(close["store_years"]), close_label=close["label"],
                      survival_5y_pct=_one(k5["survival_pct"]), survival_lo=_one(k5["lo_pct"]), survival_hi=_one(k5["hi_pct"]), survival_n=int(k5["n"]), survival_label=k5["label"],
                      survival_curve=[{"year": int(r.year), "pct": _one(r.survival_pct)} for r in curve.itertuples()],
                      jeju_close_pct=meta()["close_base_pct"], jeju_survival_pct=meta()["km5_jeju_pct"])
        s.append(f"음식점 전체 기준 3년 폐업률은 {_one(close['rate_pct'])}%(95% 구간 {_one(close['lo_pct'])}~{_one(close['hi_pct'])}%, 제주 {meta()['close_base_pct']}%)이고, {LABEL_TEXT[close['label']]}{_small(d)}.")
        s.append(f"음식점 전체 기준 5년 생존율은 {_one(k5['survival_pct'])}%(표본 {int(k5['n'])}건, 제주 {meta()['km5_jeju_pct']}%)이고, {LABEL_TEXT[k5['label']]}{_small(d)}.")
        period.update({"개업·폐업": f"{start_year}~{end_year}", "폐업률": "2022~2024", "생존": "2015-01~2020-08 개업"})
        if end_year >= 2025:
            limits.append(f"780은 {meta()['rest_last']}까지라 2025년 값은 일부 기간이다.")
    else:
        s.append(f"{key} 업종의 개업·폐업 자료는 없습니다. 개업·폐업 이력(780)은 음식점만 담고 있습니다.")
    if d in ISLANDS:
        limits.append(SMALL_NOTE)
    return _result("biz_diagnostic", d, s, values, period, ["793", "780"] if food_all else ["793"], limits)


def _weather(dong, col, what):
    w = T("weather").set_index("dong")
    if dong not in w.index or pd.isna(w.loc[dong, f"{col}_비"]):
        return None, None
    r = w.loc[dong]
    v = {"change_pct": _one(r[f"{col}_비"]), "lo_pct": _one(r[f"{col}_하한"]), "hi_pct": _one(r[f"{col}_상한"]), "wet_days": meta()["wx_wet_days"]}
    sure = "감소가 확인됩니다" if v["hi_pct"] < 0 else ("증가가 확인됩니다" if v["lo_pct"] > 0 else "구간이 0을 포함해 차이를 확인하지 못했습니다")
    word = "적었고" if v["change_pct"] < 0 else "많았고"
    return v, f"비 오는 날 {what}은 같은 달·같은 요일의 비 안 오는 날보다 {abs(v['change_pct'])}% {word}(95% 구간 {v['lo_pct']}~{v['hi_pct']}%), {sure}."


def population_mix(dong, start_ym="2023-11", end_ym="2025-10", include_weather=False, year=2024):
    """거주·근무·방문 지수, 성·연령 구성, 같은 달 비교 추이."""
    d, err = _need_dong(dong)
    if err:
        return err
    year = int(year)
    if year not in POP_YEARS:
        return {"error": f"{year}년 유동인구 자료 없음", "available": list(POP_YEARS)}
    ratio, age = _pop_ratio(year), _age_share(year)
    m = T("pop_month")
    m = m[(m["dong"] == d) & m["ym"].between(str(start_ym), str(end_ym))].sort_values("ym")
    trend = [{"ym": r.ym, "visit_index": _one(r.visit / r.resd, 2), "days": int(r.days)} for r in m.itertuples()]
    by = {t["ym"]: t for t in trend}
    yoy = None
    for t in reversed(trend):  # 계절 영향을 빼려고 1년 전 같은 달과 비교한다. 일부만 수집한 달은 쓰지 않는다
        y0 = f"{int(t['ym'][:4]) - 1}{t['ym'][4:]}"
        if y0 in by and t["days"] >= 28 and by[y0]["days"] >= 28:
            yoy = {"ym": t["ym"], "visit_index": t["visit_index"], "prev_ym": y0, "prev_visit_index": by[y0]["visit_index"]}
            break
    pos = _position(ratio["visit"], d)
    values = {"visit_index": _one(ratio.loc[d, "visit"], 2), "work_index": _one(ratio.loc[d, "work"], 2), "old_pct": _one(age.loc[d, "old"]), "young_pct": _one(age.loc[d, "young"]),
              "position": pos, "trend": trend, "same_month_compare": yoy}
    s = [f"{d}의 {_pop_year(year)} 방문/거주 지수는 {values['visit_index']}, 근무/거주 지수는 {values['work_index']}입니다. 방문 지수는 동네 분포에서 {pos}입니다.",
         f"거주 인구 지수 중 60대 이상은 {values['old_pct']}%, 20~30대는 {values['young_pct']}%입니다."]
    limits = [L_583, _pop_note(year)]
    if yoy:
        s.append(f"같은 달 비교로 방문/거주 지수는 {yoy['prev_ym']} {yoy['prev_visit_index']}에서 {yoy['ym']} {yoy['visit_index']}입니다.")
    else:
        limits.append("1년 전 같은 달과 비교할 만큼 수집되지 않아 추이 비교를 하지 않았다.")
    if include_weather:
        w, line = _weather(d, "visit", "방문 지수")
        if w:
            values["rain"] = w
            s.append(line)
            limits.append(L_WX)
    return _result("population_mix", d, s, values, {"지수": str(year), "추이": f"{start_ym}~{end_ym}"}, ["583"] + (["579"] if include_weather else []), limits)


USER_TYPES = {"경로": "경로", "어르신": "경로", "노인": "경로", "청소년": "청소년", "학생": "청소년", "어린이": "어린이", "일반": "일반", "장애인": "장애", "장애": "장애", "유공자": "유공", "유공": "유공"}


def bus_usage(dong, user_type=None, include_weather=False, year=2024):
    """일평균 이용, 이용자 유형별 비중, 연간 증감, 날씨 비교(선택)."""
    d, err = _need_dong(dong)
    if err:
        return err
    year = int(year)
    if year not in BUS_YEARS:
        return {"error": f"{year}년 버스 자료 없음", "available": list(BUS_YEARS)}
    my, days = _bus_year(year)
    x = my[my["dong"] == d]
    if not len(x):
        return {"error": f"{d}의 버스 자료 없음"}
    tot = x["n"].sum()
    bus = _bus_daily(year)
    share = (x.groupby("user_type")["n"].sum() / tot * 100).sort_values(ascending=False)
    change, prev = None, year - 1
    if prev in BUS_YEARS:
        mp, dp = _bus_year(prev)
        tp = mp[mp["dong"] == d]["n"].sum()
        change = (tot / days) / (tp / dp) * 100 - 100 if tp else None
    pos = _position(bus, d)
    values = {"year": year, "daily": _one(tot / days), "position": pos, "shares_pct": {k: _one(v) for k, v in share.items()}, "change_prev_pct": _one(change) if change is not None else None}
    all_m = T("bus_month")
    tr = all_m[(all_m["dong"] == d) & (all_m["ym"] >= "2023-01")].groupby(["ym", "days"])["n"].sum().reset_index()
    values["trend"] = [{"ym": r.ym, "daily": _one(r.n / r.days)} for r in tr.sort_values("ym").itertuples()]
    s = [f"{d}의 {year}년 버스 일평균 이용은 {values['daily']:,}명으로 동네 분포에서 {pos}입니다."]
    if change is not None:
        s.append(f"일평균 이용은 {prev}년보다 {_change(values['change_prev_pct'])}.")
    if user_type:
        key = USER_TYPES.get(str(user_type), str(user_type))
        known = T("bus_month")["user_type"].unique()
        if not any(t.startswith(key) for t in known):
            return {"error": f"이용자 유형을 찾지 못함: {user_type}", "available": sorted(known)}
        sub = x[x["user_type"].str.startswith(key)]  # 유형은 있지만 이 동네 실적이 없으면 0으로 답한다
        pct = sub["n"].sum() / tot * 100
        values.update(user_type=key, type_daily=_one(sub["n"].sum() / days), type_share_pct=_one(pct))
        s.append(f"이 중 {key} 이용은 일평균 {values['type_daily']:,}명, 비중 {values['type_share_pct']}%입니다.")
    else:
        s.append("이용자 유형별 비중은 " + ", ".join(f"{k} {_one(v)}%" for k, v in share.head(3).items()) + "입니다.")
    limits = [L_743]
    if year == 2025:
        limits.append("743은 2025-10-25까지라 2025년은 일부 기간이다.")
    if year == 2022 or prev == 2022:
        limits.append("743은 2022년에 105일이 빠져 있어 2022년과의 비교에 주의가 필요하다.")
    if include_weather:
        w, line = _weather(d, "bus", "버스 이용")
        if w:
            values["rain"] = w
            s.append(line)
            limits.append(L_WX)
    if d in ISLANDS:
        limits.append(SMALL_NOTE)
    return _result("bus_usage", d, s, values, {"일평균·비중": str(year), "증감": f"{year - 1}→{year}"}, ["743", "612"] + (["579"] if include_weather else []), limits)


def _metric(name):
    lq = _lq_major()
    table = {"점포수": _store_count(), "숙박특화계수": lq["숙박"], "음식특화계수": lq["음식"], "소매특화계수": lq["소매"], "방문거주비": _pop_ratio()["visit"], "근무거주비": _pop_ratio()["work"],
             "고령비중": _age_share()["old"], "청년비중": _age_share()["young"], "버스일평균": _bus_daily()}
    m, days = _bus_year(2024)
    if name == "경로비중":
        return m[m["user_type"] == "경로"].groupby("dong")["n"].sum() / m.groupby("dong")["n"].sum() * 100
    if name == "경로일평균":
        return m[m["user_type"] == "경로"].groupby("dong")["n"].sum() / days
    return table[name]


def _category_metric(metric, category):
    hit, _, key = _match_biz(category)
    if hit is None:
        return None, key
    n = hit.groupby("dong")["count"].sum().reindex(dongs()).fillna(0)
    if metric == "업종점포수":
        return n, key
    biz = T("biz")
    tot = biz.groupby("dong")["count"].sum().reindex(dongs())
    return (n / tot) / (n.sum() / tot.sum()), key


def compare_rank(metric, dongs_=None, top=5, category=None):
    """동네 간 비교표·순위. 폐업률·생존율은 표본 오차가 커서 순위를 내지 않고 값과 구분만 보여 준다."""
    names = None
    if dongs_:
        names = []
        for n in dongs_:
            d, err = _need_dong(n)
            if err:
                return err
            names.append(d)
    if metric in NO_RANK:
        if metric == "폐업률":
            t = T("close_3y").set_index("dong")
            cols = ("rate_pct", "store_years")
        else:
            t = T("km").query("year == 5").set_index("dong")
            cols = ("survival_pct", "n")
        sel = names or [d for d in t.index if t.loc[d, "label"] not in ("차이 확인 안 됨", "") and d != "제주 전체"]
        rows = [{"dong": d, "value_pct": _one(t.loc[d, cols[0]]), "lo_pct": _one(t.loc[d, "lo_pct"]), "hi_pct": _one(t.loc[d, "hi_pct"]), "n": int(t.loc[d, cols[1]]), "label": t.loc[d, "label"], "small_sample": d in ISLANDS} for d in sel]
        s = [f"{r['dong']} {metric} {r['value_pct']}%(95% 구간 {r['lo_pct']}~{r['hi_pct']}%, 표본 {r['n']}): {r['label']}{_small(r['dong'])}" for r in rows]
        if not names:
            s.insert(0, f"{metric}은 표본 오차가 커서 순위를 내지 않습니다. 제주 평균과 차이가 확인된 동네만 보여 드립니다.")
        return _result("compare_rank", names or [], s, {"metric": metric, "rows": rows, "ranked": False}, {"폐업률": "2022~2024", "5년생존율": "2015-01~2020-08 개업"}[metric], ["780"], [L_780, "다중 비교를 보정(BH q=0.10)한 뒤 차이가 남는 동네만 높음·낮음으로 표시한다."])
    if metric not in RANK_METRICS:
        return {"error": f"지표를 찾지 못함: {metric}", "available": sorted(RANK_METRICS | NO_RANK)}
    key = None
    if metric in CATEGORY_METRICS:
        if not category:
            return {"error": f"{metric}에는 업종이 필요하다"}
        v, key = _category_metric(metric, category)
        if v is None:
            return {"error": f"업종을 찾지 못함: {category}", "hint": "카페, 한식, 숙박, 소매 같은 업종으로 물어보세요"}
    else:
        v = _metric(metric).dropna()
    dec = 0 if metric in ("점포수", "업종점포수") else (2 if metric in ("숙박특화계수", "음식특화계수", "소매특화계수", "방문거주비", "근무거주비", "업종특화계수") else 1)
    label_ = (f"{key} " if key else "") + METRIC_LABEL[metric]
    rank_base = v.drop(labels=[d for d in ISLANDS if d in v.index]).sort_values(ascending=False)
    if names:
        num = (lambda x: int(round(x))) if dec == 0 else (lambda x: _one(x, dec))
        rows = [{"dong": d, "value": num(v[d]) if d in v.index else None, "rank": int(rank_base.index.get_loc(d)) + 1 if d in rank_base.index else None, "small_sample": d in ISLANDS} for d in names]
        s = [f"{r['dong']} {label_} {r['value']}" + (f"(섬 제외 {len(rank_base)}곳 중 {r['rank']}위)" if r["rank"] else "(표본 적음, 순위 제외)") for r in rows]
    else:
        top = max(1, min(int(top), 15))
        num = (lambda x: int(round(x))) if dec == 0 else (lambda x: _one(x, dec))
        rows = [{"dong": d, "value": num(x), "rank": i + 1, "small_sample": False} for i, (d, x) in enumerate(rank_base.head(top).items())]
        s = [f"{label_} 상위(섬 제외 {len(rank_base)}곳): " + ", ".join(f"{r['rank']}위 {r['dong']} {r['value']}" for r in rows)]
    src = {"업종점포수": "793", "업종특화계수": "793", "점포수": "793", "숙박특화계수": "793", "음식특화계수": "793", "소매특화계수": "793", "버스일평균": "743+612", "경로비중": "743+612", "경로일평균": "743+612"}.get(metric, "583")
    lim = {"793": [L_793], "743+612": [L_743], "583": [L_583, _pop_note()]}[src]
    return _result("compare_rank", names or [], s, {"metric": metric, "metric_label": label_, "rows": rows, "ranked": True}, "2025-09 단면" if src == "793" else "2024", [src], lim + [SMALL_NOTE])


IMPL = {"dong_profile": dong_profile, "biz_diagnostic": biz_diagnostic, "population_mix": population_mix, "bus_usage": bus_usage,
        "compare_rank": lambda metric, dongs=None, top=5, category=None: compare_rank(metric, dongs, top, category)}


def _fn(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": req}}}


_D = {"dong": {"type": "string", "description": "동네 이름(행정동·법정동·리)"}}
SCHEMAS = [
    _fn("dong_profile", "동네 요약 카드(상권·생존·인구·교통). 동네 전반을 물을 때.", _D, ["dong"]),
    _fn("biz_diagnostic", "업종 점포 수·특화계수와 음식점 개업·폐업·생존. 창업·상권·업종 질문.", {**_D, "category": {"type": "string", "description": "업종(예: 카페, 한식, 숙박). 없으면 생략"}, "start_year": {"type": "integer"}, "end_year": {"type": "integer"}}, ["dong"]),
    _fn("population_mix", "거주·근무·방문 지수와 연령 구성, 추이. 비 오는 날 방문은 include_weather=true.", {**_D, "include_weather": {"type": "boolean"}, "year": {"type": "integer", "description": "2023, 2024, 2025 중 하나. 없으면 생략"}}, ["dong"]),
    _fn("bus_usage", "버스 일평균 이용, 이용자 유형 비중, 증감. 비 오는 날은 include_weather=true.", {**_D, "user_type": {"type": "string", "description": "경로, 청소년, 어린이, 일반, 장애, 유공"}, "include_weather": {"type": "boolean"}, "year": {"type": "integer", "description": "2019~2025 중 하나. 없으면 생략"}}, ["dong"]),
    _fn("compare_rank", "동네 비교표·순위. 폐업률·5년생존율은 순위 없이 값만.", {"metric": {"type": "string", "enum": sorted(RANK_METRICS | NO_RANK)}, "category": {"type": "string", "description": "업종점포수·업종특화계수일 때 업종(예: 카페)"}, "dongs": {"type": "array", "items": {"type": "string"}, "description": "비교할 동네. 없으면 상위 목록"}, "top": {"type": "integer"}}, ["metric"]),
]
