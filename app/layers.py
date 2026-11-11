"""v3 답 구조 (docs/기획/v3_설계.md 6절, 08 문서 2·5절 확정분, 2026-11-11 구현).

내부 층 L1 과거 기록 · L2 비교 · L3 통계 판정 · L4 모델 예상 · L5 판단하지 않음(판단 재료)을 줄마다 매기고,
화면 3블록(① 사실·비교 ② Agent 분석·예상 ③ 판단 재료)과 나눠 보기(views, 기본 3개 + 더 보기)를 만든다.
- 숫자는 모두 결과 저장소 값에서 코드가 만든다. 금액은 '억·만 원'으로 바꾸고, 바꾼 표시값은 numbers에 모아 수치 대조 허용 목록에 넣는다.
- 결론 한 줄은 층이 가장 높은 줄. 가치 판단 질문(L5)은 첫 문장을 거절로 쓰지 않고 신호를 먼저 말한다.
진입점: build(t, rv, ev, value_q=False)
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402
import recipes  # noqa: E402
import v3  # noqa: E402

BLOCK = {"L1": "facts", "L2": "facts", "L3": "analysis", "L4": "analysis", "L5": "guide"}
BLOCK_TITLE = {"facts": "사실·비교", "analysis": "Agent 분석·예상", "guide": "판단 재료"}
TAG = {"L2": "비교", "L5": "판단 재료"}
VALUE_WORDS = re.compile(r"잘\s*(되|돼|될)|장사\s*(요즘\s*)?(어때|어떄|괜찮)|창업|차려|차리면|열면|열어도|괜찮을까|괜찮아\?|유망|해도\s*될까|살기\s*좋|벌이")
CLOSING = "장사가 잘 되는지, 창업할지는 기준이 사람마다 달라 Agent가 정하지 않습니다. 위 신호로 직접 판단해 주세요."
MONTHLY_CARD = {"매출", "이용건수", "건당금액", "관광객비중", "과거매출", "시장추이"}
# 정책 문구의 상수(기간·기준). 결과값이 아니라 설계에서 정한 값이라 수치 대조 허용 목록에 넣는다
POLICY_NUMBERS = [12, 24, 36, 17, 43, 80, 10, 8, 25, 75, 100, 0.05, 2, 3, 5]


class Out:
    def __init__(self):
        self.lines, self.views, self.numbers = [], [], []

    def num(self, v, unit):
        text, n = v3.fmt(v, unit)
        if n is not None:
            self.numbers.append(n)
        return text

    def line(self, layer, text, source=None, as_of=None, tag=None, kind=None):
        dated = bool(as_of) and bool(re.match(r"\d{4}-\d{2}$|\d{4}년$", str(as_of)))
        tag = tag or (f"과거 기록 · ~{as_of}" if layer == "L1" and dated else f"과거 기록 · {as_of}" if layer == "L1" and as_of else "과거 기록" if layer == "L1" else TAG.get(layer, ""))
        self.lines.append({"layer": layer, "block": BLOCK[layer], "tag": tag, "text": text, "source": source, "as_of": as_of, "kind": kind})

    def view(self, vid, label, kind, series, summary, x="ym"):
        self.views.append({"id": vid, "label": label, "kind": kind, "x": x, "series": series, "summary": summary})


def _josa(w, a="은", b="는"):
    c = ord(w[-1]) - 0xAC00
    return w + (a if 0 <= c <= 11171 and c % 28 else b)


def _biz_word(t, note):
    tgt = t.get("target")
    if not tgt:
        return ""
    b, _ = v3.biz5_of(tgt)
    return f"{b} " if note and b else f"{tgt} "


def _series(tab, by="dong"):
    out = []
    for k, g in tab.groupby(by):
        g = g.sort_values("ym")
        out.append({"name": str(k), "points": [[str(a), float(b)] for a, b in zip(g["ym"], g["value"])]})
    return out


def _yearly(tab):
    y = tab.assign(year=tab["ym"].str[:4]).groupby(["dong", "year"])["value"].sum().reset_index()
    full = tab.assign(year=tab["ym"].str[:4]).groupby("year")["ym"].nunique()
    y = y[y["year"].isin(full[full == 12].index)]  # 12개월이 다 있는 해만
    return [{"name": str(k), "points": [[a, float(b)] for a, b in zip(g["year"], g["value"])]} for k, g in y.groupby("dong")]


def _median_compare(o, metric, dong, tgt, note, unit, cur):
    """L2: 같은 지표의 43개 동네 중간값 대비 배수(최근 월 또는 최근 12개월)."""
    try:
        if metric in ("매출", "이용건수"):
            c = v3.card()
            b, _ = v3.biz5_of(tgt)
            if b:
                c = c[c["biz"] == b]
            end = c["ym"].max()
            col = "amt" if metric == "매출" else "cnt"
            s = c[c["ym"] == end].groupby("dong")[col].sum()
        elif metric == "점포수":
            bz = pd.read_parquet(v3.TAB / "biz.parquet")
            if tgt and tgt != "음식점":
                bz = bz[bz["minor"].str.contains(tgt, na=False) | bz["middle"].str.contains(tgt, na=False) | bz["major"].str.contains(tgt, na=False)]
            elif tgt == "음식점":
                bz = bz[bz["major"] == "음식"]
            s = bz.groupby("dong")["count"].sum()
        else:
            return
        med = float(s.median())
        if med > 0 and dong in s.index:
            r = round(float(s[dong]) / med, 1)
            o.numbers.append(r)
            o.line("L2", f"{dong} {_josa(Q.METRICS.get(metric, metric))} 제주 43개 동네 중간값({o.num(med, unit)})의 {r}배이고, {int((s > s[dong]).sum() + 1)}위입니다.",
                   source="같은 자료의 동네별 값")
            o.numbers += [float(int((s > s[dong]).sum() + 1))]
    except Exception:
        return


def _table_lines(o, t, metric, v, note):
    tab = v["table"]
    unit = v.get("unit")
    src = v.get("dataset")
    word = _biz_word(t, note)
    if "이용자 불러옴" in str(src) and t.get("target") in v3.BIZ42:  # 센터 자료는 세부 업종 값
        word = f"{t['target']}({v3.BIZ42[t['target']]}) "
    label = Q.METRICS.get(metric, metric)
    if "ageGroup" in tab:  # 연령 구성은 기존 근거 문장(많은 순서)을 쓴다
        return
    if "hour" in tab:
        for d, g in tab.groupby("dong"):
            top = g.sort_values("value", ascending=False).head(3)
            o.line("L1", f"{d} {word}매출이 많은 시간: " + ", ".join(f"{int(h)}시({o.num(x, '%')})" for h, x in zip(top["hour"], top["value"])), src, src.split("최근 12개월 ")[-1].rstrip(")") if "최근 12개월" in str(src) else None)
            o.view("hour", "시간대", "bar", [{"name": d, "points": [[int(h), float(x)] for h, x in zip(g["hour"], g["value"])]}],
                   f"{int(top['hour'].iloc[0])}시에 매출 비중이 가장 큽니다", x="hour")
        return
    if "origin" in tab:
        last = tab[tab["ym"] == tab["ym"].max()].sort_values("value", ascending=False)
        o.line("L1", "외국인 관광객 카드 매출(제주 전체) 많은 출신지역: " + ", ".join(f"{a} {o.num(b, '원')}" for a, b in zip(last["origin"].head(3), last["value"].head(3))), src, tab["ym"].max())
        return
    if "ym" in tab:
        end = tab["ym"].max()
        cur = tab[tab["ym"] == end]
        dongs = cur["dong"].unique()
        if len(dongs) > 6:
            cur = cur.sort_values("value", ascending=False).head(6)
        for r in cur.itertuples():
            o.line("L1", f"{r.dong} {word}{label} {o.num(r.value, unit)}({end})", src, end)
        if 2 <= len(dongs) <= 6:
            g = cur.sort_values("value", ascending=False)
            o.line("L2", f"{label}: {_josa(g['dong'].iloc[0], '이', '가')} {', '.join(g['dong'].iloc[1:])}보다 많습니다(" + ", ".join(f"{d} {o.num(x, unit)}" for d, x in zip(g["dong"], g["value"])) + f", {end}).", src, kind="compare")
        if len(dongs) == 1 and metric in MONTHLY_CARD:
            s = tab.groupby("ym")["value"].sum()
            prev = v3._months_back(end, 12)
            if prev in s.index and s[prev] > 0 and metric != "관광객비중":
                pct = round((s[end] / s[prev] - 1) * 100, 1)
                o.numbers.append(abs(pct))
                o.line("L2", f"작년 같은 달({prev})보다 {abs(pct)}% {'많습니다' if pct > 0 else '적습니다'}.", src)
            if "이용자 불러옴" not in str(src):  # 동네 중간값 비교는 같은 자료(관광공사)끼리만
                _median_compare(o, metric, dongs[0], t.get("target"), note, unit, float(cur["value"].iloc[0]))
        o.view("monthly", "월별 흐름", "line", [{"name": s_["name"], "points": s_["points"][-36:]} for s_ in _series(tab)][:6],
               f"최근 {min(36, tab['ym'].nunique())}개월 {label}의 달마다 값입니다")
        yr = _yearly(tab)
        if yr and metric not in ("관광객비중", "건당금액", "일평균방문"):
            o.view("yearly", "연도별", "bar", yr[:6], f"12개월이 모두 있는 해의 {label} 합계입니다", x="year")
        return
    if "year" in tab:
        last = tab["year"].max()
        for r in tab[tab["year"] == last].head(6).itertuples():
            o.line("L1", f"{getattr(r, 'dong', '')} {word}{label} {o.num(r.value, unit)}({last}년)", src, f"{last}년")
        o.view("yearly", "연도별", "bar", [{"name": str(k), "points": [[int(a), float(b)] for a, b in zip(g["year"], g["value"])]} for k, g in tab.groupby("dong")][:6],
               f"연도별 {label}입니다", x="year")
        return
    if "biz" not in tab and "dong" in tab and "value" in tab:
        cur = tab.sort_values("value", ascending=False) if tab["dong"].nunique() > 6 else tab
        mt = v3.meta()
        asof = {"점포수": "최신 단면", "특화계수": "최신 단면", "5년생존율": f"개업 {mt.get('km_cohort')}", "조건부생존": f"개업 {mt.get('km_cohort')}", "폐업률": mt.get("close_years")}.get(metric)
        if metric in ("5년생존율", "조건부생존", "폐업률"):  # 동네별 값은 업종 구분이 없는 음식점 전체 값
            word = "음식점 전체 "
        for r in cur.head(6).itertuples():
            o.line("L1", f"{r.dong} {word}{label} {o.num(r.value, unit)}", src, asof)
        if tab["dong"].nunique() == 1 and metric == "점포수":
            _median_compare(o, metric, tab["dong"].iloc[0], t.get("target"), note, unit, float(tab["value"].iloc[0]))
        if tab["dong"].nunique() > 1:
            o.view("dongs", "동네별", "bar", [{"name": label, "points": [[d, float(x)] for d, x in zip(cur["dong"].head(10), cur["value"].head(10))]}], f"{label}이 큰 순서입니다", x="dong")


def _extra_lines(o, t, v):
    x = v["extra"]
    k = x["kind"]
    src = v.get("dataset")
    if k == "market":
        where, biz = x["where"], x["biz"]
        o.line("L1", f"{where} {biz} 카드 매출: 최근 12개월 {o.num(x['cur'], '원')}, 그 전 12개월 {o.num(x['prev'], '원')}(~{x['end']}).", src, x["end"])
        if x["prev"] > 0:
            g = round((x["cur"] / x["prev"] - 1) * 100, 1)
            o.numbers.append(abs(g))
            o.line("L2", f"그 전 12개월보다 {abs(g)}% {'많습니다' if g > 0 else '적습니다'}.", src)
        if x.get("supply") and len(x["supply"]) >= 2:
            a, b = x["supply"][-2], x["supply"][-1]
            last = v3.meta().get("rest_last", "")
            bl = f"{b['year']}년({last} 기준)" if last.startswith(str(b["year"])) and not last.endswith("12-31") else f"{b['year']}년"
            o.line("L1", f"{where} 영업 중 음식점 수(개업·폐업 누적): {a['year']}년 말 {o.num(a['value'], '곳')} → {bl} {o.num(b['value'], '곳')}.", "780 음식점 인허가", last[:7] or f"{b['year']}년")
            o.view("supply", "음식점 가게 수", "line", [{"name": "영업 중 음식점", "points": [[r["year"], r["value"]] for r in x["supply"]]}], "개업·폐업을 누적해 다시 센 영업 중 가게 수입니다", x="year")
        sh = x.get("share_by_year") or {}
        if sh:
            o.view("share", "손님 구분", "bar", [{"name": "내국인 관광객 비중(%)", "points": [[y, float(p)] for y, p in sh.items()]}],
                   f"매출 중 내국인 관광객 비중은 {list(sh)[-1]}년 {list(sh.values())[-1]}%입니다(외국인 제외)", x="year")
            o.numbers += [float(p) for p in sh.values()]
        if x.get("contrib"):
            top = x["contrib"][0]
            o.view("contrib", "성장에 기여한 동네", "bar", [{"name": "최근 12개월 증가액", "points": [[r["dong"], r["value"]] for r in x["contrib"]]}],
                   f"{top['dong']}의 증가액이 가장 큽니다", x="dong")
        if x.get("index"):
            idx = pd.DataFrame(x["index"])
            o.view("index", "장기 추이(2017~, 지수)", "line", [{"name": n, "points": [[a, b] for a, b in zip(g["ym"], g["value"])]} for n, g in idx.groupby("source")],
                   "두 자료는 카드사가 달라 금액 대신 겹치는 17개월(2020-01~2021-05) 평균을 100으로 둔 지수입니다")
        if x.get("foreign"):
            o.view("foreign", "외국인 출신지역", "bar", [{"name": "최근 12개월(제주 전체)", "points": [[r["origin"], r["value"]] for r in x["foreign"]]}],
                   f"외국인 매출은 {x['foreign'][0]['origin']}이 가장 큽니다(~{x['foreign_end']})", x="origin")
        tab = v["table"]
        o.view("monthly", "월별 흐름", "line", _series(tab), "달마다 카드 매출입니다")
        return
    if k == "bizcompare":
        for r in x["rows"]:
            parts = [f"{r['biz']} {o.num(r['cur'], '원')}"]
            if r.get("growth_pct") is not None:
                parts.append(f"1년 전보다 {o.num(abs(r['growth_pct']), '%')} {'증가' if r['growth_pct'] > 0 else '감소'}")
            if r.get("tourist_pct") is not None:
                parts.append(f"관광객 비중 {o.num(r['tourist_pct'], '%')}")
            if r.get("stores"):
                parts.append(f"가게 {o.num(r['stores'], '곳')}")
            o.line("L1", f"{x['dong']} " + ", ".join(parts) + "(최근 12개월).", src, x["end"])
        o.view("bizcompare", "업종별 매출", "bar", [{"name": "최근 12개월", "points": [[r["biz"], r["cur"]] for r in x["rows"]]}],
               f"{x['rows'][0]['biz']} 매출이 가장 큽니다", x="biz")
        o.view("bizgrowth", "업종별 증가율", "bar", [{"name": "1년 전 대비(%)", "points": [[r["biz"], r["growth_pct"]] for r in x["rows"] if r["growth_pct"] is not None]}],
               "업종마다 최근 12개월이 그 전 12개월보다 얼마나 늘거나 줄었는지입니다", x="biz")
        return
    if k == "rising":
        o.line("L2", f"최근 12개월 매출이 동네 × 업종 {x['combos']}개 조합의 중간값({o.num(x['median'], '원')}) 이상인 곳만 비교했습니다.", src)
        for r in x["rows"][:5]:
            o.line("L1", f"{r['dong']} {r['biz']}: {o.num(abs(r['growth_pct']), '%')} {'증가' if r['growth_pct'] > 0 else '감소'}(증가액 {o.num(r['gain'], '원')})", src, x["end"])
        o.view("rising", "증가율 순위", "bar", [{"name": "증가율(%)", "points": [[f"{r['dong']} {r['biz']}", r["growth_pct"]] for r in x["rows"]]}],
               f"{x['rows'][0]['dong']} {x['rows'][0]['biz']}가 가장 많이 늘었습니다", x="name")
        return
    if k == "signals":
        o.line("L5", x["rule"], "판단 기준(v3 설계 6절)", tag="판단 재료")
        for s in x["items"]:
            o.line("L5", f"{s['kind']}: {s['name']} {o.num(s['value'], s['unit'])} — {s['of']}곳 중 {s['rank']}위({s['level']})", s["source"], s["as_of"], tag="판단 재료")
            o.numbers += [float(s["rank"]), float(s["of"])]


def _judgement_lines(o, t, rv, ev):
    store = rv["run"]["store"]
    dong = "·".join(t.get("space") or []) or "제주 전체"
    tasks = {x["out"]: x for x in rv["order"]["tasks"]}
    timed = next((tasks[k].get("metric") for k, v in store.items() if k in tasks and tasks[k].get("sub") == "S1" and isinstance(v, dict)
                  and any(c in getattr(v.get("table"), "columns", []) for c in ("year", "ym"))), None)
    mk = next((v["extra"] for v in store.values() if isinstance(v, dict) and (v.get("extra") or {}).get("kind") == "market"), None)
    if mk:
        dong, timed = f"{mk['where']} {mk['biz']} 카드 매출", None
    if timed:  # 판정 문장의 주어: 무엇이 늘었는지(예: 노형동 카페 개업 수)
        tgt = t.get("target")
        dong = f"{dong} {tgt + ' ' if tgt and timed in ('개업수', '폐업수') else ''}{Q.METRICS.get(timed, timed)}"
    for v in store.values():
        if not isinstance(v, dict):
            continue
        sm = v.get("summary") or {}
        for j in v.get("judgement", []):
            if j["name"] == "추세":
                s2 = next((x.get("summary") for x in store.values() if isinstance(x, dict) and (x.get("summary") or {}).get("trend_kind") == "yoy"), None)
                sig = "(유의)" in j["claim"]
                up = j["claim"].startswith("증가")
                if s2 and s2.get("yoy_pct") is not None:
                    pct = abs(s2["yoy_pct"])
                    o.numbers.append(pct)
                    txt = (f"{dong}: 최근 12개월 동안 작년 같은 달보다 평균 {pct}% {'늘었습니다' if up else '줄었습니다'}." if sig
                           else f"{dong}: 늘었는지 줄었는지 자료로 구분할 수 없습니다(작년 같은 달 대비 평균 {'+' if up else '-'}{pct}%, 우연히 생길 수 있는 크기).")
                else:
                    txt = f"{dong}: 최근 {'늘었습니다' if up else '줄었습니다'}." if sig else f"{dong}: 늘었는지 줄었는지 자료로 구분할 수 없습니다."
                o.line("L3", txt, "통계 판정(유의수준 0.05)", tag="자료로 확인됨" if sig else "구분 못 함")
            elif "ci95" in j:
                cw = {"효과 있음": ("자료로 확인됨", "차이가 있습니다"), "작지만 0은 아님": ("자료로 확인됨", "차이는 있지만 ±10% 안의 작은 차이입니다"),
                      "작음 확인": ("자료로 확인됨", "차이가 ±10% 안으로 작습니다"), "판단 불가": ("구분 못 함", "차이를 확인하지 못했습니다")}.get(j["claim"], ("구분 못 함", j["claim"]))
                cond = "·".join(t.get("cond") or []) or "조건"
                o.line("L3", f"{cond}에 따른 {j['name']} 방문: {cw[1]}", "통계 판정(유의수준 0.05, ±10% 동등성)", tag=cw[0])
            elif j["name"].startswith("관문"):
                rid = j["name"].split()[-1]
                name = recipes.REG.get(rid, {}).get("name", rid)
                if j["use_forecast"]:
                    for fv in store.values():
                        if isinstance(fv, dict) and fv.get("recipe") == rid and fv.get("forecast"):
                            for f in fv["forecast"][:3]:
                                key = "visit" if "visit" in f else "value"
                                rng = f" (80% 구간 {o.num(f['lo'], '원')}~{o.num(f['hi'], '원')})" if "lo" in f else ""
                                o.line("L4", f"{f['dong']} {f.get('date') or f.get('ym')} {name}: {o.num(f[key], '원' if rid == 'R10' else '지수')}{rng}", f"레시피 {rid}",
                                       tag="예상 범위(10번 중 8번 맞는 폭)", kind="forecast")
                else:
                    o.numbers.append(j["mase"])
                    o.line("L4", f"{name}: 모델이 단순 기준(작년 같은 달 값 등)보다 낫지 않아 예상하지 않습니다(오차 비 {j['mase']}).", f"레시피 {rid} 관문", tag="예상하지 않음")
                    rv_ = next((x for x in store.values() if isinstance(x, dict) and x.get("recipe") == rid and x.get("reference")), None)
                    if rv_ and rv_["reference"].get("value"):  # R10 실패: 작년 같은 달 값을 비교 값으로(예상 아님, 사용자 결정 2026-11-11)
                        r = rv_["reference"]
                        o.line("L2", f"비교 값(예상 아님): {r['next']}의 작년 같은 달인 {r['ref_ym']} {r['dong']} {r['biz']} 카드 매출은 {o.num(r['value'], '원')}이었습니다.",
                               v3.KTO, r["ref_ym"], kind="reference")
                    if rv_ and rv_.get("validation"):
                        vv = rv_["validation"]
                        o.numbers += [float(rv_["closer"]), float(len(vv))]
                        o.line("L4", f"검증 기록: 최근 {len(vv)}개월 동안 매달 다음 달을 예상해 보니 모델이 작년 같은 달 값보다 실제에 가까웠던 달은 {rv_['closer']}개월입니다.",
                               f"레시피 {rid} 검증", tag="검증 기록")
                        o.view("validation", "최근 12개월 검증 기록", "line", [{"name": "실제", "points": [[x["ym"], x["actual"]] for x in vv]},
                                                                              {"name": "모델 예상", "points": [[x["ym"], x["model"]] for x in vv]},
                                                                              {"name": "작년 같은 달", "points": [[x["ym"], x["baseline"]] for x in vv]}],
                               "매달 그 달을 미리 예상했다면 어땠는지 보여 줍니다")
        if v.get("replay"):
            ins, n = v["inside"], v["months"]
            o.line("L4", f"검증 기록: 2018년까지 자료로 {v['what']}의 2019년 12개월을 예상했더니 {n}개월 중 {ins}개월이 80% 구간 안에 들었습니다.",
                   "레시피 R11(746)", tag="검증 기록")
            o.view("replay", "예상 vs 실제(2019)", "line", [{"name": "예상", "points": [[r["ym"], r["pred"]] for r in v["replay"]]},
                                                             {"name": "실제", "points": [[r["ym"], r["actual"]] for r in v["replay"]]},
                                                             {"name": "80% 구간 아래", "points": [[r["ym"], r["lo"]] for r in v["replay"]]},
                                                             {"name": "80% 구간 위", "points": [[r["ym"], r["hi"]] for r in v["replay"]]}],
                   "2018년 12월 시점에서 예상한 값과 실제 2019년 값입니다")


def _months_old(as_of, now):
    m = re.match(r"(\d{4})-(\d{2})", str(as_of or ""))
    if not m:
        return None
    return (now.year - int(m.group(1))) * 12 + now.month - int(m.group(2))


STALE_MONTHS = 3  # 기준 시점이 지금보다 3개월 넘게 지난 줄은 '오래된 자료'로 표시(v3 B)


def freshness(o, now=None):
    now = now or pd.Timestamp.now(tz="Asia/Seoul")
    rows = {}
    for x in o.lines:
        k = _months_old(x.get("as_of"), now)
        if k is None:
            continue
        if k > STALE_MONTHS and x["layer"] == "L1":
            x["tag"] = f"{x['tag']} · 오래된 자료({k}개월 전)"
        src = x.get("source") or "-"
        rows[src] = max(rows.get(src, ("", -1)), (x["as_of"], k), key=lambda r: r[0])
    return [{"source": s, "as_of": a, "months_old": k, "stale": k > STALE_MONTHS} for s, (a, k) in rows.items()]


def requests(t, store, lines):
    """자료 요청 카드(v3 C·D): 파일로만 받는 자료의 갱신 요청, 공개 자료로 부족한 세부 업종의 센터 자료 안내(F9)."""
    out = []
    card_used = any(v3.KTO in str(x.get("source")) for x in lines)
    if card_used:
        meta = __import__("json").loads((v3.TAB / "meta.json").read_text(encoding="utf-8"))
        out.append({"kind": "update", "title": "카드 매출 자료 갱신", "data": "제주관광공사 카드 소비(읍면동 월별·시간대)",
                    "now": meta.get("card_last"), "where": "제주관광빅데이터플랫폼 https://data.ijto.or.kr/",
                    "steps": ["플랫폼에서 '카드 관광 읍면동 리 월별 통계'를 검색", "기간을 2020-01부터 최신 월까지로 내려받기(시간대 자료는 최근 24개월)",
                              "파일을 data/raw/ 폴더에 넣기(파일 이름은 그대로)", "Agent 폴더에서 자료 갱신 실행: python app/update_data.py --tables-only"],
                    "why": f"지금 카드 매출은 {meta.get('card_last')}까지입니다. 최신 월이 공개됐다면 넣어 주세요."})
    tgt = t.get("target")
    center_used = any("이용자 불러옴" in str(x.get("source")) for x in lines)
    if tgt and tgt in v3.BIZ42 and not center_used and any(x.get("kind") != "survival" and "대분류" in str(x.get("text")) or v3.KTO in str(x.get("source")) for x in lines):
        out.append({"kind": "center", "title": f"{tgt}만의 최신 매출은 센터 자료로", "data": "카드 이용 현황(읍면동)_v02 (센터 1-08, 2025-05~현재)",
                    "where": "제주빅데이터센터 PC 데이터 조회 화면",
                    "query": [{"field": "데이터", "value": "카드 이용 현황(읍면동)_v02"}, {"field": "검색 기간", "value": "202505 ~ 최신 월"},
                              {"field": "법정동", "value": "·".join(t.get("space") or []) or "전체"}, {"field": "업종명", "value": v3.BIZ42[tgt]}],
                    "why": "공개 카드 자료는 업종 대분류만 있어 세부 업종 매출을 볼 수 없습니다. 센터에서 받은 CSV를 넣으면 같은 질문을 다시 계산합니다(F9)."})
    return out


def build(t, rv, ev, value_q=False):
    o = Out()
    store, order = rv["run"]["store"], rv["order"]
    tasks = {x["out"]: x for x in order["tasks"]}
    for key, v in store.items():
        task = tasks.get(key, {})
        if not isinstance(v, dict) or task.get("sub") != "S1" or "table" not in v:
            continue
        if v.get("extra"):
            _extra_lines(o, t, v)
        elif len(v["table"]):
            _table_lines(o, t, task.get("metric"), v, v.get("note"))
    for e in ev:  # 기존 근거 가운데 표에서 나오지 않는 것(생존율·비슷한 동네 등)
        if e.get("metric") in ("업종 5년생존율", "비슷한 동네", "유형", "거주연령구성", "방문연령구성"):
            o.line("L1", e["text"] + ("(업종 구성·연령·방문·버스가 가까운 순)" if e["metric"] == "비슷한 동네" else ""), e.get("dataset"), e.get("as_of"),
                   kind="similar" if e["metric"] == "비슷한 동네" else "survival" if e["metric"] == "업종 5년생존율" else None)
    _judgement_lines(o, t, rv, ev)
    fresh = freshness(o)  # 결론을 고르기 전에 '오래된 자료' 꼬리표를 붙인다
    # 결론: 층이 가장 높은 줄. 가치 판단 질문은 판단 재료 요약
    sig = next((v["extra"] for v in store.values() if isinstance(v, dict) and (v.get("extra") or {}).get("kind") == "signals"), None)
    if value_q and sig:
        dong = sig["dong"]
        parts = [f"{s['short']} {s['level']}" for s in sig["items"]]
        conclusion = {"text": f"{dong} 판단 재료: " + " · ".join(parts) + "(43개 동네 중 위치). 기준과 수치는 아래에 있습니다.", "layer": "L5", "tag": "판단 재료"}
    else:
        rank = {"L4": 4, "L3": 3, "L1": 1, "L2": 0, "L5": 0}
        cmp_ = next((x for x in o.lines if x.get("kind") == "compare"), None)
        lead = next((x for x in o.lines if x.get("kind") == {"T9": "similar"}.get(t.get("type"), "survival")), None)
        best = cmp_ if t.get("type") == "T2" and cmp_ else lead if lead else max(o.lines, key=lambda x: (rank[x["layer"]], -o.lines.index(x)), default=None)
        conclusion = {"text": best["text"], "layer": best["layer"], "tag": best["tag"]} if best else {"text": "확인된 결과가 없습니다.", "layer": None, "tag": None}
    blocks = []
    for b in ("facts", "analysis", "guide"):
        ls = [x for x in o.lines if x["block"] == b]
        if ls or (b == "guide" and value_q):
            blk = {"id": b, "title": BLOCK_TITLE[b], "lines": ls}
            if b == "guide" and (value_q or sig):
                blk["closing"] = CLOSING
            blocks.append(blk)
    seen, views = set(), []
    for vw in o.views:
        if vw["id"] not in seen:
            seen.add(vw["id"])
            views.append(vw)
    return {"conclusion": conclusion, "blocks": blocks, "views": views, "default_views": 3, "value_question": bool(value_q),
            "freshness": fresh, "requests": requests(t, store, o.lines), "numbers": o.numbers + POLICY_NUMBERS}
