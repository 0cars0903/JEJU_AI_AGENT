"""상세 분석: 도구 호출 루프(문서 26 안 A, 2026-11-14). 요청 → LLM이 도구를 골라 호출 → 코드가 검사·실행 → 답 제출 → 숫자 대조.

- 도구 5개(`prompts.AGENT_TOOLS`): describe_data, run_technique(기법 12종), run_python(격리 실행), search_center_catalog, submit_answer.
- 루프는 코드가 통제한다: 도구 호출 합계 MAX_STEPS(5)번, 시간 예산 BUDGET(90초, Vercel 상한 120초 안).
- 백엔드: Claude 키가 있으면 Claude(도구 5개). 없으면 로컬 Ollama `JEJU_AGENT_MODEL`(기본 qwen2.5:7b)이 설치돼 있을 때 도구 4개(run_python 제외).
  로컬 모델은 도구 선택 9/10이지만 스스로 끝내지 못해(문서 26 8절 측정), 분석 도구가 성공하면 코드가 루프를 끝낸다.
  도구를 고르지 못하면 규칙(`techniques.detect`)이 기법을 고른다.
- 해설 문장의 숫자는 실행 결과와 대조한다(`textcheck.check_numbers`). 어긋나면 해설을 버리고 숫자표만 보인다.
- 하루 요청 상한 `JEJU_EXPERT_DAILY`(기본 50, 아이디마다). 키 값은 출력하지 않는다.
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import datadict  # noqa: E402
import sandbox  # noqa: E402
from textcheck import check_numbers  # noqa: E402

DAILY = int(os.environ.get("JEJU_EXPERT_DAILY", "50"))
_count = {"day": None}  # 아이디별 오늘 요청 수(인스턴스 안에서만 셈)

import prompts as P  # noqa: E402
from prompts import EXPLAIN_SYSTEM, TOOL_EXPLAIN  # noqa: E402

MAX_STEPS = 5
REWRITES = 2  # 안 B: 답 숫자 대조 실패 시 다시 쓰기 상한
BUDGET = float(os.environ.get("JEJU_EXPERT_BUDGET", "90"))
AGENT_MODEL = os.environ.get("JEJU_AGENT_MODEL", "qwen2.5:7b")
_local = {"t": 0.0, "ok": False}


def claude_key():
    """Claude 키가 있고 막혀 있지 않은가(켤 수 있는가)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("LLM_BACKEND") not in ("rule", "ollama")


def claude_auto():
    """Claude를 자동으로 쓰는가. 기본은 '요청 단위'(JEJU_CLAUDE=request): 담당자가 [Claude로 분석]을 누른 요청에만 쓴다(2026-11-14 마스터 결정).
    JEJU_CLAUDE=auto면 키가 있을 때 계획 선택·넘김 판정·설명 문장·Agent에 자동으로 쓴다(예전 동작)."""
    return os.environ.get("JEJU_CLAUDE", "request") == "auto"


def _claude_on():
    return claude_key() and claude_auto()


def _local_on():
    """로컬 Agent 모델이 Ollama에 설치돼 있는가(60초 캐시). JEJU_LOCAL_AGENT=0이나 LLM_BACKEND=rule이면 끈다."""
    if os.environ.get("JEJU_LOCAL_AGENT") == "0" or os.environ.get("LLM_BACKEND") == "rule":
        return False
    if time.time() - _local["t"] < 60:
        return _local["ok"]
    import urllib.request
    import llm
    try:
        with urllib.request.urlopen(urllib.request.Request(llm.OLLAMA_URL.replace("/api/chat", "/api/tags"), headers=llm.ollama_headers()), timeout=llm.ping_timeout()) as r:
            names = {m["name"] for m in json.loads(r.read()).get("models", [])}
        ok = AGENT_MODEL in names or f"{AGENT_MODEL}:latest" in names
    except OSError:
        ok = False
    _local.update(t=time.time(), ok=ok)
    return ok


def backend():
    """'claude' | 'ollama' | None"""
    return "claude" if _claude_on() else ("ollama" if _local_on() else None)


def enabled():
    return backend() is not None


def _quota(user="local"):
    today = dt.date.today().isoformat()
    if _count.get("day") != today:
        _count.clear()
        _count["day"] = today
    n = _count.get(user, 0)
    if n >= DAILY:
        return False
    _count[user] = n + 1
    return True


def _chat_fn(name):
    if name == "claude":
        import llm_claude
        return llm_claude.chat
    import llm
    return lambda model, messages, tools: llm.chat(AGENT_MODEL, messages, tools, name="ollama", max_tokens=900)


def _call(messages, tool, chat=None):
    """도구 하나를 강제할 때(해설). 도구 호출 인자 dict와 원 응답 메시지, 사용량을 돌려준다."""
    chat = chat or _chat_fn("claude")
    r = chat(None, messages, [tool])
    msg = r["message"]
    args = next((c["function"]["arguments"] for c in msg.get("tool_calls") or [] if c["function"]["name"] == tool["function"]["name"]), None)
    if isinstance(args, str):
        args = json.loads(args)
    return args, msg, r.get("usage") or {}


def _why(e):
    name = type(e).__name__
    if "Authentication" in name or "401" in str(e):
        return "Claude API 키가 맞지 않아요(인증 실패). .env의 ANTHROPIC_API_KEY를 확인해 주세요."
    if "RateLimit" in name or "429" in str(e):
        return "Claude API 사용 한도에 닿았어요. 잠시 뒤 다시 시도해 주세요."
    return f"Claude 호출에 실패했어요({name})."


def _add_usage(total, u):
    for k in ("input_tokens", "output_tokens"):
        total[k] = total.get(k, 0) + int(u.get(k) or 0)


def _fallback_lines(result):
    nums = result.get("numbers") or {}
    lines = [f"{k}: {v}" for k, v in list(nums.items())[:8]]
    return lines + [f"주의: {n}" for n in (result.get("notes") or [])[:3]]


# ---------- 도구 ----------
def _describe(args):
    import datadict
    tabs = datadict.load_tables()
    name = (args.get("table") or "").strip()
    if not name or name not in datadict.DESC:
        rows = [{"table": n, "title": t, "rows": len(tabs[n])} for n, (t, _) in datadict.DESC.items()]
        return True, {"tables": rows, "note": "" if not name else f"'{name}' 표는 없어요. 위 목록에서 고르세요."}
    d = tabs[name]
    title, cols = datadict.DESC[name]
    head = json.loads(d.head(5).to_json(orient="records", force_ascii=False, date_format="iso"))
    return True, {"table": name, "title": title, "rows": len(d), "columns": cols, "head": head}


def _technique(question, args):
    import techniques
    tech = args.get("technique")
    if tech not in techniques.RUN:
        return False, {"error": f"없는 기법: {tech}"}, None
    named = techniques.detect(question)
    if named and named != tech:  # 질문에 적힌 기법과 다르면 코드가 되돌린다(자기 교정, 문서 26 8절 측정의 오선택 대응)
        return False, {"error": f"질문에는 '{techniques.TECH[named][0]}'이(가) 적혀 있어요. 기법을 다시 고르세요.", "hint": named}, None
    import qparse
    raw = []
    for d in args.get("dongs") or []:  # 생활 지명은 행정동으로 바꾼다('신제주' → 연동·노형동, 2026-11-16 마스터 Windows 시험)
        raw += qparse.MULTI_PLACES.get(d) or ([techniques.Q.DONG_ALIAS[d]] if d in techniques.Q.DONG_ALIAS else [d])
    bad = [d for d in raw if d and d not in techniques.Q.DONGS]
    dongs = list(dict.fromkeys(d for d in raw if d in techniques.Q.DONGS)) or None
    tgt = (args.get("target") or "").strip() or None
    bad_t = tgt if tgt and tgt not in techniques.Q.TARGETS_BIZ else None  # 목록 밖 업종은 빼고 알린다(2026-11-14: 없는 업종 이름을 붙여 답한 결함)
    slots = {"method": tech, "space": dongs, "target": None if bad_t else tgt, **{k: args[k] for k in ("k", "metrics") if k in args}}
    ans = techniques.answer(question, slots)
    steps = (ans.get("process") or {}).get("steps") or []
    if any(s.get("status") == "거부" for s in steps):
        return False, {"error": "적용 조건이 맞지 않아 계산하지 않았어요", "why": (ans.get("card") or {}).get("limits")}, ans
    card = ans.get("card") or {}
    if bad or bad_t:
        card["limits"] = (card.get("limits") or []) + ([f"동네 이름이 아니어서 뺐어요: {', '.join(bad)}"] if bad else []) \
            + ([f"'{bad_t}'은(는) 자료의 업종 목록에 없어 업종 구분 없이 계산했어요"] if bad_t else [])
        ans["card"] = card
    return True, {"technique": tech, "conclusion": card.get("conclusion"), "numbers": ans.get("numbers"),
                  "evidence": [e["text"] for e in card.get("evidence", [])][:6], "limits": card.get("limits")}, ans


def _catalog(args):
    kw = [w for w in str(args.get("keyword") or "").replace(",", " ").split() if w]
    items = json.loads((Path(__file__).resolve().parents[1] / "data" / "catalog.json").read_text())
    def score(c):
        text = " ".join(str(c.get(k) or "") for k in ("name", "domain", "columns", "space", "time", "category"))
        return sum(w in text for w in kw)
    hits = sorted((c for c in items if score(c) > 0), key=score, reverse=True)[:5]
    return True, {"found": [{k: c.get(k) for k in ("no", "name", "source", "space", "time", "period", "export")} for c in hits],
                  "note": "센터 자료는 센터 PC에서 조회한 CSV를 '센터 자료 넣기'로 넣으면 계산할 수 있어요." if hits else "찾지 못했어요. 다른 말로 찾아 보세요."}


def _topic(question, args):
    """answer_topic: 일반 경로를 지정한 질문 종류·칸으로 다시 부른다(LLM 없이, 넘김 없이). 숫자·검수·답 카드는 일반 경로 그대로."""
    import qparse
    import qtuple as Q
    import result
    import verify
    t = {"type": args.get("type"), "metric": [m for m in args.get("metric") or [] if m in Q.METRICS],
         "target": (args.get("target") or None), "space": [d for d in args.get("space") or [] if d in Q.DONGS],
         "time": None, "time_year": None, "breakdown": None, "cond": [], "form": "수치", "expect": "답함"}
    dropped = [d for d in args.get("space") or [] if d and d not in Q.DONGS]
    errs = verify.check_tuple(t)
    if errs:
        return False, {"error": "칸이 맞지 않아요: " + "; ".join(e.get("detail", "") for e in errs) + (f" (동네 이름이 아님: {dropped})" if dropped else "")}, None
    it = {"tuple": t, "card": qparse.card(t), "path": "Agent 지정", "confidence": None, "sec": 0.0}
    out = result.respond(question, {"_no_split": True}, llm_on=False, interpret=lambda q: it)  # 지정한 해석으로만 답한다(질문 나누기 끔)
    card = out.get("card") or {}
    if out.get("status") in ("범위밖", "선택필요") or not card.get("evidence"):
        return False, {"status": out.get("status"), "error": card.get("conclusion") or (out.get("choose") or {}).get("message") or "답을 만들지 못했어요"}, out
    return True, {"status": out.get("status"), "type": t["type"], "conclusion": card.get("conclusion"),
                  "evidence": [e["text"] for e in card.get("evidence", [])][:6], "limits": card.get("limits")}, out


def _views_to_series(ans):
    out = []
    for v in ((ans or {}).get("answer") or {}).get("views") or []:
        kind = v.get("kind") if v.get("kind") in ("line", "bar", "scatter") else None
        if not kind:
            continue
        for s in v.get("series") or []:
            pts = s.get("points") or []
            out.append({"title": v.get("label"), "kind": kind, "name": s.get("name"), "x": [p[0] for p in pts][:200], "y": [p[1] for p in pts][:200]})
    return out


def _short(args):
    a = dict(args or {})
    if "code" in a:
        a["code"] = f"({len(a['code'].splitlines())}줄)"
    return json.dumps(a, ensure_ascii=False)[:160]


TOOL_KO = {"describe_data": "자료 확인", "run_technique": "통계 기법 실행", "run_python": "코드 실행(격리)",
           "search_center_catalog": "센터 자료 찾기", "submit_answer": "답 제출"}


def ask(question, chat=None, user="local", mode="expert", use_claude=False):
    """상세 분석 한 번(도구 루프). use_claude: 담당자가 [Claude로 분석]을 누른 요청(키가 있을 때만).
    돌려주는 값: status, method, plan, code, result, lines, by, attempts, trace, backend, error, usage, sec."""
    t0 = time.perf_counter()
    name = "claude" if use_claude and claude_key() else backend()
    if name is None:
        return {"status": "꺼짐", "error": "Claude API 키나 로컬 분석 모델이 없어 상세 분석을 쓸 수 없어요. 기법 목록이나 일반 질문을 써 주세요."}
    if not _quota(user):
        return {"status": "상한", "error": f"오늘 상세 분석 요청 상한({DAILY}건)에 닿았어요."}
    if name == "ollama" and mode == "expert" and os.environ.get("JEJU_ANALYST") != "0":
        import step_agent  # 여러 일을 묻는 요청은 단계형 Agent(2026-11-16 마스터 '전체 서비스에 적용'), 기법 하나는 분석 담당 Agent
        multi = step_agent.serve_expert(question, staff=user not in (None, "local"))  # 로그인한 심사용 계정만 Claude
        if multi:
            return multi
        # 로컬 상세 분석은 단계형 분석 담당 Agent(app/analyst.py): 단계마다 모델이 판단하고 코드가 검사한다(2026-11-14 마스터 지시)
        import analyst
        return analyst.run(question, chat=chat)
    chat = chat or _chat_fn(name)
    local = name == "ollama"
    if mode == "escalate":  # 일반 경로가 처리하지 못해 넘어온 질문(중간안): 코드 실행 도구는 주지 않는다
        tools = [P.TOOL_TOPIC, P.TOOL_TECHNIQUE, P.TOOL_CATALOG, P.TOOL_SUBMIT] + ([] if local else [P.TOOL_DESCRIBE])
        system = P.ESCALATE_SYSTEM_LOCAL if local else P.ESCALATE_SYSTEM
    else:
        tools = P.AGENT_TOOLS_LOCAL if local else P.AGENT_TOOLS
        system = P.AGENT_SYSTEM_LOCAL if local else P.AGENT_SYSTEM + datadict.describe()
    allowed = {t["function"]["name"] for t in tools}
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    usage, trace, attempts = {}, [], []
    got = None  # {"kind", "result", "method", "plan", "code", "answer"}
    lines, nudged, calls, fails, rewrites = None, False, 0, 0, 0
    info = []  # 자료 확인·센터 자료 찾기 결과(정보 질문은 이것으로 답한다)
    topics = []  # answer_topic으로 만든 일반 답(넘김 모드)
    seen_calls = set()
    import techniques
    analysis_q = techniques.detect(question) is not None

    def run_tool(fn, args, by):
        nonlocal got
        t1 = time.perf_counter()
        ok, reply, extra = False, {}, None
        if fn == "describe_data":
            ok, reply = _describe(args)
            if ok:
                info.append(("describe", reply))
        elif fn == "run_technique":
            ok, reply, extra = _technique(question, args)
            if ok:
                import techniques
                got = {"kind": "technique", "method": techniques.TECH[args["technique"]][0] + " (정해진 기법 코드)",
                       "plan": None, "code": None, "answer": extra,
                       "result": {"numbers": extra.get("numbers") or {}, "notes": (extra.get("card") or {}).get("limits") or [],
                                  "tables": [], "series": _views_to_series(extra)}}
        elif fn == "run_python":
            out = sandbox.run(args.get("code") or "")
            attempts.append({"stage": out.get("stage"), "ok": out.get("ok"), "error": out.get("error")})
            ok = bool(out.get("ok"))
            if ok:
                res = out["result"]
                got = {"kind": "python", "method": args.get("method"), "plan": args.get("plan"), "code": args.get("code"), "result": res, "answer": None}
                reply = {"numbers": res.get("numbers"), "notes": res.get("notes"),
                         "tables": [{**t, "rows": t["rows"][:30]} for t in res.get("tables", [])],
                         "series": [{**x, "x": x["x"][:60], "y": x["y"][:60]} for x in res.get("series", [])]}
            else:
                reply = {"error": f"{out.get('stage')} 실패: {out.get('error')}. 규칙을 지켜 고친 코드를 다시 제출하세요."}
        elif fn == "answer_topic":
            ok, reply, extra = _topic(question, args)
            if ok:
                topics.append(extra)
                card = extra.get("card") or {}
                got = {"kind": "topic", "method": "일반 답 경로(" + ", ".join(str(x.get("process", {}).get("type") or "") for x in topics) + ")",
                       "plan": None, "code": None, "answer": {"topics": topics},
                       "result": {"numbers": {}, "notes": card.get("limits") or [], "tables": [], "series": []}}
        elif fn == "search_center_catalog":
            ok, reply = _catalog(args)
            if ok and reply.get("found"):
                info.append(("catalog", reply))
        trace.append({"step": len(trace) + 1, "tool": fn, "name": TOOL_KO.get(fn, fn), "by": by, "args": _short(args), "ok": ok,
                      "note": (reply.get("error") or reply.get("conclusion") or reply.get("note") or "")[:120] if isinstance(reply, dict) else "",
                      "sec": round(time.perf_counter() - t1, 2)})
        return ok, reply

    while calls < MAX_STEPS:
        if time.perf_counter() - t0 > BUDGET:
            trace.append({"step": len(trace) + 1, "tool": "-", "name": "시간 예산 초과", "by": "프로그램", "args": "", "ok": False,
                          "note": f"{BUDGET:.0f}초를 넘어 루프를 멈췄어요", "sec": 0})
            break
        try:
            r = chat(None, msgs, tools)
        except Exception as e:  # 키·네트워크 오류는 앱을 멈추지 않는다(키 값은 넣지 않음)
            if not trace:
                return {"status": "오류", "error": _why(e), "backend": name, "sec": round(time.perf_counter() - t0, 1)}
            attempts.append({"stage": "설계", "error": _why(e)})
            break
        _add_usage(usage, r.get("usage") or {})
        msg = r["message"]
        if not msg.get("tool_calls") and msg.get("content"):  # 소형 모델이 도구 호출을 본문 JSON으로 쓴 경우(2026-11-14 관찰)
            import re as _re
            m_ = _re.search(r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*\})\s*\}', msg["content"], _re.S)
            if m_ and m_.group(1) in allowed:
                try:
                    msg = {**msg, "tool_calls": [{"id": "text_call", "function": {"name": m_.group(1), "arguments": json.loads(m_.group(2))}}]}
                except ValueError:
                    pass
        tcs = [c for c in (msg.get("tool_calls") or []) if c.get("function", {}).get("name") in allowed]
        if not tcs:
            if got or (info and not analysis_q):
                break  # 결과가 있으면 코드가 끝낸다
            tech = techniques.detect(question)
            if (local or nudged) and tech:  # 도구를 고르지 못하면 규칙이 고른다
                run_tool("run_technique", {"technique": tech, "dongs": [], "target": ""}, "규칙(AI가 도구를 고르지 않음)")
                calls += 1
                break
            if nudged:
                said = (msg.get("content") or "").strip()
                attempts.append({"stage": "설계", "error": ("AI가 도구를 쓰지 않음: " + said[:300]) if said else "도구 호출을 받지 못함"})
                break
            nudged = True
            msgs += [msg, {"role": "user", "content": "도구를 하나 골라 호출하세요."}]
            continue
        msgs.append(msg)
        done, repeated = False, False
        for i, c in enumerate(tcs):
            fn = c["function"]["name"]
            args = c["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            cid = c.get("id") or f"call_{i}"
            sig = fn + json.dumps(args, ensure_ascii=False, sort_keys=True)
            if sig in seen_calls and got:
                repeated = True
                msgs.append({"role": "tool", "tool_call_id": cid, "content": "이미 같은 도구를 같은 인자로 실행했어요."})
                continue
            seen_calls.add(sig)
            calls += 1
            if fn == "submit_answer":
                if got or info:
                    cand = [str(x) for x in args.get("lines") or []]
                    src = [(got or {}).get("result") or {}, (got or {}).get("answer") or {}] + [r_ for _, r_ in info] + [{"q": question, "dict": datadict.describe()}]
                    bad = check_numbers("\n".join(cand), src) if cand else ["빈 답"]
                    if bad and rewrites < REWRITES:  # 안 B: 결과에 없는 숫자면 되돌려 다시 쓰게 한다
                        rewrites += 1
                        note = f"결과에 없는 숫자 {bad[:5]} → 다시 쓰기 {rewrites}/{REWRITES}"
                        trace.append({"step": len(trace) + 1, "tool": fn, "name": TOOL_KO[fn], "by": "AI", "args": f"{len(cand)}문장", "ok": False, "note": note, "sec": 0})
                        msgs.append({"role": "tool", "tool_call_id": cid, "content": f"숫자 대조 실패: 도구 결과에 없는 숫자 {bad[:5]}. 도구 결과에 있는 값만 그대로 써서 submit_answer로 다시 제출하세요."})
                        continue
                    lines = cand
                    trace.append({"step": len(trace) + 1, "tool": fn, "name": TOOL_KO[fn], "by": "AI", "args": f"{len(lines)}문장", "ok": not bad, "note": "" if not bad else f"결과에 없는 숫자 {bad[:5]}", "sec": 0})
                    msgs.append({"role": "tool", "tool_call_id": cid, "content": "받았어요."})
                    done = True
                    continue
                reply, ok = {"error": "아직 분석 결과가 없어요. run_technique나 run_python을 먼저 실행하세요."}, False
                trace.append({"step": len(trace) + 1, "tool": fn, "name": TOOL_KO[fn], "by": "AI", "args": "", "ok": False, "note": reply["error"], "sec": 0})
            else:
                ok, reply = run_tool(fn, args, "AI")
                fails = 0 if ok else fails + 1
            msgs.append({"role": "tool", "tool_call_id": cid, "content": json.dumps(reply, ensure_ascii=False, default=str)[:6000]})
        if done or (local and got and mode != "escalate"):  # 로컬 모델은 스스로 끝내지 못해 분석이 성공하면 코드가 끝낸다(넘김 모드는 여러 하위 질문을 위해 계속)
            break
        if repeated:  # 같은 도구·인자를 되풀이하면 더 할 일이 없다고 보고 끝낸다
            break
        if local and info and not analysis_q:  # 정보 질문(기법 이름 없음)은 찾은 정보로 끝낸다
            break
        if local and fails >= 2 and analysis_q and calls < MAX_STEPS:  # 로컬 모델이 두 번 연속 실패하면 규칙이 고른다
            run_tool("run_technique", {"technique": techniques.detect(question), "dongs": [], "target": ""}, "규칙(AI가 두 번 실패)")
            calls += 1
            break

    base = {"backend": name, "trace": trace, "attempts": attempts, "usage": usage,
            "method": (got or {}).get("method"), "plan": (got or {}).get("plan") or [f"{t['step']}. {t['name']}" + (f" — {t['note']}" if t["note"] else "") for t in trace],
            "code": (got or {}).get("code")}
    if not got and info:
        kind, rep = info[-1]
        if kind == "catalog":
            rows = [[c.get("no"), c.get("name"), c.get("space"), c.get("time"), c.get("period"), c.get("export")] for c in rep["found"]]
            res = {"numbers": {}, "notes": [rep["note"]], "series": [],
                   "tables": [{"title": "센터 자료 찾기 결과", "columns": ["번호", "자료", "공간 단위", "시간 단위", "기간", "반출"], "rows": rows}]}
            auto = [f"센터 자료 목록에서 {len(rows)}건을 찾았어요."] + [f"{r[0]} {r[1]}: {r[2]}·{r[3]} 단위" + (f", {r[4]}" if r[4] else "") for r in rows[:3]] \
                + ["센터에서 조회한 CSV를 '센터 자료 넣기'로 넣으면 이 자료로 계산할 수 있어요."]
        else:
            cols = rep.get("columns") or {}
            res = {"numbers": {"행 수": rep.get("rows", 0)} if rep.get("table") else {}, "notes": [rep["note"]] if rep.get("note") else [], "series": [],
                   "tables": [{"title": rep.get("title") or "표 목록", "columns": ["열", "설명"], "rows": [[k, v] for k, v in cols.items()]}] if cols else
                             [{"title": "쓸 수 있는 표", "columns": ["표", "내용", "행 수"], "rows": [[t["table"], t["title"], t["rows"]] for t in rep.get("tables", [])]}]}
            auto = [f"{rep.get('table')} 표는 {rep.get('title')}이고 열은 {len(cols)}개예요."] if cols else ["쓸 수 있는 표 목록이에요."]
        out_lines = lines if lines and not check_numbers("\n".join(lines), [res, rep, {"q": question}]) else auto
        return {**base, "status": "성공", "method": "자료 안내", "result": res, "lines": out_lines,
                "by": "AI" if out_lines is lines else "프로그램(찾은 정보의 문장)", "sec": round(time.perf_counter() - t0, 1)}
    if not got:
        return {**base, "status": "실패", "sec": round(time.perf_counter() - t0, 1),
                "error": (attempts[-1].get("error") if attempts else None) or next((t["note"] for t in reversed(trace) if not t["ok"] and t["note"]), None) or "분석 결과를 받지 못했어요",
                "hint": "기법 목록(상관·군집·시계열 분해·회귀·두 집단 검정·분포·이상치)이나 일반 질문으로 다시 물어 주세요."}
    result = got["result"]
    allowed_src = [result, got.get("answer") or {}, {"q": question, "dict": datadict.describe()}]
    by = "AI"
    if lines is None:  # 답을 제출하지 않았으면(로컬·루프 상한) 해설을 따로 받거나 기법 문장을 쓴다
        if got["kind"] == "topic":
            lines, by = [], "프로그램(일반 답 카드의 문장)"
            for x in topics:
                c = x.get("card") or {}
                lines += [c.get("conclusion") or ""] + [e["text"] for e in c.get("evidence", [])][:2]
        elif got["kind"] == "technique":
            card = (got.get("answer") or {}).get("card") or {}
            lines, by = [card.get("conclusion") or ""] + [e["text"] for e in card.get("evidence", [])][:4], "프로그램(기법 코드의 문장)"
            if mode == "escalate" and not analysis_q:  # 기법을 묻지 않은 질문에 기법으로 답했으면 근사 답이라고 밝힌다
                lines = ["질문한 분석을 그대로 할 자료가 없어, 가장 가까운 분석을 보여 드려요."] + lines
        elif not local:
            view = {"numbers": result.get("numbers"), "notes": result.get("notes")}
            try:
                ex, _, u = _call([{"role": "system", "content": EXPLAIN_SYSTEM},
                                  {"role": "user", "content": f"요청: {question}\n기법: {base['method']}\n실행 결과: {json.dumps(view, ensure_ascii=False)}"}], TOOL_EXPLAIN, chat)
                _add_usage(usage, u)
                lines = [str(x) for x in (ex or {}).get("lines") or []]
            except Exception as e:
                attempts.append({"stage": "해설", "error": f"{type(e).__name__}"})
    bad = check_numbers("\n".join(lines or []), allowed_src) if lines else ["해설 없음"]
    if bad and by == "AI":
        attempts.append({"stage": "숫자 대조", "ok": False, "error": f"결과에 없는 숫자 {bad[:5]}"})
        lines, by = _fallback_lines(result), "프로그램(해설 숫자 불일치로 대체)"
    return {**base, "status": "성공", "result": result, "lines": lines, "by": by, "topics": topics or None, "sec": round(time.perf_counter() - t0, 1)}
