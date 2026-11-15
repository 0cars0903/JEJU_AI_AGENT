"""두 라벨러의 정답을 합친다(정답 기준 data/eval/answer_rubric.md 3절). 사용:
  python tools/eval/merge_labels.py            → 일치한 문항은 확정, 불일치는 data/eval/labels/dispute_<판정 모델>.jsonl로 내보냄, 일치도 출력
  python tools/eval/merge_labels.py --final    → 세 번째 모델 판정(data/eval/labels/judge_<모델>.jsonl)까지 합쳐 data/eval/general_answer_v2.jsonl 저장
일치 조건: 처리 허용 집합(accept)이 같고, 지표 허용 값이 겹치고, 동네가 같다(답함이 허용될 때). 일치하면 허용 값은 합친다.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
L = ROOT / "data" / "eval" / "labels"
GEN = ROOT / "data" / "eval" / "gen"
LABELERS = ["opus", "fable", "sonnet", "haiku"]
MODELS = ["opus", "fable", "sonnet", "haiku", "gemini"]


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def questions():
    drop = {"FB-016", "GA-096", "GA-111", "GA-246", "HK-039", "OP-021", "SN-036"}  # 기존 판정과 0.9 이상·생성기끼리 0.95 이상
    out = {}
    for f in sorted(GEN.glob("*.jsonl")):
        for g in jl(f):
            if g["id"] not in drop:
                out[g["id"]] = g
    return out


sys.path.insert(0, str(ROOT / "app"))
import qtuple as Q  # noqa: E402
# 조건은 네 묶음으로 맞춰 비교한다(라벨러마다 '여름'·'계절'처럼 적는 수준이 달랐음)
COND_GROUP = {"비": "비", "주말": "주말", "평일": "주말", "봄": "계절", "여름": "계절", "가을": "계절", "겨울": "계절", "계절": "계절",
              "성수기": "성수기", "비수기": "성수기"}


def norm_label(x):
    acc = sorted(set(x.get("accept") or []))
    bad = [d for d in (x.get("space") or []) if d not in Q.DONGS]
    return {"accept": acc, "space": sorted(x.get("space") or []), "metric_ok": sorted(set(x.get("metric_ok") or [])),
            "target_ok": sorted(set(x.get("target_ok") or [])) or None, "period": x.get("period") or None,
            "cond": sorted({COND_GROUP.get(c, c) for c in (x.get("cond") or [])}), "bad_space": bad,
            "order": x.get("order") or None, "notice": sorted(set(x.get("notice") or [])), "ambiguous": bool(x.get("ambiguous")), "why": x.get("why", "")}


def agree(a, b):
    if a["bad_space"] or b["bad_space"]:  # 행정동 목록에 없는 이름이 있으면 확정하지 않는다
        return False
    if a["accept"] != b["accept"]:
        return False
    if "답함" in a["accept"]:
        if a["space"] != b["space"]:
            return False
        if (a["metric_ok"] or b["metric_ok"]) and not set(a["metric_ok"]) & set(b["metric_ok"]):
            return False
    return True


def combine(a, b):
    m = dict(a)
    m["metric_ok"] = sorted(set(a["metric_ok"]) | set(b["metric_ok"]))
    m["target_ok"] = sorted(set(a["target_ok"] or []) | set(b["target_ok"] or [])) or None
    m["period"] = a["period"] or b["period"]
    m["cond"] = sorted(set(a["cond"]) & set(b["cond"])) if a["cond"] and b["cond"] else (a["cond"] or b["cond"])
    m["order"] = a["order"] if a["order"] == b["order"] else (a["order"] or b["order"])
    m["notice"] = sorted(set(a["notice"]) & set(b["notice"]))  # 둘 다 요구한 안내만
    m["ambiguous"] = a["ambiguous"] and b["ambiguous"]  # 두 라벨러가 모두 애매하다고 볼 때만(한쪽만이면 허용 값을 넓게 합친 것으로 충분)
    return m


def kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def main():
    Q = questions()
    lab = {m: {x["id"]: norm_label(x) for x in jl(L / f"{m}.jsonl")} for m in LABELERS}
    final, disputes, pairs = {}, {m: [] for m in MODELS}, []
    for qid, g in Q.items():
        have = [m for m in LABELERS if qid in lab[m]]
        if len(have) < 2:
            continue
        a, b = lab[have[0]][qid], lab[have[1]][qid]
        pairs.append(("|".join(a["accept"]), "|".join(b["accept"])))
        if agree(a, b):
            final[qid] = combine(a, b)
        else:
            third = next(m for m in LABELERS if m not in have and m != g["gen"])
            disputes[third].append({"id": qid, "q": g["q"], "label_a": {k: v for k, v in a.items() if k != "why"}, "label_b": {k: v for k, v in b.items() if k != "why"}})
    print(json.dumps({"문항": len(Q), "두 라벨 있음": len(pairs), "일치": len(final), "불일치": sum(len(v) for v in disputes.values()),
                      "처리 카파": kappa(pairs), "판정 모델별 불일치": {k: len(v) for k, v in disputes.items() if v}}, ensure_ascii=False))
    if "--final" not in sys.argv:
        for m, rows in disputes.items():
            if rows:
                (L / f"dispute_{m}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return
    for m in LABELERS:
        for x in jl(L / f"judge_{m}.jsonl"):
            final[x["id"]] = norm_label(x)
    rows = []
    for qid, g in Q.items():
        if qid in final:
            rows.append({"id": qid, "gen": g["gen"], "split": g["split"], "q": g["q"], "hard": g.get("hard") or [], **final[qid]})
    out = ROOT / "data" / "eval" / "general_answer_v2.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    c = Counter((r["gen"], r["split"]) for r in rows)
    print(json.dumps({"저장": str(out.relative_to(ROOT)), "문항": len(rows), "애매": sum(r["ambiguous"] for r in rows), "생성 모델·split": {f"{k[0]}·{k[1]}": v for k, v in sorted(c.items())}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
