"""한 동네 안에서 두 업종 견주기(문제 기록 57·58번, 2026-11-17).

마스터 질문 '노형동에서 음식점 수와 매출이 카페 수와 매출과 비교했을 때 어떤 결과가 있나요?'에서 서비스는 업종을 하나(음식점)만 읽어
카페·가게 수·두 업종 비교를 모두 빠뜨렸다. Opus·Fable이 같은 질문을 따로 푼 절차를 규칙으로 옮긴다(58번 '규칙 증류').
① 업종 낱말을 모두 읽는다 → ② 업종마다 가게 수(상가 정보 793)와 제주 전체 비중·순위 → ③ 이 표로 이 업종의 매출을 답할 수 있는지 점검:
최근 카드 자료(관광공사, 2020-01~)는 업종 대분류뿐이라 카페·한식 같은 세부 업종을 나눌 수 없다 → 세부 업종이 있는 746 카드(2017-01~2021-05)로 바꾸고,
두 카드 자료는 규모가 달라(meta card_crosscheck_pass=False) 금액 대신 비중만 쓴다. 746의 2020-04는 모든 동·업종이 앞뒤 달의 약 2배라 뺀다
→ ④ 이 동네만의 특징인지 제주 전체와 견준다 → ⑤ 한계를 밝힌다(가게 비중과 매출 비중의 차이는 모든 동에서 같은 방향이라 카드 업종 분류 탓일 수 있어
가게 한 곳당 매출은 계산하지 않는다).
"""
import re
from functools import lru_cache

import pandas as pd

import qparse
import techniques as T
import v3

CMP = re.compile(r"비교|견주|견줘|대비|차이|보다\s|어느\s*쪽|중에|중\s*(어디|뭐|어느)|어디가\s*더|뭐가\s*더|더\s*(많|높|잘|적|크|낮)|vs|VS")
SALE = re.compile(r"매출|장사|벌이|카드|소비|팔")
SURV = re.compile(r"생존|버티|버텨|오래|살아남")
CLOSE = re.compile(r"폐업|문\s*닫|망하|없어지")
OPEN = re.compile(r"개업|새로\s*(생|문|연|여)|창업|신규")
COUNT = re.compile(r"수|개수|몇\s*(개|곳|군데)|가게|점포|많")
BAD_746 = "2020-04"  # 746 카드: 모든 동·업종이 앞뒤 달의 약 2배(제주 전체 2,486억 대 1,187·1,523억)


def find_bizs(q):
    """질문에 나온 업종을 나온 순서대로 모두(겹치는 낱말은 긴 것 먼저). find_targets는 첫 업종 하나만 돌려준다."""
    q = q or ""
    used, hits = q, []
    keys = sorted(list(qparse.BIZ_KEYS) + [(g, g) for g in v3.FOOD], key=lambda x: -len(x[0]))  # '중식'처럼 사전에 '중식당'만 있는 업종 이름(2026-11-17 Gemini 066 dev)
    for w, g in keys:  # 긴 낱말 먼저
        if g not in qparse.CLOSED_TARGETS:
            continue
        i = used.find(w)
        if i >= 0:
            hits.append((i, g))
            used = used[:i] + " " * len(w) + used[i + len(w):]
    out = []
    for _, g in sorted(hits):
        if g not in out:
            out.append(g)
    return out


def detect(q):
    bz = find_bizs(q)
    food = [b for b in bz if b in v3.FOOD]
    return len(bz) >= 2 and len(food) >= 1 and bool(CMP.search(q or ""))  # 한쪽이 음식 업종이면 다른 쪽은 제과점 등도 받는다(2026-11-17 067)  # 동네가 여럿이면(신제주 = 연동·노형동) 한 지역으로 합쳐 본다


@lru_cache(maxsize=1)
def _biz():
    return pd.read_parquet(v3.TAB / "biz.parquet")


def _stores(dongs, targets):
    """업종별 가게 수: 세부 업종(카페 등)은 그 분류만, '음식점'은 음식 분류에서 함께 물은 세부 업종을 뺀 나머지."""
    b = _biz()
    every = sorted(b["dong"].unique())
    subs = {t: v3.biz_rows(b, t) for t in targets if t != "음식점"}
    if "음식점" in targets:
        food = b[b["major"] == "음식"]
        taken = pd.concat(list(subs.values())) if subs else food.iloc[:0]
        subs["음식점"] = food.drop(index=taken.index, errors="ignore")
    out = {}
    for t in targets:
        by = subs[t].groupby("dong")["count"].sum().reindex(every, fill_value=0)
        v = int(by.reindex(dongs, fill_value=0).sum()) if dongs else int(by.sum())
        out[t] = {"value": v, "jeju": int(by.sum()), "rank": int((by > v).sum() + 1) if dongs and len(dongs) == 1 else None, "of": len(every)}
    return out


def _gap_count(targets, small):
    """매출 비중이 가게 비중보다 작은 동네 수(분류 탓인지 가늠: 모든 동네에서 같은 방향이면 업종 분류 영향으로 본다)."""
    every = sorted(_biz()["dong"].unique())
    n = m = 0
    for d in every:
        ss, st = _sales_share([d], list(targets)), _stores([d], list(targets))
        tot = sum(st[t]["value"] for t in targets)
        try:
            sh = float(ss["here"][small].iloc[-1])
        except (TypeError, KeyError, IndexError):
            continue
        if tot:
            n += 1
            m += sh < st[small]["value"] / tot * 100
    return m, n


def _sales_share(dongs, targets):
    """746 카드(2017-01~2021-05, 도민·내국인 관광객)에서 연도별 두 업종 매출 합 대비 비중. 음식점 = 음식점업에서 함께 물은 세부 업종을 뺀 나머지."""
    c = v3.card746()
    c = c[(c["biz"] == "음식점업") & (c["ym"] != BAD_746)]
    names = {t: v3.BIZ42[t] for t in targets if t in v3.BIZ42}
    if len(names) + ("음식점" in targets) < 2:
        return None

    def share(d):
        g = {}
        for t in targets:
            if t == "음식점":
                g[t] = d[~d["biz42"].str.startswith(tuple(names.values()))]
            else:
                g[t] = d[d["biz42"].str.startswith(names[t])]
        tot = sum(x.groupby(x["ym"].str[:4])["amt"].sum() for x in g.values())  # 두 업종 합 대비(가게 비중과 같은 기준)
        return {t: (x.groupby(x["ym"].str[:4])["amt"].sum() / tot * 100).round(2) for t, x in g.items()}
    here = share(c[c["dong"].isin(dongs)] if dongs else c)
    jeju = share(c)
    return {"here": here, "jeju": jeju, "last": max(c["ym"]), "first": min(c["ym"])}


def _rest_lines(q, dong, targets, warn):
    """생존·폐업·개업을 물었으면 업종마다 값(2026-11-17 새 문항 067: 두 업종의 생존·폐업·개업 비교). 동네 × 업종 표본 50곳 이상이면 동네 값, 아니면 제주 전체 업종 값."""
    from places import REST_MAP
    out = []
    asks = [k for k, rx in (("surv", SURV), ("close", CLOSE), ("open", OPEN)) if rx.search(q)]
    if not asks:
        return out
    miss = [t for t in targets if not REST_MAP.get(t) and t != "음식점"]
    if miss:
        warn.append(f"{', '.join(miss)}은(는) 음식점 인허가 업종 분류에 따로 없어 생존·폐업·개업을 견주지 못했어요.")
    tg = [t for t in targets if t not in miss]
    if not tg:
        return out
    kb, cb = pd.read_parquet(v3.TAB / "km_biz.parquet"), pd.read_parquet(v3.TAB / "close_biz.parquet")
    ev = pd.read_parquet(v3.TAB / "rest_events.parquet")
    where = dong or "제주 전체"
    for k in asks:
        vals = []
        for t in tg:
            if k == "surv":
                r = kb[(kb.group == t) & (kb.year == 5) & (kb.dong == (dong or "제주 전체"))] if t != "음식점" else pd.DataFrame()
                if t != "음식점" and (r.empty or int(r.iloc[0]["n"]) < 50):
                    r = kb[(kb.group == t) & (kb.year == 5) & (kb.dong == "제주 전체")]
                    vals.append(f"{t} {float(r.iloc[0]['survival_pct']):.1f}%(제주 전체, {where} 표본 50곳 미만)" if dong and len(r) else (f"{t} {float(r.iloc[0]['survival_pct']):.1f}%" if len(r) else f"{t} 값 없음"))
                elif t == "음식점":
                    km = pd.read_parquet(v3.TAB / "km.parquet")
                    rr = km[(km.dong == (dong or "제주 전체")) & (km.year == 5)]
                    vals.append(f"음식점 전체 {float(rr.iloc[0]['survival_pct']):.1f}%" if len(rr) else "음식점 값 없음")
                else:
                    vals.append(f"{t} {float(r.iloc[0]['survival_pct']):.1f}%(95% 구간 {float(r.iloc[0]['lo_pct']):.1f}~{float(r.iloc[0]['hi_pct']):.1f}%)")
            elif k == "close":
                if t == "음식점":
                    c3 = pd.read_parquet(v3.TAB / "close_3y.parquet")
                    rr = c3[c3.dong == dong] if dong else pd.DataFrame()
                    vals.append(f"음식점 전체 {float(rr.iloc[0]['rate_pct']):.1f}%" if len(rr) else "음식점 전체 값은 동네를 정해야 해요")
                    continue
                r = cb[(cb.group == t) & (cb.dong == (dong or "제주 전체"))]
                if r.empty or (dong and int(r.iloc[0]["store_years"]) < 50):
                    r = cb[(cb.group == t) & (cb.dong == "제주 전체")]
                    vals.append(f"{t} {float(r.iloc[0]['rate_pct']):.1f}%(제주 전체, {where} 표본 적음)" if dong and len(r) else (f"{t} {float(r.iloc[0]['rate_pct']):.1f}%" if len(r) else f"{t} 값 없음"))
                else:
                    vals.append(f"{t} {float(r.iloc[0]['rate_pct']):.1f}%")
            else:
                cats = REST_MAP.get(t) if t != "음식점" else None
                e = ev[(ev.kind == "open") & ((ev.dong == dong) if dong else True)]
                y = int(ev.year.max()) - 1  # 다 차지 않은 올해 대신 지난해(업종마다 같은 해)
                if cats:
                    e = e[e.category.isin(cats)]
                last3 = e[e.year.between(y - 2, y)].groupby("year")["count"].sum() if y else pd.Series(dtype=float)
                vals.append(f"{t} {int(last3.get(y, 0))}곳({y}년, 최근 3년 합 {int(last3.sum())}곳)" if y else f"{t} 값 없음")
        word = {"surv": "5년 생존율(2015년~ 개업)", "close": "3년 폐업률", "open": "개업 수"}[k]
        out.append(T._line(f"{where} {word}: " + ", ".join(vals) + ".", {"surv": "생존", "close": "폐업", "open": "개업"}[k], source="음식점 인허가(행정안전부)"))
    return out


def _j(w, a, b):
    """받침이 있으면 a, 없으면 b(예: 카페가·음식점이)."""
    c = w[-1]
    return w + (a if "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 else b)


def _n(t):
    return t if t.endswith("점") else f"{t} 가게"


def answer(question):
    q = question or ""
    targets = find_bizs(q)[:2]
    tr = []
    dongs = qparse.find_places(q, trace=tr)[0]
    dong = dongs[0] if dongs else None
    where = ("·".join(dongs) if len(dongs) <= 2 else f"{dongs[0]} 등 {len(dongs)}곳") if dongs else "제주 전체"
    st = _stores(dongs, targets)
    a, b = targets
    lines, warn, views = [], [], []
    tot = st[a]["value"] + st[b]["value"]
    for t in targets:
        x = st[t]
        sh = x["value"] / tot * 100 if tot else 0
        jsh = x["jeju"] / (st[a]["jeju"] + st[b]["jeju"]) * 100
        rk = (f"(제주 전체 비중 {jsh:.1f}%" + (f", 제주 {x['of']}개 동네 중 가게 수 {x['rank']}위)" if x["rank"] else ")")) if dong else ""
        lines.append(T._line(f"{where} {_j(_n(t), '은', '는')} {x['value']:,}곳으로 두 업종 합의 {sh:.1f}%예요{rk}.", "가게 수", source="상가 정보(공공데이터포털)"))
    ratio = st[a]["value"] / st[b]["value"] if st[b]["value"] else None
    concl = f"{where}에는 {_j(_n(a), '이', '가')} {st[a]['value']:,}곳, {_j(_n(b), '이', '가')} {st[b]['value']:,}곳" + (f"으로 {_j(a, '이', '가')} {b}의 {ratio:.1f}배예요." if ratio else "이에요.")
    views.append(T._view("bc_stores", f"{where} 가게 수", "bar", {"가게 수": [(t, st[t]["value"]) for t in targets]}, f"{a}·{b}", unit="곳"))
    ss = _sales_share(dongs, targets) if SALE.search(q) else None
    if SALE.search(q) and ss is None:
        warn.append(f"{a}·{_j(b, '을', '를')} 나눈 카드 매출 자료가 없어 매출은 견주지 않았어요.")
    if ss:
        small = min(targets, key=lambda t: float(ss["here"][t].iloc[-1]))
        s_here, s_jeju = ss["here"][small], ss["jeju"][small]
        yrs = list(s_here.index)
        jp = f"제주 전체 {s_jeju[yrs[-1]]:.1f}%, " if dong else ""
        trend = " → ".join(f"{y}년 {s_here[y]:.1f}%" for y in yrs)
        lines.append(T._line(f"{where} 두 업종 카드 매출 합 중 {small} 몫은 {trend}예요({jp}{yrs[-1]}년은 {ss['last'][5:].lstrip('0')}월까지, 도민·내국인 관광객 결제).", "매출 비중",
                             source="제주데이터허브 746 업종별 카드 매출"))
        big = [t for t in targets if t != small][0]
        shs, sts = float(s_here[yrs[-1]]), st[small]["value"] / tot * 100
        if shs < sts / 2:  # 매출 비중이 가게 비중의 절반도 안 되면 업종 분류 영향을 의심하고 동네 수로 확인한다
            m, n = _gap_count(tuple(targets), small)
            why = (f"이 차이는 매출 자료가 있는 제주 {n}개 동네 중 {m}곳에서 같은 방향이라, 카드 가맹점 업종 분류에서 {small} 상당수가 다른 음식점으로 잡혔을 수 있어요. 그래서 가게 한 곳당 매출은 계산하지 않았어요."
                   if n and m >= 0.9 * n else f"같은 방향인 동네는 제주 {n}개 동네 중 {m}곳이에요.")
            lines.append(T._line(f"매출 비중({small} {shs:.1f}%)이 가게 비중({sts:.1f}%)보다 크게 작아요. " + why, "읽는 법", block="analysis", layer="L5"))
        views.append(T._view("bc_share", f"{where} 두 업종 카드 매출 중 {small} 몫", "line", {where: [(y, float(s_here[y])) for y in yrs], "제주 전체": [(y, float(s_jeju[y])) for y in yrs]},
                             f"{yrs[0]}~{yrs[-1]}년", unit="%"))
        warn.append(f"{small} 매출을 따로 볼 수 있는 카드 자료는 746 자료({ss['first']}~{ss['last']})뿐이에요. 최근 카드 자료(관광공사, 2020-01부터)는 업종 대분류라 {_j(small, '을', '를')} 나눌 수 없어요.")
        warn.append("746 자료는 최근 카드 자료와 금액 규모가 달라 금액 대신 비중만 썼고, 모든 동네가 앞뒤 달의 약 2배인 2020년 4월은 뺐어요.")
        cm = v3.card()
        r = cm[(cm["biz"] == "음식점업") & (cm["dong"].isin(dongs) if dongs else True)].groupby("ym")["amt"].sum().sort_index()
        if len(r) >= 24:
            cur, prev = r.iloc[-12:].sum(), r.iloc[-24:-12].sum()
            lines.append(T._line(f"최근 {where} 음식점업 전체({small} 포함) 카드 매출은 최근 12개월({r.index[-12]}~{r.index[-1]}) {cur / 1e8:,.0f}억 원으로 그 전 12개월보다 {(cur / prev - 1) * 100:+.1f}%예요.",
                                 "최근 매출", source="제주관광공사 카드 소비"))
    lines += _rest_lines(q, dong if len(dongs) == 1 else None, targets, warn)
    if not dong:
        warn.append("동네 이름이 없어 제주 전체로 견줬어요. 동네 이름을 넣으면 그 동네와 제주 전체를 견줘요.")
    if len(dongs) >= 2:
        warn.append(f"질문의 '{' '.join(dict.fromkeys(w for w, _ in tr))}'는 행정동 {', '.join(dongs)}을 합쳐 계산했어요.")
    g = T.gloss([concl] + [x["text"] for x in lines])
    concl = g[0]
    for x, t in zip(lines, g[1:]):
        x["text"] = t
    warn_lines = [T._line(w, "주의", block="analysis", layer="L5") for w in warn]
    blocks = [{"id": "facts", "title": "두 업종 견주기", "lines": [x for x in lines if x["block"] == "facts"]},
              {"id": "analysis", "title": "읽는 법과 주의", "lines": [x for x in lines if x["block"] == "analysis"] + warn_lines}]
    method = {"kind": "biz_compare", "title": "두 업종 견주기", "how": "가게 수는 상가 정보, 매출은 세부 업종이 있는 746 카드 자료의 비중으로 견주고 제주 전체와 비교",
              "check": "카드 자료가 업종을 나눌 수 있는지 먼저 확인", "result": f"{a} {st[a]['value']}곳, {b} {st[b]['value']}곳", "limit": " ".join(warn[:1])}
    srcs = [{"source": "상가 정보(공공데이터포털)", "as_of": T.as_of("stores"), "next": T.NEXT["stores"]}]
    if ss:
        srcs.append({"source": "제주데이터허브 746 업종별 카드 매출", "as_of": T.as_of("sales746"), "next": T.NEXT["sales746"]})
    ans = {"conclusion": {"text": concl, "layer": "L3", "tag": "Agent 계산 · 두 업종 견주기"}, "blocks": blocks, "views": views, "default_views": len(views),
           "value_question": False, "footer": srcs, "freshness": [{"source": s["source"], "as_of": s["as_of"], "months_old": 0, "stale": False} for s in srcs],
           "requests": [], "methods": [method]}
    return {"question": question, "status": "성공", "tuple": None, "interpret": None,
            "understood": {"text": f"이렇게 이해했어요: {where} {a}·{b} 견주기(가게 수{'·매출' if SALE.search(q) else ''})", "by": "코드(업종 둘 + 비교 낱말)", "assumed": False,
                           "slots": {"topic": "biz_compare", "space": dongs, "target": a, "targets": targets}, "notes": []},
            "suggestions": [], "card": {"conclusion": concl, "evidence": [{"text": x["text"], "tag": x["tag"], "layer": x["layer"], "dataset": x["source"], "as_of": None, "kind": None} for x in lines],
                                        "intervals": [], "limits": warn},
            "answer": ans,
            "process": {"type": "두 업종 견주기", "steps": [{"id": "b1", "sub": "S1", "name": "업종 둘 읽기", "op": "조회", "status": "성공"},
                                                          {"id": "b2", "sub": "S2", "name": "카드 자료가 업종을 나눌 수 있는지 확인", "op": "검사", "status": "통과"},
                                                          {"id": "b3", "sub": "S4", "name": "가게 수·매출 비중 계산과 제주 전체 비교", "op": "통계", "status": "성공"}],
                        "data": {s["source"]: s["as_of"] for s in srcs}, "unused": []},
            "downloads": []}


if __name__ == "__main__":
    import json
    import sys
    for q in sys.argv[1:]:
        print(detect(q), find_bizs(q))
        if detect(q):
            r = answer(q)
            print(r["card"]["conclusion"])
            for e in r["card"]["evidence"]:
                print(" -", e["text"])
            for w in r["card"]["limits"]:
                print(" *", w)
