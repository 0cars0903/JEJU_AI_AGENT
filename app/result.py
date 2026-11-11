"""W8 결과 생성 Agent (docs/기획/05_Agent구조_v2.md 4-5절, 2026-11-11 구현).

입력: 검수(verify.review)를 거친 결과. 출력: 응답 JSON
  card     답 카드 — 결론 한 줄 → 근거 수치(자료별 기준일) → 구간 → 한계 → 다음 질문 3개. 수치 문장은 코드 템플릿이다.
  process  판단 과정 — 질문 Tuple, 고른 자료와 이유(M3-b 해설), 완화한 축, 쓰지 못한 자료와 이유, 검수 기록
  clarify  되묻기 — 의도 확인 문장과 버튼 3개(M1-b)
  downloads 집계표 CSV(반출 불가 자료는 검수에서 집계만 남김)와 차트 명세
LLM은 M1-b(되묻기 버튼 문구)와 M3-b(계획 해설 1~2문장) 두 곳만 쓴다. 숫자를 쓰면 버리고 템플릿으로 대체한다.
진입점: respond(question, env, llm_on=True)
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import qtuple as Q  # noqa: E402
import recipes  # noqa: E402
import verify as V  # noqa: E402
from agent import BANNED, DONG_NUM, UNFOUNDED, _norm, check_numbers, is_korean  # noqa: E402

UNIT_NOTE = {"지수": "유동인구는 사람 수가 아니라 지수입니다(통신 자료 추계)."}
CLAIM_KO = {"효과 있음": "차이가 있습니다", "작지만 0은 아님": "차이는 있지만 ±10% 안의 작은 차이입니다",
            "작음 확인": "차이가 ±10% 안으로 작습니다", "판단 불가": "차이를 확인하지 못했습니다"}
TYPE_KO = {"T1": "현황 조회", "T2": "동네 비교", "T3": "순위", "T4": "추세", "T5": "구성", "T6": "조건 효과", "T7": "관계", "T8": "예측",
           "T9": "비슷한 동네", "T10": "종합 진단", "T11": "자료 찾기", "T13": "시간대 패턴", "T14": "조건 탐색", "T15": "이례 변화"}
SUB_KO = {"S0": "자료 탐색", "S1": "조회", "S2": "통계·점검", "S3": "모델", "S4": "차트", "S5": "단위 맞추기", "S6": "판정"}
M3B_SYSTEM = ("너는 제주 동네 자료 안내원이다. 시스템이 고른 자료와 계산 순서를 도민에게 한두 문장으로 설명한다. "
              "규칙: 숫자를 한 글자도 쓰지 않는다. 주어진 자료 이름과 단계만 말한다. 결과나 결론을 말하지 않는다. '~했습니다'체로 쓴다.\n"
              "예시) 질문: 아라동 카페 개업 늘었어? / 고른 자료: 개업 수(음식점 인허가) / 계산 순서: 조회 → 통계·점검 → 판정 → 차트\n"
              "답: 음식점 인허가 자료에서 아라동 카페 개업 수를 연도별로 모으고, 최근 흐름이 우연인지 판정한 뒤 그래프로 정리했습니다.")
M1B_SYSTEM = ("너는 제주 동네 자료 안내원이다. 질문에 빈 칸이 있어 사용자에게 고르게 한다. "
              "주어진 후보마다 버튼 문구를 하나씩, 후보 이름을 그대로 넣어 짧게 쓴다. 숫자를 쓰지 않는다. "
              'JSON으로만 답한다: {"ask": "묻는 문장", "buttons": ["...", "...", "..."]}')
EXAMPLE_DONGS = ["노형동", "연동", "아라동"]


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
    t0 = time.perf_counter()
    try:
        out = llm.chat(None, [{"role": "system", "content": system}, {"role": "user", "content": user}], [], name="ollama", max_tokens=160)["message"].get("content", "").strip()
    except Exception as e:
        return None, f"LLM 오류 {type(e).__name__}", time.perf_counter() - t0
    return out, None, time.perf_counter() - t0


# ---------- 답 카드 ----------
def _evidence(order, res):
    ev, intervals, as_of = [], [], {}
    tasks = {t["out"]: t for t in order["tasks"]}
    for k, v in res["store"].items():
        t = tasks.get(k, {})
        if "table" in v and t.get("sub") == "S1" and len(v["table"]):
            tab = v["table"]
            c, last = _as_of(tab)
            cur = tab[tab[c] == last] if c else tab
            when = str(last)[:7] if c else "최신 단면"
            as_of[v.get("dataset")] = when
            m = t.get("metric")
            if "ageGroup" in cur:  # 연령 구성은 많은 순서만(값은 지수라 비중 계산을 따로 하지 않는다)
                for d, g in cur.groupby("dong"):
                    order_ = g.sort_values("value", ascending=False)["ageGroup"].astype(str).head(3).tolist()
                    ev.append({"metric": m, "text": f"{d} 거주 인구 많은 연령대: {', '.join(order_)}", "dataset": v.get("dataset"), "as_of": when})
                continue
            for r in cur.head(6).to_dict(orient="records"):
                ev.append({"metric": m, "dong": r.get("dong"), "value": r["value"], "unit": v.get("unit"),
                           "text": f"{r.get('dong', '')} {_label(m)} {_num(r['value'])}{'' if v.get('unit') in ('-', None) else ' ' + v['unit']}",
                           "dataset": v.get("dataset"), "as_of": when})
        if v.get("survival"):
            s = v["survival"]
            ev.append({"metric": "업종 5년생존율", "text": f"{s['group']} 5년 생존율 {_num(s['surv5_pct'])}% (표본 {s['n']:,}곳, 제주 전체)", "dataset": "780 음식점 인허가", "as_of": "개업 2015-01~2020-08 코호트"})
            intervals.append(f"{s['group']} 5년 생존율 95% 구간 ±{_num(s['ci95_pp'])}%p")
        if v.get("forecast") and any(j.get("use_forecast") for j in V._judgements(res["store"]) if j["name"] == f"관문 {v.get('recipe')}"):  # 관문 통과한 예측만 쓴다(15-6)
            fc = v["forecast"]
            key = "visit" if "visit" in fc[0] else "value"
            hi, lo = max(fc, key=lambda r: r[key]), min(fc, key=lambda r: r[key])
            if hi is lo:
                hi = lo = fc[0]
            when = lambda r: r.get("date") or r.get("ym")  # noqa: E731
            ev.append({"metric": "예측", "kind": "forecast", "recipe": v.get("recipe"),
                       "text": f"{hi['dong']} 예측 최고 {when(hi)} {_num(hi[key])}, 최저 {when(lo)} {_num(lo[key])}", "dataset": f"레시피 {v.get('recipe')}", "as_of": v.get("data_last") or "-"})
            intervals.append(f"{v.get('recipe')} 예측 구간: {recipes.REG[v['recipe']]['interval']}")
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
            intervals.append(f"{j['name']} 효과 95% 구간 {_num(j['ci95'][0])}% ~ {_num(j['ci95'][1])}%")
    return ev, intervals, as_of


def _conclusion(t, order, res, ev, review):
    js = V._judgements(res["store"])
    dong = "·".join(t.get("space") or []) or "제주"
    if review["status"] == "부분 결과" and not ev:
        return "확인된 결과가 없습니다. 아래 '계산하지 못함'을 확인해 주세요."
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
        return (f"{dong} {name}: 모델이 단순 기준(7일 전 값 등)보다 정확해 예측값을 씁니다." if gate["use_forecast"]
                else f"{dong} {name}: 모델이 단순 기준보다 낫지 않아 예측값 대신 최근 값으로 답합니다.").replace("(7일 전 값 등)", "")
    eff = [j for j in js if j.get("claim") in CLAIM_KO and "ci95" in j]
    if eff:
        cond = "·".join(t.get("cond") or []) or "조건"
        return " / ".join(f"{cond}에 따른 {j['name']} {_label((t.get('metric') or ['일평균방문'])[0])}: {CLAIM_KO[j['claim']]}" for j in eff[:3])
    trend = next((j for j in js if j["name"] == "추세"), None)
    if trend:
        tm = next((x.get("metric") for x in order["tasks"] if x["sub"] == "S1" and x["out"] in res["store"]
                   and any(c in getattr(res["store"][x["out"]].get("table"), "columns", []) for c in ("year", "ym"))), None)
        word = "늘었습니다" if trend["claim"].startswith("증가") else "줄었습니다"
        if "(유의)" in trend["claim"]:
            return f"{dong} {_label(tm)}: 최근 {word}(통계적으로 유의)."
        return f"{dong} {_label(tm)}: 최근 {word[:-3]}지만 통계적으로 의미 있는 변화는 확인하지 못했습니다."
    if any(j.get("claim") in ("이례 증가", "이례 감소") for j in js):
        return f"{dong}: 올해 평소와 다른 변화가 있습니다."
    nums = [e for e in ev if e.get("dong") and e.get("value") is not None]
    if t.get("type") == "T2" and len({e["dong"] for e in nums}) >= 2:  # 비교: 있는 값끼리 크기만 말한다(새 숫자를 만들지 않음)
        m = nums[0]["metric"]
        g = sorted([e for e in nums if e["metric"] == m], key=lambda e: -float(e["value"]))
        return f"{_label(m)}: {_josa(g[0]['dong'], '이', '가')} {', '.join(e['dong'] for e in g[1:])}보다 많습니다({', '.join(e['dong'] + ' ' + _num(e['value']) for e in g)})."
    if t.get("type") == "T11":
        return "관련 자료 목록입니다. 반출 여부를 함께 적었습니다." if ev else "관련 자료를 찾지 못했습니다."
    if ev:
        return ev[0]["text"] + "."
    return "확인된 결과가 없습니다."


def next_questions(t):
    d = (t.get("space") or ["노형동"])[0]
    tgt = t.get("target") or "카페"
    pool = {
        "T1": [f"{d} {tgt} 개업 최근 3년 늘었어?", f"{d} {tgt} 5년 생존율은?", f"{d}이랑 비슷한 동네는?"],
        "T4": [f"{d} {tgt} 5년 생존율은?", f"비 오는 날 {d} 방문은?", f"{d} 생활 진단해줘"],
        "T6": [f"{d} 다음주 방문 예측해줘", f"{d} 생활 진단해줘", f"{d}이랑 비슷한 동네는?"],
        "T8": [f"비 오는 날 {d} 방문은?", f"{d} 생활 진단해줘", f"{d}이랑 비슷한 동네는?"],
        "T9": [f"{d} 생활 진단해줘", f"{d} {tgt} 몇 개야?", f"{d} 다음주 방문 예측해줘"],
        "T10": [f"{d} {tgt} 개업 최근 3년 늘었어?", f"비 오는 날 {d} 방문은?", f"{d}이랑 비슷한 동네는?"],
        "T11": ["센터에 카드 매출 자료 있어?", "센터에 버스 자료 있어?", f"{d} 생활 진단해줘"],
    }
    return pool.get(t.get("type"), [f"{d} 생활 진단해줘", f"{d} {tgt} 몇 개야?", f"{d}이랑 비슷한 동네는?"])


def card(t, review, ev, intervals):
    order, res = review["order"], review["run"]
    limits = list(res.get("relaxed", []))
    limits += [UNIT_NOTE[u] for u in {e.get("unit") for e in ev} if u in UNIT_NOTE]
    limits += [f"계산하지 못함: {SUB_KO.get(x.get('sub'), '')} {x.get('error')}" for x in _failed(order, res)]
    if any("업종 구분 없음" in str(e.get("dataset")) for e in ev) and any(e["metric"] == "업종 5년생존율" for e in ev):
        limits.append("동네별 생존율은 음식점 전체 값이고, 업종별 생존율은 동네 표본이 작아 제주 전체 값입니다.")
    for v in res["store"].values():
        if v.get("survival") and v.get("fallback"):
            limits.append(f"표본 부족: {v['fallback']}")
    for r in review["record"]:
        if r["type"] == "효과 없음" and "관문" in r["detail"]:
            rid = r["detail"].split()[1].rstrip(":")
            limits.append(f"{recipes.REG[rid]['name']}: 모델이 단순 기준보다 낫지 않아 예측값을 쓰지 않고 최근 값으로 답함")
    return {"conclusion": _conclusion(t, order, res, ev, review), "evidence": ev, "intervals": intervals, "limits": limits, "next_questions": next_questions(t)}


def _failed(order, res):
    subs = {t["id"]: t["sub"] for t in order["tasks"]}
    return [dict(x, sub=subs.get(x["task_id"])) for x in res.get("log", []) if x["status"] in ("실패",)]


def card_problems(c, res):
    """수치 대조: 카드의 결론·근거·구간 문장 숫자는 결과 저장소에 있어야 한다. 다음 질문·한계 문구(정책 문장)는 제외."""
    text = "\n".join([c["conclusion"], *[e["text"] for e in c["evidence"]], *c["intervals"]])
    allowed = V._plain(res["store"]) + [recipes.REG]  # 구간 설명 문구는 등록부의 고정 문장
    return check_numbers(text.replace("±10%", ""), allowed)


# ---------- M3-b 계획 해설 ----------
def explain_plan(question, t, order, res, llm_on=True):
    data = []
    for x in order["tasks"]:
        if x["sub"] == "S1":
            src = x.get("source") or {}
            nm = re.sub(r"^\d+\s*", "", str((res["store"].get(x["out"]) or {}).get("dataset") or src.get("name") or x.get("metric")))
            data.append(f"{_label(x.get('metric'))}({nm})")
    path = " → ".join(dict.fromkeys(SUB_KO[x["sub"]] for x in order["tasks"]))
    tpl = f"질문을 '{TYPE_KO.get(t['type'], t['type'])}'로 보고 {', '.join(data) or '자료 목록'}을 골라 {path} 순서로 계산했습니다."
    if not llm_on:
        return {"text": tpl, "by": "템플릿", "sec": 0.0}
    user = f"질문: {question}\n질문 종류: {TYPE_KO.get(t['type'])}\n고른 자료: {', '.join(data) or '자료 목록'}\n계산 순서: {path}"
    out, err, sec = _ask_llm(M3B_SYSTEM, user)
    probs = [err] if err else llm_text_ok(out, question)
    if not probs and not re.search(r"니다\.?$", out):
        probs = ["문체('~습니다' 아님)"]
    subs = {x["sub"] for x in order["tasks"]}
    for pat, need in ((r"판정|우연", "S6"), (r"예측|모델", "S3"), (r"그래프|차트", "S4"), (r"단위", "S5")):  # 없는 단계를 말하면 사실과 다른 해설
        if not probs and re.search(pat, out) and need not in subs:
            probs = [f"없는 단계 언급({need})"]
    if not probs and re.search(r"연도별", out) and not any("year" in getattr((res["store"].get(x["out"]) or {}).get("table"), "columns", []) for x in order["tasks"]):
        probs = ["없는 단계 언급(연도별)"]
    if probs:
        return {"text": tpl, "by": "템플릿(LLM 대체)", "llm_raw": out, "problems": probs, "sec": round(sec, 3)}
    return {"text": out, "by": "LLM", "sec": round(sec, 3)}


# ---------- M1-b 되묻기 ----------
def clarify(question, it, llm_on=True):
    t = it["tuple"]
    amb = it.get("amb") or {}
    cands = [c for cs in amb.values() for c in cs][:3]
    slot = "동네"
    if not cands:
        cands = EXAMPLE_DONGS if not t.get("space") else [TYPE_KO["T1"], TYPE_KO["T4"], TYPE_KO["T8"]]
        slot = "동네" if not t.get("space") else "질문 종류"
    base = re.sub(r"[?？]$", "", question)
    tpl = {"ask": f"어느 {slot}인지 골라 주세요.", "buttons": [f"{c}" for c in cands], "slot": slot, "by": "템플릿", "card": it.get("card")}
    if not llm_on:
        return tpl
    out, err, sec = _ask_llm(M1B_SYSTEM, f"질문: {base}\n빈 칸: {slot}\n후보: {', '.join(cands)}")
    try:
        js = json.loads(re.search(r"\{.*\}", out or "", re.S).group(0))
        btn = [str(b) for b in js["buttons"]][:3]
        ok = len(btn) == len(cands) and all(c in b for c, b in zip(cands, btn)) and not any(llm_text_ok(x) for x in [js["ask"], *btn] if re.search(r"\d", DONG_NUM.sub(" ", x)))
        if ok and not llm_text_ok(js["ask"]) and base not in js["ask"]:
            return {"ask": js["ask"], "buttons": btn, "slot": slot, "values": cands, "by": "LLM", "sec": round(sec, 3), "card": it.get("card")}
    except Exception:
        pass
    return dict(tpl, by="템플릿(LLM 대체)", values=cands, llm_raw=out, sec=round(sec, 3))


# ---------- 내려받기 ----------
def downloads(order, res):
    out = []
    for t in order["tasks"]:
        v = res["store"].get(t["out"])
        if v is not None and "table" in v and len(v["table"]):
            out.append({"name": f"{t['id']}_{t.get('metric') or 'catalog'}.csv", "rows": int(len(v["table"])), "export": v.get("export", "가능"),
                        "csv": v["table"].to_csv(index=False)})
        if t["sub"] == "S4" and v:
            out.append({"name": f"{t['id']}_chart.json", "chart": v.get("chart")})
    return out


# ---------- 진입점 ----------
def respond(question, env=None, llm_on=True, interpret=None, **review_kw):
    t0 = time.perf_counter()
    seen = {}
    if interpret is None:
        import m1
        interpret = m1.M1().interpret

    def capture(q):
        it = interpret(q)
        seen["it"] = it
        return it
    rv = V.review(question, env, interpret=capture, **review_kw)
    it = seen["it"]
    t = rv["tuple"]
    out = {"question": question, "status": rv["status"], "tuple": t, "interpret": {k: it.get(k) for k in ("path", "confidence", "card", "sec")}}
    if rv["status"] in ("되묻기",):
        import qparse
        amb = qparse.parse(question).get("_amb") or {}
        out["clarify"] = clarify(question, dict(it, amb=amb), llm_on)
    elif rv["status"] in ("범위밖",) or rv.get("run") is None:
        out["card"] = {"conclusion": (it.get("card") or {}).get("text") or "지금 자료로 답할 수 없는 질문입니다.", "evidence": [], "intervals": [], "limits": [], "next_questions": next_questions(t)}
    else:
        ev, intervals, as_of = _evidence(rv["order"], rv["run"])
        c = card(t, rv, ev, intervals)
        probs = card_problems(c, rv["run"])
        if probs:  # 카드 수치가 결과와 어긋나면 검수 템플릿 문장으로 바꾼다
            c = dict(c, conclusion="수치 대조에 실패해 확인된 값만 보여 드립니다.", evidence=[{"text": x} for x in V.template_answer(rv["order"], rv["run"]).splitlines()])
        out["card"] = dict(c, number_check=probs)
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
    off = "--no-llm" in sys.argv
    for q in [a for a in sys.argv[1:] if not a.startswith("--")]:
        r = respond(q, llm_on=not off)
        print("■", q, "|", r["status"], f"{r['sec']}초")
        if "clarify" in r:
            print("  되묻기:", r["clarify"]["ask"], r["clarify"]["buttons"], r["clarify"]["by"])
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
