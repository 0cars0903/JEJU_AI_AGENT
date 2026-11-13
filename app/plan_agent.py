"""계획 선택 Agent(문서 26 안 C, 2026-11-14 마스터 결정).

해석이 애매한 질문만 LLM이 '질문 종류'(= 정해진 계산 계획)를 고른다. 재현성은 네 가지로 지킨다.
1. 범위: 분류기 확신도가 낮거나(needs_confirm) 분류기와 사전 규칙의 질문 종류가 다를 때만 부른다. 확실한 질문은 지금 경로 그대로다.
2. 선택지: 정해진 질문 종류(enum)만 고를 수 있다. 종류가 같으면 계획(`planner.TYPE_PLAN`)과 숫자가 같다.
3. 저장: 같은 질문·같은 후보면 저장해 둔 결정을 다시 쓴다(`plan_cache.json`).
4. 검사: 고른 해석을 검수 규칙(`verify.check_tuple`)이 검사하고, 실패하거나 LLM이 없거나 오류면 분류기 결과를 그대로 쓴다.
모델: Claude 키가 있으면 Claude, 없으면 로컬 Ollama `JEJU_AGENT_MODEL`(qwen2.5:7b)이 설치돼 있을 때. 끄기: JEJU_PLAN_AGENT=0.
"""
import json
import os
import re
import time
from pathlib import Path

import llm
import qparse

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("JEJU_WRITE_DIR") or (ROOT / "data" / "interim")) / "plan_cache.json"
CHOICES = {  # 질문 종류 → LLM에게 보이는 설명(계산 계획은 planner.TYPE_PLAN이 정한다). 2026-11-14 개발용 세트(std150b·c)로 구분 기준 보강
    "T1": "현황 조회: 한 동네·업종의 지금 값 하나(가게 수, 매출, 방문 등). 시각·시간대를 묻지 않음",
    "T2": "동네 비교: 이름을 댄 두 동네 이상을 같은 지표로 나란히 비교",
    "T3": "순위: 여러 동네를 지금 값의 크기로 줄 세우기(어디가 가장 많아/적어). 변화의 크기가 아니라 수준",
    "T4": "추세: 한 동네·업종의 시간에 따른 흐름(늘었나, 요즘 많나)",
    "T5": "구성: 연령대·성별·업종·손님 구분이 차지하는 비중(%)",
    "T6": "조건 효과: 비·주말·휴일 같은 조건일 때 값이 달라지는지",
    "T7": "관계: 두 지표가 같이 움직이는지",
    "T8": "예측: 다음 기간 값 예상",
    "T9": "비슷한 동네: 구조·성격이 닮은(가까운) 동네 찾기",
    "T10": "종합 진단: 한 동네·업종을 여러 지표로 종합(창업해도 될까, 분위기 어때)",
    "T13": "시간대 패턴: 오전·점심·저녁, 몇 시~몇 시처럼 시각별 매출·방문·이용",
    "T14": "조건 탐색: 두 가지 이상 조건을 함께 만족하는 동네 찾기(~이면서 ~인 곳). 값의 급변을 찾는 것이 아님",
    "T15": "이례 변화: 평소·작년 대비 급증·급감·폭증·추락·치솟은 동네나 달 찾기(가장 가파르게 바뀐 곳 포함, 경보·모니터링)",
}
SYSTEM = ("너는 제주 상권 질문을 정해진 분석 계획으로 연결하는 계획 담당이다. 질문을 읽고 아래 질문 종류 중 하나를 고른다. "
          "분류기와 사전 규칙의 판단이 함께 주어진다. 분류기 판단이 설명에 맞으면 그대로 고른다. 분류기 판단이 분명히 틀렸을 때만 "
          "사전 규칙 판단이나 다른 종류를 고른다. 변화의 크기(급증·급감·추락·치솟음)를 묻는지, 지금 값의 크기를 묻는지, 조건 여러 개를 함께 거는지 먼저 구분한다. "
          "질문 하나에 여러 종류가 섞였거나(예: 추세를 보고 다른 동네와 비교) 위 종류로 답할 수 없으면 AGENT를 고른다. "
          "오류 노트가 주어지면 그 칸을 특히 다시 본다. 이유는 한 문장, 숫자 없이 쓴다.\n질문 종류:\n" + "\n".join(f"- {k}: {v}" for k, v in CHOICES.items())
          + "\n- AGENT: 정해진 종류 하나로 답할 수 없음(여러 단계를 함께 묻거나, 자료를 찾아야 하거나, 위 종류 밖) → Agent에게 넘김")
EXPECTS = ["답함", "되묻기", "범위밖"]
TOOL = {"type": "function", "function": {"name": "choose_plan", "description": "질문 종류(분석 계획)를 하나 고른다.", "strict": True,
        "parameters": {"type": "object", "additionalProperties": False, "required": ["type", "reason"],
                       "properties": {"type": {"type": "string", "enum": list(CHOICES) + ["AGENT"]}, "reason": {"type": "string"}}}}}
FORMAT = TOOL["function"]["parameters"]
_mem = {}


def _backend():
    if os.environ.get("JEJU_PLAN_AGENT") == "0" or os.environ.get("LLM_BACKEND") == "rule":
        return None
    import expert
    return expert.backend()


def _load():
    if not _mem and CACHE.exists():
        try:
            _mem.update(json.loads(CACHE.read_text()))
        except (OSError, ValueError):
            pass
    return _mem


def _save():
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_mem, ensure_ascii=False, indent=0))
    except OSError:  # 읽기 전용 환경이면 메모리에만 둔다
        pass


def ko(type_):
    return CHOICES.get(type_, type_ or "-").split(":")[0]


# 여러 단계 표지(2026-11-14, 조정용 047 100문항으로 정함): 한 질문에 하위 질문이 둘 이상일 때 흔한 연결 표현.
# 분류기는 이런 질문도 종류 하나로 자신 있게 읽어(047: Agent 문항 50 중 4만 넘김) 확신도 관문을 통과하므로 따로 건다.
MULTI = re.compile(r"(하고|보고|본 뒤|확인한 뒤|확인하고|뽑고|구하고|나서|다음|이어서|그리고|함께|연계|까지|뒤에|후에|및\s|와 함께|랑 같이|도 (알려|보여|비교|정리)|도 같이)")


def multi(question):
    return bool(MULTI.search(question or ""))


def notes(it, question=None):
    """오류 노트(검수·재실행 라인 1단계, 2026-11-14): 해석에서 의심되는 칸과 이유. 코드만으로 만든다."""
    t, out = it["tuple"], []
    if it.get("rule_type") in CHOICES and t.get("type") in CHOICES and it.get("rule_type") != t.get("type"):
        out.append({"field": "type", "why": f"분류기는 '{ko(t['type'])}', 사전 규칙은 '{ko(it['rule_type'])}'로 읽음"})
    re_ = it.get("rule_expect")
    if re_ in EXPECTS and t.get("expect") in EXPECTS and re_ != t.get("expect") and it.get("rule_type") != "T12":
        out.append({"field": "expect", "why": f"분류기는 '{t['expect']}', 사전 규칙은 '{re_}'로 판단"})
    if it.get("needs_confirm") and t.get("expect") == "답함" and it.get("confidence") is not None:
        out.append({"field": "type", "why": f"분류기 확신도가 낮음({it['confidence']:.2f})"})
    if question and multi(question):
        out.append({"field": "route", "why": "여러 단계를 잇는 표현이 있음(하위 질문이 둘 이상일 수 있음)"})
    return out


def needed(it, question=None):
    """계획 선택 Agent를 부를지(코드 관문). ① 확신도 낮음 ② 분류기·사전 규칙 종류 불일치 ③ 여러 단계 표지(되묻기 질문 포함)."""
    t = it["tuple"]
    if question and multi(question) and t.get("expect") in ("답함", "되묻기") and it.get("rule_type") != "T12":
        return True
    return (t.get("expect") == "답함" and t.get("type") in CHOICES and
            (bool(it.get("needs_confirm")) or (it.get("rule_type") not in (None, t.get("type")) and it.get("rule_type") in CHOICES)))


def _ask(name, question, it, chat=None):
    t = it["tuple"]
    user = (f"질문: {question}\n분류기 판단: {t['type']}({CHOICES.get(t['type'], '-')}), 확신도 {it.get('confidence')}\n"
            f"사전 규칙 판단: {it.get('rule_type')}({CHOICES.get(it.get('rule_type'), '-')})"
            + ("\n오류 노트:\n" + "\n".join(f"- {n['field']}: {n['why']}" for n in notes(it, question)) if notes(it, question) else "")
            + ("\n참고: 질문에 여러 단계를 잇는 표현이 있다. 하위 질문이 둘 이상이면 AGENT를 고른다." if multi(question) else ""))
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    if chat:
        m = chat(None, msgs, [TOOL])["message"]
    elif name == "claude":
        m = llm.chat(None, msgs, [TOOL], name="claude", effort="low")["message"]
    else:
        import expert
        m = llm.chat(expert.AGENT_MODEL, msgs, [], name="ollama", max_tokens=200, fmt=FORMAT)["message"]
    args = next((c["function"]["arguments"] for c in m.get("tool_calls") or [] if c["function"]["name"] == "choose_plan"), None)
    if args is None and (m.get("content") or "").strip().startswith("{"):
        args = json.loads(m["content"])
    if isinstance(args, str):
        args = json.loads(args)
    return args or {}


def adjust(question, it, chat=None):
    """해석 결과 it를 받아, 필요하면 LLM이 고른 질문 종류로 바꾼 it를 돌려준다. it["plan_agent"]에 기록을 남긴다."""
    if not question or not needed(it, question):
        return it
    name = "test" if chat else _backend()
    if not name:
        return it
    t = it["tuple"]
    key = f"{' '.join(question.split())}|{t['type']}|{it.get('rule_type')}|{t.get('expect')}|{it.get('rule_expect')}"
    t0 = time.perf_counter()
    rec = {"by": {"claude": "AI(Claude)", "ollama": "AI(로컬 모델)"}.get(name, "AI"), "from": t["type"], "rule": it.get("rule_type"), "from_ko": ko(t["type"])}
    cache = _load()
    if key in cache:
        got, cached = cache[key], True
    else:
        try:
            got, cached = _ask(name, question, it, chat), False
        except Exception as e:  # LLM 오류면 분류기 결과를 그대로 쓴다
            return dict(it, plan_agent={**rec, "to": t["type"], "kept": True, "why": f"AI 호출 실패({type(e).__name__})"})
    new = got.get("type")
    if new == "AGENT":  # 중간안: 정해진 종류 하나로 답할 수 없으면 Agent에게 넘긴다
        if not cached and name != "test":
            cache[key] = {"type": new, "reason": str(got.get("reason") or "")[:200]}
            _save()
        return dict(it, escalate=True, plan_agent={**rec, "to": "AGENT", "to_ko": "Agent에게 넘김", "kept": True, "escalate": True,
                                                   "reason": str(got.get("reason") or "")[:200], "cached": cached})
    if new not in CHOICES:
        return dict(it, plan_agent={**rec, "to": t["type"], "kept": True, "why": "AI가 정해진 종류를 고르지 않음"})
    import verify
    # '답할지'는 LLM이 바꾸지 않는다: 개발용 300 측정(2026-11-14)에서 답할지 변경은 망침이 많고(범위 밖→답함, 되묻기↔답함) 종류 변경만 고침이 있었다.
    # 답할지 불일치는 오류 노트로 남겨 사람 확인(이해 카드)으로 넘긴다.
    new_exp = t.get("expect")
    t2 = dict(t, type=new, expect=new_exp)
    errs = verify.check_tuple(t2)
    if errs:
        return dict(it, plan_agent={**rec, "to": t["type"], "kept": True, "why": "AI가 고른 종류가 검수 규칙에 걸림: " + "; ".join(e.get("detail", "") for e in errs)[:120]})
    if not cached and name != "test":
        cache[key] = {"type": new, "expect": new_exp, "reason": str(got.get("reason") or "")[:200]}
        _save()
    card = qparse.card(t2)
    return dict(it, tuple=t2, card=card, path=f"{it.get('path')} + 계획 선택 {rec['by']}",
                plan_agent={**rec, "to": new, "to_ko": ko(new), "kept": new == t["type"] and new_exp == t.get("expect"),
                            "expect_from": t.get("expect"), "expect_to": new_exp, "notes": notes(it, question), "reason": str(got.get("reason") or "")[:200], "cached": cached,
                            "sec": round(time.perf_counter() - t0, 3)})
