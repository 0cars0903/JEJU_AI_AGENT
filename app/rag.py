"""질문 기록 찾기(RAG, 마스터 설계 2026-11-15): 새 질문과 비슷한 과거 질문이 어떤 분석을 받았는지 찾아, 1차 질의 분석과 크게 어긋나면 모델에 다시 판단을 요청한다.

- 쓰임: 답을 만들지 않는다. 질의 분석(질문 종류 T1~T15, 분석 담당의 기법 고르기)을 점검하는 데만 쓴다. 최종 판단은 모델이 하고 코드는 결과를 바꾸지 않는다.
- 기록(지금): 학습·조정용 문장을 '과거 질문'으로 쓴다. 판정 문항(data/eval·data/x1/test_*)과 같은 문장은 넣지 않는다(같은 문장이 자기를 찾으면 측정이 부풀려진다).
  · 종류 기록: 질문 해석 학습 문장(data/x1/*_train.jsonl, 템플릿 포함) → 질문 종류
  · 기법 기록: 조정용 문항(data/eval/tech_dev_*.jsonl) → 기법 12종 또는 general
- 운영(기획): 센터에서 질문이 쌓이면 사람이 확인한 질문(피드백 [맞아요]·고친 해석)이 기록에 더해진다(tools/rag_build.py로 다시 만듦).
- 색인: models/rag_index.npz(벡터, float16) + models/rag_rows.json(문장·분석). bge-m3 임베딩(질문 해석과 같은 벡터를 다시 쓴다).
- 어긋남 판정: 유사도 상위 K개 가운데 유사도 SIM 이상인 것만 투표(유사도 가중). 가장 많은 분석이 1차 분석과 다르고 그 몫이 SHARE 이상이면 '어긋남'.
  기준값(K·SIM·SHARE)은 기록 안에서 한 문장씩 빼고 찾는 방식(leave-one-out)으로만 정한다(tools/rag_build.py --tune). 판정 문항은 쓰지 않는다.
"""
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "models" / "rag_index.npz"
ROWS = ROOT / "models" / "rag_rows.json"
_lib = None


def norm(q):
    return re.sub(r"\s+", " ", re.sub(r"[?!.,~]", "", q or "")).strip()


def load():
    global _lib
    if _lib is None:
        if not (INDEX.exists() and ROWS.exists()):
            _lib = {}
            return _lib
        z = np.load(INDEX)
        meta = json.loads(ROWS.read_text(encoding="utf-8"))
        _lib = {}
        for name, m in meta["libs"].items():
            if name == "untyped":  # 재학습 바탕(종류 없는 되묻기 문장)은 질문 기록 대조에 쓰지 않는다
                continue
            v = z[name].astype(np.float32)
            v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
            _lib[name] = {"vec": v, "q": m["q"], "label": m["label"], "param": meta["param"].get(name, {})}
    return _lib


def neighbors(vec, name, k=None, skip=None):
    """vec와 비슷한 과거 질문 k개: [(문장, 분석, 유사도)]. skip: 빼고 찾을 기록 번호(조정용 leave-one-out)."""
    lib = load().get(name)
    if not lib:
        return []
    k = k or lib["param"].get("k", 5)
    v = np.asarray(vec, dtype=np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    s = lib["vec"] @ v
    if skip is not None:
        s[skip] = -1
    idx = np.argsort(-s)[:k]
    return [(lib["q"][i], lib["label"][i], float(s[i])) for i in idx]


def vote(nb, sim):
    """유사도 SIM 이상인 이웃의 유사도 가중 투표: (가장 많은 분석, 몫, 가장 높은 유사도)."""
    use = [(lab, s) for _, lab, s in nb if s >= sim]
    if not use:
        return None, 0.0, (nb[0][2] if nb else 0.0)
    w = {}
    for lab, s in use:
        w[lab] = w.get(lab, 0.0) + s
    top = max(w, key=w.get)
    return top, w[top] / sum(w.values()), nb[0][2]


def check(vec, first, name, skip=None, group=None):
    """1차 분석(first)과 비슷한 과거 질문의 분석을 견준다. group: 분석 이름을 묶는 함수(예: 기법이 아니면 모두 general)."""
    lib = load().get(name)
    if not lib or vec is None:
        return {"used": False}
    p = lib["param"]
    nb = neighbors(vec, name, p.get("k", 5), skip)
    g = group or (lambda x: x)
    nb = [(q, g(lab), s) for q, lab, s in nb]
    top, share, best = vote(nb, p.get("sim", 0.8))
    differ = top is not None and top != g(first) and share >= p.get("share", 0.6)
    return {"used": True, "first": first, "vote": top, "share": round(share, 3), "best_sim": round(best, 3), "differ": differ,
            "examples": [{"q": q, "label": lab, "sim": round(s, 3)} for q, lab, s in nb[:3]]}


def note(chk, describe):
    """모델에 다시 판단을 요청할 때 붙이는 메모: 비슷한 과거 질문과 그 분석."""
    ex = "\n".join(f"- '{e['q']}' → {describe(e['label'])}" for e in chk["examples"])
    return (f"(검사 메모: 비슷한 과거 질문은 다음처럼 분석했어요.\n{ex}\n"
            f"처음 판단({describe(chk['first'])})과 달라요. 질문의 뜻을 다시 보고 맞는 것을 고르세요. 과거 질문과 뜻이 다르면 처음 판단을 유지해도 돼요.)")


TYPE_DESC = {"T1": "현황: 한 동네(또는 제주 전체)의 지금 값(가게 수·매출·방문 등)", "T2": "비교: 두 동네 이상을 견줌",
             "T3": "순위: 여러 동네 가운데 가장 많은·적은 곳", "T4": "추이: 시간에 따라 늘었는지 줄었는지",
             "T5": "구성: 비중·나눠 보기(연령·업종·관광객 비중)", "T6": "조건 효과: 비·주말·계절 같은 조건에 따라 달라지는지",
             "T7": "관계: 두 지표가 같이 움직이는지", "T8": "예상: 다음 주·다음 달 값", "T9": "비슷한 동네 찾기",
             "T10": "종합 진단: 동네 상권 전체를 진단하거나 창업 판단 재료", "T11": "자료 찾기: 어떤 자료가 있는지",
             "T12": "범위 밖: 지금 자료로 답할 수 없는 질문", "T13": "시간대 패턴: 몇 시에 많은지",
             "T14": "조건 탐색: 여러 조건을 함께 만족하는 동네 찾기", "T15": "이례 변화: 올해 평소와 다르게 크게 변한 것"}
S_REJUDGE = ("너는 제주 동네 질문의 종류를 고르는 담당자다. 질문 하나와 후보 종류 두 개(A, B), 비슷한 과거 질문의 예시를 받는다. "
             "질문이 실제로 묻는 것에 맞는 후보 하나를 고른다. 과거 질문은 참고일 뿐이고, 뜻이 다르면 따르지 않는다. 출력은 JSON 하나.")
F_REJUDGE = {"type": "object", "properties": {"choice": {"type": "string", "enum": ["A", "B"]}, "reason": {"type": "string"}}, "required": ["choice"]}


def rejudge_type(question, chk, chat=None):
    """질문 종류가 어긋나면 모델에 두 후보 중 하나를 고르게 한다. 모델이 없거나 실패하면 None(처음 판단 유지)."""
    import llm
    import expert
    a, b = chk["first"], chk["vote"]
    ex = "\n".join(f"- '{e['q']}' → {e['label']}({TYPE_DESC.get(e['label'], '')})" for e in chk["examples"])
    user = f"질문: {question}\nA: {a}({TYPE_DESC.get(a, '')})\nB: {b}({TYPE_DESC.get(b, '')})\n비슷한 과거 질문:\n{ex}"
    msgs = [{"role": "system", "content": S_REJUDGE}, {"role": "user", "content": user}]
    try:
        m = (chat or (lambda ms: llm.chat(expert.AGENT_MODEL, ms, [], name="ollama", max_tokens=120, fmt=F_REJUDGE)))(msgs)["message"]
        c = json.loads(m.get("content") or "{}").get("choice")
    except Exception:
        return None
    return {"A": a, "B": b}.get(c)
