"""확인 카드 오답 판단 방식 비교 실험(2026-11-17 문제 기록 50번, 마스터 '29번 검토: 두 값 고르기는 오답에도 확률이 높을 수 있다').

사용: python tools/eval/confcard_eval.py --set first|service [--out 결과.json] [--limit N]
- 자료: 조정용 일반 질문(general_answer_v2.jsonl, split dev, 애매 제외). 판정 문항은 쓰지 않는다.
- --set first: 보정 규칙을 끈 첫 해석의 답(result.respond, RULE_FIX=False). 오답이 많아 '오답을 잡는 능력'을 잰다.
- --set service: 서비스 최종 답(step_agent.serve). 오답이 적어 '정답을 잘못 멈추는 비율'을 잰다.
- 판단 방식(같은 답에 셋 다 적용, 모델 qwen2.5:7b):
  YN(기준선, 29번에서 기각): '이 처리가 질문에 맞는가' Y·N, 확신도 = Y 확률
  A: '처리가 질문과 다른 요소'를 7개(동네·지표·업종·기간·조건·범위·없음) 중 하나로 고름, 확신도 = '없음' 확률
  B: 모델이 시스템 답을 보지 않고 질문만 읽어 동네·지표·업종·답할 수 있는지를 고르고, 코드가 시스템 해석과 견줘 하나라도 다르면 멈춤
- 정답 여부는 general_answer.score의 '정답'(완전 정답)으로 정한다.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "eval"))
args = sys.argv[1:]
SET = args[args.index("--set") + 1] if "--set" in args else "first"
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else None
LIMIT = int(args[args.index("--limit") + 1]) if "--limit" in args else None

import general_answer as GA  # noqa: E402
import qparse  # noqa: E402
import question_agent as QA  # noqa: E402

S_A = ("너는 제주빅데이터센터 상담 결과를 검토하는 담당자다. 도민 질문과 시스템 처리를 보고, 처리가 질문과 가장 크게 다른 요소 하나를 고른다.\n"
       "A 동네(질문의 동네와 다르거나 빠짐)\nB 지표(물은 값과 다른 값을 답함)\nC 업종\nD 기간(물은 해·달·최근 몇 개월과 다름)\n"
       "E 조건(비·주말·계절·성수기 등)\nF 범위(자료로 답할 수 없는 질문을 답했거나, 답할 수 있는 질문을 범위 밖으로 냄)\nG 없음(모두 질문과 맞음)\n"
       "choice에 글자 하나, reason에 이유 한 문장.")
SCHEMA_A = {"type": "object", "required": ["choice", "reason"],
            "properties": {"choice": {"type": "string", "enum": list("ABCDEFG")}, "reason": {"type": "string"}}}
METRIC_CODES = [m for m, _ in QA.MAIN_METRICS]
S_B = ("너는 도민 질문을 읽고 무엇을 물었는지 적는 담당자다. 시스템 답은 보지 않고 질문만 보고 고른다.\n"
       "dongs: 질문에 나온 제주 동네·읍면·지명(없으면 빈 목록). metric: 아래 지표 이름 중 질문이 물은 것 하나(맞는 것이 없으면 '없음').\n"
       + "\n".join(f"- {m}: {d}" for m, d in QA.MAIN_METRICS) +
       "\nbiz: 질문의 업종 낱말(없으면 빈 문자열). answerable: 이 서비스(제주 동네의 가게 수·카드 매출·방문·개폐업·생존율·버스 공개 자료)로 답할 수 있으면 Y, "
       "맛집·가게 추천·후기·임대료·시세·개인 정보·제주 밖·미래 매출 금액처럼 자료로 답할 수 없으면 N.")
SCHEMA_B = {"type": "object", "required": ["dongs", "metric", "biz", "answerable"],
            "properties": {"dongs": {"type": "array", "items": {"type": "string"}}, "metric": {"type": "string", "enum": METRIC_CODES + ["없음"]},
                           "biz": {"type": "string"}, "answerable": {"type": "string", "enum": ["Y", "N"]}}}
FOOD_SUB = GA.FOOD_SUB


def judge_yn(q, r):
    p, _ = QA.advise(q, r)
    return p


def judge_a(q, r):
    d, p = QA._ask_choice(None, S_A, f"질문: {q}\n{QA.summary(r)}", SCHEMA_A, list("ABCDEFG"))
    return (p or {}).get("G", 1.0 if d.get("choice") == "G" else 0.0) if (p or d) else None, d.get("choice")


def judge_b(q, r):
    d, _ = QA._ask_choice(None, S_B, f"질문: {q}", SCHEMA_B, ["Y", "N"], key="answerable")
    if not d:
        return None, []
    t = r.get("tuple") or {}
    out = r.get("status") == "범위밖"
    miss = []
    if (d.get("answerable") == "N") != out:
        miss.append("범위")
    if not out and d.get("answerable") == "Y" and GA.status_of(r) == "답함":
        md = set(qparse.find_places(" ".join(str(x) for x in d.get("dongs") or []))[0])
        if md and md != set(t.get("space") or []) and not (md <= set(t.get("space") or []) and len(t.get("space") or []) > len(md) and t.get("type") in ("T3", "T2")):
            miss.append("동네")
        m = d.get("metric")
        got = set(t.get("metric") or []) or (GA.DIAG_METRICS if t.get("type") == "T10" else set())
        if m and m != "없음" and m not in got:
            miss.append("지표")
        b = str(d.get("biz") or "").strip()
        tg = qparse.find_targets(b) if b else []
        if tg and t.get("target") != tg[0] and not (tg[0] in FOOD_SUB and t.get("target") == "음식점") and not (t.get("target") in FOOD_SUB and tg[0] == "음식점"):
            miss.append("업종")
    return d, miss


def auc(pos, neg):
    """정답(pos)의 확신도가 오답(neg)보다 높을 확률(같으면 0.5)."""
    if not pos or not neg:
        return None
    s = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(s / (len(pos) * len(neg)), 3)


def stops(rows, key, th=None):
    if th is None:
        st = [r for r in rows if r[key]]
    else:
        st = [r for r in rows if r[key] is not None and r[key] < th]
    wrong = [r for r in rows if not r["ok"]]
    caught = [r for r in st if not r["ok"]]
    return {"멈춤": len(st), "멈춘 문항 오답": f"{len(caught)}/{len(st)}", "잡은 오답": f"{len(caught)}/{len(wrong)}"}


def main():
    import result
    items = [json.loads(x) for x in (ROOT / "data" / "eval" / "general_answer_v2.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    items = [g for g in items if g.get("split") == "dev" and not g.get("ambiguous")][:LIMIT]
    if SET == "first":
        result.RULE_FIX = False
        ask = lambda q: result.respond(q, {}, llm_on=False)  # noqa: E731
    else:
        import step_agent
        ask = lambda q: step_agent.serve(q, {}, llm_on=False)  # noqa: E731
    rows = []
    for g in items:
        try:
            r = ask(g["q"])
        except Exception as e:  # noqa: BLE001
            r = {"status": f"오류:{type(e).__name__}"}
        ok = GA.score(r, g)["정답"]
        t0 = time.perf_counter()
        yn = judge_yn(g["q"], r)
        t1 = time.perf_counter()
        a, a_pick = judge_a(g["q"], r)
        t2 = time.perf_counter()
        bd, bmiss = judge_b(g["q"], r)
        t3 = time.perf_counter()
        qa = r.get("question_agent") or {}
        margin = min([x.get("margin") for x in qa.get("turns", []) if x.get("margin") is not None] or [None]) if qa.get("turns") else None
        row = {"id": g["id"], "ok": ok, "status": r.get("status"), "yn": yn, "a": a, "a_pick": a_pick, "b_miss": bmiss, "b": bd,
               "pause_now": bool((r.get("confirm") or {}).get("pause")), "margin": margin,
               "sec": {"yn": round(t1 - t0, 2), "a": round(t2 - t1, 2), "b": round(t3 - t2, 2)}}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("id", "ok", "yn", "a", "a_pick", "b_miss")}, ensure_ascii=False), flush=True)
    pos, neg = [r for r in rows if r["ok"]], [r for r in rows if not r["ok"]]
    summ = {"set": SET, "n": len(rows), "정답": len(pos), "오답": len(neg),
            "YN AUC": auc([r["yn"] for r in pos if r["yn"] is not None], [r["yn"] for r in neg if r["yn"] is not None]),
            "A AUC": auc([r["a"] for r in pos if r["a"] is not None], [r["a"] for r in neg if r["a"] is not None]),
            "YN 0.5 미만 멈춤": stops(rows, "yn", 0.5), "A 0.5 미만 멈춤": stops(rows, "a", 0.5), "B 불일치 멈춤": stops(rows, "b_miss"),
            "B 불일치 요소": {k: sum(k in r["b_miss"] for r in rows) for k in ("범위", "동네", "지표", "업종")},
            "A가 고른 요소(오답 문항)": {k: sum(r["a_pick"] == k for r in neg) for k in "ABCDEFG"},
            "지연 중앙값(초)": {k: sorted(r["sec"][k] for r in rows)[len(rows) // 2] for k in ("yn", "a", "b")}}
    if SET == "service":
        summ["지금 확인 카드 멈춤"] = stops([dict(r, now=r["pause_now"]) for r in rows], "now")
    for th in (0.3, 0.7, 0.9):
        summ[f"A {th} 미만 멈춤"] = stops(rows, "a", th)
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if OUT:
        OUT.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
