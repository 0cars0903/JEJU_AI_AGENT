"""로컬 분석 담당 Agent(2026-11-14 마스터 지시: '사람이 하던 일을 Agent가 수행', 로컬 모델 역할 확장).

센터 분석 담당자가 요청을 처리하는 순서를 단계로 나누고, 단계마다 로컬 소형 모델(qwen2.5:7b)이 한 번씩 판단한다.
소형 모델은 한 번에 끝나는 판단은 하지만 결과를 보고 다음 도구를 이어 부르는 일에서 무너지므로(여러 단계 1/40),
단계 순서는 코드가 쥐고 각 단계의 판단만 모델에 맡긴다. 코드는 판단을 검사하고 숫자를 계산한다.

| 단계 | 모델이 판단 | 코드가 검사·실행 |
| ① 요청 이해 | 요청의 뜻으로 기법(12종)·자료 찾기·일반 질문 중 하나와 동네·업종을 고르고 이유를 적음. 기법 이름이 적혀 있어도 모델이 판단 | 요청에 적힌 기법 이름과 다르면 한 번 되묻고, 그래도 다르면 적힌 기법으로 바로잡음(기록). 목록 밖 동네·업종은 뺌 |
| ② 적용 조건 | 조건이 안 맞아 계산하지 않았으면, 이유를 보고 대신 할 기법을 목록에서 고름 | 조건 검사(techniques의 거부 규칙) |
| ③ 실행 | - | 정해진 기법 코드로 계산 |
| ④ 해석 | 결과의 뜻을 도민 말로 2~3문장. 숫자를 쓰지 않음 | 숫자가 들어 있거나, 결과에 없는 동네를 쓰면 버리고 기법 코드 문장을 씀 |
| ⑤ 다음 분석 | 이어서 볼 기법 1~2개와 이유 | 목록 밖이면 버림 |
"""
import json
import re
import time

import qtuple as Q
import techniques as T

TECHS = list(T.TECH)
KINDS = TECHS + ["catalog", "general"]
TECH_GUIDE = "\n".join(f"- {k}: {T.TECH[k][0]}" for k in TECHS)
BY = "AI(로컬 모델)"

S_UNDERSTAND = ("너는 제주빅데이터센터의 상권 분석 담당자다. 도민이나 담당자의 요청을 읽고 어떤 분석이 맞는지 판단한다. "
                "기법 이름이 적혀 있어도 요청의 뜻이 그 기법과 맞는지 스스로 판단한다. 고르는 기준:\n"
                "- corr: 두 지표가 같이 움직이는 정도(관계의 세기만)\n- regress: 여러 요인이 매출을 얼마나 설명하는지(영향·설명력)\n"
                "- cluster: 동네를 비슷한 무리로 묶기\n- decomp: 한 곳의 월별 값에서 계절 몫과 긴 흐름 떼어 내기\n"
                "- test: 두 동네·두 집단의 값이 정말 다른지\n- dist: 여러 동네 값이 어떻게 퍼져 있는지(구간·치우침·상위 몇 %)\n"
                "- outlier: 평소와 다르게 튀거나 떨어진 달 찾기\n- change: 매출 변화를 결제 건수와 건당 금액(손님 수와 한 번에 쓰는 돈)으로 나누기\n"
                "- lq: 한 동네에 제주 전체보다 많이 몰린(특화·과밀) 업종, 업종 비중 견주기\n- surv: 개업 뒤 몇 년 살아남는지(생존 곡선)\n"
                "- hhi: 한 동네 안에 업종이 고르게 섞였는지(다양성 점수)\n- shift: 매출 변화를 제주 전체 성장·업종 구성·동네 고유 효과로 나누기\n"
                "- catalog: 센터에 어떤 자료가 있는지 찾는 요청\n- general: 통계 기법이 필요 없는 일반 질문(가게 수, 두 동네 비교, 순위, 추세 등)\n"
                "동네는 제주 행정동·읍면 이름, 업종은 음식점·카페·한식 같은 말을 질문에서 그대로 옮긴다. 이유는 한 문장, 숫자 없이 쓴다.")
F_UNDERSTAND = {"type": "object", "required": ["kind", "dongs", "target", "keyword", "reason"], "properties": {
    "kind": {"type": "string", "enum": KINDS}, "dongs": {"type": "array", "items": {"type": "string"}},
    "target": {"type": "string"}, "keyword": {"type": "string"}, "reason": {"type": "string"}}}
S_ALT = ("너는 상권 분석 담당자다. 고른 기법이 자료 조건에 맞지 않아 계산하지 않았다. 이유를 읽고, 요청에 가장 가깝게 답할 수 있는 다른 기법을 하나 고른다. "
         "맞는 기법이 없으면 general을 고른다. 이유는 한 문장.\n" + TECH_GUIDE)
F_ALT = {"type": "object", "required": ["kind", "reason"], "properties": {"kind": {"type": "string", "enum": TECHS + ["general"]}, "reason": {"type": "string"}}}
S_EXPLAIN = ("너는 상권 분석 담당자다. 분석 결과를 IT 비전문가 도민이 이해할 말로 2~3문장 설명한다. 규칙: 숫자를 쓰지 않는다(숫자는 화면 표에 있다). "
             "결과에 나온 동네 이름만 쓴다. 원인을 단정하지 않는다(~일 수 있어요). 해요체로 쓴다.")
F_EXPLAIN = {"type": "object", "required": ["lines"], "properties": {"lines": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}
S_NEXT = ("너는 상권 분석 담당자다. 방금 한 분석에 이어 도민에게 도움이 될 다음 분석을 목록에서 1~2개 고르고 이유를 한 문장으로 쓴다. 방금 한 기법은 고르지 않는다.\n" + TECH_GUIDE)
F_NEXT = {"type": "object", "required": ["next", "reason"], "properties": {"next": {"type": "array", "items": {"type": "string", "enum": TECHS}, "maxItems": 2},
                                                                          "reason": {"type": "string"}}}
DIGIT = re.compile(r"\d")


def _ask(chat, system, user, schema, max_tokens=300):
    """모델 호출 1회(JSON 형식 고정). chat이 있으면(시험) chat(None, msgs, [])의 본문 JSON을 읽는다."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if chat:
        m = chat(None, msgs, [])["message"]
    else:
        import expert
        import llm
        m = llm.chat(expert.AGENT_MODEL, msgs, [], name="ollama", max_tokens=max_tokens, fmt=schema)["message"]
    try:
        return json.loads(m.get("content") or "{}")
    except ValueError:
        return {}


def understand(question, chat=None, checks=True):
    """① 요청 이해. 돌려주는 값: (판단 dict, 기록 목록). checks=False면 코드 검사 없이 모델 판단 그대로(측정용)."""
    log = []
    t0 = time.perf_counter()
    a = _ask(chat, S_UNDERSTAND, question, F_UNDERSTAND)
    kind = a.get("kind") if a.get("kind") in KINDS else "general"
    log.append({"tool": "understand", "name": "요청 이해(기법 고르기)", "by": BY, "ok": a.get("kind") in KINDS,
                "args": json.dumps({k: a.get(k) for k in ("kind", "dongs", "target")}, ensure_ascii=False),
                "note": str(a.get("reason") or "")[:120], "sec": round(time.perf_counter() - t0, 2)})
    if checks:
        named = T.detect(question)
        if named and kind != named:  # 요청에 적힌 기법 이름과 다르면 한 번 되묻는다
            t1 = time.perf_counter()
            again = _ask(chat, S_UNDERSTAND, f"{question}\n(검사 메모: 요청에 '{T.TECH[named][0]}'이라는 말이 있어요. 요청의 뜻이 그 기법과 맞는지 다시 판단하세요.)", F_UNDERSTAND)
            k2 = again.get("kind") if again.get("kind") in KINDS else kind
            fixed = k2 != named
            log.append({"tool": "understand", "name": "요청 이해(다시 판단)", "by": BY, "ok": True, "args": json.dumps({"kind": k2}, ensure_ascii=False),
                        "note": str(again.get("reason") or "")[:120], "sec": round(time.perf_counter() - t1, 2)})
            if fixed:  # 그래도 다르면 적힌 기법으로 바로잡는다(코드 검사)
                log.append({"tool": "check", "name": "코드 검사", "by": "코드", "ok": True, "args": "",
                            "note": f"요청에 적힌 '{T.TECH[named][0]}'(으)로 바로잡음", "sec": 0.0})
                k2 = named
            kind, a = k2, {**a, **{k: v for k, v in again.items() if k in ("dongs", "target", "keyword") and v}}
    dongs = [d for d in (a.get("dongs") or []) if d in Q.DONGS]
    target = (a.get("target") or "").strip()
    target = target if target in Q.TARGETS_BIZ else ""
    if checks:
        p = T.parse(question)
        if not dongs and p["dongs"]:  # 모델이 동네를 옮기지 못했으면 사전으로 채운다
            dongs = p["dongs"]
            log.append({"tool": "check", "name": "코드 검사", "by": "코드", "ok": True, "args": "", "note": f"동네를 질문에서 채움: {', '.join(dongs)}", "sec": 0.0})
        if not target and p["target"]:
            target = p["target"]
    return {"kind": kind, "dongs": dongs, "target": target, "keyword": a.get("keyword") or "", "reason": a.get("reason") or ""}, log


def _explain_ok(lines, allowed_dongs):
    if not lines or any(DIGIT.search(x) for x in lines):
        return False
    used = {d for d in Q.DONGS for x in lines if d in x}
    return used <= set(allowed_dongs)


def run(question, chat=None, checks=True):
    """로컬 분석 담당 Agent 한 번. expert.ask와 같은 모양(status, method, result, lines, by, trace, plan, backend, sec)을 돌려준다."""
    import expert
    t0 = time.perf_counter()
    trace = []

    def add(entries):
        for e in entries:
            trace.append({"step": len(trace) + 1, **e})

    u, log = understand(question, chat, checks)
    add(log)
    kind, ans, method = u["kind"], None, None
    if kind == "catalog":
        ok, rep = expert._catalog({"keyword": u["keyword"] or question})
        add([{"tool": "search_center_catalog", "name": "센터 자료 찾기", "by": "코드", "ok": ok and bool(rep.get("found")), "args": u["keyword"], "note": rep.get("note", "")[:120], "sec": 0.0}])
        rows = [[c.get("no"), c.get("name"), c.get("space"), c.get("time"), c.get("period"), c.get("export")] for c in rep.get("found") or []]
        lines = [f"센터 자료 목록에서 {len(rows)}건을 찾았어요."] + [f"{r[0]} {r[1]}: {r[2]}·{r[3]} 단위" for r in rows[:3]] + [rep.get("note", "")]
        return {"status": "성공" if rows else "실패", "method": "센터 자료 찾기", "backend": "ollama", "trace": trace, "plan": _plan(trace), "code": None,
                "result": {"numbers": {}, "notes": [], "series": [], "tables": [{"title": "센터 자료 찾기 결과", "columns": ["번호", "자료", "공간 단위", "시간 단위", "기간", "반출"], "rows": rows}]},
                "lines": [x for x in lines if x], "by": "프로그램(찾은 정보)", "error": None if rows else "찾지 못했어요.", "sec": round(time.perf_counter() - t0, 1)}
    if kind in TECHS:
        ok, rep, ans = expert._technique(question, {"technique": kind, "dongs": u["dongs"], "target": u["target"]})
        if not ok and "질문에는" in str(rep.get("error")) and rep.get("hint"):  # expert._technique의 이름 대조(checks와 같은 검사)
            kind = rep["hint"]
            ok, rep, ans = expert._technique(question, {"technique": kind, "dongs": u["dongs"], "target": u["target"]})
        add([{"tool": "run_technique", "name": f"{T.TECH[kind][0]} 계산", "by": "코드", "ok": ok, "args": json.dumps({"technique": kind, "dongs": u["dongs"], "target": u["target"]}, ensure_ascii=False),
              "note": (rep.get("error") or rep.get("conclusion") or "")[:120], "sec": 0.0}])
        if not ok:  # ② 적용 조건이 안 맞으면 모델이 대안을 고른다
            t1 = time.perf_counter()
            why = "; ".join(map(str, rep.get("why") or [rep.get("error")]))
            alt = _ask(chat, S_ALT, f"요청: {question}\n고른 기법: {T.TECH[kind][0]}\n계산하지 않은 이유: {why}", F_ALT)
            k2 = alt.get("kind") if alt.get("kind") in TECHS + ["general"] else "general"
            add([{"tool": "alternative", "name": "대안 고르기", "by": BY, "ok": True, "args": k2, "note": str(alt.get("reason") or "")[:120], "sec": round(time.perf_counter() - t1, 2)}])
            if k2 in TECHS and k2 != kind:
                kind = k2
                ok, rep, ans = expert._technique(question, {"technique": kind, "dongs": u["dongs"], "target": u["target"]})
                add([{"tool": "run_technique", "name": f"{T.TECH[kind][0]} 계산", "by": "코드", "ok": ok, "args": kind, "note": (rep.get("error") or rep.get("conclusion") or "")[:120], "sec": 0.0}])
            else:
                kind = "general"
            if not ok and kind != "general":
                kind = "general"
        method = f"{T.TECH[kind][0]} (정해진 기법 코드)" if kind in TECHS else None
    if kind == "general":  # 일반 질문: 일반 경로(정해진 계산)로 답한다
        import result
        out = result.respond(question, {"_no_split": False}, llm_on=False)
        card = out.get("card") or {}
        ok = bool(card.get("evidence"))
        add([{"tool": "answer_topic", "name": "일반 답(정해진 계산)", "by": "코드", "ok": ok, "args": "", "note": (card.get("conclusion") or "")[:120], "sec": 0.0}])
        lines = [card.get("conclusion") or "답을 만들지 못했어요."] + [e["text"] for e in card.get("evidence", [])][:3]
        return {"status": "성공" if ok else "실패", "method": "일반 답 경로", "backend": "ollama", "trace": trace, "plan": _plan(trace), "code": None,
                "result": {"numbers": {}, "notes": card.get("limits") or [], "series": [], "tables": []}, "lines": lines, "by": "프로그램(일반 답 카드의 문장)",
                "topics": [out], "error": None if ok else card.get("conclusion"), "sec": round(time.perf_counter() - t0, 1)}
    card = (ans or {}).get("card") or {}
    numbers = (ans or {}).get("numbers") or {}
    # ④ 해석: 숫자 없는 도민 말(모델) + 숫자 문장(코드)
    t1 = time.perf_counter()
    ex = _ask(chat, S_EXPLAIN, f"요청: {question}\n기법: {T.TECH[kind][0]}\n결과 요약: {card.get('conclusion')}\n주의: {'; '.join(card.get('limits') or [])[:300]}", F_EXPLAIN)
    allowed = [d for d in Q.DONGS if d in (card.get("conclusion") or "") or d in u["dongs"]]
    ex_lines = [str(x).strip() for x in ex.get("lines") or [] if str(x).strip()]
    good = _explain_ok(ex_lines, allowed)
    add([{"tool": "explain", "name": "결과 해석(도민 말)", "by": BY, "ok": good, "args": "", "note": "" if good else "숫자나 결과에 없는 동네가 있어 기법 코드 문장으로 바꿈", "sec": round(time.perf_counter() - t1, 2)}])
    lines = [card.get("conclusion") or ""] + (ex_lines if good else [e["text"] for e in card.get("evidence", [])][:3])
    # ⑤ 다음 분석 제안
    t1 = time.perf_counter()
    nx = _ask(chat, S_NEXT, f"요청: {question}\n방금 한 기법: {T.TECH[kind][0]}\n결과 요약: {card.get('conclusion')}", F_NEXT)
    nexts = [k for k in nx.get("next") or [] if k in TECHS and k != kind][:2]
    add([{"tool": "suggest", "name": "다음 분석 제안", "by": BY, "ok": bool(nexts), "args": ",".join(nexts), "note": str(nx.get("reason") or "")[:120], "sec": round(time.perf_counter() - t1, 2)}])
    if nexts:
        lines.append("다음으로 볼 만한 분석: " + ", ".join(T.TECH[k][0] for k in nexts) + (f" — {nx.get('reason')}" if nx.get("reason") and not DIGIT.search(str(nx.get('reason'))) else ""))
    return {"status": "성공", "method": method, "backend": "ollama", "trace": trace, "plan": _plan(trace), "code": None,
            "result": {"numbers": numbers, "notes": card.get("limits") or [], "tables": [], "series": expert._views_to_series(ans)},
            "lines": [x for x in lines if x], "by": "AI(로컬 모델: 기법 선택·해석·다음 분석) + 프로그램(숫자)", "next": nexts, "sec": round(time.perf_counter() - t0, 1)}


def _plan(trace):
    return [f"{t['step']}. {t['name']}" + (f" — {t['note']}" if t.get("note") else "") for t in trace]
