"""실험 X1 학습 자료 생성: (질문 → 질문 Tuple JSON) 쌍.

- 유형 T1~T15 + 되묻기 + 범위 밖 템플릿 × 값 사전 조합 × 말투 변형으로 만든다.
- 산출: data/x1/train.jsonl, valid.jsonl(MLX-LM chat 형식), bank.jsonl(예시 질문 검색 A+B용 질문 은행 = train과 같은 질문).
- 시험 문항은 여기서 만들지 않는다. Gemini가 사전을 보지 않고 따로 쓴다(c2g 021).
실행: .venv/bin/python app/x1_data.py [--per-type 180]
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

OUT = Q.ROOT / "data" / "x1"
ENDS = ["알려줘", "알려 주세요", "궁금해", "어때?", "보여줘", "좀 봐줘", "어떻게 돼?", "알 수 있을까요?", "말해줘", "정리해줘"]
ALIAS_BY_DONG = {}
for a, d in Q.DONG_ALIAS.items():
    ALIAS_BY_DONG.setdefault(d, []).append(a)


def dong_word(r, d):
    opts = [d] * 3 + ALIAS_BY_DONG.get(d, [])
    return r.choice(opts)


def biz_word(r, b):
    return r.choice(Q.BIZ_ALIAS[b])


def cond_word(r, c):
    return r.choice(Q.COND_ALIAS.get(c, [c]))


def T(type_, **kw):
    t = Q.empty()
    t["type"] = type_
    t.update(kw)
    return t


def gen_one(r, typ):
    d = r.choice(Q.DONGS)
    d2 = r.choice([x for x in Q.DONGS if x != d])
    b = r.choice(Q.TARGETS_BIZ[:10])
    e = r.choice(ENDS)
    D, D2, B = dong_word(r, d), dong_word(r, d2), biz_word(r, b)
    if typ == "T1":
        k = r.randrange(4)
        if k == 0:
            return f"{D}에 {B} 몇 곳 있어? {e}", T("T1", metric=["점포수"], target=b, space=[d])
        if k == 1:
            return f"{D} {B} 많은 편이야?", T("T1", metric=["특화계수"], target=b, space=[d])
        if k == 2:
            return f"{D} 버스 하루에 몇 명 타? {e}", T("T1", metric=["버스일평균"], space=[d])
        return f"{D} 음식점 폐업률 {e}", T("T1", metric=["폐업률"], target="음식점", space=[d])
    if typ == "T2":
        m = r.choice([("점포수", "가게 수"), ("버스일평균", "버스 이용"), ("고령비중", "어르신 비율"), (None, "")])
        if m[0] is None:
            return f"{D}랑 {D2} 비교해줘", T("T2", space=[d, d2])
        return f"{D}하고 {D2} {m[1]} 비교 {e}", T("T2", metric=[m[0]], space=[d, d2])
    if typ == "T3":
        m = r.choice([("특화계수", f"{B} 비중이 높은"), ("버스일평균", "버스 이용이 많은"), ("청년비중", "젊은 사람 비율 높은"), ("고령비중", "어르신 많이 사는")])
        tgt = b if m[0] == "특화계수" else None
        return f"{m[1]} 동네 순위 {e}", T("T3", metric=[m[0]], target=tgt)
    if typ == "T4":
        y = r.choice(["최근3년", "최근5년"])
        w = {"최근3년": "최근 3년", "최근5년": "최근 5년"}[y]
        k = r.randrange(3)
        if k == 0:
            return f"{w} {D} {B} 개업 줄고 있어?", T("T4", metric=["개업수"], target=b, space=[d], time=y)
        if k == 1:
            return f"{D} {B} 문 닫는 집 {w} 동안 늘었어?", T("T4", metric=["폐업수"], target=b, space=[d], time=y)
        return f"{D} 버스 이용 {w} 어떻게 변했어?", T("T4", metric=["버스일평균"], space=[d], time=y)
    if typ == "T5":
        k = r.randrange(3)
        if k == 0:
            return f"{D} 사는 사람 연령대 구성 {e}", T("T5", metric=["거주연령구성"], space=[d], breakdown="연령대")
        if k == 1:
            return f"{D} 오가는 사람들 나이대가 어떻게 돼?", T("T5", metric=["방문연령구성"], space=[d], breakdown="연령대")
        return f"{D} 버스 타는 사람 중 어르신 비율 {e}", T("T5", metric=["경로비중"], target="어르신", space=[d], breakdown="이용자구분")
    if typ == "T6":
        c = r.choice(["비", "주말", "비", "여름", "강풍"])
        C = cond_word(r, c)
        if r.random() < 0.5:
            return f"{C} {D} 사람 많이 줄어?", T("T6", metric=["일평균방문"], space=[d], cond=[c])
        return f"{C} {D} 버스 이용은 {e}", T("T6", metric=["버스일평균"], space=[d], cond=[c])
    if typ == "T7":
        if r.random() < 0.6:
            ms = [("일평균방문", "유동인구", "사람 많이 다니는"), ("점포수", "가게 수", "가게 많은"), ("버스일평균", "버스 이용", "버스 많이 타는"),
                  ("고령비중", "어르신 비율", "어르신 많은"), ("청년비중", "청년 비율", "젊은 사람 많은"), ("폐업률", "폐업률", "폐업 많은"), ("개업수", "개업 수", "개업 많은")]
            a1, a2 = r.sample(ms, 2)
            form = r.choice([f"{a1[2]} 동네일수록 {a2[1]}도 높아?", f"{a1[1]}랑 {a2[1]} 사이에 관계 있어?", f"동네별 {a1[1]}와 {a2[1]} 상관관계 {e}",
                             f"{a1[2]} 곳이 {a2[1]}도 많은 편인지 {e}"])
            return form, T("T7", metric=[a1[0], a2[0]])
        pair = r.choice([(["일평균방문", "점포수"], "유동인구 많은 동네가 가게도 많아?"), (["버스일평균", "고령비중"], "어르신 많은 동네가 버스도 많이 타?"),
                         (["일평균방문", "매출"], "사람 많이 다니는 동네가 매출도 높아?"), (["청년비중", "개업수"], f"젊은 사람 많은 동네에 {B} 개업도 많아?")])
        return pair[1], T("T7", metric=pair[0], target=b if "개업수" in pair[0] else None)
    if typ == "T8":
        t = r.choice(["다음분기", "다음달"])
        w = {"다음분기": "다음 분기", "다음달": "다음 달"}[t]
        return f"{w} {D} 버스 이용 얼마나 될까?", T("T8", metric=["버스일평균"], space=[d], time=t)
    if typ == "T9":
        if r.random() < 0.5:
            return f"{D}랑 비슷한 동네 어디야?", T("T9", space=[d])
        return f"{D}는 어떤 유형 동네야? {e}", T("T9", space=[d])
    if typ == "T10":
        return f"{D} 생활 진단 {e}", T("T10", space=[d])
    if typ == "T11":
        s = r.choice(["와이파이", "날씨", "카드 매출", "버스 정류소", "유동인구 시간대", "쓰레기 배출", "교통량", "음식물쓰레기", "종량제 봉투", "버스 노선",
                      "도로 구간", "관광객 카드", "POS 매출", "격자 유동인구", "교통카드 승하차"])
        form = r.choice([f"센터에 {s} 자료 있어? 기간이랑 같이 {e}", f"{s} 데이터는 어디서 볼 수 있어?", f"빅데이터센터에서 {s} 관련 데이터 제공해?",
                         f"{s} 자료 몇 년부터 있어?", f"{s} 데이터 반출 가능해?", f"분석에 쓸 수 있는 {s} 데이터 목록 보여줘"])
        return form, T("T11", metric=["자료목록"])
    if typ == "T13":
        if r.random() < 0.5:
            return f"{D} {B} 손님 제일 많은 시간대가 언제야?", T("T13", metric=["시간대방문"], target=b, space=[d], breakdown="시간대")
        return f"{D} 버스 몇 시에 제일 붐벼?", T("T13", metric=["시간대버스"], space=[d], breakdown="시간대")
    if typ == "T14":
        return f"청년 비중 높고 {B} 폐업률 낮은 동네 찾아줘", T("T14", metric=["청년비중", "폐업률"], target=b)
    if typ == "T15":
        k = r.choice(["폐업수", "개업수", "버스일평균"])
        w = {"폐업수": "폐업", "개업수": "개업", "버스일평균": "버스 이용"}[k]
        tgt = None if k == "버스일평균" else b
        sub = "" if k == "버스일평균" else f"{B} "
        form = r.choice([f"올해 {sub}{w}이 갑자기 늘어난 동네 있어?", f"최근 {sub}{w} 급증한 곳 {e}", f"작년 대비 {sub}{w}이 확 줄어든 동네는?",
                         f"{sub}{w} 이상하게 튄 동네 경보 {e}", f"요즘 {sub}{w} 급감한 데 어디야?"])
        return form, T("T15", metric=[k], target=tgt, time="최근1년")
    raise ValueError(typ)


def gen_clarify(r):
    b = r.choice(Q.TARGETS_BIZ[:10])
    B = biz_word(r, b)
    k = r.randrange(6)
    if k == 3:
        return r.choice(["우리 동네 요즘 어때?", "여기 장사 잘 돼?", "동네 분위기 좀 알려줘", "이 동네 살기 괜찮아?"]), T("T10", expect="되묻기")
    if k == 4:
        return f"{B} 몇 개야?", T("T1", metric=["점포수"], target=b, expect="되묻기")
    if k == 5:
        return r.choice(["버스 많이 타?", "사람 많이 다녀?", "비 오면 손님 줄어?"]), T("T6" if "비" in B else "T1", expect="되묻기")
    if k == 0:
        return f"우리 동네 {B} 어때?", T("T1", target=b, expect="되묻기")
    if k == 1:
        return "동네 비교해줘", T("T2", expect="되묻기")
    return f"{B} 창업하려는데 어디가 좋아?", T("T14", target=b, expect="되묻기")


def gen_out(r):
    d = r.choice(Q.DONGS)
    D = dong_word(r, d)
    k = r.randrange(4)
    if k == 0:
        return f"{D} 상가 임대료 얼마야?", T("T12", space=[d], expect="범위밖")
    if k == 1:
        return f"지금 {D} 실시간으로 사람 많아?", T("T12", space=[d], time="지금", expect="범위밖")
    if k == 2:
        o = r.choice(Q.TARGETS_OUT)
        return f"{D} {o} 몇 개야?", T("T12", target=o, space=[d], expect="범위밖")
    return f"{D} 아파트 값 오를까?", T("T12", space=[d], expect="범위밖")


def to_chat(q, t):
    return {"messages": [{"role": "system", "content": Q.SCHEMA_PROMPT}, {"role": "user", "content": q},
                         {"role": "assistant", "content": json.dumps(t, ensure_ascii=False, separators=(",", ":"))}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=180)
    a = ap.parse_args()
    r = random.Random(20261111)
    rows, seen = [], set()
    types = [t for t in Q.TYPES if t != "T12"]
    for typ in types:
        n, tries = 0, 0
        while n < a.per_type and tries < a.per_type * 50:  # 템플릿이 적은 유형은 가능한 만큼만 만든다
            tries += 1
            q, t = gen_one(r, typ)
            if r.random() < 0.5 and not q.endswith(("?", "요")):
                q = f"{q} {r.choice(ENDS)}" if not any(q.endswith(x) for x in ENDS) else q
            if q not in seen:
                seen.add(q)
                rows.append((q, t))
                n += 1
    for g in [gen_clarify, gen_out]:
        n, tries = 0, 0
        while n < a.per_type and tries < a.per_type * 20:
            tries += 1
            q, t = g(r)
            if q not in seen:
                seen.add(q)
                rows.append((q, t))
                n += 1
    gold = OUT / "test_gold.jsonl"
    if gold.exists():  # 시험 문항과 같은 문장은 학습에서 뺀다
        test_q = {json.loads(x)["q"] for x in gold.read_text(encoding="utf-8").splitlines() if x.strip()}
        rows = [(q, t) for q, t in rows if q not in test_q]
    bad = [q for q, t in rows if Q.validate(t)]
    assert not bad, bad[:3]
    r.shuffle(rows)
    nv = max(100, len(rows) // 10)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "valid.jsonl", "w", encoding="utf-8") as f:
        for q, t in rows[:nv]:
            f.write(json.dumps(to_chat(q, t), ensure_ascii=False) + "\n")
    with open(OUT / "train.jsonl", "w", encoding="utf-8") as f, open(OUT / "bank.jsonl", "w", encoding="utf-8") as g:
        for q, t in rows[nv:]:
            f.write(json.dumps(to_chat(q, t), ensure_ascii=False) + "\n")
            g.write(json.dumps({"q": q, "tuple": t}, ensure_ascii=False) + "\n")
    from collections import Counter
    print({"train": len(rows) - nv, "valid": nv, "by_type": dict(Counter(t["type"] + ("/" + t["expect"] if t["expect"] != "답함" else "") for _, t in rows))})


if __name__ == "__main__":
    main()
