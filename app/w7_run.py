"""W7 검수 오류 주입 측정 (docs/기획/05_Agent구조_v2.md 11-2절 ③ 되돌림 경로, X2에서 W7 뒤로 미룬 항목, 2026-11-11).

질문 10개(x2_run.QS, 블라인드 문항 아님) × 주입 7종. 해석은 실제 M1(B3).
  해석: 질문 Tuple 지표 칸을 목록 밖 값으로 → 기대 M1
  계획: 지시서 마지막 작업 depends_on을 없는 작업으로 → 기대 M2·M3
  실행: 첫 조회 작업에 실행 오류 1회 → 기대 Sub 안에서 1회 재실행으로 회복(검수 기록 없음)
  실행(센터 미연결): center_db=True로 센터 경로 계획 → 기대 M2·M3(공개 경로 재계획)
  계산: 마지막 S1 다음 작업(없으면 첫 작업)에 계산 오류 → 기대 Sub(실패 작업과 의존 작업만 재실행)
  표현: 결과에 없는 숫자 문장 → 기대 검수(템플릿 대체)
  반출: 첫 조회를 반출 불가로 표시하고 원자료 열을 섞음 → 기대 검수(행 제거)
지표: 되돌림 경로 적중, 재시도 횟수, 상한(Sub 1·Main 1·누적 2) 준수, 최종 상태, 답에 주입 흔적이 남지 않음.
결과: data/interim/w7/w7_result.json (검수 기록 포함)
실행: .venv/bin/python app/w7_run.py
"""
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m1  # noqa: E402
import verify as V  # noqa: E402
from x2_run import QS  # noqa: E402

OUT = V.Q.ROOT / "data" / "interim" / "w7"


def cases(order0):
    tasks = order0["tasks"]
    calc_t = next((t["id"] for t in tasks if t["sub"] != "S1"), tasks[0]["id"])

    def broken(o):
        o["tasks"][-1]["depends_on"] = ["t99"]
        return o

    def restrict(o):
        o["tasks"][0]["export_restricted"] = True
        return o

    def leak(order, res):
        k = order["tasks"][0]["out"]
        v = res["store"].get(k)
        if v is not None and "table" in v:
            v["table"] = v["table"].assign(raw_id="X").loc[v["table"].index.repeat(2)].reset_index(drop=True)
    return [
        ("해석", "M1", {"tuple_override": lambda t: dict(t, metric=["없는지표"])}),
        ("계획", "M2·M3", {"order_hook": broken}),
        ("실행", "Sub(내부 재실행)", {"env": {"center_db": False, "inject": {tasks[0]["id"]: "실행"}}}),
        ("실행(센터 미연결)", "M2·M3", {"env": {"center_db": True}}),
        ("계산", "Sub", {"env": {"center_db": False, "inject": {calc_t: "계산"}}}),
        ("표현", "검수", {"answer_fn": lambda o, r: "결과는 98765입니다."}),
        ("반출", "검수", {"order_hook": restrict, "store_hook": leak}),
    ]


def hit(kind, want, r):
    rt = [x["route"] for x in r["record"] if x["type"] in V.ROUTE]
    if kind == "실행":
        log = r["run"]["log"] if r["run"] else []
        return any(x.get("attempts") == 2 and x["status"] == "성공" for x in log) and not rt
    if kind == "실행(센터 미연결)":
        centered = any(x.get("route") == "center" for x in r.get("order_first", {}).get("tasks", []))
        return (want in rt) if centered else (not rt)  # 센터 경로가 없는 질문은 되돌릴 일이 없어야 한다
    return want in rt


def main():
    M = m1.M1()
    rows = []
    for q in QS:
        base = V.review(q, interpret=M.interpret)
        if base["status"] in ("되묻기", "범위밖") or not base.get("order"):
            rows.append({"q": q, "kind": "-", "status": base["status"], "note": "M1 단계에서 실행하지 않음"})
            continue
        for kind, want, kw in cases(base["order"]):
            env = kw.pop("env", None)
            first = {}
            if kind == "실행(센터 미연결)":
                p = V.planner.plan(base["tuple"], {"center_db": True})
                first = V.runner.build_order(p)
            t0 = time.perf_counter()
            r = V.review(q, env, interpret=M.interpret, **kw)
            r["order_first"] = first
            ans = r.get("answer") or ""
            rows.append({"q": q, "kind": kind, "want": want, "hit": hit(kind, want, r), "status": r["status"], "retries": r["retries"],
                         "limit_ok": all(r["retries"][k] <= V.LIMIT[k] for k in V.LIMIT), "clean": "98765" not in ans and "raw_id" not in ans,
                         "record": r["record"], "sec": round(time.perf_counter() - t0, 3)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "w7_result.json").write_text(json.dumps({"rows": rows, "at": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    run = [x for x in rows if x["kind"] != "-"]
    print("| 주입 | 기대 되돌림 | 적중 | 상한 준수 | 답에 흔적 없음 | 최종 상태 |")
    print("|---|---|---|---|---|---|")
    for kind in dict.fromkeys(x["kind"] for x in run):
        g = [x for x in run if x["kind"] == kind]
        st = {}
        for x in g:
            st[x["status"]] = st.get(x["status"], 0) + 1
        print(f"| {kind} | {g[0]['want']} | {sum(x['hit'] for x in g)}/{len(g)} | {sum(x['limit_ok'] for x in g)}/{len(g)} | {sum(x['clean'] for x in g)}/{len(g)} | {st} |")
    print("전체 적중", f"{sum(x['hit'] for x in run)}/{len(run)}", "· 실행 안 한 질문", [(x["q"], x["status"]) for x in rows if x["kind"] == "-"])
    for x in run:
        if not x["hit"]:
            print("불일치:", x["q"], x["kind"], x["status"], [(y["type"], y["route"], y["detail"]) for y in x["record"]][:4])


if __name__ == "__main__":
    main()
