"""실험 X1 채점: 방식별로 시험 54문항(data/x1/test_gold.jsonl)의 질문 Tuple을 만들고 정답과 대조한다.

핵심 정답 = type(되묻기 문항은 제외) · expect · space(집합 일치) · target(허용 집합, 채점 대상일 때) 모두 맞음.
보조: 칸별 적중, metric 허용 집합 교집합, JSON 형식 성공률, 응답 시간 중앙값. 방식 간 비교는 같은 문항 짝 비교(McNemar 정확 검정).
실행: .venv/bin/python app/x1_eval.py A AB [L:qwen3:1.7b] [AL:qwen3:1.7b] [C] [LR(LoRA, app/x1_lora_eval.py 먼저)]
"""
import json
import statistics
import time
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402
import x1_methods as M  # noqa: E402

GOLD = Q.ROOT / "data" / "x1" / ("test_std150d_gold.jsonl" if "--std150d" in sys.argv else "test_std150c_gold.jsonl" if "--std150c" in sys.argv else "test_std150b_gold.jsonl" if "--std150b" in sys.argv else "test_std150_gold.jsonl" if "--std150" in sys.argv else "test_final_gold.jsonl" if "--final" in sys.argv else "test_gold.jsonl")
OUTD = Q.ROOT / "data" / "x1" / "results"


def score(t, g):
    alt = "--alt" in sys.argv and t.get("expect") in g.get("expect_alt", [])
    s = {"type": g["type"] is None or t.get("type") == g["type"] or alt, "expect": t.get("expect") == g["expect"] or alt,
         "space": sorted(t.get("space") or []) == g["space"] or g["expect"] == "범위밖",
         "target": g["target_ok"] is None or (t.get("target") or "") in g["target_ok"] or any(x in g["target_ok"] for x in (t.get("_targets") or [])),
         "metric": g["metric_ok"] is None or bool(set(t.get("metric") or []) & set(g["metric_ok"]))}
    s["core"] = s["type"] and s["expect"] and s["space"] and s["target"]
    return s


def mcnemar(a, b):
    """같은 문항 짝: a만 맞음 n10, b만 맞음 n01. 양측 정확 이항 검정 p."""
    n10 = sum(x and not y for x, y in zip(a, b))
    n01 = sum(y and not x for x, y in zip(a, b))
    n = n10 + n01
    if n == 0:
        return n10, n01, 1.0
    k = min(n10, n01)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    return n10, n01, round(p, 4)


def _lora_raw():
    """LoRA 원출력(app/x1_lora_eval.py가 LoRA 가상환경에서 저장) → id별 {text, sec}."""
    test = GOLD.name[len("test_"):-len("_gold.jsonl")]
    f = OUTD / f"LR_{test}_raw.jsonl"
    return {r["id"]: r for r in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if r}


def run(name, gold):
    bank = M.Bank() if name == "AB" else None
    lraw = _lora_raw() if name == "LR" else None
    emb = None
    if name.startswith("E"):
        import x1_embed
        emb = x1_embed.EmbedParser(use={"Etpl": ("template",), "Eb1": ("template", "b1")}.get(name, ("template", "b1", "b1b")))
    kind, _, model = name.partition(":")
    out = []
    for g in gold:
        _t0 = time.perf_counter()
        if kind == "A":
            t = M.rule_parse(g["q"])
        elif kind == "A2":
            import qparse_a2
            t = qparse_a2.parse(g["q"])
        elif kind == "A2p":
            import qparse
            t = qparse.parse(g["q"])
        elif kind == "AB":
            t = bank.parse(g["q"])
        elif kind == "L":
            t = M.llm_parse(g["q"], model)
        elif kind == "Lfs":
            t = M.llm_parse(g["q"], model, fewshot=True)
        elif kind == "AL":
            t = M.llm_fill_parse(g["q"], model)
        elif kind == "ALfs":
            t = M.llm_fill_parse(g["q"], model, fewshot=True)
        elif kind in ("E", "Etpl", "Eb1"):
            t = emb.parse(g["q"])
        elif kind == "S":
            t = M.schema_parse(g["q"], model or "qwen3:1.7b")
        elif kind == "LR":  # LoRA: 저장된 원출력을 같은 규칙(coerce)으로 Tuple로 바꾸고, 시간은 추론 때 잰 값을 쓴다
            r = lraw[g["id"]]
            try:
                o, ok = json.loads(r["text"]), True
            except ValueError:
                o, ok = {}, False
            t = M.coerce(o)
            t["_json_ok"], t["_sec"] = ok and isinstance(o, dict), r["sec"]
        else:
            raise ValueError(name)
        t["_wall"] = t["_sec"] if kind == "LR" else round(time.perf_counter() - _t0, 4)  # 질의 해석 1건 처리 시간(초). 시간 기준: 0.5초 이하(사용자 결정 2026-11-11)
        out.append({"id": g["id"], "pred": {k: v for k, v in t.items()}, "score": score(t, g)})
    return out


def main():
    gold = [json.loads(x) for x in GOLD.read_text(encoding="utf-8").splitlines() if x.strip()]
    ex = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--exclude=")), None)
    if ex:  # 제주어 문항 제외(사용자 결정 2026-11-11). 파일: id 목록(jsonl의 jeju=true)
        drop = {json.loads(x)["id"] for x in Path(ex).read_text(encoding="utf-8").splitlines() if x.strip() and json.loads(x).get("jeju")}
        gold = [g for g in gold if g["id"] not in drop]
        print("제주어 제외:", len(drop), "문항, 남은 문항", len(gold))
    OUTD.mkdir(parents=True, exist_ok=True)
    res = {}
    for name in [a for a in sys.argv[1:] if not a.startswith("--")] or ["A", "AB"]:
        res[name] = run(name, gold)
        (OUTD / f"{name.replace(':', '_')}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in res[name]) + "\n", encoding="utf-8")
    keys = ["core", "type", "expect", "space", "target", "metric"]
    print("| 방식 | " + " | ".join(keys) + " | JSON 성공 | 시간 중앙값(초) | 해석 시간 중앙값·90%(초) | 0.5초 기준 |")
    for name, rs in res.items():
        cells = [f"{sum(r['score'][k] for r in rs)}/{len(rs)}" for k in keys]
        js = [r["pred"].get("_json_ok") for r in rs if "_json_ok" in r["pred"]]
        sec = [r["pred"]["_sec"] for r in rs if "_sec" in r["pred"]]
        wall = sorted(r["pred"]["_wall"] for r in rs)
        p50, p90 = statistics.median(wall), wall[int(len(wall) * 0.9) - 1]
        print(f"| {name} | " + " | ".join(cells) + f" | {sum(js)}/{len(js) if js else '-'} | {statistics.median(sec) if sec else '-'} | {p50:.3f}·{p90:.3f} | {'통과' if p90 <= 0.5 else '초과'} |")
    names = list(res)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = [r["score"]["core"] for r in res[names[i]]]
            b = [r["score"]["core"] for r in res[names[j]]]
            print(f"McNemar {names[i]} vs {names[j]}: 앞만 맞음 {mcnemar(a, b)[0]}, 뒤만 맞음 {mcnemar(a, b)[1]}, p={mcnemar(a, b)[2]}")
    # 유형별 핵심 정답(맨 앞 방식 기준 비교용)
    by = {}
    for name, rs in res.items():
        for r, g in zip(rs, gold):
            key = g["type"] or g["expect"]
            by.setdefault(key, {}).setdefault(name, []).append(r["score"]["core"])
    print("유형별 핵심 정답:", {k: {n: f"{sum(v)}/{len(v)}" for n, v in d.items()} for k, d in sorted(by.items())})


if __name__ == "__main__":
    main()
