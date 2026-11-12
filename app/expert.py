"""전문가 모드(설계 11-2절, 2026-11-13): 요청 → Claude가 계획·pandas 코드 설계 → 검사·격리 실행 → 해설 → 숫자 대조.

- Claude 키가 있을 때만 켠다(`enabled()`). 로컬 Ollama 경로는 쓰지 않는다(소형 모델은 코드 품질이 낮다고 봄 [추정]).
- 고치기는 1번만: 검사·실행 오류를 Claude에 되돌려 한 번 고치게 한다. 다시 실패하면 이유와 기법 목록 안내를 돌려준다.
- 해설 문장의 숫자는 실행 결과와 대조한다(`textcheck.check_numbers`). 어긋나면 해설을 버리고 숫자표만 보인다.
- 하루 요청 상한 `JEJU_EXPERT_DAILY`(기본 50). 키 값은 출력하지 않는다.
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
_count = {"day": None, "n": 0}

from prompts import EXPERT_SYSTEM as SYSTEM, EXPLAIN_SYSTEM, TOOL_ANALYSIS, TOOL_EXPLAIN  # noqa: E402


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("LLM_BACKEND") not in ("rule", "ollama")


def _quota():
    today = dt.date.today().isoformat()
    if _count["day"] != today:
        _count.update(day=today, n=0)
    if _count["n"] >= DAILY:
        return False
    _count["n"] += 1
    return True


def _call(messages, tool, chat=None):
    """도구 호출 인자 dict와 원 응답 메시지, 사용량을 돌려준다."""
    if chat is None:
        import llm_claude
        chat = llm_claude.chat
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


def ask(question, chat=None):
    """전문가 모드 한 번. 돌려주는 값: status, method, plan, code, result, lines, by, attempts, error, usage, sec."""
    t0 = time.perf_counter()
    if not enabled():
        return {"status": "꺼짐", "error": "Claude API 키가 없어 전문가 모드를 쓸 수 없어요. 기법 목록이나 일반 질문을 써 주세요."}
    if not _quota():
        return {"status": "상한", "error": f"오늘 전문가 모드 요청 상한({DAILY}건)에 닿았어요."}
    usage = {}
    msgs = [{"role": "system", "content": SYSTEM + datadict.describe()}, {"role": "user", "content": question}]
    attempts = []
    try:
        args, msg, u = _call(msgs, TOOL_ANALYSIS, chat)
    except Exception as e:  # 키 오류·네트워크 오류는 앱을 멈추지 않고 이유만 돌려준다(키 값은 넣지 않음)
        return {"status": "오류", "error": _why(e), "sec": round(time.perf_counter() - t0, 1)}
    _add_usage(usage, u)
    out = None
    for i in range(2):
        if not args or not args.get("code"):
            said = (msg.get("content") or "").strip() if isinstance(msg, dict) else ""
            attempts.append({"stage": "설계", "error": ("AI가 코드를 만들지 않음: " + said[:300]) if said else "코드를 받지 못함"})
            break
        out = sandbox.run(args["code"])
        attempts.append({"stage": out.get("stage"), "ok": out.get("ok"), "error": out.get("error")})
        if out.get("ok") or i == 1:
            break
        call_id = (msg.get("tool_calls") or [{}])[0].get("id", "call_0")
        msgs += [msg, {"role": "tool", "tool_call_id": call_id,
                       "content": f"{out['stage']} 실패: {out['error']}. 규칙을 지켜 고친 코드를 submit_analysis로 다시 제출하세요."}]
        try:
            args, msg, u = _call(msgs, TOOL_ANALYSIS, chat)
        except Exception as e:
            attempts.append({"stage": "설계", "error": _why(e)})
            break
        _add_usage(usage, u)
    base = {"method": (args or {}).get("method"), "plan": (args or {}).get("plan"), "code": (args or {}).get("code"),
            "attempts": attempts, "usage": usage}
    if not out or not out.get("ok"):
        return {**base, "status": "실패", "sec": round(time.perf_counter() - t0, 1),
                "error": (out or {}).get("error") or (attempts[-1]["error"] if attempts else "코드를 받지 못했어요"),
                "hint": "기법 목록(상관·군집·시계열 분해·회귀·두 집단 검정·분포·이상치)이나 일반 질문으로 다시 물어 주세요."}
    result = out["result"]
    view = {"numbers": result.get("numbers"), "notes": result.get("notes"),
            "tables": [{**t, "rows": t["rows"][:30]} for t in result.get("tables", [])],
            "series": [{**s, "x": s["x"][:60], "y": s["y"][:60]} for s in result.get("series", [])]}
    ex_msgs = [{"role": "system", "content": EXPLAIN_SYSTEM},
               {"role": "user", "content": f"요청: {question}\n기법: {base['method']}\n계획: {base['plan']}\n실행 결과: {json.dumps(view, ensure_ascii=False)}"}]
    lines, by = None, "AI"
    try:
        ex, _, u = _call(ex_msgs, TOOL_EXPLAIN, chat)
        _add_usage(usage, u)
        lines = [str(x) for x in (ex or {}).get("lines") or []]
    except Exception as e:  # 해설 실패는 숫자표로 대신
        attempts.append({"stage": "해설", "error": f"{type(e).__name__}"})
    bad = check_numbers("\n".join(lines or []), [result, {"q": question, "dict": datadict.describe()}]) if lines else ["해설 없음"]  # 자료 사전의 기간·행 수도 허용
    if bad:
        attempts.append({"stage": "숫자 대조", "ok": False, "error": f"결과에 없는 숫자 {bad[:5]}"})
        lines, by = _fallback_lines(result), "프로그램(해설 숫자 불일치로 대체)"
    return {**base, "status": "성공", "result": result, "lines": lines, "by": by, "sec": round(time.perf_counter() - t0, 1)}
