"""화면 시험의 기대값을 eval/run_eval.py의 독립 계산에서 뽑아 web/e2e/case-gold.json에 쓴다. 화면 코드는 이 값을 알지 못한다.
data/interim이 있어야 한다. 실행: .venv/bin/python tests/export_case_gold.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import run_eval  # noqa: E402

gold = {qid: {"question": q, "status": status, "tools": tools, "must": must, "mustnot": mustnot} for qid, q, status, tools, must, mustnot in run_eval.EVAL}
gold["stores"] = {d: run_eval.raw_stores(d) for d in ("노형동", "아라동", "이도2동", "연동", "애월읍")}
out = ROOT / "web" / "e2e" / "case-gold.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
print(out, len(gold))
