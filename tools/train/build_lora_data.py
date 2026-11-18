"""학습 증류(문제 기록 58번) LoRA 학습 자료를 만든다(mlx_lm chat 형식: {"messages": [...], "tools": [...]?}).

1) 기법 고르기: 교사(Opus) 라벨 = data/plans/teacher_techs_304.jsonl(조정용 일반 질문) + teacher_synth_600.jsonl(합성, 판정 문항과 유사도 0.90 이상 4개 제외).
   입력은 서비스의 student 방식(more.pick_examples k=0)과 같은 지시문·허용 목록, 출력은 {"intent","flow","techs"} JSON.
   자료 적합성 관문(more.unfit)에 걸리는 질문은 서비스에서 모델에 가지 않으므로 넣지 않는다. 교사 기법은 허용 목록 안의 것만(최대 2).
2) 기존 역할 보존(자기 증류, arXiv 2402.13669): 조정용 묶음을 돌릴 때 남긴 7B 호출 기록(JEJU_LLM_LOG)의 입력과 7B 응답 그대로.
판정 문항은 넣지 않는다. 사용: python tools/train/build_lora_data.py <selflog.jsonl> <out_dir> [drop.json]
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import more  # noqa: E402

selflog, out = Path(sys.argv[1]), Path(sys.argv[2])
drop = set(json.loads(Path(sys.argv[3]).read_text())) if len(sys.argv) > 3 else set()
out.mkdir(parents=True, exist_ok=True)
rows = []
teach = [json.loads(x) for f in ("teacher_techs_304.jsonl", "teacher_synth_600.jsonl") for x in (ROOT / "data/plans" / f).read_text(encoding="utf-8").splitlines() if x.strip()]
n_pick = n_gate = 0
for t in teach:
    if t["id"] in drop:
        continue
    q = t["q"]
    s = more.slots_of(q)
    if more.unfit(q, s):
        n_gate += 1
        continue
    ok = more.allowed(q, s)
    if not ok:
        continue
    techs = [x for x in (t.get("techs") or []) if x in ok][:2]
    user = f"질문: {q}\n읽은 동네: {', '.join(s.get('space') or []) or '없음'} / 업종: {s.get('target') or '없음'}\n이 질문에 계산할 수 있는 기법: {', '.join(ok)}"
    ans = json.dumps({"intent": t.get("intent"), "flow": t.get("flow"), "techs": techs}, ensure_ascii=False)
    rows.append({"messages": [{"role": "system", "content": more.S_EX}, {"role": "user", "content": user}, {"role": "assistant", "content": ans}], "kind": "pick"})
    n_pick += 1
seen, n_self = set(), 0
for line in selflog.read_text(encoding="utf-8").splitlines():
    x = json.loads(line)
    r = x.get("response") or {}
    msg = {"role": "assistant", "content": r.get("content") or ""}
    if r.get("tool_calls"):
        msg["tool_calls"] = [{"type": "function", "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}}} for c in r["tool_calls"]]
    key = json.dumps([x["messages"], msg], ensure_ascii=False)
    if key in seen or not (msg["content"] or msg.get("tool_calls")):
        continue
    seen.add(key)
    row = {"messages": x["messages"] + [msg], "kind": "self"}
    if x.get("tools"):
        row["tools"] = x["tools"]
    rows.append(row)
    n_self += 1
random.seed(0)
random.shuffle(rows)
k = max(20, len(rows) // 10)
for name, part in (("valid", rows[:k]), ("train", rows[k:])):
    with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
        for r in part:
            r = {kk: v for kk, v in r.items() if kk != "kind"}
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(json.dumps({"기법 고르기": n_pick, "관문 제외": n_gate, "자기 증류": n_self, "train": len(rows) - k, "valid": k}, ensure_ascii=False))
