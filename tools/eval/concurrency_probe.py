"""같은 PC에서 질문 3개가 겹칠 때의 지연(2026-11-17 문제 기록 52번, 완료 기준 '3개 동시에 마지막 답 180초 안').

사용: 서버를 띄운 뒤(`uvicorn app.api:app --port 8599`) python tools/eval/concurrency_probe.py [--url http://127.0.0.1:8599] [--out 결과.json]
- 질문 3개(일반 질문 2, 여러 단계 질문 1)를 0.2초 간격으로 /api/ask에 보낸다. 서버는 JEJU_MAX_CONCURRENT(기본 1)만큼만 동시에 계산하고 나머지는 차례를 기다린다.
- 질문마다 보낸 시각부터 답을 받은 시각까지(초), 상태, 결론 첫 60자를 적는다. 혼자 보냈을 때의 지연도 따로 잰다.
"""
import json
import sys
import threading
import time
import urllib.request

args = sys.argv[1:]
URL = args[args.index("--url") + 1] if "--url" in args else "http://127.0.0.1:8599"
OUT = args[args.index("--out") + 1] if "--out" in args else None
QS = ["노형동 카페 몇 개나 있어?", "애월읍 식당 요즘 장사 잘돼?", "식당 매출 가장 높은 동네 찾고 거기 카페 수 알려줘"]


def ask(q):
    req = urllib.request.Request(URL + "/api/ask", json.dumps({"question": q}).encode(), {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as r:
        x = json.loads(r.read())
    return round(time.perf_counter() - t0, 1), x.get("status"), str((x.get("card") or {}).get("conclusion") or "")[:60]


def main():
    alone = {q: ask(q)[0] for q in QS}  # 혼자 보냈을 때(같은 질문을 겹쳐 보내기 전에 한 번씩)
    res = {}

    def run(q):
        res[q] = ask(q)
    ts = []
    for q in QS:
        t = threading.Thread(target=run, args=(q,))
        t.start()
        ts.append(t)
        time.sleep(0.2)
    for t in ts:
        t.join()
    rows = [{"q": q, "혼자(초)": alone[q], "겹침(초)": res[q][0], "status": res[q][1], "결론": res[q][2]} for q in QS]
    summ = {"질문 수": len(QS), "혼자 합(초)": round(sum(alone.values()), 1), "겹침 마지막 답(초)": max(r["겹침(초)"] for r in rows), "180초 안": max(r["겹침(초)"] for r in rows) < 180}
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print("SUMMARY", json.dumps(summ, ensure_ascii=False))
    if OUT:
        open(OUT, "w", encoding="utf-8").write(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
