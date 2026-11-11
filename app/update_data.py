"""자료 갱신(v3 설계 C, 2026-11-11): API 자료는 새로 받고, 파일 자료는 data/raw/에 넣은 것을 읽어 표를 다시 만든다.

순서
  1) API 수집(키는 .env, 이미 받은 날짜·쪽은 건너뜀)
     - 583 내국인 유동인구, 589·590 외국인 유동인구: 최근 --days일
     - 기상 ASOS: 마지막 수집일 다음 날부터 오늘까지
     - 상가(상권) 정보: 기준월이 바뀌었으면 기존 폴더를 store_<기준월>로 옮기고 새로 받음
     - 음식점 인허가: 마지막 갱신 시점 이후 바뀐 것만(--since)
  2) 파일 자료: data/raw/의 제주관광공사 카드 파일(가장 최근 끝 월 파일을 자동 선택)
  3) 표 다시 만들기: build_tables → build_dong_tables → build_v3_tables → catalog
실행(Windows·Mac 공통): python app/update_data.py   (API 없이 표만: --tables-only)
"""
import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "data" / "interim" / "api"
PY = sys.executable


def run(*args, ok_fail=False):
    print("▶", " ".join(str(a) for a in args), flush=True)
    r = subprocess.run([PY, *map(str, args)], cwd=ROOT)
    if r.returncode and not ok_fail:
        raise SystemExit(f"실패: {args}")
    return r.returncode == 0


def last_asos():
    fs = sorted((API / "asos").glob("*.parquet"))
    return max(f.stem.split("_")[-1] for f in fs) if fs else "20250331"


def last_food_update():
    fs = list((API / "food").rglob("*.parquet"))
    if not fs:
        return None
    t = max(pd.read_parquet(f, columns=["DAT_UPDT_PNT"])["DAT_UPDT_PNT"].max() for f in fs)
    return t.replace("-", "").replace(":", "").replace(" ", "")[:14]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45, help="유동인구를 다시 확인할 최근 일수")
    ap.add_argument("--tables-only", action="store_true")
    a = ap.parse_args()
    today = dt.date.today()
    if not a.tables_only:
        start = (today - dt.timedelta(days=a.days)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        for did in ("583", "589", "590"):
            run("app/collect_api.py", did, "--start", start, "--end", end, "--max-calls", "900", ok_fail=True)
        run("app/collect_public.py", "asos", "--start", last_asos(), "--end", end, ok_fail=True)
        store = API / "store"
        backup = None
        if store.exists() and any(store.glob("*.parquet")):
            old = pd.read_parquet(sorted(store.glob("*.parquet"))[0], columns=["stdrYm"])["stdrYm"].iloc[0]
            backup = API / f"store_{old}"
            shutil.move(str(store), str(backup))  # 새 기준월을 처음부터 받는다(단면 자료라 섞지 않음)
        if not run("app/collect_public.py", "store", "--max-calls", "200", ok_fail=True) and backup:
            shutil.rmtree(store, ignore_errors=True)  # 받다가 끊기면 이전 기준월로 되돌린다
            shutil.move(str(backup), str(store))
        since = last_food_update()
        if since:
            run("app/collect_public.py", "food", "--since", since, ok_fail=True)
    run("app/build_tables.py", "stores", "restaurants", "station")
    run("app/build_dong_tables.py")
    run("app/build_v3_tables.py")
    run("app/catalog.py")
    print("완료: data/tables/meta.json의 *_last 값으로 자료별 최신 시점을 확인하세요.")


if __name__ == "__main__":
    main()
