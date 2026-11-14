"""단계형 분석 담당 Agent(app/analyst.py) 5단계 전체 측정(2026-11-14 평가 B1: '① 요청 이해만 측정' 지적).

사용: python tools/eval/analyst_eval.py <문항.jsonl> [--out 결과.json]   (기법 문항만 쓴다: technique가 있는 줄)
단계별로 센다:
  ① 요청 이해: 고른 기법이 정답인가
  ② 대안: 조건이 안 맞아 대안을 고른 건수, 그 뒤 계산에 성공한 건수
  ③ 계산: 정해진 기법 코드가 결과를 냈는가(최종)
  ④ 해석: 모델 해석 문장이 숫자·결과 밖 동네 검사를 통과해 채택됐는가(통과 못 하면 기법 코드 문장으로 대체)
  ⑤ 다음 분석: 목록 안 기법 1개 이상을 제안했는가
로컬 Ollama(qwen2.5:7b)가 필요하다.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import analyst  # noqa: E402

args = sys.argv[1:]
items = [json.loads(l) for l in Path(args[0]).read_text(encoding="utf-8").splitlines() if l.strip()]
items = [g for g in items if g.get("technique")]
out = Path(args[args.index("--out") + 1]) if "--out" in args else None
rows = []
for g in items:
    t0 = time.perf_counter()
    r = analyst.run(g["q"])
    tr = r.get("trace") or []
    first = next((json.loads(t["args"]).get("kind") for t in tr if t["tool"] == "understand"), None)
    final_u = [t for t in tr if t["tool"] == "understand"][-1] if any(t["tool"] == "understand" for t in tr) else None
    alt = [t for t in tr if t["tool"] == "alternative"]
    calc = [t for t in tr if t["tool"] == "run_technique"]
    ex = next((t for t in tr if t["tool"] == "explain"), None)
    sg = next((t for t in tr if t["tool"] == "suggest"), None)
    rows.append({"id": g.get("id"), "want": g["technique"], "first": first, "understand_ok": first == g["technique"],
                 "alt": bool(alt), "alt_ok": bool(alt) and bool(calc) and calc[-1]["ok"], "calc_ok": bool(calc) and calc[-1]["ok"],
                 "explain": None if ex is None else ex["ok"], "suggest": None if sg is None else sg["ok"], "status": r.get("status"),
                 "sec": round(time.perf_counter() - t0, 2)})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
n = len(rows)
ex = [r for r in rows if r["explain"] is not None]
sg = [r for r in rows if r["suggest"] is not None]
summ = {"n": n, "① 요청 이해 정답": sum(r["understand_ok"] for r in rows), "② 대안 고른 건수": sum(r["alt"] for r in rows),
        "② 대안 뒤 계산 성공": sum(r["alt_ok"] for r in rows), "③ 기법 계산 성공": sum(r["calc_ok"] for r in rows),
        "④ 해석 채택": f"{sum(r['explain'] for r in ex)}/{len(ex)}", "⑤ 다음 분석 제안": f"{sum(r['suggest'] for r in sg)}/{len(sg)}",
        "성공으로 끝남": sum(r["status"] == "성공" for r in rows), "지연 중앙값": sorted(r["sec"] for r in rows)[n // 2] if rows else None}
print("SUMMARY", json.dumps(summ, ensure_ascii=False))
if out:
    out.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
