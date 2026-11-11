"""W7 검수 Agent (docs/기획/05_Agent구조_v2.md 4-4절·15-6절, 2026-11-11 구현). 코드 규칙만 쓰고 LLM에 맡기지 않는다.

오류 6유형과 되돌릴 곳
  해석 오류 → M1     : 질문 Tuple 칸이 목록 밖 값, 필수 칸(동네) 누락 → 규칙 해석기(qparse)로 다시 채움. 그래도 비면 되묻기
  계획 오류 → M2·M3  : 질문 Tuple 축(지표·동네)을 계획이 덮지 못함, 지시서 형식 오류, 센터 경로 미연결 → 공개 경로로 재계획
  실행 오류 → Sub    : 조회 실패·열 없음·기간 밖 → 실행기가 같은 Sub에서 1회 재실행(runner._exec). 그래도 실패면 부분 결과
  계산 오류 → Sub    : 값 범위 위반(비율 0~100% 밖, 음수, 결측), 모델 수치에 관문 기록 없음 → 실패 작업과 의존 작업만 다시 실행
  표현 오류 → 검수   : 답의 수치가 Sub 결과에 없음, 한계(완화) 누락, S6 판정 없는 주장 문장 → 코드 템플릿 문장으로 바꿈
  반출 위반 → 검수   : 반출 불가 자료의 원자료 행이 결과에 있음 → 그 행을 지우고 동네 집계만 남김
오류가 아닌 것: S6 판정이 '판단 불가'·'작음 확인'·'유의하지 않음'이거나 관문 실패(MASE ≥ 1 등)면 '효과 없음'(no_significant_effect). 재시도하지 않는다.
재시도 상한: Sub 재실행 1회, Main 재계획 1회, 질문당 누적 2회. 넘으면 확인된 결과만 내고 못 한 부분과 이유를 붙인다.
진입점: review(question, env) → {"status", "answer", "record", "retries", "run"}. record가 '검수 기록'이다.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import planner  # noqa: E402
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402
import runner  # noqa: E402
from textcheck import check_numbers  # noqa: E402

ROUTE = {"해석": "M1", "계획": "M2·M3", "실행": "Sub", "계산": "Sub", "표현": "검수", "반출": "검수"}
LIMIT = {"sub": 1, "main": 1, "total": 2}
NO_EFFECT = ("판단 불가", "작음 확인", "실패(fallback)", "유의하지 않음")
CLAIM = re.compile(r"늘었|줄었|증가|감소|차이가?\s*(있|크)|많아졌|적어졌|효과가?\s*있")
AGG_COLS = {"dong", "ym", "year", "value", "ageGroup", "name", "source", "space", "time", "period", "export"}  # 집계표에 허용하는 열
PCT_UNITS = {"%"}


def _f(kind, detail, task=None, sub=None):
    return {"type": kind, "route": ROUTE[kind], "detail": detail, "task": task, "sub": sub}


# ---------- 해석·계획 ----------
def check_tuple(t):
    out = [_f("해석", f"목록 밖 칸: {b}") for b in Q.validate(t)]
    if t.get("expect") == "답함" and t.get("type") in qparse.NEED_DONG and not t.get("space"):
        out.append(_f("해석", "필수 칸 누락: 동네"))
    return out


def check_plan(t, plan, order):
    out = []
    if plan.get("status") != "ok":
        return out
    out += [_f("계획", f"지시서 형식: {e}") for e in runner.validate(order)]
    if t.get("type") == "T11":  # 자료 찾기(S0)는 지표·동네 축이 없다
        return out
    covered = {s.get("metric") for s in plan["steps"]} | {s.get("instead_of") for s in plan["steps"]}
    said = " ".join(plan.get("relaxed", []) + plan.get("notes", []))
    for m in t.get("metric") or []:
        if m not in covered and m not in said and Q.METRICS.get(m, m) not in said:
            out.append(_f("계획", f"지표 {m}을 덮는 단계 없음"))
    for d in t.get("space") or []:
        if not any(d in ((s.get("filter") or {}).get("dong") or []) for s in plan["steps"] if s["sub"] == "S1"):
            out.append(_f("계획", f"동네 {d}가 조회 조건에 없음"))
    return out


# ---------- 실행 결과 ----------
def _bad_values(v, unit):
    a = np.asarray(v, float)
    if np.isnan(a).any() or np.isinf(a).any():
        return "결측·무한 값"
    if unit in PCT_UNITS and ((a < 0) | (a > 100)).any():
        return "비율 0~100% 밖"
    if unit != "배" and (a < 0).any():
        return "음수 값"
    return None


def _judgements(store):
    return [j for v in store.values() for j in v.get("judgement", [])]


def check_run(order, res):
    """실행 결과 검사 → (오류 목록, '효과 없음' 목록, 표본 부족 목록)."""
    errs, no_eff, short = [], [], []
    tasks = {t["id"]: t for t in order["tasks"]}
    for x in res.get("log", []):
        if x["status"] == "실패":
            t = tasks[x["task_id"]]
            kind = x.get("error_type") or "실행"
            if kind == "실행" and t.get("route") == "center":
                kind = "계획"  # 센터 경로가 없으면 Sub를 고쳐도 안 된다 → 공개 경로로 재계획
            errs.append(_f(kind, x.get("error"), x["task_id"], t["sub"]))
    judged = _judgements(res["store"])
    for t in order["tasks"]:
        v = res["store"].get(t["out"])
        if not v:
            continue
        if "table" in v and "value" in getattr(v["table"], "columns", []):
            why = _bad_values(v["table"]["value"], v.get("unit"))
            if why:
                errs.append(_f("계산", f"{t.get('metric')}: {why}", t["id"], t["sub"]))
        if v.get("survival"):
            s = v["survival"]
            if not 0 <= s["surv5_pct"] <= 100:
                errs.append(_f("계산", "생존율 0~100% 밖", t["id"], t["sub"]))
        if v.get("forecast"):  # 15-6: 모델 수치에는 같은 질의의 관문 기록이 있어야 한다
            if not any(j["name"] == f"관문 {v.get('recipe')}" for j in judged):
                errs.append(_f("계산", f"관문 {v.get('recipe')} 기록 없음", t["id"], t["sub"]))
            if any(np.asarray([r.get("visit", r.get("value", 0)) for r in v["forecast"]], float) < 0):
                errs.append(_f("계산", "예측값 음수", t["id"], t["sub"]))
        chk = v.get("check")
        if isinstance(chk, dict) and chk.get("fail"):
            short.append({"task": t["id"], "recipe": v.get("recipe"), "fail": chk["fail"]})
    for j in judged:
        if any(w in j["claim"] for w in NO_EFFECT):
            no_eff.append(j)
    return errs, no_eff, short


def strip_export(order, res):
    """반출 위반: 반출 불가 자료의 표에 집계 외 열(원자료 행)이 있으면 그 행을 지우고 동네 집계만 남긴다."""
    fixed = []
    for t in order["tasks"]:
        v = res["store"].get(t["out"])
        if not (v and t.get("export_restricted") and "table" in v):
            continue
        tab = v["table"]
        extra = [c for c in tab.columns if c not in AGG_COLS]
        if extra:
            keys = [c for c in ("dong", "ym", "year") if c in tab.columns]
            v["table"] = tab.groupby(keys)["value"].sum().reset_index() if keys and "value" in tab else tab[[c for c in tab.columns if c in AGG_COLS]].drop_duplicates()
            v["export"] = "집계만"
            fixed.append(_f("반출", f"원자료 열 {extra} 제거, {len(tab)}행 → {len(v['table'])}행", t["id"], t["sub"]))
    return fixed


# ---------- 표현 ----------
def _plain(store):
    out = []
    for v in store.values():
        out.append({k: (x.round(4).to_dict(orient="records") if hasattr(x, "to_dict") else x) for k, x in v.items() if k not in ("sec", "attempts")})
    return json.loads(json.dumps(out, ensure_ascii=False, default=str))


def template_answer(order, res, no_eff=(), short=()):
    """코드 템플릿 답(LLM 없이). 수치는 저장소 값만 쓴다."""
    lines = []
    tasks = {t["out"]: t for t in order["tasks"]}
    for k, v in res["store"].items():
        t = tasks.get(k, {})
        if "table" in v and t.get("sub") == "S1" and len(v["table"]):
            tab = v["table"]
            last = tab[tab[c] == tab[c].max()] if (c := next((x for x in ("ym", "year") if x in tab), None)) else tab
            vals = ", ".join(f"{r['dong']}{' ' + str(r['ageGroup']) if 'ageGroup' in r else ''} {round(float(r['value']), 1)}" for r in last.head(8).to_dict(orient="records") if "dong" in r)
            when = f"({last[c].iloc[0]} 기준)" if c else ""
            lines.append(f"{t.get('metric')}{when}: {vals} {v.get('unit', '')} · 자료 {v.get('dataset')}")
        if "table" in v and t.get("sub") == "S0":
            lines.append("관련 자료: " + ", ".join(f"{r['name']}(반출 {r['export']})" for r in v["table"].head(8).to_dict(orient="records")))
        if v.get("forecast") and any(j.get("use_forecast") for j in _judgements(res["store"])):
            fc = v["forecast"][:7]
            lines.append(f"{v.get('recipe')} 예측: " + ", ".join(f"{r['dong']} {r.get('date', r.get('ym'))} {r.get('visit', r.get('value'))}" for r in fc))
        if v.get("survival"):
            s = v["survival"]
            lines.append(f"{s['group']} 5년 생존율 {s['surv5_pct']}% (±{s['ci95_pp']}%p, n={s['n']})")
    for j in _judgements(res["store"]):
        lines.append(f"판정 {j['name']}: {j['claim']}")
    if no_eff:
        lines.append("효과 없음: 차이를 확인하지 못했습니다(" + ", ".join(j["name"] for j in no_eff[:3]) + ").")
    for s in short:
        lines.append(f"표본 부족: {s['recipe']} {', '.join(s['fail'])}")
    lines += [f"한계: {r}" for r in res.get("relaxed", [])]
    lines += [f"계산하지 못함: {x['task_id']}({x.get('error_type')}: {x.get('error')})" for x in res.get("log", []) if x["status"] == "실패"]
    return "\n".join(lines) or "확인된 결과가 없습니다."


def check_answer(text, res):
    """표현 오류: 결과에 없는 숫자, 완화(한계) 누락, S6 판정 없는 주장 문장."""
    out = []
    bad = check_numbers(text, _plain(res["store"]))
    if bad:
        out.append(_f("표현", f"결과에 없는 숫자 {bad[:5]}"))
    for r in res.get("relaxed", []):
        if r.split(":")[0].split("→")[0].strip() not in text:
            out.append(_f("표현", f"한계 누락: {r}"))
    if CLAIM.search(text) and not _judgements(res["store"]):
        out.append(_f("표현", f"S6 판정 없는 주장: {CLAIM.search(text).group(0)}"))
    return out


# ---------- 조정자 ----------
def _rerun_ids(order, failed):
    """실패한 작업과 그 작업에 (간접으로) 의존하는 작업."""
    ids, changed = set(failed), True
    while changed:
        changed = False
        for t in order["tasks"]:
            if t["id"] not in ids and any(d in ids for d in t["depends_on"]):
                ids.add(t["id"])
                changed = True
    return ids


def review(question, env=None, interpret=None, answer_fn=None, tuple_override=None, order_hook=None, store_hook=None):
    """질문 하나의 해석→계획→실행→검수. 시험용 갈고리: tuple_override(해석 결과 바꾸기), order_hook(지시서 바꾸기), store_hook(실행 결과 바꾸기)."""
    env = dict(env or {"center_db": False}, question=question)
    rec, used = [], {"sub": 0, "main": 0, "total": 0}

    def spend(kind):
        if used[kind] >= LIMIT[kind] or used["total"] >= LIMIT["total"]:
            return False
        used[kind] += 1
        used["total"] += 1
        return True

    def log(stage, f, action):
        rec.append({"stage": stage, **f, "action": action})

    # ① 해석 검수
    if interpret is None:
        import m1
        interpret = m1.M1().interpret
    t = tuple_override(interpret(question)["tuple"]) if tuple_override else interpret(question)["tuple"]
    errs = check_tuple(t)
    if errs:
        for f in errs:
            log("해석", f, "M1 규칙 해석기로 다시 채움" if used["main"] < LIMIT["main"] else "상한 초과")
        if spend("main"):
            r = qparse.parse(question)
            t = {k: v for k, v in r.items() if not k.startswith("_")}
            if check_tuple(t):
                t["expect"] = "되묻기"
                log("해석", _f("해석", "규칙으로도 비어 있음"), "되묻기")
    if t["expect"] != "답함":
        return {"status": t["expect"], "answer": None, "record": rec, "retries": used, "tuple": t, "run": None}

    # ② 계획 검수
    p = planner.plan(t, env)
    order = runner.build_order(p)
    if order_hook:
        order = order_hook(order)
    errs = check_plan(t, p, order)
    if errs:
        can = used["main"] < LIMIT["main"] and used["total"] < LIMIT["total"]
        for f in errs:
            log("계획", f, "M2·M3 재계획" if can else "재시도 상한")
        if spend("main"):
            p = planner.plan(t, env)
            order = runner.build_order(p)
            errs = check_plan(t, p, order)
            for f in errs:
                log("계획", f, "재계획 후에도 남음")
        if any("지시서 형식" in f["detail"] for f in errs):  # 형식이 틀린 지시서는 Sub에 보내지 않는다
            return {"status": "계획 오류", "answer": None, "record": rec, "retries": used, "tuple": t, "order": order, "run": None}
    if p["status"] != "ok":
        return {"status": p["status"], "answer": None, "record": rec, "retries": used, "tuple": t, "run": None}

    # ③ 실행 + 실행 결과 검수
    res = runner.run(order, env)
    if store_hook:
        store_hook(order, res)
    errs, no_eff, short = check_run(order, res)
    plan_errs = [f for f in errs if f["type"] == "계획"]
    if plan_errs:  # 센터 경로 미연결 → 공개 경로로 재계획(Main)
        for f in plan_errs:
            log("실행", f, "M2 공개 경로로 재계획")
        if spend("main"):
            env = dict(env, center_db=False)
            p = planner.plan(t, env)
            order = runner.build_order(p)
            res = runner.run(order, {k: v for k, v in env.items() if k != "inject"})
            if store_hook:
                store_hook(order, res)
            errs, no_eff, short = check_run(order, res)
    sub_errs = [f for f in errs if f["type"] in ("실행", "계산")]
    for f in sub_errs:
        log("실행", f, "실행기 1회 재실행 후에도 실패" if f["type"] == "실행" else "해당 Sub 재계산")
    calc = [f["task"] for f in sub_errs if f["type"] == "계산" and f["task"]]
    if calc and spend("sub"):  # 실패한 작업과 의존 작업만 다시 실행. 성공한 결과는 그대로 쓴다
        redo = _rerun_ids(order, calc)
        done = [x["task_id"] for x in res["log"] if x["status"] == "성공" and x["task_id"] not in redo]
        keep = {t["out"]: res["store"][t["out"]] for t in order["tasks"] if t["id"] in done and t["out"] in res["store"]}
        renv = dict(env, resume={"store": keep, "done": done})
        if not env.get("inject_persist"):
            renv.pop("inject", None)
        res2 = runner.run(order, renv)
        res2["log"] = [x for x in res["log"] if x["task_id"] in done] + res2["log"]
        if store_hook and env.get("inject_persist"):
            store_hook(order, res2)
        res = res2
        errs, no_eff, short = check_run(order, res)
        for f in errs:
            log("실행", f, "재계산 후에도 실패 → 부분 결과")
    elif calc:
        log("실행", _f("계산", "재시도 상한"), "부분 결과")
    # 남은 계산 오류 작업의 결과는 쓰지 않는다
    for f in errs:
        if f["type"] == "계산" and f["task"]:
            out = next(t["out"] for t in order["tasks"] if t["id"] == f["task"])
            res["store"].pop(out, None)
            for x in res["log"]:
                if x["task_id"] == f["task"]:
                    x.update(status="실패", error_type="계산", error=f["detail"])
    for f in strip_export(order, res):
        log("반출", f, "원자료 행 제거, 집계만 남김")
    for j in no_eff:
        rec.append({"stage": "판정", "type": "효과 없음", "route": None, "detail": f"{j['name']}: {j['claim']}", "task": None, "sub": "S6", "action": "재시도하지 않음"})

    # ④ 답 표현 검수
    text = answer_fn(order, res) if answer_fn else template_answer(order, res, no_eff, short)
    errs = check_answer(text, res)
    if errs:
        for f in errs:
            log("표현", f, "코드 템플릿 문장으로 바꿈")
        text = template_answer(order, res, no_eff, short)
    ok = [x for x in res.get("log", []) if x["status"] == "성공"]
    status = "no_significant_effect" if no_eff and len(ok) == len(order["tasks"]) else ("성공" if len(ok) == len(order["tasks"]) else "부분 결과" if ok else "실패")
    return {"status": status, "answer": text, "record": rec, "retries": used, "tuple": t, "order": order, "run": res}


if __name__ == "__main__":
    for q in sys.argv[1:]:
        r = review(q)
        print(q, "|", r["status"], r["retries"])
        for x in r["record"]:
            print("   ", x["stage"], x["type"], "→", x["route"], "|", x["detail"], "|", x["action"])
        print(r["answer"])
