"""종류 기록(RAG)의 기준값을 '분류기와 어긋났을 때 이웃이 맞는 비율'로 다시 잰다(조정용, 판정 문항 쓰지 않음).
기록 5,980문장을 5등분: 4묶음으로 분류기를 배우고 이웃 기록을 만들어 남은 1묶음을 판정한다(교차 검증). 사용: python tools/rag_cv_type.py
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import rag  # noqa: E402

z = np.load(rag.INDEX)
meta = json.loads(rag.ROWS.read_text(encoding="utf-8"))
X = z["type"].astype(np.float32)
y = np.array(meta["libs"]["type"]["label"])
Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
rng = np.random.default_rng(0)
fold = rng.integers(0, 5, len(y))
pred = np.empty(len(y), dtype=object)
nb_lab, nb_sim = [], []
idx_all = np.arange(len(y))
NB = np.zeros((len(y), 7), dtype=int)
NS = np.zeros((len(y), 7))
for f in range(5):
    tr, te = idx_all[fold != f], idx_all[fold == f]
    m = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced").fit(X[tr], y[tr])
    pred[te] = m.predict(X[te])
    S = Xn[te] @ Xn[tr].T
    o = np.argsort(-S, axis=1)[:, :7]
    NB[te] = tr[o]
    NS[te] = np.take_along_axis(S, o, axis=1)
acc = float((pred == y).mean())
res = []
for k, sim, share in itertools.product((3, 5, 7), (0.6, 0.7, 0.75, 0.8, 0.85, 0.9), (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)):
    diff = vote_ok = clf_ok = 0
    for i in range(len(y)):
        top, sh, _ = rag.vote([(None, y[j], s) for j, s in zip(NB[i, :k], NS[i, :k])], sim)
        if top is not None and sh >= share and top != pred[i]:
            diff += 1
            vote_ok += top == y[i]
            clf_ok += pred[i] == y[i]
    res.append({"k": k, "sim": sim, "share": share, "differ": diff, "vote_right": vote_ok, "clf_right": clf_ok})
res.sort(key=lambda r: -(r["vote_right"] - r["clf_right"]))
print(json.dumps({"n": len(y), "cv_classifier_acc": round(acc, 3), "top": res[:8]}, ensure_ascii=False))
