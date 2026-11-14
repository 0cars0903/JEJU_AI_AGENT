"""W8 결과 생성 Agent (docs/기획/05_Agent구조_v2.md 4-5절, 2026-11-11 구현).

입력: 검수(verify.review)를 거친 결과. 출력: 응답 JSON
  understood  "이렇게 이해했어요" — 해석한 칸, 추정 여부, [바꾸기]에서 미리 골라 둘 버튼 값(slots)
  card        답 카드 — 결론 한 줄 → 근거 수치(자료별 기준일) → 구간 → 한계 → 다음 질문 3개. 수치 문장은 코드 템플릿이다.
  suggestions 추천 질문 3개(버튼 값 포함, 해석 없이 바로 답함)
  process     판단 과정 — 질문 Tuple, 고른 자료와 이유(M3-b 해설), 완화한 축, 쓰지 못한 자료와 이유, 검수 기록
  choose      예외(추정할 수 없음) — 상황 안내 문장과 다음에 고를 칸(동네·주제), 미리 골라 둔 값
  downloads   집계표 CSV(반출 불가 자료는 검수에서 집계만 남김)와 차트 명세
되묻기 Loop 방지(사용자 결정 2026-11-11 17:25): 되묻지 않고 가장 가능성 높은 해석으로 답한다. 동네가 없거나 여러 동네로 읽히는 등
추정할 수 없을 때만 status '선택필요'로 상황을 알리고 단계별 선택으로 넘긴다. 버튼 값(slots)으로 온 질문은 해석하지 않는다.
LLM은 M3-b(계획 해설 1~2문장) 한 곳만 쓴다. 숫자를 쓰면 버리고 템플릿으로 대체한다.
진입점: respond(question, env, llm_on=True, slots=None)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guide as G  # noqa: E402
import layers  # noqa: E402
import llm  # noqa: E402
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402
import recipes  # noqa: E402
import verify as V  # noqa: E402
from textcheck import BANNED, DONG_NUM, UNFOUNDED, _norm, check_numbers, is_korean  # noqa: E402

UNIT_NOTE = {"지수": "유동인구는 사람 수가 아니라 지수예요(통신 자료 추계)."}
CLAIM_KO = {"효과 있음": "차이가 있어요", "작지만 0은 아님": "차이는 있지만 ±10% 안의 작은 차이예요",
            "작음 확인": "차이가 ±10% 안으로 작아요", "판단 불가": "차이를 확인하지 못했어요"}
TYPE_KO = {"T1": "현황 조회", "T2": "동네 비교", "T3": "순위", "T4": "추세", "T5": "구성", "T6": "조건 효과", "T7": "관계", "T8": "예측",
           "T9": "비슷한 동네", "T10": "종합 진단", "T11": "자료 찾기", "T13": "시간대 패턴", "T14": "조건 탐색", "T15": "이례 변화"}
SUB_KO = {"S0": "자료 탐색", "S1": "조회", "S2": "통계·점검", "S3": "모델", "S4": "차트", "S5": "단위 맞추기", "S6": "판정"}
from prompts import M3B_SYSTEM, M3B_TOOL, M3B_FORMAT  # noqa: E402

# ---------- 공통 ----------
def _label(m):
    return Q.METRICS.get(m, m)


def _josa(w, a="은", b="는"):
    c = ord(w[-1]) - 0xAC00
    return w + (a if 0 <= c <= 11171 and c % 28 else b)


def _num(v):
    v = float(v)
    return f"{int(v):,}" if v == int(v) else f"{round(v, 1):,}"


def _as_of(tab):
    c = next((x for x in ("ym", "year") if x in tab), None)
    return (c, tab[c].max()) if c else (None, None)


def llm_text_ok(text, question=""):
    """LLM 문장 검사: 숫자 없음(동네 이름의 숫자, 질문에 이미 있는 '3년' 같은 말은 허용), 한국어, 금지 표현·근거 없는 해석 없음."""
    p = []
    if not text:
        return ["빈 문장"]
    plain = DONG_NUM.sub(" ", _norm(text))
    for tok in re.findall(r"\d+\s*[년개월주일]", question or ""):
        plain = plain.replace(tok, " ")
    if re.search(r"\d", plain):
        p.append("숫자")
    if not is_korean(text):
        p.append("한국어 아님")
    if BANNED.search(text) or UNFOUNDED.search(text):
        p.append("금지 표현")
    return p


def _ask_llm(system, user, timeout_ok=True):
    """계획 해설 한 문장. llm.backend()를 따른다(키 있으면 Claude → Ollama). 출력은 {"text"} 한 칸으로 고정(2026-11-13).
    Claude: submit_plan_text 도구(strict), 생각 깊이 low. Ollama: format JSON 스키마. 돌려주는 값: (문장, 오류, 초, 백엔드)."""
    t0 = time.perf_counter()
    name = llm.backend()
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        if name == "claude":
            m = llm.chat(None, msgs, [M3B_TOOL], name="claude", effort="low")["message"]
            args = next((c["function"]["arguments"] for c in m.get("tool_calls") or [] if c["function"]["name"] == "submit_plan_text"), None)
            if isinstance(args, str):
                args = json.loads(args)
            out = (args or {}).get("text", "").strip()
        else:
            raw = llm.chat(None, msgs, [], name="ollama", max_tokens=160, fmt=M3B_FORMAT)["message"].get("content", "").strip()
            out = str(json.loads(raw).get("text", "")).strip() if raw.startswith("{") else raw
    except Exception as e:
        return None, f"LLM 오류 {type(e).__name__}", time.perf_counter() - t0, name
    return out, None, time.perf_counter() - t0, name


# ---------- 답 카드 ----------
def _interval_ko(rid):
    """예상 범위 설명을 쉬운 말로 쓴다(문서 20 A2·A10: 'R1'·'관문 v3'·'포함률' 같은 내부 용어를 화면에 내지 않는다). 숫자는 등록부(recipes.json) 값만 쓴다."""
    reg = recipes.REG[rid]
    raw, name = reg.get("interval") or "", reg["name"]
    m = re.search(r"80% 구간 포함률 (\d+)~(\d+)%", raw)
    if m:  # R1: 예상 범위를 싣되 지난 기록의 실제 적중 비율을 함께 적는다(문서 21 3.1절)
        narrow = "(범위가 좁게 잡혀요)" if int(m.group(1)) < 75 else ""
        return (f"{name}의 예상 범위는 지난 세 시점의 예상이 빗나간 크기를 보고 10번 중 8번 맞도록 잡은 폭이에요. 지난 기록으로 확인했더니 "
                f"100번 중 {m.group(1)}~{m.group(2)}번 맞았어요{narrow}. 실제 값은 범위를 벗어날 수 있어요.")
    if raw.startswith("80% 구간"):
        return f"{name}의 예상 범위는 지난 예상이 빗나간 크기를 보고 10번 중 8번 맞도록 잡은 폭이에요."
    return f"{name} 예상 범위: {raw}"


def _evidence(order, res):
    ev, intervals, as_of = [], [], {}
    tasks = {t["out"]: t for t in order["tasks"]}
    for k, v in res["store"].items():
        t = tasks.get(k, {})
        if "table" in v and t.get("sub") == "S1" and len(v["table"]):
            tab = v["table"]
            c, last = _as_of(tab)
            cur = tab[tab[c] == last] if c else tab
            when = str(last)[:7] if c else (layers.v3.BIZ_ASOF if t.get("metric") in ("점포수", "특화계수") else "-")
            as_of[v.get("dataset")] = when
            m = t.get("metric")
            if "ageGroup" in cur:  # 연령 구성은 많은 순서만(값은 지수라 비중 계산을 따로 하지 않는다)
                for d, g in cur.groupby("dong"):
                    order_ = g.sort_values("value", ascending=False)["ageGroup"].astype(str).head(3).tolist()
                    ev.append({"metric": m, "text": f"{d} 거주 인구 많은 연령대: {', '.join(order_)}", "dataset": v.get("dataset"), "as_of": when})
                continue
            if "hour" in cur:  # 시간대 비중: 동네마다 비중이 큰 시간 3개
                for d, g in cur.groupby("dong"):
                    top = g.sort_values("value", ascending=False).head(3)
                    ev.append({"metric": m, "dong": d, "text": f"{d} 매출이 많은 시간: " + ", ".join(f"{int(h)}시 {_num(x)}%" for h, x in zip(top["hour"], top["value"])),
                               "dataset": v.get("dataset"), "as_of": when})
                continue
            if "origin" in cur:  # 외국인 출신지역 구성(제주 전체)
                top = cur.sort_values("value", ascending=False).head(4)
                ev.append({"metric": m, "text": "외국인 관광객 카드 매출(제주 전체) 많은 출신지역: " + ", ".join(f"{o} {_num(x)}원" for o, x in zip(top["origin"], top["value"])),
                           "dataset": v.get("dataset"), "as_of": when})
                continue
            if "dong" in cur and cur["dong"].nunique() > 6:  # 여러 동네(순위·전체 조회)는 값이 큰 순서로 보여 준다
                cur = cur.sort_values("value", ascending=False)
            for r in cur.head(6).to_dict(orient="records"):
                ev.append({"metric": m, "dong": r.get("dong"), "value": r["value"], "unit": v.get("unit"),
                           "text": f"{r.get('dong', '')} {_label(m)} {_num(r['value'])}{'' if v.get('unit') in ('-', None) else ' ' + v['unit']}",
                           "dataset": v.get("dataset"), "as_of": when})
        if v.get("survival"):
            s = v["survival"]
            ev.append({"metric": "업종 5년생존율", "text": f"{s['group']} 5년 생존율 {_num(s['surv5_pct'])}% (표본 {s['n']:,}곳, 제주 전체)", "dataset": "780 음식점 인허가", "as_of": f"개업 {s.get('cohort') or '2015-01~2020-08'} 코호트"})
            intervals.append(f"{s['group']} 5년 생존율은 표본으로 계산한 값이라 ±{_num(s['ci95_pp'])}%p 안에서 달라질 수 있어요(100번 중 95번 맞게 잡은 폭).")
        if v.get("forecast") and any(j.get("use_forecast") for j in V._judgements(res["store"]) if j["name"] == f"관문 {v.get('recipe')}"):  # 관문 통과한 예측만 쓴다(15-6)
            fc = v["forecast"]
            key = "visit" if "visit" in fc[0] else "value"
            hi, lo = max(fc, key=lambda r: r[key]), min(fc, key=lambda r: r[key])
            if hi is lo:
                hi = lo = fc[0]
            when = lambda r: r.get("date") or r.get("ym")  # noqa: E731
            ev.append({"metric": "예측", "kind": "forecast", "recipe": v.get("recipe"),
                       "text": f"{hi['dong']} 예측 최고 {when(hi)} {_num(hi[key])}, 최저 {when(lo)} {_num(lo[key])}", "dataset": f"레시피 {v.get('recipe')}", "as_of": v.get("data_last") or "-"})
            intervals.append(_interval_ko(v["recipe"]))
        if v.get("neighbors"):
            for d, nb in v["neighbors"].items():
                ev.append({"metric": "비슷한 동네", "text": f"{_josa(d, '과', '와')} 비슷한 동네: {', '.join(nb)}", "dataset": "레시피 R5", "as_of": "-"})
        if v.get("anomaly"):
            for a in v["anomaly"]:
                if a["flag"] != "보통":
                    ev.append({"metric": "이례", "text": f"{a['dong']} {a['year']}년 {v.get('kind')} {a['count']}곳({a['flag']})", "dataset": "레시피 R7", "as_of": str(a["year"])})
        if "table" in v and t.get("sub") == "S0":
            for r in v["table"].head(8).to_dict(orient="records"):
                ev.append({"metric": "자료", "text": f"{r['name']} — {r.get('source')}, 반출 {r.get('export')}", "dataset": "자료 목록", "as_of": r.get("period") or "-"})
    for j in V._judgements(res["store"]):
        if "ci95" in j:
            intervals.append(f"{j['name']}: 조건에 따른 차이는 {_num(j['ci95'][0])}% ~ {_num(j['ci95'][1])}% 사이로 봐요(100번 중 95번 맞게 잡은 폭).")
    return ev, intervals, as_of


def _conclusion(t, order, res, ev, review):
    js = V._judgements(res["store"])
    dong = "·".join(t.get("space") or []) or "제주"
    if review["status"] == "부분 결과" and not ev:
        return "확인된 결과가 없어요. 아래 '계산하지 못함'을 확인해 주세요."
    nb = next((e for e in ev if e["metric"] == "비슷한 동네"), None)
    if t.get("type") == "T9" and nb:
        return nb["text"] + "(업종 구성·연령·방문·버스가 가까운 순)."
    sv = next((e for e in ev if e["metric"] == "업종 5년생존율"), None)
    if sv:
        return sv["text"] + "."
    gate = next((j for j in js if j["name"].startswith("관문")), None)
    if gate:
        rid = gate["name"].split()[-1]
        name = recipes.REG[rid]["name"]
        return (f"{dong} {name}: 모델이 단순 기준(7일 전 값 등)보다 정확해 예측값을 써요." if gate["use_forecast"]
                else f"{dong} {name}: 모델이 단순 기준보다 낫지 않아 예측값 대신 최근 값으로 답해요.").replace("(7일 전 값 등)", "")
    eff = [j for j in js if j.get("claim") in CLAIM_KO and "ci95" in j]
    if eff:
        cond = "·".join(t.get("cond") or []) or "조건"
        return " / ".join(f"{cond}에 따른 {j['name']} {_label((t.get('metric') or ['일평균방문'])[0])}: {CLAIM_KO[j['claim']]}" for j in eff[:3])
    trend = next((j for j in js if j["name"] == "추세"), None)
    if trend:
        tm = next((x.get("metric") for x in order["tasks"] if x["sub"] == "S1" and x["out"] in res["store"]
                   and any(c in getattr(res["store"][x["out"]].get("table"), "columns", []) for c in ("year", "ym"))), None)
        word = "늘었어요" if trend["claim"].startswith("증가") else "줄었어요"
        if "(유의)" in trend["claim"]:
            return f"{dong} {_label(tm)}: 최근 {word}(통계적으로 유의)."
        return f"{dong} {_label(tm)}: 최근 {word[:-2]}지만 통계적으로 의미 있는 변화는 확인하지 못했어요."
    if any(j.get("claim") in ("이례 증가", "이례 감소") for j in js):
        return f"{dong}: 올해 평소와 다른 변화가 있어요."
    nums = [e for e in ev if e.get("dong") and e.get("value") is not None]
    if t.get("type") == "T2" and len({e["dong"] for e in nums}) >= 2:  # 비교: 있는 값끼리 크기만 말한다(새 숫자를 만들지 않음)
        m = nums[0]["metric"]
        g = sorted([e for e in nums if e["metric"] == m], key=lambda e: -float(e["value"]))
        return f"{_label(m)}: {_josa(g[0]['dong'], '이', '가')} {', '.join(e['dong'] for e in g[1:])}보다 많아요({', '.join(e['dong'] + ' ' + _num(e['value']) for e in g)})."
    if t.get("type") == "T11":
        return "관련 자료 목록이에요. 반출 여부를 함께 적었어요." if ev else "관련 자료를 찾지 못했어요."
    if ev:
        return ev[0]["text"] + "."
    return "확인된 결과가 없어요."


def card(t, review, ev, intervals):
    order, res = review["order"], review["run"]
    limits = list(res.get("relaxed", []))
    limits += sorted({v["note"] for v in res["store"].values() if isinstance(v, dict) and v.get("note") and "table" in v})  # 조회 결과의 자료 범위 한계만(판정 단계 메모 제외)  # 자료 범위 한계(예: 카드 매출 업종 대분류)
    limits += [UNIT_NOTE[u] for u in {e.get("unit") for e in ev} if u in UNIT_NOTE]
    limits += [f"계산하지 못함: {SUB_KO.get(x.get('sub'), '')} {x.get('error')}" for x in _failed(order, res)]
    if any("업종 구분 없음" in str(e.get("dataset")) for e in ev) and any(e["metric"] == "업종 5년생존율" for e in ev):
        limits.append("동네별 생존율은 음식점 전체 값이고, 업종별 생존율은 동네 표본이 작아 제주 전체 값이에요.")
    for v in res["store"].values():
        if v.get("survival") and v.get("fallback"):
            limits.append(f"표본 부족: {v['fallback']}")
    for r in review["record"]:
        if r["type"] == "효과 없음" and "관문" in r["detail"]:
            rid = r["detail"].split()[1].rstrip(":")
            limits.append(f"{recipes.REG[rid]['name']}: 모델이 단순 기준보다 낫지 않아 예측값을 쓰지 않고 최근 값으로 답해요")
    limits = [layers.plain_names(x) for x in limits]  # 한계 문구에도 자료 번호를 싣지 않는다(문서 20 A10)
    return {"conclusion": _conclusion(t, order, res, ev, review), "evidence": ev, "intervals": intervals, "limits": limits, "next_questions": [x["text"] for x in G.suggestions(t)]}


def _failed(order, res):
    subs = {t["id"]: t["sub"] for t in order["tasks"]}
    return [dict(x, sub=subs.get(x["task_id"])) for x in res.get("log", []) if x["status"] in ("실패",)]


def card_problems(c, res):
    """수치 대조: 카드의 결론·근거·구간 문장 숫자는 결과 저장소에 있어야 한다. 다음 질문·한계 문구(정책 문장)는 제외."""
    text = "\n".join([c["conclusion"], *[e["text"] for e in c["evidence"]], *c["intervals"]])
    allowed = V._plain(res["store"]) + [recipes.REG]  # 구간 설명 문구는 등록부의 고정 문장
    return check_numbers(text.replace("±10%", ""), allowed)


# ---------- M3-b 계획 해설 ----------
REWRITES = 2  # 안 B: 해설 다시 쓰기 상한


def explain_plan(question, t, order, res, llm_on=True):
    data = []
    for x in order["tasks"]:
        if x["sub"] == "S1":
            src = x.get("source") or {}
            nm = re.sub(r"^\d+\s*", "", str((res["store"].get(x["out"]) or {}).get("dataset") or src.get("name") or x.get("metric")))
            data.append(f"{_label(x.get('metric'))}({nm})")
    path = " → ".join(dict.fromkeys(SUB_KO[x["sub"]] for x in order["tasks"]))
    tpl = f"질문을 '{TYPE_KO.get(t['type'], t['type'])}'로 보고 {', '.join(data) or '자료 목록'}을 골라 {path} 순서로 계산했어요."
    if not llm_on:
        return {"text": tpl, "by": "템플릿", "sec": 0.0}
    user = f"질문: {question}\n질문 종류: {TYPE_KO.get(t['type'])}\n고른 자료: {', '.join(data) or '자료 목록'}\n계산 순서: {path}"
    subs = {x["sub"] for x in order["tasks"]}

    def check(out):
        probs = llm_text_ok(out, question)
        if not probs and not re.search(r"(어요|아요|해요|예요|이에요)\.?$", out):
            probs = ["문체('~해요' 아님)"]
        for pat, need in ((r"판정|우연", "S6"), (r"예측|모델", "S3"), (r"그래프|차트", "S4"), (r"단위", "S5")):  # 없는 단계를 말하면 사실과 다른 해설
            if not probs and re.search(pat, out) and need not in subs:
                probs = [f"없는 단계 언급({need})"]
        if not probs and re.search(r"연도별", out) and not any("year" in getattr((res["store"].get(x["out"]) or {}).get("table"), "columns", []) for x in order["tasks"]):
            probs = ["없는 단계 언급(연도별)"]
        return probs

    # 안 B(문서 26): 검사에 걸리면 틀린 문장과 이유를 돌려 최대 REWRITES번 다시 쓰게 한다. 그래도 걸리면 템플릿.
    tries, total = [], 0.0
    ask = user
    for i in range(REWRITES + 1):
        out, err, sec, name = _ask_llm(M3B_SYSTEM, ask)
        total += sec
        probs = [err] if err else check(out)
        tries.append({"text": out, "problems": probs})
        if not probs or err:
            break
        ask = f"{user}\n\n앞서 쓴 문장: {out}\n검사에서 걸린 이유: {', '.join(probs)}\n이유를 고쳐 규칙대로 다시 쓰세요."
    if probs:
        return {"text": tpl, "by": "템플릿(LLM 대체)", "llm_raw": out, "problems": probs, "rewrites": len(tries) - 1, "tries": tries, "sec": round(total, 3), "backend": name}
    return {"text": out, "by": "LLM", "rewrites": len(tries) - 1, "tries": tries if len(tries) > 1 else None, "sec": round(total, 3), "backend": name}


# ---------- 내려받기 ----------
def bundle_csv(order, res):
    """패턴 I: 이 답의 자료를 한 파일로(긴 형식: 자료·지표·동네·시점·값·단위). 반출 불가 자료는 검수에서 이미 집계만 남았다."""
    import io
    import pandas as pd
    tasks = {t["out"]: t for t in order["tasks"]}
    rows = []
    for k, v in res["store"].items():
        t = tasks.get(k, {})
        if t.get("sub") != "S1" or "table" not in v or not len(v["table"]):
            continue
        tab = v["table"].copy()
        tcol = next((c for c in ("ym", "year", "hour") if c in tab), None)
        key = next((c for c in ("dong", "origin", "biz", "name") if c in tab), None)
        rows.append(pd.DataFrame({"자료": v.get("dataset"), "지표": Q.METRICS.get(t.get("metric"), t.get("metric")), "대상": tab[key] if key else "",
                                  "시점": tab[tcol].astype(str) if tcol else "", "값": tab["value"], "단위": v.get("unit")}))
    if not rows:
        return None
    b = io.StringIO()
    pd.concat(rows).to_csv(b, index=False)
    return b.getvalue()


def downloads(order, res):
    out = []
    for t in order["tasks"]:
        v = res["store"].get(t["out"])
        if v is not None and "table" in v and len(v["table"]):
            out.append({"kind": "csv", "name": f"{t['id']}_{t.get('metric') or 'catalog'}.csv", "rows": int(len(v["table"])), "export": v.get("export", "가능"),
                        "csv": v["table"].to_csv(index=False)})
        if t["sub"] == "S4" and v:
            out.append({"kind": "chart", "name": f"{t['id']}_chart.json", "chart": v.get("chart")})
    b = bundle_csv(order, res)
    if b:
        out.insert(0, {"kind": "bundle", "name": "이 답의 자료.csv", "rows": b.count("\n") - 1, "export": "집계", "csv": b})
    return out


# ---------- 진입점 ----------
def _choose(question, t, slots, message, step, candidates=None, sec=0.0):
    return {"question": question, "status": "선택필요", "tuple": t,
            "choose": {"message": message, "step": step, "candidates": candidates or [], "preset": slots}, "sec": round(sec, 3)}


MY_DONG = re.compile(r"(우리|내|저희|제)\s*(동네|집|가게)|집\s*(근처|앞|주변)|이\s*동네|여기\s*(근처|주변)?")
MY_DONG_MSG = "이 서비스는 위치 정보를 쓰지 않아서 '우리 동네'가 어디인지 알 수 없어요. 동네 이름을 골라 주세요."
FOREIGN_Q = re.compile(r"외국인|중국인|일본인|중화권|해외\s*관광객")
SPEND_Q = re.compile(r"매출|소비|결제|손님|카드|돈|써|쓰|쓴|쓸|팔")
VS_Q = re.compile(r"비교|견주|vs|VS|중에|중 (어디|뭐|무엇|어느)|(뭐|무엇|어느 쪽|어디)[이가]? 더|[이가] 더 (많|적)")
TOUR_COUNT_Q = re.compile(r"관광객.{0,6}(얼마나|몇\s*명|많이|얼마|수가|수는).{0,6}(와|오[나는니]|온|올|방문|찾)|관광객\s*(방문자|입도객|방문)\s*(수|규모)(?![준요])")
TOUR_NOTE = "관광객 방문자 수 자료는 없어요. 대신 카드 매출에서 도민과 관광객이 차지하는 비중을 보여 드려요."
FOREIGN_NOTE = "동네별 외국인 카드 매출은 공개 자료에 없어요. 그래서 제주 전체 값을 출신지역별로 보여 드려요. 동네별 값은 아래 '자료 요청' 카드의 센터 자료로 볼 수 있어요."
# 5개 업종(Q.TARGETS_OUT)의 가게 수 밖 질문. 비씨카드 42개 업종 목록은 허브 746(2017~2021)에서 확인했다. 센터 자료(1-08)의 목록은 직접 보지 못했다.
OUT_ONLY_COUNT = "{we} 가게 수만 볼 수 있어요(상가 정보). "
OUT_NO_CARD = "카드 매출은 공개 자료에 업종 대분류 5개로만 있어서 {w}만 따로 볼 수 없어요. 비씨카드 42개 업종 목록(2017~2021년 공개분)에도 {we} 없어요."
OUT_NO_OPEN = "개업·폐업·생존율은 음식점 인허가 자료로 계산해서 음식점 업종만 볼 수 있어요."
LOW_CONF = 0.5  # 이보다 확신도가 낮으면 추정하지 않는다(X1 024: 0.5 미만 유형 정답 26/39, 0.8 이상 58/58)
TIME_WORDS = re.compile(r"언제|몇\s*시|시간대|붐비|붐벼|한산|출근|퇴근|점심\s*때|저녁\s*때")
SALES_WORDS = re.compile(r"매출|잘\s*(되|돼)|장사|수익|벌이|벌어")
ONLY_DONG_REST = re.compile(r"[\s?!.,~]|동네|은|는|이|가|도|어때요?|어떤가요|알려\s*줘|보여\s*줘|궁금해|진단해?\s*줘?|좀|요")


def _blocked(question, t, message, alts):
    """답할 수 없는 질문은 답을 만들지 않고 이유와 대신 볼 수 있는 질문(버튼 값)을 준다(범위 확장 없음·차단, 2026-11-11 17:25)."""
    sug = [{"text": G.sentence(a), "slots": a} for a in alts] or [{"text": x["text"], "slots": x["slots"]} for x in G.representative()[:3]]
    return {"question": question, "status": "범위밖", "tuple": t,
            "card": {"conclusion": message, "evidence": [], "intervals": [], "limits": [], "next_questions": [x["text"] for x in sug]}, "suggestions": sug}


MONTH_EXT = re.compile(r"(가장|제일|최고|최저)\s*(많|적|높|낮|잘|안\s*되|붐비|한산)\S*\s*(달|월)|(몇\s*월|어느\s*달|무슨\s*달)\S*\s*(가장|제일)?\s*(많|적|높|낮|잘|안)")
REASON_Q = re.compile(r"이유|왜|원인|때문")
REASON_NOTE = "원인은 자료만으로 단정할 수 없어요. 결제 건수와 건당 금액의 변화(변화 분해), 비 온 날의 차이를 함께 보면 짐작하는 데 도움이 돼요."


def _plain_answer(question, t, concl, ev, limits, tag, src, as_of, t0, path, notes=()):
    """코드가 직접 계산한 짧은 답(센터 버스·가장 많은/적은 달)의 공통 모양."""
    return {"question": question, "status": "성공", "tuple": t, "interpret": {"path": path, "card": None},
            "understood": {"text": f"이렇게 이해했어요: {', '.join(t.get('space') or []) or '제주'} {tag}", "by": path, "assumed": False, "slots": {}, "notes": list(notes), "check": []},
            "card": {"conclusion": concl, "evidence": [{"text": e, "tag": tag, "layer": "L1", "dataset": src, "as_of": as_of, "kind": None} for e in ev], "intervals": [], "limits": list(limits)},
            "answer": {"conclusion": {"text": concl, "layer": "L1", "tag": tag},
                       "blocks": [{"id": "facts", "title": "계산한 값", "lines": [{"layer": "L1", "block": "facts", "tag": tag, "text": e, "source": src, "as_of": as_of, "kind": None} for e in ev]},
                                  {"id": "analysis", "title": "읽는 법과 주의", "lines": [{"layer": "L5", "block": "analysis", "tag": "주의", "text": x, "source": None, "as_of": None, "kind": None} for x in limits]}],
                       "views": [], "default_views": 0, "value_question": False, "footer": [{"source": src, "as_of": as_of, "next": "매달"}], "freshness": [], "requests": [], "methods": []},
            "suggestions": [], "downloads": [], "sec": round(time.perf_counter() - t0, 3)}


# 비(雨)를 뜻하는 말만 잡는다. '비교'·'비중'·'눈에 띄게'를 비로 읽던 결함(최종 평가 2026-11-14) 수정
RAIN_WORD = r"(비\s*(가|오|올|와|내리|온|많)|빗|우천|강수|강우|장마|폭우)"  # 눈은 비가 아니다: 눈 온 날은 따로 안내한다(SNOW_Q, 2026-11-15)
RAIN_RANK = re.compile(RAIN_WORD + r".*(가장|제일|어디|어느\s*동네|순위|많이\s*줄|덜\s*줄)")


def _rain_rank(question, t, t0):
    """'비 오는 날 가장 많이 줄어드는 동네'(평가 2026-11-14 A4): 동네별 비 효과 검정 결과(방문 기준)로 43곳 순위."""
    if t.get("space") or not RAIN_RANK.search(question or ""):
        return None
    import deep
    import v3
    f = next((p for p in (v3.ROOT / "data" / "tables" / "rain_test.json", v3.ROOT / "data" / "interim" / "gates" / "rain_test.json") if p.exists()), None)
    if not f:
        return None
    rows = json.loads(f.read_text(encoding="utf-8"))["per_dong"]
    less = bool(re.search(r"덜|늘|잘\s*되|영향\s*(이\s*)?(적|작)", question or ""))
    rows = sorted(rows, key=lambda r: r["effect_pct"], reverse=less)
    word = "덜 줄어드는" if less else "많이 줄어드는"
    top = ", ".join(f"{i}위 {r['dong']}({r['effect_pct']:+.1f}%)" for i, r in enumerate(rows[:3], 1))
    concl = f"비 오는 날 하루 방문이 가장 {word} 동네는 {top}{layers._cop(top)}."
    asked = "버스 이용" if "버스" in (question or "") else "카드 매출" if re.search(r"매출|장사|팔", question or "") else None
    if asked:  # 물은 지표와 답한 지표가 다르면 결론에 먼저 밝힌다(미처리 결함 D4)
        concl = f"{asked}의 동네별 비 효과는 계산하지 않아 하루 방문 기준으로 답해요. " + concl
    ev = [f"{r['dong']}: 비 오는 날 방문 {r['effect_pct']:+.1f}%(95% 구간 {r['lo95']:+.1f}~{r['hi95']:+.1f}%){'' if r['diff_sig'] else ', 0과 구분되지 않음'}" for r in rows[:8]]
    n_sig = sum(bool(r["diff_sig"]) for r in rows)
    limits = [f"동네별 비 효과는 하루 방문(유동인구 지수) 기준이에요. 카드 매출의 동네별 비 효과는 계산하지 않아요.",
              f"43곳 중 {n_sig}곳만 0과 구분되는 차이가 있었어요. 구간이 겹치는 동네끼리는 순위 차이를 단정할 수 없어요."]
    return _plain_answer(question, t, concl, ev, limits, "비 오는 날 방문 변화 순위", "유동인구(제주데이터허브 583)·기상(579·ASOS) 가설 검정", "2023-11~2026-08", t0, "비 효과 순위(코드)")


SALES_CHG = re.compile(r"(매출|카드|소비|장사)\S*\s*.*(급증|급감|늘|줄|떨어|올랐|오른|뛰|증가|감소|하락|상승|치솟|추락)")
SALES_UP = re.compile(r"급증|늘|올랐|오른|뛰|증가|상승|치솟")


def _sales_change_rank(question, t, t0):
    """'매출이 급증·급감한 동네'(미처리 결함 D1, 2026-11-14): 이례 변화 경로는 음식점 폐업 수만 다뤄 매출을 물으면 폐업으로 답했다.
    카드 매출(관광공사, 업종 대분류)로 최근 12개월과 그 전 12개월을 견준 증감률 순위를 낸다."""
    if t.get("space") or not SALES_CHG.search(question or "") or not re.search(r"동네|곳|어디|지역", question or ""):
        return None
    import techniques as TQ
    d = TQ._T()["card_month"]
    b = TQ._biz(t.get("target"))
    d = d[d.biz == b] if b else d
    ms = sorted(d.ym.unique())
    if len(ms) < 24:
        return None
    cur, prev = ms[-12:], ms[-24:-12]
    d = d[d.ym.isin(cur + prev)]  # 비교 기간을 최근 24개월로 제한한다
    g = d.groupby(["dong", d.ym.isin(cur)]).amt.sum().unstack()
    g = g[(g.get(False, 0) > 0)]
    chg = ((g[True] / g[False] - 1) * 100).dropna()
    up = bool(SALES_UP.search(question or ""))
    chg = chg.sort_values(ascending=not up)
    word = "많이 늘어난" if up else "많이 줄어든"
    top = ", ".join(f"{i}위 {k}({v:+.1f}%)" for i, (k, v) in enumerate(chg.head(3).items(), 1))
    who = f"{b} " if b else ""
    concl = f"최근 12개월({cur[0]}~{cur[-1]}) {who}카드 매출이 그 전 12개월보다 가장 {word} 동네는 {top}{layers._cop(top)}."
    ev = [f"{k}: {v:+.1f}%" for k, v in chg.head(8).items()] + [f"43곳 중간값 {chg.median():+.1f}%"]
    limits = ["카드 매출은 제주관광공사 자료(업종 대분류)예요. 카페 같은 세부 업종만의 값이 아니에요."] if t.get("target") and t.get("target") not in ("음식점",) else []
    limits += ["이 순위는 1년 단위 증감률이에요. 평소 범위를 벗어난 '이례 변화' 판정(경보)은 음식점 폐업 수로만 해요."]
    return _plain_answer(question, t, concl, ev, limits, "매출 증감 순위", "제주관광공사 카드 소비", cur[-1], t0, "매출 증감 순위(코드)")


def _extreme_month(question, t, t0):
    """'가장 많은·적은 달'(평가 2026-11-14 A2): 한 동네의 월별 카드 매출 또는 방문에서 최댓값·최솟값 달과, 같은 달끼리 평균한 계절 순위."""
    if not MONTH_EXT.search(question or "") or len(t.get("space") or []) > 1:
        return None
    import techniques as TQ
    dong = (t.get("space") or [None])[0]
    metric = "visit" if re.search(r"방문|유동|사람|인구", question or "") else "sales"
    s = TQ.monthly(metric, dong, t.get("target")).dropna()
    s = s[s > 0]
    if len(s) < 12:
        return None
    low = bool(re.search(r"적|낮|안\s*되|안\s*팔|한산|최저", question or ""))
    last = s.iloc[-24:]
    pick = last.idxmin() if low else last.idxmax()
    cal = s.groupby(s.index.str[5:7]).mean()
    cm = cal.idxmin() if low else cal.idxmax()
    name = TQ.METRIC[metric][0]
    who = f"{dong or '제주 전체'} {(t.get('target') + ' ') if t.get('target') and metric == 'sales' else ''}{name}"
    word = "적은" if low else "많은"
    concl = f"{layers._josa(who, '이', '가')} 가장 {word} 달은 최근 {len(last)}개월 중 {pick}({TQ.fmt(last[pick], metric)})이고, 해마다 같은 달끼리 평균하면 {int(cm)}월이 가장 {word}요."
    concl = concl.replace("많은요", "많아요").replace("적은요", "적어요")
    ev = [f"{m}: {TQ.fmt(v, metric)}" for m, v in (last.nsmallest(3) if low else last.nlargest(3)).items()] + \
         [f"같은 달끼리 평균({s.index[0]}~{s.index[-1]}): " + ", ".join(f"{int(k)}월 {TQ.fmt(v, metric)}" for k, v in (cal.nsmallest(3) if low else cal.nlargest(3)).items())]
    limits = (["카드 매출은 업종 대분류 단위예요."] if metric == "sales" and t.get("target") else []) + ([REASON_NOTE] if REASON_Q.search(question or "") else [])
    src = TQ.SRC[metric][0]
    return _plain_answer(question, t, concl, ev, limits, f"{name} 월별 비교", src, s.index[-1], t0, "가장 많은·적은 달(코드)",
                         notes=[REASON_NOTE] if REASON_Q.search(question or "") else [])


OUTSIDE_Q = re.compile(r"서울|부산|대구(?!탕|찜|뽈|국|요리|매운탕|전|살|회)|인천|광주광역|대전|울산|세종시|경기도|강원|충청|충북|충남|전라|전북|전남|경상|경북|경남|강남역|해운대|홍대|명동|여의도|판교")
OUTSIDE_MSG = "제주 43개 읍면동 자료만 있어서 제주 밖 지역은 답할 수 없어요. 제주의 동네로 물어 주세요."
MATJIP_Q = re.compile(r"맛집|맛있|맛\s*좋|후기|리뷰|평점|(가게|식당|카페|집)\S*\s*추천")
MATJIP_MSG = "맛·후기·평점 자료가 없어 맛집을 고르거나 가게를 추천할 수 없어요. 대신 그 지역 음식점 수, 카드 매출, 생존율을 볼 수 있어요."
RECO_Q = re.compile(r"(업종|창업|아이템|뭐\s*하|무엇을\s*하)\S*\s*.*추천|추천\s*(해|좀)?\s*줘")
RECO_MSG = "이 서비스는 어떤 업종을 할지 추천하거나 정하지 않아요(판단은 도민이 해요). 대신 업종별 가게 수·카드 매출·생존율을 견주어 판단 재료를 보여 드려요."
CITY_Q = re.compile(r"제주시|서귀포시|서귀포\s*(쪽|지역|시내)|제주\s*시내")
SEOGWIPO = ["대정읍", "남원읍", "성산읍", "안덕면", "표선면", "송산동", "정방동", "중앙동", "천지동", "효돈동", "영천동", "동홍동", "서홍동",
            "대륜동", "대천동", "중문동", "예래동"]  # 서귀포시 17곳(12동·3읍·2면)
CITY_MSG = "제주시·서귀포시처럼 시 단위로 합친 값은 계산하지 않아요(자료가 동네 단위예요). 동네를 하나 고르거나, '제주 전체'로 물어 주세요."
STOP_Q = re.compile(r"정류소|정류장")
STOP_NOTE = "정류소별 자료는 제출본에 없어 동네 전체 값으로 답했어요. 센터 PC에서 '버스 정류소별 이용 현황'(3-04)을 넣으면 정류소·시간대별로 볼 수 있어요."


def _result_dongs(t, run):
    """답에서 나온 동네 목록(구조값). 비슷한 동네(T9)는 이웃 목록, 이례 변화(T15)는 z가 큰 순서. 없으면 빈 목록."""
    out = []
    for v in (run.get("store") or {}).values():
        if not isinstance(v, dict):
            continue
        if v.get("neighbors"):
            src = (t.get("space") or [None])[0]
            out = list(v["neighbors"].get(src) or next(iter(v["neighbors"].values()), []))
        elif isinstance(v.get("anomaly"), list):
            out = [a["dong"] for a in sorted(v["anomaly"], key=lambda a: -abs(a.get("z") or 0)) if a.get("dong")]
    return [d for d in out if d in Q.DONGS]


def _near_suggestions(question, t):
    """범위 밖 답의 추천 질문(평가 2026-11-14 A7): 질문에서 찾은 동네(또는 지역 이름의 후보 동네)로 만든다. 없으면 대표 질문."""
    dongs = list(t.get("space") or [])
    if not dongs:
        found, amb = qparse.find_places(question or "")
        dongs = found or [d for c in amb.values() for d in c][:2]
    if not dongs and re.search(r"서귀포", question or ""):  # 시 이름만 있으면 그 시의 중심 동네로(서귀포시 17곳 중)
        dongs = [d for d in ("동홍동", "중앙동") if d in Q.DONGS]
    elif not dongs and re.search(r"제주시", question or ""):
        dongs = [d for d in ("연동", "이도2동") if d in Q.DONGS]
    if not dongs:
        return [{"text": x["text"], "slots": x["slots"]} for x in G.representative()[:3]]
    tgt = t.get("target") if t.get("target") in G.TOPIC["stores"]["options"].get("target", []) else None
    out = []
    for d in dongs[:2]:  # 동네 하나면 진단·가게 수·방문, 둘이면 앞의 셋
        for sl in ({"topic": "diagnose", "space": [d]}, {"topic": "stores", "space": [d], **({"target": tgt} if tgt else {"target": "음식점"})}, {"topic": "visit", "space": [d]}):
            if not G.missing(sl):
                out.append({"text": G.sentence(sl), "slots": sl})
    return out[:3] or [{"text": x["text"], "slots": x["slots"]} for x in G.representative()[:3]]


def _center_bus(question, t, env, t0):
    """센터 3-04 버스 CSV를 넣은 상태의 버스 질문(2026-11-14, 평가 감점 '센터 자료 직접 활용'): 넣은 자료로 동네 하루 평균 이용과
    순위, 시간대가 있으면 붐비는 시간대를 계산한다. 버스 질문이 아니면 None."""
    import center_csv
    did = (env or {}).get("center_bus")
    if not did or "버스" not in (question or ""):
        return None
    meta, d = center_csv.get(did), center_csv.table(did)
    last = d["ym"].max()
    cur = d[d["ym"] == last]
    daily = cur.groupby("dong").agg(n=("n", "sum"), days=("days", "first"))
    daily = (daily["n"] / daily["days"]).sort_values(ascending=False)
    dong = (t.get("space") or [None])[0]
    src = meta["label"]
    ev = []
    if dong and dong in daily.index:
        rank = list(daily.index).index(dong) + 1
        concl = f"{last} {dong} 버스 승차는 하루 평균 {daily[dong]:,.0f}명이에요(넣은 센터 자료 {len(daily)}개 동네 중 {rank}위)."
        if meta.get("hours") and TIME_WORDS.search(question or ""):
            h = cur[cur["dong"] == dong].groupby("hour")["n"].sum()
            share = (h / h.sum() * 100).sort_values(ascending=False)
            top = ", ".join(f"{k}({v:.1f}%)" for k, v in share.head(3).items())
            concl = f"{last} {dong} 버스 승차가 많은 시간대는 {top}{layers._cop(top)}."
            ev = [{"text": f"{k}: 하루 평균 {h[k] / cur['days'].iloc[0]:,.0f}명({v:.1f}%)", "dataset": src, "as_of": last} for k, v in share.items()]
        if not meta.get("hours") and TIME_WORDS.search(question or ""):
            concl += " 넣은 자료에 시간대 칸이 없어 하루 평균만 보여 드려요(3-04를 시간대가 들어가게 받아 주세요)."
        ev = [{"text": f"{dong} 하루 평균 승차 {daily[dong]:,.0f}명, {len(daily)}개 동네 중 {rank}위", "dataset": src, "as_of": last}] + ev
    elif dong:
        return _blocked(question, t, f"넣은 센터 자료에 {dong} 정류소가 없어요. 센터 조회 화면에서 {dong} 정류소가 들어가게 다시 받아 주세요.", [])
    else:
        top = ", ".join(f"{i}위 {k}({v:,.0f}명)" for i, (k, v) in enumerate(daily.head(3).items(), 1))
        concl = f"{last} 하루 평균 버스 승차 순위는 {top}{layers._cop(top)}(넣은 센터 자료 기준)."
        ev = [{"text": f"{k}: 하루 평균 {v:,.0f}명", "dataset": src, "as_of": last} for k, v in daily.head(10).items()]
    limits = [f"넣은 파일({meta['file']})로 계산했어요. 정류소 이름으로 동네를 이어서, 같은 이름이 떨어진 곳에 있으면 구분하지 못해요."] + \
             ([f"동네를 찾지 못한 정류소 {len(meta['unmapped_bdong'])}곳은 뺐어요."] if meta.get("unmapped_bdong") else [])
    return {"question": question, "status": "성공", "tuple": t, "interpret": {"path": "센터 자료(버스)", "card": None},
            "understood": {"text": f"이렇게 이해했어요: {dong or '제주'} 버스 이용 — 넣은 센터 자료({src})로 계산", "by": "센터 자료", "assumed": False,
                           "slots": {}, "notes": [], "check": []},
            "card": {"conclusion": concl, "evidence": [{**e, "tag": "센터 자료", "layer": "L1", "kind": None} for e in ev], "intervals": [], "limits": limits},
            "answer": {"conclusion": {"text": concl, "layer": "L1", "tag": "센터 자료로 계산"},
                       "blocks": [{"id": "facts", "title": "센터 자료로 계산한 값", "lines": [{"layer": "L1", "block": "facts", "tag": "센터 자료", "text": e["text"], "source": src, "as_of": last, "kind": None} for e in ev]},
                                  {"id": "analysis", "title": "읽는 법과 주의", "lines": [{"layer": "L5", "block": "analysis", "tag": "주의", "text": x, "source": None, "as_of": None, "kind": None} for x in limits]}],
                       "views": [], "default_views": 0, "value_question": False, "footer": [{"source": src, "as_of": last, "next": "센터에서 다시 조회"}],
                       "freshness": [], "requests": [], "methods": []},
            "suggestions": [], "downloads": [], "sec": round(time.perf_counter() - t0, 3)}


def _unsupported(question, t, env):
    """질문에 지금 자료로 답할 수 없는 축이 있으면 다른 지표로 바꿔 답하지 않는다(028 대조).
    v3(2026-11-11): 매출과 상권의 시간대는 제주관광공사 카드 자료로 답하므로 막지 않는다. 버스의 시간대만 센터 전용으로 남는다."""
    d = (t.get("space") or [])[:1]
    if t.get("type") == "T8" and "버스" in (question or ""):  # v3: 버스 예상(R2) 제외(문서 18)
        return _blocked(question, t, "버스 이용 예상은 하지 않아요. 상권 분석 범위 밖이고, 예측 모델이 단순 기준보다 정확하지 않았어요.", [{"topic": "visit", "space": d}] if d else [])
    if TIME_WORDS.search(question or "") and "버스" in (question or "") and not (env or {}).get("center_db") and not (env or {}).get("center_bus"):
        alts = [{"topic": "visit", "space": d}] if d else []
        return _blocked(question, t, "버스의 시간대별 이용은 빅데이터센터 PC의 센터 자료로만 볼 수 있어요. 센터 PC에서 '버스 정류소별 이용 현황'(3-04)을 조회해 CSV로 받아 '센터 자료 넣기'로 넣으면 시간대별로 계산해 드려요.", alts)
    return None


def _dong_only(question, t):
    """동네 이름만 입력한 질문인가('노형동', '노형동 어때?')."""
    if not t.get("space"):
        return False
    rest = question
    for n in sorted({*Q.DONGS, *Q.DONG_ALIAS, *qparse.PLACES}, key=len, reverse=True):
        if n in rest:
            rest = rest.replace(n, " ")
    return ONLY_DONG_REST.sub("", rest) == ""


def _exception(question, t):
    """M1이 되묻기로 본 질문 가운데 추정할 수 없는 경우를 고른다. 추정할 수 있으면 None."""
    preset = G.to_slots(t)
    amb = qparse.parse(question).get("_amb") or {}
    if amb and not t.get("space"):
        name, cands = next(iter(amb.items()))
        return _choose(question, t, preset, f"'{name}'{'이' if 0 <= ord(name[-1]) - 0xAC00 <= 11171 and (ord(name[-1]) - 0xAC00) % 28 else '가'} 여러 동네로 읽혀요. 어느 동네인지 골라 주세요.", "space", list(cands))
    if not preset.get("topic"):
        return _choose(question, t, preset, "무엇을 알고 싶은지 찾지 못했어요. 궁금한 것을 골라 주세요.", "topic")
    miss = G.missing(preset)
    if "space" in miss:
        msg = ("비교할 동네를 하나 더 골라 주세요." if preset["topic"] == "compare" and preset.get("space")
               else MY_DONG_MSG if MY_DONG.search(question or "") else "질문에서 동네를 찾지 못했어요. 동네를 골라 주세요.")
        return _choose(question, t, preset, msg, "space")
    if miss:
        return _choose(question, t, preset, G.missing_message(preset, miss[0]), miss[0])
    return None


def _to_check(question, it):
    """검수·재실행 라인 3단계(사람 확인): LLM이 풀지 못한 오류 노트를 도민이 읽을 말로 바꾼다.
    답할지 불일치는 LLM이 바꾸지 않으므로 늘 남기고, 종류 불일치는 계획 선택 Agent가 보지 않았을 때만 남긴다."""
    import plan_agent
    pa = it.get("plan_agent")
    out = []
    for n in plan_agent.notes(it, question):
        if n["field"] == "expect":
            out.append({"field": "expect", "text": "동네·업종을 정확히 읽었는지 확인해 주세요. 다르면 [조건 바꾸기]로 고쳐 주세요."})
        elif n["field"] == "type" and not pa and it.get("rule_type") in plan_agent.CHOICES:
            out.append({"field": "type", "text": f"질문을 '{plan_agent.ko(it['tuple']['type'])}' 또는 '{plan_agent.ko(it['rule_type'])}'(으)로 읽을 수 있어요. "
                                                 "원하는 쪽이 아니면 [조건 바꾸기]로 고쳐 주세요."})
    return list({x["field"]: x for x in out}.values())


def _escalate(question, it, t0, why):
    """일반 경로가 처리하지 못한 질문을 Agent(expert.ask, mode=escalate)에게 넘긴다. Agent가 실패하면 None(일반 경로 결과를 그대로 쓴다)."""
    import expert
    ag = expert.ask(question, mode="escalate")
    if ag.get("status") != "성공":
        return None
    meta = {k: it.get(k) for k in ("path", "confidence", "card", "sec", "plan_agent")}
    return {"question": question, "status": "Agent", "tuple": it["tuple"], "interpret": meta, "agent": ag, "escalated": why,
            "card": {"conclusion": (ag.get("lines") or [""])[0], "evidence": [], "intervals": [], "limits": [], "next_questions": []},
            "sec": round(time.perf_counter() - t0, 3)}


RULE_FIX = True
RANK_LOW = re.compile(r"(가장|제일|덜)\s*(적|낮|작)|최하위|꼴찌|(적|낮|작)은\s*(동네|곳|지역|데)|안\s*되는\s*(동네|곳|지역|데)")
# 동네를 말하지 않고 '높은·낮은·많은 동네', '어디가 제일 잘 돼'처럼 물으면 순위 질문이다(2026-11-15 최종 평가 결함: 단일 조회 T1로 읽음)
RANK_ADJ = re.compile(r"(높|낮|많|적|큰|작|잘\s*되|안\s*되)(은|는)\s*(동네|곳|지역|데)|어디(가|서|에서|가\s*더)?\s*(가장|제일|젤|더|잘)|(가장|제일)\s*잘\s*(돼|되)")
DATA_Q = re.compile(r"(자료|데이터)\S{0,2}\s*(뭐|무엇|어떤|있)")  # '버스 자료 뭐 있어?'는 자료 찾기(T11)
SNOW_Q = re.compile(r"눈\s*(이\s*)?(오|올|와|내리|온|많|쌓)|폭설|대설|적설")
SNOW_NOTE = "눈 온 날을 따로 나눈 자료는 없어요(날씨 자료는 비 온 날만 나눠요). 위 답은 날씨 조건 없이 본 값이에요."
PRICE_Q = re.compile(r"비싼|비싸|저렴|싼\s*(곳|식당|가게|집|데)|가격")
PRICE_NOTE = "메뉴 가격 자료는 없어요. 카드 결제 1건당 금액으로 봤어요."
POP_Q = re.compile(r"(?<!유동)(?<!방문)인구(?!\s*(구성|연령|나이))|주민\s*수|몇\s*명\s*(이\s*)?(살|사)")
POP_NOTE = "동네 인구 수(주민등록 인구)는 자료에 없어요. 거주 인구의 연령 구성으로 답했어요."
TOUR_MANY = re.compile(r"관광객\S{0,2}\s*(많|적|몰|붐|순위)")
HOUR_Q = re.compile(r"(오전|오후|새벽|아침|저녁|밤|낮)\s*\d{1,2}\s*시|\d{1,2}\s*시\s*(쯤|경|에|부터|대|께)")
HOUR_NOTE = "시간대별 사람 수는 센터 유동인구 자료를 넣어야 볼 수 있어요. 위 답은 카드 매출의 시간대 비중이에요."
RAIN_SALES_NOTE = "하루 단위 매출 자료가 없어요. 비 온 날의 방문 변화로 봤어요."
def _asked_period(q):
    """질문의 해·달. '작년'·'올해'는 오늘 날짜 기준. '3개월'·'12월까지 다음 달' 같은 말은 달로 보지 않는다."""
    import datetime
    y = datetime.date.today().year
    m = re.search(r"(20\d\d)\s*년", q)
    ay = int(m.group(1)) if m else (y - 1 if re.search(r"작년|지난\s*해|전년", q) else y if re.search(r"올해|금년|올\s*해", q) else None)
    mm = re.search(r"(?<!\d)(1[0-2]|[1-9])\s*월(?!\s*(까지|부터|이후))", q)
    am = int(mm.group(1)) if mm and not re.search(r"\d\s*개월", q) else None
    return ay, am


SALES_WORD = re.compile(r"잘\s*(돼|되|나가|팔)|장사(가|는)?\s*(잘|안)")
MULTI_NOTE = "질문에 묻는 것이 여럿일 수 있어요. 위 답은 그중 하나만 다뤘으니, 나머지는 따로 물어 주세요."


def _split(question, it, interpret, env, t0):
    """질문 나누기(app/split.py). Claude 유무와 상관없이 먼저 돈다(2026-11-14 마스터 결정: 센터 PC·Vercel 같은 구조, Claude 한도 절약).
    나누지 않은 질문만 계획 선택·(다) 넘김 판정(Claude)이 맡는다. 나누지 않으면 None."""
    import split
    if not split.enabled():
        return None
    ag = split.answer(question, interpret, dict(env or {}, _no_split=True))
    if not ag or ag.get("status") != "성공":
        return None
    meta = {k: it.get(k) for k in ("path", "confidence", "card", "sec")}
    return {"question": question, "status": "Agent", "tuple": it["tuple"], "interpret": meta, "agent": ag, "escalated": "질문을 나눠 조각마다 답함",
            "card": {"conclusion": (ag.get("lines") or [""])[0], "evidence": [], "intervals": [], "limits": [], "next_questions": []},
            "sec": round(time.perf_counter() - t0, 3)}


def _route_check(question, it, status, t0, said=None):
    """(다) 넘김 판정: 일반 경로가 정한 처리(계산해 답함·고르게 하기·범위 밖)로 질문이 다 다뤄지는지 Claude가 판정하고, 아니면 Agent에게 넘긴다.
    로컬 모델은 판정하지 않는다(200문항 비교에서 해로움). 넘기지 않으면 None."""
    import plan_agent
    esc, rc = plan_agent.route_check(question, it, status, said=said)
    if rc:
        it["route_check"] = rc
    if not esc:
        return None
    ag = _escalate(question, it, t0, "넘김 판정 Agent가 일반 경로로 다 답할 수 없다고 판단")
    if ag:
        ag["interpret"]["route_check"] = rc
    return ag


def respond(question=None, env=None, llm_on=True, interpret=None, slots=None, path=None, **review_kw):
    t0 = time.perf_counter()
    assumed, notes, typed = False, [], question if not slots or path else None
    if not slots and question:  # 서비스가 만든 문장(추천 질문·주제 문장)을 그대로 적으면 해석하지 않고 그 버튼 값으로 답한다(문서 20 A1)
        ms = G.match_sentence(question)
        if ms and not G.missing(ms):
            return respond(question, env, llm_on, slots=ms, path="제안 문장 일치", **review_kw)
    value_q = bool(slots and slots.get("topic") == "diagnose")
    if slots:  # ②③④ 버튼 값: 해석하지 않는다
        miss = G.missing(slots)
        if miss:
            return _choose(question, None, slots, G.missing_message(slots, miss[0]), miss[0], sec=time.perf_counter() - t0)
        t = G.to_tuple(slots)
        question = question or G.sentence(slots)
        if t.get("detail") and not typed:  # 버튼 값에 세부 업종이 실려 온 경우(다시 계산·주소)에도 세는 기준을 알린다
            typed = question
        it = {"tuple": t, "card": qparse.card(t), "path": path or "버튼 선택", "confidence": None, "sec": 0.0}
        un = _unsupported(question, t, env) if t["type"] == "T13" else None
        if un:
            return dict(un, sec=round(time.perf_counter() - t0, 3))
        agent_ok = False  # 버튼 값은 넘기지 않는다
    else:  # ① 자유 입력
        agent_ok = llm_on and bool((env or {}).get("agent_ok"))
        if interpret is None:
            import m1
            interpret = m1.M1().interpret
        it = interpret(question)
        if not (env or {}).get("_no_split"):  # 질문 나누기(049): 하위 질문이 여럿이면 코드가 나눠 조각마다 답한다(Claude 유무 무관)
            sp = _split(question, it, interpret, env, t0)
            if sp:
                return sp
        if llm_on:  # 안 C(문서 26): 해석이 애매하면 LLM이 정해진 질문 종류 중에서 계획을 고른다
            import plan_agent
            it = plan_agent.adjust(question, it)
        t = it["tuple"]
        # 질문 보정 규칙(2026-11-15 P1: 기간·대체 지표·눈·비·자료 찾기·순위). 질문 담당 Agent가 고른 해석으로 다시 계산할 때(env _agent_tuple)는
        # 규칙이 덮어쓰지 않는다. RULE_FIX는 비교 측정(tools/eval/general_answer.py --no-rule-fix)에서만 끈다.
        if RULE_FIX and not (env or {}).get("_agent_tuple"):
            q_ = question or ""
            if not t.get("metric") and SALES_WORD.search(q_):  # '잘 돼?'는 매출로 답한다(점포 수로 답하던 결함, 2026-11-15)
                t = dict(t, metric=["매출"])
                it = dict(it, tuple=t)
            # 지표·조건을 못 찾았거나 다른 지표로 답하는 질문(2026-11-15 최종 평가 결함): 가까운 지표로 바꾸고 바꾼 사실을 알린다
            if DATA_Q.search(q_) and not t.get("space") and t.get("type") != "T11":
                t = dict(t, type="T11", metric=["자료목록"], expect="답함")
            if PRICE_Q.search(q_) and "건당금액" not in (t.get("metric") or []) and set(t.get("metric") or []) <= {"점포수"}:
                t = dict(t, metric=["건당금액"])
                notes.append(PRICE_NOTE)
            if POP_Q.search(q_) and set(t.get("metric") or []) <= {"점포수"}:
                t = dict(t, metric=["거주연령구성"], expect="답함" if t.get("space") else t.get("expect"))
                notes.append(POP_NOTE)
            if TOUR_MANY.search(q_) and set(t.get("metric") or []) <= {"점포수"}:
                t = dict(t, metric=["관광객비중"])
                notes.append(TOUR_NOTE)
            if HOUR_Q.search(q_) and set(t.get("metric") or []) <= {"점포수", "일평균방문"}:
                t = dict(t, type="T13", metric=["시간대방문"], form=Q.DEFAULT_FORM["T13"])
            hm = re.search(r"(오후|저녁|밤)?\s*(\d{1,2})\s*시", q_) if HOUR_Q.search(q_) else None
            if hm:  # 물은 시각의 값도 답한다('오후 3시' → 15시)
                h = int(hm.group(2)) % 24
                t = dict(t, ask_hour=h + 12 if hm.group(1) and h < 12 else h)
            ay, am = _asked_period(q_)
            rm = re.search(r"(최근|지난)\s*(\d{1,2})\s*개월", q_)
            if rm and 1 <= int(rm.group(2)) <= 24:  # '최근 3개월'은 그 기간 합계(평균)로(2026-11-15)
                t = dict(t, ask_recent=int(rm.group(2)))
            if ay or am:  # 질문에 적힌 기간(문서 계산은 layers._asked_ym)
                t = dict(t, ask_year=ay, ask_month=am)
                if am and t.get("type") == "T6" and not re.search(r"여름|겨울|봄|가을|계절|성수기|비수기|날씨|" + RAIN_WORD, q_):
                    t = dict(t, type="T1", cond=[], form=Q.DEFAULT_FORM["T1"])  # '7월 연동 방문객'은 계절 효과가 아니라 7월 값
            if SNOW_Q.search(q_):
                t = dict(t, cond=[c for c in (t.get("cond") or []) if c != "비"])
                notes.append(SNOW_NOTE)
            elif re.search(RAIN_WORD, q_) and t.get("type") == "T1" and t.get("space") and not t.get("cond"):
                if "매출" in (t.get("metric") or []):
                    notes.append(RAIN_SALES_NOTE)
                t = dict(t, type="T6", cond=["비"], metric=["일평균방문"], form=Q.DEFAULT_FORM["T6"])
            it = dict(it, tuple=t)
            if len(t.get("metric") or []) > 1:  # 질문에 그대로 적힌 지표를 앞에(폐업률을 물었는데 폐업 수 순위로 답하던 결함)
                t = dict(t, metric=sorted(t["metric"], key=lambda m: m not in q_))
                it = dict(it, tuple=t)
            if t.get("type") == "T1" and not t.get("space") and RANK_ADJ.search(question or ""):
                t = dict(t, type="T3", expect="답함")
                it = dict(it, tuple=t)
        if t.get("type") == "T3" and RANK_LOW.search(question or ""):  # 순위 방향(작은 순서)
            t = dict(t, order="asc")
            it = dict(it, tuple=t)
        meta = {k: it.get(k) for k in ("path", "confidence", "card", "sec", "plan_agent")}

        def stop(r):  # 일반 경로가 계산 전에 끝내는 출구(고르게 하기·범위 밖). (다) 넘김 판정도 여기서 한다
            r = dict(r, interpret=meta, sec=round(time.perf_counter() - t0, 3))
            return (_route_check(question, it, r["status"], t0, (r.get("choose") or {}).get("message") or (r.get("card") or {}).get("conclusion")) or r) if agent_ok else r
        od = qparse.DETAIL.get(t.get("detail"), {}).get("word")
        if od in Q.TARGETS_OUT and (qparse.CARD_METRICS | qparse.FOOD_ONLY) & set(t["metric"]):
            # 미용실·약국·학원·병원·부동산중개는 가게 수만 답한다(문서 20 7.5절 3번). 카드 매출·개업·폐업은 다른 업종·동네 전체 값으로 바꿔 답하지 않고 이유를 알린다.
            # 방문·버스처럼 업종 구분이 없는 값('병원 가는 버스')은 막지 않는다.
            d = t["space"][:1]
            why = OUT_NO_CARD if qparse.CARD_METRICS & set(t["metric"]) else OUT_NO_OPEN
            return stop(_blocked(question, dict(t, type="T12", expect="범위밖"), (OUT_ONLY_COUNT + why).format(w=od, we=_josa(od)),
                                 [{"topic": "stores", "space": d, "detail": od}] if d else []))
        if OUTSIDE_Q.search(question or "") and not t.get("space"):  # 제주 밖 지역(미처리 결함 D2, 2026-11-14)
            return stop(_blocked(question, dict(t, type="T12", expect="범위밖"), OUTSIDE_MSG, []))
        if MATJIP_Q.search(question or "") or RECO_Q.search(question or ""):  # 맛집·추천은 막고, 이유와 주변 동네 질문을 보여 준다(평가 2026-11-14 A7)
            msg = MATJIP_MSG if MATJIP_Q.search(question or "") else RECO_MSG  # 업종 추천은 '추천하지 않는다' 원칙으로 안내(최종 평가)
            sl = [x["slots"] for x in _near_suggestions(question, t)]
            if msg is RECO_MSG:
                sl = [{"topic": "bizcompare", "space": (t.get("space") or ["노형동"])[:1]}] + sl
            return stop(_blocked(question, dict(t, type="T12", expect="범위밖"), msg, [x for x in sl if not G.missing(x)][:3]))
        cb = _center_bus(question, t, env, t0) or _rain_rank(question, t, t0) or _sales_change_rank(question, t, t0) or _extreme_month(question, t, t0)
        if cb:
            return dict(cb, interpret=meta)
        if CITY_Q.search(question or "") and not t.get("space") and t.get("type") in ("T3", "T14", "T15"):
            # '서귀포시 동네 중 ~가 가장 많은 곳'은 그 시의 동네로 범위를 좁힌다(제주 전체 순위로 답하던 결함, 최종 평가 2026-11-14)
            city = [d for d in SEOGWIPO if d in Q.DONGS] if re.search(r"서귀포", question or "") else [d for d in Q.DONGS if d not in SEOGWIPO]
            t = dict(t, space=city)
            it = dict(it, tuple=t, card=qparse.card(t))
            notes.append(f"{'서귀포시' if re.search(r'서귀포', question or '') else '제주시'} {len(city)}개 동네 안에서 견줬어요.")
        elif CITY_Q.search(question or "") and not t.get("space") and (t.get("expect") == "되묻기" or t.get("type") in qparse.NEED_DONG):
            ps = G.to_slots(t) if t.get("expect") != "범위밖" else {}  # 시 단위는 합치지 않는다는 것을 알리고 동네를 고르게 한다(평가 2026-11-14 A5)
            return stop(_choose(question, t, ps if ps.get("topic") else {"topic": "diagnose"}, CITY_MSG, "space"))
        if "외국인매출" in t["metric"] or (FOREIGN_Q.search(question or "") and SPEND_Q.search(question or "")):
            # 외국인 매출은 공개 자료에 제주 전체(업종·출신지역)만 있다. 전체 매출 순위로 바꿔 답하지 않고 있는 값과 받을 곳을 알린다(문서 20 A9)
            t = dict(Q.empty(), type="T5" if t["space"] else "T3", metric=["외국인매출"], space=t["space"][:1],
                     target=t.get("target") if t.get("target") in G.CARD_TARGETS else None, form=Q.DEFAULT_FORM["T5" if t["space"] else "T3"], expect="답함")
            it = dict(it, tuple=t, card=qparse.card(t))
            assumed = True
            notes.append(FOREIGN_NOTE)
        elif (len(t["space"]) == 1 and TOUR_COUNT_Q.search(question or "") and not (qparse.CARD_METRICS - {"관광객비중"}) & set(t["metric"])
              and t["type"] not in ("T6", "T8") and not t["cond"]):  # 조건 효과·예상 질문은 그대로 둔다
            # '관광객이 얼마나 와?': 방문자 수 자료가 없으므로 사는 사람 연령대로 바꿔 답하지 않고 손님 구성(카드 매출 비중)으로 답한다(문서 20 7.5절 11번, 사용자 결정 2026-11-12)
            t = dict(Q.empty(), type="T5", metric=["관광객비중"], space=t["space"][:1],
                     target=t.get("target") if t.get("target") in G.CARD_TARGETS else None, form=Q.DEFAULT_FORM["T5"], expect="답함")
            it = dict(it, tuple=t, card=qparse.card(t))
            assumed = True
            notes.append(TOUR_NOTE)
        elif len(t["space"]) == 1 and VS_Q.search(question or "") and len(qparse.find_details(question)) >= 2:
            # 한 동네 안에서 세부 업종끼리 비교: 매출은 대분류뿐이라 상가 정보 소분류의 가게 수로 견준다(문서 20 A9)
            t = dict(Q.empty(), type="T5", metric=["업종비교"], space=t["space"][:1], details=[d["word"] for d in qparse.find_details(question)],
                     form=Q.DEFAULT_FORM["T5"], expect="답함")
            it = dict(it, tuple=t, card={"text": f"이렇게 이해했어요: {t['space'][0]} · {'·'.join(t['details'])} — 점포 수 비교", "buttons": ["맞아요", "동네 바꾸기", "질문 종류 바꾸기"]})
            assumed = True
        elif not t["space"] and MY_DONG.search(question or ""):  # '우리 동네': 위치를 모른다는 것을 알리고 동네를 고르게 한다(문서 20 A9)
            ps = G.to_slots(t) if t["expect"] != "범위밖" else {}
            return stop(_choose(question, t, ps if ps.get("topic") else {"topic": "diagnose"}, MY_DONG_MSG, "space"))
        elif t["expect"] != "범위밖" and _dong_only(question, t):  # 동네 이름만 → 동네 종합 진단
            t = dict(Q.empty(), type="T10", space=t["space"][:1], form=Q.DEFAULT_FORM["T10"], expect="답함")
            it = dict(it, tuple=t, card=qparse.card(t))
            assumed = True
        elif t["space"] and layers.VALUE_WORDS.search(question or "") and len(t["space"]) == 1:
            # 가치 판단 질문(L5)은 확신도 검사보다 먼저: 판단 재료(상권 묶음 진단)로 답한다(08 문서 0절 합성안)
            t = dict(Q.empty(), type="T10", space=t["space"][:1], target=t.get("target"), form=Q.DEFAULT_FORM["T10"], expect="답함",
                     **({"detail": t["detail"]} if t.get("detail") else {}))
            it = dict(it, tuple=t, card=qparse.card(t))
            assumed, value_q = True, True
        elif t["expect"] != "범위밖":
            un = _unsupported(question, t, env)
            if un:
                return stop(un)
            if t["expect"] == "되묻기":
                ex = _exception(question, t)
                if ex:
                    return stop(ex)
            conf = it.get("confidence")
            agree = it.get("rule_type") == t["type"]  # 분류기와 사전 해석기가 같은 유형: 블라인드 4묶음에서 확신도 0.5 미만이어도 29/30 정답(불일치 9/27), 2026-11-11 측정
            if conf is not None and conf < LOW_CONF and not agree:  # 추정할 근거가 약하면 답하지 않고 고르게 한다
                ps = G.to_slots(t)  # 확신이 낮으면 답하지 않는다(사용자 승인 규칙). 다만 읽은 뜻을 보여 주고 한 번에 확인할 수 있게 한다(문서 20 A1)
                msg = (f"질문을 '{G.sentence(ps)}'로 읽었는데 확실하지 않아요. 맞으면 [이대로 답 보기]를 누르고, 아니면 궁금한 것을 다시 골라 주세요."
                       if ps.get("topic") and not G.missing(ps) else "질문을 정확히 이해하지 못했어요. 궁금한 것을 골라 주세요.")
                return stop(_choose(question, t, ps, msg, "topic"))
            if t["expect"] == "되묻기":
                t = dict(t, expect="답함")  # 추정해서 답하고 "이렇게 이해했어요"로 보여 준다
                it = dict(it, tuple=t, card=qparse.card(t))
                assumed = True
    if agent_ok and it.get("escalate"):  # 중간안: 계획 선택 Agent가 '정해진 종류 하나로 답할 수 없음'을 고름
        ag = _escalate(question, it, t0, "계획 선택 Agent가 여러 단계·종류 밖으로 판단")
        if ag:
            return ag
    rv = V.review(question, env, interpret=lambda q: it, **review_kw)
    if agent_ok and ((rv["status"] == "범위밖" and it.get("rule_type") != "T12") or (rv["status"] not in ("범위밖", "되묻기") and rv.get("run") is None)):
        # 중간안: 일반 경로로 해결되지 않으면 Agent에게 넘긴다(분류기만 범위 밖으로 본 질문, 계획·계산 실패). 규칙도 범위 밖이면 그대로 막는다
        ag = _escalate(question, it, t0, "일반 경로가 범위 밖으로 판단(규칙과 불일치)" if rv["status"] == "범위밖" else "일반 경로 계산 실패")
        if ag:
            return ag
        agent_ok = False  # 이미 넘겨 봤으면 다시 넘기지 않는다
    if agent_ok and not it.get("escalate"):  # (다) 넘김 판정(2026-11-14 마스터 결정)
        ag = _route_check(question, it, rv["status"], t0)
        if ag:
            return ag
    t = rv["tuple"]
    out = {"question": question, "status": rv["status"], "tuple": t, "interpret": {k: it.get(k) for k in ("path", "confidence", "card", "sec", "plan_agent", "route_check")}}
    if rv["status"] == "되묻기":  # 검수 단계에서 칸을 채우지 못한 경우
        ex = _exception(question, t) or _choose(question, t, G.to_slots(t), "질문을 이해하지 못했어요. 궁금한 것을 골라 주세요.", "topic")
        ex["sec"] = round(time.perf_counter() - t0, 3)
        return ex
    if rv["status"] == "범위밖" or rv.get("run") is None:  # 범위 밖은 답하지 않는다(차단)
        sug = _near_suggestions(question, t)
        concl = MATJIP_MSG if MATJIP_Q.search(question or "") else (it.get("card") or {}).get("text") or "지금 자료로는 답할 수 없는 질문이에요."
        out["card"] = {"conclusion": concl, "evidence": [], "intervals": [], "limits": [], "next_questions": [x["text"] for x in sug]}
        out["suggestions"] = sug
    else:
        if any("이용자 불러옴" in str(v.get("dataset")) for v in rv["run"]["store"].values() if isinstance(v, dict)):
            notes = [x for x in notes if x != FOREIGN_NOTE]  # 넣은 센터 파일로 동네 값을 답했으면 '제주 전체로 답해요' 안내를 뺀다
        if question and not slots and not (env or {}).get("_no_split"):
            import plan_agent
            if plan_agent.multi(question):  # 여러 단계 표지가 있는데 나누지 못하고 하나로 답한 경우 알린다(둘째 조각이 조용히 빠지던 문제, 페르소나 평가 2026-11-14)
                notes = notes + [MULTI_NOTE]
        if "시간대방문" in t.get("metric", []) and not any("이용자 불러옴" in str(v.get("dataset")) for v in rv["run"]["store"].values() if isinstance(v, dict)):
            notes = notes + [HOUR_NOTE]
        if question and REASON_Q.search(question):  # '이유·왜'는 자료로 단정할 수 없음을 알린다(평가 2026-11-14 A2)
            notes = notes + [REASON_NOTE]
        if question and STOP_Q.search(question) and not (env or {}).get("center_bus"):  # 정류소를 물었는데 동네 값으로 답한 경우(A6)
            notes = notes + [STOP_NOTE]
        out["understood"] = {"text": (it.get("card") or {}).get("text"), "by": it.get("path"), "assumed": assumed or bool(it.get("needs_confirm")),
                             "slots": slots or ({"space": t["space"]} if "외국인매출" in t["metric"] else G.to_slots(t)),
                             "notes": list(dict.fromkeys(notes + (qparse.notes(typed, t) if typed else []))),
                             "check": _to_check(question, it) if not slots else []}
        if out["understood"]["check"]:
            out["understood"]["assumed"] = True
        out["suggestions"] = G.suggestions(t)
        ev, intervals, as_of = _evidence(rv["order"], rv["run"])
        c = card(t, rv, ev, intervals)
        ans = layers.build(t, rv, ev, value_q or t.get("type") == "T10")
        rv["run"]["store"]["_display"] = {"numbers": ans.pop("numbers")}
        all_lines = ans.pop("all_lines")  # 답 카드 근거는 화면 중복 제거(결론과 같은 줄) 전의 줄 전부  # 코드가 만든 표시값(억·만 원, 배수, 순위)과 정책 상수
        c = dict(c, conclusion=ans["conclusion"]["text"],
                 evidence=[{"text": x["text"], "tag": x["tag"], "layer": x["layer"], "dataset": x.get("source"), "as_of": x.get("as_of"), "kind": x.get("kind")} for x in all_lines])
        probs = card_problems(c, rv["run"])
        if probs:  # 카드 수치가 결과와 어긋나면 검수 템플릿 문장으로 바꾼다
            c = dict(c, conclusion="수치 대조에 실패해 확인된 값만 보여 드립니다.", evidence=[{"text": x} for x in V.template_answer(rv["order"], rv["run"]).splitlines()])
        out["card"] = dict(c, number_check=probs)
        if probs:
            ans["conclusion"] = {"text": c["conclusion"], "layer": None, "tag": None}
            ans["blocks"] = [{"id": "facts", "title": layers.BLOCK_TITLE["facts"], "lines": [{"layer": "L1", "block": "facts", "tag": "검수 템플릿", "text": e["text"]} for e in c["evidence"]]}]
        if t.get("type") in ("T10", "T2"):
            ans["biz_tabs"] = G.biz_tabs(t)
        if t.get("type") == "T10" and len(t.get("space") or []) == 1:  # 문서 22 3절: 종합 진단 → 다른 동네와 비교. 후보는 비슷한 동네 5곳(R5)
            nb = next((v["neighbors"].get(t["space"][0]) for v in rv["run"]["store"].values() if isinstance(v, dict) and (v.get("neighbors") or {}).get(t["space"][0])), [])
            tgt = t.get("target") if t.get("target") in G.TOPIC["compare"]["options"]["target"] else None
            ans["compare_with"] = {"dong": t["space"][0], "target": tgt,
                                   "candidates": [{"dong": d, "slots": {k: v for k, v in {"topic": "compare", "space": [t["space"][0], d], "target": tgt}.items() if v}} for d in nb]}
            for c in ans["compare_with"]["candidates"]:
                c["text"] = G.sentence(c["slots"])
        out["answer"] = ans
        out["result_dongs"] = _result_dongs(t, rv["run"])  # 뒤 조각이 이어받을 동네 목록(질문 나누기, 평가 2026-11-14 B6)
        out["process"] = {
            "tuple": t, "type": TYPE_KO.get(t["type"]),
            "steps": [{"id": x["id"], "sub": x["sub"], "name": SUB_KO[x["sub"]], "op": x.get("op"), "metric": x.get("metric"), "recipe": x.get("recipe"),
                       "status": next((y["status"] for y in rv["run"]["log"] if y["task_id"] == x["id"]), "-")} for x in rv["order"]["tasks"]],
            "data": as_of, "explain": explain_plan(question, t, rv["order"], rv["run"], llm_on),
            "relaxed": rv["run"].get("relaxed", []), "unused": rv["run"].get("notes", []) + [f"{SUB_KO.get(x['sub'], '')}: {x.get('error')}" for x in _failed(rv["order"], rv["run"])],
            "review": rv["record"], "retries": rv["retries"]}
        out["downloads"] = downloads(rv["order"], rv["run"])
    out["sec"] = round(time.perf_counter() - t0, 3)
    return out


if __name__ == "__main__":
    off = "--no-llm" in sys.argv or llm.backend() == "rule"  # LLM_BACKEND=rule도 LLM을 끈다
    for q in [a for a in sys.argv[1:] if not a.startswith("--")]:
        r = respond(q, llm_on=not off)
        print("■", q, "|", r["status"], f"{r['sec']}초")
        if "choose" in r:
            print("  선택:", r["choose"]["message"], r["choose"]["step"], r["choose"]["candidates"], r["choose"]["preset"])
        if "understood" in r:
            print("  이해:", r["understood"]["text"], "| 추정" if r["understood"]["assumed"] else "", r["understood"]["slots"])
        if "card" in r:
            c = r["card"]
            print("  결론:", c["conclusion"])
            for e in c["evidence"][:5]:
                src = ", ".join(str(x) for x in (e.get("dataset"), e.get("as_of")) if x)  # 출처가 없으면 괄호째 생략(D7)
                print("  근거:", e["text"], f"[{src}]" if src else "")
            for x in c["intervals"]:
                print("  구간:", x)
            for x in c["limits"]:
                print("  한계:", x)
            print("  다음:", c["next_questions"], "| 수치 대조 문제:", c.get("number_check"))
        if "process" in r:
            print("  해설:", r["process"]["explain"]["text"], "|", r["process"]["explain"]["by"], r["process"]["explain"]["sec"])
            print("  내려받기:", [(d["name"], d.get("rows")) for d in r["downloads"]])
