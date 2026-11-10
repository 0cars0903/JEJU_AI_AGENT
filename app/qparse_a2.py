"""M1 질의 해석 2판(A2): 사전(data/lexicon) 기반, 판단 → 유형 순서, 유형별 필수 칸, 의도 확인 카드.

1판(app/x1_methods.rule_parse)의 오류 분석(2026-11-11, 개발용 021 문항)에서 나온 원인을 고친다.
  ① 단어 목록 밖 표현은 유형 기본값(T1)으로 떨어짐 → 유형 표현 사전 확장 + 신호 점수
  ② 판단(되묻기)이 유형에 매달림 → 판단을 먼저, 유형별 필수 칸 표로 따로
  ③ 지명 사전이 좁음 → 생활 지명 2,828개(lexicon.places)
제주어는 지원하지 않는다(사용자 결정 2026-11-11). 시험 문항(022·023)은 보지 않고 만든다.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

LEX = Q.ROOT / "data" / "lexicon"


def _load(name):
    return json.loads((LEX / f"{name}.json").read_text(encoding="utf-8"))


PLACES = _load("places")
BIZ = _load("biz")
METRIC_W = _load("metrics")
POP_W = _load("population")
COND_W = _load("conditions")
TIME_W = _load("time")
INTENT_W = _load("intent")
OUT_W = _load("out_of_scope")
COMMON_NOUNS = {"해안", "해변", "시내", "항구", "시장", "오름", "대비", "이용", "평소", "주변", "근처", "중앙", "바다", "공원", "학교"}  # 지명과 겹치는 일반 명사
PLACE_KEYS = sorted((k for k in PLACES if k not in COMMON_NOUNS), key=len, reverse=True)
BIZ_KEYS = sorted([(w, g) for g, ws in BIZ["colloquial"].items() for w in ws] + [(c, (v.get("rest_group") or c)) for c, v in BIZ["categories"].items() if len(c) >= 2],
                  key=lambda x: -len(x[0]))
FOOD_ONLY = {"개업수", "폐업수", "폐업률", "5년생존율", "조건부생존"}  # 780 음식점에서만 계산되는 지표
FOOD_GROUPS = {"카페", "한식", "일식", "횟집", "중식", "치킨", "분식", "주점", "편의점", "음식점", "기타"}
# 유형별 필수 칸: 동네가 있어야 답하는 유형(그 밖은 동네 없이 제주 전체·동네 전체로 답함)
NEED_DONG = {"T1", "T4", "T5", "T6", "T8", "T9", "T10", "T13"}
NEED_TWO = {"T2"}


def norm(q):
    return re.sub(r"\s+", " ", q.strip())


def find_places(q):
    found, amb, used = [], {}, q
    for k in PLACE_KEYS:
        if k in used:
            v = PLACES[k]
            if "dong" in v:
                if v["dong"] not in found:
                    found.append(v["dong"])
            else:
                amb[k] = v["candidates"]
            used = used.replace(k, " ")
    return found, amb


def find_targets(q):
    """업종과 인구 집단을 모두 찾는다(Fable 일치도 분석: 둘이 함께 드는 질문이 있음). 첫째가 대표 대상."""
    out = []
    for w, g in BIZ_KEYS:
        if has(q, w):
            out.append(g)
            break
    for p, ws in POP_W.items():
        if any(has(q, w) for w in ws):
            out.append(p)
            break
    return out


def find_target(q):
    ts = find_targets(q)
    return ts[0] if ts else None


def has(q, w):
    """띄어쓰기 차이를 무시하고 포함 여부를 본다(예: '몇시' = '몇 시')."""
    return w in q or w.replace(" ", "") in q.replace(" ", "")


def hits(q, table):
    return [k for k, ws in table.items() if any(has(q, w) for w in ws)]


WEIGHT = {"T7": 2, "T9": 2, "T11": 3, "T13": 2, "T14": 2, "T15": 2}  # 표현이 그 유형에만 쓰이는 정도(구별력)
EXTRA_INTENT = {"T11": ["자료가 있", "데이터가 있", "데이터셋", "원천 자료", "자료를 제공", "데이터를 제공"], "T13": ["붐비는 시간", "몇시", "몇 시쯤", "시간이 언제"],
                "T14": ["동시에", "이면서", "들면서", "면서 동시에"], "T9": ["유사", "비슷"]}
for _k, _ws in EXTRA_INTENT.items():
    INTENT_W.setdefault(_k, [])
    INTENT_W[_k] = list(dict.fromkeys(INTENT_W[_k] + _ws))


def type_scores(q, t):
    sc = {k: sum(WEIGHT.get(k, 1) for w in ws if has(q, w)) for k, ws in INTENT_W.items()}
    # 구조 신호
    if len(t["space"]) >= 2:
        sc["T2"] = sc.get("T2", 0) + 1.5
    if not t["space"] and re.search(r"(가장|제일|어디가|어느 동네|어떤 동네가).*(많|높|적|낮)", q):
        sc["T3"] = sc.get("T3", 0) + 2
    if t["cond"] and not sc.get("T8"):
        sc["T6"] = sc.get("T6", 0) + 1.5
    if "시간대방문" in t["metric"] or "시간대" in q:
        sc["T13"] = sc.get("T13", 0) + 1.5
    if "자료목록" in t["metric"]:
        sc["T11"] = sc.get("T11", 0) + 2
    if (len(t["metric"]) >= 2 or "상위" in q or "하위" in q) and not t["space"] and re.search(r"(높고|낮고|많고|적고|이면서|면서|동시에)", q):
        sc["T14"] = sc.get("T14", 0) + 3  # 조건 두 개 이상을 함께 거는 탐색은 순위(T3)보다 앞선다
    if len(t["metric"]) >= 2 and re.search(r"(일수록|할수록|관계|상관|연관|도 (많|높|낮|적))", q):
        sc["T7"] = sc.get("T7", 0) + 2
    return {k: v for k, v in sc.items() if v > 0}


def parse(q):
    q = norm(q)
    t = Q.empty()
    t["space"], amb = find_places(q)
    ts = find_targets(q)
    t["target"] = ts[0] if ts else None
    t["_targets"] = ts
    t["metric"] = hits(q, METRIC_W)[:3]
    t["cond"] = [c for c in hits(q, COND_W) if c in Q.CONDS][:2]
    tm = hits(q, TIME_W)
    t["time"] = next((x for x in tm if x in Q.TIMES), None)
    t["_amb"] = amb
    t["_why"] = []
    # ① 판단: 범위 밖 주제 먼저
    out = hits(q, OUT_W)
    if out:
        t.update(type="T12", expect="범위밖")
        t["_why"].append(f"자료가 없는 주제: {', '.join(out)}")
        return t
    if t["target"] and t["target"] not in FOOD_GROUPS and t["target"] not in Q.TARGETS_POP and any(m in FOOD_ONLY for m in t["metric"]):
        t.update(type="T12", expect="범위밖")
        t["_why"].append(f"{t['target']}은 개업·폐업·생존 자료(음식점 인허가)에 없음")
        return t
    # ② 유형
    sc = type_scores(q, t)
    t["type"] = max(sc, key=sc.get) if sc else "T1"
    t["_type_default"] = not sc
    if t["type"] == "T3" and t["space"]:
        t["type"] = "T1"
    if t["type"] in ("T8",) and not t["time"]:
        t["time"] = "다음달" if "달" in q else "다음분기" if "분기" in q else "다음주" if "주" in q else None
    if "시간대" in q or "몇 시" in q:
        t["breakdown"] = "시간대"
    elif re.search(r"나이|연령", q):
        t["breakdown"] = "연령대"
    if not t["target"] and any(m in FOOD_ONLY for m in t["metric"]):
        t["target"] = "음식점"  # 개업·폐업·생존 지표는 음식점 인허가 자료라 대상이 음식점으로 정해진다
    vague = not t["metric"] and not t["target"] and t["_type_default"]
    # ③ 판단: 필수 칸
    if amb and not t["space"]:
        t["expect"] = "되묻기"
        t["_why"].append(f"여러 동네로 읽히는 지명: {', '.join(amb)}")
    elif t["type"] in NEED_DONG and not t["space"]:
        t["expect"] = "되묻기"
        t["_why"].append("동네가 필요함")
    elif vague:
        t["expect"] = "되묻기"
        t["_why"].append("무엇을 알고 싶은지(손님 흐름·개업·폐업·버스 등)가 빠짐")
    elif re.search(r"(창업|장사를?\s*(새로\s*)?시작|차리려|열려고)", q) and any(m in FOOD_ONLY for m in t["metric"]) and t["target"] == "음식점" and not ts:
        t["expect"] = "되묻기"
        t["_why"].append("어떤 업종인지가 빠짐")
    elif t["type"] in NEED_TWO and len(t["space"]) < 2:
        t["expect"] = "되묻기"
        t["_why"].append("비교할 동네 두 곳이 필요함")
    return t


TYPE_KO = Q.TYPES


def card(t):
    """의도 확인 카드 문장(사용자 승인 2026-11-11). 화면은 이 문장과 칸별 수정 버튼을 보여 준다."""
    if t["expect"] == "범위밖":
        return {"text": "이 질문은 지금 자료로 답할 수 없어요. " + "; ".join(t.get("_why", [])), "buttons": ["다른 질문 예시 보기"]}
    parts = []
    if t["space"]:
        parts.append("·".join(t["space"]))
    if t["target"]:
        parts.append(t["target"])
    if t["metric"]:
        parts.append("·".join(Q.METRICS.get(m, m) for m in t["metric"]))
    if t["cond"]:
        parts.append("조건 " + "·".join(t["cond"]))
    if t["time"]:
        parts.append(t["time"])
    body = " · ".join(parts) if parts else "(대상 미정)"
    text = f"이렇게 이해했어요: {body} — {TYPE_KO.get(t['type'], t['type'])}"
    buttons = ["맞아요", "동네 바꾸기", "업종 바꾸기", "질문 종류 바꾸기"]
    if t["expect"] == "되묻기":
        text += ". " + "; ".join(t.get("_why", [])) + "."
        buttons = ([f"{c}" for cands in t.get("_amb", {}).values() for c in cands][:4]) or ["동네 고르기"]
    return {"text": text, "buttons": buttons}


if __name__ == "__main__":
    for q in sys.argv[1:]:
        t = parse(q)
        print(json.dumps({k: v for k, v in t.items() if not k.startswith("_")}, ensure_ascii=False), "|", card(t)["text"])
