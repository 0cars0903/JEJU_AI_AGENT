"""B3: 문장 임베딩 + 분류기 (2026-11-11 사용자 승인 오전 진행안).

- 임베딩: Ollama bge-m3(다국어, CPU 모드 num_gpu 0). 새 pip 의존성 없음(requests·scikit-learn).
- 분류기 2개: 유형(T1~T15) · 판단(답함/되묻기/범위밖). 로지스틱 회귀(scikit-learn).
- 동네·업종·조건 같은 값 칸은 사전 해석기(qparse, A2′)로 채운다. 모호한 지명의 되묻기는 사전 판단을 따른다.
- 학습 자료: 템플릿 자료(data/x1/train.jsonl) + B1 다양 자료(data/x1/b1_train.jsonl, 있으면). 시험 문항(021~024)은 쓰지 않는다.
- 임베딩 캐시: data/x1/emb_cache.json (문장 → 벡터)
"""
import hashlib
import json
import sys
from pathlib import Path

import os

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402

X1 = Q.ROOT / "data" / "x1"
CACHE = X1 / "emb_cache.json"
MODEL = "bge-m3"
EMBED_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat").replace("/api/chat", "/api/embed")  # 대화 모델과 같은 Ollama(기본 11434)
_cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def _key(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def embed(texts, batch=32):
    todo = [t for t in texts if _key(t) not in _cache]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        r = llm.http().post(EMBED_URL, headers=llm.ollama_headers(), json={"model": MODEL, "input": chunk, "options": {"num_gpu": 0}}, timeout=600)
        for t, v in zip(chunk, r.json()["embeddings"]):
            _cache[_key(t)] = v
    if todo:
        CACHE.write_text(json.dumps(_cache), encoding="utf-8")
    return np.array([_cache[_key(t)] for t in texts], dtype=np.float32)


def embed_live(q):
    """서비스와 같은 조건: 캐시 없이 한 문장을 바로 임베딩한다(시간 측정용)."""
    r = llm.http().post(EMBED_URL, headers=llm.ollama_headers(), json={"model": MODEL, "input": [q], "options": {"num_gpu": 0}}, timeout=120)
    return np.array(r.json()["embeddings"], dtype=np.float32)


def training_rows():
    rows = []
    for line in (X1 / "train.jsonl").read_text(encoding="utf-8").splitlines():
        m = json.loads(line)["messages"]
        rows.append((m[1]["content"], json.loads(m[2]["content"]), "template"))
    for name, tag in [("b1_train.jsonl", "b1"), ("b1b_train.jsonl", "b1b"), ("v3_train.jsonl", "v3"), ("human_train.jsonl", "human"), ("fragment_train.jsonl", "fragment"), ("feedback_train.jsonl", "feedback")]:  # feedback: 사람이 확인·고친 해석(tools/feedback_to_train.py)
        # B1(짧은 말투) + B1b(긴 문장) + v3 카드 매출 예문 + human(사람 말투 정답 1,000문항, Gemini 045·046, 2026-11-14. 되묻기는 type 없음)
        # + fragment(질문 나누기 조각 말투 600, Gemini 051, 평가용 050과 겹침 0. 평가용 300: 246→248, 050 조각 종류 270→274/300)
        f = X1 / name
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    rows.append((r["q"], r["tuple"], tag))
    return rows


class EmbedParser:
    def __init__(self, use=("template", "b1", "b1b", "v3", "human", "feedback")):
        from sklearn.linear_model import LogisticRegression
        rows = [r for r in training_rows() if r[2] in use]
        X = embed([q for q, _, _ in rows])
        ti = [i for i, (_, t, _) in enumerate(rows) if t.get("type")]  # 되묻기 사람 문항은 type이 없어 type 분류기에서 뺀다
        ex = [t["expect"] for _, t, _ in rows]
        self.type_clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced").fit(X[ti], [rows[i][1]["type"] for i in ti])
        self.exp_clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced").fit(X, ex)
        self.n = len(rows)

    def parse(self, q):
        base = qparse.parse(q)
        v = embed_live(q)
        t = dict(base)
        t["type"] = self.type_clf.predict(v)[0]
        t["expect"] = self.exp_clf.predict(v)[0]
        if t["expect"] == "범위밖":
            t["type"] = "T12"
        elif base["_amb"] and not base["space"]:
            t["expect"] = "되묻기"
        elif t["type"] in qparse.NEED_DONG and not base["space"] and t["expect"] == "답함":
            t["expect"] = "되묻기"
        t["_type_proba"] = float(self.type_clf.predict_proba(v).max())
        return t
