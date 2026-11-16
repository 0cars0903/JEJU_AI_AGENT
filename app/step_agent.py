"""단계형 Agent 루프(2026-11-16 마스터 지시: 소형 모델 자율 루프의 실패 유형 7개를 고친다).

조정용 047 Agent 문항 30개로 지금 도구 루프(expert.ask)를 돌려 본 실패 유형(30문항 중, 겹침 포함):
  ① 첫 단계만 하고 답을 냄 26 ② 일반 질문을 통계 기법으로 대신 12 ③ 목록 밖 인자(업종·지명·기법 이름) 11
  ④ 오류 뒤 같은 잘못 반복·정보 버림 6 ⑤ 앞 결과를 쓰는 단계 못 함 5 ⑥ 여러 단계를 한 호출에 몰아넣음 4
  ⑦ 코드 검사가 정당한 두 번째 기법을 막음 3 (+ 자료가 있는데 센터 자료 찾기로 감 2)

고친 방법(모델이 정하는 것: 단계 나누기, 단계마다 부를 도구와 인자, 건너뛰기 / 코드가 하는 것: 상태 보여 주기, 인자 정규화, 형식 검사, 상한):
  ① 남은 단계를 기억하는 장치: 모델이 첫 차례에 단계 목록을 쓰면 코드가 체크리스트로 들고, 차례마다 끝난 단계·결과와 남은 단계를 보여 준다.
     남은 단계가 있으면 답을 내지 않는다(모델이 skip_step으로 이유를 대고 넘길 수는 있다).
  ⑤ 앞 결과 전달: 끝난 단계의 핵심 값(1위 동네 등)을 다음 차례 입력에 넣고, 앞 결과를 쓰는 단계의 빈 동네 칸을 채운다.
  ③ 인자 정규화: 업종·지명·지표의 같은 뜻 낱말을 목록 값으로 바꾼다('한식당' → 한식, '대정읍 모슬포' → 대정읍).
  ④ 오류 문장에 고칠 값: 단계 문장을 규칙 해석기로 읽어 '이렇게 부르세요'를 제안한다. 한 단계에 두 번 실패하면 코드가 제안대로 한 번 부른다.
  ② 도구 좁히기: 단계 문장에 분석 기법을 뜻하는 말이 없으면 통계 기법 도구를 보이지 않는다.
  ⑥ 몰아넣기 막기: 한 차례에 지금 단계 하나만, 일반 답의 지표는 단계 문장에 있는 것만.
  ⑦ 기법 이름 검사는 질문 전체가 아니라 지금 단계 문장에 대해 한다.
  (+) 공개 자료로 답할 수 있는 단계에서 센터 자료 찾기를 부르면 일반 답 도구를 안내한다.
"""
import json
import re
import time

import qparse
import qtuple as Q

MAX_STEPS = 4
TRIES = 2  # 단계마다 모델이 고를 기회
BUDGET = 150.0  # 초(질문 담당 Agent와 같은 상한)
BY = "AI(로컬 모델)"

S_PLAN = ("너는 제주 상권 질문을 처리 단계로 나눈다. 질문에 물은 것이 여럿이면 물은 순서대로 한 단계에 하나씩 쓴다. "
          "단계는 동네·업종·무엇을 볼지가 드러난 짧은 한국어 문장이다. 앞 단계의 결과(예: 1위 동네, 비슷한 동네)를 써야 하면 uses_prev를 true로 한다. "
          "물은 것이 하나면 단계도 하나다. 질문에 없는 일을 더하지 않는다.")
PLAN_SCHEMA = {"type": "object", "required": ["steps"], "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": MAX_STEPS, "items": {
    "type": "object", "required": ["do", "uses_prev"], "properties": {"do": {"type": "string"}, "uses_prev": {"type": "boolean"}}}}}}

S_STEP = ("너는 제주 상권 자료 분석 Agent다. 아래 상태를 보고 '지금 단계' 하나를 처리할 도구를 하나 부른다. 숫자는 직접 만들지 않는다.\n"
          "- 정해진 질문 종류로 답할 수 있으면 answer_topic. 지금 단계에 필요한 칸만 넣는다.\n"
          "- 통계 기법(상관·군집·시계열 분해·회귀·검정·분포·이상치·변화 분해·입지계수·생존분석·다양성·변이할당)이 필요하면 run_technique.\n"
          "- 제출본 자료로 할 수 없고 센터 자료가 필요하면 search_center_catalog.\n"
          "- 자료로 할 수 없는 단계면 skip_step에 이유를 쓴다.\n"
          "- 앞 단계 결과에 나온 동네를 써야 하면 그 동네 이름을 그대로 넣는다.\n"
          "- 업종은 " + "·".join(Q.TARGETS_BIZ) + " 중에서, 동네는 행정동 이름으로 쓴다.")

TOOL_SKIP = {"type": "function", "function": {"name": "skip_step", "description": "지금 단계를 자료로 할 수 없을 때 이유를 적고 넘긴다.",
             "parameters": {"type": "object", "required": ["reason"], "properties": {"reason": {"type": "string"}}}}}

TARGET_ALIAS = {"외식": "음식점", "외식업": "음식점", "식당": "음식점", "음식": "음식점", "일반음식점": "음식점", "요식업": "음식점", "레스토랑": "음식점",
                "커피": "카페", "커피숍": "카페", "술집": "주점", "호프": "주점", "숙소": "숙박", "펜션": "숙박", "호텔": "숙박", "마트": "소매", "편의점업": "편의점"}
METRIC_ALIAS = {"유동인구": "일평균방문", "방문인구": "일평균방문", "방문객": "일평균방문", "생존율": "5년생존율", "매출액": "매출", "카드매출": "매출",
                "점포 수": "점포수", "가게 수": "점포수", "폐업": "폐업률", "개업": "개업수", "매출성장률": "매출성장", "증감률": "매출성장",
                "버스": "버스일평균", "버스이용": "버스일평균", "시간대": "시간대매출", "고령": "고령비중", "청년": "청년비중", "관광객": "관광객비중", "건당": "건당금액"}
TECH_ALIAS = {"forecast": ("T8", "예측은 통계 기법 목록에 없어요. answer_topic의 T8(예측)을 쓰세요."),
              "rank": ("T3", "순위는 통계 기법이 아니에요. answer_topic의 T3(순위)을 쓰세요."),
              "time": ("T13", "시간대는 통계 기법이 아니에요. answer_topic의 T13(시간대)을 쓰세요."),
              "trend": ("T4", "추세는 answer_topic의 T4(추세)를 쓰세요.")}
PREV_WORDS = re.compile(r"1위|선정|그\s*동네|해당|위\s*동네|앞|유사|비슷한")


def _tech_ok(step):
    import analyst
    import techniques as T
    # '예측·전망'은 통계 기법 도구가 아니라 일반 답(T8)이다
    return bool(T.detect(step) or (analyst.ANALYSIS_HINT.search(step) and not re.fullmatch(r".*(예측|전망).*", step) or re.search(r"상관|군집|회귀|검정|분해|이상치|입지계수|생존\s*분석|변이할당", step)))


def _target(x, step):
    x = (x or "").strip()
    if not x:
        return ""
    if x in Q.TARGETS_BIZ:
        return x
    if x in TARGET_ALIAS:
        return TARGET_ALIAS[x]
    for w, g in qparse.BIZ_KEYS:  # '한식당' → 한식, '치킨집' → 치킨
        if w in x and g in Q.TARGETS_BIZ:
            return g
    fam = qparse.TARGET_FAMILY.get(x)
    if fam in Q.TARGETS_BIZ:
        return fam
    d = qparse.DETAIL.get(x)  # 세부 업종(베이커리 등)은 대분류로
    if d and qparse.MAJOR_TARGET.get(d.get("major")) in Q.TARGETS_BIZ:
        return qparse.MAJOR_TARGET[d["major"]]
    p = qparse.parse(step).get("target")
    return p if p in Q.TARGETS_BIZ else ""


def _space(xs, step, facts, uses_prev):
    out = []
    for x in xs or []:
        x = str(x).strip()
        if x in Q.DONGS:
            out.append(x)
        elif x in qparse.MULTI_PLACES:
            out += qparse.MULTI_PLACES[x]
        elif x in Q.DONG_ALIAS:
            out.append(Q.DONG_ALIAS[x])
        elif x:
            out += qparse.find_places(x)[0]  # '대정읍 모슬포' → 대정읍, '안덕면 사계리' → 안덕면, '일대' → 없음
    if uses_prev and facts.get("dongs") and (not out or any(PREV_WORDS.search(str(x)) for x in xs or [])):
        out = list(facts["dongs"])[:1] if re.search(r"1위|가장|제일", step) else list(facts["dongs"])[:2]
    if not out:
        out = qparse.find_places(step)[0]
    if not out and facts.get("space") and not re.search(r"제주\s*(도|전체|전역)|동네\s*(별|들)|순위|가장|제일", step):
        out = list(facts["space"])  # 단계 문장에 동네가 없으면 앞 단계의 동네를 이어받는다('앞으로 3개월 방문 예측' ← 안덕면)
    return list(dict.fromkeys(d for d in out if d in Q.DONGS))


def _metric(ms, step):
    out = []
    for m in ms or []:
        m = str(m).strip()
        out.append(m if m in Q.METRICS else METRIC_ALIAS.get(m) or METRIC_ALIAS.get(m.replace(" ", "")))
    out = [m for m in dict.fromkeys(out) if m]
    said = qparse.parse(step).get("metric") or []
    if said:  # 몰아넣기 막기: 단계 문장에 있는 지표만(모델이 붙인 다른 지표는 뺀다)
        out = [m for m in out if m in said] or said
    elif len(out) > 2:
        out = out[:1]
    return out


def suggest(step, facts, uses_prev):
    """단계 문장을 규칙 해석기로 읽은 answer_topic 인자(오류 문장의 '고칠 값'이자 두 번 실패했을 때 코드가 부를 값)."""
    p = qparse.parse(step)
    t = p.get("type") if p.get("type") in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T13", "T14", "T15") else "T1"
    sp = _space([], step, facts, uses_prev)
    if t == "T3" and uses_prev and sp:  # 앞 결과의 동네를 쓰는 단계는 순위가 아니라 그 동네 값
        t = "T1"
    return {"type": t, "space": sp, "target": p.get("target") if p.get("target") in Q.TARGETS_BIZ else "", "metric": p.get("metric") or []}


def _call_topic(step, args):
    import result
    import verify
    t = {"type": args.get("type"), "metric": args.get("metric") or [], "target": args.get("target") or None, "space": args.get("space") or [],
         "time": None, "time_year": None, "breakdown": None, "cond": [], "form": "수치", "expect": "답함"}
    errs = verify.check_tuple(t)
    if errs:
        return False, {"error": "칸이 맞지 않아요: " + "; ".join(e.get("detail", "") for e in errs)}, None
    it = {"tuple": t, "card": qparse.card(t), "path": "단계형 Agent 지정", "confidence": None, "sec": 0.0}
    # 지금 단계 문장으로, 모델이 정한 칸 그대로(보정 규칙이 덮지 않게 _agent_tuple) 계산한다
    out = result.respond(step, {"_no_split": True, "_agent_tuple": True}, llm_on=False, interpret=lambda q: it)
    card = out.get("card") or {}
    if out.get("status") in ("범위밖", "선택필요") or not card.get("evidence"):
        return False, {"error": card.get("conclusion") or (out.get("choose") or {}).get("message") or "답을 만들지 못했어요"}, out
    return True, {"conclusion": card.get("conclusion"), "evidence": [e["text"] for e in card.get("evidence", [])][:4]}, out


def _facts(out, facts):
    ds = [d for d in (out or {}).get("result_dongs") or [] if d in Q.DONGS]
    concl = ((out or {}).get("card") or {}).get("conclusion") or ""
    top = re.findall(r"\d+위 ([가-힣0-9]+(?:동|읍|면))", concl)
    got = [d for d in top if d in Q.DONGS] or ds
    if got:
        facts["dongs"] = got
        facts["text"] = f"앞 단계에서 나온 동네: {', '.join(got[:3])}" + (" (1위부터)" if top else "")
    return facts


def run(question, chat=None):
    """단계형 Agent 한 번. expert.ask와 비슷한 모양(status, method, lines, trace, steps, topics)을 돌려준다."""
    import analyst
    import expert
    import prompts as P
    t0 = time.perf_counter()
    trace, topics, facts = [], [], {}
    # ① 계획: 모델이 단계를 나눈다(JSON 형식 고정). 실패하면 코드가 질문 나누기로 대신한다. chat은 시험용 가짜 모델
    plan = (analyst._ask(chat, S_PLAN, question, PLAN_SCHEMA, max_tokens=400) or {}).get("steps") or []
    chat = chat or expert._chat_fn("ollama")
    steps = [{"do": s["do"].strip(), "uses_prev": bool(s.get("uses_prev")), "state": "남음", "result": None, "tries": 0} for s in plan if str(s.get("do", "")).strip()][:MAX_STEPS]
    by_plan = BY
    if not steps:
        import split
        steps = [{"do": p, "uses_prev": i > 0 and bool(PREV_WORDS.search(p)), "state": "남음", "result": None, "tries": 0} for i, p in enumerate(split.pieces(question) or [question])][:MAX_STEPS]
        by_plan = "코드(모델이 단계를 쓰지 못함)"
    trace.append({"step": 1, "tool": "plan", "name": "단계 나누기", "by": by_plan, "ok": True, "args": json.dumps([s["do"] for s in steps], ensure_ascii=False)[:160], "note": f"{len(steps)}단계", "sec": round(time.perf_counter() - t0, 2)})

    while any(s["state"] == "남음" for s in steps):
        if time.perf_counter() - t0 > BUDGET:
            trace.append({"step": len(trace) + 1, "tool": "-", "name": "시간 상한", "by": "코드", "ok": False, "args": "", "note": f"{BUDGET:.0f}초를 넘어 멈춤", "sec": 0})
            break
        i = next(k for k, s in enumerate(steps) if s["state"] == "남음")
        s = steps[i]
        tools = [P.TOOL_TOPIC] + ([P.TOOL_TECHNIQUE] if _tech_ok(s["do"]) else []) + [P.TOOL_CATALOG, TOOL_SKIP]  # ② 도구 좁히기
        state = _state(question, steps, i, facts, s.get("hint"))
        t1 = time.perf_counter()
        try:
            msg = chat(None, [{"role": "system", "content": S_STEP}, {"role": "user", "content": state}], tools)["message"]
        except Exception as e:  # noqa: BLE001
            msg = {"content": f"모델 오류 {type(e).__name__}"}
        fn, args = _first_call(msg, {t["function"]["name"] for t in tools})
        s["tries"] += 1
        if fn is None:
            ok, reply, extra, who = False, {"error": "도구를 부르지 않았어요. 지금 단계에 맞는 도구 하나를 부르세요."}, None, BY
        else:
            ok, reply, extra, args = _do(fn, args, s, facts)
            who = BY
        if not ok and s["tries"] >= TRIES and fn != "skip_step":  # ④ 두 번 실패하면 코드가 제안대로 한 번 부른다
            sug = suggest(s["do"], facts, s["uses_prev"])
            ok, reply, extra = _call_topic(s["do"], sug)
            fn, args, who = "answer_topic", sug, "코드(모델이 두 번 실패해 제안대로)"
        trace.append({"step": len(trace) + 1, "tool": fn or "-", "name": f"{i + 1}단계: {s['do'][:30]}", "by": who, "ok": ok,
                      "args": json.dumps(args, ensure_ascii=False)[:160] if args else "", "note": str(reply.get("error") or reply.get("conclusion") or reply.get("note") or "")[:120],
                      "sec": round(time.perf_counter() - t1, 2)})
        if fn == "skip_step" and ok:
            s["state"], s["result"] = "건너뜀", reply.get("note")
        elif ok:
            s["state"], s["result"] = "끝남", reply.get("conclusion") or reply.get("note")
            if fn == "answer_topic" and extra:
                topics.append(extra)
                _facts(extra, facts)
            if args and (args.get("space") or args.get("dongs")):
                facts["space"] = list(args.get("space") or args.get("dongs"))
        elif s["tries"] >= TRIES:
            s["state"], s["result"] = "못 함", reply.get("error")
        else:
            s["hint"] = reply.get("error")  # ④ 다음 차례에 고칠 값을 보여 준다

    lines = [x for s in steps if s["state"] == "끝남" for x in [s["result"]] if x]
    lines += [f"'{s['do']}'은(는) {s['result'] or '자료로 할 수 없어'} 넘겼어요." for s in steps if s["state"] in ("건너뜀", "못 함")]
    return {"status": "성공" if any(s["state"] == "끝남" for s in steps) else "실패", "method": "단계형 Agent", "backend": "ollama",
            "trace": trace, "steps": steps, "topics": topics, "lines": lines, "by": "AI(로컬 모델: 단계 나누기·도구 고르기) + 프로그램(숫자)",
            "sec": round(time.perf_counter() - t0, 1)}


def _state(question, steps, i, facts, hint):
    rows = []
    for k, s in enumerate(steps):
        tag = "지금" if k == i else s["state"]
        rows.append(f"{k + 1}. [{tag}] {s['do']}" + (f" → 결과: {str(s['result'])[:100]}" if s["result"] and k != i else ""))
    left = sum(1 for s in steps if s["state"] == "남음") - 1
    return (f"질문: {question}\n단계:\n" + "\n".join(rows)
            + (f"\n{facts['text']}" if facts.get("text") else "")
            + f"\n남은 단계: 지금 단계 말고 {left}개"
            + (f"\n지난 시도의 문제: {hint}" if hint else "")
            + f"\n지금 단계 {i + 1}을(를) 처리할 도구 하나를 부르세요.")


def _first_call(msg, allowed):
    calls = msg.get("tool_calls") or []
    if not calls and msg.get("content"):  # 소형 모델이 도구 호출을 본문 JSON으로 쓴 경우
        m = re.search(r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*\})\s*\}', msg["content"], re.S)
        if m and m.group(1) in allowed:
            try:
                return m.group(1), json.loads(m.group(2))
            except ValueError:
                pass
    for c in calls:
        fn = c.get("function", {}).get("name")
        if fn in allowed:
            a = c["function"].get("arguments") or {}
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except ValueError:
                    a = {}
            return fn, a
    return None, None


def _do(fn, args, s, facts):
    """도구 하나 실행. 돌려주는 값: ok, reply, extra(일반 답 결과), 정규화한 인자."""
    import expert
    step = s["do"]
    if fn == "skip_step":
        why = str(args.get("reason") or "").strip()
        if not why:
            return False, {"error": "넘기는 이유를 적어 주세요."}, None, args
        return True, {"note": why}, None, args
    if fn == "search_center_catalog":
        p = qparse.parse(step)
        if p.get("metric") and p.get("type") not in ("T11", "T12"):  # (+) 공개 자료로 답할 수 있는 단계
            sug = suggest(step, facts, s["uses_prev"])
            return False, {"error": f"이 단계는 공개 자료로 답할 수 있어요. answer_topic을 이렇게 부르세요: {json.dumps(sug, ensure_ascii=False)}"}, None, args
        ok, rep = expert._catalog(args)
        return ok and bool(rep.get("found")), {"note": rep.get("note"), "error": None if rep.get("found") else rep.get("note")}, None, args
    if fn == "run_technique":
        tech = args.get("technique")
        if tech in TECH_ALIAS:
            t, why = TECH_ALIAS[tech]
            sug = dict(suggest(step, facts, s["uses_prev"]), type=t)
            return False, {"error": f"{why} 예: {json.dumps(sug, ensure_ascii=False)}"}, None, args
        a2 = {"technique": tech, "dongs": _space(args.get("dongs"), step, facts, s["uses_prev"]), "target": _target(args.get("target"), step)}
        ok, rep, ans = expert._technique(step, a2)  # ⑦ 기법 이름 검사는 지금 단계 문장으로
        if not ok:
            return False, {"error": str(rep.get("error")) + (f" 이유: {rep.get('why')}" if rep.get("why") else "")}, None, a2
        return True, {"conclusion": rep.get("conclusion")}, None, a2
    # answer_topic: ③ 인자 정규화 ⑥ 지표 좁히기 ⑤ 앞 결과 채우기
    a2 = {"type": args.get("type") if args.get("type") in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T13", "T14", "T15") else suggest(step, facts, s["uses_prev"])["type"],
          "space": _space(args.get("space"), step, facts, s["uses_prev"]), "target": _target(args.get("target"), step), "metric": _metric(args.get("metric"), step)}
    if a2["type"] == "T3" and len(a2["space"]) == 1:  # 동네 하나의 값을 물은 단계는 순위가 아니라 현황
        a2["type"] = "T1"
    ok, rep, out = _call_topic(step, a2)
    if not ok:  # ④ 고칠 값 제안
        sug = suggest(step, facts, s["uses_prev"])
        rep = {"error": f"{rep.get('error')} 고칠 값 제안: {json.dumps(sug, ensure_ascii=False)}"}
    return ok, rep, out, a2
