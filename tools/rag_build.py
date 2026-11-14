"""질문 기록 색인 만들기(app/rag.py). 사용: python tools/rag_build.py [--tune]

- 종류 기록: 질문 해석 학습 문장(app/x1_embed.training_rows) → 질문 종류(T1~T15). 되묻기만 있는 문장(종류 없음)은 뺀다.
- 기법 기록: 조정용 문항 data/eval/tech_dev_24·tech_dev_052_48(기법) + tech_dev_general_60(general).
- 판정 문항(data/eval의 판정용 파일, data/x1/test_*_gold)과 같은 문장(공백·문장부호 무시)은 넣지 않는다.
- --tune: 기록 안에서 한 문장씩 빼고 이웃을 찾아(leave-one-out) 기준값(K·SIM·SHARE)을 정한다.
  목표: 이웃 투표가 기준을 넘을 때 그 투표가 맞는 비율(정밀도) 0.9 이상 중에서 적용 비율이 가장 큰 값. 판정 문항은 쓰지 않는다.
- bge-m3가 있는 Ollama가 필요하다(OLLAMA_URL로 주소 지정). 결과: models/rag_index.npz, models/rag_rows.json
"""
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import rag  # noqa: E402
import x1_embed as XE  # noqa: E402

# 판정용: 넘김 200·나누기 150·요청→기법 120(055)·질문 해석 300(test_std150·test_std150d). 052(tech_eval_48 = tech_dev_052_48)와
# test_std150b·c(일반 요청 조정용 60의 출처)는 조정용이다. 예전 실험 문항(test_gold·test_final_gold)도 보수적으로 뺀다.
JUDGE = [ROOT / "data" / "eval" / n for n in ("route_eval_200.jsonl", "split_eval_150.jsonl", "tech_route_eval_120.jsonl")] + \
        [ROOT / "data" / "x1" / n for n in ("test_std150_gold.jsonl", "test_std150d_gold.jsonl", "test_gold.jsonl", "test_final_gold.jsonl")]
TECH_DEV = ["tech_dev_24.jsonl", "tech_dev_052_48.jsonl", "tech_dev_general_60.jsonl"]


def _jsonl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def judge_set():
    s = set()
    for p in JUDGE:
        for r in _jsonl(p):
            q = r.get("q") or r.get("question")
            if q:
                s.add(rag.norm(q))
    return s


def libraries():
    bad = judge_set()
    out, dropped = {}, {}
    rows, seen = [], set()
    for q, t, _ in XE.training_rows():
        n = rag.norm(q)
        if not t.get("type") or n in seen:
            continue
        if n in bad:
            dropped["type"] = dropped.get("type", 0) + 1
            continue
        seen.add(n)
        rows.append((q, t["type"]))
    out["type"] = rows
    rows, seen = [], set()
    for name in TECH_DEV:
        for r in _jsonl(ROOT / "data" / "eval" / name):
            n = rag.norm(r["q"])
            if n in seen:
                continue
            if n in bad:
                dropped["tech"] = dropped.get("tech", 0) + 1
                continue
            seen.add(n)
            rows.append((r["q"], r.get("technique") or "general"))
    out["tech"] = rows
    return out, dropped


def tune(vec, labels, ks=(3, 5, 7), sims=(0.6, 0.65, 0.7, 0.75, 0.8, 0.85), shares=(0.5, 0.6, 0.7, 0.8, 0.9), target=0.9):
    v = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-9)
    S = v @ v.T
    np.fill_diagonal(S, -1)
    order = np.argsort(-S, axis=1)[:, :max(ks)]
    res = []
    for k, sim, share in itertools.product(ks, sims, shares):
        fire = right = 0
        for i in range(len(labels)):
            nb = [(None, labels[j], float(S[i, j])) for j in order[i, :k]]
            top, sh, _ = rag.vote(nb, sim)
            if top is not None and sh >= share:
                fire += 1
                right += top == labels[i]
        prec = right / fire if fire else 0.0
        res.append({"k": k, "sim": sim, "share": share, "fire": fire, "coverage": round(fire / len(labels), 3), "precision": round(prec, 3)})
    ok = [r for r in res if r["precision"] >= target]
    best = max(ok, key=lambda r: (r["coverage"], r["precision"])) if ok else max(res, key=lambda r: r["precision"])
    return best, res


def main():
    libs, dropped = libraries()
    arrays, meta = {}, {"built_at": time.strftime("%Y-%m-%d %H:%M"), "embed_model": XE.MODEL, "dropped_judge": dropped, "libs": {}, "param": {}, "tune": {}}
    old = json.loads(rag.ROWS.read_text(encoding="utf-8")) if rag.ROWS.exists() else {}
    for name, rows in libs.items():
        X = XE.embed([q for q, _ in rows])
        arrays[name] = X.astype(np.float16)
        meta["libs"][name] = {"q": [q for q, _ in rows], "label": [lab for _, lab in rows], "n": len(rows)}
        if "--tune" in sys.argv:
            best, _ = tune(X.astype(np.float32), [lab for _, lab in rows])
            meta["param"][name] = {k: best[k] for k in ("k", "sim", "share")}
            meta["tune"][name] = best
        else:
            meta["param"][name] = old.get("param", {}).get(name, {"k": 5, "sim": 0.8, "share": 0.6})
            meta["tune"][name] = old.get("tune", {}).get(name)
    rag.INDEX.parent.mkdir(exist_ok=True)
    np.savez_compressed(rag.INDEX, **arrays)
    rag.ROWS.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "libs"} | {"n": {k: v["n"] for k, v in meta["libs"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
