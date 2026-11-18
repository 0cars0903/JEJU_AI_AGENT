"""흐름 기법 방식 비교(문제 기록 59번): 코드 표 / 예시 증류(examples) / 분석 질문 생성 + 카드 검색 + 의미 정렬(agent).

사용: python tools/eval/flow_eval.py --split dev|judge --methods code,examples,agent [--labels ...] [--out 결과.json]
- 답에 실제로 보인 기법(계산 성공, agent는 의미 점수 0.35 이상 상위 2개)을 기준으로 잰다.
- 정밀: 보인 기법 중 Gemini 정답 목록(accept, 065)에 든 비율. 적중: 정답이 있는 문항에서 보인 기법 중 하나라도 정답. 안 붙임: 정답이 빈 문항에서 아무것도 안 보임.
- 다채로움: 문항당 보인 기법 수, 전체에서 쓴 기법 종류 수와 분포 엔트로피(비트).
- 쓸모 판정용으로 질문·기법·결론 문장을 저장한다(judge는 저장하지 않고 id·기법만, 쓸모 판정은 하위 에이전트가 원문을 읽는다).
"""
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import more  # noqa: E402

args = sys.argv[1:]
SPLIT = args[args.index("--split") + 1] if "--split" in args else "dev"
METHODS = (args[args.index("--methods") + 1] if "--methods" in args else "code,examples,agent").split(",")
LAB = Path(args[args.index("--labels") + 1]) if "--labels" in args else ROOT / "interaction/gemini_work/065/labels_613.jsonl"
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else None


def ent(c):
    n = sum(c.values())
    return round(-sum(v / n * math.log2(v / n) for v in c.values()), 2) if n else 0.0


def main():
    qs = {x["id"]: x for x in (json.loads(l) for l in (ROOT / "data/eval/general_answer_v2.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
    labs = [x for x in (json.loads(l) for l in LAB.read_text(encoding="utf-8").splitlines() if l.strip()) if x.get("split") == SPLIT and x["id"] in qs]
    rows = []
    for lb in labs:
        q = qs[lb["id"]]["q"]
        acc = [k for k in lb.get("accept") or [] if k in more.KEYS]
        s = more.slots_of(q)
        row = {"id": lb["id"], "accept": acc, "q": q}
        for m in METHODS:
            t0 = time.perf_counter()
            techs, why, subqs = more.choose(q, s, m)
            t1 = time.perf_counter() - t0
            got = more.compute(q, techs, s, m)
            row[m] = {"chosen": techs, "shown": [t for t, _, _ in got], "pick_sec": round(t1, 2), "sec": round(time.perf_counter() - t0, 2),
                      "concl": [g[0][0]["text"] for _, g, _ in got], "subqs": subqs, "why": why}
        rows.append(row)
        print(json.dumps({"id": row["id"], **{m: row[m]["shown"] for m in METHODS}}, ensure_ascii=False), flush=True)
    pos = [r for r in rows if r["accept"]]
    neg = [r for r in rows if not r["accept"]]
    summ = {"split": SPLIT, "n": len(rows), "정답 있음": len(pos), "빈 목록": len(neg)}
    for m in METHODS:
        shown = [t for r in rows for t in r[m]["shown"]]
        c = Counter(shown)
        summ[m] = {
            "정밀(보인 기법 중 정답)": f"{sum(t in r['accept'] for r in rows for t in r[m]['shown'])}/{len(shown)}",
            "적중(정답 있는 문항)": f"{sum(any(t in r['accept'] for t in r[m]['shown']) for r in pos)}/{len(pos)}",
            "안 붙임(빈 목록 문항)": f"{sum(not r[m]['shown'] for r in neg)}/{len(neg)}",
            "문항당 보인 기법 평균": round(len(shown) / len(rows), 2) if rows else 0,
            "기법 2개 보인 문항": sum(len(r[m]["shown"]) >= 2 for r in rows),
            "쓴 기법 종류": len(c), "엔트로피(비트)": ent(c), "분포": dict(c.most_common()),
            "고르기 시간 중앙값·최대(초)": [round(statistics.median(r[m]["pick_sec"] for r in rows), 2), max(r[m]["pick_sec"] for r in rows)],
            "전체 시간 중앙값(초)": round(statistics.median(r[m]["sec"] for r in rows), 2),
        }
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if OUT:
        if SPLIT == "judge":  # 판정 문항 문장은 저장하지 않는다(쓸모 판정은 하위 에이전트가 원문 파일에서 읽음)
            for r in rows:
                r.pop("q", None)
                for m in METHODS:
                    r[m].pop("subqs", None)
                    r[m].pop("why", None)
        OUT.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
