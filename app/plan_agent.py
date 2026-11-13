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
import time
from pathlib import Path

import llm
import qparse

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("JEJU_WRITE_DIR") or (ROOT / "data" / "interim")) / "plan_cache.json"
CHOICES = {  # 질문 종류 → LLM에게 보이는 설명(계산 계획은 planner.TYPE_PLAN이 정한다)
    "T1": "현황 조회: 한 동네·업종의 지금 값(가게 수, 매출, 방문 등)",
    "T2": "동네 비교: 두 동네 이상을 같은 지표로 비교",
    "T3": "순위: 여러 동네를 지표로 줄 세우기(어디가 가장 ~)",
    "T4": "추세: 시간에 따른 변화(늘었나, 흐름)",
    "T5": "구성: 연령·성별·업종·손님 구성 비율",
    "T6": "조건 효과: 비·주말·휴일 같은 조건에서 값이 달라지는지",
    "T7": "관계: 두 지표가 같이 움직이는지",
    "T8": "예측: 다음 기간 값 예상",
    "T9": "비슷한 동네: 닮은 동네 찾기",
    "T10": "종합 진단: 한 동네·업종을 여러 지표로 종합(창업해도 될까 등)",
    "T13": "시간대 패턴: 시간대별 매출",
    "T14": "조건 탐색: 조건에 맞는 동네 찾기(예: 방문 많고 가게 적은 곳)",
    "T15": "이례 변화: 평소와 다르게 크게 바뀐 달",
}
SYSTEM = ("너는 제주 상권 질문을 정해진 분석 계획으로 연결하는 계획 담당이다. 질문을 읽고 아래 질문 종류 중 하나를 고른다. "
          "분류기와 사전 규칙의 판단이 함께 주어진다. 둘 중 하나가 맞으면 그것을, 둘 다 틀리면 다른 종류를 고른다. "
          "이유는 한 문장, 숫자 없이 쓴다.\n질문 종류:\n" + "\n".join(f"- {k}: {v}" for k, v in CHOICES.items()))
TOOL = {"type": "function", "function": {"name": "choose_plan", "description": "질문 종류(분석 계획)를 하나 고른다.", "strict": True,
        "parameters": {"type": "object", "additionalProperties": False, "required": ["type", "reason"],
                       "properties": {"type": {"type": "string", "enum": list(CHOICES)}, "reason": {"type": "string"}}}}}
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


def needed(it):
    t = it["tuple"]
    return (t.get("expect") == "답함" and t.get("type") in CHOICES and
            (bool(it.get("needs_confirm")) or (it.get("rule_type") not in (None, t.get("type")) and it.get("rule_type") in CHOICES)))


def _ask(name, question, it, chat=None):
    t = it["tuple"]
    user = (f"질문: {question}\n분류기 판단: {t['type']}({CHOICES.get(t['type'], '-')}), 확신도 {it.get('confidence')}\n"
            f"사전 규칙 판단: {it.get('rule_type')}({CHOICES.get(it.get('rule_type'), '-')})")
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
    if not question or not needed(it):
        return it
    name = "test" if chat else _backend()
    if not name:
        return it
    t = it["tuple"]
    key = f"{' '.join(question.split())}|{t['type']}|{it.get('rule_type')}"
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
    if new not in CHOICES:
        return dict(it, plan_agent={**rec, "to": t["type"], "kept": True, "why": "AI가 정해진 종류를 고르지 않음"})
    import verify
    t2 = dict(t, type=new)
    errs = verify.check_tuple(t2)
    if errs:
        return dict(it, plan_agent={**rec, "to": t["type"], "kept": True, "why": "AI가 고른 종류가 검수 규칙에 걸림: " + "; ".join(e.get("detail", "") for e in errs)[:120]})
    if not cached and name != "test":
        cache[key] = {"type": new, "reason": str(got.get("reason") or "")[:200]}
        _save()
    card = qparse.card(t2)
    return dict(it, tuple=t2, card=card, path=f"{it.get('path')} + 계획 선택 {rec['by']}",
                plan_agent={**rec, "to": new, "to_ko": ko(new), "kept": new == t["type"], "reason": str(got.get("reason") or "")[:200], "cached": cached,
                            "sec": round(time.perf_counter() - t0, 3)})
