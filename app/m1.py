"""W2 Main Layer M1 질의 해석 (2026-11-11 구현).

경로(실험 X1 블라인드 024·025 결과로 선택, docs/조사/11_X1_질의파악_실험.md)
  기본  B3: 문장 임베딩(Ollama bge-m3, CPU) + 분류기(유형·판단). 동네·업종·조건 같은 값 칸은 사전 해석기(qparse, A2′).
  대체  A2′: 임베딩을 쓸 수 없으면(Ollama 없음·실패) 사전 규칙만으로 해석한다.
- 분류기는 joblib 대신 JSON(계수·절편)으로 저장하고 numpy로 계산한다(관문 v2 저장 원칙, scikit-learn 버전 의존 제거). 파일: models/m1_intent.json
- 출력: 질문 Tuple + 의도 확인 카드 + 유형 확신도 + 쓴 경로 + 처리 시간.
- 확신도가 낮으면(기본 0.5 미만, 024에서 유형 26/39 정답) 카드에 "확인 필요"를 붙인다. 기준값은 025 재확인 대상.
학습·저장: .venv/bin/python app/m1.py --train   /  해석: .venv/bin/python app/m1.py "질문"
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402

MODEL = Q.ROOT / "models" / "m1_intent.json"
LOW_CONF = 0.5


def train_and_save():
    from sklearn import __version__ as skv
    from sklearn.linear_model import LogisticRegression
    import x1_embed as XE
    rows = XE.training_rows()
    X = XE.embed([q for q, _, _ in rows])
    out = {"embed_model": XE.MODEL, "n_train": len(rows), "sources": sorted({s for *_, s in rows}), "trained_at": time.strftime("%Y-%m-%d %H:%M"),
           "sklearn": skv, "low_conf": LOW_CONF, "heads": {}}
    for head in ["type", "expect"]:
        y = [t[head] for _, t, _ in rows]
        m = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced").fit(X, y)
        out["heads"][head] = {"classes": list(m.classes_), "coef": m.coef_.round(6).tolist(), "intercept": m.intercept_.round(6).tolist()}
    MODEL.parent.mkdir(exist_ok=True)
    MODEL.write_text(json.dumps(out), encoding="utf-8")
    return {k: v for k, v in out.items() if k != "heads"}


def _softmax(z):
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


class M1:
    def __init__(self, path=MODEL):
        self.ok = path.exists()
        if self.ok:
            m = json.loads(path.read_text(encoding="utf-8"))
            self.heads = {h: (v["classes"], np.array(v["coef"]), np.array(v["intercept"])) for h, v in m["heads"].items()}
            self.embed_model = m["embed_model"]
            self.low_conf = m.get("low_conf", LOW_CONF)

    def _embed(self, q):
        import requests
        r = requests.post("http://localhost:11434/api/embed", json={"model": self.embed_model, "input": [q], "options": {"num_gpu": 0}}, timeout=10)
        return np.array(r.json()["embeddings"][0], dtype=np.float64)

    def _predict(self, head, v):
        classes, W, b = self.heads[head]
        with np.errstate(all="ignore"):  # numpy 2.0 + Accelerate의 거짓 경고(값에는 영향 없음, 관문 실험에서 확인)
            z = W @ v + b
        p = _softmax(z) if len(classes) > 2 else None
        if p is None:  # 이진 분류(로지스틱)
            s = 1 / (1 + np.exp(-z[0]))
            p = np.array([1 - s, s])
        i = int(p.argmax())
        return classes[i], float(p[i])

    def interpret(self, q):
        t0 = time.perf_counter()
        base = qparse.parse(q)
        t = dict(base)
        path, conf = "A2′(사전 규칙)", None
        if self.ok:
            try:
                v = self._embed(q)
                t["type"], conf = self._predict("type", v)
                t["expect"], _ = self._predict("expect", v)
                path = "B3(임베딩 + 분류기)"
                if t["expect"] == "범위밖" and base["expect"] == "답함" and {"매출성장", "시장추이", "업종비교"} & set(base["metric"]):
                    # v3 묶음 지표가 사전에 명시적으로 잡히면 사전 해석을 따른다(예문이 적어 분류기가 '요즘 ~ 어디야'를 범위 밖으로 봄, 2026-11-11)
                    t["type"], t["expect"] = base["type"], "답함"
                    t["_why"] = list(base.get("_why") or []) + ["v3 묶음 지표는 사전 해석 우선"]
                elif t["expect"] == "범위밖":
                    t["type"] = "T12"
                elif base["_amb"] and not base["space"]:
                    t["expect"] = "되묻기"
                elif t["type"] in qparse.NEED_DONG and not base["space"] and t["expect"] == "답함" and not {"시장추이", "매출성장"} & set(t.get("metric") or []):
                    t["expect"] = "되묻기"
            except Exception as e:  # Ollama가 없거나 실패하면 규칙 경로로 대체
                t["_fallback_reason"] = type(e).__name__
        card = qparse.card(t)
        low = conf is not None and conf < self.low_conf and t["expect"] == "답함"
        if low:
            card["text"] += " (확인이 필요해요)"
        return {"tuple": {k: v for k, v in t.items() if not k.startswith("_")}, "card": card, "confidence": conf, "needs_confirm": low or t["expect"] != "답함", "rule_type": base["type"],
                "path": path, "why": t.get("_why", []), "sec": round(time.perf_counter() - t0, 4)}


if __name__ == "__main__":
    if "--train" in sys.argv:
        print(train_and_save())
    else:
        m = M1()
        for q in sys.argv[1:]:
            print(json.dumps(m.interpret(q), ensure_ascii=False))
