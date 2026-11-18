"""여러 단계·기법 + 일반 질문(Agent 문항)의 단계 처리 측정(2026-11-16).

사용: python tools/eval/agent_steps_eval.py --file 문항.jsonl --mode step|loop [--out 결과.json]
- 문항: 조정용 data/eval/route_test_100.jsonl(원본 interaction/gemini_work/047), 판정용 data/eval/route_eval_200.jsonl. group a(여러 단계)·b(기법 + 일반)만 쓴다.
- step: 서비스 경로의 단계형 Agent(app/step_agent.serve). loop: 옛 도구 루프(app/expert.ask, mode=escalate, 로컬 모델).
- 채점: 정답 단계(parts)마다, 성공한 도구 호출 가운데 도구 종류·동네·지표 묶음이 맞는 것이 하나라도 있으면 그 단계를 처리한 것으로 본다.
  모든 단계를 처리한 문항만 '성공'이다. 호출 인자(단계형은 단계 답의 해석)를 보므로 답 내용까지 맞는지는 보지 않는다(후한 채점).
- 답 내용 채점(content): 실제 답 문장 하나 안에 정해진 동네·지표 낱말·순위/예측 표지가 함께 있는지 본다(아래 content_ok). 하위 질문 문장은 보지 않는다.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
args = sys.argv[1:]
FILE = Path(args[args.index("--file") + 1])
MODE = args[args.index("--mode") + 1] if "--mode" in args else "step"
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else None
STAFF = "--staff" in args  # 심사용 계정으로 로그인한 요청처럼(단계별 도구 고르기에 Claude, 모델은 JEJU_STEP_CLAUDE_MODEL). 2026-11-18 모델 비교

FAM = {"매출": {"매출", "매출성장", "이용건수", "건당금액", "시간대매출", "과거매출", "업종비교", "시장추이"}, "유동인구": {"일평균방문", "시간대방문", "시간대매출", "방문거주비", "청년비중", "고령비중", "방문연령구성"},
       "방문인구": {"일평균방문", "시간대방문", "방문거주비"}, "생존율": {"5년생존율", "조건부생존", "폐업률"}, "폐업률": {"폐업률", "폐업수", "5년생존율"}, "개업수": {"개업수"},
       "점포수": {"점포수", "특화계수"}, "특화계수": {"특화계수", "점포수"}, "인구비중": {"고령비중", "청년비중", "거주연령구성", "방문연령구성"}, "버스이용": {"버스일평균", "정류소일이용"},
       "매출변화": {"매출", "매출성장"}}
PLACEHOLDER = {"선정동", "유사동", "선정업종", "제주"}  # '제주'는 특정 동네가 아니라 제주 전체(2026-11-17 Gemini 067 라벨)


def covered(part, calls):
    sp = set(part.get("space") or []) - PLACEHOLDER
    ms = part.get("metric_ok") or []
    fam = set().union(*[FAM.get(m, set()) for m in ms]) if any(m in FAM for m in ms) else None
    for tool, a in calls:
        if part.get("type") == "기법분석":
            if tool == "run_technique":
                return True
            continue
        if tool != "answer_topic" and part.get("type") not in ("T15", "T7"):
            continue
        if sp and not (sp & set(a.get("space") or a.get("dongs") or [])):
            continue
        if part.get("type") in ("T8", "T9") and tool == "answer_topic" and a.get("type") != part["type"]:
            continue
        if fam and tool == "answer_topic" and a.get("type") not in ("T10", "T9", "T8") and not (set(a.get("metric") or []) & fam):
            continue
        return True
    return False


# 답 내용 채점(2026-11-16 마스터 '채점 기준 수립하여 진행'): 호출 인자가 아니라 실제 답 문장을 본다.
# 정답 단계마다 ① 답 문장이 있고 ② 정해진 동네 이름이 나오고(앞 결과로 정해지는 칸은 보지 않음) ③ 지표 묶음 낱말이 나오고
# ④ 순위('n위')·예측('예측·예상')·비슷한 동네('비슷한') 단계는 그 표지가 나와야 맞음으로 센다.
WORDS = {"매출": r"매출", "유동인구": r"방문", "방문인구": r"방문", "생존율": r"생존", "폐업률": r"폐업", "개업수": r"개업", "점포수": r"점포|가게 수",
         "특화계수": r"특화|입지계수", "인구비중": r"비중|연령|60대|20~30대", "버스이용": r"버스", "매출변화": r"매출|증가|감소|늘었|줄었",
         "유사도": r"비슷한", "상관분석": r"상관", "변이할당": r"변이할당|성장 효과", "생존분석": r"생존", "회귀분석": r"회귀|설명", "계절분해": r"계절|추세",
         "수명표": r"생존|영업", "분산분석": r"검정|차이", "이상치탐지": r"튀는|이상", "교차상관": r"상관", "입지계수": r"입지계수|몰려", "이용건수": r"건수|이용",
         # 2026-11-17 실패 유형 6가지 새 문항(Gemini 067)의 지표 이름
         "포화도": r"포화|1곳당|한 곳당|점포당", "강수 효과": r"비\s*오|비가|강수|날씨|맑은", "폐업수": r"폐업|문 닫", "매출": r"매출", "매출성장": r"매출|증가|감소|늘었|줄었",
         "상관": r"상관", "시계열분해": r"계절|추세", "군집분석": r"군집|비슷한|묶", "업종다양성": r"다양성|고르게"}
REFUSE = r"할 수 없|없어요|하지 않았어요|계산하지 않|자료가 없|넣을 수 없|알 수 없"  # '할 수 없음' 단계: 할 수 없다고 밝힌 문장이 있으면 맞음
KIND = {"T3": r"\d+위", "T8": r"예측|예상", "T9": r"비슷한"}


def content_ok(part, sentences):
    """한 문장 안에 정해진 동네·지표 낱말·종류 표지가 함께 있어야 맞음(문장끼리 섞여 맞는 것을 막는다)."""
    import re
    sp = set(part.get("space") or []) - PLACEHOLDER
    if part.get("expect") == "할 수 없음":
        return any(re.search(REFUSE, t) for t in sentences)
    ws = [WORDS[m] for m in part.get("metric_ok") or [] if m in WORDS]
    k = KIND.get(part.get("type"))
    for t in sentences:
        if sp and not any(d in t for d in sp):
            continue
        if ws and not any(re.search(w, t) for w in ws):
            continue
        if k and not re.search(k, t):
            continue
        return True
    return False


def content_score(row):
    """row: {'parts', 'lines'}. 답 줄을 문장으로 나눠(단계형은 '질문 → 답'의 답 쪽) 정답 단계마다 맞는 문장이 있는지 본다."""
    import re
    sents = []
    for x in row.get("lines") or []:
        if not x:
            continue
        x = str(x).split(" → ", 1)[-1]  # 단계형 줄의 하위 질문 쪽은 보지 않는다(질문 문장에 낱말이 있어 맞는 것을 막음)
        sents += [s.strip() for s in re.split(r"(?<=[.?!요])\s+", x) if s.strip()]  # '다' 뒤 띄어쓰기로는 나누지 않는다('제주 전체보다 가장 몰려…'가 '보다'에서 잘려 동네와 지표가 다른 문장이 되던 채점기 결함, 2026-11-17)
    return [content_ok(p, sents) for p in row.get("parts") or []]


def run_step(q):
    """서비스(api._ask_work)와 같은 순서로 답한다(2026-11-17): 기법 이름이 있는 한 문장 질문 → 정해진 기법, 두 업종 견주기 → biz_compare, 나머지 → 단계형 Agent."""
    import biz_compare
    import split
    import step_agent
    import techniques
    multi_q = (split.enabled() and len(split.pieces(q)) >= 2) or len(step_agent.clauses(q)) >= 2  # api._ask_work와 같게
    if os.environ.get("JEJU_EVAL_API_ROUTE", "1") == "1" and techniques.detect(q) and not multi_q:
        x = techniques.answer(q)
        return x, [("run_technique", {})] if (x.get("card") or {}).get("conclusion") else []
    if os.environ.get("JEJU_EVAL_API_ROUTE", "1") == "1" and biz_compare.detect(q):
        x = biz_compare.answer(q)
        return x, [("answer_topic", {"space": (x.get("understood") or {}).get("slots", {}).get("space") or [], "metric": ["점포수", "매출"]})]
    x = step_agent.serve(q, {"staff": STAFF}, llm_on=False)
    calls = []
    if x.get("status") == "Agent":
        for tp in (x.get("agent") or {}).get("topics") or []:
            calls.append(("answer_topic", tp.get("tuple") or {}))
        for t in (x.get("agent") or {}).get("trace") or []:
            if t.get("tool") == "run_technique" and t.get("ok"):
                calls.append(("run_technique", {}))
    elif (x.get("card") or {}).get("evidence"):
        calls.append(("answer_topic", x.get("tuple") or {}))
    return x, calls


def run_loop(q):
    import expert
    x = expert.ask(q, mode="escalate")
    calls = []
    for t in x.get("trace") or []:
        if t.get("ok") and t.get("tool") in ("answer_topic", "run_technique"):
            try:
                calls.append((t["tool"], json.loads(t.get("args") or "{}")))
            except ValueError:
                calls.append((t["tool"], {}))
    return x, calls


def main():
    if MODE == "loop":
        os.environ["JEJU_ANALYST"] = "0"
    items = [json.loads(x) for x in FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    items = [r for r in items if r.get("group") in ("a", "b")]
    rows = []
    for r in items:
        t0 = time.perf_counter()
        x, calls = (run_loop if MODE == "loop" else run_step)(r["q"])
        cov = [covered(p, calls) for p in r.get("parts") or []]
        lines = (x.get("agent") or {}).get("lines") or x.get("lines") or [(x.get("card") or {}).get("conclusion")] + [e.get("text") for e in (x.get("card") or {}).get("evidence") or []]
        con = content_score({"parts": r.get("parts"), "lines": lines})
        row = {"id": r["id"], "group": r["group"], "done": sum(cov), "parts": len(cov), "ok": all(cov), "content_done": sum(con), "content_ok": all(con),
               "status": x.get("status"), "lines": lines, "sec": round(time.perf_counter() - t0, 1)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summ = {"file": FILE.name, "mode": MODE}
    for g in ("a", "b"):
        gs = [x for x in rows if x["group"] == g]
        summ[f"{g} 모든 단계 처리"] = f"{sum(x['ok'] for x in gs)}/{len(gs)}"
    summ["전체"] = f"{sum(x['ok'] for x in rows)}/{len(rows)}"
    summ["처리한 단계"] = f"{sum(x['done'] for x in rows)}/{sum(x['parts'] for x in rows)}"
    summ["답 내용 채점: 모든 단계"] = f"{sum(x['content_ok'] for x in rows)}/{len(rows)}"
    summ["답 내용 채점: 단계"] = f"{sum(x['content_done'] for x in rows)}/{sum(x['parts'] for x in rows)}"
    secs = sorted(x["sec"] for x in rows)
    summ["지연 중앙값"] = secs[len(secs) // 2] if secs else None
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if OUT:
        OUT.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
