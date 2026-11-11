"""W4 작업 지시서 + 실행기 최소판 (docs/기획/05_Agent구조_v2.md 4-2절·4-4절, 2026-11-11 구현).

- build_order(plan): M2 실행 계획 → 작업 지시서(JSON). task마다 id·sub·op·in/out·depends_on, 정책(timeout_ms, on_task_failure).
- validate(order): 실행 전 스키마 검사(형식 오류는 M3로 되돌림, 검수의 '계획 오류').
- run(order, env): 공유 저장소(blackboard)에 out 이름으로 결과를 쓰고 다음 작업이 in으로 읽는다. 결과마다 출처(task_id·상태·오류 유형·자료·행 수·반출)를 붙인다.
  · 실패하면 그 작업과 그 작업에 의존하는 작업만 건너뛴다(partial). 실행 오류는 같은 작업을 1회 다시 실행한다.
  · 기본은 순차 실행. env["parallel"]=True면 의존 관계가 없는 작업을 스레드로 함께 돌린다(실험 X2에서 시간 비교).
  · env["inject"]={task_id: 오류 유형}으로 오류를 주입한다(실험 X2).
- 이번 최소판의 Sub 범위: S0 자료 탐색, S1 공개 경로 조회(지표 사전의 표), S2 기술 통계·추세, S2 학습 전 점검, S3 레시피 R1~R7(app/recipes.py, W5), R8·R9는 센터 전용, S4 차트 명세, S5 통과, S6 판정.
  센터 경로(S1 center)는 W9 어댑터 전이라 '센터 DB 미연결' 실행 오류로 처리한다.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402
import recipes  # noqa: E402
import s6  # noqa: E402
from places import REST_MAP  # noqa: E402

TAB = Q.ROOT / "data" / "tables"
SUBS = {"S0", "S1", "S2", "S3", "S4", "S5", "S6"}
ERR = ["해석", "계획", "실행", "계산", "표현", "반출"]


class TaskError(Exception):
    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind = kind


# ---------- 작업 지시서 ----------
def build_order(plan, timeout_ms=30000, on_failure="partial"):
    tasks, prev_s1, last = [], [], None
    for i, st in enumerate(plan.get("steps", []), 1):
        tid = f"t{i}"
        task = {"id": tid, "sub": st["sub"], "op": st.get("op"), "out": f"r{i}"}
        for k in ("metric", "route", "source", "filter", "breakdown", "recipe", "dataset", "instead_of"):
            if k in st:
                task[k] = st[k]
        if st["sub"] == "S1":  # 반출 불가 자료 표시(원자료 행 차단의 근거, 검수 '반출 위반')
            task["export_restricted"] = isinstance(st.get("source"), dict) and st["source"].get("export") == "불가능"
        if st["sub"] in ("S0", "S1"):
            task["in"], task["depends_on"] = [], []
            prev_s1.append(task["out"])
        else:  # 후속 단계는 앞선 조회 결과 전부와 직전 단계를 입력으로 받는다
            ins = list(prev_s1) + ([last] if last and last not in prev_s1 else [])
            f = next((x.get("filter") for x in tasks if x["sub"] == "S1" and x.get("filter")), None)
            if f and "filter" not in task:
                task["filter"] = f  # 동네·업종 조건을 후속 단계(S3 등)에도 전달
            task["in"] = ins
            task["depends_on"] = [t["id"] for t in tasks if t["out"] in ins]
        tasks.append(task)
        last = task["out"]
    return {"policy": {"timeout_ms": timeout_ms, "on_task_failure": on_failure}, "tasks": tasks, "relaxed": plan.get("relaxed", []), "notes": plan.get("notes", [])}


def validate(order):
    errs, ids, outs = [], set(), set()
    if order.get("policy", {}).get("on_task_failure") not in ("abort", "partial"):
        errs.append("policy.on_task_failure")
    for t in order.get("tasks", []):
        if t.get("sub") not in SUBS:
            errs.append(f"{t.get('id')}: sub")
        if t.get("id") in ids:
            errs.append(f"{t.get('id')}: id 중복")
        if t.get("out") in outs:
            errs.append(f"{t.get('id')}: out 키 충돌")
        if any(d not in ids for d in t.get("depends_on", [])):
            errs.append(f"{t.get('id')}: depends_on이 앞선 작업이 아님")
        ids.add(t.get("id"))
        outs.add(t.get("out"))
    return errs


# ---------- Sub 최소판 ----------
def _foods(target):
    return REST_MAP.get(target) if target in REST_MAP and REST_MAP.get(target) else None


def s1_query(task, store, env):
    if task.get("route") == "center":
        raise TaskError("실행", "센터 DB 미연결(W9 어댑터 전)")
    m, f = task["metric"], task.get("filter") or {}
    dongs = f.get("dong") if isinstance(f.get("dong"), list) else None
    tgt = f.get("target")

    def by_dong(df):
        return df[df["dong"].isin(dongs)] if dongs else df
    if m in ("점포수", "특화계수"):
        b = pd.read_parquet(TAB / "biz.parquet")
        sub = b[b["minor"].str.contains(tgt, na=False) | b["middle"].str.contains(tgt, na=False) | b["major"].str.contains(tgt, na=False)] if tgt and tgt not in ("음식점",) else (b[b["major"] == "음식"] if tgt == "음식점" else b)
        out = by_dong(sub).groupby("dong")["count"].sum().rename("value").reset_index()
        if m == "특화계수":
            tot = b.groupby("dong")["count"].sum()
            share = sub.groupby("dong")["count"].sum() / tot
            out = by_dong((share / (sub["count"].sum() / b["count"].sum())).rename("value").reset_index().rename(columns={"index": "dong"}))
        return {"table": out, "dataset": "793 상가", "unit": "곳" if m == "점포수" else "배"}
    if m in ("개업수", "폐업수"):
        e = pd.read_parquet(TAB / "rest_events.parquet")
        e = e[e["kind"] == ("open" if m == "개업수" else "close")]
        cats = _foods(tgt)
        if cats:
            e = e[e["category"].isin(cats)]
        out = by_dong(e[e["year"] >= 2015]).groupby(["dong", "year"])["count"].sum().rename("value").reset_index()
        return {"table": out, "dataset": "780 음식점 인허가", "unit": "곳/년"}
    if m == "폐업률":
        return {"table": by_dong(pd.read_parquet(TAB / "close_3y.parquet")).rename(columns={"rate_pct": "value"}), "dataset": "780 음식점 인허가", "unit": "%"}
    if m in ("일평균방문", "방문거주비"):
        p = by_dong(pd.read_parquet(TAB / "pop_month.parquet"))
        p = p.assign(value=p["visit"] / p["days"] if m == "일평균방문" else p["visit"] / p["resd"])[["dong", "ym", "value"]]
        return {"table": p, "dataset": "583 유동인구", "unit": "지수"}
    if m in ("버스일평균", "경로일평균"):
        bm = by_dong(pd.read_parquet(TAB / "bus_month.parquet"))
        if m == "경로일평균":
            bm = bm[bm["user_type"] == "경로"]
        g = bm.groupby(["dong", "ym"]).agg(n=("n", "sum"), days=("days", "first")).reset_index()
        return {"table": g.assign(value=g["n"] / g["days"])[["dong", "ym", "value"]], "dataset": "743 버스", "unit": "명/일"}
    if m in ("5년생존율", "조건부생존"):  # 동네별 카플란-마이어(음식점 전체, 07 문서)
        k = by_dong(pd.read_parquet(TAB / "km.parquet")).pivot_table(index="dong", columns="year", values="survival_pct")
        v = k[5] if m == "5년생존율" else k[5] / k[2] * 100
        return {"table": v.rename("value").reset_index(), "dataset": "780 음식점 인허가(동네별, 업종 구분 없음)", "unit": "%"}
    if m == "거주연령구성":
        a = by_dong(pd.read_parquet(TAB / "pop_age.parquet"))
        a = a[a["year"] == a["year"].max()].groupby(["dong", "ageGroup"])["resd"].sum().rename("value").reset_index()
        return {"table": a, "dataset": "583 유동인구(연령)", "unit": "지수"}
    raise TaskError("실행", f"지표 {m}의 공개 경로 조회 미구현")


def s0_catalog(task, store, env):
    rows = json.loads((Q.ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    q = (env.get("question") or "").replace("센터에", "").replace("자료", "").replace("데이터", "")
    words = [w for w in q.replace("?", " ").split() if len(w) >= 2 and w not in ("있어", "있나요", "있어요", "도", "기간")]
    hit = [r for r in rows if any(w in f"{r['name']} {r.get('domain', '')} {r.get('columns') or ''}" for w in words)]
    return {"table": pd.DataFrame([{k: r.get(k) for k in ("name", "source", "space", "time", "period", "export")} for r in hit]), "dataset": "자료 목록", "unit": "-"}


def s2_describe(task, store, env):
    tabs = [store[k]["table"] for k in task["in"] if k in store and "table" in store[k]]
    if task.get("op") == "학습 전 점검":  # S3 앞: 레시피 자료가 학습할 만한지(동네별 기간·결측·0값, 표본 수)
        try:
            return {"check": recipes.check(task.get("recipe"), task.get("filter"), tabs), "recipe": task.get("recipe")}
        except recipes.RecipeError as e:
            raise TaskError("계산", str(e))
    if not tabs:
        raise TaskError("계산", "입력 표 없음")
    timed = [x for x in tabs if "year" in x or "ym" in x]  # 추세를 볼 수 있는 표를 먼저
    t = (timed or tabs)[-1]
    tcol = "year" if "year" in t else "ym" if "ym" in t else None
    out = {"rows": int(len(t)), "mean": float(t["value"].mean())}
    if tcol:
        s = t.groupby(tcol)["value"].sum().sort_index()
        last = s.tail(3)
        out.update(trend_last=last.round(2).to_dict(), direction="증가" if len(last) > 1 and last.iloc[-1] > last.iloc[0] else "감소" if len(last) > 1 and last.iloc[-1] < last.iloc[0] else "변화 없음")
        if len(s) >= 4:  # 추세 기울기(최근 6개 시점 회귀)와 그 유의성 → S6에서 판정
            y = s.tail(6).to_numpy(float)
            x = np.arange(len(y))
            slope, se = np.polyfit(x, y, 1)[0], None
            resid = y - np.polyval(np.polyfit(x, y, 1), x)
            if len(y) > 2:
                se = float(np.sqrt(resid.var(ddof=2) / ((x - x.mean()) ** 2).sum()))
            out.update(slope=float(slope), slope_se=se, slope_dof=len(y) - 2)
    return {"summary": out}


def s3_recipe(task, store, env):
    r = task.get("recipe")
    if r == "R3":  # 조건 효과: 08 문서의 동네별 비 효과(가설 검정 결과)
        f = Q.ROOT / "data" / "interim" / "gates" / "rain_test.json"
        if not f.exists():
            raise TaskError("실행", "R3 결과표 없음")
        rt = json.loads(f.read_text(encoding="utf-8"))["per_dong"]
        dongs = (task.get("filter") or {}).get("dong")
        rows = [x for x in rt if not isinstance(dongs, list) or x["dong"] in dongs]
        return {"effects": [{"name": x["dong"], "beta": x["beta"], "se": x["se"], "dof": 800} for x in rows], "recipe": "R3", "gate": "08 문서 검정 결과 사용"}
    tabs = [store[k]["table"] for k in task["in"] if k in store and "table" in store[k]]
    chk = next((store[k]["check"] for k in task["in"] if k in store and "check" in store[k]), None)
    metric = next((store[k].get("metric") for k in task["in"] if k in store and store[k].get("metric")), None)
    try:  # 학습·검증·추론(app/recipes.py). 관문 판정은 S6
        return recipes.run(r, task.get("filter"), tabs, chk, metric)
    except recipes.RecipeError as e:
        raise TaskError("실행", str(e))


def s4_chart(task, store, env):
    srcs = [k for k in task["in"] if k in store]
    return {"chart": {"kind": "auto", "inputs": srcs}}


def s5_pass(task, store, env):
    return {"note": "단위 맞추기: 공개 표는 이미 동네 단위(최소판 통과)"}


def s6_judge(task, store, env):
    out = []
    for k in task["in"]:
        v = store.get(k, {})
        if "effects" in v:
            out += [{"name": r["name"], "claim": r["claim"], "effect_pct": round(r["effect_pct"], 2), "ci95": [round(c, 2) for c in r["ci95"]]} for r in s6.judge_effects(v["effects"])]
        if v.get("gate_input") and v["gate_input"].get("mase") is not None:  # S3 레시피 관문
            gi = v["gate_input"]
            g = s6.gate(gi["model_err"], gi["baseline_err"], gi["mase"])
            out.append({"name": f"관문 {v.get('recipe')}", "claim": "통과(예측 사용)" if g["pass"] else "실패(fallback)", "mase": round(g["mase"], 4),
                        "better": f"{g['better']}/{g['n']}", "p_sign": g["p_sign"], "use_forecast": g["pass"]})
        if v.get("anomaly"):  # R7: 포아송 z(예측 아님)
            out += [{"name": f"{a['dong']} {a['year']}년 {v.get('kind')}", "claim": a["flag"], "z": a["z"], "count": a["count"], "expected": a["expected"]} for a in v["anomaly"]]
        if "summary" in v and v["summary"].get("slope_se"):
            sm = v["summary"]
            from scipy import stats
            p = float(2 * stats.t.sf(abs(sm["slope"] / sm["slope_se"]), max(sm["slope_dof"], 1)))
            out.append({"name": "추세", "claim": ("증가" if sm["slope"] > 0 else "감소") + (" (유의)" if p < s6.ALPHA else " (유의하지 않음)"), "p": round(p, 4)})
    if not out:
        return {"judgement": [], "note": "판정할 주장 없음"}
    return {"judgement": out}


EXEC = {"S0": s0_catalog, "S1": s1_query, "S2": s2_describe, "S3": s3_recipe, "S4": s4_chart, "S5": s5_pass, "S6": s6_judge}


# ---------- 실행기 ----------
def _exec(task, store, env):
    inj = (env.get("inject") or {}).get(task["id"])
    attempts = 0
    while True:
        attempts += 1
        t0 = time.perf_counter()
        try:
            if inj and attempts == 1 or inj in ("계산", "반출", "표현"):
                raise TaskError(inj, f"주입된 {inj} 오류")
            res = EXEC[task["sub"]](task, store, env)
            if task.get("export_restricted"):
                res["export"] = "집계만"
            if task.get("metric"):
                res.setdefault("metric", task["metric"])
            return {**res, "task_id": task["id"], "status": "성공", "attempts": attempts, "sec": round(time.perf_counter() - t0, 4)}
        except TaskError as e:
            if e.kind == "실행" and attempts < 2:  # 실행 오류는 같은 Sub에서 1회 재시도
                continue
            return {"task_id": task["id"], "status": "실패", "error_type": e.kind, "error": str(e), "attempts": attempts, "sec": round(time.perf_counter() - t0, 4)}


def run(order, env=None):
    env = env or {}
    t0 = time.perf_counter()
    errs = validate(order)
    if errs:
        return {"status": "계획 오류", "errors": errs, "store": {}, "sec": 0.0}
    store, failed, log = {}, set(), []
    budget = order["policy"]["timeout_ms"] / 1000
    tasks = order["tasks"]
    pending = list(tasks)
    done_before = set()
    if env.get("resume"):  # 검수 되돌림: 성공한 작업 결과는 저장소에 남기고 나머지만 다시 실행(05 문서 4-4절)
        store = dict(env["resume"]["store"])
        done_before = set(env["resume"]["done"])
        pending = [t for t in tasks if t["id"] not in done_before]
    while pending:
        if time.perf_counter() - t0 > budget:
            for t in pending:
                log.append({"task_id": t["id"], "status": "건너뜀", "reason": "시간 초과"})
            break
        ready = [t for t in pending if all(d in {x["id"] for x in tasks if x not in pending} for d in t["depends_on"])]
        layer = ready if env.get("parallel") else ready[:1]
        runnable = []
        for t in layer:
            if any(d in failed for d in t["depends_on"]):
                failed.add(t["id"])
                log.append({"task_id": t["id"], "status": "건너뜀", "reason": "의존 작업 실패"})
            else:
                runnable.append(t)
        if env.get("parallel") and len(runnable) > 1:
            with ThreadPoolExecutor(max_workers=len(runnable)) as ex:
                results = list(ex.map(lambda t: _exec(t, store, env), runnable))
        else:
            results = [_exec(t, store, env) for t in runnable]
        for t, r in zip(runnable, results):
            log.append({k: v for k, v in r.items() if k in ("task_id", "status", "error_type", "error", "attempts", "sec")})
            if r["status"] == "성공":
                store[t["out"]] = r
            else:
                failed.add(t["id"])
                if order["policy"]["on_task_failure"] == "abort":
                    return {"status": "중단", "log": log, "store": store, "sec": round(time.perf_counter() - t0, 4)}
        done = set(x["id"] for x in layer)
        pending = [t for t in pending if t["id"] not in done]
    ok = [x for x in log if x["status"] == "성공"] + [{"task_id": i} for i in done_before]
    status = "성공" if len(ok) == len(tasks) else "부분 결과" if ok else "실패"
    return {"status": status, "log": log, "store": store, "relaxed": order.get("relaxed", []), "notes": order.get("notes", []), "sec": round(time.perf_counter() - t0, 4)}


def answer(question, env=None):
    """M1 해석 → M2 계획 → M3 지시서 → 실행. (W7 검수·W8 결과 생성 전의 연결 확인용)"""
    import m1
    import planner
    env = dict(env or {"center_db": False}, question=question)
    it = m1.M1().interpret(question)
    p = planner.plan(it["tuple"], env)
    if p["status"] not in ("ok",):
        return {"interpret": it, "plan": p, "run": None}
    order = build_order(p)
    return {"interpret": it, "plan": p, "order": order, "run": run(order, env)}


if __name__ == "__main__":
    for q in sys.argv[1:]:
        r = answer(q)
        rr = r["run"]
        print(q, "|", r["plan"]["status"], "|", rr and rr["status"], rr and rr["sec"], "|", rr and [(x["task_id"], x["status"], x.get("error_type")) for x in rr["log"]])
        if rr:
            for k, v in rr["store"].items():
                brief = {kk: (vv if kk != "table" else f"표 {len(vv)}행") for kk, vv in v.items() if kk not in ("task_id", "status", "attempts", "sec")}
                print("   ", k, json.dumps(brief, ensure_ascii=False, default=str)[:220])
