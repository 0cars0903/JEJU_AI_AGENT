"""F9 센터 자료 불러오기 (docs/기획/v3_설계.md 4-1절, 2026-11-12 구현).

센터 자료는 Agent가 DB에 붙지 않고, 이용자가 센터 조회 화면에서 받은 CSV를 넣으면 읽는다(데이콘 안내 2026-11-11).
구현 범위(사용자 결정): 시험할 수 있는 1-07·1-08 카드 이용 현황(읍면동)만. 칸 구성이 같은 허브 746 CSV로 시험한다.
- 칸 이름은 명세의 영문(base_year_month, bjd, biz_nm, user_type, use_amt …)과 한글(년월, 법정동, 업종명, 이용자구분, 이용금액 …)을 모두 받는다.
- 법정동 → 행정동은 상가 자료의 법정동·행정동 쌍 비율로 나눈다(build_v3_tables.dong_weights와 같음).
- 저장: data/interim/uploads/<id>.parquet + <id>.json. 하루 지난 파일은 다음 불러오기 때 지운다(반출 불가 자료를 오래 두지 않음).
- 답에는 집계 결과만 쓴다(원자료 줄을 내려받기로 내보내지 않음).
"""
import io
import json
import time
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "data" / "interim" / "uploads"
MAX_BYTES = 300 * 1024 * 1024
KEEP_SEC = 24 * 3600
# 표준 칸 ← 받을 수 있는 이름들(센터 명세 영문·한글, 허브 746)
COLS = {
    "ym": ["base_year_month", "년월"],
    "bdong": ["bjd", "법정동", "읍면동명"],
    "biz": ["biz_nm", "업종명"],
    "user": ["user_type", "이용자구분", "이용자 구분"],
    "amt": ["use_amt", "이용금액"],
    "cnt": ["use_cnt", "이용건수"],
    "region": ["dstrct_se", "지역구분"],
}
NEED = ["ym", "bdong", "biz", "amt"]
CUST = {"제주도민": "도민", "도민": "도민", "내국인": "내국인 관광객", "법인": "법인"}  # 그 밖(중국·일본·동남아·기타외국)은 외국인 관광객
LABEL = {"C1-07": "센터 1-07 카드 이용 현황(읍면동)_v01", "C1-08": "센터 1-08 카드 이용 현황(읍면동)_v02", "P746": "허브 746(센터 1-07과 같은 칸 구성, 시험용)"}


class CsvError(ValueError):
    pass


def _cleanup():
    UP.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for f in UP.glob("*"):
        if now - f.stat().st_mtime > KEEP_SEC:
            f.unlink(missing_ok=True)


def _read(raw):
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as e:
            raise CsvError(f"CSV 형식을 읽지 못했습니다: {e}") from e
    raise CsvError("파일 인코딩을 알 수 없습니다(UTF-8 또는 CP949 CSV를 넣어 주세요).")


def identify(columns):
    """칸 이름 → (표준 칸 대응, 빠진 필수 칸)."""
    cols = {c.strip(): c for c in columns}
    m = {k: next((cols[n] for n in names if n in cols), None) for k, names in COLS.items()}
    return m, [k for k in NEED if not m[k]]


def load(raw, filename="upload.csv"):
    """CSV 바이트 → 저장 후 요약. 자료를 알아보지 못하면 CsvError(이유와 다시 받을 방법)."""
    if len(raw) > MAX_BYTES:
        raise CsvError("파일이 300MB보다 큽니다. 센터 조회 화면에서 동네·업종·기간 조건을 좁혀 다시 받아 주세요.")
    if not filename.lower().endswith(".csv"):
        raise CsvError("CSV 파일만 넣을 수 있습니다.")
    _cleanup()
    d = _read(raw)
    m, miss = identify(d.columns)
    if miss:
        names = {"ym": "년월(base_year_month)", "bdong": "법정동(bjd)", "biz": "업종명(biz_nm)", "amt": "이용금액(use_amt)"}
        raise CsvError("카드 이용 현황(읍면동) 자료가 아닙니다. 빠진 칸: " + ", ".join(names[k] for k in miss)
                       + ". 센터 조회 화면에서 '카드 이용 현황(읍면동)_v02'를 골라 다시 받아 주세요.")
    t = pd.DataFrame({k: d[c] for k, c in m.items() if c})
    t["ym"] = t["ym"].str.replace(r"\D", "", regex=True).str[:6]
    t = t[t["ym"].str.len() == 6]
    t["ym"] = t["ym"].str[:4] + "-" + t["ym"].str[4:]
    t["amt"] = pd.to_numeric(t["amt"], errors="coerce")
    t = t.dropna(subset=["amt"])
    if t.empty:
        raise CsvError("이용금액 값이 비어 있습니다. 검색 결과가 있는 조건으로 다시 받아 주세요.")
    t["cust"] = t["user"].map(lambda u: "전체" if pd.isna(u) else CUST.get(str(u).strip(), "외국인 관광객")) if "user" in t else "전체"
    import build_v3_tables as B  # 법정동 → 행정동 비율(상가 자료)
    w = B.dong_weights()
    g = t.groupby(["ym", "bdong", "biz", "cust"], as_index=False)["amt"].sum().merge(w, on="bdong", how="left")
    unmapped = sorted(g.loc[g["dong"].isna(), "bdong"].unique())
    g["amt"] = g["amt"] * g["w"]
    out = g.dropna(subset=["dong"]).groupby(["ym", "dong", "biz", "cust"], as_index=False)["amt"].sum()
    kind = "P746" if "매장수" in d.columns else ("C1-08" if out["ym"].max() >= "2025-05" else "C1-07")
    did = uuid.uuid4().hex[:12]
    out.to_parquet(UP / f"{did}.parquet", index=False)
    meta = {"id": did, "dataset": kind, "label": LABEL[kind], "file": filename, "rows": int(len(d)), "agg_rows": int(len(out)),
            "period": [out["ym"].min(), out["ym"].max()], "dongs": sorted(out["dong"].unique()), "bdongs": sorted(t["bdong"].unique())[:20],
            "biz": sorted(out["biz"].unique())[:50], "unmapped_bdong": unmapped, "columns": {k: v for k, v in m.items() if v}}
    (UP / f"{did}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def get(did):
    f = UP / f"{did}.json"
    if not did or not f.exists() or not did.isalnum():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def table(did):
    return pd.read_parquet(UP / f"{did}.parquet")


def check_request(meta, dong=None, biz42=None):
    """요청한 조건(동네·업종)이 들어 있는지. 없으면 다시 받을 조건을 안내한다."""
    probs = []
    if dong and dong not in meta["dongs"]:
        probs.append(f"{dong} 자료가 없습니다(들어 있는 동네: {', '.join(meta['dongs'][:5])}{' 등' if len(meta['dongs']) > 5 else ''}). 법정동 조건을 넣어 다시 받아 주세요.")
    if biz42 and not any(biz42 in b for b in meta["biz"]):
        probs.append(f"업종 '{biz42}'가 없습니다. 업종명 조건을 넣어 다시 받아 주세요.")
    return probs
