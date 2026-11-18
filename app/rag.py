"""질문 기록 찾기(RAG, 마스터 설계 2026-11-15): 새 질문과 비슷한 과거 질문이 어떤 분석을 받았는지 찾아, 1차 질의 분석과 크게 어긋나면 모델에 다시 판단을 요청한다.

- 쓰임: 답을 만들지 않는다. 질의 분석(질문 종류 T1~T15, 분석 담당의 기법 고르기)을 점검하는 데만 쓴다. 최종 판단은 모델이 하고 코드는 결과를 바꾸지 않는다.
- 기록(지금): 학습·조정용 문장을 '과거 질문'으로 쓴다. 판정 문항(data/eval·data/x1/test_*)과 같은 문장은 넣지 않는다(같은 문장이 자기를 찾으면 측정이 부풀려진다).
  · 종류 기록: 질문 해석 학습 문장(data/x1/*_train.jsonl, 템플릿 포함) → 질문 종류
  · 기법 기록: 조정용 문항(data/eval/tech_dev_*.jsonl) → 기법 13종 또는 general
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


# 낱말 검색(BM25) 혼합(2026-11-16 문제 기록 28번): 이웃을 고를 때만 '벡터 유사도 + 가중 × BM25(글자 두 개 단위, 최댓값으로 나눔)'를 쓴다.
# 투표 가중과 SIM 기준은 벡터 유사도 그대로. 가중은 기록 안 leave-one-out으로 정함(기법 기록 786문장: 이웃 투표가 자기 분석과 같음
# 0 → 71.4%, 0.3 → 74.0%, 0.5 → 74.6%, 0.7 → 76.3%, 1.0 → 76.8%. 거짓 '어긋남'이 0일 때(43) 이하인 것 가운데 가장 높은 0.7).
BM25_W = {"tech": 0.7}
_bm = {}


def _grams(q):
    t = re.sub(r"\s+", "", norm(q))
    return [t[i:i + 2] for i in range(len(t) - 1)]


def _bm25(name, lib, q, k1=1.2, b=0.75):
    """기록 문장마다 질문 q의 BM25 점수(최댓값 1로 나눔)."""
    if name not in _bm:
        import math
        from collections import Counter
        docs = [Counter(_grams(x)) for x in lib["q"]]
        avg = float(np.mean([sum(d.values()) for d in docs])) or 1.0
        df = Counter(g for d in docs for g in d)
        idf = {g: math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for g, n in df.items()}
        post = {}
        for i, d in enumerate(docs):
            ln = sum(d.values())
            for g, tf in d.items():
                post.setdefault(g, []).append((i, idf[g] * tf * (k1 + 1) / (tf + k1 * (1 - b + b * ln / avg))))
        _bm[name] = post
    sc = np.zeros(len(lib["q"]), dtype=np.float32)
    for g in set(_grams(q)):
        for i, w in _bm[name].get(g, ()):
            sc[i] += w
    return sc / (sc.max() + 1e-9)


def neighbors(vec, name, k=None, skip=None, q=None):
    """vec와 비슷한 과거 질문 k개: [(문장, 분석, 유사도)]. skip: 빼고 찾을 기록 번호(조정용 leave-one-out). q: 질문 문장(있으면 BM25 혼합)."""
    lib = load().get(name)
    if not lib:
        return []
    k = k or lib["param"].get("k", 5)
    v = np.asarray(vec, dtype=np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    s = lib["vec"] @ v
    sim = s.copy()
    if q and BM25_W.get(name):
        s = s + BM25_W[name] * _bm25(name, lib, q)
    if skip is not None:
        s[skip] = -1
    idx = np.argsort(-s)[:k]
    return [(lib["q"][i], lib["label"][i], float(sim[i])) for i in idx]


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


def check(vec, first, name, skip=None, group=None, q=None):
    """1차 분석(first)과 비슷한 과거 질문의 분석을 견준다. group: 분석 이름을 묶는 함수(예: 기법이 아니면 모두 general)."""
    lib = load().get(name)
    if not lib or vec is None:
        return {"used": False}
    p = lib["param"]
    nb = neighbors(vec, name, p.get("k", 5), skip, q)
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

