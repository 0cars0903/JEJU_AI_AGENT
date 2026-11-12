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
import deep  # noqa: E402
import compare  # noqa: E402

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
# 임대료 참고값: 2025년 상가건물임대차 실태조사(중소벤처기업부) 결과를 전한 보도에서 옮김(https://www.dt.co.kr/article/12062733). 제주 보증금·권리금 값은 없다.
RENT = {"year": 2025, "jeju": 119, "nation": 112, "source": "상가건물임대차 실태조사(중소벤처기업부, 보도 인용)"}
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
        self.side = False  # 곁가지(단순 주제에 붙인 모델 결과·위치) 줄을 만드는 중인지. 곁가지 줄은 결론으로 고르지 않는다(문서 22)

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
        if self.side:
            self.lines[-1]["side"] = True

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
        only = f"{t['space'][0]}만 따로 센 자료는 없어 제주 전체 값이에요. " if t.get("space") else ""
        o.line("L1", f"{only}제주 전체 외국인 관광객 카드 매출이 많은 출신지역은 {og}{_cop(og)}.", src, tab["ym"].max())
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
        rl = v3.meta().get("rest_last", "") if metric in ("개업수", "폐업수") else ""
        part = rl.startswith(str(last)) and not rl.endswith("12-31")  # 아직 덜 찬 해: '곳/년'이 아니라 그날까지 센 수(이중 검토 035)
        for r in tab[tab["year"] == last].head(6).itertuples():
            v_ = o.num(r.value, "곳" if part else unit)
            when = f"{last}년({int(rl[5:7])}월 {int(rl[8:10])}일까지)" if part else f"{last}년"
            if part:
                o.numbers += [float(int(rl[5:7])), float(int(rl[8:10]))]
            o.line("L1", f"{when} {getattr(r, 'dong', '')} {word}{_josa(label)} {v_}{_cop(v_)}.", src, f"{last}년")
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
        # 임대료·권리금(사용자 승인 2026-11-12): 읍면동 단위 공개 자료가 없다. 월세는 시도 단위 참고값만 적고 권리금은 값 없이 현장 확인으로 남긴다.
        o.line("L5", f"임대료·권리금 — 동네별로 공개된 자료가 없어 이 답에 넣지 못했어요. 참고로 {RENT['year']}년 상가건물임대차 실태조사에서 제주 평균 월세는 "
                     f"{RENT['jeju']}만 원, 전국은 {RENT['nation']}만 원이었어요(제주 전체 평균이고 동네·업종별 값이 아니에요). 권리금은 제주 값이 공개되지 않아 현장에서 확인해 주세요.",
               RENT["source"], f"{RENT['year']}년 조사", tag=GUIDE)
        o.numbers += [float(RENT["year"]), float(RENT["jeju"]), float(RENT["nation"])]


def _judgement_lines(o, t, rv, ev):
    store = rv["run"]["store"]
    side_r = _side_recipes(rv)
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
                    o.trend = {"pct": pct, "up": up, "sig": sig}  # 종합 진단 5칸 요약의 '앞으로' 칸(문서 23)
                    txt = (f"{dong}: 최근 12개월 동안 작년 같은 달보다 평균 {pct}% {'늘었어요' if up else '줄었어요'}." if sig
                           else f"{dong}: 늘었는지 줄었는지는 자료로 가릴 수 없어요(작년 같은 달 대비 평균 {'+' if up else '-'}{pct}%, 우연히 생길 수 있는 크기).")
                else:
                    txt = f"{dong}: 최근 {'늘었어요' if up else '줄었어요'}." if sig else f"{dong}: 늘었는지 줄었는지는 자료로 가릴 수 없어요."
                if mk and s2 and s2.get("yoy_pct") is not None:  # 위 '12개월 합계' 비교와 값이 다른 이유(문서 20 A5)
                    txt += " 달마다 작년 같은 달과 견준 변화율을 평균한 값이라 위 합계 비교와 수치가 조금 달라요."
                o.line("L3", txt, None, tag="자료로 확인됨" if sig else NOT_SURE, kind="trend")
            elif "ci95" in j:
                cw = {"효과 있음": ("자료로 확인됨", "자료로 확인된 차이예요"), "작지만 0은 아님": ("자료로 확인됨", "차이는 있지만 ±10% 안의 작은 차이예요"),
                      "작음 확인": ("자료로 확인됨", "차이가 ±10% 안으로 작아요"), "판단 불가": (NOT_SURE, "차이를 확인하지 못했어요")}.get(j["claim"], (NOT_SURE, j["claim"]))
                cond = "·".join(t.get("cond") or []) or "조건"
                head = f"비 오는 날 {j['name']} 방문" if t.get("type") != "T6" else f"{cond}에 따른 {j['name']} 방문"
                lo, hi = (round(float(c), 1) for c in j["ci95"])
                eff = round(float(j["effect_pct"]), 1) if j.get("effect_pct") is not None else None
                o.numbers += [abs(lo), abs(hi), lo, hi] + ([abs(eff), eff] if eff is not None else [])
                rng = f"자료로 본 범위 {lo}% ~ {hi}%"
                if eff is not None and j["claim"] in ("효과 있음", "작지만 0은 아님"):  # 방향과 크기를 결론 줄에 쓴다(문서 20 A8)
                    txt = f"{head}: 약 {abs(eff)}% {'줄어요' if eff < 0 else '늘어요'}({rng}). {cw[1]}."
                else:
                    txt = f"{head}: {cw[1]}({rng})."
                o.side = "R3" in side_r
                o.line("L3", txt, None, tag=cw[0], kind="rain")
                o.side = False
            elif j["name"].startswith("관문"):
                rid = j["name"].split()[-1]
                name = recipes.REG.get(rid, {}).get("name", rid)
                if j["use_forecast"]:
                    for fv in store.values():
                        if isinstance(fv, dict) and fv.get("recipe") == rid and fv.get("forecast"):
                            if t.get("type") != "T8" and rid == "R1":  # 종합 진단·단순 주제의 곁가지 예상은 한 줄로 줄인다
                                o.side = rid in side_r
                                _visit_forecast_lines(o, fv, j)
                                o.side = False
                                continue
                            for i, f in enumerate(fv["forecast"][:3]):
                                key = "visit" if "visit" in f else "value"
                                u = "원" if rid == "R10" else "지수"
                                rng = f" (예상 범위 {o.num(f['lo'], u)}~{o.num(f['hi'], u)})" if "lo" in f else ""
                                # 날짜 예상은 '자료가 끝난 다음 7일'이다. 오늘 기준 다음 주가 아님을 첫 줄에 밝힌다(문서 20 A2)
                                if i == 0 and f.get("date") and fv.get("data_last"):
                                    o.numbers += [7.0, float(str(fv["data_last"])[8:10] or 0)]
                                base = f" — 유동인구 자료가 {fv['data_last']}까지 있어서 그 다음 7일을 예상한 값이에요(오늘 기준 다음 주가 아니에요)" if i == 0 and f.get("date") and fv.get("data_last") else ""
                                o.line("L4", f"{f['dong']} {f.get('date') or f.get('ym')} {name}: {o.num(f[key], '원' if rid == 'R10' else '지수')}{rng}{base}", None,
                                       tag="예상 범위(10번 중 8번 맞는 폭)" if rng and rid != "R1" else f"모델 예상 · 자료 ~{fv.get('data_last') or ''}".rstrip(" ~·"), kind="forecast")
                elif t.get("type") != "T8":  # 종합 진단·단순 주제의 곁가지: 예상하지 않는 사유와 작년 같은 달 값을 한 줄로(문서 21 3.1절)
                    rv_ = next((x for x in store.values() if isinstance(x, dict) and x.get("recipe") == rid and x.get("reference")), None)
                    if not rv_:
                        continue
                    o.side = rid in side_r
                    r, vv = rv_["reference"], rv_.get("validation") or []
                    txt = f"다음 달({_ym_ko(r['next'])}) {r['dong']} {r['biz']} 카드 매출은 예상하지 않아요."
                    ratio = round(float(j["mase"]) * 100)
                    o.numbers.append(float(ratio))
                    txt += f" 검증해 보니 모델 예상의 오차가 '작년 같은 달 값을 그대로 쓰는 방법'의 약 {ratio}%였어요. 거의 같아서 모델을 쓰는 이점을 확인하지 못했어요."
                    if vv:
                        o.numbers += [float(rv_["closer"]), float(len(vv))]
                        txt += f" 이 동네·업종에서 모델 예상이 실제에 더 가까웠던 달은 지난 {len(vv)}개월 가운데 {rv_['closer']}개월이에요."
                        o.view("validation", "최근 12개월 검증 기록", "line", [{"name": "실제", "points": [[x["ym"], x["actual"]] for x in vv]},
                                                                              {"name": "모델 예상", "points": [[x["ym"], x["model"]] for x in vv]},
                                                                              {"name": "작년 같은 달", "points": [[x["ym"], x["baseline"]] for x in vv]}],
                               "매달 그 달을 미리 예상했다면 어땠는지 보여 줍니다")
                    if r.get("value"):
                        txt += f" 참고로 작년 같은 달({_ym_ko(r['ref_ym'])}) 값은 {o.num(r['value'], '원')}이었어요(예상 아님)."
                        same = _same_month(r)
                        if len(same) >= 2:  # 문서 22 4절 R10: 최근 3년 같은 달 범위
                            lo_, hi_ = min(same, key=lambda x: x[1]), max(same, key=lambda x: x[1])
                            o.numbers += [float(len(same))] + [float(x) for x in re.findall(r"\d+", _ym_ko(lo_[0]) + _ym_ko(hi_[0]))]
                            txt += f" 최근 {len(same)}년 같은 달 값은 {o.num(lo_[1], '원')}({_ym_ko(lo_[0])})~{o.num(hi_[1], '원')}({_ym_ko(hi_[0])}) 사이였어요."
                    o.line("L4", txt, v3.KTO, None, tag="예상하지 않음", kind="salesfc")
                    o.side = False
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


DIAG_ORDER = {k: i for i, k in enumerate(["decomp", "survival", "forecast", "similar", "salesfc", "anomaly", "season", "rain", "trend"])}
FEATURE_KO = {"visit_resd": "사는 사람에 견준 방문", "work_resd": "사는 사람에 견준 직장 인구", "bus_per_day": "버스 이용"}


def _feature_ko(k):
    if k.startswith("biz_"):
        return f"{k[4:]} 업종 비중"
    if k.startswith("age_"):
        return f"{k[4:].replace('대이상', '대 이상').replace('세미만', '세 미만')} 거주 비중"
    return FEATURE_KO.get(k, k)


def _visit_forecast_lines(o, fv, j):
    """종합 진단의 방문 예상: 7일을 한 줄로 줄이고(값 + 예상 범위), 검증 기록을 쉬운 말로 붙인다(문서 21 3.1절)."""
    fc = fv["forecast"]
    lo, hi = min(fc, key=lambda r: r["visit"]), max(fc, key=lambda r: r["visit"])
    days = f"{fc[0]['date']}~{fc[-1]['date'][5:]}"
    o.numbers += [float(len(fc)), float(str(fv["data_last"])[8:10] or 0)] + [float(x) for r in (fc[0], fc[-1]) for x in r["date"].split("-")]
    wd = lambda r: "월화수목금토일"[pd.Timestamp(r["date"]).dayofweek]
    o.fc = {"lo": o.num(lo["visit"], "지수"), "hi": o.num(hi["visit"], "지수"), "days": days}  # 5칸 요약(문서 23)
    txt = f"{lo['dong']} 하루 방문 예상({days}, {len(fc)}일): 적은 날({wd(lo)}요일) {o.num(lo['visit'], '지수')}, 많은 날({wd(hi)}요일) {o.num(hi['visit'], '지수')}예요."
    if "lo" in lo:
        txt += f" 예상 범위까지 보면 {o.num(min(r['lo'] for r in fc), '지수')}~{o.num(max(r['hi'] for r in fc), '지수')}예요."
    txt += f" 유동인구 자료가 {fv['data_last']}까지 있어서 그 다음 {len(fc)}일을 예상한 값이에요(오늘 기준 다음 주가 아니에요)."
    rp = fc[0].get("rain_effect_pct")
    if rp is not None:  # 비 보정이 들어간 8곳: 맑은 날·비 오는 날 예상을 함께(문서 22 4절 R1 + R3)
        o.numbers.append(abs(rp))
        txt += f" 이 동네 예상에는 비에 따른 변동을 따로 넣었어요. 비가 오면 위 값보다 약 {abs(rp)}% {'적게' if rp < 0 else '많게'} 예상해요."
        o.view("rainfc", "맑은 날·비 오는 날 예상", "line", [{"name": "비 안 오는 날", "points": [[r["date"], r["visit"]] for r in fc]},
                                                       {"name": "비 오는 날", "points": [[r["date"], round(r["visit"] * (1 + rp / 100), 1)] for r in fc]}],
               f"비가 오면 하루 방문을 약 {abs(rp)}% {'적게' if rp < 0 else '많게'} 예상해요", x="date", unit="지수")
    o.line("L4", txt, "583 유동인구", None, tag=f"모델 예상 · 자료 ~{fv['data_last']}", kind="forecast")
    o.view("forecast", "다음 7일 방문 예상", "line", [{"name": "예상", "points": [[r["date"], r["visit"]] for r in fc]},
                                                {"name": "예상 범위 아래", "points": [[r["date"], r.get("lo")] for r in fc]},
                                                {"name": "예상 범위 위", "points": [[r["date"], r.get("hi")] for r in fc]}],
           "자료가 끝난 다음 7일의 예상값과 예상 범위(10번 중 8번 맞게 잡은 폭)예요", x="date", unit="지수")
    md = (fv.get("mase_by_dong") or {}).get(lo["dong"])
    ratio = round(float(j["mase"]) * 100)
    m = re.search(r"포함률 (\d+)~(\d+)%", recipes.REG["R1"].get("interval") or "")
    o.numbers += [float(ratio), 7.0, 1.0]
    txt = f"방문 예상의 검증 기록이에요. 예상 오차는 '7일 전 값을 그대로 쓰는 단순 예상'의 약 {ratio}%였어요(단순 예상보다 오차가 작아요)."
    if m and "lo" in lo:
        o.numbers += [float(m.group(1)), float(m.group(2))]
        txt += f" 예상 범위는 10번 중 8번 맞도록 잡았어요. 지난 기록으로 확인하니 100번 중 {m.group(1)}~{m.group(2)}번 맞았어요" + ("(범위가 좁게 잡혀요)." if int(m.group(1)) < 75 else ".")
    if md is not None:  # 동네별 정확도(문서 22 4절 R1 ②)
        r2 = round(float(md) * 100)
        o.numbers.append(float(r2))
        txt += f" {lo['dong']}만 보면 오차가 단순 예상의 약 {r2}%예요" + ("." if r2 < 90 else "(단순 예상과 비슷해요)." if r2 <= 110 else "(이 동네는 단순 예상의 오차가 더 작았어요).")
    o.line("L4", txt, None, tag="검증 기록", kind="forecast")


KM_LABEL = {"제주 평균보다 낮음": ("제주 전체보다 낮아요", "자료로 확인됨"), "제주 평균보다 높음": ("제주 전체보다 높아요", "자료로 확인됨"),
            "차이 확인 안 됨": ("제주 전체와 견줘 차이를 확인하지 못했어요", NOT_SURE)}


def _dong_survival_line(o, dong, grp):
    """동네 음식점(업종 구분 없음)의 연차별 통과율과 5년 생존율 구간·판정(문서 22 4절 R4 ①②). '몇 년 넘기면 안정' 같은 해석은 쓰지 않는다."""
    k = pd.read_parquet(v3.TAB / "km.parquet")
    k = k[k["dong"] == dong].sort_values("year")
    if len(k) < 5:
        return
    s = list(k["survival_pct"])
    rate = [s[0]] + [b / a * 100 for a, b in zip(s, s[1:])]
    five = k[k["year"] == 5].iloc[0]
    word, tag = KM_LABEL.get(five["label"], (None, NOT_SURE))
    parts = ", ".join(f"{y}년차 {o.num(r, '%')}" for y, r in zip(k["year"], rate))
    o.numbers += [float(y) for y in k["year"]] + [float(five["n"]), 95.0]
    txt = (f"{dong} 음식점(업종 구분 없음, {int(five['n']):,}곳)이 해마다 다음 해까지 영업을 이어 간 비율이에요. {parts}예요. "
           f"5년 생존율은 {o.num(five['survival_pct'], '%')}(95% 구간 {o.num(five['lo_pct'], '%')}~{o.num(five['hi_pct'], '%')})")
    txt += f"이고, {word}." if word else "예요."
    o.line("L3", txt, "780 음식점 인허가(동네별 카플란-마이어, 연차 통과율 = 그해 생존율 ÷ 전해 생존율)", None, tag=tag, kind="survival")
    o.view("survdong", "동네 생존 곡선", "line", [{"name": f"{dong} 음식점 전체(%)", "points": [[f"{y}년", round(float(v), 1)] for y, v in zip(k["year"], s)]},
                                                {"name": f"제주 {grp['group']}(%)", "points": [[f"{r['year']}년", r["pct"]] for r in grp["curve"]]}],
           f"{dong} 음식점과 제주 {grp['group']}의 생존 곡선을 견줘요", x="year", unit="%")


def _same_month(r, years=3):
    """다음 달과 같은 달의 최근 몇 해 카드 매출(동네·대분류). [(ym, 값)]"""
    c = v3.card()
    s = c[(c["dong"] == r["dong"]) & (c["biz"] == r["biz"])].groupby("ym")["amt"].sum()
    out = [(v3._months_back(r["next"], 12 * k), float(s[v3._months_back(r["next"], 12 * k)])) for k in range(1, years + 1) if v3._months_back(r["next"], 12 * k) in s.index]
    return out


def _event_view(o, dong, tgt):
    import places
    e = pd.read_parquet(v3.TAB / "rest_events.parquet")
    e = e[e["dong"] == dong]
    cats = places.REST_MAP.get(tgt) if tgt and tgt != "음식점" else None
    if cats:
        e = e[e["category"].isin(cats)]
    pv = e.pivot_table(index="year", columns="kind", values="count", aggfunc="sum").fillna(0).sort_index().tail(8)
    if len(pv) < 4:
        return
    w = f"{tgt} " if tgt and tgt != "음식점" else "음식점 "
    o.view("events", "연도별 개업·폐업", "bar", [{"name": n, "points": [[int(y), float(pv.loc[y, k])] for y in pv.index]} for k, n in (("open", "개업"), ("close", "폐업")) if k in pv],
           f"{dong} {w}개업·폐업 수를 해마다 보여 줘요(마지막 해는 덜 찼을 수 있어요)", x="year", unit="곳")


def _compare_lines(o, t):
    """동네 비교(문서 22 3절): 5절 표와 요약 줄. 어느 쪽이 낫다는 판단은 쓰지 않는다."""
    a, b = t["space"][:2]
    tgt = t.get("target") if t.get("target") in v3.FOOD or t.get("target") in ("숙박", "소매", "편의점") else None
    cmp_ = compare.table([a, b], tgt)
    rows = [r for s in cmp_["sections"] for r in s["rows"]]
    short = lambda r: re.sub(r"\(.*?\)", "", r["label"]).strip()
    diff = [short(r) for r in rows if r["verdict"] == compare.DIFF]
    same = [short(r) for r in rows if r["verdict"] == compare.SAME]
    rank = [short(r) for r in rows if r["verdict"] == compare.RANK]
    o.numbers += [float(len(rows)), float(len(diff)), float(len(same)), float(len(rank)), 5.0]
    txt = f"{_josa(a, '과', '와')} {_josa(b, '을', '를')} {len(rows)}개 지표로 견줬어요. 자료로 차이가 확인된 지표는 {len(diff)}개, 확인되지 않은 지표는 {len(same)}개"
    txt += (f", 순위로만 견준 지표는 {len(rank)}개예요." if rank else "예요.") + (f" 차이가 확인된 지표: {', '.join(diff)}." if diff else "")
    o.line("L3", txt, "통계 판정(같은 날짜·같은 달끼리 짝 지은 Wilcoxon 검정, 생존율은 95% 구간)", None, tag="자료로 확인됨" if diff else NOT_SURE, kind="compare_sum")
    f = cmp_.get("forecast")
    if f:
        o.view("cmpfc", "두 동네 방문 예상", "line", [{"name": d, "points": [[x, round(v, 1)] for x, v in zip(f["dates"], f[d]["visit"])]} for d in (a, b)],
               "자료가 끝난 다음 7일의 하루 방문 예상을 두 동네로 견줘요", x="date", unit="지수")
    o.compare = cmp_


def _biz_notice(t, lines):
    """카페처럼 카드 매출이 대분류로만 있는 업종: 답 위에 한 줄로 알린다(이중 검토 035: '카페 매출 105억'으로 읽힐 위험)."""
    tgt = t.get("target")
    b, note = v3.biz5_of(tgt)
    if not note or not any(f"{b} 전체({tgt} 포함)" in x["text"] for x in lines):
        return {}
    return {"notice": f"{tgt}만의 카드 매출 자료는 없어요. 매출 값은 {b} 전체(카페·한식 등 모두 포함)예요. 가게 수·개업·폐업은 {tgt}만 센 값이에요."}


def _side_recipes(rv):
    """곁가지로 붙인 레시피 번호(실행 지시서의 optional S3)."""
    return {x.get("recipe") for x in rv["order"]["tasks"] if x.get("optional") and x["sub"] == "S3"}


def _diagnosis_lines(o, t, store, side_r=frozenset()):
    """모델 결과 줄: 업종 생존 곡선, 닮은 동네와 이유, 개업·폐업 이례, 계절 유형. 예상(방문·매출)과 비 효과는 판정 줄에서 쓴다.
    종합 진단(T10)은 전부, 단순 주제는 생존·이례만 여기서 쓴다(닮은 동네는 위치 줄, 계절은 계절 곡선 줄이 대신한다, 문서 22)."""
    tgt, diag = t.get("target"), t.get("type") == "T10"
    for v in store.values():
        if not isinstance(v, dict):
            continue
        o.side = v.get("recipe") in side_r
        s = v.get("survival")
        if s and s.get("curve"):
            c = {r["year"]: r["pct"] for r in s["curve"]}
            o.numbers += [float(s["n"]), 1.0] + [float(x) for x in re.findall(r"\d+", s.get("cohort") or "")]
            pre = f"{tgt} 표본이 적어 음식점 전체로 계산했어요. " if v.get("fallback") else ""
            grp = "음식점" if s["group"] == "음식점 전체" else s["group"]
            o.line("L4", f"{pre}{_josa(grp)} 문을 연 뒤 1년에 {o.num(c[1], '%')}, 3년에 {o.num(c[3], '%')}, 5년에 {o.num(c[5], '%')}가 영업 중이었어요. "
                         f"제주 전체 {s['n']:,}곳({s.get('cohort')} 개업)을 센 값이고, 5년 값의 오차는 ±{o.num(s['ci95_pp'], '%p')}예요.",
                   "780 음식점 인허가", None, tag="생존 추정", kind="survival")
            o.view("survcurve", "개업 뒤 생존 곡선", "line", [{"name": f"{s['group']} 영업 중 비율(%)", "points": [[f"{k}년", p] for k, p in c.items()]}],
                   f"{s['group']} 가게가 개업 뒤 해마다 얼마나 남는지 보여 줘요(제주 전체)", x="year", definition=DEFS["survival"], unit="%")
            o.numbers += [float(p) for p in c.values()]
            if len(t.get("space") or []) == 1:
                _dong_survival_line(o, t["space"][0], s)
        for d, nb in ((v.get("neighbors") or {}) if diag or t.get("type") == "T9" else {}).items():
            why = (v.get("why") or {}).get(d) or []
            m = re.search(r"(\d+)%", v.get("gate") or "")
            o.numbers += [float(len(nb)), 2024.0, 2025.0] + ([float(m.group(1))] if m else [])
            txt = f"{_josa(d, '과', '와')} {'비슷한' if t.get('type') == 'T9' else '닮은'} 동네는 {', '.join(nb)}{_cop(nb[-1])}(업종 구성·연령·방문·버스 이용이 가까운 {len(nb)}곳)."
            if why:
                def _w(w):
                    head = f"{_feature_ko(w['feature'])}{'이 높은 편' if w['high'] else '이 낮은 편'}"
                    if "value" not in w or not w["feature"].startswith(("biz_", "age_")):
                        return head  # 비율 특성만 수치로 쓴다(방문·버스 특성은 로그 값이라 뜻이 어렵다)
                    vals = [round(w[k] * 100, 1) for k in ("value", "nb_mean", "all_mean")]
                    o.numbers += vals
                    return f"{head}이에요({d} {vals[0]}%, 닮은 {len(nb)}곳 평균 {vals[1]}%, 43곳 평균 {vals[2]}%)"
                txt += f" 닮은 점은 {len(why)}가지예요. " + " ".join(f"{_w(w)}." if _w(w).endswith(")") else f"{_w(w)}이에요." for w in why)
                o.numbers.append(float(len(why)))
            if m:
                txt += f" 2024년과 2025년 자료로 따로 계산해도 이웃의 {m.group(1)}%가 같았어요."
            o.line("L4", txt, "상가·유동인구·버스 자료(Agent 계산)", None, tag="Agent 계산", kind="similar")
        if v.get("anomaly") and t.get("type") != "T15" and len(v["anomaly"]) == 1:  # 문서 22 4절 R7: 연도별 개업·폐업 표
            _event_view(o, v["anomaly"][0]["dong"], tgt)
        for a in (v.get("anomaly") or []) if t.get("type") != "T15" else []:
            flagged = a["flag"] in ("많음", "적음")
            word = f"{tgt} " if tgt and tgt != "음식점" else "음식점 "
            o.numbers += [float(a["year"]), 3.0]
            tail = (f"보다 뚜렷이 {'많아요' if a['flag'] == '많음' else '적어요'}(우연으로 보기 어려운 크기)" if flagged else "과 견줘 평소 범위 안이에요")
            o.line("L3", f"{a['year']}년 {a['dong']} {word}{v.get('kind')}은 {o.num(a['count'], '곳')}으로, 앞선 3년 평균 {o.num(a['expected'], '곳')}{tail}.",
                   "780 음식점 인허가", None, tag="자료로 확인됨" if flagged else "평소 범위", kind="anomaly")
        for d, st in ((v.get("season_type") or {}) if diag else {}).items():
            mon = int(re.match(r"\d+", st["group"]).group())
            o.numbers += [float(mon), float(len(st["same_type"])), 43.0]
            o.line("L4", f"{_josa(d)} 한 해 가운데 {mon}월에 방문이 가장 많은 유형이에요(월별 방문 흐름으로 43개 동네를 두 유형으로 나눴고, 같은 유형은 {len(st['same_type'])}곳). "
                         "두 유형의 경계는 뚜렷하지 않아서 참고로만 봐 주세요.", "583 유동인구", None, tag="Agent 계산", kind="season")
    o.side = False


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
    if any("임대료·권리금" in str(x.get("text")) for x in lines):  # 임대료·권리금은 이 Agent에 없다 → 볼 수 있는 곳을 알린다
        out.append({"kind": "update", "title": "임대료·권리금은 다른 통계와 현장에서 확인", "data": "상업용부동산 임대동향조사(한국부동산원) · 상가건물임대차 실태조사(중소벤처기업부)",
                    "where": "한국부동산원 부동산통계정보 R-ONE https://www.reb.or.kr/r-one/ · 공공데이터포털 부동산통계 조회 서비스 https://www.data.go.kr/data/15134761/openapi.do", "steps": [],
                    "why": "임대료와 권리금은 동네(읍면동) 단위로 공개된 자료를 찾지 못해 이 답에 들어 있지 않아요. 아래 통계와 부동산 중개업소에서 직접 확인해 주세요."})
    return out


def _anomaly_lines(o, t, store):
    """이례 변화 질문(T15)의 줄: 마지막 완전 연도의 개업·폐업 수가 앞선 3년 평균에서 우연으로 보기 어려울 만큼 벗어난 동네·업종(R7)."""
    for v in store.values():
        rows = v.get("anomaly") if isinstance(v, dict) else None
        if not rows:
            continue
        kind, by_biz, year = v.get("kind"), v.get("by") == "업종", rows[0]["year"]
        tgt = t.get("target") if t.get("target") and t.get("target") != "음식점" else "음식점"
        name = (lambda a: a["biz"]) if by_biz else (lambda a: a["dong"])
        where = f"{rows[0]['dong']} " if by_biz else ""
        unit = "음식 업종" if by_biz else "동네"
        o.numbers += [float(year), 3.0, float(len(rows))] + ([float(v["end_year"])] if v.get("end_year") else [])
        head = f"{v['end_year']}년은 아직 다 차지 않아 {year}년으로 봤어요. " if v.get("end_year") and v["end_year"] != year else ""
        src = "음식점 인허가 기록(그해 수와 앞선 3년 평균의 차이 ÷ 평균의 제곱근이 2를 넘는지)"
        if len(rows) == 1:
            a = rows[0]
            flagged = a["flag"] in ("많음", "적음")
            tail = f"보다 뚜렷이 {'많아요' if a['flag'] == '많음' else '적어요'}(우연으로 보기 어려운 크기)" if flagged else "과 견줘 평소 범위 안이에요"
            o.line("L3", f"{head}{year}년 {a['dong']} {tgt} {kind}은 {o.num(a['count'], '곳')}으로, 앞선 3년 평균 {o.num(a['expected'], '곳')}{tail}.", src, None,
                   tag="자료로 확인됨" if flagged else "평소 범위", kind="anomaly")
            continue
        for flag, word in (("많음", "많은"), ("적음", "적은")):
            hit = sorted((a for a in rows if a["flag"] == flag), key=lambda a: -abs(a["z"]))[:5]
            if not hit and flag == "적음":
                continue
            subj = f"{head if flag == '많음' else ''}{year}년 {where}{'' if by_biz else tgt + ' '}{kind}이 앞선 3년 평균보다 뚜렷이 {word} {unit}"
            if hit:
                ls = ", ".join(f"{name(a)}({o.num(a['count'], '곳')}, 평균 {o.num(a['expected'], '곳')})" for a in hit)
                o.line("L3", f"{subj}{'은' if by_biz else '는'} {ls}{_cop(ls)}.", src, None, tag="자료로 확인됨", kind="anomaly")
            else:
                o.line("L3", f"{subj}{'은' if by_biz else '는'} 없어요({unit} {len(rows)}곳 모두 평소 범위이거나 더 적어요).".replace(f"{unit} {len(rows)}곳", f"{len(rows)}개 {unit}" if by_biz else f"{len(rows)}개 동네"),
                       src, None, tag="평소 범위", kind="anomaly")


def _composite_lines(o, t, dong):
    """종합 진단의 복합 지표 줄(문서 21 4절 (가)): 건당 결제 금액·방문에 견준 가게 수·업종 특화도·시간대 소비·개업−폐업·3개년 매출.
    둘 이상의 칸으로 계산한 값이라 계산식을 출처 괄호에 적는다."""
    import places
    tgt, det = t.get("target"), t.get("detail")
    names = qparse.DETAIL.get(det, {}).get("names") if det else None
    biz, _ = v3.biz5_of(tgt)
    rest = not tgt or tgt in v3.FOOD
    x = v3.composite(dong, tgt, biz, cats=(places.REST_MAP.get(tgt) if rest else False), names=names)
    bw, sw = biz or "전 업종", det if names else tgt
    shop = "숙박업소" if sw == "숙박" else f"{sw} 가게"
    k = x.get("ticket")
    if k:
        by = k["by"]
        o.numbers += [float(v) for v in re.findall(r"\d+", _ym_ko(k["ym"]))]
        txt = f"{_ym_ko(k['ym'])} {dong} {bw} 결제 1건당 금액은 " + ", ".join(f"{c} {o.num(v['value'], '원')}" for c, v in by.items())
        txt = txt + _cop(txt) + "(43개 동네 중간값은 " + ", ".join(f"{c} {o.num(v['median'], '원')}" for c, v in by.items()) + ")."
        o.line("L1", txt, f"{v3.KTO}({k['basis']})", k["ym"], kind="ticket")
        first = next(iter(by.items()))  # 손익분기 칸의 결제 1건당 금액 기본값(문서 23 B, 사용자 결정 2026-11-12)
        o.bep = {"ticket": int(round(first[1]["value"])), "basis": f"{_ym_ko(k['ym'])} {dong} {bw} {first[0]} 결제 1건당 금액"}
    d = x.get("density")
    if d and sw:
        o.numbers += [1.0, float(d["rank"]), float(d["of"])]
        a, m = o.num(d["value"], "곳"), o.num(d["median"], "곳")
        o.line("L2", f"{dong} {shop}는 하루 방문 1만 지수당 {a}{_ro(a)}, 43곳 중 {d['rank']}위예요(중간값 {m}). 값이 클수록 방문에 견줘 {shop}가 많다는 뜻이에요.",
               f"상가 정보·유동인구({d['basis']})", None, kind="density")
    q = x.get("lq")
    if q and sw:
        o.numbers += [1.0, float(q["rank"]), float(q["of"]), round(q["value"], 2)]
        side = "제주 평균보다 높아요" if q["value"] > 1.1 else "제주 평균보다 낮아요" if q["value"] < 0.9 else "제주 평균과 비슷해요"
        o.line("L2", f"{dong} 가게 가운데 {sw} 비중은 {o.num(q['share_pct'], '%')}로 제주 전체({o.num(q['jeju_pct'], '%')})의 {round(q['value'], 2)}배예요(43곳 중 {q['rank']}위). "
                     f"이 동네 가게 가운데 {shop} 비중은 {side}.", f"상가 정보({q['basis']})", v3.BIZ_ASOF, kind="lq")
    h = x.get("hours")
    if h:
        o.numbers += [float(h["peak"]), 11.0, 14.0, 17.0, 21.0, 22.0, 4.0]
        o.line("L1", f"{dong} {bw} 카드 결제는 {h['peak']}시에 가장 많아요(하루 매출의 {o.num(h['peak_pct'], '%')}). 시간대로 묶으면 "
                     + ", ".join(f"{n} {o.num(v, '%')}" for n, v in h["bands"].items()) + f"예요({h['from']}~{h['to']} 합계).",
               f"{v3.KTO}({h['basis']})", h["to"], kind="hours")
        o.view("hour", "시간대", "bar", [{"name": dong, "points": h["points"]}], f"{h['peak']}시에 매출 비중이 가장 큽니다", x="hour", unit="%")
        o.numbers += [float(p[1]) for p in h["points"]]
    n = x.get("net")
    if n:
        word = f"{tgt} " if tgt and tgt != "음식점" else "음식점 "
        parts = []
        for r in n["rows"]:
            o.numbers += [float(r["year"]), float(r["open"]), float(r["close"]), float(abs(r["net"]))]
            parts.append(f"{r['year']}년 {'+' if r['net'] > 0 else '−' if r['net'] < 0 else ''}{abs(r['net'])}곳(개업 {r['open']}, 폐업 {r['close']})")
        o.line("L1", f"{dong} {word}개업 수에서 폐업 수를 뺀 값이에요. " + ", ".join(parts) + "예요.", f"음식점 인허가 기록({n['basis']})", f"{n['rows'][-1]['year']}년", kind="net")
    y = x.get("yearly")
    if y:
        rows, ch = y["rows"], round(y["change_pct"], 1)
        o.numbers += [float(r["year"]) for r in rows] + [abs(ch), 2.0]
        o.line("L2", f"{dong} {bw} 카드 매출은 " + ", ".join(f"{r['year']}년 {o.num(r['amt'], '원')}" for r in rows)
                     + f"으로, 2년 사이 {abs(ch)}% {'늘었어요' if ch > 0 else '줄었어요'}.", f"{v3.KTO}({y['basis']})", None, kind="yearly3")


POS_LABEL = {"일평균방문": "하루 평균 방문(최근 12개월)", "매출": "카드 매출(최근 12개월)", "점포수": "가게 수", "5년생존율": "5년 생존율",
             "관광객비중": "관광객 매출 비중(최근 12개월)", "건당금액": "결제 1건당 금액(최근 12개월)", "이용건수": "결제 건수(최근 12개월)",
             "개업수": "개업 수", "폐업수": "폐업 수", "시간대매출": "매출이 많은 3개 시간대의 비중", "매출증감": "카드 매출 증감률(최근 12개월 ÷ 그 전 12개월)"}
POS_KEYS = {"업종비교": ["매출"], "시장추이": ["매출증감"], "조건부생존": ["5년생존율"]}
NB_SRC = "비슷한 동네(업종 구성·연령·방문·버스가 가까운 5곳, Agent 계산)"
def _decomp_line(o, dong, biz, word):
    """매출 = 결제 건수 × 1건당 금액 분해 줄(문서 22). 종합 진단은 5칸 요약의 매출 칸에도 쓴다(문서 23)."""
    d = deep.decomp(dong, biz)
    if not d:
        return None
    a, c, k = d["amt_pct"], d["cnt_pct"], d["ticket_pct"]
    tp, tc = round(d["ticket_prev"]), round(d["ticket_cur"])
    o.numbers += [abs(a), abs(c), abs(k), 12.0, float(tp), float(tc)]
    verb = lambda x, up, dn: "그대로" if x == 0 else f"{abs(x)}% {up if x > 0 else dn}"
    o.line("L4", f"{dong} {word}카드 매출은 최근 12개월이 그 전 12개월보다 {verb(a, '늘었어요', '줄었어요')}. "
                 f"결제 건수는 {verb(c, '늘고', '줄고')}, 1건당 금액({tp:,}원 → {tc:,}원)은 {verb(k, '늘었어요', '줄었어요')}. "
                 f"매출 변화에는 {d['driver']} 쪽 변화가 더 컸어요.", f"{v3.KTO}(매출 = 결제 건수 × 1건당 금액)", d["end"], tag="Agent 계산", kind="decomp")
    return d


ANA_ORDER = {k: i for i, k in enumerate(["position", "decomp", "swing", "season", "survival", "anomaly", "forecast", "salesfc", "rain", "rainrank", "similar", "spread", "trend"])}


def _pos_word(t, key):
    tgt, det = t.get("target"), t.get("detail")
    if key in ("일평균방문",):
        return "전체 " if tgt or det else ""
    if key == "5년생존율":
        return "음식점 전체 "
    if key in ("개업수", "폐업수"):
        return f"{tgt} " if tgt and tgt != "음식점" else "음식점 "
    if key == "점포수":
        return f"{det or tgt} " if det or tgt else "전 업종 "
    b, note = v3.biz5_of(tgt)
    return _biz_word(t, note, "매출") if tgt else "전 업종 "


def _position_line(o, t, dong, key, nb):
    """43곳 중 위치 + 비슷한 동네 5곳 평균과의 차이(문서 22 4절: 수치마다 순위와 비슷한 동네 대비 차이)."""
    names = (qparse.DETAIL.get(t.get("detail")) or {}).get("names") if t.get("detail") else None
    p = deep.position(dong, key, t.get("target"), names, nb)
    if not p:
        return
    u = p["unit"]
    word, label = _pos_word(t, key), POS_LABEL[key]
    o.numbers += [float(p["rank"]), float(p["of"]), float(p["top_pct"])]
    v_ = o.num(p["value"], u)
    year = f"{p['as_of']} " if str(p["as_of"]).endswith("년") else ""  # 개업·폐업은 마지막 완전 연도(이중 검토 035: 연도 없이 나왔다)
    if year:
        o.numbers.append(float(str(p["as_of"])[:4]))
    txt = f"{year}{dong} {word}{_josa(label)} {v_}{_ro(v_)} 제주 {p['of']}곳 중 {p['rank']}위예요."
    txt += f" 위에서 {p['top_pct']}%이고, 중간값은 {o.num(p['median'], u)}{_cop(o.num(p['median'], u))}."
    up, down = ("높아요", "낮아요") if u == "%" else ("많아요", "적어요")
    if p.get("nb"):
        o.numbers += [float(len(p["nb"])), abs(p.get("diff", 0.0))]
        avg = o.num(p["nb_avg"], u)
        d = p.get("diff")
        tail = ("와 거의 같아요" if d is not None and abs(d) < 1 else f"보다 {abs(d)}{p['diff_unit']} {up if d > 0 else down}") if d is not None else "과 견줄 수 없어요"
        txt += f" 비슷한 동네 {len(p['nb'])}곳의 평균 {avg}{tail}({', '.join(p['nb'])})."
        o.line("L4", txt, NB_SRC, None, tag="Agent 계산 · 비슷한 동네 기준", kind="position")
        o.view(f"pos_{key}", f"비슷한 동네와 {label}", "bar", [{"name": label, "points": [[dong, round(p["value"], 2)]] + [[n, round(x, 2)] for n, x in p["nb_values"].items()]}],
               f"{dong}과 비슷한 동네 {len(p['nb'])}곳의 {_josa(label, '을', '를')} 견줘요", x="dong", unit=u)
    else:
        o.line("L2", txt, None, p["as_of"], kind="position")


def _deep_lines(o, t, rv):
    """단순 주제(동네 하나)의 심화 줄(문서 22 3단계): 위치·비슷한 동네 대비 + 주제별 분해. 모두 곁가지라 결론으로 고르지 않는다."""
    store = rv["run"]["store"]
    tasks = {x["out"]: x for x in rv["order"]["tasks"]}
    metrics = [tasks[k].get("metric") for k in store if k in tasks and tasks[k]["sub"] == "S1" and tasks[k].get("metric")]
    nbs = next((v["neighbors"] for v in store.values() if isinstance(v, dict) and v.get("neighbors")), {})
    o.side = True
    try:
        if t.get("type") == "T3":  # 순위: 상위 집중도
            tab = next((v["table"] for v in store.values() if isinstance(v, dict) and "table" in v and "dong" in v["table"] and "value" in v["table"]), None)
            if tab is not None and len(tab):
                cur = tab[tab["ym"] == tab["ym"].max()] if "ym" in tab else tab
                sp = deep.spread(dict(zip(cur["dong"], cur["value"])))
                if sp:
                    o.numbers += [5.0, sp["top5_pct"], sp["first_vs_median"], float(sp["n"])]
                    o.line("L4", f"값이 큰 5곳이 {sp['n']}곳 합계의 {sp['top5_pct']}%를 차지하고, 1위는 중간값의 {sp['first_vs_median']}배예요. "
                                 f"{'몇 곳에 크게 몰려 있어요' if sp['top5_pct'] >= 40 else '여러 동네에 고르게 퍼져 있어요'}.", None, tag="Agent 계산", kind="spread")
            return
        sp = t.get("space") or []
        if len(sp) != 1:
            return
        dong = sp[0]
        if t.get("type") == "T9":  # 닮은 동네: 닮은 5곳 평균과 주요 지표 차이
            nb = nbs.get(dong)
            if nb:
                parts = []
                for key, name in (("일평균방문", "하루 방문"), ("매출", "카드 매출"), ("점포수", "가게 수")):
                    p = deep.position(dong, key, None, None, nb)
                    if p and p.get("diff") is not None:
                        o.numbers.append(abs(p["diff"]))
                        parts.append(f"{name} {'+' if p['diff'] > 0 else '−' if p['diff'] < 0 else ''}{abs(p['diff'])}%")
                if parts:
                    o.numbers.append(float(len(nb)))
                    o.line("L4", f"{dong}을 닮은 {len(nb)}곳 평균과 견주면 " + ", ".join(parts) + "예요(닮은 동네라도 규모는 다를 수 있어요).", NB_SRC, None, tag="Agent 계산", kind="position")
            return
        nb = nbs.get(dong)
        tgt = t.get("target")
        biz, _ = v3.biz5_of(tgt)
        keys = []
        for m in metrics:
            for k in POS_KEYS.get(m, [m]):
                if k in POS_LABEL and k not in keys:
                    keys.append(k)
        if t.get("type") == "T4" and "매출" in metrics:
            keys.append("매출증감")
        for k in keys:
            _position_line(o, t, dong, k, nb)
        word = _biz_word(t, v3.biz5_of(tgt)[1], "매출") if tgt else "전 업종 "
        if any(m in ("매출", "이용건수", "시장추이", "업종비교", "건당금액") for m in metrics):
            _decomp_line(o, dong, biz, word)
        if "관광객비중" in metrics:
            w = deep.swing(dong, biz)
            if w:
                r, tr = w["by"]["도민"], w["by"]["내국인 관광객"]
                o.numbers += [float(w["months"]), r["cv_pct"], tr["cv_pct"]] + ([tr["hi_lo"]] if tr.get("hi_lo") else [])
                o.line("L4", f"{dong} {word}월 카드 매출을 최근 {w['months']}개월 동안 보면, 도민 매출은 평균에서 약 {r['cv_pct']}% 오르내렸어요. "
                             f"관광객 매출은 약 {tr['cv_pct']}% 오르내려 {'도민보다 크게 흔들려요' if tr['cv_pct'] > r['cv_pct'] else '도민보다 덜 흔들려요'}. "
                             f"관광객 매출이 가장 많은 달은 {_ym_ko(tr['hi_ym'])}, 가장 적은 달은 {_ym_ko(tr['lo_ym'])}이에요" + (f"({tr['hi_lo']}배 차이)." if tr.get("hi_lo") else "."),
                       f"{v3.KTO}(월 매출의 표준편차 ÷ 평균)", w["to"], tag="Agent 계산", kind="swing")
            x = v3.composite(dong, tgt, biz, cats=False)
            k = x.get("ticket")
            if k:
                o.line("L1", f"{_ym_ko(k['ym'])} {dong} {word}결제 1건당 금액은 " + ", ".join(f"{c} {o.num(v['value'], '원')}" for c, v in k["by"].items())
                       + "이에요(43개 동네 중간값은 " + ", ".join(f"{c} {o.num(v['median'], '원')}" for c, v in k["by"].items()) + ").", f"{v3.KTO}({k['basis']})", k["ym"], kind="ticket")
                o.numbers += [float(v) for v in re.findall(r"\d+", _ym_ko(k["ym"]))]
        if "시간대매출" in metrics:
            h = deep.hour_vs(dong, biz)
            if h:
                g = h["gap"]
                o.numbers += [abs(x) for x in g.values()] + [11.0, 14.0, 17.0, 21.0, 22.0, 4.0]
                o.line("L2", f"제주 전체 같은 업종과 견주면 {dong}은 " + ", ".join(f"{b} {'+' if x > 0 else '−' if x < 0 else ''}{abs(x)}%p" for b, x in g.items())
                       + f"예요. {_josa(h['biggest'].split('(')[0], '이', '가')} 가장 크게 달라요.", f"{v3.KTO}(시간대 매출 비중의 차이, 최근 12개월)", h["to"], kind="hourcmp")
        if "일평균방문" in metrics:
            near = next((v["nearest"].get(dong) for v in store.values() if isinstance(v, dict) and (v.get("nearest") or {}).get(dong)), None)
            if near:
                gap = round((near["peak_ratio"] - near["low_ratio"]) * 100)
                o.numbers += [float(near["peak"]), float(near["low"]), float(gap), float(near["months"])]
                o.line("L4", f"{dong} 방문은 {near['peak']}월에 가장 많아요(한 해 평균의 {o.num(near['peak_ratio'], '배')}). {near['low']}월에 가장 적어요({o.num(near['low_ratio'], '배')}). "
                             f"성수기와 비수기 차이는 {gap}%p예요. 월별 흐름이 가장 비슷한 동네는 {', '.join(near['dongs'][:3])}{_cop(near['dongs'][2])}.",
                       "583 유동인구(월별 하루 평균 방문 ÷ 그 동네 한 해 평균)", None, tag="Agent 계산", kind="season")
        if "일평균방문" in metrics or t.get("type") == "T6":
            rr = deep.rain_rank(dong)
            if rr:
                o.numbers += [float(rr["rank"]), float(rr["of"]), float(rr["n_sig"]), abs(rr["effect_pct"])]
                o.line("L3", f"비 오는 날 방문이 줄어드는 정도는 {rr['of']}곳 가운데 {rr['rank']}번째로 커요({dong} {'+' if rr['effect_pct'] > 0 else '−'}{abs(rr['effect_pct'])}%). "
                             f"{rr['of']}곳 중 {rr['n_sig']}곳에서 0이 아닌 차이가 확인됐어요.", "기상·유동인구(동네별 회귀 검정)", None,
                       tag="자료로 확인됨" if rr["sig"] else NOT_SURE, kind="rainrank")
        if "점포수" in metrics:
            names = qparse.DETAIL.get(t.get("detail"), {}).get("names") if t.get("detail") else None
            x = v3.composite(dong, tgt, biz, cats=False, names=names)
            sw = (t.get("detail") if names else tgt) or "전 업종"
            shop = "숙박업소" if sw == "숙박" else f"{sw} 가게"
            q, dn = x.get("lq"), x.get("density")
            if q and tgt:
                o.numbers += [1.0, float(q["rank"]), float(q["of"]), round(q["value"], 2)]
                side = "제주 평균보다 높아요" if q["value"] > 1.1 else "제주 평균보다 낮아요" if q["value"] < 0.9 else "제주 평균과 비슷해요"
                o.line("L2", f"{dong} 가게 가운데 {sw} 비중은 {o.num(q['share_pct'], '%')}로 제주 전체({o.num(q['jeju_pct'], '%')})의 {round(q['value'], 2)}배예요(43곳 중 {q['rank']}위). "
                             f"가게 수가 많아도 동네 가게 가운데 {shop} 비중은 {side}.", f"상가 정보({q['basis']})", v3.BIZ_ASOF, kind="lq")
            if dn and tgt:
                o.numbers += [1.0, float(dn["rank"]), float(dn["of"])]
                a, m = o.num(dn["value"], "곳"), o.num(dn["median"], "곳")
                o.line("L2", f"{dong} {shop}는 하루 방문 1만 지수당 {a}{_ro(a)}, 43곳 중 {dn['rank']}위예요(중간값 {m}). 값이 클수록 방문에 견줘 {shop}가 많다는 뜻이에요.",
                       f"상가 정보·유동인구({dn['basis']})", None, kind="density")
        if any(m in ("개업수", "폐업수") for m in metrics) and (not tgt or tgt in v3.FOOD):
            import places
            x = v3.composite(dong, tgt, biz, cats=places.REST_MAP.get(tgt))
            n = x.get("net")
            if n:
                w = f"{tgt} " if tgt and tgt != "음식점" else "음식점 "
                parts = []
                for r in n["rows"]:
                    o.numbers += [float(r["year"]), float(r["open"]), float(r["close"]), float(abs(r["net"]))]
                    parts.append(f"{r['year']}년 {'+' if r['net'] > 0 else '−' if r['net'] < 0 else ''}{abs(r['net'])}곳(개업 {r['open']}, 폐업 {r['close']})")
                o.line("L1", f"{dong} {w}개업 수에서 폐업 수를 뺀 값이에요. " + ", ".join(parts) + "예요.", f"음식점 인허가 기록({n['basis']})", f"{n['rows'][-1]['year']}년", kind="net")
    finally:
        o.side = False


def _methods(lines, store):
    """답에 쓰인 모델별 '방법과 검증' 설명(문서 21 3.2절 부록 A). 화면의 접힌 설명과 PDF 부록이 같은 자료를 쓴다.
    항목: title(모델), how(방법), check(검증 방식·기준선), result(검증 수치), limit(쓸 수 없는 경우). 내부 이름(레시피 번호·오차 지표 이름)은 쓰지 않는다."""
    kinds = {x.get("kind") for x in lines}
    vals = [v for v in store.values() if isinstance(v, dict)]
    gate = {j["name"].split()[-1]: j for v in vals for j in v.get("judgement", []) if j.get("name", "").startswith("관문")}

    def ratio(rid):
        j = gate.get(rid)
        if not j:
            return ""
        b, n = (int(x) for x in str(j["better"]).split("/"))
        return f"빗나간 크기가 기준의 약 {round(float(j['mase']) * 100)}%였고, 견준 {n:,}개 짝 가운데 {b:,}개에서 모델이 더 가까웠어요."

    out = []
    if "forecast" in kinds and "R1" in gate:
        m = re.search(r"포함률 (\d+)~(\d+)%", recipes.REG["R1"].get("interval") or "")
        out.append({"kind": "forecast", "title": "하루 방문 예상",
                    "how": "지난 방문 기록에서 요일·달·공휴일·연휴와 7일 전·14일 전 값을 배워 다음 7일을 예상해요. 비의 영향이 큰 8개 동네는 비 효과를 더 반영해요.",
                    "check": "지난 기록을 세 시점(2025년 7월·10월, 2026년 1월)에서 끊고, 그 뒤 60일을 미리 예상해 실제 값과 견줬어요. 기준은 '7일 전 값을 그대로 쓰는 단순 예상'이에요. 예상 범위 폭은 동과 읍면을 나눠 잡아요(읍면은 오르내림이 커요).",
                    "result": ratio("R1") + (f" 예상 범위는 10번 중 8번 맞도록 잡았고, 한 시점을 빼고 잡은 범위로 그 시점을 확인하니 100번 중 {m.group(1)}~{m.group(2)}번 맞았어요." if m else ""),
                    "limit": "축제·태풍처럼 달력에 없는 일은 반영하지 못해요. 자료가 끝난 날 다음 7일만 예상해서 오늘 기준 다음 주와 다를 수 있어요. 값은 지수라서 사람 수로 읽을 수 없어요."})
    if "salesfc" in kinds and "R10" in gate:
        out.append({"kind": "salesfc", "title": "다음 달 카드 매출 예상(쓰지 않음)",
                    "how": "작년 같은 달 값에 최근 흐름을 더해 다음 달 카드 매출을 계산하는 방법이에요.",
                    "check": "최근 12개월을 달마다 미리 예상해 실제 값과 견줬어요(43개 동네 × 5개 업종). 기준은 '작년 같은 달 값을 그대로 쓰는 방법'이에요.",
                    "result": ratio("R10") + " 기준과 차이가 우연과 구분되지 않아서 예상값을 보여 주지 않아요.",
                    "limit": "예상값 대신 작년 같은 달 값을 참고로 보여 드려요. 이 값은 예상이 아니에요."})
    s = next((v["survival"] for v in vals if (v.get("survival") or {}).get("curve")), None)
    if "survival" in kinds:
        out.append({"kind": "survival", "title": "업종 생존율",
                    "how": "음식점 인허가 기록의 개업일과 폐업일로, 개업 뒤 해마다 영업 중인 비율을 계산해요. 아직 영업 중인 가게는 '그때까지 영업 중'으로 반영해요(카플란-마이어 방법).",
                    "check": "업종 표본이 150곳 이상일 때만 업종별로 계산하고, 모자라면 음식점 전체 값을 써요. 예상이 아니라 지난 기록의 집계라서 기준과 견준 오차는 없어요.",
                    "result": f"{s['group']} {s['n']:,}곳 기준이고, 5년 값의 오차는 ±{s['ci95_pp']}%p예요(95% 신뢰구간)." if s else "",
                    "limit": "제주 전체 값이라 동네별 차이는 알 수 없어요. 과거에 개업한 가게의 기록이라 지금 여는 가게의 결과를 보장하지 않아요. 음식점이 아닌 업종은 계산하지 못해요."})
    nb = next((v for v in vals if v.get("neighbors")), None)
    if ("similar" in kinds or "position" in kinds) and nb:  # 위치 줄의 '비슷한 동네 5곳'도 같은 계산(문서 22)
        m = re.search(r"(\d+)%", nb.get("gate") or "")
        out.append({"kind": "similar", "title": "닮은 동네",
                    "how": "업종 구성·연령·방문·버스 이용 지표를 같은 눈금으로 맞춘 뒤, 지표 사이 거리가 가까운 5곳을 골라요.",
                    "check": "2024년 자료와 2025년 자료로 따로 계산해 이웃이 그대로인지 확인했어요.",
                    "result": f"두 해에서 이웃의 {m.group(1)}%가 같았어요." if m else "",
                    "limit": "지표가 닮았다는 뜻이고 매출이나 성과가 같다는 뜻이 아니에요. 임대료·골목 분위기처럼 자료에 없는 것은 반영하지 못해요."})
    if any(x.get("kind") == "similar" and "월별 방문 흐름이 가까운" in x["text"] for x in lines):
        out.append({"kind": "seasonnear", "title": "월별 흐름이 가까운 동네",
                    "how": "월별 하루 평균 방문을 그 동네 한 해 평균으로 나눠 곡선을 만들고, 곡선 사이 거리가 가까운 5곳을 골라요.",
                    "check": "지난 기록으로 계산한 값이에요. 다른 해에도 같은 순서인지는 따로 검증하지 않았어요.", "result": "",
                    "limit": "방문 흐름의 모양만 견줘요. 방문 규모나 매출이 비슷하다는 뜻이 아니에요."})
    if "season" in kinds:
        m = re.search(r"실루엣 ([\d.]+), 두 해 ARI ([\d.]+)", recipes.REG["R6"].get("pass") or "")
        out.append({"kind": "season", "title": "계절 유형",
                    "how": "월별 방문 곡선이 비슷한 동네끼리 묶어 43개 동네를 두 유형으로 나눠요.",
                    "check": "묶음이 뚜렷한 정도(1에 가까울수록 뚜렷)와, 두 해를 따로 묶었을 때 결과가 일치하는 정도(1이면 완전 일치)를 계산했어요.",
                    "result": f"뚜렷한 정도는 {m.group(1)}, 두 해의 일치 정도는 {m.group(2)}예요. 둘 다 높지 않아요." if m else "",
                    "limit": "두 유형의 경계가 뚜렷하지 않아서 참고로만 써요. 유형이 같다고 매출 흐름이 같다는 뜻은 아니에요."})
    if "anomaly" in kinds:
        out.append({"kind": "anomaly", "title": "개업·폐업 이례",
                    "how": "그 해 개업·폐업 수를 앞선 3년 평균과 견줘요. 차이가 건수의 우연한 오르내림 폭(포아송 분포 기준 표준편차)의 2배를 넘으면 '뚜렷이 많음·적음'으로 표시해요.",
                    "check": "예상이 아니라 지난 기록끼리의 비교라서 기준과 견준 오차는 없어요. 기록이 4년 이상 있을 때만 계산해요.", "result": "",
                    "limit": "많고 적은 원인은 알려 주지 않아요. 건수가 적은 동네·업종은 한두 곳 차이로 표시가 바뀔 수 있어요. 아직 다 차지 않은 해는 쓰지 않아요."})
    if "rain" in kinds:
        out.append({"kind": "rain", "title": "비 오는 날 방문 차이",
                    "how": "동네별로 비 온 날과 오지 않은 날의 방문을 회귀 분석으로 견줘요. 날짜가 이어지며 생기는 비슷함을 감안해 오차 범위를 넓게 잡아요.",
                    "check": "차이가 0과 구분되는지와, 차이가 ±10% 안으로 작은지를 따로 검정해요. 여러 동네를 함께 볼 때 생기는 우연한 적중을 보정해요.",
                    "result": "답에 적은 '자료로 본 범위'가 95% 신뢰구간이에요.",
                    "limit": "방문(유동인구) 기준이고 매출 차이는 아니에요. 동네 평균이라 가게마다 다를 수 있어요."})
    if "compare_sum" in kinds:
        out.append({"kind": "compare", "title": "두 동네 차이 판정",
                    "how": "방문은 같은 날짜끼리, 카드 매출·증감률·관광객 비중·1건당 금액은 같은 달끼리 두 동네 값을 짝 지어 차이의 방향이 한쪽으로 쏠렸는지 봐요(Wilcoxon 부호순위 검정).",
                    "check": "틀릴 가능성 5% 미만이면 '차이 있음'이에요. 생존율은 두 동네의 95% 구간이 겹치지 않을 때, 방문 예상은 7일 모두 예상 범위가 떨어질 때 '차이 있음'이에요. 가게 수는 한 시점 값이라 검정하지 않고 43곳 중 순위만 적어요.",
                    "result": "",
                    "limit": "'차이 확인 안 됨'은 같다는 뜻이 아니라 자료로 가릴 수 없다는 뜻이에요. 차이가 있다고 해서 어느 동네가 낫다는 뜻은 아니에요. 방문 날짜가 많으면 작은 차이도 '차이 있음'이 될 수 있어요."})
    if "trend" in kinds:
        out.append({"kind": "trend", "title": "늘었는지 줄었는지 판정",
                    "how": "기간 동안 값이 오르내린 흐름에 직선을 맞추고, 그 기울기가 우연히 생길 수 있는 크기보다 큰지 검정해요.",
                    "check": "틀릴 가능성 5%를 기준으로 '자료로 확인됨'과 '가릴 수 없음'을 나눠요.", "result": "",
                    "limit": "'가릴 수 없음'은 변화가 없다는 뜻이 아니라 자료만으로 판단하기 어렵다는 뜻이에요. 왜 변했는지는 알려 주지 않아요."})
    return out


# 이 답에 없는 것과 확인할 곳(문서 23 B 기준: 조언이 아니라 빠진 자료와 확인 경로만 적는다)
GAPS = [
    {"what": "임대료·권리금", "why": "동네별 공개 자료가 없어요.", "where": "후보 자리 근처 부동산 중개사무소, 건물주"},
    {"what": "현금·계좌이체 매출", "why": "카드 결제만 센 자료예요.", "where": "같은 업종 가게의 판매 기록(POS), 상인회"},
    {"what": "실제 지나가는 사람 수", "why": "방문 값은 통신 자료로 추계한 지수라 사람 수가 아니에요.", "where": "후보 자리에서 시간대별로 직접 세기"},
    {"what": "가게 자리 하나의 조건(골목·층·주차·간판)", "why": "모든 값이 동네 단위예요.", "where": "후보 자리 현장 방문"},
    {"what": "앞으로의 개발·입주 계획", "why": "지난 기록만 쓴 자료예요.", "where": "제주시·서귀포시 도시계획 고시"},
]
SUM_NAME = {"방문": "하루 방문", "매출": "카드 매출", "가게 수(경쟁)": "가게 수", "생존율": "음식점 5년 생존율"}
SUM_LABEL = {"방문": "수요", "매출": "매출", "가게 수(경쟁)": "경쟁", "생존율": "생존"}


def _summary_cells(o, sig, lvl):
    """종합 진단 5칸 요약(문서 23 4절, 사람 시험 H3): 수요·매출·경쟁·생존·앞으로. 칸마다 값 하나와 43곳 중 위치 한 줄."""
    cells = []
    for s in sig["items"]:
        cells.append({"key": s["short"], "label": SUM_LABEL.get(s["short"], s["kind"]), "name": SUM_NAME.get(s["short"], s["name"]),
                      "value": o.num(s["value"], s["unit"]), "level": lvl.get(s["level"], s["level"]), "note": f"{s['of']}곳 중 {s['rank']}위"})
        d = getattr(o, "decomp", None)
        if s["short"] == "매출" and d:  # 매출 = 결제 건수 × 1건당 금액(문서 23: 건수·건당 금액 흐름을 앞에)
            sg = lambda x: f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x)}%"
            cells[-1]["sub"] = f"최근 1년, 그 전 1년보다 결제 건수 {sg(d['cnt_pct'])}, 1건당 금액 {sg(d['ticket_pct'])}"
    tr, fc = getattr(o, "trend", None), getattr(o, "fc", None)
    if tr or fc:
        if tr and tr["sig"]:
            val, lv = f"{'+' if tr['up'] else '−'}{tr['pct']}%", "늘어나는 중" if tr["up"] else "줄어드는 중"
        elif tr:
            val, lv = "변화 확인 안 됨", "보통"
        else:
            val, lv = f"{fc['lo']}~{fc['hi']}", "방문 예상"
        note = "최근 12개월, 작년 같은 달 대비" if tr else f"하루 방문 예상({fc['days']})"
        cell = {"key": "앞으로", "label": "앞으로", "name": "매출 흐름" if tr else "방문 예상", "value": val, "level": lv, "note": note}
        if tr and fc:
            cell["sub"] = f"하루 방문 예상 {fc['lo']}~{fc['hi']}({fc['days']})"
        cells.append(cell)
    return cells


def _summary_conclusion(o, sig, lvl):
    """결론 한 문장에 실제 수치를 넣는다(문서 23 B 기준: 판단을 미루지 않는다). 같은 수준끼리 묶는다."""
    groups = {}
    for s in sig["items"]:
        groups.setdefault(lvl.get(s["level"], s["level"]), []).append(s)
    parts = []
    for lv, items in groups.items():
        if len(items) == 1:
            s = items[0]
            v = o.num(s["value"], s["unit"])
            parts.append(f"{_josa(SUM_NAME.get(s['short'], s['name']))} {v}({s['rank']}위){_ro(v)} {lv}")
        else:
            names = "·".join(SUM_NAME.get(s["short"], s["name"]) for s in items)
            rs = sorted(s["rank"] for s in items)
            r = f"{rs[0]}위" if rs[0] == rs[-1] else f"{rs[0]}~{rs[-1]}위"
            parts.append(f"{_josa(names, '이', '가')} {r}{_ro(r)} {lv}")
    return f"{sig['dong']}: " + "이고, ".join(parts) + "이에요(제주 43개 동네 중)."


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
    diag = t.get("type") == "T10"
    side_r = _side_recipes(rv)
    for e in ev:  # 기존 근거 가운데 표에서 나오지 않는 것(생존율·비슷한 동네 등)
        if diag and e.get("metric") in ("업종 5년생존율", "비슷한 동네"):
            continue  # 종합 진단은 아래 _diagnosis_lines가 곡선·닮은 이유와 함께 쓴다
        if (e.get("metric") == "업종 5년생존율" and "R4" in side_r) or (e.get("metric") == "비슷한 동네" and (t.get("type") == "T9" or "R5" in side_r)):
            continue  # 종합 진단은 아래 _diagnosis_lines가 곡선·닮은 이유와 함께 쓴다
        if e.get("metric") in ("업종 5년생존율", "비슷한 동네", "유형", "거주연령구성", "방문연령구성"):
            if e["metric"] == "비슷한 동네":  # 모델 계산 결과라 비교 층(L2), 출처는 쓴 자료 묶음
                o.line("L2", e["text"] + "(업종 구성·연령·방문·버스가 가까운 순)", "상가·유동인구·버스 자료(Agent 계산)", None, kind="similar")
            else:
                o.line("L1", e["text"], e.get("dataset"), e.get("as_of"), kind="survival" if e["metric"] == "업종 5년생존율" else None)
    if t.get("type") == "T15":
        _anomaly_lines(o, t, store)
    if t.get("type") == "T9":  # 계절 흐름이 닮은 동네(R6의 월별 곡선 거리)
        for v in store.values():
            for d, n in ((v.get("nearest") or {}) if isinstance(v, dict) else {}).items():
                o.numbers += [float(len(n["dongs"])), float(n["peak"]), float(n["low"]), float(n["months"]), 1.0]
                o.line("L4", f"{_josa(d, '과', '와')} 월별 방문 흐름이 가까운 동네는 {', '.join(n['dongs'])}{_cop(n['dongs'][-1])}(가까운 순 {len(n['dongs'])}곳). "
                             f"{_josa(d)} {n['peak']}월에 방문이 가장 많고(한 해 평균의 {o.num(n['peak_ratio'], '배')}) {n['low']}월에 가장 적어요({o.num(n['low_ratio'], '배')}).",
                       "유동인구(월별 하루 평균 방문을 그 동네 한 해 평균으로 나눈 곡선의 거리)", None, tag="Agent 계산", kind="similar")
    if diag:
        if t.get("space"):
            _composite_lines(o, t, t["space"][0])
            bz = v3.biz5_of(t.get("target"))[0]
            o.decomp = _decomp_line(o, t["space"][0], bz, f"{bz} " if bz else "전 업종 ")  # 문서 23: 건수·건당 금액 흐름을 앞에
        _diagnosis_lines(o, t, store)
    else:
        _diagnosis_lines(o, t, store, side_r)
        _deep_lines(o, t, rv)
        if t.get("type") == "T2" and len(t.get("space") or []) == 2 and not t.get("metric") and not t.get("details"):  # 지표를 지정한 비교(예: 버스 이용)는 그 지표로 답한다
            _compare_lines(o, t)
    _judgement_lines(o, t, rv, ev)
    if diag:  # 분석 블록의 줄 순서: 생존 → 방문 예상 → 닮은 동네 → 매출 예상 → 개업·폐업 → 계절 → 비 → 추세(문서 21 3.1절)
        ana = sorted((x for x in o.lines if x["block"] == "analysis"), key=lambda x: DIAG_ORDER.get(x.get("kind"), len(DIAG_ORDER)))
        o.lines = [x for x in o.lines if x["block"] != "analysis"] + ana
        facts = [x for x in o.lines if x["block"] == "facts"]  # 결제 1건당 금액은 매출 줄 바로 뒤(문서 23)
        tk = [x for x in facts if x.get("kind") == "ticket"]
        facts = [x for x in facts if x.get("kind") != "ticket"]
        facts[3:3] = tk
        o.lines = facts + [x for x in o.lines if x["block"] != "facts"]
    else:  # 단순 주제: 주 결과 먼저, 곁가지는 위치 → 분해 → 모델 결과 순서(문서 22)
        ana = sorted((x for x in o.lines if x["block"] == "analysis"), key=lambda x: (bool(x.get("side")), ANA_ORDER.get(x.get("kind"), len(ANA_ORDER)), o.lines.index(x)))
        o.lines = [x for x in o.lines if x["block"] != "analysis"] + ana
    fresh = freshness(o)  # 결론을 고르기 전에 '오래된 자료' 꼬리표를 붙인다
    summary = None
    # 결론: 층이 가장 높은 줄. 가치 판단 질문은 판단 재료 요약
    sig = next((v["extra"] for v in store.values() if isinstance(v, dict) and (v.get("extra") or {}).get("kind") == "signals"), None)
    if (value_q or diag) and sig:
        dong = sig["dong"]
        lvl = {"많음": "많은 편", "적음": "적은 편", "높음": "높은 편", "낮음": "낮은 편", "보통": "보통"}
        summary = _summary_cells(o, sig, lvl)
        conclusion = {"text": _summary_conclusion(o, sig, lvl), "layer": "L5", "tag": GUIDE}
    else:
        rank = {"L4": 4, "L3": 3, "L1": 1, "L2": 0, "L5": 0}
        main = [x for x in o.lines if not x.get("side")] or o.lines  # 곁가지 줄(위치·모델 결과)은 결론으로 고르지 않는다(문서 22)
        cmp_ = next((x for x in main if x.get("kind") == "compare"), None)
        lead = next((x for x in main if x.get("kind") == {"T9": "similar", "T15": "anomaly"}.get(t.get("type"), "survival")), None)
        if t.get("type") == "T4":  # 센터 자료의 흐름 줄이 있으면 그것이 결론(문서 20 A6)
            lead = next((x for x in main if x.get("kind") == "flow"), lead)
        csum = next((x for x in main if x.get("kind") == "compare_sum"), None)
        best = csum if csum else cmp_ if (t.get("type") == "T2" or t.get("details")) and cmp_ else lead if lead else max(main, key=lambda x: (rank[x["layer"]], -o.lines.index(x)), default=None)
        conclusion = {"text": best["text"], "layer": best["layer"], "tag": best["tag"]} if best else {"text": "확인된 결과가 없어요.", "layer": None, "tag": None}
        if best and best.get("source"):  # 결론과 같은 줄은 블록에서 빠지므로 출처를 결론에 붙인다(이중 검토 035)
            conclusion["source"] = nice_source(best["source"])
        if best and best["layer"] == "L1" and getattr(o, "rank_head", None):  # 순위 질문은 1~3위를 결론으로(문서 20 A9)
            conclusion["text"] = o.rank_head
    blocks = []
    for b in ("facts", "analysis", "guide"):
        ls = [x for x in o.lines if x["block"] == b and x["text"] != conclusion["text"]]  # 결론과 같은 줄은 한 번만(이중 검토 035)
        if ls or (b == "guide" and value_q):
            blk = {"id": b, "title": BLOCK_TITLE[b], "lines": ls}
            if b == "guide" and (value_q or sig):
                blk["closing"] = CLOSING
            blocks.append(blk)
    order_ = ["map", "map_sales", "map_visit", "map_stores", "map_survival", "survcurve", "biz_yearly", "yoy3", "rising", "monthly", "yearly", "hour", "bizcompare", "bizgrowth",
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
            "freshness": fresh, "requests": requests(t, store, o.lines), "methods": _methods(o.lines, store), "numbers": o.numbers + POLICY_NUMBERS, "all_lines": [x for x in o.lines],
            **({"compare": o.compare} if getattr(o, "compare", None) else {}), **({"summary": summary} if summary else {}), **({"bep": o.bep} if summary and getattr(o, "bep", None) else {}), **({"gaps": GAPS} if summary else {}), **_biz_notice(t, o.lines)}
