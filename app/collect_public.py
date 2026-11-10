"""공공데이터포털(data.go.kr) API 수집기 — 제주 범위만 받는다 (2026-11-10 사용자 지시).

- 키: 프로젝트 최상위 `.env`의 DATA_ASOS_API_KEY · DATA_STORE_API_KEY · DATA_FOOD_1_API_KEY(휴게) ·
  DATA_FOOD_2_API_KEY(일반) · DATA_RAIN_API_KEY(단기예보). 값은 따옴표 안의 인코딩 키. 키는 출력·로그·파일에 남기지 않는다.
- 일일 한도: API마다 10,000회. --max-calls로 이번 실행의 호출 상한을 둔다. 호출 기록 data/interim/api/calls_public.log.
- 받는 범위(시험 호출로 확인, 2026-11-10):
  asos  : 제주 ASOS 관측소 4곳(184 제주, 185 고산, 188 성산, 189 서귀포) × 기간. 579가 멈춘 2025-03-31 이후만.
  store : 상가(상권) 정보, 시도 코드 50(제주) 전체 약 59,100건(1,000건씩). 단면 자료라 일부만 받으면 동네 비교가 깨진다.
  food  : 행정안전부 휴게음식점·일반음식점, 개방자치단체코드 6510000(제주시)·6520000(서귀포시) 전체 약 53,400건(100건씩).
          780과 이어 줄 관리번호가 없어 폐업을 정확히 세려면 전체가 필요하다(사용자 결정 (가)안). 도로명주소 조건은 약 3,000건이 빠져 쓰지 않는다.
          이후에는 --since(데이터갱신시점)로 바뀐 것만 받는다.
- 저장: data/interim/api/<asos|store|food>/. 페이지별 파일로 저장해 끊겨도 이어받는다.

사용 예:
  .venv/bin/python app/collect_public.py asos --start 20250331 --end 20261109
  .venv/bin/python app/collect_public.py store
  .venv/bin/python app/collect_public.py food
  .venv/bin/python app/collect_public.py food --since 20261108000000
"""
import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "interim" / "api"
ASOS_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
STORE_URL = "http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"
FOOD_URL = "http://apis.data.go.kr/1741000/{ep}/info"
ASOS_STATIONS = [184, 185, 188, 189]
JEJU_ORGS = ["6510000", "6520000"]
FOOD_KINDS = {"rest_cafes": "DATA_FOOD_1_API_KEY", "general_restaurants": "DATA_FOOD_2_API_KEY"}


def env_key(name):
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == name:
            m = re.match(r'\s*["\']([^"\']*)["\']', v)
            return m.group(1) if m else v.split("#")[0].strip()
    sys.exit(f".env에 {name}가 없습니다")


class QuotaStop(Exception):
    pass


def as_text(rows):
    """API 값은 숫자·빈 문자열이 섞여 온다(상가 lnoSlno 등). 원본 그대로 문자열로 저장하고 형 변환은 표 만들 때 한다."""
    df = pd.DataFrame(rows)
    return df.map(lambda v: None if v is None else str(v))


class Client:
    def __init__(self, key_name, max_calls):
        self.key, self.max_calls, self.calls = env_key(key_name), max_calls, 0
        OUT.mkdir(parents=True, exist_ok=True)
        self.log = open(OUT / "calls_public.log", "a", encoding="utf-8")
        self.name = key_name

    def get(self, url, params):
        """키는 이미 인코딩된 값이라 그대로 붙이고, 나머지 변수만 인코딩한다."""
        q = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
        waits = [5, 10, 20, 40]
        for attempt in range(len(waits) + 1):
            if self.calls >= self.max_calls:
                raise QuotaStop
            self.calls += 1
            r = None
            try:
                r = requests.get(f"{url}?serviceKey={self.key}&{q}", timeout=60)
                body = r.json()
                self.log.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{self.name}\t{params}\t{r.status_code}\n")
                return body
            except (requests.RequestException, ValueError) as e:
                head = "-" if r is None else f"{r.status_code} " + r.text[:120].replace(self.key, "<KEY>").replace("\n", " ")
                self.log.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{self.name}\t{params}\tERR {type(e).__name__}\t{head}\n")
                if attempt < len(waits):
                    time.sleep(waits[attempt])
        raise RuntimeError(f"{self.name} {params} 실패")


def collect_asos(start, end, max_calls):
    c = Client("DATA_ASOS_API_KEY", max_calls)
    folder = OUT / "asos"; folder.mkdir(exist_ok=True)
    for stn in ASOS_STATIONS:
        f = folder / f"{stn}_{start}_{end}.parquet"
        if f.exists():
            continue
        rows, page = [], 1
        while True:
            body = c.get(ASOS_URL, dict(dataType="JSON", dataCd="ASOS", dateCd="DAY", startDt=start, endDt=end,
                                         stnIds=stn, numOfRows=999, pageNo=page))
            res = body["response"]
            if res["header"]["resultCode"] != "00":
                raise RuntimeError(f"ASOS {stn}: {res['header']}")
            items = (res["body"].get("items") or {}).get("item") or []
            rows += items
            if len(rows) >= int(res["body"]["totalCount"]) or not items:
                break
            page += 1
        as_text(rows).to_parquet(f, index=False)
        print(f"  asos {stn} {len(rows)}일 ({rows[0]['tm'] if rows else '-'} ~ {rows[-1]['tm'] if rows else '-'}), 누적 호출 {c.calls}")
    return c.calls


def collect_store(max_calls):
    c = Client("DATA_STORE_API_KEY", max_calls)
    folder = OUT / "store"; folder.mkdir(exist_ok=True)
    page, total, stdr = 1, None, None
    while True:
        f = folder / f"p{page:04d}.parquet"
        if not f.exists():
            body = c.get(STORE_URL, dict(divId="ctprvnCd", key="50", numOfRows=1000, pageNo=page, type="json"))
            if body["header"]["resultCode"] != "00":
                raise RuntimeError(f"store: {body['header'].get('resultMsg')}")
            items = body["body"].get("items") or []
            total, stdr = int(body["body"]["totalCount"]), body["header"].get("stdrYm")
            df = as_text(items); df["stdrYm"] = stdr
            df.to_parquet(f, index=False)
        else:
            df = pd.read_parquet(f)
            stdr = df["stdrYm"].iloc[0] if len(df) else stdr
        if total is None:  # 이어받기에서 총 건수를 모르면 한 번 묻는다
            body = c.get(STORE_URL, dict(divId="ctprvnCd", key="50", numOfRows=1, pageNo=1, type="json"))
            total = int(body["body"]["totalCount"])
        if page * 1000 >= total or len(df) == 0:
            break
        page += 1
    n = sum(len(pd.read_parquet(p)) for p in folder.glob("p*.parquet"))
    print(f"  store 기준 {stdr}: {n}건 / totalCount {total}, 호출 {c.calls}")
    return c.calls


def collect_food(max_calls, since=None):
    used = 0
    for ep, key_name in FOOD_KINDS.items():
        c = Client(key_name, max_calls)
        for org in JEJU_ORGS:
            folder = OUT / "food" / (f"since_{since}" if since else "full") / f"{ep}_{org}"
            folder.mkdir(parents=True, exist_ok=True)
            cond = {"cond[OPN_ATMY_GRP_CD::EQ]": org}
            if since:
                cond["cond[DAT_UPDT_PNT::GTE]"] = since
            page, total = 1, None
            while True:
                f = folder / f"p{page:04d}.parquet"
                if f.exists() and total is not None:
                    page += 1
                    if (page - 1) * 100 >= total:
                        break
                    continue
                body = c.get(FOOD_URL.format(ep=ep), {"pageNo": page, "numOfRows": 100, "returnType": "json", **cond})
                b = body["response"]["body"]
                total = int(b.get("totalCount") or 0)
                items = (b.get("items") or {}).get("item") or []
                if not f.exists():
                    as_text(items).to_parquet(f, index=False)
                if page * 100 >= total or not items:
                    break
                page += 1
            n = sum(len(pd.read_parquet(p)) for p in folder.glob("p*.parquet"))
            print(f"  {ep} {org}: {n}건 / totalCount {total}, 누적 호출 {c.calls}")
        used += c.calls
    return used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["asos", "store", "food"])
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--since", help="food: 데이터갱신시점 이상(YYYYMMDDHHMMSS)만")
    ap.add_argument("--max-calls", type=int, default=1000)
    a = ap.parse_args()
    try:
        n = {"asos": lambda: collect_asos(a.start, a.end, a.max_calls),
             "store": lambda: collect_store(a.max_calls),
             "food": lambda: collect_food(a.max_calls, a.since)}[a.what]()
        print(f"완료: 호출 {n}회")
    except QuotaStop:
        print(f"호출 상한 {a.max_calls}회 도달 — 다음 실행 때 이어서 받음")


if __name__ == "__main__":
    main()
