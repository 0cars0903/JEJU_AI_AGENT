"""질문 유도 (사용자 결정 2026-11-11 17:25, docs/기획/06_남은과제.md 1절).

화면의 네 진입로 가운데 ②추천 질문 ③단계별 선택 ④대표 질문은 버튼 값(slots)으로 질문 Tuple을 바로 채운다.
해석(M1)을 거치지 않으므로 해석 오류가 생기지 않는다. ①자유 입력만 M1이 해석한다.

slots 형식: {"topic": 주제 id, "space": [동네], "target": 업종·인구, "variant": 보기 id, "metric": 순위 지표, "keyword": 자료 검색어}
단계별 선택의 첫 단계는 '궁금한 것'(주제)이고, 그 주제에 필요한 칸만 이어서 고른다.
"""
import copy

import qtuple as Q

FOOD = ["음식점", "카페", "한식", "일식", "횟집", "중식", "치킨", "분식", "주점"]  # 개업·폐업·생존은 음식점 인허가(780)만 있음
# 순위 지표: 폐업·생존은 순위를 내지 않는다(docs/조사/06_EDA_H1H3.md 사용자 확정). 고령·청년 비중은 공개 경로 조회 미구현이라 뺐다.
RANK_METRICS = {"점포수": "가게 수", "일평균방문": "일평균 방문", "버스일평균": "버스 일평균 이용"}
KEYWORDS = ["버스", "유동인구", "카드 매출", "날씨", "상가", "와이파이"]

# 주제: id → 이름, 기본 Tuple, 이어서 고를 칸(필수 / 선택), 칸별 선택지, 보기(variant)
TOPICS = [
    {"id": "stores", "label": "가게 수", "base": {"type": "T1", "metric": ["점포수"]},
     "need": ["space"], "optional": ["target"], "options": {"target": Q.TARGETS_BIZ}},
    {"id": "openclose", "label": "가게 개업·폐업", "base": {"type": "T4", "metric": ["개업수", "폐업수"], "time": "최근3년", "target": "음식점"},
     "need": ["space"], "optional": ["target", "variant"], "options": {"target": FOOD},
     "variants": {"flow": {"label": "최근 3년 개업·폐업 흐름"}, "survival": {"label": "5년 생존율", "base": {"type": "T1", "metric": ["5년생존율"], "time": None}}}},
    {"id": "visit", "label": "오가는 사람", "base": {"type": "T1", "metric": ["일평균방문"]}, "need": ["space"]},  # 연령 구성(T5)은 나눔 기준 미구현이라 뺐다
    {"id": "bus", "label": "버스 이용", "base": {"type": "T1", "metric": ["버스일평균"]},
     "need": ["space"], "optional": ["target"], "options": {"target": ["어르신"]}},
    {"id": "rain", "label": "비 오는 날 손님 변화", "base": {"type": "T6", "metric": ["일평균방문"], "cond": ["비"]}, "need": ["space"]},
    {"id": "forecast", "label": "다음 주 방문 예상", "base": {"type": "T8", "metric": ["일평균방문"], "time": "다음주"}, "need": ["space"]},
    {"id": "similar", "label": "비슷한 동네", "base": {"type": "T9"}, "need": ["space"]},
    {"id": "compare", "label": "동네 비교", "base": {"type": "T2"}, "need": ["space"], "min_space": 2},
    {"id": "diagnose", "label": "동네 한눈에 보기", "base": {"type": "T10"}, "need": ["space"]},
    {"id": "rank", "label": "동네 순위", "base": {"type": "T3"}, "need": ["metric"], "options": {"metric": list(RANK_METRICS)}},
    {"id": "catalog", "label": "센터 자료 찾기", "base": {"type": "T11", "metric": ["자료목록"]}, "need": ["keyword"], "options": {"keyword": KEYWORDS}},
]
TOPIC = {x["id"]: x for x in TOPICS}

# ④ 대표 질문: 이용 사례 U1~U6에서 고른 설계 목록(질문 기록을 쌓아 고른 것이 아님)
REPRESENTATIVE = [
    {"use_case": "U1 예비 창업자", "slots": {"topic": "stores", "space": ["노형동"], "target": "카페"}},
    {"use_case": "U1 예비 창업자", "slots": {"topic": "openclose", "space": ["노형동"], "target": "카페"}},
    {"use_case": "U2 소상공인", "slots": {"topic": "rain", "space": ["아라동"]}},
    {"use_case": "U3 생활 도민", "slots": {"topic": "similar", "space": ["노형동"]}},
    {"use_case": "U4 상담 직원", "slots": {"topic": "bus", "space": ["애월읍"], "target": "어르신"}},
    {"use_case": "U5 자료 탐색", "slots": {"topic": "catalog", "keyword": "버스"}},
]


def sentence(slots):
    """버튼 값으로 화면에 보여 줄 질문 문장을 만든다(자료 탐색은 이 문장을 검색어로도 쓴다)."""
    tp = TOPIC[slots["topic"]]
    d = "·".join(slots.get("space") or [])
    tgt = slots.get("target")
    v = slots.get("variant")
    s = {
        "stores": f"{d} {tgt + ' ' if tgt else ''}가게는 몇 곳이야?",
        "openclose": f"{d} {tgt or '음식점'} 5년 생존율은?" if v == "survival" else f"{d} {tgt or '음식점'} 개업·폐업은 최근 3년 어땠어?",
        "visit": f"{d} 하루 평균 방문은?",
        "bus": f"{d} {'어르신 ' if tgt == '어르신' else ''}버스 이용은?",
        "rain": f"비 오는 날 {d} 방문은 얼마나 달라져?",
        "forecast": f"{d} 다음 주 방문 예상은?",
        "similar": f"{d}이랑 비슷한 동네는?",
        "compare": f"{' · '.join(slots.get('space') or [])} 비교해줘",
        "diagnose": f"{d} 한눈에 보여줘",
        "rank": f"{RANK_METRICS.get(slots.get('metric'), '')} 동네 순위는?",
        "catalog": f"센터에 {slots.get('keyword', '')} 자료 있어?",
    }[tp["id"]]
    return " ".join(s.split())


def missing(slots):
    """주제에 꼭 필요한데 아직 고르지 않은 칸 목록."""
    tp = TOPIC.get(slots.get("topic"))
    if tp is None:
        return ["topic"]
    out = [k for k in tp.get("need", []) if not slots.get(k)]
    if "space" not in out and len(slots.get("space") or []) < tp.get("min_space", 1) and "space" in tp.get("need", []):
        out.append("space")
    return out


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
        if tp["id"] == "bus" and slots["target"] == "어르신":
            t["metric"] = ["버스일평균", "경로일평균"]
    if tp["id"] == "rank":
        if slots.get("metric") not in RANK_METRICS:
            raise ValueError(f"고를 수 없는 순위 지표: {slots.get('metric')}")
        t["metric"] = [slots["metric"]]
    t["form"] = Q.DEFAULT_FORM.get(t["type"])
    t["expect"] = "답함"
    return t


TYPE_TOPIC = {"T2": "compare", "T1": "stores", "T4": "openclose", "T5": "visit", "T6": "rain", "T8": "forecast", "T9": "similar", "T10": "diagnose", "T3": "rank", "T11": "catalog"}
METRIC_TOPIC = {"점포수": "stores", "개업수": "openclose", "폐업수": "openclose", "5년생존율": "openclose", "일평균방문": "visit", "버스일평균": "bus", "경로일평균": "bus"}


def to_slots(t):
    """질문 Tuple → 화면이 [바꾸기]에서 미리 골라 둘 버튼 값. 대응하는 주제가 없으면 topic 없이 돌려준다."""
    m = (t.get("metric") or [None])[0]
    topic = TYPE_TOPIC.get(t.get("type"))
    if t.get("type") in ("T1", "T5") and m in METRIC_TOPIC:
        topic = METRIC_TOPIC[m]
    if t.get("type") == "T3":
        topic = "rank"
    out = {"topic": topic, "space": list(t.get("space") or [])}
    tp = TOPIC.get(topic)
    if tp and t.get("target") in tp.get("options", {}).get("target", []):
        out["target"] = t["target"]
    if topic == "openclose" and m == "5년생존율":
        out["variant"] = "survival"
    if topic == "rank" and m in RANK_METRICS:
        out["metric"] = m
    return {k: v for k, v in out.items() if v}


def suggestions(t, n=3):
    """② 추천 질문: 지금 동네·대상과 이어지는 질문 3개(버튼 값 포함, 해석 없이 바로 답함)."""
    d = (t.get("space") or ["노형동"])[:1]
    tgt = t.get("target") if t.get("target") in FOOD else "카페"
    here = to_slots(t).get("topic")
    pool = [{"topic": "openclose", "space": d, "target": tgt}, {"topic": "rain", "space": d}, {"topic": "forecast", "space": d},
            {"topic": "similar", "space": d}, {"topic": "stores", "space": d, "target": tgt}, {"topic": "diagnose", "space": d},
            {"topic": "openclose", "space": d, "target": tgt, "variant": "survival"}]
    out = [s for s in pool if s["topic"] != here][:n]
    return [{"text": sentence(s), "slots": s} for s in out]


def representative():
    return [dict(x, text=sentence(x["slots"])) for x in REPRESENTATIVE]


def catalog_view():
    """화면용 /api/guide 응답: 주제 목록, 칸별 선택지, 대표 질문."""
    topics = []
    for tp in TOPICS:
        topics.append({"id": tp["id"], "label": tp["label"], "need": tp.get("need", []), "optional": tp.get("optional", []), "min_space": tp.get("min_space", 1),
                       "options": {k: [{"value": v, "label": RANK_METRICS.get(v, v)} for v in vs] for k, vs in tp.get("options", {}).items()},
                       "variants": [{"value": k, "label": v["label"]} for k, v in tp.get("variants", {}).items()]})
    return {"topics": topics, "dongs": Q.DONGS, "representative": representative()}
