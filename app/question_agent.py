"""질문 담당 Agent(일반 경로, 2026-11-15 마스터 지시: 계획표로 단정 짓지 말고 Agent가 개입하게).

센터 상담원이 도민 질문을 처리하듯 '계산 → 결과 확인 → 다음 행동'을 되풀이한다(최대 3번).
- 코드가 하는 일(정해진 것): 해석·계산·숫자, 그리고 질문과 결과의 어긋남 찾기(물은 기간·조건으로 계산했는지, 순위를 물었는데 한 동네 값인지,
  지표 낱말이 없어 기본 지표로 계산했는지, 해석 확신이 낮은지). 고칠 후보 값도 질문에서 코드가 뽑는다(모델이 값을 지어내지 않게).
- 모델이 하는 일(판단): 지금 결과와 어긋남 목록을 보고 행동 하나를 고른다. 답하기 · 안내 붙여 답하기 · 다시 계산(종류·지표·조건·기간·순위 방향을
  목록 안에서 바꿈) · 기법으로(분석 담당에게) · 되묻기 · 범위 밖.
- 소형 모델(qwen2.5:7b)이 다단계 자율 계획에 약한 원인(열린 행동 공간, 결과를 안 보고 계획, 근거 없음)을 막으려고, 한 번에 닫힌 선택 하나만 하게 하고
  결과 요약과 어긋남 목록을 근거로 준다(분석 담당 Agent와 같은 방식, 요청 이해 111/120).
기본으로 켠다(Ollama가 있을 때). 끄기: JEJU_QUESTION_AGENT=0. 모든 일반 질문에서 첫 판단을 한 번 하고(어긋남이 없으면 '지금 답'), 지표가 질문 뜻과 맞는지도 확인한다.
측정: tools/eval/general_answer.py(판정 150: 계획 표 83 → Agent 97)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guide as G  # noqa: E402
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402

BY = "로컬 모델(qwen2.5:7b)"
TYPE_KO = {"T1": "현황", "T2": "동네 비교", "T3": "순위", "T4": "추이", "T5": "구성", "T6": "조건 효과", "T7": "관계", "T8": "예상", "T9": "비슷한 동네",
           "T10": "종합 진단", "T11": "자료 찾기", "T13": "시간대", "T14": "조건 탐색", "T15": "이례 변화"}
# 자료에 그 말이 없을 때 가까운 지표 후보(코드가 후보만 낸다, 고르는 것은 모델)
SUB_HINTS = [(re.compile(r"비싼|비싸|저렴|싼\s*(곳|식당|가게|집|데)|가격|객단가"), ["건당금액"], "메뉴 가격 자료는 없어 카드 결제 1건당 금액이 가장 가까워요."),
             (re.compile(r"(?<!유동)(?<!방문)인구(?!\s*(구성|연령|나이))|주민\s*수|몇\s*명\s*(이\s*)?(살|사)"), ["거주연령구성", "일평균방문"], "주민등록 인구 수 자료는 없어요."),
             (re.compile(r"관광객"), ["관광객비중", "외국인매출"], "관광객 수 자료는 없고 카드 매출의 관광객 비중이 있어요."),
             (re.compile(r"\d{1,2}\s*시|몇\s*시|시간대"), ["시간대매출", "시간대방문"], "시간대별 사람 수는 센터 자료가 필요하고, 공개 자료는 카드 매출 시간대 비중이에요."),
             (re.compile(r"잘\s*(돼|되|나가|팔)|장사|벌이|수입"), ["매출", "이용건수"], "장사가 잘되는지는 카드 매출로 봐요."),
             (re.compile(r"사람\s*(많|적)|붐비|붐벼|북적|유동|발길|한산|썰렁"), ["일평균방문"], "사람이 많은지는 하루 방문 지수로 봐요."),
             # 자료 능력 명세 7절 대체 지표 목록에 맞춤(2026-11-15 새 기준 조정용: 생활 말투 지표 낱말을 못 읽던 Fable·Haiku 문항)
             (re.compile(r"커지|커져|성장|확장|키워"), ["매출성장"], "상권이 커지는지는 최근 12개월 카드 매출이 그 전보다 늘었는지로 봐요."),
             (re.compile(r"오래\s*(버티|버텨|가|못)|살아남"), ["5년생존율"], "가게가 오래 버티는지는 5년 생존율로 봐요."),
             (re.compile(r"나이대|연령대|몇\s*살|나이"), ["거주연령구성", "방문연령구성"], ""),
             (re.compile(r"버스|정류"), ["버스일평균"], ""), (re.compile(r"문\s*(닫|연)|폐업|개업|새로\s*생"), ["폐업수", "개업수", "폐업률"], "")]
# 지표 낱말이 없을 때 모델이 뜻으로 고르는 주요 지표(설명은 화면 용어와 같음)
MAIN_METRICS = [("점포수", "가게가 몇 곳 있는지·몰려 있는지"), ("매출", "카드 매출 규모, 장사가 잘되는지"), ("매출성장", "매출이 늘고 있는지(성장)"),
                ("일평균방문", "사람이 얼마나 오가는지(유동인구)"), ("개업수", "새로 문을 여는 가게 수"), ("폐업수", "문을 닫는 가게 수"),
                ("5년생존율", "가게가 오래 버티는지"), ("건당금액", "손님이 한 번에 쓰는 돈"), ("관광객비중", "관광객·외지인 손님 비중"),
                ("외국인매출", "외국인 손님 결제"), ("시간대매출", "몇 시·어느 때 매출이 많은지"), ("청년비중", "20~30대 젊은 사람 비중"), ("고령비중", "어르신 비중")]
METRIC_WORDS = json.loads((Q.ROOT / "data" / "lexicon" / "metrics.json").read_text(encoding="utf-8"))


def evidenced(q, m):
    """질문 낱말이 지표 m을 뒷받침하는지: 지표 이름·사전 낱말·대체 지표 힌트(SUB_HINTS)."""
    qs = re.sub(r"\s+", "", q or "")
    if m in qs or Q.METRICS.get(m, "#").replace(" ", "") in qs:
        return True
    if any(w.replace(" ", "") in qs for w in METRIC_WORDS.get(m) or []):
        return True
    return any(m in ms and rx.search(q or "") for rx, ms, _ in SUB_HINTS)


RANK_Q = re.compile(r"(가장|제일|젤|최고|최대|최소|꼴찌|1위|순위|어디가|어느\s*동네)")
LOW_Q = re.compile(r"(가장|제일|젤|덜)\s*(적|낮|작|안)|최하위|꼴찌|(적|낮|작)은\s*(동네|곳|지역|데)")
DATA_Q = re.compile(r"(자료|데이터)\S{0,2}\s*(뭐|무엇|어떤|있)")
OUT_HINT = re.compile(r"인허가|허가|신고|서류|절차|법률|법적|세금|맛집|맛있|맛은|후기|평점|리뷰|추천해|매매가|시세|임대|권리금|예약자|투숙객")  # 명세 6절 범위 밖 낱말
FUTURE_MONEY_Q = re.compile(r"(내년|다음\s*해|앞으로|미래|\d+\s*년\s*뒤|하면).{0,25}(매출|수익|벌|수입).{0,15}(얼마|예측|나올|될지|될까)")
PRIVATE_Q = re.compile(r"명단|연락처|전화\s*번호|인적\s*사항|개인\s*정보|주민\s*번호|예약자|투숙객\s*정보|누가\s*(사|운영)")
SNOW_Q = re.compile(r"눈\s*(이\s*)?(오|올|와|내리|온|많|쌓)|폭설|대설")


def enabled():
    """켜는 조건: JEJU_QUESTION_AGENT가 0이 아니고, 로컬 모델(Ollama)이 살아 있을 때. 웹 데모(Vercel)처럼 Ollama가 없으면 지금 경로로 답한다."""
    if os.environ.get("JEJU_QUESTION_AGENT", DEFAULT_ON) == "0":
        return False
    import llm
    return llm.backend() != "rule" and llm._ollama_alive()


DEFAULT_ON = "1"


def _period_words(q):
    import result
    ay, am = result._asked_period(q)
    rm = re.search(r"(최근|지난)\s*(\d{1,2})\s*개월", q)
    return {"year": ay, "month": am, "recent": int(rm.group(2)) if rm else None}


def _conds(q):
    found = qparse.hits(q, qparse.COND_W) if hasattr(qparse, "COND_W") else []
    import result
    if re.search(result.RAIN_WORD, q) and "비" not in found:
        found = ["비"] + list(found)
    return [c for c in found if c in Q.CONDS]


def summary(r):
    """지금 처리를 한 줄로(모델에 보여 줄 관찰)."""
    t = r.get("tuple") or {}
    st = r.get("status")
    if st == "선택필요":
        return f"처리: 되묻기(빠진 조건을 고르게 함: {(r.get('choose') or {}).get('message', '')[:60]})"
    if st == "범위밖":
        return f"처리: 범위 밖 안내({((r.get('card') or {}).get('conclusion') or '')[:60]})"
    per = "질문 기간 반영" if (t.get("ask_year") or t.get("ask_month") or t.get("ask_recent")) else "가장 최근 달·해"
    conc = ((r.get("card") or {}).get("conclusion") or "")[:90]
    return (f"처리: 답함 · 종류 {TYPE_KO.get(t.get('type'), t.get('type'))} · 지표 {', '.join(t.get('metric') or []) or '없음(기본 지표)'} · "
            f"동네 {', '.join(t.get('space') or []) or '없음(제주 전체)'} · 업종 {t.get('target') or '없음'} · 조건 {', '.join(t.get('cond') or []) or '없음'} · "
            f"기간 {per}{' · 작은 순서' if t.get('order') == 'asc' else ''}\n결론: {conc}")




def gaps(q, it, r, done=()):
    """질문 요소와 결과의 어긋남(코드). 항목: kind, text(모델에 보임), change(다시 계산 후보), note(안내 문장)."""
    t = r.get("tuple") or it.get("tuple") or {}
    out = []
    if r.get("status") in ("범위밖", "선택필요"):
        pass
    p = _period_words(q)
    if any(p.values()) and not (t.get("ask_year") or t.get("ask_month") or t.get("ask_recent")) and r.get("status") != "범위밖":
        desc = " ".join(x for x in [f"{p['year']}년" if p["year"] else "", f"{p['month']}월" if p["month"] else "", f"최근 {p['recent']}개월" if p["recent"] else ""] if x)
        out.append({"kind": "기간", "text": f"질문의 기간({desc})이 아니라 가장 최근 값으로 계산했어요.", "change": {"period": True},
                    "note": f"질문의 기간({desc})으로는 계산하지 못해 가장 최근 값으로 답했어요."})
    cs = [c for c in _conds(q) if c not in (t.get("cond") or [])]
    if cs and r.get("status") not in ("범위밖",):
        out.append({"kind": "조건", "text": f"질문에 조건 '{', '.join(cs)}'이 있는데 조건 없이 계산했어요(조건 효과는 종류 '조건 효과'로 계산).",
                    "change": {"cond": cs[0], "type": "T6"}, "note": f"'{cs[0]}' 조건별 값은 이 답에 반영하지 않았어요."})
    if SNOW_Q.search(q):
        out.append({"kind": "자료 없음", "text": "질문에 '눈'이 있지만 날씨 자료는 비 온 날만 나눠요(눈 자료 없음).", "change": {},
                    "note": "눈 온 날을 따로 나눈 자료는 없어요. 위 답은 날씨 조건 없이 본 값이에요."})
    if RANK_Q.search(q) and not t.get("space") and t.get("type") not in ("T3", "T14", "T11", "T12", "T9") and r.get("status") not in ("범위밖",):
        out.append({"kind": "순위", "text": "동네 이름 없이 '가장·어디'를 물었는데 순위로 계산하지 않았어요.", "change": {"type": "T3", "order": "asc" if LOW_Q.search(q) else "desc"}, "note": ""})
    if t.get("type") == "T3" and LOW_Q.search(q) and t.get("order") != "asc":
        out.append({"kind": "순위 방향", "text": "'가장 적은·낮은'을 물었는데 큰 순서로 계산했어요.", "change": {"order": "asc"}, "note": ""})
    hints = [(ms, why) for rx, ms, why in SUB_HINTS if rx.search(q)]
    cand = [m for ms, _ in hints for m in ms if m not in (t.get("metric") or [])]
    metric_done = any("지표를" in x for x in done)
    # 지표 확인: 지금 지표가 질문 낱말로 뒷받침되면(예: '매출'·'고령비중'을 그대로 물음) 바꾸는 선택지를 내지 않는다.
    # 2026-11-15 새 기준 조정용 304: 질문에 적힌 지표를 모델이 다른 지표로 바꿔 틀린 문항 12건(도운 문항 23건)
    if not done and (t.get("metric") or []) and r.get("status") not in ("범위밖", "선택필요") and t.get("type") not in ("T11", "T9", "T10") \
            and not any(evidenced(q, m) for m in t["metric"]):
        cur = ", ".join(Q.METRICS.get(m, m) for m in t["metric"])
        alt = [m for m, _ in MAIN_METRICS if m not in t["metric"]]
        ev = [m for m in alt if evidenced(q, m)]
        out.append({"kind": "지표 확인", "text": f"지금 지표는 '{cur}'예요. 질문의 뜻과 다르면 다른 지표로 바꿀 수 있어요.",
                    "change": {"metric": ev or alt}, "note": "", "only": bool(ev)})
    if metric_done:
        pass
    elif not (t.get("metric") or []) and r.get("status") not in ("범위밖", "선택필요"):
        out.append({"kind": "지표 없음", "text": "질문에서 지표 낱말을 찾지 못해 기본 지표(가게 수 등)로 계산했어요." + (f" 질문과 가까운 지표 후보: {', '.join(dict.fromkeys(cand))}." if cand else ""),
                    "change": {"metric": list(dict.fromkeys(cand))}, "note": next((why for _, why in hints if why), "")})
    elif cand and not set(t.get("metric") or []) & {m for ms, _ in hints for m in ms}:
        out.append({"kind": "대체 지표", "text": f"질문의 말에 더 가까운 지표 후보가 있어요: {', '.join(dict.fromkeys(cand))}.", "change": {"metric": list(dict.fromkeys(cand))},
                    "note": next((why for _, why in hints if why), "")})
    if FUTURE_MONEY_Q.search(q) and r.get("status") != "범위밖":  # 명세 6절: 미래 매출 금액 예측은 범위 밖(다음 7일 방문 예상은 범위 안)
        out.append({"kind": "미래 금액", "text": "앞으로의 매출 금액을 맞히는 질문 같아요. 자료로는 미래 매출 금액을 예측하지 않아요(다음 7일 방문 예상만 있어요).",
                    "change": {}, "note": ""})
    if DATA_Q.search(q) and t.get("type") != "T11" and not t.get("space"):
        out.append({"kind": "자료 찾기", "text": "자료가 있는지를 묻는 질문 같아요.", "change": {"type": "T11", "metric": ["자료목록"]}, "note": ""})
    import result
    blocked = r.get("status") == "범위밖"
    if blocked and it.get("rule_expect") == "답함" and it.get("rule_type") not in (None, "T12") and not result.OUTSIDE_Q.search(q) and not PRIVATE_Q.search(q):
        out.append({"kind": "범위 밖 판단", "text": f"분류기는 범위 밖으로 봤지만 사전 규칙은 '{TYPE_KO.get(it['rule_type'], it['rule_type'])}' 질문으로 읽었어요.",
                    "change": {"rule": True}, "note": ""})
    if not t.get("space") and r.get("status") not in ("범위밖", "선택필요") and t.get("type") in qparse.NEED_DONG and not RANK_Q.search(q) and not qparse.jeju_wide(t):
        out.append({"kind": "동네 없음", "text": "질문에 동네 이름이 없어 제주 전체로 답했어요('동네', '이 근방'처럼 어느 동네인지 모르는 말일 수 있어요).", "change": {}, "note": ""})
    if t.get("space") and result.OUTSIDE_Q.search(q) and not blocked:
        out.append({"kind": "제주 밖", "text": "질문에 제주 밖 지명이 있어요. 자료는 제주 43개 동네뿐이에요.", "change": {}, "note": ""})
    if PRIVATE_Q.search(q) and not blocked:
        out.append({"kind": "개인 정보", "text": "개인·업체 명단이나 연락처 같은 개인 정보를 묻는 질문 같아요. 자료에 없고 제공할 수 없어요.", "change": {}, "note": ""})
    if r.get("status") == "선택필요" and RANK_Q.search(q) and not t.get("space"):
        out.append({"kind": "순위 되묻기", "text": "동네 없이 '가장·어디'를 물어 되물었지만, 제주 전체 동네 순위로 답할 수 있어요.",
                    "change": {"type": "T3", "order": "asc" if LOW_Q.search(q) else "desc", "confirm": True}, "note": ""})
    conf = it.get("confidence")
    if conf is not None and conf < 0.5 and r.get("status") not in ("범위밖",):
        top = ", ".join(f"{TYPE_KO.get(c, c)}({c}) {p_:.2f}" for c, p_ in (it.get("type_top") or []))
        out.append({"kind": "확신 낮음", "text": f"질문 종류 해석의 확신이 낮아요({conf:.2f}). 후보: {top}.", "change": {"type": [c for c, _ in (it.get("type_top") or [])]}, "note": ""})
    return out


S_DECIDE = ("너는 제주빅데이터센터에서 도민 질문을 처리하는 상담 담당자다. 시스템이 질문을 한 번 계산했다. 질문, 지금 처리, 코드가 찾은 어긋남을 보고 "
            "선택지 가운데 질문에 가장 맞게 답하는 것 하나를 번호로 고른다. 더 맞게 다시 계산할 수 있으면 다시 계산을 고르고, "
            "다시 계산할 방법이 없을 때만 안내를 붙여 답한다. 어긋남이 없고 답이 질문에 맞으면 '지금 답 그대로'를 고른다. 이유는 한 문장.")


def options(q, r, it, gs, tried=()):
    """코드가 만든 선택지 목록: [{id, text, act, change}]. change는 해석에 반영할 값(모두 질문·후보에서 뽑음)."""
    t = r.get("tuple") or it.get("tuple") or {}
    p = _period_words(q)
    out = []

    def add(text, act, change=None):
        if text in tried:  # 이미 해 본 다시 계산은 다시 보이지 않는다
            return
        out.append({"id": str(len(out) + 1), "text": text, "act": act, "change": change or {}})
    for x in gs:
        c = x["change"]
        if x["kind"] == "기간":
            add(f"질문의 기간({x['text'].split('(')[1].split(')')[0]})으로 다시 계산", "다시 계산", {"period": p})
        elif x["kind"] == "조건":
            add(f"'{c['cond']}' 조건 효과로 다시 계산(하루 방문 기준)", "다시 계산", {"cond": c["cond"], "type": "T6", "metric": ["일평균방문"]})
        elif x["kind"] in ("순위", "순위 방향"):
            add(f"동네 순위({'작은' if c.get('order') == 'asc' else '큰'} 순서)로 다시 계산", "다시 계산", {"type": "T3", "order": c.get("order")})
        elif x["kind"] in ("지표 없음", "대체 지표", "지표 확인"):
            ms = list(c.get("metric") or [])
            if (x["kind"] == "지표 없음" and not ms) or (x["kind"] == "지표 확인" and not x.get("only")):  # 낱말 근거가 없으면 주요 지표 중에서 뜻으로 고르게 한다
                ms += [m for m, _ in MAIN_METRICS if m not in ms and m not in (t.get("metric") or [])]
            desc = dict(MAIN_METRICS)
            for m in ms:
                add(f"지표를 '{Q.METRICS.get(m, m)}'(으)로 바꿔 다시 계산" + (f" — {desc[m]}" if m in desc else ""), "다시 계산", {"metric": [m]})
        elif x["kind"] == "자료 찾기":
            add("센터·공개 자료 목록에서 찾아 답하기", "다시 계산", {"type": "T11", "metric": ["자료목록"]})
        elif x["kind"] == "범위 밖 판단":
            add(f"사전 규칙 해석('{TYPE_KO.get(it.get('rule_type'), it.get('rule_type'))}')대로 답해 보기", "다시 계산", {"rule": True})
        elif x["kind"] == "순위 되묻기":
            add(f"제주 전체 동네 순위({'작은' if c.get('order') == 'asc' else '큰'} 순서)로 답하기", "다시 계산", c)
        elif x["kind"] == "확신 낮음":
            for c_ in c.get("type") or []:
                if c_ != t.get("type") and c_ in TYPE_KO:
                    add(f"질문 종류를 '{TYPE_KO[c_]}'(으)로 보고 다시 계산", "다시 계산", {"type": c_})
    if r.get("status") == "선택필요" and t.get("expect") == "답함":
        add("지금 해석대로 답 보기(되묻지 않음)", "다시 계산", {"confirm": True})
    if any(x.get("note") for x in gs):
        add("다시 계산하지 않고, 어긋남을 안내해 지금 답", "안내 붙여 답하기")
    add("지금 답 그대로" if r.get("status") not in ("선택필요", "범위밖") else "지금 처리 그대로(되묻기·범위 밖 안내)", "답하기")
    # 근거 없는 처리 바꾸기를 막는다(2026-11-15 새 기준 조정용: 어긋남이 없는데 모델이 되묻기·범위 밖으로 바꾼 13건 중 10건이 오답)
    if r.get("status") != "선택필요" and not t.get("space") and not RANK_Q.search(q):  # 동네가 있거나 순위 질문이면 되묻기 선택지를 주지 않는다
        add("꼭 필요한 동네가 질문에 없어 되묻기", "되묻기")
    if r.get("status") != "범위밖" and (gs or OUT_HINT.search(q) or qparse.hits(q, qparse.OUT_W)):
        add("지금 자료로 답할 수 없는 질문이라 범위 밖 안내", "범위 밖")
    add("통계 분석(기법)이 필요해 분석 담당에게 넘기기", "기법으로")
    return out


def decide(q, r, it, gs, chat=None, done=()):
    import analyst
    ops = options(q, r, it, gs, done)
    g = "\n".join(f"- [{x['kind']}] {x['text']}" for x in gs) or "- 없음"
    tried = ("\n이미 해 본 것: " + "; ".join(done)) if done else ""
    user = (f"질문: {q}\n{summary(r)}\n코드가 찾은 어긋남:\n{g}{tried}\n선택지:\n" + "\n".join(f"{o['id']}. {o['text']}" for o in ops))
    schema = {"type": "object", "required": ["choice", "reason"], "properties": {"choice": {"type": "string", "enum": [o["id"] for o in ops]}, "reason": {"type": "string"}}}
    d = analyst._ask(chat, S_DECIDE, user, schema, max_tokens=150)
    keep = next(o for o in ops if o["act"] == "답하기")  # 모델이 없거나 실패하면 지금 답을 그대로 둔다
    pick = next((o for o in ops if o["id"] == str(d.get("choice"))), keep)
    return pick, str(d.get("reason") or "")


def _apply(t, change):
    """선택지의 값을 해석에 반영(값은 모두 코드가 만든 후보)."""
    t2, why = dict(t), []
    if change.get("rule"):  # 사전 규칙 해석으로 바꿔 답해 본다(값은 qparse가 질문에서 읽은 것)
        base = {k: v for k, v in qparse.parse(t.get("_q") or "").items() if not k.startswith("_")} if t.get("_q") else None
        if base:
            t2 = dict(base, expect="답함")
            if not t2.get("metric") and t.get("metric"):  # 사전 규칙이 지표를 못 읽으면 지금 지표(보정 규칙의 대체 지표 포함)를 둔다
                t2["metric"] = list(t["metric"])
            why.append(f"사전 규칙 해석({TYPE_KO.get(base.get('type'), base.get('type'))})")
            return t2, why
    if change.get("type"):
        t2["type"], t2["form"] = change["type"], Q.DEFAULT_FORM.get(change["type"])
        why.append(f"종류 {TYPE_KO.get(change['type'], change['type'])}")
    if change.get("metric"):
        t2["metric"] = list(change["metric"])
        if t2.get("type") in ("T10", "T9", "T5", "T15", "T12", None) and not change.get("type"):  # 지표를 쓰지 않는 종류면 그 지표를 계산하는 종류로
            t2["type"] = "T3" if (RANK_Q.search(t.get("_q") or "") and not t2.get("space")) else "T1"
            t2["form"] = Q.DEFAULT_FORM[t2["type"]]
        why.append(f"지표 {', '.join(Q.METRICS.get(m, m) for m in change['metric'])}")
    if change.get("cond"):
        t2["cond"] = [change["cond"]]
        why.append(f"조건 {change['cond']}")
    p = change.get("period")
    if p and p.get("month") and t2.get("type") == "T6" and not change.get("cond"):  # '7월'에서 읽은 계절 조건 효과가 아니라 그 달 값
        t2["type"], t2["form"], t2["cond"] = "T1", Q.DEFAULT_FORM["T1"], []
    if p:
        t2.update({k2: v for k2, v in (("ask_year", p.get("year")), ("ask_month", p.get("month")), ("ask_recent", p.get("recent"))) if v})
        why.append("질문 기간")
    if change.get("order"):
        t2["order"] = "asc" if change["order"] == "asc" else None
        why.append("작은 순서" if change["order"] == "asc" else "큰 순서")
    if change.get("confirm"):
        why.append("지금 해석대로")
    if t2.get("type") in ("T3", "T11", "T6") or change.get("confirm"):
        t2["expect"] = "답함"
    return t2, why


def run(question, env=None, llm_on=True, chat=None, max_turns=3):
    """질문 하나. 돌려주는 값: result.respond와 같은 형식 + question_agent(판단 기록)."""
    import m1
    import result
    t0 = time.perf_counter()
    env = dict(env or {})
    M = m1.M1()
    it = M.interpret(question)
    r = result.respond(question, env, llm_on, interpret=lambda q: it)
    trace = []
    if r.get("status") == "Agent" or r.get("pieces") or (r.get("agent") and "나눠" in str(r.get("escalated"))):  # 나눠 답한 질문은 조각마다 이미 처리됨
        return dict(r, question_agent={"turns": [], "skipped": "질문 나누기로 조각마다 답함"})
    done, notes = [], []
    for turn in range(max_turns):
        gs = gaps(question, it, r, done)
        if not gs and turn > 0:  # 첫 차례는 어긋남이 없어도 모델이 한 번 확인한다
            break
        t1 = time.perf_counter()
        pick, reason = decide(question, r, it, gs, chat, done)
        act = pick["act"]
        rec = {"turn": turn + 1, "gaps": [x["kind"] for x in gs], "choice": pick["text"], "action": act, "reason": reason[:120], "by": BY, "sec": round(time.perf_counter() - t1, 2)}
        trace.append(rec)
        if act == "답하기":
            break
        if act == "안내 붙여 답하기":
            notes += [x["note"] for x in gs if x.get("note")]
            break
        if act == "다시 계산":
            t2, why = _apply(dict(r.get("tuple") or it["tuple"], _q=question), pick["change"])
            t2.pop("_q", None)
            rec["change"] = why
            it2 = dict(it, tuple=t2, card=qparse.card(t2), needs_confirm=False, confidence=None)  # Agent가 고른 해석은 다시 확인하지 않는다
            r2 = result.respond(question, dict(env, _agent_tuple=True, _no_split=True), llm_on, interpret=lambda q, _it=it2: _it)
            asked = list((r.get("tuple") or it["tuple"]).get("space") or [])
            text2 = json.dumps((r2.get("card") or {}).get("conclusion") or "", ensure_ascii=False) + json.dumps(r2.get("result_dongs") or [], ensure_ascii=False)
            if asked and r2.get("card") and not any(d in text2 for d in asked):  # 결과 검증(코드): 다시 계산한 답이 질문의 동네를 담지 않으면 버린다
                rec["note"] = "다시 계산한 답에 질문의 동네가 없어 앞 답을 유지(결과 검증)"
                break
            if r2.get("card") and r2.get("status") not in ("범위밖", "선택필요", "되묻기"):  # 답이 나왔으면 받는다(상태 이름은 경로마다 다름)
                r, it = r2, it2
                done.append(pick["text"])
                continue
            rec["note"] = f"다시 계산이 '{r2.get('status')}'로 끝나 앞 답을 유지"
            break
        if act == "기법으로":
            ag = result._escalate(question, it, t0, "질문 담당 Agent가 통계 분석이 필요하다고 판단")
            if ag:
                r = ag
            else:
                rec["note"] = "분석 담당이 답하지 못해 앞 답을 유지"
            break
        if act == "되묻기":
            t = r.get("tuple") or it["tuple"]
            r = result._choose(question, t, G.to_slots(t), "질문에 꼭 필요한 조건이 없어요. 아래에서 골라 주세요.", "space")
            break
        if act == "범위 밖":
            t = r.get("tuple") or it["tuple"]
            r = result._blocked(question, dict(t, type="T12", expect="범위밖"), "지금 자료로는 답할 수 없는 질문이에요.", [])
            break
    changed = [", ".join(x.get("change") or []) for x in trace if x.get("action") == "다시 계산" and x.get("change") and not x.get("note")]
    if changed:
        notes = [f"질문 담당 Agent가 결과를 보고 다시 계산했어요({' → '.join(changed)})."] + notes
    if notes and r.get("understood"):
        r["understood"]["notes"] = list(dict.fromkeys(list(r["understood"].get("notes") or []) + notes))
    r = dict(r, question_agent={"turns": trace, "sec": round(time.perf_counter() - t0, 2), "model_calls": len(trace)})
    return r
