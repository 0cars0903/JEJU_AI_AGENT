"""프로젝트 최상위 `.env`를 읽어 환경 변수로 올린다(평가용 키를 ZIP의 `.env`로 받기 위해, 2026-11-13).

- 이미 설정된 환경 변수는 덮어쓰지 않는다(명령 창에서 `set`한 값이 우선).
- 키 값은 출력·로그에 남기지 않는다. 빈 값(`KEY=`)은 건너뛴다.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path=None):
    """읽어 올린 변수 이름 목록을 돌려준다(값은 돌려주지 않는다)."""
    p = Path(path) if path else ROOT / ".env"
    if not p.is_file():
        return []
    names = []
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if not k or not v or k in os.environ:
            continue
        os.environ[k] = v
        names.append(k)
    return names
