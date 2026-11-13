"""제출용 zip을 만들고 민감정보를 검사한다. 실행: .venv/bin/python tools/build_package.py
넣는 것: 실행 코드, 모델·레시피, 표준 테이블, 사전, 수동 매핑표, 시험. 빼는 것: .env, 원본·중간 데이터, 이중 검토 기록.
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "jeju_dong_agent"
INCLUDE = ["README.md", "docs/제출", "notebooks", "requirements.txt", ".env.example", "app", "scripts", "tests", "models/m1_intent.json", "models/recipes.json", "data/tables", "data/manual", "data/lexicon", "data/catalog.json", "data/metric_dict.json",
           "web/out", "web/src", "web/public", "web/package.json", "web/package-lock.json", "web/next.config.ts", "web/tsconfig.json", "web/postcss.config.mjs", "web/components.json", "web/playwright.config.ts"]
SKIP = {"__pycache__", ".DS_Store", "node_modules", ".next", "test-results"}
# 실행에 쓰지 않는 실험 스크립트(채택하지 않은 LoRA 판정, 개발 PC 경로 포함). 마스터 결정 2026-11-13.
EXCLUDE = {"app/x1_lora_eval.py"}
# 키 형식과 개발 PC의 절대 경로(macOS /Volumes·/Users)가 제출본에 들어가지 않게 막는다.
PATTERNS = [re.compile(rb"sk-ant-[A-Za-z0-9_-]{8,}"), re.compile(rb"/Volumes/"), re.compile(rb"/Users/")]


def secrets():
    """실제 키 값을 읽어 검사에만 쓴다. 출력하지 않는다."""
    env = ROOT / ".env"
    vals = []
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            _, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            if len(v) >= 8:
                vals.append(v.encode())
    return vals


def main():
    files = []
    for item in INCLUDE:
        p = ROOT / item
        if not p.exists():
            continue
        files += [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and not SKIP & set(f.parts)]
    files = [f for f in files if f.relative_to(ROOT).as_posix() not in EXCLUDE]
    keys, bad = secrets(), []
    for f in files:
        b = f.read_bytes()
        if any(k in b for k in keys) or any(x.search(b) for x in PATTERNS):
            bad.append(str(f.relative_to(ROOT)))
    if not (ROOT / "web" / "out" / "index.html").exists():
        sys.exit("web/out이 없다. web 폴더에서 npm run build를 먼저 실행한다.")
    if bad:
        sys.exit(f"민감정보 의심 파일이 있어 멈춘다: {bad}")
    out = ROOT / "dist" / f"{NAME}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"{NAME}/{f.relative_to(ROOT).as_posix()}")
    print(f"{out.relative_to(ROOT)} · 파일 {len(files)}개 · {out.stat().st_size / 1e6:.1f}MB · 민감정보 검사 통과")


if __name__ == "__main__":
    main()
