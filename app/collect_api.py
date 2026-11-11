"""제주데이터허브 API 수집기 (583 유동인구 · 579 일별 기상 · 612 버스 정류소 · 589·590 외국인 단기·장기체류 유동인구 · 592 관광지별 외국인 유입자).

- 키: 프로젝트 최상위 `.env`의 JEJU_DATAHUB_KEY. 키는 출력·로그·파일에 남기지 않는다.
- 저장: data/interim/api/<id>/<YYYYMMDD>.parquet (612는 stations.parquet). 이미 받은 날짜는 건너뛴다(이어받기).
- 호출 상한: --max-calls. 데이터별 일일 쿼터를 넘지 않게 멈춘다. 호출 기록은 data/interim/api/calls.log.
- 호출 규칙(2026-11-04 확인, docs/조사/05_데이터확인.md): 583은 limit 최대 100 + number(페이지),
  579는 searchDate 하루씩(역시 limit·number로 페이지 조회, 기본 10행), 612는 파라미터 없이 페이지 조회.

사용 예:
  .venv/bin/python app/collect_api.py 612
  .venv/bin/python app/collect_api.py 579 --start 20230401 --end 20250330 --max-calls 900
  .venv/bin/python app/collect_api.py 583 --start 20231104 --end 20251103 --max-calls 900
  .venv/bin/python app/collect_api.py 590 --start 20250901 --end 20260831 --newest-first --max-calls 900   (2026-11-11 추가: 653행/일 → 7회/일)
  .venv/bin/python app/collect_api.py 589 --start 20250901 --end 20260831 --newest-first --max-calls 900   (401행/일 → 5회/일)
  .venv/bin/python app/collect_api.py 592 --start 2009 --end 2024   (startDate·endDate는 YYYYMM, 1년 389행 → 4회/년)
"""
import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "interim" / "api"
BASE = "https://open.jejudatahub.net/api/proxy"
DATA_KEY = {  # 공개 상세 API(/api/data/view?id=)의 dataKey, 2026-11-04 확인
    583: "Daaa1t3at3tt8a8DD3t55538t35Dab1t",
    579: "1aD5taat1attaa51Db1511b51ab9Da19",
    612: None,  # 실행 시 조회
}
PAGE = 100  # 583 limit 최대값(200 이상은 0건)


def project_key():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "JEJU_DATAHUB_KEY":
            return v.strip().strip('"').strip("'")
    sys.exit(".env에 JEJU_DATAHUB_KEY가 없습니다")


class Client:
    def __init__(self, max_calls):
        self.key, self.max_calls, self.calls = project_key(), max_calls, 0
        OUT.mkdir(parents=True, exist_ok=True)
        self.log = open(OUT / "calls.log", "a", encoding="utf-8")

    def get(self, data_id, params):
        if self.calls >= self.max_calls:
            raise QuotaStop
        dk = DATA_KEY.get(data_id) or self._data_key(data_id)
        waits = [5, 10, 20, 40, 60]  # 빈 응답·JSON 아닌 응답은 재시도(2026-11-04 612에서 1회, 11-05 583에서 연속 발생)
        for attempt in range(len(waits) + 1):
            self.calls += 1
            r = None
            try:
                r = requests.get(f"{BASE}/{dk}/{self.key}", params=params, timeout=60)
                body = r.json()
                self.log.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{data_id}\t{params}\t{r.status_code}\t{len(body.get('data') or [])}\n")
                return body
            except (requests.RequestException, ValueError) as e:
                self.log.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{data_id}\t{params}\tERR {type(e).__name__}\t{self._head(r)}\n")
                if self.calls >= self.max_calls:
                    raise QuotaStop
                if attempt < len(waits):
                    time.sleep(waits[attempt])
        raise RuntimeError(f"{data_id} {params} {len(waits) + 1}회 실패")

    def _head(self, r):  # 오류 응답 앞부분(키 제거)만 기록
        if r is None:
            return "-"
        return f"{r.status_code} " + r.text[:80].replace(self.key, "<KEY>").replace("\n", " ").replace("\t", " ")

    def _data_key(self, data_id):
        meta = requests.get(f"https://www.jejudatahub.net/api/data/view?id={data_id}", timeout=30).json()
        DATA_KEY[data_id] = meta["dataKey"]
        return DATA_KEY[data_id]


class QuotaStop(Exception):
    pass


class DayFails:
    """하루치가 끝내 실패하면 그날은 저장하지 않고 넘어간다(다음 실행 때 다시 받음). 연속 3일 실패면 중단."""
    def __init__(self, limit=3):
        self.limit, self.run, self.skipped = limit, 0, []

    def fail(self, day, e):
        self.run += 1; self.skipped.append(day)
        print(f"  건너뜀 {day}: {e}")
        if self.run >= self.limit:
            raise RuntimeError(f"연속 {self.limit}일 실패 — 서버 상태 확인 후 다시 실행")

    def ok(self):
        self.run = 0


def days(start, end):
    d, e = dt.datetime.strptime(start, "%Y%m%d").date(), dt.datetime.strptime(end, "%Y%m%d").date()
    while d <= e:
        yield d.strftime("%Y%m%d")
        d += dt.timedelta(days=1)


def fetch_pages(c, data_id, params):
    rows, page = [], 1
    while True:
        body = c.get(data_id, {**params, "limit": PAGE, "number": page})
        data = body.get("data") or []
        rows += data
        if not body.get("hasMore") or not data:
            return rows, body
        page += 1


def collect_583(c, start, end):
    """하루치(약 688행)를 100행씩 나눠 받아 날짜별 파일로 저장."""
    folder = OUT / "583"; folder.mkdir(exist_ok=True)
    fails = DayFails()
    for day in days(start, end):
        f = folder / f"{day}.parquet"
        if f.exists():
            continue
        try:
            rows, body = fetch_pages(c, 583, {"startDate": day, "endDate": day})
        except RuntimeError as e:
            fails.fail(day, e); continue
        fails.ok()
        if rows and len(rows) != body.get("totCnt", len(rows)):
            print(f"  경고 {day}: totCnt {body.get('totCnt')} ≠ 받은 행 {len(rows)}")
        pd.DataFrame(rows).to_parquet(f, index=False)  # 0행도 저장(자료 없는 날 기록)
        print(f"  583 {day} {len(rows)}행 (누적 호출 {c.calls})")


def collect_579(c, start, end):
    folder = OUT / "579"; folder.mkdir(exist_ok=True)
    fails = DayFails()
    for day in days(start, end):
        f = folder / f"{day}.parquet"
        if f.exists():
            continue
        try:  # 579도 기본 10행만 줌(2026-11-04 확인) → limit·number로 페이지 조회
            rows, _ = fetch_pages(c, 579, {"searchDate": day})
        except RuntimeError as e:
            fails.fail(day, e); continue
        fails.ok()
        pd.DataFrame(rows).to_parquet(f, index=False)
        if c.calls % 100 == 0:
            print(f"  579 {day} (누적 호출 {c.calls})")


def collect_daily(c, data_id, start, end, newest_first=False):
    """589·590: 583과 같은 호출 규칙(startDate=endDate=하루, limit 100 페이지). limit 1000은 거절(2026-11-11 확인)."""
    folder = OUT / str(data_id); folder.mkdir(exist_ok=True)
    fails = DayFails()
    ds = list(days(start, end))
    for day in (reversed(ds) if newest_first else ds):
        f = folder / f"{day}.parquet"
        if f.exists():
            continue
        try:
            rows, body = fetch_pages(c, data_id, {"startDate": day, "endDate": day})
        except RuntimeError as e:
            fails.fail(day, e); continue
        fails.ok()
        pd.DataFrame(rows).to_parquet(f, index=False)
        print(f"  {data_id} {day} {len(rows)}행 (누적 호출 {c.calls})")


def collect_592(c, start, end):
    """관광지별 외국인 유입자 수: 1년씩(startDate·endDate = YYYYMM)."""
    folder = OUT / "592"; folder.mkdir(exist_ok=True)
    for y in range(int(start[:4]), int(end[:4]) + 1):
        f = folder / f"{y}.parquet"
        if f.exists():
            continue
        rows, body = fetch_pages(c, 592, {"startDate": f"{y}01", "endDate": f"{y}12"})
        pd.DataFrame(rows).to_parquet(f, index=False)
        print(f"  592 {y} {len(rows)}행 (totCnt {body.get('totCnt')}, 누적 호출 {c.calls})")


def collect_612(c):
    rows, page = [], 1
    while True:
        body = c.get(612, {"limit": PAGE, "number": page})
        data = body.get("data") or []
        rows += data
        if not body.get("hasMore") or not data:
            break
        page += 1
    pd.DataFrame(rows).to_parquet(OUT / "612_stations.parquet", index=False)
    print(f"  612 {len(rows)}곳 (totCnt {body.get('totCnt')}, 호출 {c.calls})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_id", type=int, choices=[583, 579, 612, 589, 590, 592])
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--max-calls", type=int, default=900)
    ap.add_argument("--newest-first", action="store_true")
    a = ap.parse_args()
    c = Client(a.max_calls)
    try:
        {583: lambda: collect_583(c, a.start, a.end), 579: lambda: collect_579(c, a.start, a.end), 612: lambda: collect_612(c),
         589: lambda: collect_daily(c, 589, a.start, a.end, a.newest_first), 590: lambda: collect_daily(c, 590, a.start, a.end, a.newest_first),
         592: lambda: collect_592(c, a.start, a.end)}[a.data_id]()
        print(f"완료: 호출 {c.calls}회")
    except QuotaStop:
        print(f"호출 상한 {a.max_calls}회 도달 — 다음 실행 때 이어서 받음")


if __name__ == "__main__":
    main()
