"""질문 유도 (사용자 결정 2026-11-11 17:25; v3 주제 목록 2026-11-11 23:20, docs/기획/v3_설계.md 2절).

화면의 네 진입로 가운데 ②추천 질문 ③단계별 선택 ④대표 질문은 버튼 값(slots)으로 질문 Tuple을 바로 채운다.
해석(M1)을 거치지 않으므로 해석 오류가 생기지 않는다. ①자유 입력만 M1이 해석한다.

slots 형식: {"topic": 주제 id, "space": [동네], "target": 업종·인구, "variant": 보기 id, "metric": 순위 지표}
단계별 선택의 첫 단계는 '궁금한 것'(주제)이고, 그 주제에 필요한 칸만 이어서 고른다.
"""
import copy
import re

import qtuple as Q

FOOD = ["음식점", "카페", "한식", "일식", "횟집", "중식", "치킨", "분식", "주점"]  # 개업·폐업·생존은 음식점 인허가(780)만 있음
# 순위 지표: 폐업·생존은 순위를 내지 않는다(docs/조사/06_EDA_H1H3.md 사용자 확정). 고령·청년 비중은 공개 경로 조회 미구현이라 뺐다.
RANK_METRICS = {"매출": "카드 매출", "매출성장": "요즘 매출이 많이 는 곳", "관광객비중": "관광객 매출 비중", "점포수": "가게 수", "일평균방문": "일평균 방문"}
# 카드 매출(제주관광공사)은 업종 대분류만 있다. 세부 업종을 고르면 대분류(음식점업 등) 기준으로 답하고 한계에 적는다.
CARD_TARGETS = ["음식점", "카페", "한식", "치킨", "횟집", "숙박", "소매"]

DIAG_TARGETS = FOOD + ["숙박", "소매", "편의점"]  # 종합 진단에서 고를 수 있는 업종(문서 20 A6: 업종을 버리지 않는다)

# 주제: id → 이름, 기본 Tuple, 이어서 고를 칸(필수 / 선택), 칸별 선택지, 보기(variant)
TOPICS = [
    {"id": "stores", "label": "가게 수", "base": {"type": "T1", "metric": ["점포수"]},
     "need": ["space"], "optional": ["target"], "options": {"target": Q.TARGETS_BIZ}},
    {"id": "openclose", "label": "가게 개업·폐업", "base": {"type": "T4", "metric": ["개업수", "폐업수"], "time": "최근3년", "target": "음식점"},
     "need": ["space"], "optional": ["target", "variant"], "options": {"target": FOOD},
     "variants": {"flow": {"label": "최근 3년 개업·폐업 흐름"}, "survival": {"label": "5년 생존율", "base": {"type": "T1", "metric": ["5년생존율"], "time": None}}}},
    {"id": "visit", "label": "오가는 사람", "base": {"type": "T1", "metric": ["일평균방문"]}, "need": ["space"], "optional": ["variant"],
     "variants": {"amount": {"label": "하루 평균 방문"}, "age": {"label": "사는 사람 연령대", "base": {"type": "T5", "metric": ["거주연령구성"]}}}},
    {"id": "sales", "label": "카드 매출", "base": {"type": "T4", "metric": ["매출"], "time": "최근3년"}, "need": ["space"], "optional": ["target", "variant"],
     "options": {"target": CARD_TARGETS},
     "variants": {"trend": {"label": "월 매출 흐름"}, "now": {"label": "최근 월 매출", "base": {"type": "T1", "time": None}},
                  "unit": {"label": "결제 1건당 금액", "base": {"type": "T1", "metric": ["건당금액"], "time": None}}}},
    {"id": "customers", "label": "손님 구성(도민·관광객)", "base": {"type": "T5", "metric": ["관광객비중"]}, "need": ["space"], "optional": ["target"],
     "options": {"target": CARD_TARGETS}},
    {"id": "hourly", "label": "몇 시에 손님이 많은지", "base": {"type": "T13", "metric": ["시간대매출"]}, "need": ["space"], "optional": ["target"],
     "options": {"target": CARD_TARGETS}},
    {"id": "market", "label": "업종 시장 추이", "base": {"type": "T4", "metric": ["시장추이"]}, "need": ["target"], "optional": ["space"],
     "options": {"target": CARD_TARGETS}},
    {"id": "bizcompare", "label": "한 동네 안에서 업종끼리 비교", "base": {"type": "T5", "metric": ["업종비교"]}, "need": ["space"]},
    {"id": "rain", "label": "비 오는 날 오가는 사람 변화", "base": {"type": "T6", "metric": ["일평균방문"], "cond": ["비"]}, "need": ["space"]},
    {"id": "forecast", "label": "예상해 보기", "base": {"type": "T8", "metric": ["일평균방문"], "time": "다음주"}, "need": ["space"], "optional": ["variant", "target"],
     "options": {"target": CARD_TARGETS},
     "variants": {"visit": {"label": "다음 주 방문 예상"}, "sales": {"label": "다음 달 업종 매출 예상", "base": {"metric": ["매출"], "time": "다음달"}},
                  }},
    {"id": "similar", "label": "비슷한 동네 추천받기", "base": {"type": "T9"}, "need": ["space"]},
    {"id": "compare", "label": "동네끼리 비교(2곳 이상)", "base": {"type": "T2"}, "need": ["space"], "min_space": 2, "optional": ["target"], "options": {"target": Q.TARGETS_BIZ}},
    {"id": "diagnose", "label": "상권 종합 진단", "base": {"type": "T10"}, "need": ["space"], "optional": ["target"], "options": {"target": DIAG_TARGETS}},
    {"id": "rank", "label": "동네 순위", "base": {"type": "T3"}, "need": ["metric"], "optional": ["target"], "options": {"metric": list(RANK_METRICS), "target": CARD_TARGETS}},
]
TOPIC = {x["id"]: x for x in TOPICS}

# ④ 대표 질문: 이용 사례 U1~U6에서 고른 설계 목록(질문 기록을 쌓아 고른 것이 아님)
REPRESENTATIVE = [  # v3 사용자 3유형(docs/기획/v3_설계.md 1절)
    {"use_case": "예비창업자", "slots": {"topic": "stores", "space": ["노형동"], "target": "카페"}},
    {"use_case": "예비창업자", "slots": {"topic": "openclose", "space": ["노형동"], "target": "카페", "variant": "survival"}},
    {"use_case": "예비창업자", "slots": {"topic": "sales", "space": ["노형동"], "target": "음식점"}},
    {"use_case": "소상공인", "slots": {"topic": "hourly", "space": ["애월읍"], "target": "음식점"}},
    {"use_case": "소상공인", "slots": {"topic": "customers", "space": ["성산읍"], "target": "숙박"}},
    {"use_case": "소상공인", "slots": {"topic": "rain", "space": ["아라동"]}},
    {"use_case": "중소기업", "slots": {"topic": "rank", "metric": "매출", "target": "숙박"}},
]


def sentence(slots):
    """버튼 값으로 화면에 보여 줄 질문 문장을 만든다(자료 탐색은 이 문장을 검색어로도 쓴다)."""
    tp = TOPIC[slots["topic"]]
    d = "·".join(slots.get("space") or [])
    tgt = slots.get("target")
    det = slots.get("detail") or tgt  # 세부 업종(국수·꽃집 …)은 가게 수를 세는 주제의 문장에만 쓴다
    v = slots.get("variant")
    s = {
        "stores": f"{d} {det + ' ' if det else ''}가게는 몇 곳이야?",
        "openclose": f"{d} {tgt or '음식점'} 5년 생존율은?" if v == "survival" else f"{d} {tgt or '음식점'} 개업·폐업은 최근 3년 어땠어?",
        "hourly": f"{d} {tgt + ' ' if tgt else ''}몇 시에 손님이 많아?",
        "sales": f"{d} {tgt + ' ' if tgt else ''}" + {"unit": "결제 1건당 금액은?", "now": "최근 카드 매출은?"}.get(v, "카드 매출 흐름은?"),
        "customers": f"{d} {tgt + ' ' if tgt else ''}손님 중 관광객 비중은?",
        "visit": f"{d}에 사는 사람 연령대는?" if v == "age" else f"{d} 하루 평균 방문은?",
        "rain": f"비 오는 날 {d} 방문은 얼마나 달라져?",
        "forecast": {"sales": f"{d} {tgt or '음식점'} 다음 달 카드 매출 예상은?"}.get(v, f"{d} 다음 주 방문 예상은?"),
        "market": f"{d + ' ' if d else '제주 '}{tgt or ''} 시장이 커지고 있어?",
        "bizcompare": f"{d}에서 {'·'.join(slots['details'])} 점포 수 비교해줘" if len(slots.get("details") or []) >= 2 else f"{d}에서 업종별 카드 매출 비교해줘",
        "similar": f"{d}이랑 비슷한 동네는?",
        "compare": f"{' · '.join(slots.get('space') or [])} {det + ' ' if det else ''}비교해줘",
        "diagnose": f"{d} {det + ' ' if det else ''}상권 종합 진단해줘",
        "rank": f"{tgt + ' ' if tgt else ''}{RANK_METRICS.get(slots.get('metric'), '')} 동네 순위는?",
    }[tp["id"]]
    return " ".join(s.split())


_SQUASH = re.compile(r"[\s?!.,·~]")


def match_sentence(question):
    """서비스가 만든 문장(추천 질문·대표 질문·공유한 주소의 질문)을 입력 칸에 그대로 다시 넣었을 때 같은 버튼 값을 돌려준다.
    해석기(M1)가 자기 문장을 다르게 읽는 일을 막는다(문서 20 A1). 띄어쓰기·문장부호만 다르면 같은 문장으로 본다. 없으면 None."""
    q = _SQUASH.sub("", question or "")
    if not q:
        return None
    dongs = sorted([d for d in Q.DONGS if d in question], key=question.index)
    for tp in TOPICS:
        opts = tp.get("options", {})
        for sp in ([dongs, []] if dongs else [[]]):
            for v in [None, *tp.get("variants", {})]:
                for tgt in [None, *opts.get("target", [])]:
                    for m in opts.get("metric", [None]):
                        slots = {k: x for k, x in {"topic": tp["id"], "space": sp, "variant": v, "target": tgt, "metric": m}.items() if x}
                        if not missing(slots) and _SQUASH.sub("", sentence(slots)) == q:
                            return slots
    return None


def missing(slots):
    """주제에 꼭 필요한데 아직 고르지 않은 칸 목록."""
    tp = TOPIC.get(slots.get("topic"))
    if tp is None:
        return ["topic"]
    out = [k for k in tp.get("need", []) if not slots.get(k)]
    if "space" not in out and len(slots.get("space") or []) < tp.get("min_space", 1) and "space" in tp.get("need", []):
        out.append("space")
    return out


STEP_MESSAGE = {"topic": "궁금한 것을 골라 주세요.", "space": "동네를 골라 주세요.", "metric": "순위 기준을 골라 주세요."}


def missing_message(slots, step):
    """빠진 칸을 고르라는 안내(자유 입력의 예외 안내와 같은 말투)."""
    if step == "space" and slots.get("topic") == "compare" and slots.get("space"):
        return "비교할 동네를 하나 더 골라 주세요."
    return STEP_MESSAGE.get(step, "이어서 골라 주세요.")


def to_tuple(slots):
    """버튼 값 → 질문 Tuple. 잘못된 값이면 ValueError."""
    tp = TOPIC.get(slots.get("topic"))
    if tp is None:
        raise ValueError(f"알 수 없는 주제: {slots.get('topic')}")
    t = Q.empty()
    t.update(copy.deepcopy(tp["base"]))
    v = slots.get("variant")
    if v:
        if v not in tp.get("variants", {}):
            raise ValueError(f"알 수 없는 보기: {v}")
        t.update(copy.deepcopy(tp["variants"][v].get("base", {})))
    if slots.get("space"):
        bad = [s for s in slots["space"] if s not in Q.DONGS]
        if bad:
            raise ValueError(f"알 수 없는 동네: {', '.join(bad)}")
        t["space"] = list(slots["space"])
    if slots.get("target"):
        if slots["target"] not in tp.get("options", {}).get("target", []):
            raise ValueError(f"이 주제에서 고를 수 없는 대상: {slots['target']}")
        t["target"] = slots["target"]
    if tp["id"] == "bizcompare" and isinstance(slots.get("details"), list):  # 자유 입력에서 읽은 세부 업종 묶음(가게 수로 비교, 문서 20 A9)
        import qparse
        ds = [w for w in slots["details"] if w in qparse.DETAIL or w in qparse.VS_BIZ]
        if len(ds) >= 2:
            t["details"] = ds
    if slots.get("detail"):  # 자유 입력에서 읽은 세부 업종. 주소·'다시 계산'에서도 사라지지 않게 그대로 넘긴다(문서 20 A3·A6)
        import qparse
        if slots["detail"] in qparse.DETAIL:
            t["detail"] = slots["detail"]
            fam = qparse.MAJOR_TARGET.get(qparse.DETAIL[slots["detail"]]["major"])
            if not t.get("target") and fam in tp.get("options", {}).get("target", []):
                t["target"] = fam
    if tp["id"] == "rank":
        if slots.get("metric") not in RANK_METRICS:
            raise ValueError(f"고를 수 없는 순위 지표: {slots.get('metric')}")
        t["metric"] = [slots["metric"]]
    t["form"] = Q.DEFAULT_FORM.get(t["type"])
    t["expect"] = "답함"
    return t


TYPE_TOPIC = {"T13": "hourly", "T2": "compare", "T1": "stores", "T4": "openclose", "T5": "visit", "T6": "rain", "T8": "forecast", "T9": "similar", "T10": "diagnose", "T3": "rank"}
METRIC_TOPIC = {"거주연령구성": "visit", "점포수": "stores", "개업수": "openclose", "폐업수": "openclose", "5년생존율": "openclose", "일평균방문": "visit",
                "매출": "sales", "이용건수": "sales", "건당금액": "sales", "관광객비중": "customers", "시간대매출": "hourly", "시장추이": "market", "업종비교": "bizcompare"}


def to_slots(t):
    """질문 Tuple → 화면이 [바꾸기]에서 미리 골라 둘 버튼 값. 대응하는 주제가 없으면 topic 없이 돌려준다."""
    m = (t.get("metric") or [None])[0]
    topic = TYPE_TOPIC.get(t.get("type"))
    if t.get("type") in ("T1", "T4", "T5") and m in METRIC_TOPIC:
        topic = METRIC_TOPIC[m]
    if t.get("type") == "T6" and m in METRIC_TOPIC and m != "일평균방문":  # '관광객 손님이 줄었어?'를 비 효과로 미리 고르지 않는다(문서 20 A1)
        topic = METRIC_TOPIC[m]
    if t.get("type") == "T3":
        topic = "rank"
    out = {"topic": topic, "space": list(t.get("space") or [])}
    tp = TOPIC.get(topic)
    if tp and t.get("target") in tp.get("options", {}).get("target", []):
        out["target"] = t["target"]
    if topic == "openclose" and m == "5년생존율":
        out["variant"] = "survival"
    if t.get("type") == "T8" and m in ("매출", "과거매출"):
        out["variant"] = "sales"
    if topic == "sales" and m == "건당금액":
        out["variant"] = "unit"
    elif topic == "sales" and t.get("type") == "T1":
        out["variant"] = "now"
    if topic == "visit" and m == "거주연령구성":
        out["variant"] = "age"
    if topic == "rank" and m in RANK_METRICS:
        out["metric"] = m
    if t.get("detail"):
        out["detail"] = t["detail"]
    if t.get("details"):
        out["details"] = list(t["details"])
    return {k: v for k, v in out.items() if v}


def suggestions(t, n=3):
    """② 추천 질문: 지금 동네·대상과 이어지는 질문 3개(버튼 값 포함, 해석 없이 바로 답함)."""
    d = (t.get("space") or ["노형동"])[:1]
    tgt = t.get("target") if t.get("target") in FOOD else "카페"
    here = to_slots(t).get("topic")
    ctgt = t.get("target") if t.get("target") in CARD_TARGETS else "음식점"
    pool = [{"topic": "sales", "space": d, "target": ctgt}, {"topic": "openclose", "space": d, "target": tgt}, {"topic": "customers", "space": d, "target": ctgt},
            {"topic": "hourly", "space": d, "target": ctgt}, {"topic": "stores", "space": d, "target": tgt}, {"topic": "diagnose", "space": d},
            {"topic": "openclose", "space": d, "target": tgt, "variant": "survival"}, {"topic": "rain", "space": d}, {"topic": "similar", "space": d}]
    out = [s for s in pool if s["topic"] != here][:n]
    return [{"text": sentence(s), "slots": s} for s in out]


def representative():
    return [dict(x, text=sentence(x["slots"])) for x in REPRESENTATIVE]


def catalog_view():
    """화면용 /api/guide 응답: 주제 목록, 칸별 선택지, 대표 질문."""
    topics = []
    for tp in TOPICS:
        topics.append({"id": tp["id"], "label": tp["label"], "need": tp.get("need", []), "optional": tp.get("optional", []), "min_space": tp.get("min_space", 1), "center_only": tp.get("center_only", False),
                       "options": {k: [{"value": v, "label": RANK_METRICS.get(v, v)} for v in vs] for k, vs in tp.get("options", {}).items()},
                       "variants": [{"value": k, "label": v["label"]} for k, v in tp.get("variants", {}).items()]})
    return {"topics": topics, "dongs": Q.DONGS, "representative": representative()}
