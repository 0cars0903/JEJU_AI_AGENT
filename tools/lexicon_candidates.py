"""동네·업종 낱말 사전 보강(센터 PC용, 2026-11-15). 사용:
  python tools/lexicon_candidates.py            → 후보 표(lexicon_candidates.csv)를 기록 폴더에 만든다
  python tools/lexicon_candidates.py --apply 표  → 표에서 '채택' 칸이 O인 줄만 data/lexicon/learned.json에 넣는다

- 근거: [조건 바꾸기]로 동네나 업종을 고친 기록(feedback.jsonl의 before → slots). 고친 질문에서 사전에 없는 낱말을 찾아
  '낱말 → 고친 동네·업종' 후보로 만든다. 학습 문장 3개 이상에 나오는 일반 낱말은 뺀다. 지명·가게 끝말(거리·단지·해변 / 집·당·점 등)이면
  '추천'에 O를 붙여 위에 둔다. 같은 후보가 여러 질문에서 나올수록 위에 둔다.
- 사람이 채택한 것만 넣는다. 넣은 낱말은 질문 해석기(app/qparse.py)가 시작할 때 읽는다. learned.json을 지우면 원래 사전으로 돌아간다.
- 판정 문항(data/x1/test_*_gold.jsonl)과 같은 질문의 기록은 쓰지 않는다.
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import qparse  # noqa: E402
import qtuple as Q  # noqa: E402

LEARNED = ROOT / "data" / "lexicon" / "learned.json"
PLACE_END = re.compile(r"(거리|단지|해변|해수욕장|항|포구|오름|공원|시장|광장|마을|사거리|로터리|해안도로|입구|역|공항|터미널|타운|센터|리)$")
BIZ_END = re.compile(r"(집|당|점|포차|가게|숍|샵|전문점|식당|요리|라면|국수|칼국수|탕|국밥|횟집|술집|주점|베이커리|빵집)$")
_DF = {}


def common(w, limit=3):
    """학습 문장(질문 기록 색인의 종류 기록)에서 limit개 이상 나오는 낱말은 일반 낱말로 보고 뺀다."""
    if not _DF:
        import rag
        meta = json.loads(rag.ROWS.read_text(encoding="utf-8")) if rag.ROWS.exists() else {"libs": {}}
        for q in meta["libs"].get("type", {}).get("q", []):
            for t in set(words(q)):
                _DF[t] = _DF.get(t, 0) + 1
    return _DF.get(w, 0) >= limit


JOSA = re.compile(r"(에서|에는|에도|으로|이랑|하고|까지|부터|보다|처럼|이나|은|는|이|가|을|를|에|의|도|만|랑|와|과|로|쪽|근처|주변|일대)$")


def write_dir():
    return Path(os.environ["JEJU_WRITE_DIR"]) if os.environ.get("JEJU_WRITE_DIR") else ROOT / "data" / "interim"


def known(w):
    """이미 사전에 있는 낱말(지명·업종·지표·조건)은 후보에서 뺀다."""
    if w in qparse.PLACES or w in Q.DONGS or any(w == k for k, _ in qparse.BIZ_KEYS):
        return True
    return bool(qparse.find_places(w)[0] or qparse.find_targets(w) or qparse.hits(w, qparse.METRIC_W))


def words(q):
    out = []
    for t in re.findall(r"[가-힣A-Za-z0-9]+", q):
        t = JOSA.sub("", t)
        if len(t) >= 2 and not t.isdigit():
            out.append(t)
    return out


def candidates(records, test=()):
    """records: feedback 기록 목록. 반환: [{낱말, 종류, 값, 건수, 예시}]"""
    c, ex = defaultdict(int), {}
    for r in records:
        q, b, s = (r.get("question") or "").strip(), r.get("before") or {}, r.get("slots") or {}
        if not q or r.get("kind") != "고침" or q in test:
            continue
        new_d = [d for d in (s.get("space") or []) if d not in (b.get("space") or [])]
        new_t = s.get("target") if s.get("target") and s.get("target") != b.get("target") else None
        ws = [w for w in words(q) if not known(w) and not common(w)]
        for w in ws:
            for d in new_d:
                c[(w, "동네", d)] += 1
                ex.setdefault((w, "동네", d), q)
            if new_t:
                c[(w, "업종", new_t)] += 1
                ex.setdefault((w, "업종", new_t), q)
    rows = [{"채택": "", "추천": "O" if (PLACE_END if k == "동네" else BIZ_END).search(w) else "", "낱말": w, "종류": k, "값": v, "건수": n,
             "예시 질문": ex[(w, k, v)]} for (w, k, v), n in c.items()]
    return sorted(rows, key=lambda r: (r["추천"] != "O", -r["건수"], r["낱말"]))


def apply(rows, path=LEARNED):
    cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"places": {}, "targets": {}}
    n = 0
    for r in rows:
        if (r.get("채택") or "").strip().upper() not in ("O", "Y", "예"):
            continue
        if r["종류"] == "동네" and r["값"] in Q.DONGS:
            cur.setdefault("places", {})[r["낱말"]] = r["값"]
            n += 1
        elif r["종류"] == "업종" and r["값"] in qparse.CLOSED_TARGETS:
            cur.setdefault("targets", {})[r["낱말"]] = r["값"]
            n += 1
    path.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def main():
    import envfile
    envfile.load()
    if "--apply" in sys.argv:
        f = Path(sys.argv[sys.argv.index("--apply") + 1])
        with f.open(encoding="utf-8-sig") as fp:
            n = apply(list(csv.DictReader(fp)))
        print(f"[사전] 채택한 낱말 {n}개를 {LEARNED.relative_to(ROOT)}에 넣었습니다. 앱을 다시 실행하면 적용됩니다.")
        return 0
    src = write_dir() / "feedback.jsonl"
    if not src.exists():
        print(f"[사전] 기록이 없습니다: {src}")
        return 0
    test = {json.loads(l)["q"] for p in (ROOT / "data" / "x1").glob("test_*_gold.jsonl") for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = candidates([json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()], test)
    out = write_dir() / "lexicon_candidates.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fp:  # 엑셀에서 한글이 깨지지 않게 BOM
        w = csv.DictWriter(fp, fieldnames=["채택", "추천", "낱말", "종류", "값", "건수", "예시 질문"])
        w.writeheader()
        w.writerows(rows)
    print(f"[사전] 후보 {len(rows)}개를 {out}에 만들었습니다. 맞는 줄의 '채택' 칸에 O를 적고 --apply로 넣어 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
