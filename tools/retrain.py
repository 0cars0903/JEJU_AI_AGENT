"""질문 해석 분류기 재학습(센터 PC용, 2026-11-15). 사용: python tools/retrain.py   (또는 scripts/retrain_windows.bat · retrain_mac.sh)

순서
1. 화면의 [맞아요]·[조건 바꾸기] 기록(feedback.jsonl)을 학습 자료로 바꾼다(tools/feedback_to_train.py, 판정 문항과 같은 문장은 뺌).
2. 기존 학습 문장의 벡터는 질문 기록 색인(models/rag_index.npz의 종류 기록 5,980문장)을 그대로 쓰고, 피드백 문장만 새로 임베딩한다.
   같은 질문이 기존 문장에 있으면 피드백(사람이 확인·고친 해석)이 이긴다.
3. '종류' 판단(T1~T15)은 종류가 있는 기록으로, '답할지'(답함·되묻기·범위 밖) 판단은 모든 기록으로 다시 학습한다.
   '답할지' 기록은 범위 밖 안내의 [맞아요]·[답할 수 있는 질문이에요]와 되묻기 화면에서 동네·업종을 고른 기록에서 온다.
4. 판정용 300문항(data/x1/test_std150·test_std150d)으로 지금 모델과 새 모델을 채점한다. 새 모델이 같거나 높을 때만 바꾸고,
   지금 모델은 models/m1_intent.prev.json으로 남긴다. 낮으면 바꾸지 않는다(자동 되돌림).
5. 끝에 동네·업종 낱말 후보 표(lexicon_candidates.csv)를 만든다(tools/lexicon_candidates.py). 채택은 담당자가 한다.
필요: Ollama bge-m3(OLLAMA_URL). 결과는 실행 창에 출력하고 models/retrain_log.jsonl에 한 줄씩 남긴다.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import m1  # noqa: E402
import rag  # noqa: E402

FEEDBACK_TRAIN = ROOT / "data" / "x1" / "feedback_train.jsonl"
GOLD = [ROOT / "data" / "x1" / n for n in ("test_std150_gold.jsonl", "test_std150d_gold.jsonl")]
CAND = ROOT / "models" / "m1_intent.candidate.json"
PREV = ROOT / "models" / "m1_intent.prev.json"
LOG = ROOT / "models" / "retrain_log.jsonl"


def base_rows():
    """기존 학습 문장의 벡터·종류·답할지(질문 기록 색인). 종류 없는 되묻기 문장(untyped)은 답할지 학습에만 쓴다."""
    z = np.load(rag.INDEX)
    meta = json.loads(rag.ROWS.read_text(encoding="utf-8"))
    lib, un = meta["libs"]["type"], meta["libs"].get("untyped", {"q": [], "label": []})
    X = z["type"].astype(np.float64)
    XU = z["untyped"].astype(np.float64) if "untyped" in z.files else np.zeros((0, X.shape[1]))
    return {"X": X, "type": list(lib["label"]), "expect": list(lib.get("expect") or []), "q": list(lib["q"]),
            "XU": XU, "qU": list(un["q"]), "expectU": list(un["label"])}


def feedback_rows():
    """[(질문, 종류 또는 None, 답할지)]. 종류가 없는 기록은 범위 밖·되묻기 화면에서 남긴 '답할지' 신호다."""
    if not FEEDBACK_TRAIN.exists():
        return []
    rows = [json.loads(l) for l in FEEDBACK_TRAIN.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [(r["q"], (r.get("tuple") or {}).get("type"), (r.get("tuple") or {}).get("expect", "답함")) for r in rows if r.get("q")]


def fit_head(X, y):
    from sklearn.linear_model import LogisticRegression
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)  # numpy + Accelerate의 거짓 경고(m1._predict와 같은 사정)
    m = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced").fit(X, y)  # m1.train_and_save와 같은 설정
    return {"classes": list(m.classes_), "coef": m.coef_.round(6).tolist(), "intercept": m.intercept_.round(6).tolist()}


def build(embed, fb):
    """새 모델(dict). embed: 문장 → 벡터. fb: [(질문, 종류 또는 None, 답할지)].
    같은 질문이 기존 문장에 있으면 피드백이 이긴다. 종류 판단은 종류가 있는 기록으로, 답할지 판단은 모든 기록으로 다시 학습한다."""
    B = base_rows()
    if len(fb) and len(fb[0]) == 2:  # 예전 형식 [(질문, 종류)]
        fb = [(q, t, "답함") for q, t in fb]
    over = {rag.norm(q) for q, _, _ in fb}
    keep = [i for i, q in enumerate(B["q"]) if rag.norm(q) not in over]
    keepU = [i for i, q in enumerate(B["qU"]) if rag.norm(q) not in over]
    F = np.array([embed(q) for q, _, _ in fb], dtype=np.float64).reshape(len(fb), B["X"].shape[1])
    ft = [i for i, (_, t, _) in enumerate(fb) if t]
    Xt = np.vstack([B["X"][keep], F[ft]])
    yt = [B["type"][i] for i in keep] + [fb[i][1] for i in ft]
    cur = json.loads(m1.MODEL.read_text(encoding="utf-8"))
    heads = dict(cur["heads"], type=fit_head(Xt, yt))
    if B["expect"]:  # 색인에 답할지 정답이 있으면(2026-11-15 이후 색인) 답할지 판단도 다시 학습
        Xe = np.vstack([B["X"][keep], B["XU"][keepU], F])
        ye = [B["expect"][i] for i in keep] + [B["expectU"][i] for i in keepU] + [e for _, _, e in fb]
        heads["expect"] = fit_head(Xe, ye)
    n_exp = sum(1 for _, t, e in fb if not t or e != "답함")
    return dict(cur, heads=heads, trained_at=time.strftime("%Y-%m-%d %H:%M"),
                retrain={"base": len(keep) + len(keepU), "feedback": len(fb), "feedback_expect_only": n_exp,
                         "how": "질문 기록 색인 벡터 + 피드백, 종류·답할지 판단 재학습"})


def score(path, vec):
    """판정용 300문항 핵심 정답 수(질문 해석 전체 규칙 포함). vec: 질문 → 벡터(두 모델이 같은 벡터로 채점되게)."""
    import x1_eval as X1
    gold = [json.loads(l) for p in GOLD for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    M = m1.M1(path, rag_on=False)
    M._embed = vec
    return sum(X1.score(M.interpret(g["q"])["tuple"], g)["core"] for g in gold), len(gold)


def decide(old, new):
    """새 모델을 쓸지: 판정 점수가 같거나 높을 때만."""
    return new >= old


def main():
    import envfile
    envfile.load()  # .env의 JEJU_WRITE_DIR·OLLAMA_URL을 실행 스크립트와 같게 읽는다
    import feedback_to_train
    feedback_to_train.main()
    fb = feedback_rows()
    probe = m1.M1()
    try:
        probe._embed("확인")
    except Exception as e:
        print(f"[재학습] Ollama bge-m3를 쓸 수 없어 멈춥니다({type(e).__name__}). Ollama를 켜고 'ollama pull bge-m3' 뒤 다시 실행해 주세요.")
        return 1
    cache = {}

    def vec(q):
        if q not in cache:
            cache[q] = probe._embed(q)
        return cache[q]
    print(f"[재학습] 피드백 {len(fb)}건(답할지만 알려 준 기록 {sum(1 for _, t, e in fb if not t or e != '답함')}건)으로 질문 종류·답할지 판단을 다시 학습합니다.")
    CAND.write_text(json.dumps(build(vec, fb)), encoding="utf-8")
    old, n = score(m1.MODEL, vec)
    new, _ = score(CAND, vec)
    keep = decide(old, new)
    if keep:
        PREV.write_text(m1.MODEL.read_text(encoding="utf-8"), encoding="utf-8")
        CAND.replace(m1.MODEL)
        print(f"[재학습] 판정 {n}문항: 지금 {old} → 새 모델 {new}. 새 모델로 바꿨습니다(이전 모델: {PREV.name}). 실행 스크립트를 다시 시작하면 적용됩니다.")
    else:
        CAND.unlink()
        print(f"[재학습] 판정 {n}문항: 지금 {old} → 새 모델 {new}. 점수가 낮아 바꾸지 않았습니다.")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "feedback": len(fb), "old": old, "new": new, "kept": keep}, ensure_ascii=False) + "\n")
    import lexicon_candidates  # 동네·업종 낱말 후보 표도 함께 만든다(채택은 담당자가 표에 O를 적고 --apply)
    lexicon_candidates.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
