"""문서 22 5절 3단계 검증: 주제 14개의 분석 블록 줄 수와 종류(노형동·카페 기준, 업종을 못 고르는 주제는 업종 없이)."""
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import result

CASES = [
    ("diagnose", {"topic": "diagnose", "space": ["노형동"], "target": "카페"}),
    ("stores", {"topic": "stores", "space": ["노형동"], "target": "카페"}),
    ("openclose", {"topic": "openclose", "space": ["노형동"], "target": "카페"}),
    ("openclose/survival", {"topic": "openclose", "space": ["노형동"], "target": "카페", "variant": "survival"}),
    ("market", {"topic": "market", "space": ["노형동"], "target": "음식점"}),
    ("sales", {"topic": "sales", "space": ["노형동"], "target": "카페"}),
    ("customers", {"topic": "customers", "space": ["노형동"], "target": "카페"}),
    ("hourly", {"topic": "hourly", "space": ["노형동"], "target": "카페"}),
    ("visit", {"topic": "visit", "space": ["노형동"]}),
    ("rain", {"topic": "rain", "space": ["노형동"]}),
    ("bizcompare", {"topic": "bizcompare", "space": ["노형동"]}),
    ("compare", {"topic": "compare", "space": ["노형동", "연동"], "target": "카페"}),
    ("rank", {"topic": "rank", "metric": "매출", "target": "음식점"}),
    ("similar", {"topic": "similar", "space": ["노형동"]}),
    ("forecast", {"topic": "forecast", "space": ["노형동"]}),
]
env = {"center_db": False}
show = "-v" in sys.argv
for name, s in CASES:
    t0 = time.perf_counter()
    r = result.respond(None, env, llm_on=False, slots=s)
    sec = time.perf_counter() - t0
    ans = r.get("answer") or {}
    blocks = {b["id"]: b["lines"] for b in ans.get("blocks", [])}
    ana = blocks.get("analysis", [])
    kinds = [x.get("kind") or "-" for x in ana]
    print(f"{name:20s} 결론: {(ans.get('conclusion') or {}).get('text', '')[:70]}")
    print(f"{'':20s} 사실 {len(blocks.get('facts', [])):2d} 분석 {len(ana):2d} {sec:5.2f}s {kinds}")
    if show:
        for x in ana:
            print("    ·", x["text"][:160])
