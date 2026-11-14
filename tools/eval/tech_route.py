"""전문가 모드 '요청 → 기법' 연결 측정(로컬 분석 담당 Agent, app/analyst.py).

사용: python tools/eval/tech_route.py <문항.jsonl> [--no-checks] [--out 결과.json]
- 문항 한 줄: {"id", "q", "technique": 기법 키 또는 null(기법이 아닌 요청)}
- --no-checks: 코드 검사 없이 모델 판단만(모델 단독 성능). 기본은 '모델 + 코드 검사'.
- --rule: 모델 없이 기법 이름 규칙(techniques.detect)만. 이름이 없으면 general로 본다(비교 기준).
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
    if "--rule" in args:
        import techniques as T
        u, log = {"kind": T.detect(g["q"]) or "general"}, []
    else:
        u, log = analyst.understand(g["q"], checks=checks)
    want = g.get("technique")
    good = lambda k: (k == want) if want else k in ("general", "catalog")  # noqa: E731
    first = json.loads(log[0]["args"]).get("kind") if log else u["kind"]  # 모델이 처음 고른 것(코드 검사 전)
    rows.append({"id": g.get("id"), "want": want, "got": u["kind"], "ok": good(u["kind"]), "model_first": first, "model_first_ok": good(first),
                 "changed": first != u["kind"], "named": g.get("named"), "sec": round(time.perf_counter() - t0, 2)})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
tech = [r for r in rows if r["want"]]
non = [r for r in rows if not r["want"]]
summ = {"file": path.name, "checks": "이름 규칙만" if "--rule" in args else checks, "n": len(rows), "정답": sum(r["ok"] for r in rows),
        "기법 문항": f"{sum(r['ok'] for r in tech)}/{len(tech)}", "기법 아닌 요청": f"{sum(r['ok'] for r in non)}/{len(non)}",
        "이름 있음": f"{sum(r['ok'] for r in tech if r['named'])}/{sum(1 for r in tech if r['named'])}",
        "이름 없음": f"{sum(r['ok'] for r in tech if r['named'] is False)}/{sum(1 for r in tech if r['named'] is False)}",
        "지연 중앙값": sorted(r["sec"] for r in rows)[len(rows) // 2] if rows else None,
        "모델 첫 판단 정답": sum(r["model_first_ok"] for r in rows), "검사가 바꾼 건수": sum(r["changed"] for r in rows),
        "바꿔서 맞음": sum(r["changed"] and r["ok"] and not r["model_first_ok"] for r in rows), "바꿔서 틀림": sum(r["changed"] and r["model_first_ok"] and not r["ok"] for r in rows)}
print("SUMMARY", json.dumps(summ, ensure_ascii=False))
if out:
    out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
