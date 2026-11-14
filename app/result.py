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


def _unsupported(question, t, env):
    """질문에 지금 자료로 답할 수 없는 축이 있으면 다른 지표로 바꿔 답하지 않는다(028 대조).
    v3(2026-11-11): 매출과 상권의 시간대는 제주관광공사 카드 자료로 답하므로 막지 않는다. 버스의 시간대만 센터 전용으로 남는다."""
    d = (t.get("space") or [])[:1]
    if t.get("type") == "T8" and "버스" in (question or ""):  # v3: 버스 예상(R2) 제외(문서 18)
        return _blocked(question, t, "버스 이용 예상은 하지 않아요. 상권 분석 범위 밖이고, 예측 모델이 단순 기준보다 정확하지 않았어요.", [{"topic": "visit", "space": d}] if d else [])
    if TIME_WORDS.search(question or "") and "버스" in (question or "") and not (env or {}).get("center_db"):
        alts = [{"topic": "visit", "space": d}] if d else []
        return _blocked(question, t, "버스의 시간대별 이용은 빅데이터센터 PC의 센터 자료로만 볼 수 있어요.", alts)
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


RANK_LOW = re.compile(r"(가장|제일|덜)\s*(적|낮|작)|최하위|꼴찌")
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
        out["card"] = {"conclusion": (it.get("card") or {}).get("text") or "지금 자료로는 답할 수 없는 질문이에요.", "evidence": [], "intervals": [], "limits": [],
                       "next_questions": [x["text"] for x in G.representative()[:3]]}
        out["suggestions"] = [{"text": x["text"], "slots": x["slots"]} for x in G.representative()[:3]]
    else:
        if any("이용자 불러옴" in str(v.get("dataset")) for v in rv["run"]["store"].values() if isinstance(v, dict)):
            notes = [x for x in notes if x != FOREIGN_NOTE]  # 넣은 센터 파일로 동네 값을 답했으면 '제주 전체로 답해요' 안내를 뺀다
        if question and not slots and not (env or {}).get("_no_split"):
            import plan_agent
            if plan_agent.multi(question):  # 여러 단계 표지가 있는데 나누지 못하고 하나로 답한 경우 알린다(둘째 조각이 조용히 빠지던 문제, 페르소나 평가 2026-11-14)
                notes = notes + [MULTI_NOTE]
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
                print("  근거:", e["text"], f"[{e.get('dataset')}, {e.get('as_of')}]")
            for x in c["intervals"]:
                print("  구간:", x)
            for x in c["limits"]:
                print("  한계:", x)
            print("  다음:", c["next_questions"], "| 수치 대조 문제:", c.get("number_check"))
        if "process" in r:
            print("  해설:", r["process"]["explain"]["text"], "|", r["process"]["explain"]["by"], r["process"]["explain"]["sec"])
            print("  내려받기:", [(d["name"], d.get("rows")) for d in r["downloads"]])
