"""질문 나누기(문서 26·Gemini 049, 2026-11-14 마스터 결정): 한 질문에 하위 질문이 여럿이면 코드가 나누고, 조각마다 일반 경로로 답해 코드가 답을 묶는다.

역할 나눔(마스터 원칙 '정해진 것은 코드, 문장 파악은 모델'):
- 코드: 자를 자리(문장 끝·여러 단계 표지), 동네·업종 물려주기, 앞 결과 넣기('1위 동네'), 실패 처리, 답 묶기.
- 분류기(LLM 아님): 조각마다 질문 종류 읽기(일반 경로 그대로).
- LLM: 쓰지 않는다. 개발용 측정(047·048 a·b 90 + 일반 100)에서 소형 모델의 나누기는 코드 규칙보다 낮았다(수 맞음 30~38/90 vs 70/90).
049 실패 처리: 앞 결과가 없으면 뒤 조각을 계산하지 않고 알림, 1위 동률은 첫 동네로 계산하고 알림, 뒤 조각은 앞 조각만 참조, 동네 이름은 목록(Q.DONGS)으로만 넣음.
Claude 유무와 상관없이 먼저 돈다(2026-11-14 마스터 결정). 끄기: JEJU_SPLIT=0.
"""
import os
import re
import time

import guide as G
import plan_agent as PA
import qparse
import qtuple as Q

SENT = re.compile(r"(?<=[.?!？])\s+|(?<=[가-힣][요줘라])[,.]\s*")
REF = re.compile(r"(그|해당|이|저|그런)\s*(동네|곳|지역|읍|면|동네의|곳의)|거기|그곳|이곳|1위\s*(동네|곳|지역)?|가장 [^ ]+ (동네|곳)")
DONG_LISTS = ("T3", "T9", "T14", "T15")  # 결과가 동네 목록인 질문 종류(뒤 조각이 '그 동네'로 이어 받을 수 있음)
MIN = 4
# 자를 자리(개발용 047·048 a·b 90 + 일반 100으로 정함, 2026-11-14). 여러 단계 표지(plan_agent.MULTI)에 동사 + 쉼표 연결('확인한 후,', '살피고,')을 더한다.
CUT = re.compile(PA.MULTI.pattern + r"|(?:[한은던]\s*(?:후|뒤|다음)(?:에)?\s*,)|(?:[가-힣]고\s*,)|(?:(?:알려|보여|찾아|골라|뽑아)주고\s)")
# 자르지 않는 경우: 시점의 '다음'(다음 달), 바람·진행의 '-고 싶다/있다', 명사를 잇는 '및', 범위의 '~부터 ~까지'
TIME_AFTER = re.compile(r"^\s*(달|주말|주|분기|해|년|날|번|시즌|개월)(?![가-힣])|^\s*(달|주말|주|분기|해|년|날)(에|의|도|쯤|부터|까지)")
WISH_AFTER = re.compile(r"^\s*(싶|있)")
SHORT = 10  # 이보다 짧은 조각(예: '분석해줘', '그 다음')은 따로 묻는 것이 아니라 앞 조각에 붙인다. 단 내용어가 있으면 붙이지 않는다
CONTENT = re.compile(r"매출|폐업|개업|생존|방문|유동|점포|가게|매장|버스|손님|관광객|비중|순위|추이|흐름|인구|거기|그곳|그 동네|해당")
REF_POINT = re.compile(r"거기|그곳|이곳|(그|해당|이)\s*(동네|곳|지역)")  # 앞 결과를 가리키는 말만(순위 단서 제외)
METRIC_WORD = re.compile(r"카드 매출|매출|하루 방문|방문|유동인구|점포 수|가게 수|매장 수|생존율|폐업률|폐업|개업|버스 이용|관광객 비중")  # 뒤 조각이 물려받을 지표(미처리 결함 D3)
RANK_CUE = re.compile(r"(1위|가장|제일|최고|최대|최소|꼴찌)\s*\S*\s*(동네|곳|지역)")
# 병렬 최상급: '방문이 가장 적은 동네와 가장 많은 동네 알려줘' → 둘로(평가 2026-11-14 A1)
PARALLEL = re.compile(r"((?:가장|제일)\s*\S+\s*(?:동네|곳))\s*(?:와|과|랑|하고|이랑)\s*((?:가장|제일)\s*\S+\s*(?:동네|곳))")
# 생략형 후속: '그리고 노형동은?' → 앞 질문에서 동네만 바꿈
ELLIPSIS = re.compile(r"^(?:그리고|그럼|또|그러면)?\s*(\S+?)(?:은|는|도)\s*(?:어때|어때요|요)?\s*[?？]?$")


def enabled():
    return os.environ.get("JEJU_SPLIT") != "0"


def _cut(s):
    """문장 하나에서 첫 자를 자리(자르지 않는 경우는 건너뜀)."""
    for m in CUT.finditer(s):
        w = m.group(0)
        if w.strip().startswith("및"):
            continue
        if "까지" in w and "부터" in s[:m.start()]:
            continue
        rest = s[m.end():]
        if w.strip().endswith("다음") and TIME_AFTER.search(rest) or w.rstrip(" ,").endswith("고") and WISH_AFTER.search(rest):
            continue
        if not (MIN <= m.end() < len(s) - 3):
            continue
        return m.end()
    return None


def _content(x):
    return bool(CONTENT.search(x) or qparse.find_target(x) or qparse.find_places(x)[0])


def pieces(q):
    """코드 규칙으로 자른 조각(병렬 최상급 → 문장 끝 → 자를 자리 → 생략형 후속)."""
    m = PARALLEL.search(q or "")
    if m:  # 앞말(지표)과 뒷말(동사)을 두 조각이 함께 쓴다
        head, tail = q[:m.start()], q[m.end():]
        return [f"{head}{m.group(1)}{tail}".strip(), f"{head}{m.group(2)}{tail}".strip()]
    out = []
    for s in [x.strip() for x in SENT.split(q or "") if x and x.strip()]:
        while True:
            i = _cut(s)
            if i is None:
                break
            out.append(s[:i].strip(" ,"))
            s = s[i:].strip(" ,")
        out.append(s)
    out = [x for x in out if len(x) >= 2]
    merged = []
    for x in out:
        e = ELLIPSIS.match(x)
        if merged and e:
            dongs, _ = qparse.find_places(e.group(1))
            prev_dongs, _ = qparse.find_places(merged[-1])
            if dongs and prev_dongs:  # 앞 질문을 그대로 두고 동네만 바꾼다
                merged.append(merged[-1].replace(prev_dongs[0], dongs[0], 1))
                continue
        if merged and len(x.replace(" ", "")) < SHORT and not _content(x):
            merged[-1] = f"{merged[-1]} {x}"
        else:
            merged.append(x)
    if len(merged) >= 2 and len(merged[0].replace(" ", "")) < SHORT and not _content(merged[0]):  # 첫 조각이 짧으면 다음 조각에 붙인다(IndexError 수정, 2026-11-14)
        first = merged.pop(0)
        merged[0] = f"{first} {merged[0]}"
    return merged if len(merged) >= 2 else [q]


def plan(q, interpret):
    """하위 질문 목록. 각 조각: text(실행할 문장), type(분류기), dongs, target, ref(앞 조각 번호 또는 None), inherited(물려받은 칸)."""
    parts = []
    for i, p in enumerate(pieces(q)):
        dongs, _ = qparse.find_places(p)
        tgt = qparse.find_target(p)
        part = {"text": p, "type": None, "expect": None, "dongs": list(dongs), "target": tgt, "ref": None, "inherited": []}
        prev = parts[-1] if parts else None
        if prev and not dongs:
            own_rank = RANK_CUE.search(p) and not REF_POINT.search(p)  # 자기 순위 단서가 있는 조각(병렬 최상급의 둘째 등)은 앞 결과를 이어받지 않는다
            if not own_rank and ((prev["type"] in DONG_LISTS and not prev["dongs"]) or (REF_POINT.search(p) and (not prev["dongs"] or prev["type"] in DONG_LISTS))):
                # '노형동과 비슷한 동네 + 거기'처럼 동네 목록을 내는 종류는 '거기'가 결과 동네를 가리킨다
                part["ref"] = i - 1  # 앞 조각이 낸 동네를 쓴다(값은 실행할 때 코드가 넣는다)
            elif prev["dongs"]:
                part["dongs"], part["inherited"] = list(prev["dongs"]), part["inherited"] + ["동네"]
        if prev and not tgt and prev["target"]:
            part["target"], part["inherited"] = prev["target"], part["inherited"] + ["업종"]
        mw = METRIC_WORD.search(p)
        part["metric_word"] = mw.group(0) if mw else None
        if prev and not mw and prev.get("metric_word") and part["ref"] is None:  # '추이 보고 연동이랑 비교'는 앞 조각의 지표로 비교한다
            part["metric_word"], part["inherited"] = prev["metric_word"], part["inherited"] + ["지표"]
        # 종류는 물려받은 칸을 붙인 문장으로 읽는다. 앞 결과를 쓰는 조각은 동네 자리에 대표 동네를 넣어 읽는다(종류만 보려는 것)
        t = interpret(_text_for(part, "노형동" if part["ref"] is not None else None))["tuple"]
        part["type"], part["expect"] = t.get("type"), t.get("expect")
        if not dongs and part["ref"] is None and RANK_CUE.search(p) and part["type"] != "T3":  # '1위·가장 ~ 동네'는 순위 질문이다
            part["type"], part["force"] = "T3", True
        if part["type"] == "T2" and len(part["dongs"]) == 1 and prev and prev["dongs"] and prev["dongs"][0] not in part["dongs"]:
            part["dongs"], part["inherited"] = [prev["dongs"][0]] + part["dongs"], part["inherited"] + ["비교 동네"]
        parts.append(part)
    return parts


LOW = re.compile(r"적은|낮은|작은|덜|최하|꼴찌")


def top_dong(out, exclude=(), text=""):
    """앞 조각 답에서 뒤 조각이 쓸 동네와 동률 여부. 순위(T3)는 계산값(지도 값)에서 고른다(결론 문장 의존 제거, Gemini 054 지적).
    비슷한 동네(T9)·이례 변화(T15)는 답의 result_dongs(계산 결과). 그 밖(조건 탐색 등)만 결론 문장에서 처음 나온 동네."""
    t = ((out or {}).get("tuple") or {}).get("type")
    vals = next((v.get("values") for v in ((out or {}).get("answer") or {}).get("views") or [] if v.get("kind") == "map" and v.get("values")), None)
    if t == "T3" and vals:
        vals = {k: v for k, v in vals.items() if k in Q.DONGS and k not in exclude and v is not None}
        if vals:
            best = (min if LOW.search(text or "") else max)(vals.values())
            top = sorted(k for k, v in vals.items() if v == best)
            return top[0], len(top) > 1
    rd = [d for d in (out or {}).get("result_dongs") or [] if d not in exclude]
    if rd:  # 비슷한 동네·이례 변화는 계산 결과의 동네 목록에서(결론 문장 의존 제거, 평가 2026-11-14 B6)
        return rd[0], False
    text_c = ((out or {}).get("card") or {}).get("conclusion") or ""
    found = []
    for k in sorted(Q.DONGS, key=len, reverse=True):
        i = text_c.find(k)
        if i >= 0 and k not in exclude:
            found.append((i, k))
    found.sort()
    if not found:
        return None, False
    tie = bool(re.search(r"1위\s*" + re.escape(found[0][1]) + r"\s*[·,와과]\s*", text_c))
    return found[0][1], tie


def _text_for(part, dong=None):
    p = part["text"]
    if dong:
        p = REF.sub(dong, p, count=1) if REF.search(p) else f"{dong} {p}"
    add = []
    if "동네" in part["inherited"]:
        add += part["dongs"]
    elif "비교 동네" in part["inherited"]:
        add.append(part["dongs"][0])
    if "업종" in part["inherited"] and part["target"]:
        add.append(part["target"])
    if "지표" in part["inherited"] and part.get("metric_word"):
        add.append(part["metric_word"])
    return (" ".join(add) + " " + p).strip() if add else p


def answer(question, interpret, env=None):
    """나눌 질문이면 Agent 모양 결과(화면의 ResultView가 그린다)를, 아니면 None."""
    if not enabled():
        return None
    t0 = time.perf_counter()
    parts = plan(question, interpret)
    if len(parts) < 2:
        return None
    import result
    import techniques
    outs, lines, trace, topics = [], [], [], []
    for k, part in enumerate(parts):
        dong, note = None, None
        if part["ref"] is not None:
            src = outs[part["ref"]]
            if not src.get("ok"):
                note = f"{part['ref'] + 1}번 질문의 답이 없어 이 질문은 계산하지 않았어요."
            else:
                dong, tie = top_dong(src["out"], text=parts[part["ref"]]["text"])
                if not dong:
                    note = f"{part['ref'] + 1}번 답에서 동네를 찾지 못해 이 질문은 계산하지 않았어요."
                elif tie:
                    note = f"{part['ref'] + 1}번 답의 1위가 여럿이라 처음 나온 {dong} 기준으로 계산했어요."
        if note and not dong:
            outs.append({"ok": False, "out": None})
            lines.append(f"{k + 1}. {part['text']} → {note}")
            trace.append({"step": k + 1, "tool": "split", "name": f"{k + 1}번 질문 건너뜀", "by": "코드", "ok": False, "note": note, "args": part["text"], "sec": 0.0})
            continue
        text = _text_for(part, dong)
        t1 = time.perf_counter()
        tech = techniques.detect(text)
        if tech:
            import expert
            ok, rep, ans = expert._technique(text, {"technique": tech, "dongs": part["dongs"] or ([dong] if dong else []), "target": part["target"] or ""})
            card = (ans or {}).get("card") or {}
            out = {"status": "성공" if ok else "실패", "card": card}
            tool = "run_technique"
        else:
            env2 = dict(env or {}, agent_ok=False, _no_split=True)
            interp = interpret
            if part.get("force"):  # 순위 단서로 종류를 바로잡은 조각: 실행할 때도 순위(T3)로 읽는다
                def interp(q, _f=interpret):
                    it = _f(q)
                    return dict(it, tuple=dict(it["tuple"], type="T3", expect="답함"), card=qparse.card(dict(it["tuple"], type="T3", expect="답함")))
            out = result.respond(text, env2, llm_on=False, interpret=interp)
            pre = (out.get("choose") or {}).get("preset") or {}
            if out.get("status") == "선택필요" and pre.get("topic") and not G.missing(pre):
                # 혼자 묻는 질문이면 고르게 하지만, 나눈 조각에서는 고를 화면이 없다. 읽은 뜻대로 계산하고 확실하지 않다고 밝힌다
                out = result.respond(text, env2, llm_on=False, slots=pre, path="질문 나누기(확신 낮음)")
                note = (note + " " if note else "") + f"확실하지 않아 '{G.sentence(pre)}'(으)로 읽고 계산했어요."
            card = out.get("card") or {}
            ok = out.get("status") not in ("범위밖", "선택필요", "되묻기") and bool(card.get("evidence"))
            tool = "answer_topic"
        outs.append({"ok": ok, "out": out})
        head = f"{k + 1}. {text}"
        if ok:
            lines.append(f"{head} → {card.get('conclusion') or ''}")
            lines += [f"   · {e['text']}" for e in (card.get("evidence") or [])[:2]]
            topics.append({"tuple": out.get("tuple"), "card": card, "question": text})
        else:
            why = card.get("conclusion") or ((out.get("choose") or {}).get("message")) or "답을 만들지 못했어요"
            lines.append(f"{head} → {why}")
        if note:
            lines.append(f"   · {note}")
        trace.append({"step": k + 1, "tool": tool, "name": f"{k + 1}번 질문 · " + ("통계 기법" if tool == "run_technique" else "일반 답"), "by": "코드(질문 나누기)",
                      "ok": ok, "note": note or "", "args": text, "sec": round(time.perf_counter() - t1, 1)})
    n_ok = sum(o["ok"] for o in outs)
    ag = {"status": "성공" if n_ok else "실패", "method": f"질문 나누기({len(parts)}개)", "lines": lines, "by": "프로그램(조각별 일반 답을 묶음)",
          "result": {"numbers": {}, "notes": [], "series": [], "tables": []}, "trace": trace, "topics": topics or None, "backend": "code",
          "plan": [f"{i + 1}. {p['text']}" + (f" (앞 {p['ref'] + 1}번 답의 동네를 씀)" if p["ref"] is not None else "")
                   + (f" (물려받음: {', '.join(p['inherited'])})" if p["inherited"] else "") for i, p in enumerate(parts)],
          "sec": round(time.perf_counter() - t0, 1)}
    if not n_ok:
        ag["error"] = "나눈 질문 어느 것도 답하지 못했어요."
    return ag
