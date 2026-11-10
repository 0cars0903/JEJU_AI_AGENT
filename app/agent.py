"""동네 생활 진단 Agent: ① 해석 → ② 계획 → ③ 실행 → ④ 검증 → ⑤ 설명.

LLM은 계획(도구 고르기)과 숫자 없는 요약 1~2문장만 맡는다. 계산과 수치 문장은 tools.py의 결정론적 코드가 맡는다.
실제 모델 시험(2026-11-06)에서 숫자는 맞지만 주어가 틀린 답("어르신 일평균 1474명", 실제 전체 값)이 나와 LLM이 숫자를 쓰지 못하게 했다.
로컬 소형 모델(qwen2.5:7b, qwen3:1.7b)은 숫자 금지도 지키지 못해 계획만 맡기고, 요약은 SUMMARY_BACKENDS에서만 켠다.
LLM이 없거나 실패하면 기본 계획과 수치 문장만으로 답한다(규칙 모드). 숫자 대조는 LOTTE check_numbers를 복사해 조였다.
실행: .venv/bin/python app/agent.py "애월읍에 카페가 많은 편이야?" [--backend rule|ollama|claude] [--model 이름] [--json]
"""
import argparse
import datetime
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import tools as tl  # noqa: E402

OUT_OF_SCOPE = [
    (r"내일|모레|다음\s*(주|달|해)|내년|앞으로|예측|될까|오를까|(상권|매출|사업|창업|경기|장사|향후|미래)\s*(의\s*)?전망", "미래 예측", "과거 기록만 요약하므로 앞으로의 값은 답하지 않습니다."),
    (r"매출|수익|순이익|객단가", "매출·수익", "매출·수익 자료가 없어 답하지 못합니다."),
    (r"임대료|월세|권리금|시세|집값", "임대료·시세", "임대료·시세 자료가 없어 답하지 못합니다."),
    (r"시간대|몇\s*시|출근\s*시간|실시간|지금\s*혼잡", "시간대·실시간", "자료가 일 단위라 시간대·실시간 질문은 답하지 못합니다."),
]
SUGGEST = ["동문시장이 있는 일도1동의 음식점 개업·폐업은?", "노형동 생활 진단해 줘", "아라동과 이도2동 비교해 줘"]
ALIAS = {"동문시장": "일도1동", "제주공항": "용담2동", "중문": "중문동", "애월": "애월읍", "한림": "한림읍", "성산": "성산읍", "구좌": "구좌읍", "조천": "조천읍", "표선": "표선면", "남원": "남원읍", "대정": "대정읍", "안덕": "안덕면", "한경": "한경면", "우도": "우도면", "추자": "추자면"}
BIZ_WORDS = ["카페", "커피", "까페", "한식", "일식", "중식", "치킨", "분식", "횟집", "주점", "편의점", "숙박", "호텔", "펜션", "소매", "미용", "약국", "학원", "병원", "식당", "음식점"]
METRICS = [(r"폐업", "폐업률"), (r"생존|오래\s*가", "5년생존율"), (r"숙박|숙소|호텔|펜션", "숙박특화계수"), (r"소매", "소매특화계수"), (r"음식|식당", "음식특화계수"),
           (r"(경로|어르신|노인).*(비중|비율)", "경로비중"), (r"경로|(어르신|노인).*(버스|이용|타는)|버스.*(어르신|노인)", "경로일평균"), (r"고령|60대|어르신|노인", "고령비중"), (r"버스|교통", "버스일평균"), (r"방문|유동", "방문거주비"), (r"근무|직장", "근무거주비"),
           (r"청년|20대|30대", "청년비중"), (r"점포|가게|상권", "점포수")]

PLAN_SYSTEM = """너는 제주 동네 생활 진단 에이전트의 계획 담당이다. 질문에 답하는 데 필요한 도구만 골라 호출하라.
규칙: 글로 답하지 말고 도구만 호출한다. 해석 결과에 있는 동네·업종을 그대로 쓴다. 동네 전반 진단은 dong_profile, 업종·창업은 biz_diagnostic, 인구는 population_mix, 버스는 bus_usage, 동네 비교·순위는 compare_rank."""
EXPLAIN_SYSTEM = """너는 제주 도민에게 동네 자료를 설명한다. 질문에 대한 결론을 1~2문장의 쉬운 한국어로 쓴다. 자세한 수치는 시스템이 따로 붙인다.
규칙: 1) 숫자를 한 글자도 쓰지 않는다(동네 이름의 숫자는 괜찮다). 2) 자료에 있는 사실만 말한다. 원인·관광객·경향 같은 해석을 덧붙이지 않는다.
3) 예측·추천·단정을 하지 않는다. 4) 폐업률·생존율이 "차이 확인 안 됨"이면 높다·낮다고 말하지 않고 "제주 평균과 차이를 확인하지 못했다"고 쓴다. 5) 유동인구는 사람 수가 아니라 지수다."""

# ---------- ④ 숫자 대조(LOTTE agent.py에서 복사) ----------
NUM = re.compile(r"-?\d[\d,]*\.?\d*")
EXCLUDE = re.compile(r"\d{4}-\d{2}|[A-Z]+-\d+|\d{4}\s*년|(?<!\d)(?:0?[1-9]|1[0-2])\s*[~∼–-]\s*(?=(?:0?[1-9]|1[0-2])\s*월)"
                     r"|(?<!\d)(?:0?[1-9]|1[0-2])\s*월|(?<!\d)\d{1,2}\s*개월")
PCT = re.compile(r"(-?\d[\d,]*\.?\d*)\s*%")
KO_NUM = re.compile(r"[일이삼사오육칠팔구십백천만]+(?:점[일이삼사오육칠팔구영공]+)?\s*(?:%|퍼센트|곳|명)")
DONG_NUM = re.compile(r"[가-힣]+\d+동")  # '이도2동'의 2는 수치가 아니다
BANNED = re.compile(r"유망|망할|반드시|확실히|보장|추천합니다|\d+\s*위.{0,12}(폐업|생존)|(폐업|생존).{0,12}\d+\s*위")
SUMMARY_BACKENDS = {"claude"}
ECHO = re.compile(r"요약에|숫자를|문제를 고쳐|다시 써라")  # 재시도 지시문을 그대로 돌려준 답(실제 사례)
PERIOD_WORD = re.compile(r"\d년\s*(폐업|생존)")  # '3년 폐업률'의 3은 지표 이름이다
UNFOUNDED = re.compile(r"관광객|안정적|호황|활발|침체|경향|때문|덕분|것으로 보입니다|아마")  # 도구 결과로 뒷받침되지 않는 해석


def _norm(text):
    return unicodedata.normalize("NFKC", text or "")


def numbers(text):
    text = EXCLUDE.sub(" ", DONG_NUM.sub(" ", _norm(text)))
    out = []
    for s in NUM.findall(text):
        try:
            out.append(float(s.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def check_numbers(answer, tool_results):
    """답의 숫자 중 도구 결과에 없는 것을 돌려준다. 질문의 숫자는 허용하지 않는다."""
    allowed = set()
    for r in tool_results:
        allowed |= {abs(x) for x in numbers(json.dumps(r, ensure_ascii=False))}
    # LOTTE의 '정수 반올림 허용'은 뺐다: 없는 값 "12%"가 11.6의 반올림으로 통과한 사례(2026-11-06)
    bad = [n for n in numbers(answer) if not any(abs(abs(n) - a) < 0.005 or round(a, 1) == abs(n) for a in allowed)]
    return bad + KO_NUM.findall(DONG_NUM.sub(" ", _norm(answer)))


def is_korean(text):
    if re.search(r"[一-鿿]", text):
        return False
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum("가" <= c <= "힣" for c in letters) / len(letters) >= 0.3


def verify_answer(answer, results):
    """최종 답(수치 문장 포함) 검사. 비어 있으면 통과."""
    problems = []
    bad = check_numbers(answer, results)
    if bad:
        problems.append(f"도구 결과에 없는 숫자: {bad}")
    if not is_korean(answer):
        problems.append("한국어 답변이 아님")
    m = BANNED.search(answer)
    if m:
        problems.append(f"쓰지 않는 표현: {m.group(0)}")
    return problems


def _labels(results):
    """도구 결과의 폐업·생존 판정. {'폐업': {판정...}, '생존': {판정...}}"""
    out = {"폐업": set(), "생존": set()}
    for r in results:
        v = r.get("values") or {}
        if v.get("close_label"):
            out["폐업"].add(v["close_label"])
        if v.get("survival_label"):
            out["생존"].add(v["survival_label"])
        if v.get("metric") in ("폐업률", "5년생존율"):
            out["폐업" if v["metric"] == "폐업률" else "생존"] |= {x["label"] for x in v["rows"]}
    return out


def verify_summary(text, results):
    """LLM 요약 검사: 숫자 금지, 근거 없는 해석 금지, 폐업·생존 판정과 어긋난 비교 금지."""
    problems = verify_answer(text, results) if text else ["빈 답변"]
    if re.search(r"\d", DONG_NUM.sub(" ", PERIOD_WORD.sub(r"\1", _norm(text)))):  # 연도도 숫자다('2023년에는 증가' 통과 사례)
        problems.append("요약에 숫자를 썼다")
    if ECHO.search(text):
        problems.append("지시문을 되풀이했다")
    m = UNFOUNDED.search(text)
    if m:
        problems.append(f"근거 없는 해석: {m.group(0)}")
    labels = _labels(results)
    for clause in re.split(r"(?<=[.!?])\s+|\n|지만|으나|는데|,", text):  # 절마다 본다('생존율은 높지만 폐업률은 차이 없음' 오탐 방지)
        for word in ("폐업", "생존"):
            if word not in clause or not labels[word] or "차이" in clause:
                continue
            c = re.sub(r"(높|많|낮|적)지\s*않", " ", clause)  # '높지 않습니다'는 높다는 단언이 아니다
            says_high, says_low = bool(re.search(r"높|많", c)), bool(re.search(r"낮|적", c))
            if (says_high and "제주 평균보다 높음" not in labels[word]) or (says_low and "제주 평균보다 낮음" not in labels[word]):
                problems.append(f"{word} 판정과 어긋난 비교: {clause.strip()}")
    return problems


# ---------- ① 해석 ----------
def _eun(word):
    """받침에 맞는 조사 은/는."""
    c = ord(word[-1]) - 0xAC00
    return word + ("은" if 0 <= c <= 11171 and c % 28 else "는")


def interpret(question):
    q = question.strip()
    for pat, kind, msg in OUT_OF_SCOPE:
        if re.search(pat, q):
            return {"scope": "out", "kind": kind, "reason": msg}
    text = q
    for k, v in ALIAS.items():
        if k in text and v not in text:
            text = text.replace(k, v)
    names = tl.find_places(text)
    dongs, ambiguous, place_notes = [], {}, []
    for n in names:
        r = tl.resolve(n)
        if "dong" in r and r["dong"] != n:
            place_notes.append(f"{_eun(n)} {r['dong']}에 속해 {r['dong']} 전체 값으로 답합니다.")
        if "dong" in r and r["dong"] not in dongs:
            dongs.append(r["dong"])
        elif "candidates" in r:
            ambiguous[n] = r["candidates"]
    category = next((w for w in BIZ_WORDS if w in q), None)
    ut = next((w for w in tl.USER_TYPES if w in q), None)
    return {"scope": "in", "dongs": dongs, "ambiguous": ambiguous, "place_notes": place_notes, "category": category, "user_type": ut, "weather": bool(re.search(r"비\s*(가\s*)?오|강수|날씨|우천", q)), "years": parse_years(q),
            "topic": {"bus": bool(re.search(r"버스|정류|대중교통|교통", q)) or (ut is not None and ut != "일반" and "이용" in q),
                      "pop": bool(re.search(r"유동|방문|거주|근무|인구|고령|청년|연령|오가는|구성", q)),
                      "biz": bool(category) or bool(re.search(r"상권|창업|점포|가게|개업|폐업|생존|장사", q)),
                      "compare": bool(re.search(r"비교|차이", q)) and len(dongs) >= 2,
                      "rank": bool(re.search(r"순위|가장|제일|어디가|어느\s*동네|상위|많은\s*동네", q)) and len(dongs) == 0}}


def parse_years(q, data_end=2024):
    """질문의 기간 → (시작, 끝). 없으면 None. '최근 N년'은 끝난 해(2024) 기준, '작년·올해'는 실제 달력 기준이다.
    범위를 벗어난 해는 자르지 않고 도구가 자료 범위를 안내한다."""
    now = datetime.date.today().year
    rel = {"재작년": now - 2, "작년": now - 1, "지난해": now - 1, "올해": now, "금년": now}
    hit = sorted((q.index(k), v) for k, v in rel.items() if k in q and not (k == "작년" and "재작년" in q))
    if len(hit) >= 2 or (hit and re.search(r"부터|까지|~", q)):  # '작년부터 올해까지', '작년부터'
        ys = [v for _, v in hit]
        return min(ys), max(max(ys), now if "까지" not in q and len(ys) == 1 else max(ys))
    if hit:
        return hit[0][1], hit[0][1]
    m = re.search(r"(20\d)0\s*년대", q)
    if m:
        y = int(m.group(1) + "0")
        return y, min(y + 9, now)
    m = re.search(r"((?:19|20)\d{2})\s*년?\s*(?:~|-|부터|에서)\s*((?:19|20)\d{2})", q)
    if m:  # '2024년에서 2022년'처럼 거꾸로 말해도 된다
        a, b = int(m.group(1)), int(m.group(2))
        return min(a, b), max(a, b)
    m = re.search(r"((?:19|20)\d{2})\s*년", q)
    if m:
        return int(m.group(1)), int(m.group(1))
    m = re.search(r"(?:최근|지난)\s*(\d+)\s*년", q)
    if m:
        return data_end - int(m.group(1)) + 1, data_end
    return None


def default_plan(it, question):
    """LLM이 없거나 계획이 잘못되었을 때 쓰는 기본 계획."""
    t, ds, plan = it["topic"], it["dongs"], []
    yrs = it.get("years")
    if t["rank"] or t["compare"]:
        metric = next((m for pat, m in METRICS if re.search(pat, question)), None)
        if it["category"] and metric not in ("폐업률", "5년생존율", "숙박특화계수", "음식특화계수", "소매특화계수"):
            metric = "업종특화계수" if "특화" in question else "업종점포수"
        if t["compare"] and not metric:
            return [{"name": "dong_profile", "arguments": {"dong": d}} for d in ds]
        if metric:
            args = {"metric": metric}
            if ds:
                args["dongs"] = ds
            if metric in tl.CATEGORY_METRICS:
                args["category"] = it["category"]
            return [{"name": "compare_rank", "arguments": args}]
    one_year = {"year": yrs[1]} if yrs and yrs[0] == yrs[1] else {}
    for d in ds:
        if t["biz"]:
            a = {"dong": d}
            if it["category"]:
                a["category"] = it["category"]
            if yrs:
                a.update(start_year=yrs[0], end_year=yrs[1])
            plan.append({"name": "biz_diagnostic", "arguments": a})
        if t["pop"] or (it["weather"] and not t["bus"]):
            plan.append({"name": "population_mix", "arguments": {"dong": d, "include_weather": it["weather"], **one_year}})
        if t["bus"]:
            a = {"dong": d, "include_weather": it["weather"], **one_year}
            if it["user_type"]:
                a["user_type"] = it["user_type"]
            plan.append({"name": "bus_usage", "arguments": a})
        if not (t["biz"] or t["pop"] or t["bus"] or it["weather"]):
            plan.append({"name": "dong_profile", "arguments": {"dong": d}})
    return plan


def _llm_plan(question, it, model, backend, feedback=None):
    """LLM에게 계획을 묻는다. feedback이 있으면 앞 계획의 문제를 알려 다시 세우게 한다(재계획)."""
    keys = ["dongs", "category", "user_type", "weather", "years"]
    content = f"질문: {question}\n해석 결과: {json.dumps({k: it[k] for k in keys}, ensure_ascii=False)}"
    if feedback:
        content += f"\n앞선 계획: {json.dumps(feedback['plan'], ensure_ascii=False, default=str)}\n문제: {feedback['problems']}\n문제를 고쳐 도구를 다시 호출하라."
    m = llm.chat(model, [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": content}], tl.SCHEMAS, name=backend)["message"]
    plan = []
    for c in m.get("tool_calls") or []:
        a = c["function"].get("arguments") or {}
        plan.append({"name": c["function"]["name"], "arguments": json.loads(a) if isinstance(a, str) else a})
    return plan


PROPS = {x["function"]["name"]: set(x["function"]["parameters"]["properties"]) for x in tl.SCHEMAS}
YEAR_KEYS = ("start_year", "end_year", "start_ym", "end_ym", "year")


def check_plan(plan, it, question):
    """LLM 계획을 점검한다. 돌려주는 값: (유효한 호출, 문제 목록). 문제는 재계획 때 LLM에 그대로 알려 준다."""
    problems, good = [], []
    for p in plan or []:
        if p["name"] not in tl.IMPL:
            problems.append(f"없는 도구: {p['name']}")
            continue
        args = {k: v for k, v in p["arguments"].items() if k in PROPS[p["name"]] and v is not None and not (k == "dong" and not isinstance(v, str))}
        extra = {k for k, v in p["arguments"].items() if v is not None} - set(args)  # year=null 같은 빈 값은 문제가 아니다
        if extra:
            problems.append(f"{p['name']}의 잘못된 인자: {sorted(extra)}")
        for k in YEAR_KEYS:  # 기간은 질문에서 해석한 값만 쓴다(LLM이 없는 기간을 넣지 못하게)
            args.pop(k, None)
        if not re.search(r"상위\s*\d|\d+\s*(곳|개|위)", question):  # 질문에 없는 개수 제한(top=1로 2위 이하가 빠진 사례)
            args.pop("top", None)
        if args.get("category") and args["category"] != it["category"] and args["category"] not in question:  # 실제 사례: 질문에 없는 '카페'를 넣음
            problems.append(f"질문에 없는 업종: {args['category']}")
            args.pop("category")
            if p["name"] == "compare_rank" and args.get("metric") in tl.CATEGORY_METRICS:
                continue
        if p["name"] == "compare_rank" and not (it["topic"]["rank"] or it["topic"]["compare"]):
            problems.append("비교·순위 질문이 아닌데 compare_rank를 골랐음")
            continue
        if p["name"] == "compare_rank" and it["topic"]["compare"] and not any(b["name"] == "compare_rank" for b in default_plan(it, question)):
            problems.append("질문에 비교할 지표가 없으므로 compare_rank 대신 dong_profile을 쓴다")
            continue
        if p["name"] == "compare_rank":
            if args.get("metric") not in tl.RANK_METRICS | tl.NO_RANK:
                problems.append(f"compare_rank의 지표가 잘못됨: {args.get('metric')}")
                continue
            if args["metric"] in tl.CATEGORY_METRICS and not args.get("category") and it["category"]:
                args["category"] = it["category"]
        elif "dong" not in args:
            problems.append(f"{p['name']}에 동네(dong)가 없음")
            continue
        good.append({"name": p["name"], "arguments": args})
    if not good:
        problems.append("유효한 도구 호출이 없음")
    base = default_plan(it, question)
    for b in base:
        if not _same_call(good, b):
            problems.append(f"빠진 호출: {b['name']}({b['arguments'].get('dong') or b['arguments'].get('metric')})")
    want = _metric_conflict(good, base)
    if want:
        problems.append(f"질문의 지표와 다름: {want}를 써야 한다")
    return good, problems


MAX_EXTRA_CALLS = 1  # LLM이 기본 계획 밖에서 더할 수 있는 호출 수(답이 질문을 넘어 길어지는 것을 막는 설계값)
SOFT_METRIC = {"점포수"}  # '상권이 큰'처럼 뜻이 넓은 표현에서 나온 지표. 이때만 LLM 선택을 따른다


def _metric_conflict(plan, base):
    """질문에 지표 단어가 뚜렷한데 LLM이 다른 지표를 고르면 틀린 답이 된다(평가셋 Q15: 숙박 비중 → 버스일평균)."""
    want = next((b["arguments"]["metric"] for b in base if b["name"] == "compare_rank"), None)
    if want is None or want in SOFT_METRIC:
        return None
    got = [g for g in plan if g["name"] == "compare_rank"]
    return want if got and all(g["arguments"]["metric"] != want for g in got) else None


def _same_call(plan, b):
    """같은 호출이 계획에 있는가. compare_rank는 지표를 LLM이 고를 수 있지만, 비교할 동네·업종은 질문과 같아야 한다.
    (dongs를 빠뜨리면 '노형동과 연동 비교'에 제주 전체 순위가 나가던 오류, 이중 검토 008)"""
    if b["name"] == "compare_rank":
        want = set(b["arguments"].get("dongs") or [])
        for g in plan:
            if g["name"] == "compare_rank" and want <= set(g["arguments"].get("dongs") or []) and (not b["arguments"].get("category") or g["arguments"].get("category")):
                return g
        return None
    return next((g for g in plan if g["name"] == b["name"] and g["arguments"].get("dong") == b["arguments"].get("dong")), None)


def merge_plan(good, it, question):
    """점검을 통과한 LLM 호출을 살리고, 해석 결과(업종·유형·날씨·기간)를 맞추고, 끝내 빠진 호출을 코드가 채운다."""
    notes = []
    base = default_plan(it, question)
    want = _metric_conflict(good, base)
    if want:
        good = [g for g in good if g["name"] != "compare_rank"]
        notes.append(f"LLM이 끝내 다른 지표를 골라 질문의 지표({want})로 맞췄다")
    for b in base:
        same = _same_call(good, b)
        if not same:
            if b["name"] == "compare_rank":  # 대상이 빠진 비교 호출은 남기지 않는다
                good = [g for g in good if g["name"] != "compare_rank"]
            good.append(b)
            notes.append(f"끝내 빠진 호출을 코드가 채웠다: {b['name']}({b['arguments'].get('dong') or b['arguments'].get('metric')})")
        elif b["name"] != "compare_rank":
            for k, v in b["arguments"].items():
                if same["arguments"].get(k) != v and v not in (None, False):
                    same["arguments"][k] = v
                    notes.append(f"{b['name']}의 {k}를 해석 결과로 맞췄다")
    seen, out, extra = set(), [], 0
    for g in good:
        key = json.dumps([g["name"], g["arguments"]], ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        if not any(g is _same_call(good, b) for b in base):
            extra += 1
            if extra > MAX_EXTRA_CALLS:
                notes.append(f"질문 범위를 넘는 호출을 뺐다: {g['name']}")
                continue
        out.append(g)
    return out, notes


def plan_with_llm(question, it, model, backend, trace):
    """① 계획 → ② 점검 → ③ 문제가 있으면 문제를 알려 1회 재계획 → ④ 그래도 빠지면 코드가 채운다."""
    raw = _llm_plan(question, it, model, backend)
    good, problems = check_plan(raw, it, question)
    trace.append({"stage": "계획", "source": "LLM", "plan": raw, "problems": problems})
    if problems:
        raw2 = _llm_plan(question, it, model, backend, {"plan": raw, "problems": problems})
        good2, problems2 = check_plan(raw2, it, question)
        trace.append({"stage": "재계획", "source": "LLM", "reason": problems, "plan": raw2, "problems": problems2})
        if len(problems2) <= len(problems) and good2:  # 나아졌을 때만 바꾼다
            good, problems = good2, problems2
    plan, notes = merge_plan(good, it, question)
    trace.append({"stage": "계획 확정", "plan": plan, "notes": notes})
    return plan


# ---------- ③ 실행 ----------
def execute(plan):
    results, calls = [], []
    for p in plan:
        try:
            res = tl.IMPL[p["name"]](**p["arguments"])
        except (TypeError, KeyError, ValueError) as e:
            res = {"error": f"인자 오류: {type(e).__name__} {e}"}
        calls.append({"name": p["name"], "arguments": p["arguments"], "ok": "error" not in res})
        results.append(res)
    return results, calls


def rule_answer(results):
    """수치 문장. 줄을 나누고, 동네가 여럿이면 동네 이름으로 묶는다."""
    ok = [r for r in results if "summary" in r]
    many = len({r["dong"] for r in ok if isinstance(r["dong"], str)}) > 1
    blocks = []
    for r in ok:
        blocks.append((f"[{r['dong']}]\n" if many and isinstance(r["dong"], str) else "") + "\n".join(r["summary"]))
    return "\n".join(blocks)


def _brief(results):
    """요약 단계에 넘길 결과: 숫자 없이 쓰도록 수치 문장과 판정만 준다."""
    return [{"dong": r["dong"], "facts": r["summary"], "badges": r.get("badges")} for r in results if "summary" in r]


def summarize(question, results, model, backend):
    """숫자 없는 요약. 검사 실패 시 1회 다시 쓰고, 그래도 실패하면 요약 없이 수치 문장만 쓴다."""
    log = []
    msgs = [{"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": f"질문: {question}\n자료: {json.dumps(_brief(results), ensure_ascii=False)}"}]
    for attempt in range(2):
        try:
            text = llm.chat(model, msgs, [], name=backend)["message"].get("content", "").strip()
        except Exception as e:  # LLM 장애는 요약 없이 넘어간다
            log.append({"attempt": attempt + 1, "error": type(e).__name__})
            break
        problems = verify_summary(text, results)
        log.append({"attempt": attempt + 1, "text": text, "problems": problems})
        if not problems:
            return text, log
        msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": f"다음 문제를 고쳐 다시 써라: {problems}"}]
    return "", log


def run(question, backend=None, model=None):
    t0 = time.time()
    backend = backend or llm.backend()
    trace = []
    it = interpret(question)
    trace.append({"stage": "해석", "result": it})
    base = {"question": question, "backend": backend, "trace": trace, "limits": [], "sources": [], "periods": [], "tool_results": []}
    if it["scope"] == "out":
        return {**base, "status": "out_of_scope", "answer": f"{it['reason']} 대신 이런 질문은 답할 수 있습니다: " + " / ".join(SUGGEST), "seconds": round(time.time() - t0, 2)}
    if it["ambiguous"]:
        n, c = next(iter(it["ambiguous"].items()))
        return {**base, "status": "clarify", "answer": f"{_eun(n)} 행정동 {', '.join(c)}에 걸쳐 있습니다. 어느 동을 볼까요?", "seconds": round(time.time() - t0, 2)}
    if not it["dongs"] and not it["topic"]["rank"]:
        return {**base, "status": "clarify", "answer": "어느 동네를 볼까요? 행정동이나 리 이름으로 알려 주세요(예: 애월읍, 노형동).", "seconds": round(time.time() - t0, 2)}
    plan = None
    if backend != "rule":
        try:
            plan = plan_with_llm(question, it, model, backend, trace)
        except Exception as e:  # LLM 장애·응답 형식 오류
            trace.append({"stage": "계획", "source": "LLM 실패", "error": type(e).__name__})
    if plan is None:
        plan = default_plan(it, question)
        trace.append({"stage": "계획 확정", "source": "기본 계획", "plan": plan, "notes": []})
    results, calls = execute(plan)
    trace.append({"stage": "실행", "calls": calls})
    failed = [(c, r) for c, r in zip(calls, results) if "error" in r]
    if failed and backend != "rule":  # 실행 결과를 보고 고친다: 실패 내용을 LLM에 돌려줘 1회 다시 호출
        try:
            fb = {"plan": [c for c, _ in failed], "problems": [r["error"] for _, r in failed]}
            good, _ = check_plan(_llm_plan(question, it, model, backend, fb), it, question)
            retry = [g for g in good if g not in plan and any(g["name"] == c["name"] for c, _ in failed)]  # 실패한 도구를 고친 호출만 받는다
            if retry:
                r2, c2 = execute(retry)
                trace.append({"stage": "실행 수정", "reason": fb["problems"], "calls": c2})
                if any("summary" in x for x in r2):  # 고쳐졌으면 앞선 실패는 화면 오류로 남기지 않는다(궤적에는 남음)
                    results = [x for x in results if "error" not in x]
                    calls = [c for c in calls if c["ok"]]
                results, calls = results + r2, calls + c2
        except Exception as e:
            trace.append({"stage": "실행 수정", "error": type(e).__name__})
    ok = [r for r in results if "summary" in r]
    many = len({r["dong"] for r in ok if isinstance(r["dong"], str)}) > 1
    blocks = []
    for r in ok:
        blocks.append((f"[{r['dong']}]\n" if many and isinstance(r["dong"], str) else "") + "\n".join(r["summary"]))
    return "\n".join(blocks)


def _brief(results):
    """요약 단계에 넘길 결과: 숫자 없이 쓰도록 수치 문장과 판정만 준다."""
    return [{"dong": r["dong"], "facts": r["summary"], "badges": r.get("badges")} for r in results if "summary" in r]


def summarize(question, results, model, backend):
    """숫자 없는 요약. 검사 실패 시 1회 다시 쓰고, 그래도 실패하면 요약 없이 수치 문장만 쓴다."""
    log = []
    msgs = [{"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": f"질문: {question}\n자료: {json.dumps(_brief(results), ensure_ascii=False)}"}]
    for attempt in range(2):
        try:
            text = llm.chat(model, msgs, [], name=backend)["message"].get("content", "").strip()
        except Exception as e:  # LLM 장애는 요약 없이 넘어간다
            log.append({"attempt": attempt + 1, "error": type(e).__name__})
            break
        problems = verify_summary(text, results)
        log.append({"attempt": attempt + 1, "text": text, "problems": problems})
        if not problems:
            return text, log
        msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": f"다음 문제를 고쳐 다시 써라: {problems}"}]
    return "", log


def run(question, backend=None, model=None):
    t0 = time.time()
    backend = backend or llm.backend()
    trace = []
    it = interpret(question)
    trace.append({"stage": "해석", "result": it})
    base = {"question": question, "backend": backend, "trace": trace, "limits": [], "sources": [], "periods": [], "tool_results": []}
    if it["scope"] == "out":
        return {**base, "status": "out_of_scope", "answer": f"{it['reason']} 대신 이런 질문은 답할 수 있습니다: " + " / ".join(SUGGEST), "seconds": round(time.time() - t0, 2)}
    if it["ambiguous"]:
        n, c = next(iter(it["ambiguous"].items()))
        return {**base, "status": "clarify", "answer": f"{_eun(n)} 행정동 {', '.join(c)}에 걸쳐 있습니다. 어느 동을 볼까요?", "seconds": round(time.time() - t0, 2)}
    if not it["dongs"] and not it["topic"]["rank"]:
        return {**base, "status": "clarify", "answer": "어느 동네를 볼까요? 행정동이나 리 이름으로 알려 주세요(예: 애월읍, 노형동).", "seconds": round(time.time() - t0, 2)}
    plan = None
    if backend != "rule":
        try:
            plan = plan_with_llm(question, it, model, backend, trace)
        except Exception as e:  # LLM 장애·응답 형식 오류
            trace.append({"stage": "계획", "source": "LLM 실패", "error": type(e).__name__})
    if plan is None:
        plan = default_plan(it, question)
        trace.append({"stage": "계획 확정", "source": "기본 계획", "plan": plan, "notes": []})
    results, calls = execute(plan)
    trace.append({"stage": "실행", "calls": calls})
    failed = [(c, r) for c, r in zip(calls, results) if "error" in r]
    if failed and backend != "rule":  # 실행 결과를 보고 고친다: 실패 내용을 LLM에 돌려줘 1회 다시 호출
        try:
            fb = {"plan": [c for c, _ in failed], "problems": [r["error"] for _, r in failed]}
            good, _ = check_plan(_llm_plan(question, it, model, backend, fb), it, question)
            retry = [g for g in good if g not in plan]
            if retry:
                r2, c2 = execute(retry)
                trace.append({"stage": "실행 수정", "reason": fb["problems"], "calls": c2})
                if any("summary" in x for x in r2):  # 고쳐졌으면 앞선 실패는 화면 오류로 남기지 않는다(궤적에는 남음)
                    results = [x for x in results if "error" not in x]
                    calls = [c for c in calls if c["ok"]]
                results, calls = results + r2, calls + c2
        except Exception as e:
            trace.append({"stage": "실행 수정", "error": type(e).__name__})
    ok = [r for r in results if "summary" in r]
    if not ok:
        err = next((r for r in results if r.get("error")), None)
        msg = "답할 자료를 찾지 못했습니다. 동네와 궁금한 점을 함께 적어 주세요."
        if err:
            msg = err["error"] + ("." if not err["error"].endswith(".") else "")
            if err.get("hint"):
                msg += f" {err['hint']}."
            elif err.get("available"):
                msg += f" 볼 수 있는 값: {', '.join(str(x) for x in err['available'])}."
        return {**base, "status": "no_data", "answer": msg, "tool_results": results, "seconds": round(time.time() - t0, 2)}
    facts = rule_answer(results)
    summary, log = summarize(question, results, model, backend) if backend in SUMMARY_BACKENDS else ("", [])
    how = "llm_summary" if summary else ("rule_fallback" if backend in SUMMARY_BACKENDS else "facts_only")
    answer = "\n".join(x for x in [" ".join(it["place_notes"]), summary, facts] if x)
    final = verify_answer(answer, results + [{"q": it["place_notes"]}])  # 마지막 관문: 수치 문장도 같은 검사를 받는다
    limits = list(dict.fromkeys(x for r in ok for x in r["limits"]))
    trace.append({"stage": "검증", "attempts": log, "final_problems": final})
    trace.append({"stage": "설명", "how": how})
    periods = [{"tool": r["tool"], "dong": r["dong"], "period": r["period"]} for r in ok]
    sources = sorted({s for r in ok for s in r["sources"]})
    base_calls = default_plan(it, question)  # 기본 계획의 호출이 실패했을 때만 사용자에게 알린다. LLM이 더한 호출의 실패는 궤적에만 남긴다
    errors = [r["error"] for c, r in zip(calls, results) if "error" in r and any(b["name"] == c["name"] and b["arguments"] == c["arguments"] for b in base_calls)]
    stages = [t["stage"] for t in trace]
    fills = sum("코드가 채웠다" in n or "맞췄다" in n for t in trace if t["stage"] == "계획 확정" for n in t.get("notes", []))
    process = {"intent": it, "replanned": "재계획" in stages, "exec_fixed": "실행 수정" in stages, "code_fills": fills, "llm_plan": any(t.get("source") == "LLM" for t in trace if t["stage"] == "계획"),
               "tools_ok": sum(1 for r in results if "summary" in r), "numbers_outside": 0 if not final else len(final)}
    return {**base, "process": process, "status": "blocked" if final else "ok", "answer": "검증을 통과하지 못해 답을 보이지 않습니다." if final else answer, "answer_how": how, "summary": summary, "facts": facts, "limits": limits, "periods": periods, "sources": sources,
            "tool_errors": errors, "tool_results": results, "seconds": round(time.time() - t0, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--backend", choices=["rule", "ollama", "claude"])
    ap.add_argument("--model")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = run(a.question, a.backend, a.model)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return
    print(f"[{r['status']} · {r['backend']} · {r['seconds']}초]\n{r['answer']}")
    for t in r["trace"]:
        if t["stage"] in ("계획", "재계획", "계획 확정"):
            print(f"- {t['stage']}:", [(p["name"], p["arguments"]) for p in t.get("plan", [])], t.get("problems", ""), t.get("notes", ""))
        if t["stage"] == "검증":
            print("- 검증:", t["attempts"], t["final_problems"])
    for x in r["limits"]:
        print("  · 한계:", x)
    print("  · 출처:", r["sources"])


if __name__ == "__main__":
    main()
