"""W8 결과 생성 측정 (2026-11-11). 질문 10개(x2_run.QS, 블라인드 문항 아님), 실제 M1(B3), LLM(Ollama qwen3:1.7b) 켬·끔.
지표: 카드 수치 대조 통과, 답 카드 칸 채움, M3-b LLM 채택(대체 사유), 전체 응답 시간(Mac, 3회 중앙값).
결과: data/interim/w8/w8_result.json (카드·해설 원문 포함)
실행: .venv/bin/python app/w8_run.py
"""
import json
import statistics
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m1  # noqa: E402
import result as R  # noqa: E402
from x2_run import QS  # noqa: E402

OUT = R.Q.ROOT / "data" / "interim" / "w8"


def main(n=3):
    M = m1.M1()
    rows = []
    for q in QS:
        rec = {"q": q}
        for on in (True, False):
            secs, last = [], None
            for _ in range(n):
                t0 = time.perf_counter()
                last = R.respond(q, llm_on=on, interpret=M.interpret)
                secs.append(time.perf_counter() - t0)
            key = "on" if on else "off"
            rec[f"sec_{key}"] = round(statistics.median(secs), 3)
            rec[f"sec_{key}_max"] = round(max(secs), 3)
            if on:
                rec["status"] = last["status"]
                c = last.get("card") or {}
                rec["number_check"] = c.get("number_check")
                rec["filled"] = {k: bool(c.get(k)) for k in ("conclusion", "evidence", "intervals", "limits", "next_questions")} if c else None
                rec["conclusion"] = c.get("conclusion")
                ex = (last.get("process") or {}).get("explain") or {}
                rec["choose"] = (last.get("choose") or {}).get("message")  # 추정할 수 없는 예외(선택필요), LLM 없음
                rec["llm_part"] = "M3-b" if ex else None
                rec["llm_by"] = ex.get("by")
                rec["llm_problems"] = ex.get("problems")
                rec["llm_text"] = ex.get("text")
                rec["llm_raw"] = ex.get("llm_raw")
                rec["llm_sec"] = ex.get("sec")
        rows.append(rec)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "w8_result.json").write_text(json.dumps({"n": n, "rows": rows, "at": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("| 질문 | 상태 | 수치 대조 | LLM 부분 | LLM 결과 | 대체 사유 | 시간 LLM 켬(최대) | 끔 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        nc = "-" if r["number_check"] is None else ("통과" if not r["number_check"] else f"실패 {r['number_check']}")
        print(f"| {r['q']} | {r['status']} | {nc} | {r['llm_part']} | {r['llm_by']} | {r['llm_problems'] or '-'} | {r['sec_on']}초({r['sec_on_max']}) | {r['sec_off']}초 |")
    used = [r for r in rows if r["llm_by"]]
    print("LLM 채택", sum(r["llm_by"] == "LLM" for r in used), "/", len(used), "· 시간 최대(켬)", max(r["sec_on_max"] for r in rows), "초")


if __name__ == "__main__":
    main()
