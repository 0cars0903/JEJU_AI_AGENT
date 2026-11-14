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
import v3  # noqa: E402
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
    tasks, prev_s1, last, side_out = [], [], None, []
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
        elif st.get("side"):  # 곁가지(종합 진단의 모델 결과): 조회 결과와 바로 앞의 자기 점검만 입력으로 받고, 실패해도 뒤 단계를 막지 않는다
            chk = tasks[-1] if tasks and tasks[-1].get("optional") and tasks[-1]["sub"] == "S2" and st["sub"] == "S3" and tasks[-1].get("recipe") == st.get("recipe") else None
            f = next((x.get("filter") for x in tasks if x["sub"] == "S1" and x.get("filter")), None)
            if f:
                task["filter"] = f
            task["optional"] = True
            task["in"] = list(prev_s1) + ([chk["out"]] if chk else [])
            task["depends_on"] = [t["id"] for t in tasks if t["out"] in task["in"]]
            if st["sub"] == "S3":
                side_out.append(task["out"])
            tasks.append(task)
            continue
        else:  # 후속 단계는 앞선 조회 결과 전부와 직전 단계를 입력으로 받는다. 곁가지 결과도 받되 기다리기만 한다(after)
            ins = list(prev_s1) + side_out + ([last] if last and last not in prev_s1 else [])
            f = next((x.get("filter") for x in tasks if x["sub"] == "S1" and x.get("filter")), None)
            if f and "filter" not in task:
                task["filter"] = f  # 동네·업종 조건을 후속 단계(S3 등)에도 전달
            task["in"] = ins
            task["depends_on"] = [t["id"] for t in tasks if t["out"] in ins and not t.get("optional")]
            after = [t["id"] for t in tasks if t.get("optional")]
            if after:
                task["after"] = after
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
        if any(d not in ids for d in t.get("depends_on", []) + t.get("after", [])):
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
    if task.get("route") == "center_csv":  # F9: 이용자가 불러온 센터 카드 CSV(1-07·1-08)
        import center_csv
        did = (task.get("source") or {}).get("dataset")
        meta = center_csv.get(did)
        if not meta:
            raise TaskError("계획", "불러온 센터 자료 없음")
        f0 = task.get("filter") or {}
        c = center_csv.table(did)
        dl = f0.get("dong") if isinstance(f0.get("dong"), list) else None
        if dl:
            c = c[c["dong"].isin(dl)]
        tg = f0.get("target")
        word = v3.BIZ42.get(tg) if tg else None
        if word:
            c = c[c["biz"].str.contains(word, na=False, regex=False)]
        # 넣은 파일로 답할 수 없는 질문(파일에 없는 동네·업종, 센터 업종 이름을 정하지 못한 업종)은 공개 자료로 답하고 그 이유를 남긴다.
        # 화면은 파일을 넣은 뒤의 질문에도 같은 파일 번호를 계속 보낸다(문서 20 A6). 그래서 오류로 끝내지 않는다.
        why = None
        foreign = task["metric"] == "외국인매출"
        if tg and not word:
            why = f"넣은 센터 파일에서 '{tg}'에 맞는 업종 이름을 정하지 못해"
        elif c.empty:
            why = "넣은 센터 파일에 이 동네·업종이 없어"
        elif foreign:  # 동네별 외국인 매출: 공개 자료에는 없고 센터 파일의 이용자구분(중국·일본·동남아·기타 외국)으로만 낼 수 있다
            c = c[c["cust"] == "외국인 관광객"]
            if c.empty:
                why = "넣은 센터 파일에 외국인 손님 구분(이용자구분 칸)이 없어"
        if why is None and foreign:
            g = c.groupby(["dong", "ym"], as_index=False)["amt"].sum().rename(columns={"amt": "value"})
            return {"table": g, "dataset": f"{meta['label']}(이용자 불러옴, {meta['file']})", "unit": "원",
                    "note": f"{meta['label']} 기준이에요. 손님 구분 가운데 외국인(중국·일본·동남아·기타 외국) 합계이고, 업종은 '{word or '전체'}' 값이에요."}
        if why is None:
            g = c.groupby(["dong", "ym"], as_index=False)["amt"].sum().rename(columns={"amt": "value"})
            return {"table": g, "dataset": f"{meta['label']}(이용자 불러옴, {meta['file']})", "unit": "원",
                    "note": f"{meta['label']} 기준이에요. 손님 구분 전체(도민·내국인·외국인·법인) 합계이고, 세부 업종 '{word or '전체'}' 값이에요."}
        r = _card(task["metric"], tg, dl, f0.get("detail"), f0.get("details"))
        r["note"] = " ".join(x for x in [f"{why} 이 값은 공개 자료({KTO})로 계산했어요.", r.get("note")] if x)
        return r
    m, f = task["metric"], task.get("filter") or {}
    dongs = f.get("dong") if isinstance(f.get("dong"), list) else None
    tgt = f.get("target")

    def by_dong(df):
        return df[df["dong"].isin(dongs)] if dongs else df
    if m in ("점포수", "특화계수"):
        b = pd.read_parquet(TAB / "biz.parquet")
        sub = v3.biz_rows(b, tgt) if tgt and tgt not in ("음식점",) else (b[b["major"] == "음식"] if tgt == "음식점" else b)
        det, dnote = f.get("detail"), None
        if det:  # 세부 업종(국수·꽃집 …)은 상가 정보 소분류 이름으로 센다(문서 20 A3)
            import qparse
            names = qparse.DETAIL.get(det, {}).get("names") or []
            if names:
                sub = b[b["minor"].isin(names)]
                dnote = f"'{det}' 가게 수는 {qparse.detail_desc(det)}로 셌어요."
            else:
                det = None
        out = by_dong(sub).groupby("dong")["count"].sum().rename("value").reset_index()
        if m == "특화계수":
            tot = b.groupby("dong")["count"].sum()
            share = sub.groupby("dong")["count"].sum() / tot
            out = by_dong((share / (sub["count"].sum() / b["count"].sum())).rename("value").reset_index().rename(columns={"index": "dong"}))
        return {"table": out, "dataset": "793 상가", "unit": "곳" if m == "점포수" else "배", **({"detail": det, "note": dnote} if dnote else {})}
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
    if m in CARD_METRICS:
        return _card(m, tgt, dongs, f.get("detail"), f.get("details"))
    raise TaskError("실행", f"지표 {m}의 공개 경로 조회 미구현")


# v3 카드 매출(docs/기획/v3_설계.md 3절). 관광공사는 업종 대분류 5개뿐이라 세부 업종은 대분류로 올려 답하고 그 사실을 note로 남긴다.
CARD_METRICS = {"매출", "이용건수", "건당금액", "관광객비중", "시간대매출", "외국인매출", "과거매출", "시장추이", "업종비교", "매출성장", "판단재료"}
MONTHLY_CARD = {"매출", "이용건수", "건당금액", "관광객비중", "과거매출", "시장추이"}
BIZ5 = ["소매업", "숙박업", "음식점업", "기타서비스업", "예술스포츠여가업"]
BIZ_UP = {"숙박": "숙박업", "소매": "소매업", "편의점": "소매업"}  # 음식 업종(FOOD)은 음식점업
KTO = "제주관광공사 카드 소비"


def _biz5(tgt):
    """질문 업종 → (관광공사 대분류, 한계 문구). 대분류가 아니면 위로 올린다(app/v3.py)."""
    biz, note = v3.biz5_of(tgt)
    if tgt and biz is None:
        raise TaskError("실행", f"{tgt}은 카드 매출 업종(대분류 5개)에 대응하지 않음")
    return biz, note


def _card(m, tgt, dongs, det=None, details=None):
    def by_dong(df):
        return df[df["dong"].isin(dongs)] if dongs else df
    if m == "시장추이":  # F3: 수요·공급·손님 구성·기여 동네·지수(app/v3.py)
        biz, note = _biz5(tgt)
        mk = v3.market(biz, dongs)
        tab = mk["series"].rename("value").reset_index().assign(dong=mk["where"])[["dong", "ym", "value"]]
        extra = {k: v for k, v in mk.items() if k != "series"}
        return {"table": tab, "dataset": KTO, "unit": "원", "note": note or mk.get("note"), "extra": {"kind": "market", **extra}}
    if m == "업종비교":  # F4: 같은 동네의 업종 대분류 5개
        if not dongs:
            raise TaskError("실행", "업종 비교는 동네가 필요함")
        if len(details or []) >= 2:  # 세부 업종끼리는 상가 정보 소분류의 가게 수로 견준다(문서 20 A9)
            import qparse
            dc = v3.detail_compare(dongs[0], [{"word": w, "names": qparse.DETAIL.get(w, {}).get("names")} for w in details])
            tab = pd.DataFrame([{"dong": dc["dong"], "biz": r["word"], "value": r["value"]} for r in dc["rows"]])
            return {"table": tab, "dataset": "793 상가", "unit": "곳", "extra": {"kind": "detailcompare", **dc}}
        bc = v3.biz_compare(dongs[0])
        tab = pd.DataFrame([{"dong": bc["dong"], "biz": r["biz"], "value": r["cur"]} for r in bc["rows"]])
        return {"table": tab, "dataset": f"{KTO}(최근 12개월, ~{bc['end']})", "unit": "원",
                "note": "매출 비교는 업종 대분류 5개 기준이에요. 카페·한식 같은 세부 업종끼리는 가게 수·개업·폐업으로 비교해요.", "extra": {"kind": "bizcompare", **bc}}
    if m == "매출성장":  # 뜨는 동네·업종
        biz, note = _biz5(tgt)
        rs = v3.rising(biz)
        tab = pd.DataFrame([{"dong": r["dong"], "biz": r["biz"], "value": r["growth_pct"], "gain": r["gain"]} for r in rs["rows"]])
        return {"table": tab, "dataset": f"{KTO}(최근 12개월 대비 그 전 12개월, ~{rs['end']})", "unit": "증감률(%)", "note": note,
                "extra": {"kind": "rising", **rs}}
    if m == "판단재료":  # F2: 수요·경쟁·생존 신호
        if not dongs:
            raise TaskError("실행", "판단 재료는 동네가 필요함")
        biz, _ = v3.biz5_of(tgt)
        if det:
            import qparse
        names = qparse.DETAIL.get(det, {}).get("names") if det else None
        sg = v3.signals(dongs[0], tgt, biz, detail=det if names else None, names=names)
        sg["detail"] = det if names else None
        tab = pd.DataFrame([{"dong": sg["dong"], "name": x["name"], "value": x["value"], "pct": x["pct"]} for x in sg["items"]])
        return {"table": tab, "dataset": "여러 자료(판단 재료)", "unit": "-", "extra": {"kind": "signals", **sg}}
    if m == "외국인매출":  # 제주 전체 × 업종 × 출신지역
        f = pd.read_parquet(TAB / "card_foreign.parquet")
        biz, note = _biz5(tgt)
        if biz:
            f = f[f["biz"] == biz]
        g = f.groupby(["ym", "origin"], as_index=False)["amt"].sum().rename(columns={"amt": "value"})
        return {"table": g, "dataset": f"{KTO}(외국인, 제주 전체)", "unit": "원", "note": note}
    if m == "과거매출":  # 746 세부 업종(비씨카드, ~2021-05)
        c = by_dong(pd.read_parquet(TAB / "card746_month.parquet"))
        if tgt:
            words = {"카페": "비알콜 음료점업", "한식": "한식 음식점업", "일식": "일식 음식점업", "중식": "중식 음식점업", "숙박": "숙박", "소매": "소매업"}
            c = c[c["biz42"].str.contains(words.get(tgt, tgt), na=False) | (c["biz"] == tgt)]
        if not len(c):
            raise TaskError("실행", f"746에 {tgt} 업종 없음")
        g = c.groupby(["dong", "ym"], as_index=False)["amt"].sum().rename(columns={"amt": "value"})
        return {"table": g, "dataset": "746 업종별 카드 매출(비씨카드)", "unit": "원"}
    biz, note = _biz5(tgt)
    if m == "시간대매출":
        h = by_dong(pd.read_parquet(TAB / "card_hour.parquet"))
        h = h[h["ym"] > sorted(h["ym"].unique())[-13]]  # 최근 12개월
        if biz:
            h = h[h["biz"] == biz]
        g = h.groupby(["dong", "hour"])["amt"].sum()
        share = (g / g.groupby(level="dong").transform("sum") * 100).rename("value").reset_index()
        return {"table": share, "dataset": f"{KTO}(시간대, 최근 12개월 {h['ym'].min()}~{h['ym'].max()})", "unit": "%", "note": note}
    c = by_dong(pd.read_parquet(TAB / "card_month.parquet"))
    if biz:
        c = c[c["biz"] == biz]
    if m == "관광객비중":
        g = c.groupby(["dong", "ym", "cust"])["amt"].sum().unstack("cust").fillna(0)
        v = (g.get("내국인 관광객", 0) / g.sum(axis=1) * 100).rename("value").reset_index()
        return {"table": v, "dataset": KTO, "unit": "%", "note": note}
    g = c.groupby(["dong", "ym"], as_index=False)[["amt", "cnt"]].sum()
    if m == "건당금액":
        g["value"] = g["amt"] / g["cnt"]
    else:
        g["value"] = g["amt"] if m == "매출" else g["cnt"]
    return {"table": g[["dong", "ym", "value"]], "dataset": KTO, "unit": {"매출": "원", "이용건수": "건", "건당금액": "원"}[m], "note": note}


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
    card_m = next((store[k] for k in task["in"] if k in store and store[k].get("metric") in MONTHLY_CARD and "table" in store[k]), None)
    if card_m is not None and "ym" in card_m["table"]:  # v3: 월 카드 계열은 작년 같은 달 대비(계절 제거)로 추세를 본다
        ser = card_m["table"].groupby("ym")["value"].sum() if card_m["metric"] != "관광객비중" else card_m["table"].groupby("ym")["value"].mean()
        tt = v3.yoy_test(ser, log=card_m["metric"] != "관광객비중")
        out = {"rows": int(len(card_m["table"])), "trend_kind": "yoy"}
        if tt:
            out.update(slope=tt["mean"], slope_se=tt["se"], slope_dof=tt["dof"], yoy_pct=round(tt["pct"], 1), yoy_n=tt["n"])
        return {"summary": out}
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
        f = next((p for p in (Q.ROOT / "data" / "tables" / "rain_test.json", Q.ROOT / "data" / "interim" / "gates" / "rain_test.json") if p.exists()),
                 Q.ROOT / "data" / "tables" / "rain_test.json")  # 제출본 사본을 먼저(data/interim은 ZIP에 없음, 2026-11-14 발견)
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
            out += [{"name": f"{a['dong']} {a.get('biz') or ''} {a['year']}년 {v.get('kind')}".replace("  ", " "), "claim": a["flag"], "z": a["z"], "count": a["count"], "expected": a["expected"]} for a in v["anomaly"]]
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
        except Exception as e:  # 곁가지 단계는 예상 못 한 오류도 그 단계의 실패로만 남긴다(종합 진단의 다른 줄을 막지 않는다)
            if not task.get("optional"):
                raise
            return {"task_id": task["id"], "status": "실패", "error_type": "실행", "error": f"{type(e).__name__}: {e}", "attempts": attempts, "sec": round(time.perf_counter() - t0, 4)}


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
        ready = [t for t in pending if all(d in {x["id"] for x in tasks if x not in pending} for d in t["depends_on"] + t.get("after", []))]
        layer = ready if env.get("parallel") else ready[:1]
        runnable = []
        for t in layer:
            if any(d in failed for d in t["depends_on"]):
                failed.add(t["id"])
                log.append({"task_id": t["id"], "status": "생략" if t.get("optional") else "건너뜀", "reason": "의존 작업 실패"})
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
            elif t.get("optional"):  # 곁가지는 빠져도 답이 된다. 실패가 아니라 '생략'으로 적는다
                log[-1]["status"] = "생략"
                failed.add(t["id"])
            else:
                failed.add(t["id"])
                if order["policy"]["on_task_failure"] == "abort":
                    return {"status": "중단", "log": log, "store": store, "sec": round(time.perf_counter() - t0, 4)}
        done = set(x["id"] for x in layer)
        pending = [t for t in pending if t["id"] not in done]
    ok = [x for x in log if x["status"] in ("성공", "생략")] + [{"task_id": i} for i in done_before]
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
