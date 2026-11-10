"""실험 X1 비교군: 질문 → 질문 Tuple.

A    rule_parse      : 별칭 사전 + 정규식 규칙
A+B  bank_parse      : 질문 은행(학습 자료와 같은 질문)에서 TF-IDF 글자 n-gram으로 가장 가까운 질문의 type·metric·expect를 가져오고,
                       동네·업종 같은 값 칸은 규칙으로 채운다
A+L  llm_fill_parse  : 규칙 결과에서 규칙이 정하지 못한 칸(type 기본값, 빈 metric·target·space)만 LLM 값으로 채운다
L    llm_parse       : LLM이 Tuple 전체를 낸다(A+L·A+L-ft의 원재료, 형식 오류율 측정용)
C    plan_parse      : 현재 Agent(agent.py)의 해석·계획 결과를 Tuple로 옮긴다(기존 시스템 기준선)
Ollama는 11/12~13 GPU 공유 때문에 CPU 모드(num_gpu 0)로 부른다(05 문서 11-1절).
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

OUT_PAT = r"임대료|월세|권리금|시세|집값|아파트\s*값|실시간|로또|주식"  # 시험 문항을 본 뒤 넣었던 단어(CCTV·주차장·세금·소득·개인 정보·매출 장부)는 유출이라 뺐다(2026-11-11)
OUT_BIZ = ["미용실", "미용", "헤어", "네일", "약국", "학원", "병원", "부동산", "세탁", "PC방", "피시방"]
DONG_KEYS = sorted(set(Q.DONGS) | set(Q.DONG_ALIAS), key=len, reverse=True)
BIZ_KEYS = sorted(((w, b) for b, ws in Q.BIZ_ALIAS.items() for w in ws), key=lambda x: -len(x[0]))
POP_KEYS = sorted(((w, p) for p, ws in Q.POP_ALIAS.items() for w in ws), key=lambda x: -len(x[0]))
METRIC_RULES = [(r"폐업률|문\s*닫는\s*비율", "폐업률"), (r"생존|오래\s*(가|버티)|살아남", "5년생존율"), (r"폐업|문\s*닫", "폐업수"), (r"개업|새로\s*(생|문\s*연)|오픈", "개업수"),
                (r"(경로|어르신|노인).*(버스|타)|버스.*(어르신|노인|경로)", "경로일평균"), (r"버스|정류|대중교통", "버스일평균"), (r"고령|60대|어르신|노인", "고령비중"),
                (r"청년|2030|젊은", "청년비중"), (r"나이|연령", "거주연령구성"), (r"유동|방문|오가는|사람\s*(많|몰)|붐비", "일평균방문"), (r"매출|카드", "매출"),
                (r"몇\s*(곳|개|군데)|점포|가게\s*수|매장", "점포수"), (r"많은\s*편|비중|특화", "특화계수"), (r"자료|데이터", "자료목록")]
TYPE_RULES = [("T11", r"(자료|데이터|데이터셋).*(있|찾|제공|기간)|센터에.*있"), ("T15", r"급증|급감|갑자기|확\s*(늘|줄)|이례"),
              ("T13", r"몇\s*시|시간대|붐비는\s*시간|피크"), ("T14", r"(높고|많고|낮고|적고).*(동네|곳).*(찾|추천|골라|알려)|조건.*동네"),
              ("T8", r"다음\s*(분기|달|해)|내년|될까|예상|전망"), ("T9", r"비슷한|닮은|유형|같은\s*부류"), ("T7", r"(많은|높은)\s*동네(가|는).*(도|일수록)|관계|상관"),
              ("T10", r"진단|전반|종합|리포트|어떤\s*동네"), ("T2", r"비교|vs|랑.*중에|하고.*중에|와.*중에|어디가\s*더"), ("T3", r"순위|가장|제일|top|TOP|상위"),
              ("T6", r"비\s*(가\s*)?오|우천|장마|주말|평일|여름|겨울|성수기|비수기|바람|태풍|날씨"), ("T4", r"줄고|늘고|늘었|줄었|변했|변화|추이|최근\s*\d+\s*년|몇\s*년\s*동안"),
              ("T5", r"구성|비율|나이대|연령대|비중")]
NEED_DONG = {"T1", "T2", "T4", "T5", "T6", "T8", "T9", "T10", "T13"}


def find_dongs(q):
    out, used = [], q
    for k in DONG_KEYS:
        if k in used:
            d = k if k in Q.DONGS else Q.DONG_ALIAS[k]
            if d not in out:
                out.append(d)
            used = used.replace(k, " ")
    return out


def find_target(q):
    for w, b in BIZ_KEYS:
        if w in q:
            return b
    for w, p in POP_KEYS:
        if w in q:
            return p
    return None


def rule_parse(q):
    t = Q.empty()
    t["_type_default"] = False
    if re.search(OUT_PAT, q) or any(w in q for w in OUT_BIZ):
        t.update(type="T12", expect="범위밖", space=find_dongs(q), target=next((w for w in OUT_BIZ if w in q), find_target(q)))
        return t
    t["space"] = find_dongs(q)
    t["target"] = find_target(q)
    t["metric"] = list(dict.fromkeys(m for p, m in METRIC_RULES if re.search(p, q)))[:2]
    t["cond"] = [c for c, ws in Q.COND_ALIAS.items() if any(w.split()[0] in q for w in ws)][:2]
    typ = next((ty for ty, p in TYPE_RULES if re.search(p, q)), None)
    if typ == "T3" and t["space"]:
        typ = "T1"  # 동네를 지정한 '가장'은 순위가 아니라 현황
    if typ == "T2" and len(t["space"]) < 2 and not re.search(r"비교", q):
        typ = None
    if typ is None:
        typ, t["_type_default"] = "T1", True
    t["type"] = typ
    if re.search(r"시간대|몇\s*시", q):
        t["breakdown"] = "시간대"
    elif re.search(r"나이|연령", q):
        t["breakdown"] = "연령대"
    if typ in NEED_DONG and not t["space"]:
        t["expect"] = "되묻기"
    if typ == "T2" and len(t["space"]) < 2:
        t["expect"] = "되묻기"
    return t


class Bank:
    def __init__(self, path=Q.ROOT / "data" / "x1" / "bank.jsonl"):
        from sklearn.feature_extraction.text import TfidfVectorizer
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.tuples = [r["tuple"] for r in rows]
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.X = self.vec.fit_transform([r["q"] for r in rows])

    def parse(self, q):
        sim = (self.X @ self.vec.transform([q]).T).toarray().ravel()
        nb = dict(self.tuples[int(sim.argmax())])
        r = rule_parse(q)
        t = Q.empty()
        t.update(type=nb["type"], metric=nb["metric"], expect=nb["expect"], time=nb["time"], breakdown=nb["breakdown"], form=nb.get("form"))
        t["space"], t["target"], t["cond"] = r["space"], r["target"] or nb["target"], r["cond"]
        if r["expect"] == "범위밖":  # 범위 밖 규칙은 검색보다 앞선다
            t.update(type="T12", expect="범위밖")
        elif t["type"] in NEED_DONG and not t["space"]:
            t["expect"] = "되묻기"
        t["_sim"] = round(float(sim.max()), 3)
        return t


FEWSHOT_QS = ["애월읍 카페 몇 곳 있어?", "비 오는 날 아라동 버스 이용은 어때?", "노형동이랑 연동 비교해줘", "청년 비중 높은 동네 순위 알려줘",
              "우리 동네 치킨집 어때?", "이도2동 상가 임대료 얼마야?"]


def fewshot_msgs():
    """학습 자료와 같은 생성기로 만든 예시 6개(시험 문항과 무관). L-fs 비교군용."""
    import x1_methods as _m  # noqa: F401
    out = []
    for q in FEWSHOT_QS:
        t = rule_parse(q)
        t = {k: v for k, v in t.items() if not k.startswith("_")}
        out += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(t, ensure_ascii=False)}]
    return out


def ollama_json(q, model, cpu=True, timeout=180, fewshot=False):
    msgs = [{"role": "system", "content": Q.SCHEMA_PROMPT}] + (fewshot_msgs() if fewshot else []) + [{"role": "user", "content": q}]
    body = {"model": model, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "num_predict": 300, **({"num_gpu": 0} if cpu else {})}, "messages": msgs}
    t0 = time.time()
    try:  # 출력이 끝나지 않는 경우(CPU 모드 실측 사례)는 JSON 실패로 센다
        r = requests.post("http://localhost:11434/api/chat", json=body, timeout=timeout)
        text = r.json().get("message", {}).get("content", "")
    except (requests.RequestException, ValueError):
        return {}, False, time.time() - t0
    try:
        out = json.loads(text)
        ok = isinstance(out, dict)
    except ValueError:
        out, ok = {}, False
    return (out if ok else {}), ok, time.time() - t0


def coerce(o):
    """LLM 출력 → 질문 Tuple. 목록 밖 값은 버린다(검수의 해석 오류와 같은 규칙)."""
    t = Q.empty()
    if not isinstance(o, dict):
        return t
    t["type"] = o.get("type") if isinstance(o.get("type"), str) and o.get("type") in Q.TYPES else None
    as_list = lambda v: [x for x in (v if isinstance(v, list) else ([v] if v else [])) if isinstance(x, (str, int, float))]  # noqa: E731  LLM이 dict 등을 넣으면 버린다
    t["metric"] = [m for m in as_list(o.get("metric")) if m in Q.METRICS]
    sp = []
    for s in as_list(o.get("space")):
        s = str(s)
        d = s if s in Q.DONGS else Q.DONG_ALIAS.get(s) or Q.DONG_ALIAS.get(s.rstrip("동읍면"))
        if d and d not in sp:
            sp.append(d)
    t["space"] = sp
    tg = o.get("target") if isinstance(o.get("target"), str) else None
    t["target"] = tg if tg in [*Q.TARGETS_BIZ, *Q.TARGETS_POP, *Q.TARGETS_OUT] else None
    sv = lambda k, pool: o.get(k) if isinstance(o.get(k), str) and o.get(k) in pool else None  # noqa: E731
    t["time"] = sv("time", Q.TIMES)
    t["breakdown"] = sv("breakdown", Q.BREAKDOWNS)
    t["cond"] = [c for c in as_list(o.get("cond")) if c in Q.CONDS]
    t["expect"] = sv("expect", Q.EXPECTS) or "답함"
    return t


def llm_parse(q, model, cpu=True, fewshot=False):
    o, ok, dt = ollama_json(q, model, cpu, fewshot=fewshot)
    t = coerce(o)
    t["_json_ok"], t["_sec"] = ok, round(dt, 2)
    return t


def llm_fill_parse(q, model, cpu=True, fewshot=False):
    r = rule_parse(q)
    if r["expect"] == "범위밖":
        r["_json_ok"], r["_sec"] = True, 0.0
        return r
    l = llm_parse(q, model, cpu, fewshot)
    if r["_type_default"] and l["type"]:
        r["type"] = l["type"]
    for k in ["metric", "space", "cond"]:
        if not r[k] and l[k]:
            r[k] = l[k]
    if not r["target"] and l["target"]:
        r["target"] = l["target"]
    if r["expect"] == "되묻기" and r["space"] or r["type"] == "T2" and len(r["space"]) >= 2:
        r["expect"] = "답함"
    if l["expect"] == "범위밖":
        r["expect"], r["type"] = "범위밖", "T12"
    r["_json_ok"], r["_sec"] = l["_json_ok"], l["_sec"]
    return r


TOOL_TYPE = {"dong_profile": "T10", "compare_rank": "T3", "biz_diagnostic": "T1", "population_mix": "T5", "bus_usage": "T1"}


def plan_parse(q, backend="rule", model=None):
    """현재 Agent의 해석·기본 계획을 Tuple로 옮긴다. backend='rule'이면 LLM 없이 기존 규칙 경로."""
    import agent
    it = agent.interpret(q)
    t = Q.empty()
    if it["scope"] == "out":
        t.update(type="T12", expect="범위밖")
        return t
    t["space"], t["target"] = it["dongs"], it.get("category")
    t["target"] = next((b for w, b in BIZ_KEYS if t["target"] and w == t["target"]), t["target"])
    if t["target"] not in [*Q.TARGETS_BIZ, *Q.TARGETS_POP]:
        t["target"] = None
    plan = agent.default_plan(it, q) if backend == "rule" else agent._llm_plan(q, it, model, backend)
    names = [p["name"] for p in plan]
    if not names:
        t["expect"] = "되묻기" if not it["dongs"] else "답함"
        t["type"] = "T1"
        return t
    typ = TOOL_TYPE.get(names[0], "T1")
    if names[0] == "dong_profile" and len(it["dongs"]) >= 2:
        typ = "T2"
    if it["weather"]:
        typ = "T6"
    t["type"] = typ
    return t



# ---------- B2: 구조화 출력(JSON 스키마로 칸 이름과 허용 값을 강제, 2026-11-11) ----------
def tuple_schema():
    return {"type": "object", "properties": {
        "type": {"type": "string", "enum": list(Q.TYPES)},
        "expect": {"type": "string", "enum": Q.EXPECTS},
        "metric": {"type": "array", "items": {"type": "string", "enum": list(Q.METRICS)}, "maxItems": 3},
        "cond": {"type": "array", "items": {"type": "string", "enum": Q.CONDS}, "maxItems": 2},
        "time": {"type": ["string", "null"], "enum": Q.TIMES + [None]},
        "breakdown": {"type": ["string", "null"], "enum": Q.BREAKDOWNS + [None]}},
        "required": ["type", "expect", "metric"]}


SCHEMA_GUIDE = ("질문을 분류하라. type: T1 현황(한 동네 값), T2 비교(동네 둘 이상), T3 순위(동네 전체 줄 세우기), T4 추이(늘었나 줄었나), T5 구성(비율·연령대), "
                "T6 조건 효과(비·주말 등 조건에 따라), T7 관계(두 지표의 상관), T8 예상(앞으로), T9 유형·유사(비슷한 동네), T10 종합 진단, T11 자료 탐색(이런 데이터 있나), "
                "T12 범위 밖, T13 시간대 패턴(몇 시), T14 조건 탐색(조건 여러 개로 동네 찾기), T15 급변(갑자기 늘거나 줄어든 곳). "
                "expect: 답함 / 되묻기(동네·업종·알고 싶은 것이 빠져 답을 정할 수 없음) / 범위밖(임대료·시세·실시간·개인정보·투자 등 동네 통계 자료로 답할 수 없음). JSON만 출력.")


def schema_parse(q, model="qwen3:1.7b", cpu=True, timeout=180):
    """B2: LLM은 유형·판단·지표·조건만 고른다(허용 값 강제). 동네·업종은 사전(qparse)으로 채운다."""
    import qparse
    base = qparse.parse(q)
    body = {"model": model, "stream": False, "think": False, "format": tuple_schema(),
            "options": {"temperature": 0, "num_predict": 200, **({"num_gpu": 0} if cpu else {})},
            "messages": [{"role": "system", "content": SCHEMA_GUIDE}, {"role": "user", "content": q}]}
    t0 = time.time()
    try:
        r = requests.post("http://localhost:11434/api/chat", json=body, timeout=timeout)
        o = json.loads(r.json().get("message", {}).get("content", ""))
        ok = isinstance(o, dict)
    except (requests.RequestException, ValueError):
        o, ok = {}, False
    t = dict(base)
    if ok:
        t["type"] = o.get("type", base["type"])
        t["expect"] = o.get("expect", base["expect"])
        t["metric"] = o.get("metric") or base["metric"]
        t["cond"] = o.get("cond") or base["cond"]
        if base["expect"] == "되묻기" and t["expect"] == "답함" and base["_amb"]:
            t["expect"] = "되묻기"  # 모호한 지명은 사전 판단을 따른다
    t["_json_ok"], t["_sec"] = ok, round(time.time() - t0, 2)
    return t
