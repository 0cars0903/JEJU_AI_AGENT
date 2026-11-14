"""전문가 모드 '요청 → 기법' 연결 측정(로컬 분석 담당 Agent, app/analyst.py).

사용: python tools/eval/tech_route.py <문항.jsonl> [--no-checks] [--out 결과.json]
- 문항 한 줄: {"id", "q", "technique": 기법 키 또는 null(기법이 아닌 요청)}
- --no-checks: 코드 검사 없이 모델 판단만(모델 단독 성능). 기본은 '모델 + 코드 검사'.
- 판정: technique가 있으면 ① 단계의 선택이 그 기법인지, null이면 general·catalog를 골랐는지.
- 로컬 Ollama(qwen2.5:7b)가 필요하다. OLLAMA_URL로 주소를 바꿀 수 있다.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import analyst  # noqa: E402

args = sys.argv[1:]
path = Path(args[0])
checks = "--no-checks" not in args
out = Path(args[args.index("--out") + 1]) if "--out" in args else None
items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
rows = []
for g in items:
    t0 = time.perf_counter()
    u, _ = analyst.understand(g["q"], checks=checks)
    want = g.get("technique")
    ok = u["kind"] == want if want else u["kind"] in ("general", "catalog")
    rows.append({"id": g.get("id"), "want": want, "got": u["kind"], "ok": ok, "named": g.get("named"), "sec": round(time.perf_counter() - t0, 2)})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
tech = [r for r in rows if r["want"]]
non = [r for r in rows if not r["want"]]
summ = {"file": path.name, "checks": checks, "n": len(rows), "정답": sum(r["ok"] for r in rows),
        "기법 문항": f"{sum(r['ok'] for r in tech)}/{len(tech)}", "기법 아닌 요청": f"{sum(r['ok'] for r in non)}/{len(non)}",
        "이름 있음": f"{sum(r['ok'] for r in tech if r['named'])}/{sum(1 for r in tech if r['named'])}",
        "이름 없음": f"{sum(r['ok'] for r in tech if r['named'] is False)}/{sum(1 for r in tech if r['named'] is False)}",
        "지연 중앙값": sorted(r["sec"] for r in rows)[len(rows) // 2] if rows else None}
print("SUMMARY", json.dumps(summ, ensure_ascii=False))
if out:
    out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
