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
import os
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
# 예시 증류(문제 기록 58번 (다), 2026-11-17): 교사 모델(Opus)이 조정용 질문에 쓴 단계 계획 중 질문이 가장 비슷한 2개를 계획 프롬프트에 예시로 넣는다.
# JEJU_PLAN_EXAMPLES = 예시 파일 경로(비우면 끔). 비슷함은 bge-m3 임베딩(CPU) 코사인. 같은 질문 문장은 예시로 쓰지 않는다(조정용 측정에서 답을 보는 것을 막음).
import os as _os  # noqa: E402

PLAN_EX = _os.environ.get("JEJU_PLAN_EXAMPLES", "")
PLAN_EX_K = int(_os.environ.get("JEJU_PLAN_EXAMPLES_K", "2"))
_EX = {}


def _plan_sys(question):
    """계획 프롬프트(S_PLAN) + 비슷한 질문의 교사 계획 예시."""
    if not PLAN_EX:
        return S_PLAN
    try:
        import numpy as np
        import x1_embed
        if "rows" not in _EX:
            from pathlib import Path
            _EX["rows"] = [json.loads(x) for x in Path(PLAN_EX).read_text(encoding="utf-8").splitlines() if x.strip()]
            v = x1_embed.embed([r["q"] for r in _EX["rows"]])
            _EX["vec"] = v / np.linalg.norm(v, axis=1, keepdims=True)
        q = x1_embed.embed_live(question)[0]
        sim = _EX["vec"] @ (q / np.linalg.norm(q))
        picks = [i for i in np.argsort(-sim) if _EX["rows"][i]["q"].strip() != question.strip()][:PLAN_EX_K]
    except Exception:  # noqa: BLE001 — 예시를 못 만들면 예시 없이 계획한다
        return S_PLAN
    ex = "\n".join(f"질문: {_EX['rows'][i]['q']}\n계획: " + json.dumps({"steps": [{"do": s["do"], "uses_prev": bool(s.get("uses_prev"))} for s in _EX["rows"][i]["steps"]]}, ensure_ascii=False)
                   for i in picks)
    return S_PLAN + "\n비슷한 질문의 좋은 계획 예시(형식과 단계 나누기만 참고하고, 동네·업종은 지금 질문의 것을 쓴다):\n" + ex


PLAN_SCHEMA = {"type": "object", "required": ["steps"], "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": MAX_STEPS, "items": {
    "type": "object", "required": ["do", "uses_prev"], "properties": {"do": {"type": "string"}, "uses_prev": {"type": "boolean"}}}}}}

S_STEP = ("너는 제주 상권 자료 분석 Agent다. 아래 상태를 보고 '지금 단계' 하나를 처리할 도구를 하나 부른다. 숫자는 직접 만들지 않는다.\n"
          "- 정해진 질문 종류로 답할 수 있으면 answer_topic. 지금 단계에 필요한 칸만 넣는다.\n"
          "- 통계 기법(상관·군집·시계열 분해·회귀·검정·분포·이상치·변화 분해·입지계수·생존분석·다양성·변이할당·포화도)이 필요하면 run_technique.\n"
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
    if ((out or {}).get("tuple") or {}).get("type") == "T9" and ds and not facts.get("ranked"):  # 비슷한 동네 단계: 찾은 동네들이 다음 단계의 '거기'(51번)
        facts["dongs"], facts["similar"], facts["ranked"] = ds, True, True
        facts["text"] = f"앞 단계에서 찾은 비슷한 동네: {', '.join(ds)}"
        return facts
    concl = ((out or {}).get("card") or {}).get("conclusion") or ""
    top = re.findall(r"\d+위 ([가-힣0-9]+(?:동|읍|면))", concl)
    if not top and ((out or {}).get("tuple") or {}).get("type") == "T3":  # 생존율·폐업률 순위는 'n위' 없이 '확인된 동네는 영천동(81.7%), …'로 답한다(51번 BG-026·028)
        top = [d for d in re.findall(r"([가-힣0-9]+(?:동|읍|면))\(\d", concl) if d in Q.DONGS]
    got = [d for d in top if d in Q.DONGS]
    if not got and not facts.get("ranked"):
        sp = [d for d in (((out or {}).get("tuple") or {}).get("space") or []) if d in Q.DONGS]
        got = sp[:1] or (ds[:1] if ds else [])  # 순위가 아닌 답은 해석한 동네 하나(결과 동네 목록의 '비슷한 동네'가 앞 결과가 되던 결함, 2026-11-16)
    if top and got:
        facts["ranked"] = True  # 순위 단계의 결과는 뒤 단계가 덮지 않는다('1위 동네'는 순위 결과를 가리킨다)
    elif facts.get("ranked"):
        return facts
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
    plan = (analyst._ask(chat, _plan_sys(question), question, PLAN_SCHEMA, max_tokens=400) or {}).get("steps") or []
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
        tools = [P.TOOL_TOPIC] + ([P.TOOL_TECHNIQUE] if (TECH_NAME.search(s["do"]) if s.get("orig") else _tech_ok(s["do"])) else []) + [P.TOOL_CATALOG, TOOL_SKIP]  # ② 도구 좁히기
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
    hist = "".join(f"\n앞 대화 D{k + 1}: {h['q']} → 결과: {h['result'][:100]}" for k, h in enumerate(facts.get("history") or []))
    return (f"질문: {question}" + hist + "\n단계:\n" + "\n".join(rows)
            + (f"\n{facts['text']}" if facts.get("text") else "")
            + (f"\n앞 단계에서 나온 1위 업종: {facts['biz']}" if facts.get("biz") else "")
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
        import techniques as TT
        tq = step
        if not TT.parse(step)["metrics"] and facts.get("q") and TT.parse(facts["q"])["metrics"]:  # 'STL 분해'처럼 지표 낱말이 없는 단계는 원래 질문의 지표(방문객 등)를 쓴다(2026-11-17 조정용 R076)
            tq = f"{step} ({TT.METRIC[TT.parse(facts['q'])['metrics'][0]][0]})"
        if re.search(r"CCF|교차", facts.get("q") or "") and not re.search(r"CCF|교차", tq):
            tq = f"{tq} (교차상관)"
        if re.search(r"건수", facts.get("q") or "") and "건수" not in tq:
            tq = f"{tq} (건수)"
        ok, rep, ans = expert._technique(tq, a2)  # ⑦ 기법 이름 검사는 지금 단계 문장으로
        if not ok and str(rep.get("error") or "").startswith("적용 조건이 맞지 않아"):
            # 기법이 조건 때문에 거절되면 그 이유를 이 단계의 답으로 확정한다. 다른 기법·도구로 바꿔 계산하지 않는다
            # (2026-11-17 실패 검토: 날씨 회귀가 거절되자 관계없는 43개 동 회귀를 대신 돌린 결함)
            import techniques as TT2
            why = " ".join(str(x) for x in (rep.get("why") or []))
            alt = [x.get("text") for b in ((ans or {}).get("answer") or {}).get("blocks") or [] for x in b.get("lines") or [] if x.get("tag") == "대신 할 수 있는 것"]
            why += f" 대신 할 수 있는 것: {alt[0]}" if alt else ""
            return True, {"conclusion": f"{TT2.TECH.get(tech, (tech,))[0]} 분석은 하지 않았어요. {why}".strip(), "refused": True}, None, a2
        if not ok:
            return False, {"error": str(rep.get("error")) + (f" 이유: {rep.get('why')}" if rep.get("why") else "")}, None, a2
        top = re.search(r"가장 몰려 있는 업종은 ([가-힣]+?)(?:이에요|예요)", str(rep.get("conclusion") or ""))
        if top:  # 입지계수 1위 업종을 다음 단계의 '1순위 업종'으로 넘긴다(53번, 조정용 R075)
            facts["biz"] = top.group(1)
            facts["space"] = a2["dongs"][:1] or facts.get("space")
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


# ---------- 서비스 연결(2026-11-16 마스터 '단계형 루프는 전체 서비스에 적용') ----------
STAGES = ["단계 나누기", "단계마다 도구 골라 계산", "답 정리"]
TOOL_ASK = {"type": "function", "function": {"name": "answer_question", "description":
            "지금 단계를 혼자 물어도 되는 질문 한 문장으로 써서 일반 답(해석·계산·검수·근거가 붙은 답 카드)을 만든다. 동네·업종·무엇을 볼지를 문장에 넣는다.",
            "parameters": {"type": "object", "required": ["question"], "properties": {"question": {"type": "string", "description": "예: 애월읍 카페 점포 수는?"}}}}}
S_SERVE = ("너는 제주 상권 질문에 답하는 Agent다. 아래 상태를 보고 '지금 단계' 하나를 처리할 도구를 하나 부른다. 숫자는 직접 만들지 않는다.\n"
           "- 동네·업종의 값·순위·비교·추세·예측·시간대·비 효과 같은 것은 answer_question에 그 단계만 묻는 질문 한 문장을 쓴다.\n"
           "- 통계 기법(상관·군집·시계열 분해·회귀·검정·분포·이상치·변화 분해·입지계수·생존분석·다양성·변이할당·포화도)을 지목한 단계는 run_technique.\n"
           "- 제출본 자료로 할 수 없고 센터 자료가 필요하면 search_center_catalog.\n"
           "- 자료로 할 수 없는 단계면 skip_step에 이유를 쓴다.\n"
           "- 앞 단계 결과에 나온 동네를 써야 하면 그 동네 이름을 질문 문장에 그대로 넣는다.\n"
           "- 한 동네 안에서 어떤 업종이 가장 많은지·높은지는 rank_industries. 1위 업종은 다음 단계가 이어받는다.\n"
           "- 앞 단계(또는 앞 대화)의 숫자를 견주기만 하는 단계는 compare_steps에 단계 번호를 넣는다(앞 대화는 D1·D2).")


def serve(question, env=None, llm_on=True, progress=None, forced=None):
    """서비스 경로의 단계형 Agent. 모델이 단계를 나누고(1회), 단계마다 도구를 고른다.
    단계가 하나면 원래 질문을 질문 담당 Agent(question_agent.run)에 그대로 넘긴다(단순 질문 정확도 유지).
    단계가 여럿이면 단계마다 모델이 고른 도구로 계산하고, 질문 나누기와 같은 모양(status 'Agent', agent.lines·trace·topics)으로 묶는다.
    env['history']: 화면이 보낸 직전 질문·결론(⑥ 대화 맥락, 최대 2개)."""
    import analyst
    import question_agent
    say = progress or (lambda i, d: None)
    env = dict(env or {})
    staff = bool(env.pop("staff", False))  # 심사용(담당자) 계정으로 로그인한 요청: 단계별 도구 고르기에 Claude(마스터 2026-11-18 '가. 단 평가자만')
    history = [h for h in (env.pop("history", None) or []) if isinstance(h, dict) and h.get("question")][-2:]
    if forced == ONE_STEP:  # ⑤ 확인 카드에서 '한 가지 질문으로 보고 답하기'를 고름
        r = question_agent.run(question, env, llm_on=llm_on, progress=progress)
        r["confirm"] = {"pause": False, "forced": ONE_STEP, "why": "", "first": None, "options": []}
        return r
    if forced:  # 확인 카드에서 고른 선택지로 다시 계산: 질문 담당 Agent로 바로
        return question_agent.run(question, env, llm_on=llm_on, progress=progress, forced=forced)
    t0 = time.perf_counter()
    q = question
    ctx = None
    merged = merge_follow(question, history)  # ⑥ '그럼 애월읍은?' → 앞 질문과 합침
    if merged and merged != question:
        q, ctx = merged, f"앞 질문('{history[-1]['question']}')에 이어서 '{merged}'(으)로 이해했어요."
    say(1, "질문에 물은 것이 몇 가지인지 단계로 나누고 있어요")
    if history and not merged and FOLLOW.search(question) and COMPARE_WORDS.search(question):  # ⑥ '둘 중 어디가 더 많아?': 앞 대화 결과를 비교
        plan = [{"do": question, "uses_prev": True}]
        ptrace = {"step": 1, "tool": "plan", "name": "단계 나누기", "by": "코드(앞 대화를 비교하는 이어지는 질문)", "ok": True, "args": json.dumps([question], ensure_ascii=False),
                  "note": "1단계(앞 대화 결과 비교)", "sec": 0.0}
        return _serve_steps(question, env, llm_on, (lambda i, d: progress(i, d, STAGES)) if progress else say, plan, ptrace, t0, history, staff)
    cl = clauses(q)  # 원문 구절이 둘 이상이면 코드가 원문 구절로 단계를 쓴다(51번: 초보 말투에서 모델 계획이 낱말로 쪼개거나 뜻을 바꿈)
    if len(cl) >= 2:
        plan = cl
        ptrace = {"step": 1, "tool": "plan", "name": "단계 나누기", "by": "코드(질문 원문의 구절로 나눔)", "ok": True,
                  "args": json.dumps([s["do"] for s in plan], ensure_ascii=False)[:160], "note": f"{len(plan)}단계", "sec": round(time.perf_counter() - t0, 2)}
        r = _serve_steps(q, env, llm_on, (lambda i, d: progress(i, d, STAGES)) if progress else say, plan, ptrace, t0, history, staff)
        r["question"] = question
        steps_txt = " / ".join(f"{k + 1}. {s}" for k, s in enumerate(r["step_agent"]["plan"]))
        r["confirm"] = {"pause": False, "why": "", "first": {"text": f"{len(r['step_agent']['plan'])}단계로 나눠 답하기: {steps_txt}", "pick": f"{len(plan)}단계로 나눠 답하기", "act": "단계 나누기"},
                        "after": [], "options": [{"text": ONE_STEP, "pick": ONE_STEP, "act": "한 단계"}], "plan_conf": None}
        if ctx:
            r["card"]["limits"] = [ctx] + list(r["card"].get("limits") or [])
        return r
    plan = (analyst._ask(None, _plan_sys(q), q, PLAN_SCHEMA, max_tokens=400) or {}).get("steps") or []
    plan = [s for s in plan if str(s.get("do", "")).strip()][:MAX_STEPS]
    ptrace = {"step": 1, "tool": "plan", "name": "단계 나누기", "by": BY if plan else "코드(모델이 단계를 쓰지 못함)", "ok": bool(plan),
              "args": json.dumps([s.get("do") for s in plan], ensure_ascii=False)[:160], "note": f"{len(plan) or 1}단계", "sec": round(time.perf_counter() - t0, 2)}
    if len(plan) > 1 and not _multi_ok(q):  # 여러 일을 잇는 표지가 없는 질문을 낱말마다 쪼갠 계획은 받지 않는다('노형동 / 카페 / 가게 수')
        ptrace["note"] = f"모델이 {len(plan)}단계로 나눴지만 질문에 여러 일을 잇는 표지가 없어 1단계로 봄"
        ptrace["by"] = BY + " + 코드 검사"
        plan = plan[:1]
    if len(plan) <= 1:
        r = question_agent.run(q, env, llm_on=llm_on, progress=progress)
        r["step_agent"] = {"plan": [q], "trace": [ptrace]}
        if ctx:
            r["question"] = question
            und = r.get("understood") if isinstance(r.get("understood"), dict) else None
            if und is not None:
                und["notes"] = [ctx] + list(und.get("notes") or [])
            else:
                (r.setdefault("card", {}) or {}).setdefault("limits", []).insert(0, ctx)
        return r
    _, probs = question_agent._ask_choice(None, S_COUNT, q, COUNT_SCHEMA, ["1", "2", "3", "4"], key="n")  # ⑤ 계획 확신도
    pconf = round(1 - probs.get("1", 0.0), 4) if probs else None
    if pconf is not None:
        ptrace["note"] += f", 여러 가지를 물었을 확률 {pconf:.2f}"
    r = _serve_steps(q, env, llm_on, (lambda i, d: progress(i, d, STAGES)) if progress else say, plan, ptrace, t0, history, staff)
    r["question"] = question
    steps_txt = " / ".join(f"{k + 1}. {s}" for k, s in enumerate(r["step_agent"]["plan"]))
    pause = pconf is not None and pconf < PLAN_PAUSE
    r["confirm"] = {"pause": pause, "why": f"질문이 여러 가지를 물었는지 확신이 낮아요(여러 가지일 확률 {pconf:.2f})" if pause else "",
                    "first": {"text": f"{len(r['step_agent']['plan'])}단계로 나눠 답하기: {steps_txt}", "pick": f"{len(plan)}단계로 나눠 답하기", "act": "단계 나누기"},
                    "after": [], "options": [{"text": ONE_STEP, "pick": ONE_STEP, "act": "한 단계"}], "plan_conf": pconf}
    if ctx:
        r["card"]["limits"] = [ctx] + list(r["card"].get("limits") or [])
    return r


def _serve_steps(question, env, llm_on, say, plan, ptrace, t0, history=None, staff=False):
    import analyst
    import split
    import prompts as P
    chat = _chat(staff)
    steps = [{"do": s["do"].strip(), "uses_prev": bool(s.get("uses_prev")), "orig": bool(s.get("orig")), "state": "남음", "result": None, "tries": 0} for s in plan]
    trace, topics, facts, lines, series, tables = [ptrace], [], {"q": question}, [], [], []
    facts["history"] = [{"q": h["question"], "result": str(h.get("conclusion") or "")[:200],
                         "value": values_of(h.get("conclusion"), "·".join(h.get("space") or []) or str(h["question"])[:20])} for h in (history or [])]
    notes = []  # 단계마다 붙은 안내·한계(대체 지표, 기간 등)를 묶은 답에도 남긴다
    replanned = False
    checked = all(x.get("orig") for x in steps)  # 원문 구절로 나눈 계획은 질문 전체를 덮으므로 자기 확인을 하지 않는다(51번: 불필요한 3단계를 덧붙임)
    while True:
        while any(s["state"] == "남음" for s in steps):
            if time.perf_counter() - t0 > BUDGET:
                trace.append({"step": len(trace) + 1, "tool": "-", "name": "시간 상한", "by": "코드", "ok": False, "args": "", "note": f"{BUDGET:.0f}초를 넘어 멈춤", "sec": 0})
                break
            i = next(k for k, s in enumerate(steps) if s["state"] == "남음")
            s = steps[i]
            if i > 0 and SUMMARY_STEP.search(s["do"]) and sum(1 for x in steps[:i] if x["state"] == "끝남") >= 2 and _overlap(s["do"], question) >= 0.45:
                s["state"], s["result"] = "끝남", f"앞 {i}단계의 답을 함께 보세요(따로 계산하지 않았어요)."  # 앞 단계를 모아 보여 달라는 단계는 다시 계산하지 않는다(R054 4단계)
                trace.append({"step": len(trace) + 1, "tool": "-", "name": f"{i + 1}단계 · 앞 단계 모음", "by": "코드", "ok": True, "args": s["do"][:160], "note": s["result"], "sec": 0})
                lines.append(f"{i + 1}. {s['do']} → {s['result']}")
                continue
            same = next((k for k, x in enumerate(steps[:i]) if x["state"] == "끝남" and re.sub(r"\W", "", x["do"]) == re.sub(r"\W", "", s["do"])), None)
            if same is not None:  # 다시 계획·자기 확인이 끝난 단계와 같은 문장을 다시 넣으면 계산하지 않는다(53번, 조정용 R075)
                s["state"], s["result"] = "끝남", f"{same + 1}단계와 같은 단계라 다시 계산하지 않았어요."
                trace.append({"step": len(trace) + 1, "tool": "-", "name": f"{i + 1}단계 · 같은 단계", "by": "코드", "ok": True, "args": s["do"][:160], "note": s["result"], "sec": 0})
                continue
            say(2, f"{i + 1}/{len(steps)}단계: {s['do'][:40]}")
            n_vals = sum(1 for x in steps if x.get("value")) + sum(1 for h in facts["history"] if h["value"])
            tools = ([TOOL_ASK] + ([TOOL_BIZRANK] if BIZ_RANK_WORDS.search(s["do"]) and BIZ_RANK_Q.search(s["do"]) and not (facts.get("biz") and BIZ_ASK.search(s["do"])) else [])
                     + ([P.TOOL_TECHNIQUE] if (TECH_NAME.search(s["do"]) if s.get("orig") else _tech_ok(s["do"])) else []) + ([TOOL_COMPARE] if n_vals >= 2 and COMPARE_WORDS.search(s["do"]) else [])
                     + ([] if (s.get("orig") or SIMILAR_STEP.search(s["do"])) and not (DATA_ASK.search(s["do"]) or "센터" in s["do"]) else [P.TOOL_CATALOG]) + [TOOL_SKIP])  # 원문 구절 단계는 자료·센터를 묻지 않으면 센터 자료 찾기를 보이지 않는다(BG-036 '비슷한 동네 찾아줘')
            if TECH_ONLY.search(s["do"]) or (s.get("orig") and _named_tech(s["do"])):  # 일반 답 도구로 계산할 수 없는 기법(포화도), 또는 질문 원문 구절에 기법 이름이 있으면 기법 도구만(도구 좁히기, 2026-11-17)
                tools = [P.TOOL_TECHNIQUE, TOOL_SKIP]
            t1 = time.perf_counter()
            try:
                msg = chat(None, [{"role": "system", "content": S_SERVE}, {"role": "user", "content": _state(question, steps, i, facts, s.get("hint"))}], tools)["message"]
            except Exception as e:  # noqa: BLE001
                msg = {"content": f"모델 오류 {type(e).__name__}"}
            fn, args = _first_call(msg, {t["function"]["name"] for t in tools})
            s["tries"] += 1
            who, out = BY, None
            if fn is None:
                ok, reply = False, {"error": "도구를 부르지 않았어요. 지금 단계에 맞는 도구 하나를 부르세요."}
            elif fn == "answer_question":
                if s.get("orig"):  # 원문 구절 단계는 모델이 다시 쓴 문장 대신 원문 구절로 묻는다('장사 잘돼?' → '점포 수는?'으로 바뀌던 결함)
                    args = {"question": s["do"]}
                ok, reply, out, args = _ask_step(args, s, facts, env, llm_on)
                s["asked"] = (args or {}).get("question")
                if not ok and (out or {}).get("status") == "범위밖":  # 자료 범위 밖(예: 숙박 폐업률)은 다시 시도하지 않고 이유와 함께 넘긴다
                    ok, fn, reply = True, "skip_step", {"note": reply.get("error")}
            elif fn == "compare_steps":  # ① 비교·종합
                ok, reply = _compare_step(args, steps, facts)
            elif fn == "rank_industries":  # ② 업종 순위 → 1위 업종 이어받기
                dong = (_space([str((args or {}).get("dong") or "")], s["do"], facts, s["uses_prev"]) or [str((args or {}).get("dong") or "")])[0]
                ok, line, top = rank_industries(dong, (args or {}).get("by") if (args or {}).get("by") in ("가게 수", "카드 매출") else ("카드 매출" if re.search(r"매출", s["do"]) else "가게 수"))
                reply = {"conclusion": line} if ok else {"error": line}
                if ok and top:
                    facts["biz"] = top
                    facts["space"] = [dong]
                args = {"dong": dong, "by": (args or {}).get("by")}
            else:
                ok, reply, out, args = _do(fn, args, s, facts)
                if ok and fn == "run_technique" and facts.get("biz"):  # 기법이 찾은 1위 업종을 질문이 다시 물으면('그중 1순위 업종 점포 수') 그 단계가 계획에 없을 때 코드가 더한다(53번, 조정용 R075)
                    m = BIZ_ASK.search(facts.get("q") or "")
                    if m and not any(facts["biz"] in x["do"] or BIZ_REF.search(x["do"]) for x in steps[i + 1:]):
                        steps.insert(i + 1, {"do": BIZ_REF.sub(facts["biz"], m.group(0), count=1), "uses_prev": False, "orig": False, "state": "남음", "result": None, "tries": 0})
            if not ok and s["tries"] >= TRIES and fn != "skip_step" and (TECH_ONLY.search(s["do"]) or (s.get("orig") and _named_tech(s["do"]))):  # 기법 단계는 일반 답이 아니라 그 기법으로(2026-11-17)
                ok, reply, out, args = _do("run_technique", {"technique": "sat" if TECH_ONLY.search(s["do"]) else _named_tech(s["do"])}, s, facts)
                fn, who = "run_technique", "코드(모델이 두 번 실패해 단계 문장의 기법으로)"
            elif not ok and s["tries"] >= TRIES and fn != "skip_step":  # 두 번 실패하면 코드가 단계 문장 그대로 일반 답을 한 번 부른다
                ok, reply, out, args = _ask_step({"question": s["do"]}, s, facts, env, llm_on)
                fn, who = "answer_question", "코드(모델이 두 번 실패해 단계 문장 그대로)"
            trace.append({"step": len(trace) + 1, "tool": fn or "-", "name": f"{i + 1}단계 · " + {"answer_question": "일반 답", "run_technique": "통계 기법", "search_center_catalog": "센터 자료 찾기",
                                                                                                "skip_step": "건너뜀", "compare_steps": "비교·종합", "rank_industries": "업종 순위"}.get(fn, "도구 없음"),
                          "by": who, "ok": ok, "args": (args.get("question") if isinstance(args, dict) and args.get("question") else json.dumps(args, ensure_ascii=False))[:160] if args else "",
                          "note": str(reply.get("error") or reply.get("conclusion") or reply.get("note") or "")[:120], "sec": round(time.perf_counter() - t1, 2)})
            head = f"{i + 1}. {(args or {}).get('question') or s['do']}"
            if fn == "skip_step" and ok:
                s["state"], s["result"] = "건너뜀", reply.get("note")
                lines.append(f"{head} → 자료로 할 수 없어 넘겼어요: {reply.get('note')}")
            elif ok:
                s["state"], s["result"] = "끝남", reply.get("conclusion") or reply.get("note")
                card = (out or {}).get("card") or {}
                dup = next((k for k, x in enumerate(steps[:i]) if x.get("state") == "끝남" and x.get("result") == s["result"]), None)
                if dup is not None:  # 다른 문장의 단계가 앞 단계와 똑같은 답을 내면 다시 쓰지 않는다(2026-11-17 실패 검토 V160 유형: 같은 답이 세 번 나오던 결함)
                    lines.append(f"{head} → {dup + 1}단계와 같은 결과예요. 이 단계만의 값은 자료에서 따로 찾지 못했어요.")
                    continue
                lines.append(f"{head} → {s['result']}")
                sub = [n for n in list(((out or {}).get("understood") or {}).get("notes") or []) + list(card.get("limits") or []) if "대신" in str(n)]
                lines += [f"   · {n}" for n in dict.fromkeys(sub)][:1]  # 다른 지표로 대신 답했으면 그 단계 바로 아래에 밝힌다(시간대 사람 수·비 온 날 매출, 2026-11-17)
                lines += [f"   · {e['text']}" for e in (card.get("evidence") or []) if e["text"] not in str(s["result"])][:2]  # 결론과 같은 근거 줄은 다시 쓰지 않는다
                if fn == "answer_question" and out:
                    s["value"] = values_of(s["result"], _label(out, s["do"]))
                    if s["value"] and "제주 전체" in str(s["result"]) and ((out.get("tuple") or {}).get("space")):
                        s["value"] = None  # 동네를 물었는데 제주 전체 값으로 답한 단계(업종별 동네 값이 없는 생존율 등)는 동네 값으로 견주지 않는다(R065)
                    notes += list((out.get("understood") or {}).get("notes") or []) + list(card.get("limits") or [])
                    topics.append({"tuple": out.get("tuple"), "card": card, "question": (args or {}).get("question")})
                    _facts(out, facts)
                    seen_t = {x.get("title", "").split(" · ", 1)[-1] for x in series}
                    series += [x for x in split._piece_series(i, out) if x.get("title", "").split(" · ", 1)[-1] not in seen_t]  # 같은 그래프는 한 번만
                if isinstance(args, dict) and (args.get("space") or args.get("dongs") or ((out or {}).get("tuple") or {}).get("space")):
                    facts["space"] = list(args.get("space") or args.get("dongs") or out["tuple"]["space"])
            elif s["tries"] >= TRIES:
                s["state"], s["result"] = "못 함", reply.get("error")
                lines.append(f"{head} → {reply.get('error') or '답을 만들지 못했어요'}")
            else:
                s["hint"] = reply.get("error")
            if s["state"] in ("못 함", "건너뜀") and not replanned and any(x["state"] == "남음" for x in steps) and time.perf_counter() - t0 < BUDGET - 30:
                replanned = True  # ③ 실패·건너뜀 뒤 남은 단계를 모델이 한 번 다시 쓴다
                steps, rt = _replan(analyst, question, steps, i, facts)
                trace.append(rt)
        if checked or not any(x["state"] == "끝남" for x in steps) or time.perf_counter() - t0 > BUDGET - 30:
            break
        checked = True  # ④ 답 내기 전 자기 확인(한 번)
        add, ct = _self_check(analyst, question, steps, topics)
        trace.append(ct)
        if not add:
            break
        steps.append({"do": add, "uses_prev": False, "state": "남음", "result": None, "tries": 0})
    say(3, "단계별 답을 묶고 있어요")
    n_ok = sum(1 for s in steps if s["state"] == "끝남")
    ag = {"status": "성공" if n_ok else "실패", "method": f"단계형 Agent({len(steps)}단계)", "lines": lines, "by": "AI(로컬 모델: 단계 나누기·도구 고르기·다시 계획·자기 확인) + 프로그램(숫자)",
          "result": {"numbers": {}, "notes": [], "series": series, "tables": tables}, "trace": trace, "topics": topics or None, "backend": "ollama",
          "plan": [f"{k + 1}. {s['do']}" + (" (앞 단계 결과를 씀)" if s["uses_prev"] else "") for k, s in enumerate(steps)], "sec": round(time.perf_counter() - t0, 1)}
    if not n_ok:
        ag["error"] = "어느 단계도 답하지 못했어요."
    first = next((tp["tuple"] for tp in topics if tp.get("tuple")), {})
    return {"question": question, "status": "Agent", "tuple": first, "interpret": {"path": "단계형 Agent", "card": None}, "agent": ag,
            "escalated": f"단계형 Agent가 질문을 {len(steps)}단계로 나눠 답함",
            "card": {"conclusion": (lines or [""])[0], "evidence": [], "intervals": [], "limits": list(dict.fromkeys(notes)), "next_questions": []},
            "step_agent": {"plan": [s["do"] for s in steps], "trace": trace}, "sec": round(time.perf_counter() - t0, 3)}


def _compare_step(args, steps, facts):
    """① compare_steps: 고른 단계(숫자)·앞 대화('D1')의 결론 숫자를 코드가 비교한다."""
    picks = (args or {}).get("steps") or []
    items = []
    for p in picks if isinstance(picks, list) else [picks]:
        p = str(p).strip()
        m = re.fullmatch(r"[Dd대화\s]*(\d+)", p)
        if p[:1] in "Dd대" and m and 1 <= int(m.group(1)) <= len(facts["history"]):
            items.append(facts["history"][int(m.group(1)) - 1]["value"])
        elif p.isdigit() and 1 <= int(p) <= len(steps):
            items.append(steps[int(p) - 1].get("value"))
    if len([x for x in items if x]) < 2:  # 번호를 잘못 고르면 숫자가 있는 단계를 모두 쓴다
        items = [x.get("value") for x in steps if x.get("value")] + [h["value"] for h in facts["history"] if h["value"]]
    ok, line = compare(items)
    return ok, ({"conclusion": line} if ok else {"error": line})


def _replan(analyst, question, steps, i, facts):
    """③ 실패한 단계 뒤 남은 단계를 모델이 다시 쓴다(한 번). (새 단계 목록, 기록 한 줄)."""
    t1 = time.perf_counter()
    done = "\n".join(f"{k + 1}. [{s['state']}] {s['do']}" + (f" → {str(s['result'])[:100]}" if s["result"] else "") for k, s in enumerate(steps))
    user = f"질문: {question}\n단계:\n{done}\n실패하거나 넘어간 단계: {i + 1}. {steps[i]['do']} (이유: {str(steps[i]['result'])[:120]})\n남은 단계를 다시 쓰세요."
    new = [x for x in ((analyst._ask(None, S_REPLAN, user, REPLAN_SCHEMA, max_tokens=300) or {}).get("steps") or []) if str(x.get("do", "")).strip()][:3]
    keep = [s for s in steps if s["state"] != "남음"]
    old_left = [s["do"] for s in steps if s["state"] == "남음"]
    if not new and old_left:  # 모델이 빈 목록을 쓰면 남은 단계를 모두 할 수 없다고 본 것: 이유와 함께 넘긴다
        for s in steps:
            if s["state"] == "남음":
                s["state"], s["result"] = "건너뜀", f"앞 단계({i + 1})가 실패해 다시 계획에서 뺐어요"
        return steps, {"step": 0, "tool": "replan", "name": "다시 계획", "by": BY, "ok": True, "args": "", "note": "남은 단계를 모두 뺌", "sec": round(time.perf_counter() - t1, 2)}
    revive = [dict(x, tries=0) for x in steps if x["state"] == "남음" and BIZ_ASK.search(x["do"]) and x["do"] not in [n["do"] for n in new]]
    # 다시 계획이 '1순위 업종의 점포 수' 같은 앞 결과를 쓰는 남은 단계를 빼거나 질문 전체로 뭉뚱그리면 그 단계를 먼저 되살린다(53번, 조정용 R075)
    out = keep + revive + [{"do": x["do"].strip(), "uses_prev": bool(x.get("uses_prev")), "state": "남음", "result": None, "tries": 0} for x in new]
    return out[:MAX_STEPS + 2], {"step": 0, "tool": "replan", "name": "다시 계획", "by": BY, "ok": True, "args": json.dumps([x["do"] for x in new], ensure_ascii=False)[:160],
                                 "note": f"남은 단계 {len(old_left)}개 → {len(new)}개", "sec": round(time.perf_counter() - t1, 2)}


def _self_check(analyst, question, steps, topics):
    """④ 답 내기 전 자기 확인: 모델이 빠진 요청을 적으면, 질문에 있는 동네·지표와 겹치고 이미 답한 것이 아닐 때만 단계로 더한다."""
    t1 = time.perf_counter()
    done = "\n".join(f"{k + 1}. {s['do']} → {str(s['result'] or s['state'])[:100]}" for k, s in enumerate(steps))
    miss = str((analyst._ask(None, S_CHECK, f"질문: {question}\n단계별 답:\n{done}", CHECK_SCHEMA, max_tokens=120) or {}).get("missing") or "").strip()
    why = "빠진 요청 없음"
    add = None
    if miss:
        pq, pm = qparse.parse(question), qparse.parse(miss)
        same_q = set(pm.get("metric") or []) & set(pq.get("metric") or []) or set(qparse.find_places(miss)[0]) & set(qparse.find_places(question)[0])
        dup = any(set((tp.get("tuple") or {}).get("space") or []) == set(qparse.find_places(miss)[0]) and set((tp.get("tuple") or {}).get("metric") or []) & set(pm.get("metric") or [])
                  for tp in topics)
        dup = dup or any(miss.replace(" ", "") in s["do"].replace(" ", "") or s["do"].replace(" ", "") in miss.replace(" ", "") for s in steps)
        mp, mm = set(qparse.find_places(miss)[0]), set(pm.get("metric") or [])
        for st in steps:  # 이미 시도한 단계(실패·건너뜀 포함)와 동네·지표가 같으면 다시 하지 않는다('숙박 폐업률'을 다시 묻던 결함)
            for txt in (st["do"], st.get("asked") or ""):
                if txt and mm & set(qparse.parse(txt).get("metric") or []) and (not mp or mp <= set(qparse.find_places(txt)[0])):
                    dup = True
        fc = re.compile(r"예측|예상|전망")
        if dup and fc.search(miss) and fc.search(question) and not any(fc.search(f"{st['do']} {st.get('asked') or ''} {st.get('result') or ''}") for st in steps):
            dup = False  # 같은 지표라도 예측은 아직 답한 단계가 없으면 빠진 요청이다(2026-11-17 조정용 R076 '다음 달 방문객 예측')
            miss = re.sub(r"^.*?(하고|하며|한\s*뒤|한\s*다음),?\s*", "", miss)  # '추세선만 추출하고, 다음 달 …'에서 이미 한 앞부분을 뗀다
        if not (4 <= len(miss) <= 80):
            why = f"모델이 적은 빠진 요청이 너무 짧거나 길어 받지 않음: {miss[:40]}"
        elif not same_q:
            why = f"질문에 없는 동네·지표라 받지 않음: {miss[:60]}"
        elif dup:
            why = f"이미 답한 것과 같아 받지 않음: {miss[:60]}"
        else:
            add, why = miss, f"빠진 요청을 단계로 더함: {miss[:60]}"
    return add, {"step": 0, "tool": "self_check", "name": "자기 확인", "by": BY + (" + 코드 검사" if miss and not add else ""), "ok": True, "args": miss[:160],
                 "note": why, "sec": round(time.perf_counter() - t1, 2)}


def _words(t):
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]+", t or "") if len(w) >= 2}


def _overlap(q, question):
    a, b = _words(q), _words(question)
    return len(a & b) / len(a | b) if a and b else 0.0


def _like_whole(q, question):
    """하위 질문이 원래 질문 전체와 거의 같은지(낱말 겹침 0.7 이상)."""
    return _overlap(q, question) >= 0.7


SUMMARY_STEP = re.compile(r"(함께|같이|모아|종합|정리|한꺼번에)\s*(보여|정리|제시|알려|확인)")
DATA_ASK = re.compile(r"(자료|데이터)\S{0,3}\s*(뭐|무엇|어떤|있|어디|찾|목록)|어디서\s*(구|받|찾)")
DATA_LOC = re.compile(r"(의\s*)?(시계열\s*)?(데이터|자료)(를|는|은|가|의)?\s*(어디에?\s*있(나요|어요|는지)?|어떻게\s*(분포되어\s*)?(있나요|되나요)|확인(합니다|해\s*주세요|하고|해)?|조회(합니다|해)?)?\s*[?.]?")
PERIOD = re.compile(r"\d{4}\s*년(?:\s*\d{1,2}\s*월)?|작년(?:\s*\d{1,2}\s*월)?|올해|지난해|(?:최근|지난)\s*\d{1,2}\s*개월|요즘|요새|성수기|비수기")
MULTI_Q = re.compile(r"(하고|이고|한\s*뒤|한\s*후|한\s*다음|그\s*다음|다음에|이어서|이후|먼저|뽑고|찾고|보고|확인하고|조회하고|비교하고|파악하고|계산하고|살피고|분석하고|구하고|추려|그중|1위\s*(동네|업종)|함께|같이|까지|도\s*(알려|보여|분석|비교|확인))")


def _multi_ok(question):
    import plan_agent
    import split
    return bool(MULTI_Q.search(question) or plan_agent.multi(question) or len(split.pieces(question) or []) >= 2 or len(clauses(question)) >= 2)


# 원문 구절 나누기(2026-11-17 문제 기록 51번: 초보 말투 두 가지 질문에서 모델 계획이 낱말로 쪼개거나 뜻을 바꿈 → 코드가 원문 구절로 단계를 쓴다)
SENT_CUT = re.compile(r"(?<=[?？!])\s*|(?<=[가-힣][요줘])\.\s+")
CONJ = {"있고": "있어?", "없고": "없어?", "많고": "많아?", "적고": "적어?", "높고": "높아?", "낮고": "낮아?", "잘되고": "잘돼?", "되고": "돼?",
        "나오고": "나와?", "붐비고": "붐벼?", "생기고": "생겨?", "찾고": "찾아줘", "꼽아보고": "꼽아줘", "꼽고": "꼽아줘", "뽑고": "뽑아줘",
        "찾아서": "찾아줘", "골라서": "골라줘", "뽑아서": "뽑아줘",
        "버티고": "버텨?", "살아남고": "살아남아?", "열고": "열어?", "벌고": "벌어?", "늘고": "늘어?", "줄고": "줄어?",
        # 2026-11-17 새 문항 067 조정용: 기법을 시키고 이어서 다른 것을 묻는 연결('변이할당분석 해주고 매장 수도')
        "해주고": "해줘", "계산해주고": "계산해줘", "계산하고": "계산해줘", "분석해주고": "분석해줘", "분석하고": "분석해줘", "구해주고": "구해줘", "구하고": "구해줘",
        "보여주고": "보여줘", "알려주고": "알려줘", "진단해주고": "진단해줘", "얼마이고": "얼마야?"}
CONJ_CUT = re.compile(r"(" + "|".join(sorted(CONJ, key=len, reverse=True)) + r")\s+")
ASK_WORD = re.compile(r"포화|과밀|변이|입지|다양성|분해|상관|회귀|군집|클러스터|검정|이상치|분포|매출|폐업|개업|생존|방문|유동|점포|가게|매장|버스|손님|관광객|비중|순위|인구|장사|벌어|벌이|사람|붐비|붐벼|버티|버텨|살아남|문\s*(닫|여|연|열)|새로|생기|생긴|생겨"
                      r"|몇\s*(개|곳|군데)|얼마|닮|비슷|잘돼|잘되|오래|열어|여는|수는|비율|거기|그곳|그\s*동네|줄어|늘어|비\s*오|1등|1위|제일|가장|순위|\d+\s*년\s*(넘|이상)")
RANK_HEAD = re.compile(r"(1등|1위|제일|가장|최고)\S*\s*(\S+\s*){0,2}(동네|곳|데)|(닮|비슷)\S*\s*(동네|곳|데)")
REF_WORD = re.compile(r"거기|그곳|그\s*동네")
SIMILAR_STEP = re.compile(r"(닮|비슷|유사)\S*\s*(상권|동네|곳|지역|구조)")  # 비슷한 동네 찾기는 공개 자료로 답한다(53번, 조정용 R058이 센터 자료 찾기로 감)
TECH_NAME = re.compile(r"상관|군집|클러스터|회귀|검정|분해|이상치|이상값|입지\s*계수|특화\s*계수|생존\s*분석|생존\s*곡선|생존\s*함수|카플란|kaplan|수명표|변이\s*할당|shift.?share|"
                       r"다양성\s*지수|허핀달|HHI|엔트로피|분포|히스토그램|사분위|교차|CCF|STL|LQ|피어슨|스피어만|윌콕슨|wilcoxon|newey", re.I)
# 기법 이름(용어)만 모은 목록. techniques.TECH의 이름·전문 용어와 맞춘다(2026-11-17 실패 검토: '카플란-마이어'가 빠져 개업 수 답으로 가던 결함). 도민 말(같이 움직·끼리 묶)은 넣지 않는다(BG-033)  # 원문 구절 단계는 기법 이름이 있을 때만 통계 기법 도구(BG-033 '비슷한 동네 찾아줘'가 군집으로 가던 결함)
TECH_ONLY = re.compile(r"포화|과밀|레드\s*오션")


def _named_tech(step):
    """구절에 기법 이름(용어)이 있으면 그 기법 키(techniques.detect), 없으면 None. 도민 말(같이 움직·끼리 묶)만으로는 고르지 않는다."""
    import techniques as TT
    return TT.detect(step) if TECH_NAME.search(step or "") else None
TWORD = re.compile("|".join(sorted({"카페", "식당", "음식점", "횟집", "술집", "주점", "치킨집", "빵집", "편의점", "숙박", "한식", "일식", "중식", "양식", "분식", "외식"}, key=len, reverse=True)))


def _josa(w, a, b):
    c = (w or " ")[-1]
    return w + (a if "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 else b)


# 지표 묶음 나누기(2026-11-17 실패 검토 ①: '가게 수랑 5년 생존율'처럼 한 구절에 종류가 다른 지표 둘이 묶이면 한 단계로 처리돼 하나가 빠지던 결함)
MFAM = {"stores": r"점포\s*수|가게\s*수|매장\s*수|업소\s*수|몇\s*(개|곳|군데|집)|개수", "close": r"생존|버티|버텨|폐업|문\s*닫|살아남",
        "open": r"개업|새로\s*(생|문|연|여)", "visit": r"방문|유동|손님\s*수|사람|인구|붐비|발길", "sales": r"매출|장사|결제|벌이|벌어", "sat": r"포화"}
PAIR_CUT = re.compile(r"(?<=[가-힣])(이랑|랑|하고|이고|와|과|및)\s+")
REL_WORDS = re.compile(r"상관|관계|영향|회귀|비례|설명|탄력")  # 두 지표의 관계를 묻는 한 요청은 나누지 않는다('방문과 매출의 상관')
CMP_STRICT = re.compile(r"비교|vs|대비|차이|중에|보다|어디가|어느\s*쪽")  # qparse.COMPARE는 '하고·랑'까지 잡아 지표 묶음과 구분하지 못함


def _fams(t):
    return {k for k, rx in MFAM.items() if re.search(rx, t or "")}


def _split_pair(p):
    """한 구절의 'A(랑·하고·이고·와·과) B'에서 A와 B가 다른 지표 종류이고 B에 동네가 없으면 두 조각으로 나눈다(A에는 '알려줘'를 붙임)."""
    for m in PAIR_CUT.finditer(p):
        a, b = p[:m.start(1)], p[m.end():]
        fa, fb = _fams(a), _fams(b)
        if fa and fb and not (fa & fb) and not qparse.find_places(b)[0] and not CMP_STRICT.search(p) and not REL_WORDS.search(p):
            return [a.strip() + (" 알려줘" if not re.search(r"[?？요줘]$", a.strip()) else ""), b.strip()]
    return [p]


def clauses(question):
    """질문을 원문 구절 단계로 나눈다. 두 구절 이상이면 [{'do', 'uses_prev', 'orig'}], 아니면 [].
    뒤 구절에 동네가 없으면 앞 구절의 동네(둘 이상을 견주면 'A와 B 중 어디가')를, 업종이 없으면 앞 구절의 업종을 붙인다.
    앞 구절이 순위·비슷한 동네를 물었거나 뒤 구절에 '거기'가 있으면 앞 결과를 이어받는 단계로 표시한다."""
    q = re.sub(r"\s+", " ", question or "").strip()
    parts = []
    for sent in [x for x in SENT_CUT.split(q) if x and x.strip()]:
        last = 0
        for m in CONJ_CUT.finditer(sent):
            parts.append(sent[last:m.start(1)] + CONJ[m.group(1)])
            last = m.end()
        parts.append(sent[last:])
    parts = [x for p in parts if p.strip() for x in _split_pair(p.strip())]
    merged = []
    for p in parts:  # 묻는 말이 없는 조각('카페 하기 어디가 좋아?', '사람 많은 데로'의 앞)은 이웃 조각에 붙인다
        if merged and (not ASK_WORD.search(p) or not ASK_WORD.search(merged[-1])):
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    if len(merged) < 2:
        return []
    head = merged[0]
    hp = list(dict.fromkeys(d for w in head.split() for d in qparse.find_places(w)[0])) or qparse.find_places(head)[0]  # 질문에 적힌 순서
    surface = [w for w in head.split() if qparse.find_places(w)[0] and not re.search(r"(이랑|랑|하고|와|과)$", w)]
    named = list(dict.fromkeys(re.sub(r"(이랑|랑|하고|와|과|이나|나)$", "", w) for w in head.split() if qparse.find_places(w)[0]))
    cmp = hp if len(hp) >= 2 else named  # 두 지명이 같은 행정동이면(탑동·동문시장) 질문에 적힌 지명으로 견준다
    tw = TWORD.search(head)
    prev = bool(RANK_HEAD.search(head))
    out = [{"do": head, "uses_prev": False, "orig": True}]
    for p in merged[1:MAX_STEPS]:
        ref = bool(REF_WORD.search(p))
        pl = qparse.find_places(p)[0]
        has_place = bool(pl)
        pre = ""
        if len(pl) == 1 and hp and hp[0] not in pl and CMP_STRICT.search(p) and not ref:
            p = f"{_josa(hp[0], '과', '와')} {p}"  # 비교 단계에 동네가 하나뿐이면 앞 구절의 동네를 비교 상대로(실패 검토 ①)
        if not has_place and not ref:
            if prev:
                pre, ref = "거기 ", True
            elif len(cmp) >= 2 and qparse.COMPARE.search(head):
                pre = f"{_josa(cmp[0], '과', '와')} {cmp[1]} 중 " + ("" if re.search(r"어디|어느", p) else "어디가 ")
            elif surface:
                pre = surface[0] + " "
            elif hp:
                pre = hp[0] + " "
        if tw and not TWORD.search(p):
            pre += tw.group(0) + " "
        if ref and pre and REF_WORD.search(p):  # '거기 카페는' → 업종은 '거기' 뒤에
            p = REF_WORD.sub(lambda m: f"{m.group(0)} {pre.strip()}", p, count=1)
            pre = ""
        out.append({"do": (pre + p).strip(), "uses_prev": ref, "orig": True})
    return out


STEP_CLAUDE_MODEL = os.environ.get("JEJU_STEP_CLAUDE_MODEL", "claude-sonnet-5-5")


def _chat(staff=False):
    """단계별 도구 고르기 모델. Claude 키가 있고 심사용(담당자) 계정으로 로그인한 요청이면 Sonnet, 그 밖에는 7B
    (문제 기록 60번 A안, 마스터 2026-11-18 '실행 A안' · '가. 단 평가자만 사용가능해야함').
    근거: 조정용 130문항에서 정답 수는 7B와 같고(+1 −1) 문항당 시간 30~40% 짧음. JEJU_STEP_CLAUDE=off면 로그인해도 7B.
    Claude 호출이 실패하면 그 호출부터 이 질문이 끝날 때까지 7B로 돌아간다."""
    import expert
    local = expert._chat_fn("ollama")
    if not staff or not expert.claude_key() or os.environ.get("JEJU_STEP_CLAUDE", "on") == "off":
        return local
    import llm_claude
    state = {"claude": True}

    def chat(model, messages, tools):
        if state["claude"]:
            try:
                return llm_claude.chat(STEP_CLAUDE_MODEL, messages, tools, effort="low")
            except Exception:  # noqa: BLE001  키 오류·연결 끊김·한도 초과 등: 7B로
                state["claude"] = False
        return local(model, messages, tools)
    return chat


def _ask_step(args, s, facts, env, llm_on):
    """answer_question: 모델이 쓴 하위 질문 문장을 질문 담당 Agent(해석·보정·계산·검수)로 답한다. 앞 결과의 동네가 빠졌으면 채운다."""
    import question_agent
    q = str((args or {}).get("question") or s["do"]).strip()
    m = BIZ_ASK.search(s["do"]) if facts.get("biz") else None
    if m:  # 계획 단계가 '1순위 업종 점포 수'를 물으면 모델이 다시 쓴 문장 대신 앞 단계가 찾은 업종으로 묻는다(53번, 조정용 R075)
        q = BIZ_REF.sub(facts["biz"], m.group(0), count=1)
    if s["uses_prev"] and facts.get("dongs") and REF_WORD.search(q):  # '거기 카페는?' → 앞 결과 동네(비슷한 동네면 찾은 곳 모두)
        q = REF_WORD.sub("·".join(facts["dongs"][:5] if facts.get("similar") else facts["dongs"][:1]), q, count=1)
    places = qparse.find_places(q)[0]
    has_place = bool(places)
    ref = re.search(r"(1위|첫\s*번째|선정된|그|해당|위)\s*(동네|지역|곳)", s["do"])
    if s["uses_prev"] and facts.get("dongs") and ref and has_place and not set(places) & set(facts["dongs"]):
        q = s["do"].replace(ref.group(0), facts["dongs"][0])  # 모델이 앞 결과와 다른 동네를 적었으면 단계 문장의 '1위 동네'를 앞 결과로 바꾼다
        has_place = True
    elif s["uses_prev"] and facts.get("dongs") and (not has_place or PREV_WORDS.search(q)):
        dong = facts["dongs"][0]
        q = PREV_WORDS.sub("", q) if PREV_WORDS.search(q) else q
        q = f"{dong} {q.strip()}"
    elif not has_place and facts.get("space") and not re.search(r"제주\s*(도|전체|전역)|동네\s*(별|들)|순위|가장|제일|어디", q):
        q = f"{'·'.join(facts['space'][:2])} {q}"  # 단계 문장에 동네가 없으면 앞 단계의 동네를 이어받는다
    if re.search(r"[\u4e00-\u9fff]", q):  # 모델이 하위 질문을 한자(중국어)로 쓴 경우 계획 단계 문장을 쓴다(2026-11-17 조정용 R065)
        q = s["do"]
    if _like_whole(q, facts.get("q")) and not _like_whole(s["do"], facts.get("q")):  # 여러 단계 계획에서 하위 질문에 원래 질문 전체를 다시 적은 경우 계획 단계 문장으로(R054 1단계)
        q = s["do"]
    qp_all = qparse.find_places(facts.get("q") or "")[0]
    if len(qp_all) >= 2 and re.search(r"두\s*(동네|곳|지역)|둘|양쪽", q) and not set(qp_all) <= set(qparse.find_places(q)[0]):
        rest = re.sub(r"두\s*(동네|곳|지역)(의|를|을)?|둘|양쪽", "", q).strip()
        q = "·".join(qp_all[:2]) + " " + rest  # '두 동네'를 질문의 두 동네로
    plan_sp = [d for d in qparse.find_places(s["do"])[0] if d in qp_all]
    got = qparse.find_places(q)[0]
    if len(plan_sp) >= 2 and got and set(got) < set(plan_sp) and not (s["uses_prev"] and facts.get("dongs")):
        q = q.replace(got[0], "·".join(plan_sp), 1)  # 계획 단계의 두 동네 가운데 하나만 하위 질문에 적은 경우(R080 '삼도2동과 건입동의 매출' → '건입동의 매출')
    if plan_sp and got and not set(got) & set(plan_sp) and not s["uses_prev"]:  # 계획 단계에 적힌 질문 속 동네를 하위 질문에서 다른 동네로 바꿨으면 되돌린다(2026-11-17 조정용 R065 이호동 → 도두동)
        new = q
        for d in got:
            new = new.replace(d, plan_sp[0])
        q = new if new != q else f"{plan_sp[0]} {q}"
    if not DATA_ASK.search(facts.get("q") or "") and DATA_LOC.search(q):  # 원래 질문은 자료 위치를 묻지 않았는데 하위 질문을 '데이터는 어디에 있나요'로 바꿔 쓴 경우(R076·R080) 값을 묻는 문장으로
        q = DATA_LOC.sub(" ", q).strip(" ?.")
        c = q[-1:] or " "
        q += "은?" if "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 else "는?"
    allowed = set(qparse.find_places(facts.get("q") or "")[0]) | set(facts.get("dongs") or []) | set(facts.get("space") or [])
    allowed |= {d for h in facts.get("history") or [] for d in qparse.find_places(h.get("q") or "")[0]}
    qp = qparse.find_places(facts.get("q") or "")[0]
    foreign = [d for d in qparse.find_places(q)[0] if d not in allowed]
    if foreign and qp:  # 질문·앞 결과에 없는 동네를 모델이 적었으면 질문의 동네(앞 결과를 쓰는 단계는 앞 결과 동네)로 바꾼다(2026-11-16 조정용 R075·R078)
        to = facts["dongs"][0] if s["uses_prev"] and facts.get("dongs") else qp[0]
        for d in foreign:
            q = q.replace(d, to)
    if facts.get("biz") and BIZ_REF.search(q):  # ② 앞 단계 1위 업종을 '그 업종·1위 업종' 자리에 넣는다
        q = BIZ_REF.sub(facts["biz"], q, count=1)
    elif facts.get("biz") and BIZ_REF.search(s["do"]) and facts["biz"] not in q and not any(w in q for w in Q.TARGETS_BIZ):
        q = f"{facts['biz']} {q}"  # 모델이 업종을 빼고 적었으면 앞에 붙인다
    per = PERIOD.findall(facts.get("q") or "")
    miss = [w for w in dict.fromkeys(per) if w not in q]
    if miss:  # 원래 질문의 기간('2024년', '최근 3개월')이 하위 질문에서 빠졌으면 이어 붙인다
        q = f"{' '.join(miss)} {q}"
    out = question_agent.run(q, dict(env, _no_split=True), llm_on=llm_on)
    card = out.get("card") or {}
    ok = out.get("status") not in ("범위밖", "선택필요", "되묻기", "실패") and bool(card.get("evidence"))
    if ok and (out.get("tuple") or {}).get("type") == "T11" and not DATA_ASK.search(facts.get("q") or ""):
        return False, {"error": "원래 질문은 자료가 어디 있는지 묻지 않았어요. 이 단계에서 구할 값(동네·지표)을 묻는 하위 질문으로 다시 쓰세요."}, out, {"question": q}
    if not ok:
        return False, {"error": card.get("conclusion") or (out.get("choose") or {}).get("message") or "답을 만들지 못했어요"}, out, {"question": q}
    return True, {"conclusion": card.get("conclusion")}, out, {"question": q}


def serve_expert(question, staff=False):
    """상세 분석(로컬): 여러 일을 묻는 요청이면 단계형 Agent로 답하고(상세 분석 결과 모양), 아니면 None(분석 담당 Agent가 맡음)."""
    import analyst
    if not _multi_ok(question):
        return None
    t0 = time.perf_counter()
    plan = [s for s in ((analyst._ask(None, _plan_sys(question), question, PLAN_SCHEMA, max_tokens=400) or {}).get("steps") or []) if str(s.get("do", "")).strip()][:MAX_STEPS]
    if len(plan) <= 1:
        return None
    ptrace = {"step": 1, "tool": "plan", "name": "단계 나누기", "by": BY, "ok": True, "args": json.dumps([s.get("do") for s in plan], ensure_ascii=False)[:160],
              "note": f"{len(plan)}단계", "sec": round(time.perf_counter() - t0, 2)}
    r = _serve_steps(question, {}, False, lambda i, d: None, plan, ptrace, t0, staff=staff)
    return dict(r["agent"], backend="ollama", sec=r["sec"])


# ---------- 1번 문제 '도민 질문 경로가 Workflow다'의 남은 6가지(2026-11-16 마스터 '6가지 개선부터 우선 진행') ----------
# ① 비교·종합 도구 compare_steps: 앞 단계(·앞 대화) 결론의 숫자를 코드가 모아 큰 쪽·차이·배수를 한 줄로. 새로 계산하지 않는다.
# ② 업종 이어받기: 업종 순위 도구 rank_industries(동네 안 업종별 가게 수·카드 매출)의 1위 업종을 상태에 넣고 '그 업종·1위 업종'을 채운다.
# ③ 다시 계획: 단계가 실패·건너뜀으로 끝나고 남은 단계가 있으면 모델이 남은 단계를 한 번 다시 쓴다.
# ④ 마지막 자기 확인: 모델이 질문과 단계별 답을 보고 빠진 요청을 하위 질문 한 문장으로 적으면 단계를 하나 더한다(한 번).
# ⑤ 여러 단계 확인 카드: 모델이 '물은 일이 몇 가지인가'를 고른 확률이 낮으면 단계 목록을 보여 주고 멈춘다(답은 계산해 두고 가림).
# ⑥ 대화 맥락: 화면이 보낸 직전 질문·결론(최대 2개)을 '앞 대화'로 상태에 넣고, '그럼 애월읍은?' 같은 이어지는 질문은 앞 질문과 합친다.
NUM = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(조\s*[\d,]+억\s*원|억\s*원|만\s*원|원|명/일|명|곳|%p|%|지수|배|건)")
WHEN = re.compile(r"\d{4}년(?:\s*\d{1,2}월)?|최근\s*12개월|\d{4}-\d{2}")
COMPARE_WORDS = re.compile(r"비교|차이|더\s*(많|높|크|적|낮|작|나은|낫)|어디가|어느\s*(쪽|곳|동네)|견주|대비|몇\s*배|둘\s*중|두\s*곳\s*중|종합")
BIZ_RANK_WORDS = re.compile(r"업종")
BIZ_ASK = re.compile(r"(1위|1순위|첫\s*번째|그|해당)\s*업종\S*\s*(\S+\s*){0,1}(점포|가게|매장|업소)\s*수[^,.?]*")
BIZ_RANK_Q = re.compile(r"(가장|제일|어떤|어느|무슨|순위|1위|많은|높은|큰|강세|주력)")
BIZ_REF = re.compile(r"(1위|1순위|첫\s*번째|가장\s*\S+\s*|그|해당|선정된|위|앞\s*단계의?)\s*업종")
BIZ_ITEMS = ["카페", "한식", "일식", "횟집", "중식", "치킨", "분식", "주점", "편의점", "숙박"]  # 가게 수 순위: 답할 수 있는 업종(겹치는 큰 묶음 음식점·소매는 뺌)
BIZ5_TARGET = {"음식점업": "음식점", "소매업": "소매", "숙박업": "숙박"}
FOLLOW = re.compile(r"^(그럼|그러면|그리고|그건|아까|앞에서|방금|위에서)|(둘|두\s*곳|두\s*동네|두\s*업종)\s*중|어느\s*쪽")
PLAN_PAUSE = 0.5  # ⑤ '여러 가지를 물었을 확률'(1 − '한 가지' 확률)이 이보다 낮으면 멈춤. 조정용 047 100문항(2026-11-16): 여러 단계 30개 중앙값 0.996·0.5 미만 1개, 단일 70개 중앙값 0.434
ONE_STEP = "한 가지 질문으로 보고 답하기"
TOOL_COMPARE = {"type": "function", "function": {"name": "compare_steps", "description":
                "앞 단계(또는 앞 대화)의 결론 숫자를 모아 큰 쪽·차이·몇 배인지 한 줄로 낸다. 새로 계산하지 않는다. 비교·종합만 하는 단계에 쓴다.",
                "parameters": {"type": "object", "required": ["steps"], "properties": {"steps": {"type": "array", "items": {"type": "integer"},
                               "description": "비교할 단계 번호들(상태에 적힌 번호, 앞 대화는 '대화' 번호)"}}}}}
TOOL_BIZRANK = {"type": "function", "function": {"name": "rank_industries", "description":
                "한 동네 안에서 업종끼리 순위를 낸다(가게 수: 카페·한식·일식·횟집·중식·치킨·분식·주점·편의점·숙박 / 카드 매출: 대분류 5개). 1위 업종은 다음 단계가 이어받는다.",
                "parameters": {"type": "object", "required": ["dong", "by"], "properties": {"dong": {"type": "string"}, "by": {"type": "string", "enum": ["가게 수", "카드 매출"]}}}}}
S_REPLAN = ("너는 제주 상권 질문을 처리 단계로 나눈다. 앞 단계 하나가 실패하거나 넘어갔다. 질문, 끝난 단계의 결과, 실패 이유를 보고 남은 단계를 다시 쓴다. "
            "자료로 할 수 없는 일은 빼고, 실패한 단계를 다른 방법으로 할 수 있으면 넣는다. 남은 일이 없으면 빈 목록을 쓴다.")
REPLAN_SCHEMA = {"type": "object", "required": ["steps"], "properties": {"steps": {"type": "array", "minItems": 0, "maxItems": 3, "items": PLAN_SCHEMA["properties"]["steps"]["items"]}}}
S_CHECK = ("너는 답을 내기 전에 확인하는 Agent다. 질문과 단계별 답을 보고, 질문이 물었는데 아직 답하지 않은 것이 있으면 그것만 묻는 하위 질문 한 문장을 missing에 쓴다. "
           "모두 답했거나 자료로 할 수 없다고 밝혔으면 missing을 빈 문자열로 둔다. 질문에 없는 것을 더하지 않는다.")
CHECK_SCHEMA = {"type": "object", "required": ["missing"], "properties": {"missing": {"type": "string"}}}
S_COUNT = "너는 제주 상권 질문이 서로 다른 일을 몇 가지 물었는지 센다. 한 동네·한 지표의 값 하나를 물으면 1이다. n에 1~4 중 하나를 쓴다."
COUNT_SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "string", "enum": ["1", "2", "3", "4"]}}}


def values_of(text, label=""):
    """결론 문장의 첫 숫자를 (이름, 값, 단위, 기간)으로. 억·만 원은 원으로 바꾼다. 없으면 None."""
    m = NUM.search(text or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = re.sub(r"\s+", " ", m.group(2))
    if "조" in unit:
        jo = re.match(r"조\s*([\d,]+)억", unit.replace(" ", ""))
        v, unit = v * 1e12 + (float(jo.group(1).replace(",", "")) * 1e8 if jo else 0), "원"
    elif unit == "억 원":
        v, unit = v * 1e8, "원"
    elif unit == "만 원":
        v, unit = v * 1e4, "원"
    w = WHEN.search(text or "")
    return {"label": label, "value": v, "unit": unit, "when": w.group(0) if w else None}


def _fmt(v, unit):
    if unit == "원":
        import v3
        return v3.money(v)[0]
    return f"{v:,.1f}{unit}" if abs(v) < 100 and v != int(v) else f"{v:,.0f}{unit}"


def _label(out, step):
    t = (out or {}).get("tuple") or {}
    ws = ["·".join(t.get("space") or [])] + ([t["target"]] if t.get("target") else [])
    return " ".join(w for w in ws if w) or step[:20]


def _iga(w):
    """받침이 있으면 '이', 없으면 '가'(한글이 아닌 끝 글자는 '이(가)')."""
    c = (w or " ")[-1]
    if not ("가" <= c <= "힣"):
        return f"{w}이(가)"
    return w + ("이" if (ord(c) - 0xAC00) % 28 else "가")


def _ro(w):
    """'105억 원' → '105억 원으로', '21.5%' → '21.5%로'(받침이 ㄹ이거나 없으면 '로')."""
    c = (w or " ")[-1]
    if "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 not in (0, 8):
        return w + "으로"
    return w + "로"


def compare(items):
    """② 비교·종합(코드): items = values_of 결과 목록. (ok, 결론 문장)."""
    xs = [x for x in items if x]
    if len(xs) < 2:
        return False, "비교할 숫자가 있는 단계가 두 개 이상 필요해요. 숫자를 낸 단계 번호를 고르세요."
    units = {x["unit"] for x in xs}
    if len(units) > 1:
        return True, "단위가 달라(" + ", ".join(f"{x['label']} {_fmt(x['value'], x['unit'])}" for x in xs) + ") 크기를 견주지 않았어요."
    if len({x["label"] for x in xs}) < len(xs):  # 같은 대상끼리 비교하던 결함(2026-11-17 조정용 R065 '도두동 카페와(과) 도두동 카페')
        return False, "같은 동네·업종의 값끼리는 견줄 수 없어요. 서로 다른 대상을 답한 단계 번호를 고르세요."
    u = xs[0]["unit"]
    xs = sorted(xs, key=lambda x: -x["value"])
    a, b = xs[0], xs[1]
    diff = a["value"] - b["value"]
    if diff == 0:
        c = (a["label"] or " ")[-1]
        wa = ("과" if (ord(c) - 0xAC00) % 28 else "와") if "가" <= c <= "힣" else "와(과)"
        line = f"{a['label']}{wa} {b['label']} 모두 {_ro(_fmt(a['value'], u))} 같아요."
    elif u in ("%", "%p"):
        line = f"{_iga(a['label'])} {_ro(_fmt(a['value'], u))} {b['label']}({_fmt(b['value'], u)})보다 {diff:.1f}%p 높아요."
    else:
        times = f"({a['value'] / b['value']:.1f}배)" if b["value"] > 0 else ""
        line = f"{_iga(a['label'])} {_ro(_fmt(a['value'], u))} {b['label']}({_fmt(b['value'], u)})보다 {_fmt(diff, u)} 많아요{times}."
    if len(xs) > 2:
        line = "큰 순서: " + " > ".join(f"{x['label']} {_fmt(x['value'], u)}" for x in xs) + ". " + line
    whens = {x["when"] for x in xs if x["when"]}
    if len(whens) > 1:
        line += f" 기간이 달라요({', '.join(sorted(whens))}). 같은 기간으로 다시 물으면 정확해요."
    return True, line


def rank_industries(dong, by):
    """② 동네 안 업종 순위(코드). (ok, 결론, 1위 업종(질문에 쓸 수 있는 이름) 또는 None)."""
    import v3
    if dong not in Q.DONGS:
        return False, f"'{dong}'은(는) 행정동 이름이 아니에요. 행정동 이름으로 다시 부르세요.", None
    if by == "카드 매출":
        rows = [r for r in v3.biz_compare(dong)["rows"] if r.get("cur")]
        if not rows:
            return False, f"{dong} 업종별 카드 매출이 없어요.", None
        top = ", ".join(f"{k + 1}위 {r['biz']} {v3.money(r['cur'])[0]}" for k, r in enumerate(rows[:3]))
        return True, f"{dong} 업종별 카드 매출(최근 12개월, 대분류 5개) {top}이에요.", BIZ5_TARGET.get(rows[0]["biz"])
    rows = [r for r in v3.detail_compare(dong, [{"word": w} for w in BIZ_ITEMS])["rows"] if r["value"] > 0]
    if not rows:
        return False, f"{dong}에 셀 수 있는 업종 가게가 없어요.", None
    top = ", ".join(f"{k + 1}위 {r['word']} {r['value']:,}곳" for k, r in enumerate(rows[:3]))
    return True, f"{dong} 업종별 가게 수(상가 정보, 업종 {len(BIZ_ITEMS)}개 중) {top}이에요.", rows[0]["word"]


def merge_follow(question, history):
    """⑥ 이어지는 질문을 앞 질문과 합친다. 합칠 수 없으면 None. ('그럼 애월읍은?' + '노형동 카페 매출은?' → '애월읍 카페 매출은?')"""
    if not history or not FOLLOW.search(question or "") and len(question or "") > 14:
        return None
    last = history[-1]
    lq = str(last.get("question") or "")
    p = qparse.parse(question)
    places = qparse.find_places(question)[0]
    lplaces = qparse.find_places(lq)[0]
    body = re.sub(r"^(그럼|그러면|그리고|그건|아까|앞에서|방금|위에서)\s*", "", question).strip()
    if places and not p.get("metric") and lplaces and not COMPARE_WORDS.search(question):
        q = lq
        for k, d in enumerate(lplaces):
            q = q.replace(d, places[0] if k == 0 else "").strip()
        return re.sub(r"\s+", " ", q)
    if not places and p.get("metric") and (last.get("space") or lplaces):
        return f"{'·'.join((last.get('space') or lplaces)[:2])} {body}"
    return None
