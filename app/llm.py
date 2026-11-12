"""LLM 연결부. 키가 있으면 Claude, 없으면 로컬 Ollama(제출본 기본), 둘 다 없으면 LLM 없이 동작한다. urllib만 쓴다.
LOTTE_AX_CHALLENGE/demo/llm_client.py에서 복사해 줄였다(2026-11-06)."""
import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_OLLAMA_MODEL = os.environ.get("JEJU_OLLAMA_MODEL", "qwen3:1.7b")  # 제출본 기본 경로. GTX 1060 메모리에 맞게 작은 모델(1.4GB)


def _ollama_alive():
    try:
        urllib.request.urlopen(OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=2)
        return True
    except OSError:
        return False


def backend():
    b = os.environ.get("LLM_BACKEND")
    if b:
        return b
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return "ollama" if _ollama_alive() else "rule"


def chat(model, messages, tools, name=None, max_tokens=700, fmt=None, effort=None):
    """돌려주는 형식: {"message": {"role", "content", "tool_calls"?}}
    fmt: Ollama 출력 JSON 스키마(format). effort: Claude 생각 깊이(low·medium·high)."""
    name = name or backend()
    if name == "claude":
        import llm_claude
        return llm_claude.chat(model, messages, tools, effort=effort)
    if name == "ollama":
        model = model or DEFAULT_OLLAMA_MODEL
        payload = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0, "seed": 0, "num_predict": max_tokens}}
        if tools:
            payload["tools"] = tools
        if fmt:
            payload["format"] = fmt
        if model.startswith("qwen3"):
            payload["think"] = False
        req = urllib.request.Request(OLLAMA_URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    raise ValueError(f"알 수 없는 LLM 백엔드: {name}")
