"""M1 질의 해석 2.1판(A2′, 2026-11-11 07:00). 2판(A2)은 app/qparse_a2.py에 그대로 보관.

2.1판 변경(블라인드 023 집계에서 드러난 구멍, 문항 문장은 보지 않음): ② 범위 밖을 닫힌 세계 규칙으로, ③ 지명 정밀도.

M1 질의 해석 2판(A2): 사전(data/lexicon) 기반, 판단 → 유형 순서, 유형별 필수 칸, 의도 확인 카드.

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
COMMON_NOUNS = {"상가", "해안", "해변", "시내", "항구", "시장", "오름", "대비", "이용", "평소", "주변", "근처", "중앙", "바다", "공원", "학교"}  # 지명과 겹치는 일반 명사
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


BOUNDARY = re.compile(r"^(\s|$|[,.?!]|에서|에|은|는|이|가|을|를|의|과|와|랑|이랑|하고|쪽|근처|주변|일대|부근|까지|부터|도|만)")
ADMIN_SUFFIX = re.compile(r"(동|읍|면|리)$")


TRUSTED = set(json.loads((LEX / "places_trusted.json").read_text(encoding="utf-8"))) if (LEX / "places_trusted.json").exists() else set()


def place_ok(q, k):
    """③ 지명 정밀도(기존 방식 'old'): 행정동·법정동·리 이름과 별칭은 그대로 인정. 그 밖의(정류소에서 나온) 이름은 3글자 이상이고 뒤에 조사·띄어쓰기가 올 때만 인정."""
    if k in Q.DONGS or k in Q.DONG_ALIAS or ADMIN_SUFFIX.search(k) or k in TRUSTED:
        return True
    if len(k) < 3:
        return False
    i = q.find(k)
    return i >= 0 and bool(BOUNDARY.match(q[i + len(k):]))


# ---------- 지명 오해석 수정(2026-11-11, docs/조사/15_지명해석_실험.md) ----------
# 원인: 법정동·리 이름(접미어 없는 2글자 324개 포함)을 경계 검사 없이 인정해 '상대적으로'·'고성장'·'내도 될까'·'대포 집'을 지명으로 읽었다.
STRONG = set(Q.DONGS) | set(Q.DONG_ALIAS)  # 행정동 이름과 주민이 접미어 없이 부르는 별칭
NOT_PLACE_AFTER = re.compile(r"^\s*(될|돼|되|됐|해|했|집|업종|브랜드|기간)")  # ③ 보조: 뒤가 동사·일반어면 지명이 아님
# ① 접미어 없는 짧은 마을 이름 가운데 일상어·상표이거나 도 밖 지명과 표기가 같은 것(Claude 선별, 2026-11-11). 제주에서 흔히 부르는 마을 이름(고산·사계·화순 등)은 넣지 않았다. 이 이름은 '리'·'동'을 붙여야 인정한다.
# 형태소 분석기로 자동 선별을 시험했으나 처음 보는 마을 이름(강정·세화·김녕)도 일반명사로 분류해 쓰지 않았다(15 문서).
SHORT_STOP = set("""상가 대포 회수 상대 동일 하원 가시 대기 대신 사장 시민 자연 체육 국제 공업 평화 남성 연대 연수 세기 신비 향기 소란 부록 전원 양지 하천 화산 수산 인성
어음 조수 감귤 높은 밝은 정든 이도 일도 오도 하도 더럭 하모 신도 상도 일과 인다 아름 으뜸 알밤 장구 문예 반석 화랑 제대 옹기 극락 염통 생이 넋이 원님
삼아 대서 내도 서문 신흥 수원 시흥 안성 보성 영주 광양 삼성 신협 부영 세미 사라 이화 인화 우진 백구 서해 동남 남문 명신 GM LH""".split())
COMPARE = re.compile(r"비교|이랑|랑|하고|[와과]\s|vs|대비|차이|중에|보다|어디가")
PLACE_MODE = "rule"


def _left_ok(q, i):
    return i == 0 or not (("가" <= q[i - 1] <= "힣") or q[i - 1].isalnum())


def place_ok_rule(q, k, i):
    """규칙 방식: ① 짧은 지명 제한 ② 앞뒤 경계 ③ 뒤 문맥."""
    admin = bool(ADMIN_SUFFIX.search(k)) and len(k) >= 3  # 노형동·고내리·애월읍처럼 접미어까지 쓴 이름
    if not _left_ok(q, i):  # ② 단어 중간(서귀포시의 '서귀'처럼 앞뒤가 붙은 경우 포함)
        return False
    if not (k in STRONG or admin) and k in SHORT_STOP:  # ① 일상어와 표기가 같은 짧은 이름은 '리'·'동'을 붙여야 인정
        return False
    rest = q[i + len(k):]
    if not admin and not BOUNDARY.match(rest):  # ② 뒤 경계(접미어까지 쓴 행정 이름은 붙여 써도 인정)
        return False
    if not (k in Q.DONGS or admin) and NOT_PLACE_AFTER.match(rest):  # ③
        return False
    return True


_KIWI = []


def _kiwi():
    if not _KIWI:
        from kiwipiepy import Kiwi  # 실험용(requirements.txt 밖)
        _KIWI.append(Kiwi())
    return _KIWI[0]


def place_ok_kiwi(q, k, i, toks):
    """형태소 방식: 지명이 형태소 하나와 정확히 겹치고, 그 형태소가 고유명사(일반명사는 행정 이름·별칭일 때만)여야 인정."""
    admin = bool(ADMIN_SUFFIX.search(k)) and len(k) >= 3
    for t in toks:
        if t.start == i and t.start + t.len == i + len(k):
            return t.tag == "NNP" or (t.tag == "NNG" and (k in STRONG or admin))
    return admin and _left_ok(q, i)  # 형태소가 더 잘게 나뉜 행정 이름(예: '이도2동')은 앞 경계만 본다


def find_places(q, mode=None):
    mode = mode or PLACE_MODE
    found, strong, amb, used = [], set(), {}, q
    toks = _kiwi().tokenize(q) if mode == "kiwi" else None
    for k in PLACE_KEYS:
        start = 0
        while True:
            i = used.find(k, start)
            if i < 0:
                break
            ok = place_ok(used, k) if mode == "old" else place_ok_rule(used, k, i) if mode == "rule" else place_ok_kiwi(used, k, i, toks)
            if ok:
                v = PLACES[k]
                if "dong" in v:
                    if v["dong"] not in found:
                        found.append(v["dong"])
                    if k in STRONG or (ADMIN_SUFFIX.search(k) and len(k) >= 3):
                        strong.add(v["dong"])
                else:
                    amb[k] = v["candidates"]
                used = used[:i] + " " * len(k) + used[i + len(k):]  # 글자 위치를 유지해 형태소 위치와 맞춘다
                break
            start = i + 1
    if mode != "old" and len(found) >= 2 and strong and not COMPARE.search(q):  # ④ 비교 표현 없이 두 동네가 잡히면 강한 근거만 남긴다
        found = [d for d in found if d in strong]
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
    """띄어쓰기 차이를 무시하고 포함 여부를 본다(예: '몇시' = '몇 시'). 단, 붙여 읽은 일치는 원래 문장의 단어 첫 글자에서
    시작할 때만 인정한다('제주 전체에서 점포'를 붙여 읽은 '서점'처럼 단어 중간에서 시작하는 일치는 버림, 2026-11-11)."""
    if w in q:
        return True
    pos = [i for i, c in enumerate(q) if c != " "]
    s, ws = "".join(q[i] for i in pos), w.replace(" ", "")
    j = s.find(ws)
    while j >= 0:
        i = pos[j]
        if i == 0 or q[i - 1] == " ":
            return True
        j = s.find(ws, j + 1)
    return False


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
    # v3: 카드 매출 계열 지표가 있으면 '손님'만으로 잡힌 방문 인구는 뺀다("관광객 손님 비중"의 손님은 매출 손님)
    CARD = {"매출", "이용건수", "건당금액", "관광객비중", "시간대매출", "외국인매출"}
    if "일평균방문" in t["metric"] and CARD & set(t["metric"]) and not re.search(r"방문|유동인구|오가는|인파|붐비|북적", q):
        t["metric"] = [m for m in t["metric"] if m != "일평균방문"]
    if {"업종비교", "시장추이", "매출성장"} & set(t["metric"]):  # 묶음 지표가 있으면 같이 잡힌 '매출'은 그 안에 들어 있다
        t["metric"] = [m for m in t["metric"] if m != "매출"]
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
    # ② 닫힌 세계: 답할 수 있는 것은 지표 사전·자료 목록으로 정해진다. 동네·업종·지표·유형 신호가 하나도 없으면 범위 밖으로 본다
    if t["_type_default"] and not t["metric"] and not t["target"] and not t["space"] and not amb and not t["cond"]:
        t.update(type="T12", expect="범위밖")
        t["_why"].append("지금 자료(동네·업종·유동인구·버스·날씨·개업·폐업)와 연결되는 내용을 찾지 못함")
        return t
    # ③ 판단: 필수 칸
    if amb and not t["space"]:
        t["expect"] = "되묻기"
        t["_why"].append(f"여러 동네로 읽히는 지명: {', '.join(amb)}")
    elif t["type"] in NEED_DONG and not t["space"] and not {"시장추이", "매출성장"} & set(t["metric"]):  # 시장 추이·뜨는 곳은 제주 전체로 답함
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
    if t["type"] == "T11":
        return {"text": "센터·공개 자료 목록에서 찾아볼게요.", "buttons": ["맞아요", "질문 종류 바꾸기"]}
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
