"""제출용 zip을 만들고 민감정보를 검사한다.
넣는 것: 실행 코드, 모델·레시피, 표준 테이블, 사전, 수동 매핑표, 시험, 검증 재현 도구(tools/eval·data/eval). 빼는 것: .env, 원본·중간 데이터, 이중 검토 기록.

실행(마스터 2026-11-18 순서: Claude가 폴더를 최신화 → 마스터가 계정·키를 넣음 → Claude가 압축):
  .venv/bin/python tools/build_package.py folder  # dist/<NAME>/ 를 최신 파일로 만든다. 마스터가 넣은 .env·심사용 계정 안내는 그대로 둔다
  .venv/bin/python tools/build_package.py zip     # dist/<NAME>/ 를 dist/<NAME>.zip 으로 묶는다(.env·계정 칸이 채워졌는지 확인)
  .venv/bin/python tools/build_package.py         # 키·계정 없이 저장소에서 바로 묶는다(예전 방식)
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "jeju_bigdata_consulting_agent"  # 서비스 이름: 제주빅데이터센터 빅데이터 분석·컨설팅 지원 보조 Agent
INCLUDE = ["00_먼저_읽기.md", "1_설치_Windows.bat", "2_실행_Windows.bat", "1_설치_mac.command", "2_실행_mac.command", "README.md", "docs/제출", "notebooks", "requirements.txt", ".env.example", "app", "scripts", "tests", "tools/retrain.py", "tools/feedback_to_train.py", "tools/lexicon_candidates.py", "data/x1/test_std150_gold.jsonl", "data/x1/test_std150d_gold.jsonl", "models/m1_intent.json", "models/recipes.json", "models/rag_index.npz", "models/rag_rows.json", "data/tables", "data/manual", "tools/eval", "data/eval", "data/lexicon", "data/catalog.json", "data/metric_dict.json",
           "web/out", "web/src", "web/public", "web/package.json", "web/package-lock.json", "web/next.config.ts", "web/tsconfig.json", "web/postcss.config.mjs", "web/components.json", "web/playwright.config.ts"]
SKIP = {"__pycache__", ".DS_Store", "node_modules", ".next", "test-results"}
# 실행에 쓰지 않는 실험 스크립트(채택하지 않은 LoRA 판정, 개발 PC 경로 포함). 마스터 결정 2026-11-13.
EXCLUDE = {"app/x1_lora_eval.py", "app/llm_cc.py"}  # llm_cc: Claude Code 진단용(저장소에 없음)
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


ACCOUNT_DOC = "docs/제출/심사용_계정_안내.md"
KEEP = [".env", ACCOUNT_DOC]  # 폴더를 다시 만들 때도 마스터가 채운 파일은 남긴다
ENV_KEYS = ["ANTHROPIC_API_KEY", "JEJU_ACCOUNTS", "JEJU_SESSION_SECRET"]
# 평가 위원이 Windows에서 메모장 대신 바로 읽게 PDF도 함께 둔다(마스터 2026-11-18). 계정 안내 PDF는 마스터가 채운 뒤 zip 단계에서 만든다.
PDF_DOCS = ["00_먼저_읽기.md", "docs/제출/사용자_매뉴얼.md", "docs/제출/결과_설명자료.md", "docs/제출/데이터_활용_명세.md"]


def pdfs(base, docs):
    sys.path.insert(0, str(ROOT / "tools"))
    import md_to_pdf
    return md_to_pdf.convert([base / d for d in docs])


def collect():
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
    return files


def folder():
    """dist/<NAME>/ 를 최신 파일로 다시 만든다. 마스터가 채운 .env·심사용 계정 안내는 남긴다."""
    files = collect()
    dst = ROOT / "dist" / NAME
    kept = {k: (dst / k).read_bytes() for k in KEEP if (dst / k).exists()}
    if dst.exists():
        shutil.rmtree(dst)
    for f in files:
        t = dst / f.relative_to(ROOT)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)
    for k, b in kept.items():
        if k == ACCOUNT_DOC and "<제출 ZIP에서 채움>" in b.decode("utf-8", "ignore"):
            continue  # 아직 안 채운 옛 사본이면 새 파일을 쓴다
        (dst / k).write_bytes(b)
    made = pdfs(dst, PDF_DOCS)
    print(f"PDF {len(made)}개: {[m.name for m in made]}")
    print(f"{dst.relative_to(ROOT)} · 파일 {len(files)}개 · 남긴 파일 {sorted(kept)} · 민감정보 검사 통과")
    print(f"다음: 마스터가 {dst.relative_to(ROOT)}/.env 를 만들고({', '.join(ENV_KEYS)}), {ACCOUNT_DOC} 의 아이디·비밀번호 칸을 채운다.")


def zip_folder():
    """마스터가 채운 dist/<NAME>/ 를 묶는다. 키·계정은 .env와 계정 안내에만 있어야 한다(값은 출력하지 않음)."""
    src = ROOT / "dist" / NAME
    if not src.exists():
        sys.exit("dist 폴더가 없다. 먼저 folder를 실행한다.")
    env = src / ".env"
    vals = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip('"').strip("'")
    miss = [k for k in ENV_KEYS if len(vals.get(k, "")) < 8]
    doc = (src / ACCOUNT_DOC).read_text(encoding="utf-8")
    if miss:
        sys.exit(f".env에 값이 없거나 짧은 항목: {miss}")
    if "<제출 ZIP에서 채움>" in doc:
        sys.exit(f"{ACCOUNT_DOC}의 아이디·비밀번호 칸이 비어 있다.")
    pdfs(src, [ACCOUNT_DOC])  # 채운 계정 안내의 PDF
    keys = [v.encode() for k, v in vals.items() if len(v) >= 8]
    files = [f for f in src.rglob("*") if f.is_file() and not SKIP & set(f.parts)]
    bad = [str(f.relative_to(src)) for f in files if f.relative_to(src).as_posix() not in (".env", ACCOUNT_DOC, ACCOUNT_DOC[:-3] + ".pdf")
           and (any(k in f.read_bytes() for k in keys) or any(x.search(f.read_bytes()) for x in PATTERNS))]
    if bad:
        sys.exit(f"키·계정이 .env·계정 안내 밖에 있다: {bad}")
    out = ROOT / "dist" / f"{NAME}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"{NAME}/{f.relative_to(src).as_posix()}")
    print(f"{out.relative_to(ROOT)} · 파일 {len(files)}개 · {out.stat().st_size / 1e6:.1f}MB · .env·계정 칸 확인, 그 밖 파일 키 검사 통과")


def main():
    files = collect()
    out = ROOT / "dist" / f"{NAME}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"{NAME}/{f.relative_to(ROOT).as_posix()}")
    print(f"{out.relative_to(ROOT)} · 파일 {len(files)}개 · {out.stat().st_size / 1e6:.1f}MB · 민감정보 검사 통과")


if __name__ == "__main__":
    {"folder": folder, "zip": zip_folder}.get(sys.argv[1] if len(sys.argv) > 1 else "", main)()
