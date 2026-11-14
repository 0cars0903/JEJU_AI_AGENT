"""실행 전에 어느 경로로 도는지 실행 창에 알려 준다(run_windows.bat·run_mac.sh가 부른다, 2026-11-13).

- 질문 해석: Ollama `bge-m3`가 있으면 임베딩 + 분류기(판정용 300문항 82.7%), 없으면 사전 규칙(66.3%).
- 설명 문장: Ollama `qwen3:1.7b`, 없으면 템플릿 문장(JEJU_CLAUDE=auto면 키가 있을 때 Claude). Claude는 기본으로 요청 단위.
- 키 값은 출력하지 않는다. 실패해도 앱 실행을 막지 않는다(항상 종료 코드 0).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import envfile  # noqa: E402

EMBED = "bge-m3"
AGENT = os.environ.get("JEJU_AGENT_MODEL", "qwen2.5:7b")  # 전문가 모드 로컬 도구 루프(문서 26)
CHAT = os.environ.get("JEJU_OLLAMA_MODEL", "qwen3:1.7b")
# 정확도를 잰 모델 판(Ollama digest 앞 12자리, 2026-11-15 확인). 'ollama pull'은 같은 이름이라도 새 판을 받을 수 있어 실행 전에 대조한다.
PINNED = {"bge-m3": "790764642607", "qwen3:1.7b": "8f68893c685c", "qwen2.5:7b": "845dbda0ea48"}


def ollama_models(url=None):
    """Ollama에 받아 둔 모델 이름 집합. Ollama가 꺼져 있으면 None."""
    url = url or os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat").replace("/api/chat", "/api/tags")
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            tags = json.loads(r.read())
    except (OSError, ValueError):
        return None
    names = set()
    for m in tags.get("models", []):
        n = m.get("name", "")
        names.add(n)
        names.add(n.split(":")[0] if n.endswith(":latest") else n)
    return names


def digests(url=None):
    """Ollama에 받아 둔 모델의 digest(앞 12자리). Ollama가 꺼져 있으면 {}."""
    url = url or os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat").replace("/api/chat", "/api/tags")
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            tags = json.loads(r.read())
    except (OSError, ValueError):
        return {}
    out = {}
    for m in tags.get("models", []):
        n = m.get("name", "")
        out[n[:-len(":latest")] if n.endswith(":latest") else n] = (m.get("digest") or "")[:12]
    return out


def version_lines(have):
    """측정한 판과 다른 모델이 있으면 알린다(고정한 판: PINNED)."""
    return [f"[모델 판] {n}의 판({have[n]})이 정확도를 잰 판({d})과 다릅니다. 수치가 README와 다를 수 있습니다."
            for n, d in PINNED.items() if n in have and have[n] and have[n] != d]


def report(models, has_key, backend=None):
    """경로 안내 문장 목록. models=None은 Ollama 꺼짐."""
    lines = []
    if models is None:
        lines.append("[질문 해석] Ollama가 꺼져 있어 사전 규칙으로 해석합니다(정확도가 낮아집니다). Ollama를 켜고 다시 실행하면 임베딩 경로를 씁니다.")
    elif EMBED in models:
        lines.append(f"[질문 해석] Ollama {EMBED} 임베딩 + 분류기를 씁니다.")
    else:
        lines.append(f"[질문 해석] Ollama에 {EMBED}가 없어 사전 규칙으로 해석합니다. 'ollama pull {EMBED}'를 실행해 주세요.")
    auto = os.environ.get("JEJU_CLAUDE", "request") == "auto"  # 기본은 요청 단위(담당자가 [Claude로 분석]을 누를 때만)
    if backend == "rule":
        lines.append("[설명 문장] LLM_BACKEND=rule이라 템플릿 문장으로 답합니다.")
    elif (has_key and auto) or backend == "claude":
        lines.append("[설명 문장] JEJU_CLAUDE=auto라 Claude를 씁니다.")
    elif models is not None and CHAT in models:
        lines.append(f"[설명 문장] Ollama {CHAT}를 씁니다.")
    else:
        lines.append(f"[설명 문장] LLM이 없어 템플릿 문장으로 답합니다. 숫자 계산은 그대로입니다(선택: 'ollama pull {CHAT}').")
    if backend == "rule":
        lines.append("[전문가 모드] LLM_BACKEND=rule이라 꺼져 있습니다.")
    elif models is not None and AGENT in models:
        lines.append(f"[전문가 모드] Ollama {AGENT}가 도구 4개(코드 실행 제외)와 통계 기법 12종을 골라 씁니다.")
    elif not has_key:
        lines.append(f"[전문가 모드] 로컬 모델이 없어 꺼져 있습니다(선택: 'ollama pull {AGENT}'). 통계 기법 12종은 사이드바에서 그대로 씁니다.")
    if has_key and not auto:
        lines.append("[Claude] 키가 있습니다. 담당자가 로그인한 뒤 전문가 모드의 [Claude로 분석]을 누른 요청에만 씁니다(계정: JEJU_ACCOUNTS).")
    return lines


def main():
    loaded = envfile.load()
    if loaded:
        print(".env에서 환경 변수를 읽었습니다: " + ", ".join(loaded))
    for line in report(ollama_models(), bool(os.environ.get("ANTHROPIC_API_KEY")), os.environ.get("LLM_BACKEND")) + version_lines(digests()):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
