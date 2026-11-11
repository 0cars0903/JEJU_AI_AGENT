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
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402
import recipes  # noqa: E402
from textcheck import numbers  # noqa: E402
import v3  # noqa: E402

BLOCK = {"L1": "facts", "L2": "facts", "L3": "analysis", "L4": "analysis", "L5": "guide"}
GUIDE = "판단할 때 볼 것"  # 화면에 보이는 이름. '판단 재료'는 뜻을 모르겠다는 지적이 있었다(문서 20 A10)
BLOCK_TITLE = {"facts": "사실·비교", "analysis": "Agent 분석·예상", "guide": GUIDE}
TAG = {"L2": "비교", "L5": GUIDE}
NOT_SURE = "자료로 가릴 수 없음"  # 통계 판정에서 차이·증감을 확인하지 못한 줄의 꼬리표(예전 이름 '구분 못 함', 문서 20 A8·A10)
VALUE_WORDS = re.compile(r"잘\s*(되|돼|될)|장사\s*(요즘\s*)?(어때|어떄|괜찮)|창업|차려|차리면|열면|열어도|괜찮을까|괜찮아\?|유망|해도\s*될까|살기\s*좋|벌이")
CLOSING = "장사가 잘 되는지, 창업할지는 사람마다 기준이 달라 Agent가 정하지 않아요. 위 신호를 보고 직접 판단해 주세요."
MONTHLY_CARD = {"매출", "이용건수", "건당금액", "관광객비중", "과거매출", "시장추이"}
# 업종을 나눠 볼 수 있는 지표. 그 밖의 지표(방문·버스·인구)는 동네 전체 값이라 업종 이름을 붙이지 않는다(문서 20 A4)
BIZ_METRICS = {"매출", "이용건수", "건당금액", "관광객비중", "시간대매출", "과거매출", "점포수", "특화계수", "개업수", "폐업수"}
# 정책 문구의 상수(기간·기준). 결과값이 아니라 설계에서 정한 값이라 수치 대조 허용 목록에 넣는다
POLICY_NUMBERS = [12, 24, 36, 17, 43, 80, 10, 8, 25, 75, 100, 0.05, 2, 3, 5]


# 패턴 F: 보기마다 한 줄 정의(OWID 방식). 지표·보기 id → 정의
DEFS = {
    "매출": "카드 매출 = 제주관광공사 카드 소비 자료의 카드 결제 금액 합계(현금·계좌이체 제외, 도민·내국인 관광객).",
    "이용건수": "결제 건수 = 카드 결제 횟수 합계.", "건당금액": "결제 1건당 금액 = 카드 매출 ÷ 결제 건수.",
    "관광객비중": "관광객 매출 비중 = 카드 매출 가운데 내국인 관광객 결제의 비율(외국인 제외).",
    "일평균방문": "하루 평균 방문 인구 = 통신 자료로 추계한 방문 인구 지수의 하루 평균(사람 수가 아님).",
    "점포수": "가게 수 = 상가(상권) 정보에 등록된 점포 수.", "시장추이": "카드 매출 = 제주관광공사 카드 결제 금액 합계(현금 제외).",
    "시간대매출": "시간대 비중 = 최근 12개월 카드 매출 가운데 그 시간대 결제가 차지하는 비율.",
    "index": "지수 = 두 자료가 겹치는 17개월(2020-01~2021-05) 평균을 100으로 둔 값. 카드사가 달라 금액 대신 흐름만 비교한다.",
    "supply": "영업 중 음식점 수 = 인허가 자료의 개업 누적 − 폐업 누적.", "validation": "검증 기록 = 지난 달마다 그 달을 미리 예상했다면 실제와 얼마나 가까웠는지.",
    "survival": "5년 생존율 = 개업한 음식점 가운데 5년 뒤에도 영업 중인 비율(카플란-마이어 추정).",
    "rising": "증가율 = 최근 12개월 카드 매출 ÷ 그 전 12개월 − 1.",
}
# 패턴 G: 자료별 갱신 주기(다음 갱신 안내)
CADENCE = {"제주관광공사": "매달(관광공사 공개 뒤 센터에서 갱신)", "583": "매일(약 2개월 늦게 공개)", "상가": "분기마다",
           "780": "수시", "음식점": "수시", "746": "갱신 없음(2021년 5월로 끝난 자료)", "센터": "센터 자료를 다시 받아 넣을 때"}


class Out:
    def __init__(self):
        self.lines, self.views, self.numbers = [], [], []

    def num(self, v, unit):
        text, n = v3.fmt(v, unit)
        if n is not None:
            self.numbers.append(n)
            self.numbers += [abs(x) for x in numbers(text)]  # '1조 8,241억'처럼 숫자가 둘로 나뉘는 표시
        return text

    def line(self, layer, text, source=None, as_of=None, tag=None, kind=None):
        dated = bool(as_of) and bool(re.match(r"\d{4}-\d{2}$|\d{4}년$", str(as_of)))
        tag = tag or (f"과거 기록 · ~{as_of}" if layer == "L1" and dated else f"과거 기록 · {as_of}" if layer == "L1" and as_of else "과거 기록" if layer == "L1" else TAG.get(layer, ""))
        self.lines.append({"layer": layer, "block": BLOCK[layer], "tag": tag, "text": text, "source": source, "as_of": as_of, "kind": kind})

    def view(self, vid, label, kind, series, summary, x="ym", definition=None, unit=None):
        self.views.append({"id": vid, "label": label, "kind": kind, "x": x, "series": series, "summary": summary, "definition": definition or DEFS.get(vid)})
        if unit:  # 그래프 세로축·표에 쓸 단위(문서 20 A10). 없으면 화면이 값 크기로 알아낸다
            self.views[-1]["unit"] = unit

    def map(self, vid, label, values, unit, summary, highlight=(), definition=None):
        """경계 색칠 지도 보기(43곳 값). 화면은 5단계(5등분)로 칠하고 범례에 경계값을 쓴다."""
        vals = {k: float(v) for k, v in values.items() if v == v}
        if len(vals) < 5:
            return
        self.views.append({"id": vid, "label": label, "kind": "map", "x": "dong", "series": [], "values": vals, "unit": unit,
                           "highlight": [h for h in highlight if h], "summary": summary, "definition": definition})


def _josa(w, a="은", b="는"):
    base = re.sub(r"\([^)]*\)\s*$", "", w).rstrip() or w  # '카드 매출(최근 12개월)'은 '매출'의 받침을 본다
    c = ord(base[-1]) - 0xAC00
    return w + (a if 0 <= c <= 11171 and c % 28 else b)


def _cop(text):
    """'~이에요/예요': 끝 글자의 받침으로 고른다. 숫자·기호로 끝나면 읽는 소리로 본다(%=퍼센트)."""
    t = str(text).rstrip()
    t = re.sub(r"\([^)]*\)\s*$", "", t).rstrip() or t  # '북미권(106억 원)'은 괄호 앞 '북미권'의 받침을 본다
    last = t[-1] if t else "가"
    if last == "%":
        return "예요"
    if last.isdigit():
        return "이에요" if last in "0136789" else "예요"  # 영·일·삼·육·칠·팔·구는 받침
    c = ord(last) - 0xAC00
    return "이에요" if 0 <= c <= 11171 and c % 28 else "예요"


def _ro(text):
    """'(으)로': 받침이 있으면 '으로'(ㄹ 받침은 '로')."""
    t = str(text).rstrip()
    last = t[-1] if t else "가"
    if last == "%":
        return "로"
    if last.isdigit():
        return "으로" if last in "0368" else "로"
    c = ord(last) - 0xAC00
    return "으로" if 0 <= c <= 11171 and c % 28 and c % 28 != 8 else "로"


def _ym_ko(ym):
    m = re.match(r"(\d{4})-(\d{2})", str(ym))
    return f"{m.group(1)}년 {int(m.group(2))}월" if m else str(ym)


def _biz_word(t, note, metric=None):
    """값 앞에 붙는 업종 낱말. 값이 실제로 그 업종 것일 때만 업종 이름을 쓴다(문서 20 A3·A4)."""
    tgt, det = t.get("target"), t.get("detail")
    if metric in ("점포수", "특화계수") and det:  # 세부 업종(국수·꽃집 …)으로 센 가게 수
        return f"{det} "
    if metric is not None and metric not in BIZ_METRICS and (det or tgt in Q.TARGETS_BIZ or tgt in Q.TARGETS_OUT):
        return "전체 "  # 방문·버스·인구는 업종 구분이 없는 동네 전체 값
    if not tgt:
        return ""
    b, _ = v3.biz5_of(tgt)
    if note and b:  # 대분류로 올려 계산한 값: '음식점업 전체(카페 포함)'
        return f"{b} 전체({tgt} 포함) " if b.rstrip("업") != tgt else f"{b} "
    return f"{tgt} "


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


def _median_compare(o, metric, dong, tgt, note, unit, cur, word="", det=None):
    """L2: 같은 지표의 43개 동네 중간값 대비 배수(최근 월 또는 최근 12개월)."""
    try:
        n_all = 43
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
            every = sorted(bz["dong"].unique())
            names = (qparse.DETAIL.get(det) or {}).get("names") if det else None
            if names:  # 세부 업종은 가게 수를 센 것과 같은 소분류로 견준다
                bz = bz[bz["minor"].isin(names)]
            elif tgt and tgt != "음식점":
                bz = v3.biz_rows(bz, tgt)
            elif tgt == "음식점":
                bz = bz[bz["major"] == "음식"]
            s = bz.groupby("dong")["count"].sum().reindex(every, fill_value=0)  # 그 업종 가게가 없는 동네는 0곳으로 센다
            n_all = len(s)
        else:
            return
        med = float(s.median())
        if dong not in s.index:
            return
        rank = int((s > s[dong]).sum() + 1)
        o.numbers += [float(rank), float(n_all)]
        head = f"{dong} {word}{_josa(Q.METRICS.get(metric, metric))}"
        if med > 0:
            r = round(float(s[dong]) / med, 1)
            o.numbers.append(r)
            o.line("L2", f"{head} 제주 {n_all}개 동네의 가운데 값(중간값, {o.num(med, unit)})의 {r}배이고, {n_all}곳 중 {rank}위예요.", source=None)
        else:
            o.line("L2", f"{head} 제주 {n_all}곳 중 {rank}위예요(절반이 넘는 동네에는 이 업종 가게가 없어요).", source=None)
    except Exception:
        return


def _rank_head(o, t, word, label, top, n, unit):
    """순위 질문의 결론: 1위 한 곳의 값만 쓰지 않고 몇 위인지 밝힌다(문서 20 A9)."""
    if t.get("type") != "T3" or getattr(o, "rank_head", None) or len(top) < 3:
        return
    parts = ", ".join(f"{i}위 {d}({o.num(x, unit)})" for i, (d, x) in enumerate(zip(top["dong"].head(3), top["value"].head(3)), 1))
    o.numbers += [1.0, 2.0, 3.0, float(n)]
    o.rank_head = f"{word}{label} 순위는 {parts}{_cop(parts)}(값이 있는 동네 {n}곳 가운데 큰 순서)."


def _table_lines(o, t, metric, v, note):
    tab = v["table"]
    unit = v.get("unit")
    src = v.get("dataset")
    word = _biz_word(t, note, metric)
    det = t.get("detail") if metric in ("점포수", "특화계수") and v.get("detail") else None
    if "이용자 불러옴" in str(src) and t.get("target") in v3.BIZ42:  # 센터 자료는 세부 업종 값
        word = f"{t['target']}({v3.BIZ42[t['target']]}) "
    label = Q.METRICS.get(metric, metric)
    if "ageGroup" in tab:  # 연령 구성은 기존 근거 문장(많은 순서)을 쓴다
        return
    if "hour" in tab:
        for d, g in tab.groupby("dong"):
            top = g.sort_values("value", ascending=False).head(3)
            hs = ", ".join(f"{int(h)}시({o.num(x, '%')})" for h, x in zip(top["hour"], top["value"]))
            o.line("L1", f"{d} {word}매출이 많은 시간은 {hs}{_cop(hs)}.", src, src.split("최근 12개월 ")[-1].rstrip(")") if "최근 12개월" in str(src) else None)
            o.view("hour", "시간대", "bar", [{"name": d, "points": [[int(h), float(x)] for h, x in zip(g["hour"], g["value"])]}],
                   f"{int(top['hour'].iloc[0])}시에 매출 비중이 가장 큽니다", x="hour", unit="%")
        return
    if "origin" in tab:
        last = tab[tab["ym"] == tab["ym"].max()].sort_values("value", ascending=False)
        og = ", ".join(f"{a}({o.num(b, '원')})" for a, b in zip(last["origin"].head(3), last["value"].head(3)))
        o.line("L1", f"제주 전체 외국인 관광객 카드 매출이 많은 출신지역은 {og}{_cop(og)}.", src, tab["ym"].max())
        return
    if "ym" in tab:
        end = tab["ym"].max()
        cur = tab[tab["ym"] == end]
        cur0 = cur
        dongs = cur["dong"].unique()
        if len(dongs) > 6:
            cur = cur.sort_values("value", ascending=False).head(6)
            _rank_head(o, t, f"{_ym_ko(end)} {word}", label, cur, len(dongs), unit)
        for r in cur.itertuples():
            v_ = o.num(r.value, unit)
            tail = ""
            if metric == "관광객비중" and len(dongs) == 1:  # '줄었어?'에 방향으로 답한다: 작년 같은 달과 %p로 견준다(문서 20 A8)
                pv = tab[tab["ym"] == v3._months_back(end, 12)]["value"]
                if len(pv) == 1:
                    diff = round(round(float(r.value), 1) - round(float(pv.iloc[0]), 1), 1)  # 화면에 보이는 두 값의 차와 맞춘다
                    o.numbers.append(abs(diff))
                    tail = f"(작년 같은 달 {o.num(float(pv.iloc[0]), unit)}" + ("와 같아요)" if diff == 0 else f"보다 {abs(diff)}%p {'높아요' if diff > 0 else '낮아요'})")
            o.line("L1", f"{_ym_ko(end)} {r.dong} {word}{_josa(label)} {v_}{_cop(v_)}{tail}.", src, end)
        if 2 <= len(dongs) <= 6:
            g = cur.sort_values("value", ascending=False)
            o.line("L2", f"{word}{label}: {_josa(g['dong'].iloc[0], '이', '가')} {', '.join(g['dong'].iloc[1:])}보다 많아요(" + ", ".join(f"{d} {o.num(x, unit)}" for d, x in zip(g["dong"], g["value"])) + f", {end}).", src, kind="compare")
        if len(dongs) > 6:  # 순위(전체 동네): 최근 달 값으로 지도
            o.map("map", f"지도: {label}", dict(zip(cur0["dong"], cur0["value"])), unit, f"{end} 기준 동네별 {_josa(label, '을', '를')} 지도로 보여 줘요", definition=DEFS.get(metric))
        if len(dongs) == 1 and metric in MONTHLY_CARD:
            s = tab.groupby("ym")["value"].sum()
            prev = v3._months_back(end, 12)
            if prev in s.index and s[prev] > 0 and metric != "관광객비중":
                pct = round((s[end] / s[prev] - 1) * 100, 1)
                o.numbers.append(abs(pct))
                o.line("L2", f"작년 같은 달({prev})보다 {abs(pct)}% {'많아요' if pct > 0 else '적어요'}.", src)
            if "이용자 불러옴" in str(src) and t.get("type") == "T4" and len(s) >= 2 and s.iloc[0] > 0:  # 센터 자료로 '흐름'을 물으면 넣은 기간의 처음과 끝을 견준다(문서 20 A6)
                first, chg = s.index.min(), round((s[end] / s[s.index.min()] - 1) * 100, 1)
                o.numbers += [abs(chg), float(len(s))]
                way = "변화가 없어요" if chg == 0 else f"{abs(chg)}% {'늘었어요' if chg > 0 else '줄었어요'}"
                o.line("L2", f"{dongs[0]} {word}{_josa(label)} {_ym_ko(first)} {o.num(s[first], unit)}에서 {_ym_ko(end)} {o.num(s[end], unit)}{_ro(o.num(s[end], unit))} {way}(넣은 자료 {len(s)}개월).", src, end, kind="flow")
                if prev not in s.index:
                    o.numbers.append(13.0)
                    o.line("L2", f"작년 같은 달과 견주려면 13개월 이상의 자료가 필요해요. 넣은 자료는 {len(s)}개월이에요.", src)
            if "이용자 불러옴" not in str(src):  # 동네 중간값 비교는 같은 자료(관광공사)끼리만
                _median_compare(o, metric, dongs[0], t.get("target"), note, unit, float(cur["value"].iloc[0]), word=word)
        o.view("monthly", "월별 흐름", "line", [{"name": s_["name"], "points": s_["points"][-36:]} for s_ in _series(tab)][:6],
               f"최근 {min(36, tab['ym'].nunique())}개월 동안 달마다 {_josa(label, '을', '를')} 보여 줘요", definition=DEFS.get(metric), unit=unit)
        yr = _yearly(tab)
        if yr and metric not in ("관광객비중", "건당금액", "일평균방문"):
            o.view("yearly", "연도별", "bar", yr[:6], f"12개월이 모두 있는 해의 {label} 합계예요", x="year", unit=unit)
        return
    if "year" in tab:
        last = tab["year"].max()
        for r in tab[tab["year"] == last].head(6).itertuples():
            v_ = o.num(r.value, unit)
            o.line("L1", f"{last}년 {getattr(r, 'dong', '')} {word}{_josa(label)} {v_}{_cop(v_)}.", src, f"{last}년")
        o.view("yearly", "연도별", "bar", [{"name": str(k), "points": [[int(a), float(b)] for a, b in zip(g["year"], g["value"])]} for k, g in tab.groupby("dong")][:6],
               f"해마다 {_josa(label, '을', '를')} 보여 줘요", x="year", unit=unit)
        return
    if "biz" not in tab and "dong" in tab and "value" in tab:
        cur = tab.sort_values("value", ascending=False) if tab["dong"].nunique() > 6 else tab
        mt = v3.meta()
        asof = {"점포수": v3.BIZ_ASOF, "특화계수": v3.BIZ_ASOF, "5년생존율": f"개업 {mt.get('km_cohort')}", "조건부생존": f"개업 {mt.get('km_cohort')}", "폐업률": mt.get("close_years")}.get(metric)
        if metric in ("5년생존율", "조건부생존", "폐업률"):  # 동네별 값은 업종 구분이 없는 음식점 전체 값
            word = "음식점 전체 "
        for r in cur.head(6).itertuples():
            v_ = o.num(r.value, unit)
            o.line("L1", f"{r.dong} {word}{_josa(label)} {v_}{_cop(v_)}.", src, asof)
        if tab["dong"].nunique() == 1 and metric == "점포수":
            _median_compare(o, metric, tab["dong"].iloc[0], t.get("target"), note, unit, float(tab["value"].iloc[0]), word=word, det=det)
        if 2 <= tab["dong"].nunique() <= 6 and metric == "점포수":  # 동네 비교의 결론은 그 업종 가게 수 비교부터(문서 20 A4)
            g = tab.sort_values("value", ascending=False)
            vals = ", ".join(f"{d} {o.num(x, unit)}" for d, x in zip(g["dong"], g["value"]))
            same = float(g["value"].iloc[0]) == float(g["value"].iloc[-1])
            body = "동네마다 같아요" if same else f"{_josa(g['dong'].iloc[0], '이', '가')} {', '.join(g['dong'].iloc[1:])}보다 많아요"
            o.line("L2", f"{word}{label}: {body}({vals}).", src, asof, kind="compare")
        if tab["dong"].nunique() > 6:
            _rank_head(o, t, word, label, cur, tab["dong"].nunique(), unit)
            top = cur.iloc[0]
            o.map("map", f"지도: {label}", dict(zip(tab["dong"], tab["value"])), unit, f"{_josa(top['dong'], '이', '가')} 가장 큽니다", definition=DEFS.get(metric))
        if tab["dong"].nunique() > 1:
            o.view("dongs", "동네별", "bar", [{"name": label, "points": [[d, float(x)] for d, x in zip(cur["dong"].head(10), cur["value"].head(10))]}], f"{_josa(label, '이', '가')} 큰 순서예요", x="dong", unit=unit)


def _extra_lines(o, t, v):
    x = v["extra"]
    k = x["kind"]
    src = v.get("dataset")
    if k == "market":
        where, biz = x["where"], x["biz"]
        o.line("L1", f"{where} {biz} 카드 매출은 최근 12개월 {o.num(x['cur'], '원')}, 그 전 12개월 {o.num(x['prev'], '원')}이에요(~{_ym_ko(x['end'])}).", src, x["end"])
        if x["prev"] > 0:
            g = round((x["cur"] / x["prev"] - 1) * 100, 1)
            o.numbers.append(abs(g))
            o.line("L2", f"12개월 합계로 견주면 그 전 12개월보다 {abs(g)}% {'많아요' if g > 0 else '적어요'}.", src)
        if x.get("supply") and len(x["supply"]) >= 2:
            a, b = x["supply"][-2], x["supply"][-1]
            last = v3.meta().get("rest_last", "")
            bl = f"{b['year']}년({last} 기준)" if last.startswith(str(b["year"])) and not last.endswith("12-31") else f"{b['year']}년"
            o.line("L1", f"{where} 영업 중 음식점은 {a['year']}년 말 {o.num(a['value'], '곳')}에서 {bl} {o.num(b['value'], '곳')}이 됐어요(개업·폐업 누적).", "780 음식점 인허가", last[:7] or f"{b['year']}년")
            o.view("supply", "음식점 가게 수", "line", [{"name": "영업 중 음식점", "points": [[r["year"], r["value"]] for r in x["supply"]]}], "개업·폐업을 누적해 다시 센 영업 중 가게 수예요", x="year")
        sh = x.get("share_by_year") or {}
        if sh:
            o.view("share", "손님 구분", "bar", [{"name": "내국인 관광객 비중(%)", "points": [[y, float(p)] for y, p in sh.items()]}],
                   f"매출 중 내국인 관광객 비중은 {list(sh)[-1]}년 {list(sh.values())[-1]}%예요(외국인 제외)", x="year")
            o.numbers += [float(p) for p in sh.values()]
        if x.get("biz_yearly"):
            o.view("biz_yearly", "연도별 업종 비교", "bar", [{"name": b, "points": pts} for b, pts in x["biz_yearly"].items()],
                   f"{x['where']} 업종 대분류 5개의 해마다 카드 매출이에요(12개월이 다 있는 해)", x="year", definition=DEFS["매출"])
        if x.get("yoy3"):
            o.view("yoy3", "전년 대비 3지표", "bar", [{"name": "최근 12개월 변화", "points": [[f"{r['name']}({r['unit']})", round(r["change"], 1)] for r in x["yoy3"]]}],
                   "최근 12개월이 그 전 12개월보다 얼마나 변했는지 보여 줘요(매출·건수는 %, 관광객 비중은 %p)", x="name",
                   definition="변화 = 최근 12개월 값과 그 전 12개월 값의 차이(비율).")
            o.numbers += [abs(round(r["change"], 1)) for r in x["yoy3"]]
        if x.get("contrib_all"):
            ch = [c for c in x["contrib_all"].values() if c == c]
            up, dn = sum(c > 0 for c in ch), sum(c < 0 for c in ch)
            o.numbers += [float(up), float(dn)]
            o.map("map", "지도: 1년 사이 매출 변화", x["contrib_all"], "원",
                  f"최근 12개월 매출이 그 전 12개월보다 늘어난 동네는 {up}곳, 줄어든 동네는 {dn}곳이에요(색이 진할수록 더 많이 늘어난 곳)",
                  definition="변화 = 최근 12개월 카드 매출 − 그 전 12개월 카드 매출(줄었으면 0보다 작은 값).")
        if x.get("contrib"):
            top = x["contrib"][0]
            down = x["prev"] > 0 and x["cur"] < x["prev"]
            summ = (f"모든 동네가 줄었고 {top['dong']}의 감소액이 가장 작아요" if top["value"] <= 0
                    else f"전체 매출은 줄었지만 {top['dong']}의 증가액은 가장 커요" if down else f"{top['dong']}의 증가액이 가장 커요")
            o.view("contrib", "매출이 가장 많이 늘어난 동네 5곳", "bar", [{"name": "최근 12개월 변화액", "points": [[r["dong"], r["value"]] for r in x["contrib"]]}],
                   summ, x="dong", definition="변화액 = 최근 12개월 카드 매출 − 그 전 12개월 카드 매출. 늘어난 순서로 5곳만 보여 줘요.")
        if x.get("index"):
            idx = pd.DataFrame(x["index"])
            o.view("index", "장기 추이(2017~, 지수)", "line", [{"name": n, "points": [[a, b] for a, b in zip(g["ym"], g["value"])]} for n, g in idx.groupby("source")],
                   "두 자료는 카드사가 달라 금액 대신 겹치는 17개월(2020-01~2021-05) 평균을 100으로 둔 지수로 비교해요")
        if x.get("foreign"):
            o.view("foreign", "외국인 출신지역", "bar", [{"name": "최근 12개월(제주 전체)", "points": [[r["origin"], r["value"]] for r in x["foreign"]]}],
                   f"외국인 매출은 {x['foreign'][0]['origin']}이 가장 큽니다(~{x['foreign_end']})", x="origin")
        tab = v["table"]
        o.view("monthly", "월별 흐름", "line", _series(tab), "달마다 카드 매출을 보여 줘요")
        return
    if k == "detailcompare":  # 한 동네 안에서 세부 업종끼리 가게 수 비교(문서 20 A9)
        rows, dong = x["rows"], x["dong"]
        for r in rows:
            by = "·".join(f"'{n}'" for n in r["names"]) or "해당 분류 없음"
            vv_ = o.num(r["value"], "곳")
            o.line("L1", f"{dong} {r['word']} 점포 수는 {vv_}{_cop(vv_)}(제주 {r['of']}개 동네 가운데 {r['rank']}위, 상가 정보의 {by} 분류로 셌어요).", src, v3.BIZ_ASOF)
            o.numbers += [float(r["rank"]), float(r["of"])]
        top, rest = rows[0], rows[1:]
        tie = all(r["value"] == top["value"] for r in rest)
        o.line("L2", (f"{dong}의 {'·'.join(r['word'] for r in rows)} 점포 수는 같아요(" if tie else f"{dong}에서는 {_josa(top['word'], '이', '가')} {'·'.join(r['word'] for r in rest)}보다 많아요(")
               + ", ".join(f"{r['word']} {o.num(r['value'], '곳')}" for r in rows) + ").", src, v3.BIZ_ASOF, kind="compare")
        o.view("bizcompare", "업종별 점포 수", "bar", [{"name": "점포 수(곳)", "points": [[r["word"], r["value"]] for r in rows]}],
               f"{dong}에서 {_josa(top['word'], '이', '가')} 가장 많아요" if not tie else f"{dong}에서 점포 수가 같아요", x="biz")
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
            o.line("L1", f"{x['dong']} {r['biz']}의 최근 12개월 카드 매출은 {parts[0].split(' ', 1)[1]}이에요" + (" — " + ", ".join(parts[1:]) if len(parts) > 1 else "") + ".", src, x["end"])
        o.view("bizcompare", "업종별 매출", "bar", [{"name": "최근 12개월", "points": [[r["biz"], r["cur"]] for r in x["rows"]]}],
               f"{x['rows'][0]['biz']} 매출이 가장 큽니다", x="biz")
        o.view("bizgrowth", "업종별 증가율", "bar", [{"name": "1년 전 대비(%)", "points": [[r["biz"], r["growth_pct"]] for r in x["rows"] if r["growth_pct"] is not None]}],
               "업종마다 최근 12개월이 그 전 12개월보다 얼마나 늘거나 줄었는지 보여 줘요", x="biz")
        return
    if k == "rising":
        o.line("L2", f"최근 12개월 매출이 동네 × 업종 {x['combos']}개 조합의 중간값({o.num(x['median'], '원')}) 이상인 곳만 비교했어요.", src)
        for r in x["rows"][:5]:
            o.line("L1", f"{r['dong']} {r['biz']} 매출이 1년 전보다 {o.num(abs(r['growth_pct']), '%')} {'늘었어요' if r['growth_pct'] > 0 else '줄었어요'}(증가액 {o.num(r['gain'], '원')}).", src, x["end"])
        o.map("map", "지도: 동네별 가장 많이 는 업종의 증가율", x.get("map") or {}, "%", "색이 진할수록 최근 12개월 매출이 많이 늘었어요", definition=DEFS["rising"])
        o.view("rising", "증가율 순위", "bar", [{"name": "증가율(%)", "points": [[f"{r['dong']} {r['biz']}", r["growth_pct"]] for r in x["rows"]]}],
               f"{x['rows'][0]['dong']} {x['rows'][0]['biz']}가 가장 많이 늘었어요", x="name")
        return
    if k == "signals":
        biz, _ = v3.biz5_of(t.get("target"))
        for kind, label, unit in (("visit", "하루 방문", "지수"), ("sales", f"{biz or '전 업종'} 카드 매출", "원"), ("stores", f"{t.get('target') or '전 업종'} 가게 수", "곳"), ("survival", "음식점 5년 생존율", "%")):
            s, unit_, asof = v3.dong_values(kind, biz=biz, target=t.get("target"))
            o.map(f"map_{kind}", f"지도: {label}", s.to_dict(), unit_, f"{x['dong']}(굵은 테두리)의 위치를 43곳 가운데서 봅니다({asof})", highlight=[x["dong"]],
                  definition=DEFS.get({"visit": "일평균방문", "sales": "매출", "stores": "점포수", "survival": "survival"}[kind]))
        o.line("L5", x["rule"], None, tag=GUIDE)
        tgt, lim = t.get("target"), v3.biz5_of(t.get("target"))[1]
        if tgt and tgt != "음식점":
            o.line("L5", f"줄마다 기준 업종이 달라요. 가게 수는 {tgt}, 카드 매출은 {biz or '전 업종'}{' 전체' if lim or not biz else ''}, 생존율은 음식점 전체 기준이에요."
                   + (f" 공개 자료에는 {tgt}만의 카드 매출이 없어요." if lim else ""), None, tag=GUIDE)
        for s in x["items"]:
            lv = {"많음": "많은 편", "적음": "적은 편", "높음": "높은 편", "낮음": "낮은 편", "보통": "보통"}.get(s["level"], s["level"])
            vv_ = o.num(s['value'], s['unit'])
            o.line("L5", f"{s['kind']} — {_josa(s['name'])} {vv_}{_ro(vv_)} {s['of']}곳 중 {s['rank']}위, {lv}이에요.", s["source"], s["as_of"], tag=GUIDE)
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
        note = next((v.get("note") for k, v in store.items() if k in tasks and tasks[k].get("metric") == timed and isinstance(v, dict)), None)
        word = (tgt + " " if tgt else "") if timed in ("개업수", "폐업수") else (_biz_word(t, note, timed) if timed in BIZ_METRICS else "")
        dong = f"{dong} {word}{Q.METRICS.get(timed, timed)}"
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
                    txt = (f"{dong}: 최근 12개월 동안 작년 같은 달보다 평균 {pct}% {'늘었어요' if up else '줄었어요'}." if sig
                           else f"{dong}: 늘었는지 줄었는지는 자료로 가릴 수 없어요(작년 같은 달 대비 평균 {'+' if up else '-'}{pct}%, 우연히 생길 수 있는 크기).")
                else:
                    txt = f"{dong}: 최근 {'늘었어요' if up else '줄었어요'}." if sig else f"{dong}: 늘었는지 줄었는지는 자료로 가릴 수 없어요."
                if mk and s2 and s2.get("yoy_pct") is not None:  # 위 '12개월 합계' 비교와 값이 다른 이유(문서 20 A5)
                    txt += " 달마다 작년 같은 달과 견준 변화율을 평균한 값이라 위 합계 비교와 수치가 조금 달라요."
                o.line("L3", txt, None, tag="자료로 확인됨" if sig else NOT_SURE)
            elif "ci95" in j:
                cw = {"효과 있음": ("자료로 확인됨", "자료로 확인된 차이예요"), "작지만 0은 아님": ("자료로 확인됨", "차이는 있지만 ±10% 안의 작은 차이예요"),
                      "작음 확인": ("자료로 확인됨", "차이가 ±10% 안으로 작아요"), "판단 불가": (NOT_SURE, "차이를 확인하지 못했어요")}.get(j["claim"], (NOT_SURE, j["claim"]))
                cond = "·".join(t.get("cond") or []) or "조건"
                lo, hi = (round(float(c), 1) for c in j["ci95"])
                eff = round(float(j["effect_pct"]), 1) if j.get("effect_pct") is not None else None
                o.numbers += [abs(lo), abs(hi), lo, hi] + ([abs(eff), eff] if eff is not None else [])
                rng = f"자료로 본 범위 {lo}% ~ {hi}%"
                if eff is not None and j["claim"] in ("효과 있음", "작지만 0은 아님"):  # 방향과 크기를 결론 줄에 쓴다(문서 20 A8)
                    txt = f"{cond}에 따른 {j['name']} 방문: 약 {abs(eff)}% {'줄어요' if eff < 0 else '늘어요'}({rng}). {cw[1]}."
                else:
                    txt = f"{cond}에 따른 {j['name']} 방문: {cw[1]}({rng})."
                o.line("L3", txt, None, tag=cw[0])
            elif j["name"].startswith("관문"):
                rid = j["name"].split()[-1]
                name = recipes.REG.get(rid, {}).get("name", rid)
                if j["use_forecast"]:
                    for fv in store.values():
                        if isinstance(fv, dict) and fv.get("recipe") == rid and fv.get("forecast"):
                            for i, f in enumerate(fv["forecast"][:3]):
                                key = "visit" if "visit" in f else "value"
                                rng = f" (예상 범위 {o.num(f['lo'], '원')}~{o.num(f['hi'], '원')})" if "lo" in f else ""
                                # 날짜 예상은 '자료가 끝난 다음 7일'이다. 오늘 기준 다음 주가 아님을 첫 줄에 밝힌다(문서 20 A2)
                                if i == 0 and f.get("date") and fv.get("data_last"):
                                    o.numbers += [7.0, float(str(fv["data_last"])[8:10] or 0)]
                                base = f" — 유동인구 자료가 {fv['data_last']}까지 있어서 그 다음 7일을 예상한 값이에요(오늘 기준 다음 주가 아니에요)" if i == 0 and f.get("date") and fv.get("data_last") else ""
                                o.line("L4", f"{f['dong']} {f.get('date') or f.get('ym')} {name}: {o.num(f[key], '원' if rid == 'R10' else '지수')}{rng}{base}", None,
                                       tag="예상 범위(10번 중 8번 맞는 폭)" if rng else f"모델 예상 · 자료 ~{fv.get('data_last') or ''}".rstrip(" ~·"), kind="forecast")
                else:
                    o.numbers.append(j["mase"])
                    o.line("L4", f"{name}: 모델이 단순 기준(작년 같은 달 값 등)보다 낫지 않아 예상하지 않아요(오차 비 {j['mase']}).", None, tag="예상하지 않음")
                    rv_ = next((x for x in store.values() if isinstance(x, dict) and x.get("recipe") == rid and x.get("reference")), None)
                    if rv_ and rv_["reference"].get("value"):  # R10 실패: 작년 같은 달 값을 비교 값으로(예상 아님, 사용자 결정 2026-11-11)
                        r = rv_["reference"]
                        o.line("L2", f"비교 값(예상 아님): {r['next']}의 작년 같은 달인 {r['ref_ym']} {r['dong']} {r['biz']} 카드 매출은 {o.num(r['value'], '원')}이었어요.",
                               v3.KTO, r["ref_ym"], kind="reference")
                    if rv_ and rv_.get("validation"):
                        vv = rv_["validation"]
                        o.numbers += [float(rv_["closer"]), float(len(vv))]
                        o.line("L4", f"검증 기록: 최근 {len(vv)}개월 동안 매달 다음 달을 예상해 보니 모델이 작년 같은 달 값보다 실제에 가까웠던 달은 {rv_['closer']}개월이에요.",
                               None, tag="검증 기록")
                        o.view("validation", "최근 12개월 검증 기록", "line", [{"name": "실제", "points": [[x["ym"], x["actual"]] for x in vv]},
                                                                              {"name": "모델 예상", "points": [[x["ym"], x["model"]] for x in vv]},
                                                                              {"name": "작년 같은 달", "points": [[x["ym"], x["baseline"]] for x in vv]}],
                               "매달 그 달을 미리 예상했다면 어땠는지 보여 줍니다")
        if v.get("replay"):
            ins, n = v["inside"], v["months"]
            o.line("L4", f"검증 기록: 2018년까지 자료로 {v['what']}의 2019년 12개월을 예상했더니 {n}개월 중 {ins}개월이 예상 범위(10번 중 8번 맞게 잡은 폭) 안에 들었어요.",
                   None, tag="검증 기록")
            o.view("replay", "예상 vs 실제(2019)", "line", [{"name": "예상", "points": [[r["ym"], r["pred"]] for r in v["replay"]]},
                                                             {"name": "실제", "points": [[r["ym"], r["actual"]] for r in v["replay"]]},
                                                             {"name": "예상 범위 아래", "points": [[r["ym"], r["lo"]] for r in v["replay"]]},
                                                             {"name": "예상 범위 위", "points": [[r["ym"], r["hi"]] for r in v["replay"]]}],
                   "2018년 12월 시점에서 예상한 값과 실제 2019년 값을 견줘 봐요")


def plain_names(s):
    """자료 번호가 든 이름(허브 746, 센터 1-07·1-08)을 이용자가 알아볼 이름으로 바꾼다. 출처와 한계 문구에 함께 쓴다(문서 20 A10)."""
    s = str(s).replace("허브 746(센터 1-07과 같은 칸 구성, 시험용)", "데이터허브 카드 매출(빅데이터센터 카드 자료와 같은 형식, 시험용)")
    return s.replace("센터 1-08 카드 이용 현황(읍면동)_v02", "빅데이터센터 카드 자료(2025-05~)").replace("센터 1-07 카드 이용 현황(읍면동)_v01", "빅데이터센터 카드 자료(2017~2025)")


def nice_source(src):
    """화면용 출처 이름: 자료 번호·내부 용어를 빼고 이용자가 알아볼 이름으로(사용자 지시 2026-11-12). 내부 이름은 판단 과정·내려받기에만 남는다."""
    if not src:
        return None
    s = str(src)
    if s.startswith(("레시피", "판단 기준", "통계 판정", "같은 자료")):
        return None
    s = plain_names(s)
    if "이용자 불러옴" in s:
        return s
    rules = [(r"^583 유동인구.*", "유동인구(제주데이터허브)"), (r"^793 상가.*", "상가 정보(공공데이터포털)"), (r"^780 음식점 인허가.*", "음식점 인허가(행정안전부)"),
             (r"^746 업종별 카드 매출.*|^허브 746.*", "카드 매출(제주데이터허브, 2017~2021)"), (r"^743 버스.*", "버스 이용(제주데이터허브)")]
    for pat, rep in rules:
        if re.match(pat, s):
            return rep
    return s


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
        if k > STALE_MONTHS and (x["layer"] == "L1" or x.get("kind") == "flow"):  # 결론이 되는 흐름 줄에도 붙인다
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
                    "steps": [],
                    "why": f"지금 카드 매출은 {meta.get('card_last')}까지 있어요. 새 달 자료가 나오면 센터 담당자에게 갱신을 요청해 주세요."})
    tgt = t.get("target")
    center_used = any("이용자 불러옴" in str(x.get("source")) for x in lines)
    if tgt and tgt in v3.BIZ42 and not center_used and any(x.get("kind") != "survival" and "대분류" in str(x.get("text")) or v3.KTO in str(x.get("source")) for x in lines):
        out.append({"kind": "center", "title": f"{tgt}만의 최신 매출은 센터 자료로", "data": "카드 이용 현황(읍면동)_v02 (센터 1-08, 2025-05~현재)",
                    "where": "제주빅데이터센터 PC 데이터 조회 화면",
                    "query": [{"field": "데이터", "value": "카드 이용 현황(읍면동)_v02"}, {"field": "검색 기간", "value": "202505 ~ 최신 월"},
                              {"field": "법정동", "value": "·".join(t.get("space") or []) or "전체"}, {"field": "업종명", "value": v3.BIZ42[tgt]}],
                    "why": "공개 카드 자료는 업종 대분류만 있어서 세부 업종 매출은 볼 수 없어요. 센터에서 받은 CSV를 넣으면 같은 질문을 다시 계산해요. "
                           "이 자료는 센터 PC에서만 받을 수 있어요. 센터에 가기 어려우면 위 답(업종 대분류 기준)을 참고해 주세요."})
    if len(t.get("details") or []) >= 2 and not center_used:  # 세부 업종끼리의 매출 비교는 공개 자료로 할 수 없다 → 받을 곳을 알린다(문서 20 A9)
        out.append({"kind": "center", "title": "세부 업종끼리 매출 비교는 센터 자료로", "data": "카드 이용 현황(읍면동)_v02 (센터 1-08, 2025-05~현재)",
                    "where": "제주빅데이터센터 PC 데이터 조회 화면",
                    "query": [{"field": "데이터", "value": "카드 이용 현황(읍면동)_v02"}, {"field": "검색 기간", "value": "202505 ~ 최신 월"},
                              {"field": "법정동", "value": "·".join(t.get("space") or []) or "전체"}, {"field": "업종명", "value": "전체"}],
                    "why": f"공개 카드 자료는 업종 대분류 5개만 있어서 {'·'.join(t['details'])}의 매출을 따로 견줄 수 없어요. 그래서 위 답은 점포 수로 견줬어요. "
                           "세부 업종 매출은 센터 자료에 있어요. 이 자료는 센터 PC에서만 받을 수 있어요."})
    if "외국인매출" in (t.get("metric") or []) and not center_used:  # 동네별 외국인 매출은 공개 자료에 없다 → 받을 곳과 조회 조건을 알린다(문서 20 A9)
        out.append({"kind": "center", "title": "동네별 외국인 매출은 센터 자료로", "data": "카드 이용 현황(읍면동)_v02 (센터 1-08, 2025-05~현재)",
                    "where": "제주빅데이터센터 PC 데이터 조회 화면",
                    "query": [{"field": "데이터", "value": "카드 이용 현황(읍면동)_v02"}, {"field": "검색 기간", "value": "202505 ~ 최신 월"},
                              {"field": "법정동", "value": "·".join(t.get("space") or []) or "전체"}, {"field": "이용자구분", "value": "전체(외국인 줄이 들어 있어야 해요)"}],
                    "why": "공개 카드 자료에는 외국인 매출이 제주 전체(업종·출신지역)로만 있어요. 센터 자료에는 동네·이용자구분(도민·내국인·외국인)별 값이 있어서, "
                           "센터에서 받은 CSV를 넣으면 같은 질문을 동네별 외국인 매출로 다시 계산해요."})
    fc = next((v for v in store.values() if isinstance(v, dict) and v.get("forecast") and v.get("data_last") and (v["forecast"][0] or {}).get("date")), None)
    if fc and any(x.get("kind") == "forecast" for x in lines):  # 방문 예상은 자료가 끝난 다음 7일만 낼 수 있다 → 최신 유동인구를 요청한다(문서 20 A2)
        out.append({"kind": "update", "title": "유동인구 자료 갱신(오늘 기준 예상에 필요)", "data": "내국인 유동인구(제주데이터허브 583 · 센터 4-11 내국인 유동인구(읍면동)_v02)",
                    "now": str(fc["data_last"]), "where": "제주데이터허브(약 2개월 늦게 공개) 또는 제주빅데이터센터 PC(매일 갱신)", "steps": [],
                    "why": f"방문 예상은 유동인구 자료가 끝난 날({fc['data_last']}) 다음 7일을 계산해요. 오늘 기준 다음 주를 보려면 그 사이 유동인구 자료가 필요해요. "
                           "센터 담당자에게 갱신을 요청해 주세요."})
    if any(str(x.get("as_of")) == v3.BIZ_ASOF for x in lines):  # 가게 수는 기준일이 1년 넘게 지났다 → 새 분기 파일을 요청한다(문서 20 A10)
        out.append({"kind": "update", "title": "상가 정보 갱신", "data": "상가(상권) 정보(제주데이터허브 793)", "now": v3.BIZ_ASOF.split()[0],
                    "where": "제주데이터허브 또는 공공데이터포털(분기마다 새 파일)", "steps": [],
                    "why": f"가게 수는 {v3.BIZ_ASOF} 값이에요. 그 뒤에 문을 열거나 닫은 가게는 들어 있지 않아요. 새 분기 파일이 나오면 센터 담당자에게 갱신을 요청해 주세요."})
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
            if e["metric"] == "비슷한 동네":  # 모델 계산 결과라 비교 층(L2), 출처는 쓴 자료 묶음
                o.line("L2", e["text"] + "(업종 구성·연령·방문·버스가 가까운 순)", "상가·유동인구·버스 자료(Agent 계산)", None, kind="similar")
            else:
                o.line("L1", e["text"], e.get("dataset"), e.get("as_of"), kind="survival" if e["metric"] == "업종 5년생존율" else None)
    _judgement_lines(o, t, rv, ev)
    fresh = freshness(o)  # 결론을 고르기 전에 '오래된 자료' 꼬리표를 붙인다
    # 결론: 층이 가장 높은 줄. 가치 판단 질문은 판단 재료 요약
    sig = next((v["extra"] for v in store.values() if isinstance(v, dict) and (v.get("extra") or {}).get("kind") == "signals"), None)
    if value_q and sig:
        dong = sig["dong"]
        lvl = {"많음": "많은 편", "적음": "적은 편", "높음": "높은 편", "낮음": "낮은 편", "보통": "보통"}
        parts = [f"{s['short']} {lvl.get(s['level'], s['level'])}" for s in sig["items"]]
        conclusion = {"text": f"{_josa(dong)} " + ", ".join(parts) + "이에요(제주 43개 동네 가운데 위치). 기준과 수치는 아래에 정리했어요.", "layer": "L5", "tag": GUIDE}
    else:
        rank = {"L4": 4, "L3": 3, "L1": 1, "L2": 0, "L5": 0}
        cmp_ = next((x for x in o.lines if x.get("kind") == "compare"), None)
        lead = next((x for x in o.lines if x.get("kind") == {"T9": "similar"}.get(t.get("type"), "survival")), None)
        if t.get("type") == "T4":  # 센터 자료의 흐름 줄이 있으면 그것이 결론(문서 20 A6)
            lead = next((x for x in o.lines if x.get("kind") == "flow"), lead)
        best = cmp_ if (t.get("type") == "T2" or t.get("details")) and cmp_ else lead if lead else max(o.lines, key=lambda x: (rank[x["layer"]], -o.lines.index(x)), default=None)
        conclusion = {"text": best["text"], "layer": best["layer"], "tag": best["tag"]} if best else {"text": "확인된 결과가 없어요.", "layer": None, "tag": None}
        if best and best["layer"] == "L1" and getattr(o, "rank_head", None):  # 순위 질문은 1~3위를 결론으로(문서 20 A9)
            conclusion["text"] = o.rank_head
    blocks = []
    for b in ("facts", "analysis", "guide"):
        ls = [x for x in o.lines if x["block"] == b]
        if ls or (b == "guide" and value_q):
            blk = {"id": b, "title": BLOCK_TITLE[b], "lines": ls}
            if b == "guide" and (value_q or sig):
                blk["closing"] = CLOSING
            blocks.append(blk)
    order_ = ["map", "map_sales", "map_visit", "map_stores", "map_survival", "biz_yearly", "yoy3", "rising", "monthly", "yearly", "hour", "bizcompare", "bizgrowth",
              "validation", "index", "contrib", "share", "supply", "foreign", "dongs"]
    o.views.sort(key=lambda v: order_.index(v["id"]) if v["id"] in order_ else len(order_))
    seen, views = set(), []
    for vw in o.views:
        if vw["id"] not in seen:
            seen.add(vw["id"])
            views.append(vw)
    footer, seen_src = [], set()
    for x in o.lines:  # 자료마다 기준 시점과 다음 갱신(날짜가 아닌 기준도 포함)
        src = x.get("source")
        key = re.sub(r"\(.*", "", src or "").replace(" 정보", "").strip()  # 같은 자료의 다른 표기(예: '793 상가' · '793 상가(상권) 정보')는 하나로
        if not src or key in seen_src or not x.get("as_of") or src.startswith(("통계 판정", "판단 기준", "레시피", "같은 자료")):
            continue
        seen_src.add(key)
        nxt = next((v for k, v in CADENCE.items() if k in src), "자료 제공처 공개 때")
        footer.append({"source": src, "as_of": x["as_of"], "next": nxt})
    for b in blocks:  # 화면용 출처 이름(내부 이름은 위의 판단·요청 계산에만 썼다)
        for x in b["lines"]:
            x["source"] = nice_source(x.get("source"))
    merged = {}
    for f in footer:
        f["source"] = nice_source(f["source"])
        merged.setdefault(f["source"], f)
    footer = [f for f in merged.values() if f["source"]]
    fresh = [dict(f, source=nice_source(f["source"]) or f["source"]) for f in fresh]
    return {"conclusion": conclusion, "blocks": blocks, "views": views, "default_views": 3, "value_question": bool(value_q), "footer": footer,
            "freshness": fresh, "requests": requests(t, store, o.lines), "numbers": o.numbers + POLICY_NUMBERS}
