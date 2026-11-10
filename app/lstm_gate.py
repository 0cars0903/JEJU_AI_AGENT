"""관문 v2의 LSTM 비교군. 별도 가상환경(torch CPU, 제출 의존성 아님)에서 돈다. GPU(MPS)는 쓰지 않는다(GA_KSL 학습과 겹침 방지).

입력: data/interim/gates/panel_v2.parquet(app/model_gates_v2.py가 만듦). 회차·기준선·과제(7일 뒤 로그 방문)는 v2와 같다.
모델: 43개 동네 전역 LSTM. 7일 전까지 28일의 로그 방문 차분 순열 → LSTM(은닉 32) → [마지막 상태, 동네 임베딩, 그날 달력(·날씨)] → 출력.
목표: y - lag7(7일 전 대비 변화). 비교: LSTM-M0(날씨 제외), LSTM-M1(날씨 포함).
실행: <torch가 설치된 가상환경>/bin/python app/lstm_gate.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

torch.set_num_threads(8)
torch.manual_seed(0)
np.random.seed(0)
ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "interim" / "gates"
FOLDS = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"]
TEST_DAYS, H, WIN = 60, 7, 28
CAL = ["holiday", "long_break", "myeongjeol", "vacation"]
WX = ["temp", "temp2", "windy", "r1", "r2", "r3"]


class Net(nn.Module):
    def __init__(self, n_dong, n_ctx):
        super().__init__()
        self.emb = nn.Embedding(n_dong, 8)
        self.lstm = nn.LSTM(1, 32, batch_first=True)
        self.head = nn.Sequential(nn.Linear(32 + 8 + n_ctx, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, seq, dong, ctx):
        _, (h, _) = self.lstm(seq)
        return self.head(torch.cat([h[-1], self.emb(dong), ctx], 1)).squeeze(1)


def build(d, use_wx, WIN=WIN):
    d = d.sort_values(["emd", "date"]).reset_index(drop=True)
    d["dong_id"] = d["emd"].astype("category").cat.codes
    ctx_cols = CAL + (WX if use_wx else [])
    dow = pd.get_dummies(d["dow"], prefix="dow", dtype=float)
    mon = pd.get_dummies(d["mon"], prefix="mon", dtype=float)
    ctx = pd.concat([d[ctx_cols].astype(float), dow, mon], axis=1).to_numpy(np.float32)
    seqs, idx = [], []
    for _, g in d.groupby("emd"):
        y = g["y"].to_numpy()
        diff = np.diff(y, prepend=y[0])
        for j in range(len(g)):
            end = j - H  # 7일 전까지만 사용
            if end - WIN + 1 < 0:
                continue
            seqs.append(diff[end - WIN + 1:end + 1])
            idx.append(g.index[j])
    seqs = np.array(seqs, np.float32)[:, :, None]
    idx = np.array(idx)
    return d, seqs, idx, ctx


def run(use_wx, win=WIN, seed=0):
    torch.manual_seed(seed)
    np.random.seed(seed)
    d = pd.read_parquet(P / "panel_v2.parquet")
    d, seqs, idx, ctx = build(d, use_wx, win)
    sub = d.loc[idx].reset_index(drop=True)
    target = (sub["y"] - sub["lag7"]).to_numpy(np.float32)
    S, C, D = torch.tensor(seqs), torch.tensor(ctx[idx]), torch.tensor(sub["dong_id"].to_numpy().astype(np.int64))
    pred = np.full(len(sub), np.nan)
    for f in FOLDS:
        s = pd.Timestamp(f)
        tr = (sub["date"] < s - pd.Timedelta(days=H)).to_numpy()
        te = ((sub["date"] >= s) & (sub["date"] < s + pd.Timedelta(days=TEST_DAYS))).to_numpy()
        net = Net(int(sub["dong_id"].max()) + 1, C.shape[1])
        opt = torch.optim.Adam(net.parameters(), lr=3e-3)
        ti = np.where(tr)[0]
        Y = torch.tensor(target)
        for ep in range(6):
            np.random.shuffle(ti)
            for b in range(0, len(ti), 256):
                j = ti[b:b + 256]
                opt.zero_grad()
                loss = nn.functional.l1_loss(net(S[j], D[j], C[j]), Y[j])
                loss.backward()
                opt.step()
        with torch.no_grad():
            k = np.where(te)[0]
            pred[k] = net(S[k], D[k], C[k]).numpy()
    sub["p"] = sub["lag7"] + pred
    t = sub.dropna(subset=["p"]).copy()
    t["fold"] = None
    for f in FOLDS:
        s = pd.Timestamp(f)
        t.loc[(t["date"] >= s) & (t["date"] < s + pd.Timedelta(days=TEST_DAYS)), "fold"] = f
    e, base = (t["y"] - t["p"]).abs(), (t["y"] - t["lag7"]).abs()
    big8 = t["emd"].isin(["우도면", "추자면", "남원읍", "봉개동", "대정읍", "한경면", "영천동", "구좌읍"])
    w = t["wet"] == 1
    return {"rows_test": int(len(t)), "MASE": round(float(e.mean() / base.mean()), 4),
            "MASE_by_fold": {f: round(float(e[t["fold"] == f].mean() / base[t["fold"] == f].mean()), 4) for f in FOLDS},
            "MASE_big8": round(float(e[big8].mean() / base[big8].mean()), 4), "MASE_wet": round(float(e[w].mean() / base[w].mean()), 4),
            "pred": t[["emd", "date", "p"]].assign(date=lambda x: x["date"].astype(str)).to_dict(orient="list")}


def windows():
    """실험 4: 입력 창 14·28·56·91일 × 시드 3개(LSTM M0). 앞 3회차로 고르고 뒤 2회차로 보고."""
    sel, rep = FOLDS[:3], FOLDS[3:]
    res = {}
    for w in [14, 28, 56, 91]:
        rs = []
        for sd in [0, 1, 2]:
            r = run(False, w, sd)
            pr = pd.DataFrame(r.pop("pred"))
            rs.append(r)
        res[f"win{w}"] = {"MASE_select_mean": round(float(np.mean([np.mean([x["MASE_by_fold"][f] for f in sel]) for x in rs])), 4),
                          "MASE_report_mean": round(float(np.mean([np.mean([x["MASE_by_fold"][f] for f in rep]) for x in rs])), 4),
                          "MASE_all_by_seed": [x["MASE"] for x in rs]}
        print(w, res[f"win{w}"], flush=True)
    (P / "lstm_windows.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    import sys
    if "--windows" in sys.argv:
        return windows()
    out = {}
    for nm, wx in [("LSTM_M0", False), ("LSTM_M1", True)]:
        r = run(wx)
        pd.DataFrame(r.pop("pred")).to_parquet(P / f"{nm}_pred.parquet", index=False)
        out[nm] = r
        print(nm, json.dumps(r, ensure_ascii=False))
    (P / "lstm_gate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
