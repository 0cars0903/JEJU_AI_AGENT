"""W3 Main Layer M2 자료 매칭 (docs/기획/05_Agent구조_v2.md 3-3절·5절·15절, 2026-11-11 구현).

질문 Tuple → 실행 계획(단계 목록). 단계마다 담당 Sub·연산·자료·레시피를 정한다.
- 자료 선택: 지표 사전(data/metric_dict.json)에서 지표의 공개·센터 경로를 찾는다. 실행 환경(env.center_db)에 센터 DB가 있으면 센터 경로를 앞에 둔다.
- 축 확인: 시간대 세분(T13 등)은 '시간' 단위 자료(센터 4-11·3-04·1-14)만 지원한다.
- 완화 순서(바꿀 수 없음): 조건 → 시간 해상도(시간대 → 일 → 월) → 세분·대상. 동네는 완화하지 않는다. 완화한 내용은 relaxed에 적어 답에 쓴다.
- 레시피(S3)·통계 검정(S6)이 필요한 유형은 해당 단계를 붙인다. 학습하는 레시피는 S3 앞에 S2 학습 전 점검을 둔다.
- Sub 순서는 고정이 아니다. 유형별 경로는 TYPE_PLAN에 있다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

MD = json.loads((Q.ROOT / "data" / "metric_dict.json").read_text(encoding="utf-8"))
CAT = {r["id"]: r for r in json.loads((Q.ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))}
# 센터 전용 지표 → 공개 자료로 대신 답할 지표(완화 답, 사용자 결정 2026-11-11). 대신한 내용은 relaxed에 적는다.
CENTER_SUBSTITUTE = {"시간대방문": ["일평균방문"], "시간대버스": ["버스일평균"]}  # v3: 매출은 공개 경로(제주관광공사)가 생겨 대체하지 않는다
NO_CHECK = {"R3", "R8", "R9", "R10", "R11"}  # 미리 계산한 검정 결과(R3)·센터 전용(R8·R9)은 점검하지 않는다
FOOD = {"카페", "한식", "일식", "횟집", "중식", "치킨", "분식", "주점", "편의점", "음식점"}
REST_BIZ = FOOD - {"편의점"}  # 음식점 인허가 자료로 생존·개업·폐업을 볼 수 있는 업종
# 종합 진단(T10)에 붙이는 모델 결과의 순서(문서 21 3.1절): 생존·방문 예상·닮은 동네 → 매출 예상·개업폐업 이례 → 계절 유형·비 효과
DIAG_RECIPES = ["R4", "R1", "R5", "R10", "R7", "R6", "R3"]
# 단순 주제에 곁가지로 붙이는 모델 결과(문서 22 4절, 이중 검토 033 답 4절 대응표). R5는 '비슷한 동네 5곳 대비' 위치 계산에 쓴다
SIDE_BY_METRIC = {"일평균방문": ["R1", "R6", "R3", "R5"], "점포수": ["R4", "R5"], "개업수": ["R4", "R7", "R5"], "폐업수": ["R4", "R7", "R5"],
                  "5년생존율": ["R4", "R5"], "조건부생존": ["R4", "R5"], "매출": ["R10", "R5"], "이용건수": ["R10", "R5"], "건당금액": ["R5"],
                  "관광객비중": ["R5"], "시간대매출": ["R5"], "시장추이": ["R10", "R5"], "업종비교": ["R5"]}
SIDE_SKIP = {"T2", "T3", "T8", "T9", "T10", "T11", "T15"}  # 비교(T2)는 동네 비교 화면, 예상·닮은 동네·이례는 주 레시피가 이미 모델이다

# 유형별 기본 지표(질문에 지표가 없을 때)
DEFAULT_METRIC = {"T1": "점포수", "T2": None, "T3": "점포수", "T4": "개업수", "T5": "거주연령구성", "T6": "일평균방문", "T8": "일평균방문",
                  "T13": "시간대매출", "T14": None, "T15": "폐업수"}
# 유형 → (담당 Sub 흐름, 레시피)
TYPE_PLAN = {
    "T1": (["S1"], None), "T2": (["S1", "S4"], None), "T3": (["S1", "S4"], None), "T4": (["S1", "S2", "S6", "S4"], None),
    "T5": (["S1", "S4"], None), "T6": (["S1", "S5", "S3", "S6", "S4"], "R3"), "T7": (["S1", "S5", "S2", "S6", "S4"], None),
    "T8": (["S1", "S3", "S6", "S4"], "R1"), "T9": (["S1", "S3"], "R5"), "T10": (["S1", "S2", "S4"], None), "T11": (["S0"], None),
    "T13": (["S1", "S4"], "R8"), "T14": (["S1", "S4"], None), "T15": (["S1", "S3", "S6"], "R7"),
}


def pick_source(metric, env):
    """지표 → (경로, 자료 설명). 센터 DB가 있으면 센터 경로 우선(센터 자료가 본체).
    v3 F9: 이용자가 센터 카드 CSV(1-07·1-08)를 불러왔으면 매출은 그 자료로 계산한다(route center_csv)."""
    if env.get("center_card") and metric in ("매출", "과거매출", "외국인매출"):  # 외국인매출: 센터 파일의 이용자구분으로 동네별 값을 낸다(문서 20 A9)
        return "center_csv", {"dataset": env["center_card"]}
    m = MD.get(metric)
    if not m:
        return None, None
    if env.get("center_db") and m.get("center"):
        c = CAT.get(m["center"], {})
        return "center", {"dataset": m["center"], "name": c.get("name"), "time": c.get("time"), "export": c.get("export")}
    if m.get("public"):
        return "public", m["public"]
    if m.get("center"):
        return "center_only", {"dataset": m["center"], "note": m.get("note", "센터에서만 가능")}
    return None, None


def _side_steps(t, out, metrics):
    """단순 주제(동네 하나)에 관련 모델 결과를 곁가지로 붙인다(문서 22 4절 공통 작업). 곁가지는 실패해도 답을 막지 않는다."""
    if t["type"] in SIDE_SKIP or len(t.get("space") or []) != 1 or out["status"] != "ok":
        return
    tgt = t.get("target")
    rest = not tgt or tgt in REST_BIZ
    card_biz = tgt in FOOD or tgt in ("숙박", "소매", "편의점", "음식점")  # 카드 대분류가 있는 업종(매출 예상 R10)
    main = {st.get("recipe") for st in out["steps"]}
    want = []
    for m in metrics:
        for r in SIDE_BY_METRIC.get(m, []):
            if r in want or r in main or (r in ("R4", "R7") and not rest) or (r == "R10" and not card_biz):
                continue
            want.append(r)
    if not want:
        return
    out["side"] = list(want)
    for r in want:  # 주 단계 뒤에 붙인다(주 단계의 번호와 입력은 그대로)
        if r not in NO_CHECK:
            out["steps"].append({"sub": "S2", "op": "학습 전 점검", "recipe": r, "side": True})
        out["steps"].append({"sub": "S3", "op": "레시피 학습·검증·추론", "recipe": r, "side": True})
    out["steps"].append({"sub": "S6", "op": "판정(곁가지 모델 관문·비 효과)"})  # 곁가지 예상(R1·R10)의 관문과 비 효과(R3) 판정


def plan(t, env=None):
    env = env or {"center_db": False}
    out = {"type": t["type"], "steps": [], "relaxed": [], "notes": [], "status": "ok"}
    if t["expect"] != "답함":
        out["status"] = t["expect"]  # 되묻기·범위밖은 실행하지 않는다
        return out
    if t["type"] == "T11":
        out["steps"].append({"sub": "S0", "op": "자료 목록 검색", "dataset": "catalog", "filter": {"target": t.get("target")}})
        return out
    if t["type"] == "T10":  # v3 F2 상권 묶음 진단: 판단 재료(수요·경쟁·생존) + 매출 흐름 + 손님 구성 + 가게 수
        flt = {"dong": t["space"] or "전체", "target": t.get("target"), "time": t.get("time"), "detail": t.get("detail"), "details": t.get("details")}
        biz_ok = not t.get("target") or t["target"] in FOOD or t["target"] in ("숙박", "소매", "편의점")
        for m in ["판단재료", "매출", "관광객비중", "점포수"] if biz_ok else ["판단재료", "점포수"]:
            route, src = pick_source(m, env)  # 센터 카드 CSV를 넣었으면 매출은 그 자료로 계산한다(문서 20 A6: 전에는 공개 경로로 고정돼 넣은 자료가 쓰이지 않았다)
            out["steps"].append({"sub": "S1", "op": "조회", "metric": m, "route": route if route == "center_csv" else "public", "source": src, "filter": flt, "breakdown": None})
        # 모델 결과를 곁가지 단계로 붙인다(문서 21 6.1절 1단계). 곁가지는 실패해도 진단의 다른 줄을 막지 않는다(runner: optional)
        tgt, rest = t.get("target"), not t.get("target") or t.get("target") in REST_BIZ
        for r in (DIAG_RECIPES if t["space"] else []):
            if (r in ("R4", "R7") and not rest) or (r == "R10" and not biz_ok):
                continue  # 생존·개업폐업은 음식점 인허가 업종만, 매출 예상은 카드 대분류가 있는 업종만
            if r not in NO_CHECK:
                out["steps"].append({"sub": "S2", "op": "학습 전 점검", "recipe": r, "side": True})
            out["steps"].append({"sub": "S3", "op": "레시피 학습·검증·추론", "recipe": r, "side": True})
        out["steps"] += [{"sub": "S2", "op": "기술 통계·추세·상관"}, {"sub": "S6", "op": "판정(차이·동등성·짝 비교)"}, {"sub": "S4", "op": "차트·지도"}]
        return out
    metrics = list(t["metric"]) or ([DEFAULT_METRIC.get(t["type"])] if DEFAULT_METRIC.get(t["type"]) else [])
    if t["type"] == "T8" and not t["metric"] and ("버스" in str(t.get("target")) or t.get("target") == "어르신"):
        metrics = ["버스일평균"]
    if t["type"] == "T9" and not metrics:  # 유사도 특성(R5)의 재료: 업종·방문·버스
        metrics = ["점포수", "일평균방문", "버스일평균"]
    if t["type"] in ("T2", "T14") and not metrics:
        metrics = ["점포수", "일평균방문", "버스일평균"]
        if t["type"] == "T2" and (t.get("target") in Q.TARGETS_BIZ or t.get("target") in Q.TARGETS_OUT or t.get("detail")):
            # 업종을 넣은 비교는 그 업종의 가게 수가 먼저다. 카드 매출은 대분류가 있는 업종만 붙인다(문서 20 A4: 동네 전체 방문·버스가 업종 값처럼 나왔다)
            metrics = ["점포수"] + (["매출"] if t.get("target") in FOOD or t.get("target") in ("숙박", "소매") else []) + ["일평균방문"]
    # 음식점만 있는 지표에 다른 업종이 오면 범위 밖(사전 해석기와 같은 규칙)
    if t.get("target") and t["target"] not in FOOD and t["target"] not in Q.TARGETS_POP and any(m in ("개업수", "폐업수", "폐업률", "5년생존율", "조건부생존") for m in metrics):
        out["status"] = "범위밖"
        out["notes"].append(f"{t['target']}은 개업·폐업 자료(음식점 인허가)에 없음")
        return out
    subs, recipe = TYPE_PLAN.get(t["type"], (["S1"], None))
    season = t["type"] == "T9" and t.get("breakdown") == "계절"
    if season:  # 닮은 기준이 계절 흐름이면 업종·연령 유사도(R5)가 아니라 월별 방문 곡선(R6)으로 찾는다(문서 21)
        metrics, recipe = ["일평균방문"], "R6"
    if t["type"] == "T8" and (metrics == ["버스일평균"] or "버스" in str(t.get("target"))):  # v3: 버스 예상(R2) 제외
        out["status"] = "범위밖"
        out["notes"].append("버스 이용 예상은 하지 않습니다(v3 상권 분석 범위 밖, 모델이 단순 기준보다 낫지 않음)")
        return out
    if t["type"] == "T8" and "매출" in metrics:  # v3: 업종 월 매출 예상
        metrics, recipe = ["매출"], "R10"
    if t["type"] == "T8" and "과거매출" in metrics:  # v3: R11 제외 → R10(최근 검증 기록)으로 답한다
        metrics, recipe = ["매출"], "R10"
    if any(m in ("5년생존율", "조건부생존") for m in metrics) and t.get("target"):
        subs, recipe = ["S1", "S3", "S4"], "R4"  # 업종 생존은 업종 묶음 카플란-마이어(동네별 표에는 업종 구분이 없다)
    by_biz = t["type"] == "T15" and t.get("breakdown") == "업종"  # 업종별 이례(R7): 조회는 동네 값 그대로, 레시피가 업종 묶음별로 계산한다
    breakdown = None if season or by_biz else t.get("breakdown")
    hourly = t["type"] == "T13" or any(m in ("시간대방문", "시간대버스", "시간대매출") for m in metrics) or breakdown == "시간대"
    bus = any(m in ("버스일평균", "경로일평균", "정류소일이용", "시간대버스") for m in metrics) or "버스" in str(t.get("target"))
    if hourly and not bus:  # v3: 상권의 '몇 시'는 공개 시간대 카드 매출(제주관광공사, 2024-10~)로 답한다
        if "시간대방문" in metrics and not t.get("target"):
            out["relaxed"].append("오가는 사람의 시간대 자료는 센터에만 있어 카드 매출의 시간대 비중으로 답함")
        metrics, breakdown, hourly = ["시간대매출"], None, False
        subs, recipe = ["S1", "S4"], None
    if hourly:
        breakdown = "시간대"  # 시간대 패턴은 질문에 '시간대'라는 말이 없어도 시간대 세분이다
        if any(m in ("버스일평균", "경로일평균", "정류소일이용") for m in metrics):  # 버스 질문의 '몇 시'는 버스 시간대
            metrics = ["시간대버스" if m == "시간대방문" else m for m in metrics]
        if "시간대방문" in metrics or "시간대버스" in metrics:  # 시간대 지표가 있으면 같은 대상의 일 단위 지표는 뺀다
            metrics = [m for m in metrics if m not in ("일평균방문", "버스일평균")]
        elif metrics:
            metrics = [{"일평균방문": "시간대방문", "버스일평균": "시간대버스"}.get(m, m) for m in metrics]
        else:
            metrics = ["시간대방문"]
    for m in metrics:
        route, src = pick_source(m, env)
        # 시간대 세분: 시간 단위 자료(센터)만 지원 → 없으면 시간 해상도 완화
        if breakdown == "시간대" and route != "center":
            if route == "center_only" or route is None:
                fallback = {"시간대방문": "일평균방문", "시간대버스": "버스일평균"}.get(m)
                if fallback:
                    out["relaxed"].append(f"시간대 → 일 단위({m} 대신 {fallback}). 시간대 자료는 센터에서만 가능")
                    m = fallback
                    route, src = pick_source(m, env)
            else:
                out["relaxed"].append("시간대 → 일 단위. 시간대 자료는 센터에서만 가능")
            breakdown = None
            if t["type"] == "T13":
                recipe = None
        if route == "center_csv":
            out["steps"].append({"sub": "S1", "op": "조회", "metric": m, "route": route, "source": src,
                                 "filter": {"dong": t["space"] or "전체", "target": t.get("target"), "time": t.get("time"), "detail": t.get("detail"), "details": t.get("details")}, "breakdown": breakdown})
            continue
        if route == "center_only":  # 완화 답: 공개 대체 지표로 답하고, 원래 지표는 센터에서 볼 수 있다고 안내한다
            subs_m = [x for x in CENTER_SUBSTITUTE.get(m, []) if pick_source(x, env)[0] == "public"]
            if not subs_m:
                out["notes"].append(f"{Q.METRICS.get(m, m)}: {src['note']}")
                continue
            out["relaxed"].append(f"{Q.METRICS.get(m, m)}: {src['note']}({src['dataset']}) → {'·'.join(subs_m)}로 대신 답함")
            for x in subs_m:
                flt = {"dong": t["space"] or "전체", "target": t.get("target"), "time": t.get("time"), "detail": t.get("detail"), "details": t.get("details")}
                out["steps"].append({"sub": "S1", "op": "조회", "metric": x, "route": "public", "source": pick_source(x, env)[1], "filter": flt, "breakdown": breakdown, "instead_of": m})
            continue
        if route is None:
            out["notes"].append(f"{m}: 지표 사전에 없음")
            continue
        flt = {"dong": t["space"] or "전체", "target": t.get("target"), "time": t.get("time"), "detail": t.get("detail"), "details": t.get("details")}
        out["steps"].append({"sub": "S1", "op": "조회", "metric": m, "route": route, "source": src, "filter": flt, "breakdown": breakdown})
    # 조건(비·주말 등): 조건 효과 레시피가 지원하는 지표가 아니면 조건 완화
    if t["cond"] and t["type"] not in ("T6",) and not season:
        cs = "·".join(t["cond"])
        if t["type"] == "T13" and set(t["cond"]) <= {"주말", "평일", "주말/평일"}:  # 화면에 그대로 보이는 문장이라 쉬운 말로(마스터 Windows 시험 2026-11-16)
            out["relaxed"].append("시간대 매출은 주말·평일을 나눈 자료가 없어요. 모든 요일을 합친 값이에요.")
        else:
            out["relaxed"].append(f"'{cs}' 조건으로 나눈 자료가 없어 이 답에는 반영하지 못했어요. 조건 없이 전체 값으로 답했어요.")
    if by_biz:
        for st in out["steps"]:
            if st.get("filter"):
                st["filter"] = dict(st["filter"], by="업종")
    for s in subs[1:]:
        if s == "S3" and recipe and recipe not in NO_CHECK:  # 학습 전 점검(S2)을 S3 앞에 둔다(사용자 결정 2026-11-11)
            out["steps"].append({"sub": "S2", "op": "학습 전 점검", "recipe": recipe})
        step = {"sub": s}
        if s == "S3":
            step.update(op="레시피 학습·검증·추론", recipe=recipe)
        elif s == "S6":
            step.update(op="판정(차이·동등성·짝 비교)")
        elif s == "S5":
            step.update(op="단위 맞추기(정류소→동네, 관측소→동네, 일→월)")
        elif s == "S2":
            step.update(op="기술 통계·추세·상관")
        elif s == "S4":
            step.update(op="차트·지도")
        out["steps"].append(step)
    _side_steps(t, out, metrics)
    seen, uniq = set(), []
    for st in out["steps"]:  # 같은 후속 단계(S4 등) 중복 제거
        key = json.dumps(st, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            uniq.append(st)
    out["steps"] = uniq
    if not any(st["sub"] == "S1" for st in out["steps"]) and out["status"] == "ok":
        out["status"] = "자료 없음"
    return out


if __name__ == "__main__":
    import qparse
    for q in sys.argv[1:]:
        t = qparse.parse(q)
        for env in ({"center_db": False}, {"center_db": True}):
            p = plan(t, env)
            print(q, "| 센터 DB" if env["center_db"] else "| 공개", "|", p["status"], [f"{s['sub']}:{s.get('metric') or s.get('recipe') or s.get('op')}" for s in p["steps"]], p["relaxed"], p["notes"])
