"""지명 해석 비교 실험(2026-11-11, docs/조사/15_지명해석_실험.md): 기존(old) / 규칙(rule) / 형태소(kiwi).

자료: data/x1/place_traps.jsonl(Claude 작성 32문장: 일상어 함정 16 + 짧은 지명·별칭 16),
      data/x1/b1_train·b1b_train·bank.jsonl(학습용 질문, 동네 정답 칸). 블라인드 시험 문항(test_*)은 쓰지 않는다.
지표: 동네 칸 완전 일치율(정답 동네 집합과 같음), 함정 문장의 엉뚱한 동네 수, 질문당 처리 시간.
실행: .venv/bin/python app/place_eval.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qparse  # noqa: E402

X1 = Path(__file__).resolve().parents[1] / "data" / "x1"


def load(name, key="space"):
    rows = []
    for line in (X1 / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append({"q": r["q"], "space": r.get("space", r.get("tuple", {}).get("space")) or [], "kind": r.get("kind")})
    return rows


def score(rows, mode):
    ok, extra, t0 = 0, 0, time.perf_counter()
    miss = []
    for r in rows:
        got, _ = qparse.find_places(r["q"], mode)
        if set(got) == set(r["space"]):
            ok += 1
        else:
            miss.append((r["q"], r["space"], got))
        extra += len(set(got) - set(r["space"]))
    return {"n": len(rows), "match": ok, "rate": round(ok / len(rows), 4), "extra_dongs": extra, "ms_per_q": round((time.perf_counter() - t0) / len(rows) * 1000, 3), "miss": miss}


def main():
    qparse.find_places("워밍업", "kiwi")  # 모델 불러오기 시간은 따로 잰다
    traps = load("place_traps.jsonl")
    sets = {"함정(trap)": [r for r in traps if r["kind"] == "trap"], "짧은 지명(legit)": [r for r in traps if r["kind"] == "legit"],
            "b1_train": load("b1_train.jsonl"), "b1b_train": load("b1b_train.jsonl"), "bank": load("bank.jsonl")}
    out = {}
    for name, rows in sets.items():
        out[name] = {m: score(rows, m) for m in ("old", "rule", "kiwi")}
        print(f"| {name} | " + " | ".join(f"{m} {v['match']}/{v['n']} (+{v['extra_dongs']}, {v['ms_per_q']}ms)" for m, v in out[name].items()) + " |")
    for name in ("함정(trap)", "짧은 지명(legit)"):
        for m in ("old", "rule", "kiwi"):
            for q, g, got in out[name][m]["miss"]:
                print(f"  [{name} {m}] {q} 정답 {g} → {got}")
    for name in ("b1_train", "b1b_train", "bank"):
        for m in ("rule", "kiwi"):
            lost = [x for x in out[name][m]["miss"] if x[0] not in {y[0] for y in out[name]["old"]["miss"]}]
            print(f"  [{name} {m}] 기존이 맞히고 새 방식이 틀린 질문 {len(lost)}개, 예: {lost[:4]}")
    path = Path(__file__).resolve().parents[1] / "data" / "interim" / "place_eval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: {m: {kk: vv for kk, vv in v.items() if kk != "miss"} | {"miss": v["miss"][:30]} for m, v in d.items()} for k, d in out.items()}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
