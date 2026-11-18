"""흐름 기법 고르기 측정(문제 기록 56번): 코드 흐름표 대 판단 모델(같은 흐름표 설명).

사용: python tools/eval/more_eval.py --split dev|judge [--labels interaction/gemini_work/065/labels_613.jsonl] [--out 결과.json] [--no-model] [--no-run]
- 정답: Gemini가 흐름 설명만 보고 붙인 accept 목록(0~3개, 빈 목록 = 붙이지 않는 것이 정답).
- 맞음: accept가 있으면 고른 기법이 accept 안에 있음, 비었으면 고르지 않음(None).
- 계산됨: 고른 기법을 실제로 계산했을 때 거부·오류 없이 결과가 나옴(--no-run이면 생략).
- judge는 문항 문장을 출력·저장하지 않는다(id와 판정만).
"""
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import more  # noqa: E402

args = sys.argv[1:]
SPLIT = args[args.index("--split") + 1] if "--split" in args else "dev"
LAB = Path(args[args.index("--labels") + 1]) if "--labels" in args else ROOT / "interaction/gemini_work/065/labels_613.jsonl"
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else None
MODEL = "--no-model" not in args
RUN = "--no-run" not in args


def main():
    qs = {x["id"]: x for x in (json.loads(l) for l in (ROOT / "data/eval/general_answer_v2.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
    labs = [json.loads(l) for l in LAB.read_text(encoding="utf-8").splitlines() if l.strip()]
    labs = [x for x in labs if x.get("split") == SPLIT and x["id"] in qs]
    rows = []
    for lb in labs:
        q = qs[lb["id"]]["q"]
        acc = [k for k in lb.get("accept") or [] if k in more.KEYS]
        s = more.slots_of(q)
        row = {"id": lb["id"], "accept": acc}
        ways = [("code", lambda: more.pick_code(q, s))] + ([("model", lambda: more.pick_model(q, s))] if MODEL else [])
        for name, fn in ways:
            t0 = time.perf_counter()
            k, why = fn()
            sec = time.perf_counter() - t0
            ok = (k in acc) if acc else (k is None)
            ran = None
            if RUN and k:
                ran = more.run(q, k, s) is not None
            row[name] = {"tech": k, "ok": ok, "ran": ran, "sec": round(sec, 2)}
            if SPLIT != "judge":
                row[name]["why"] = why
        if SPLIT != "judge":
            row["q"] = q
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    pos = [r for r in rows if r["accept"]]
    neg = [r for r in rows if not r["accept"]]
    summ = {"split": SPLIT, "n": len(rows), "정답 있음": len(pos), "빈 목록": len(neg)}
    for name in ["code"] + (["model"] if MODEL else []):
        picked = [r for r in rows if r[name]["tech"]]
        summ[name] = {
            "맞음": f"{sum(r[name]['ok'] for r in rows)}/{len(rows)}",
            "정답 있는 문항에서 맞음(재현)": f"{sum(r[name]['ok'] for r in pos)}/{len(pos)}",
            "빈 목록에서 안 붙임": f"{sum(r[name]['ok'] for r in neg)}/{len(neg)}",
            "붙인 것 중 맞음(정밀)": f"{sum(r[name]['tech'] in r['accept'] for r in picked)}/{len(picked)}",
            "계산됨(붙인 것 중)": f"{sum(bool(r[name]['ran']) for r in picked)}/{len(picked)}" if RUN else None,
            "고르기 시간 중앙값(초)": round(statistics.median(r[name]["sec"] for r in rows), 2) if rows else None,
            "고르기 시간 최대(초)": max(r[name]["sec"] for r in rows) if rows else None,
        }
    if MODEL:
        both = sum(r["code"]["ok"] and not r["model"]["ok"] for r in rows), sum(r["model"]["ok"] and not r["code"]["ok"] for r in rows)
        from math import comb
        n, b = sum(both), min(both)
        p = min(1.0, 2 * sum(comb(n, i) for i in range(b + 1)) / 2 ** n) if n else 1.0
        summ["짝 비교(코드만 맞음 / 모델만 맞음)"] = f"{both[0]} / {both[1]}, McNemar 정확 p = {p:.3g}"
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if OUT:
        OUT.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
