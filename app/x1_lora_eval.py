"""실험 X1 LoRA(A+L-ft) 추론: LoRA 가상환경(mlx_lm)에서 실행해 원출력과 1건 처리 시간을 저장한다.

- 기반 모델 Qwen/Qwen3-1.7B(공용 캐시), 어댑터 /Volumes/1TB/local_store/jeju_lora/adapters_1111(학습 data/x1/lora, 2026-11-11 13:13~).
- 입력 프롬프트는 학습과 같다(system = qtuple.SCHEMA_PROMPT, 생각 모드 끔). 온도 0, 최대 300토큰.
- 블라인드 문항 문장은 출력하지 않는다(사용자 규칙). 저장 파일: data/x1/results/LR_<시험>_raw.jsonl (id, text, sec)
- 채점은 프로젝트 가상환경에서: .venv/bin/python app/x1_eval.py LR --std150c
실행: HF_HOME=/Volumes/1TB/local_store/huggingface HF_HUB_OFFLINE=1 /Volumes/1TB/local_store/jeju_lora/venv/bin/python app/x1_lora_eval.py std150c
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qtuple as Q  # noqa: E402

ADAPTER = "/Volumes/1TB/local_store/jeju_lora/adapters_1111"


def main(test):
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
    model, tok = load("Qwen/Qwen3-1.7B", adapter_path=ADAPTER)
    sampler = make_sampler(temp=0.0)
    gold = [json.loads(x) for x in (Q.ROOT / "data" / "x1" / f"test_{test}_gold.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

    def ask(q):
        msgs = [{"role": "system", "content": Q.SCHEMA_PROMPT}, {"role": "user", "content": q}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False)
        return generate(model, tok, prompt=prompt, max_tokens=300, sampler=sampler)
    ask("노형동 카페 몇 개야?")  # 준비 실행(첫 호출의 컴파일 시간은 재지 않는다)
    out = []
    for g in gold:
        t0 = time.perf_counter()
        text = ask(g["q"])
        out.append({"id": g["id"], "text": text, "sec": round(time.perf_counter() - t0, 4)})
    f = Q.ROOT / "data" / "x1" / "results" / f"LR_{test}_raw.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    secs = sorted(r["sec"] for r in out)
    print(f"{len(out)}건 저장 {f.name} · 시간 중앙값 {secs[len(secs) // 2]:.3f}초 · 90% {secs[int(len(secs) * 0.9) - 1]:.3f}초")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "std150c")
