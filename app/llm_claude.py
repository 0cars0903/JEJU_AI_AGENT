"""Claude 연결부. LOTTE_AX_CHALLENGE/demo/llm_claude.py에서 복사(2026-11-06). 키는 환경 변수 ANTHROPIC_API_KEY로만 받는다.
LLM_BACKEND=claude일 때만 쓴다. 공식 Anthropic SDK(anthropic 0.125.0)는 이 백엔드를 쓸 때만 불러온다.
"""
import json
import os

MODEL = os.environ.get("JEJU_CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("JEJU_CLAUDE_EFFORT", "medium")
MAX_TOKENS = 16000  # 생각 토큰도 이 안에 든다. 비스트리밍 요청의 권장 기본값
BETAS = ["server-side-fallback-2026-07-01"]
RAW = "_anthropic_content"  # 어시스턴트 메시지에 붙여 두는 원래 응답 블록(다음 요청에 그대로 보냄)

_client = None


def client():
    global _client
    if _client is None:
        import anthropic  # 이 백엔드를 쓸 때만 불러온다(본선 OpenAI 환경에는 설치하지 않아도 됨)
        _client = anthropic.Anthropic(max_retries=2, timeout=300.0)  # 생각+도구 턴이 길어질 수 있어 300초(Gemini 098)
    return _client


def to_claude_tools(tools):
    """함수 호출 정의(OpenAI 형식 {"type": "function", "function": {...}}) → Messages API 도구 정의."""
    out = []
    for t in tools:
        f = t["function"] if t.get("type") == "function" else t
        out.append({"name": f["name"], "description": f.get("description", ""), "input_schema": f["parameters"]})
    return out


def to_claude_messages(messages):
    """agent 루프의 메시지 → (system, messages). 연속된 tool 메시지는 tool_result 블록으로 한 user 메시지에 묶는다."""
    system, out = None, []
    for m in messages:
        role = m["role"]
        if role == "system":
            system = m["content"]
        elif role == "assistant":
            if RAW in m:
                out.append({"role": "assistant", "content": m[RAW]})
            else:  # 이 모듈이 만들지 않은 어시스턴트 메시지(예: 다른 백엔드 기록)
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                for i, tc in enumerate(m.get("tool_calls") or []):
                    args = tc["function"]["arguments"]
                    blocks.append({"type": "tool_use", "id": tc.get("id", f"call_{i}"), "name": tc["function"]["name"],
                                   "input": json.loads(args) if isinstance(args, str) else args})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(빈 응답)"}]})  # 빈 content는 400
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": "user", "content": m["content"]})
    return system, out


def from_claude(resp):
    """응답 → agent 루프 모양. 거절이면 내용 없이 refusal 표시. usage는 토큰 실측용."""
    text = "".join(b.text for b in resp.content if b.type == "text")
    calls = [{"id": b.id, "function": {"name": b.name, "arguments": dict(b.input)}}
             for b in resp.content if b.type == "tool_use"]
    msg = {"role": "assistant", "content": "" if resp.stop_reason == "refusal" else text, RAW: resp.content}
    if calls and resp.stop_reason != "refusal":
        msg["tool_calls"] = calls
    u = resp.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
             "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None) or 0}
    return {"message": msg, "usage": usage, "stop_reason": resp.stop_reason, "model": resp.model}


def chat(model, messages, tools, temperature=None, max_tokens=None):
    """llm_client.chat과 같은 자리에서 부른다. temperature는 Opus 5.5에서 400이라 받기만 하고 보내지 않는다."""
    system, msgs = to_claude_messages(messages)
    kwargs = {"model": model or MODEL, "max_tokens": MAX_TOKENS, "messages": msgs, "tools": to_claude_tools(tools),
              "thinking": {"type": "adaptive"}, "output_config": {"effort": EFFORT},
              "betas": BETAS, "fallbacks": "default"}
    if system:
        kwargs["system"] = system
    return from_claude(client().beta.messages.create(**kwargs))


if __name__ == "__main__":  # 형식 변환 점검(네트워크·키 없이)
    from types import SimpleNamespace as NS
    t = to_claude_tools([{"type": "function", "function": {"name": "record", "description": "d",
                                                           "parameters": {"type": "object", "properties": {}}}}])
    assert t == [{"name": "record", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    raw = [NS(type="thinking", thinking="", signature="sig"), NS(type="tool_use", id="tu_1", name="run_forecast",
                                                               input={"part_no": "PF-210", "month": "2027-01"}),
           NS(type="tool_use", id="tu_2", name="get_indicator", input={"name": "환율", "month": "2026-10"})]
    resp = NS(content=raw, stop_reason="tool_use", model=MODEL,
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    r = from_claude(resp)
    assert [c["id"] for c in r["message"]["tool_calls"]] == ["tu_1", "tu_2"] and r["message"][RAW] is raw
    loop = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"}, r["message"],
            {"role": "tool", "content": "{}", "tool_call_id": "tu_1"}, {"role": "tool", "content": "{}", "tool_call_id": "tu_2"}]
    sysm, msgs = to_claude_messages(loop)
    assert sysm == "S" and [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"] is raw, "생각 블록을 받은 그대로 다시 보내야 함"
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["tu_1", "tu_2"], "도구 결과는 한 user 메시지에 묶음"
    ref = from_claude(NS(content=[], stop_reason="refusal", model=MODEL, usage=resp.usage))
    assert ref["message"]["content"] == "" and "tool_calls" not in ref["message"] and ref["stop_reason"] == "refusal"
    print("형식 변환 점검 통과(5개)")
