"""실험 X2 Agent 연결 시험 정식 실행 (docs/기획/05_Agent구조_v2.md 11-2절, 2026-11-11).

질문 10개(경로별 1~2개, Claude 작성, 블라인드 문항 아님) → M1(B3) 해석 → M2 계획 → M3 지시서 → 실행기.
측정
  ① 연결: 지시서대로 Sub가 이어서 실행되나(상태·작업별 결과)
  ② 순차 vs 병렬: 같은 지시서를 각 N회 실행, 시간 중앙값과 결과 일치(시간 칸 제외)
  ③ 오류 주입: 작업마다 오류 유형(실행·계산·표현·반출)을 넣어 의존 차단·부분 결과·재시도 상한(2회)을 확인. 지시서 형식 오류는 validate로 확인
  ④ 시간 초과: timeout_ms=0이면 부분 결과를 내고 멈추나
검수의 되돌림 경로(Sub / M2·M3 / M1)는 W7 전이라 여기서 재지 않는다. 오류 유형 기록만 확인한다.
결과: data/interim/x2/x2_result.json, 표는 표준 출력
실행: .venv/bin/python app/x2_run.py [--n 20]
"""
import copy
import json
import statistics
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m1  # noqa: E402
import planner  # noqa: E402
import qtuple as Q  # noqa: E402
import runner  # noqa: E402

QS = ["노형동 카페 몇 개야?", "노형동이랑 연동 버스 이용 비교해줘", "노형동 카페 개업 최근 3년 늘었어?", "비 오는 날 아라동 방문은?",
      "노형동 다음주 방문 예측해줘", "탑동 버스 다음달 얼마나 탈까?", "노형동이랑 비슷한 동네는?", "노형동 생활 진단해줘",
      "센터에 와이파이 자료 있어?", "노형동 카페 5년 생존율은?"]
OUT = Q.ROOT / "data" / "interim" / "x2"


def strip(store):
    """결과 비교용: 시간·시도 칸을 뺀 저장소 내용(표는 값으로)."""
    out = {}
    for k, v in store.items():
        out[k] = {kk: (vv.round(6).to_dict(orient="records") if hasattr(vv, "to_dict") else vv) for kk, vv in v.items() if kk not in ("sec", "attempts", "train_sec", "cache")}
    return json.dumps(out, ensure_ascii=False, sort_keys=True, default=str)


def main(n):
    M = m1.M1()
    rows, inj_rows = [], []
    for q in QS:
        it = M.interpret(q)
        p = planner.plan(it["tuple"], {"center_db": False})
        rec = {"q": q, "type": it["tuple"]["type"], "expect": it["tuple"]["expect"], "plan": p["status"], "m1_sec": it["sec"]}
        if p["status"] != "ok":
            rows.append(rec)
            continue
        o = runner.build_order(p)
        rec["route"] = "→".join(t["sub"] for t in o["tasks"])
        rec["schema_errors"] = runner.validate(o)
        # ① 연결 + ② 순차·병렬
        seq, par, same = [], [], True
        base = runner.run(o, {"question": q})
        rec["status"] = base["status"]
        rec["failed"] = [(x["task_id"], x.get("error_type"), x.get("error")) for x in base["log"] if x["status"] != "성공"]
        ref = strip(base["store"])
        for _ in range(n):
            t0 = time.perf_counter()
            a = runner.run(o, {"question": q})
            seq.append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            b = runner.run(o, {"question": q, "parallel": True})
            par.append(time.perf_counter() - t0)
            same = same and strip(a["store"]) == ref and strip(b["store"]) == ref
        rec.update(seq_ms=round(statistics.median(seq) * 1000, 2), par_ms=round(statistics.median(par) * 1000, 2), same=same,
                   layers=len({len(t["depends_on"]) for t in o["tasks"]}))
        # ③ 오류 주입: 작업마다 유형별
        for t in o["tasks"]:
            for kind in ("실행", "계산", "표현", "반출"):
                r = runner.run(o, {"question": q, "inject": {t["id"]: kind}})
                st = {x["task_id"]: x for x in r["log"]}
                dep = [x["id"] for x in o["tasks"] if t["id"] in x["depends_on"]]
                indep = [x["id"] for x in o["tasks"] if x["id"] != t["id"] and x["id"] not in dep and not x["depends_on"]]
                ok_retry = st[t["id"]]["attempts"] <= 2
                if kind == "실행":  # 1회 재시도로 회복해야 함
                    ok = st[t["id"]]["status"] == "성공" and st[t["id"]]["attempts"] == 2 and r["status"] == "성공"
                else:  # 실패 기록 + 의존 작업만 건너뜀 + 독립 작업은 계속
                    ok = (st[t["id"]]["status"] == "실패" and st[t["id"]].get("error_type") == kind
                          and all(st[d]["status"] == "건너뜀" for d in dep if d in st) and all(st[i]["status"] == "성공" for i in indep if i in st)
                          and r["status"] in ("부분 결과", "실패"))
                inj_rows.append({"q": q, "task": t["id"], "sub": t["sub"], "kind": kind, "ok": bool(ok and ok_retry), "status": r["status"]})
        # 지시서 형식 오류 2종 + ④ 시간 초과
        bad = copy.deepcopy(o)
        bad["tasks"][-1]["depends_on"] = ["t99"]
        clash = copy.deepcopy(o)
        if len(clash["tasks"]) > 1:
            clash["tasks"][1]["out"] = clash["tasks"][0]["out"]
        to = copy.deepcopy(o)
        to["policy"]["timeout_ms"] = 0
        rt = runner.run(to, {"question": q})
        rec.update(schema_bad_caught=bool(runner.validate(bad)) and runner.run(bad, {})["status"] == "계획 오류",
                   key_clash_caught=len(clash["tasks"]) < 2 or bool(runner.validate(clash)),
                   timeout_partial=any(x.get("reason") == "시간 초과" for x in rt["log"]))
        rows.append(rec)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "x2_result.json").write_text(json.dumps({"n": n, "runs": rows, "inject": inj_rows, "at": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("| 질문 | 해석 | 경로 | 상태 | 순차 ms | 병렬 ms | 결과 일치 | 형식 오류 검출 | 키 충돌 검출 | 시간 초과 부분 결과 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['q']} | {r['type']}/{r['expect']} | {r.get('route', r['plan'])} | {r.get('status', '-')} | {r.get('seq_ms', '-')} | {r.get('par_ms', '-')} | {r.get('same', '-')} | "
              f"{r.get('schema_bad_caught', '-')} | {r.get('key_clash_caught', '-')} | {r.get('timeout_partial', '-')} |")
    by = {}
    for x in inj_rows:
        by.setdefault(x["kind"], []).append(x["ok"])
    print("오류 주입 기대 동작 일치:", {k: f"{sum(v)}/{len(v)}" for k, v in by.items()}, "전체", f"{sum(x['ok'] for x in inj_rows)}/{len(inj_rows)}")
    bad = [x for x in inj_rows if not x["ok"]]
    if bad:
        print("불일치 예:", bad[:8])
    for r in rows:
        if r.get("failed"):
            print("실패 작업:", r["q"], r["failed"])


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 20)
