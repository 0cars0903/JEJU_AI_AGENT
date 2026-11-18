"""LLM 연결부. 키가 있으면 Claude, 없으면 로컬 Ollama(제출본 기본), 둘 다 없으면 LLM 없이 동작한다. urllib만 쓴다.
LOTTE_AX_CHALLENGE/demo/llm_client.py에서 복사해 줄였다(2026-11-06)."""
import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_OLLAMA_MODEL = os.environ.get("JEJU_OLLAMA_MODEL", "qwen3:1.7b")  # 제출본 기본 경로. GTX 1060 메모리에 맞게 작은 모델(1.4GB)
# 센터 PC(GTX 1060, VRAM 3GB) 메모리 설정(2026-11-17 문제 기록 52번). 문맥 32,768토큰(Ollama 기본)이면 qwen2.5:7b가 6.61GB를 쓴다.
# 실제 호출은 최대 2,788토큰이라 문맥을 4,096으로 줄이면 7b 전체 4.43GB이고, GPU에 올리는 층 수는 Ollama가 남은 VRAM에 맞춰 정한다(나머지 층은 CPU).
# 문장 모델(qwen3:1.7b, 1.35GB)은 GPU에서 7b와 자리를 다투면 모델을 번갈아 다시 올리게 되므로 CPU에 둔다.
LOG_PATH = os.environ.get("JEJU_LLM_LOG", "")
NUM_CTX = int(os.environ.get("JEJU_NUM_CTX", "4096"))
GPU_LAYERS = {k.strip(): int(v) for k, v in (x.split("=", 1) for x in os.environ.get("JEJU_GPU_LAYERS", "qwen3:1.7b=0").split(",") if "=" in x)}


def ollama_headers():
    """Ollama 요청 머리글. OLLAMA_TOKEN이 있으면 공유 토큰을 붙인다(Vercel 데모 → Mac mini Ollama 터널, 2026-11-18 문제 기록 69번)."""
    h = {"Content-Type": "application/json"}
    if os.environ.get("OLLAMA_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["OLLAMA_TOKEN"]
    return h


def ping_timeout():
    """Ollama 상태 확인 제한 시간(초). 원격 터널(OLLAMA_TOKEN)은 TLS 연결이 붙어 2초를 넘길 수 있다(2026-11-18 Vercel 데모)."""
    return 10 if os.environ.get("OLLAMA_TOKEN") else 2


_ALIVE = {"t": 0.0}
_SESSION = []


def http():
    """Ollama용 requests 세션(연결 다시 쓰기). 원격 터널은 호출마다 새 TLS 연결을 맺으면 1초 남짓씩 늘어난다(2026-11-18 Vercel 데모: 같은 질문 로컬 26초, 데모 99초)."""
    if not _SESSION:
        import requests
        _SESSION.append(requests.Session())
    return _SESSION[0]


def _ollama_alive():
    import time
    remote = bool(os.environ.get("OLLAMA_TOKEN"))
    if remote and time.time() - _ALIVE["t"] < 60:  # 원격 터널: 성공한 확인을 60초 다시 쓴다(질문 1개에 확인 35번이 오가던 것, 2026-11-18)
        return True
    for _ in range(2 if remote else 1):  # 원격 터널은 새 서버의 첫 연결이 실패할 수 있어 한 번 더 확인한다(2026-11-18 Vercel 데모 첫 질문 'Ollama 꺼짐')
        try:
            if remote:
                http().get(OLLAMA_URL.replace("/api/chat", "/api/tags"), headers=ollama_headers(), timeout=ping_timeout()).raise_for_status()
            else:
                urllib.request.urlopen(urllib.request.Request(OLLAMA_URL.replace("/api/chat", "/api/tags"), headers=ollama_headers()), timeout=ping_timeout())
            _ALIVE["t"] = time.time()
            return True
        except OSError:
            pass
    return False


def backend():
    b = os.environ.get("LLM_BACKEND")
    if b:
        return b
    if os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("JEJU_CLAUDE", "request") == "auto":  # 기본은 요청 단위(expert.claude_auto)
        return "claude"
    return "ollama" if _ollama_alive() else "rule"


def chat(model, messages, tools, name=None, max_tokens=700, fmt=None, effort=None, logprobs=0):
    """돌려주는 형식: {"message": {"role", "content", "tool_calls"?}}(Ollama는 logprobs도)
    fmt: Ollama 출력 JSON 스키마(format). effort: Claude 생각 깊이(low·medium·high). logprobs: Ollama 토큰마다 상위 후보 수(0이면 받지 않음)."""
    name = name or backend()
    if name == "claude":
        import llm_claude
        return llm_claude.chat(model, messages, tools, effort=effort)
    if name == "ollama":
        model = model or DEFAULT_OLLAMA_MODEL
        opts = {"temperature": 0, "seed": 0, "num_predict": max_tokens, "num_ctx": NUM_CTX}
        if model in GPU_LAYERS:
            opts["num_gpu"] = GPU_LAYERS[model]
        payload = {"model": model, "messages": messages, "stream": False, "options": opts}
        if tools:
            payload["tools"] = tools
        if fmt:
            payload["format"] = fmt
        if logprobs:  # 선택지 확신도(2026-11-15 실험 A): 고른 글자 토큰의 후보 확률
            payload["logprobs"], payload["top_logprobs"] = True, int(logprobs)
        if model.startswith("qwen3"):
            payload["think"] = False
        if os.environ.get("OLLAMA_TOKEN"):  # 원격 터널: 연결을 다시 쓴다
            resp = http().post(OLLAMA_URL, data=json.dumps(payload).encode(), headers=ollama_headers(), timeout=300)
            resp.raise_for_status()
            out = resp.json()
        else:
            req = urllib.request.Request(OLLAMA_URL, json.dumps(payload).encode(), ollama_headers())
            with urllib.request.urlopen(req, timeout=300) as r:
                out = json.loads(r.read())
        if LOG_PATH:  # 학습 증류의 자기 증류 자료(58번, 2026-11-17): 7B 호출의 입력과 응답을 그대로 남긴다(측정 때만 켬)
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"model": model, "messages": messages, "tools": tools or None, "format": fmt,
                                        "response": {k: v for k, v in (out.get("message") or {}).items() if k in ("role", "content", "tool_calls")}}, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return out
    raise ValueError(f"알 수 없는 LLM 백엔드: {name}")
