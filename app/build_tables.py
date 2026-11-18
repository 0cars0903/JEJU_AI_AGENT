"""원본 파일 3종(793·780·743) + 612 정류소를 정제해 data/interim/*.parquet과 매핑표를 만든다.

입력: data/raw/ (사용자 배치 원본, 수정하지 않음), data/interim/api/612_stations.parquet
출력: data/interim/
  stores.parquet          793 상가(점포 단위, 행정동 포함)
  restaurants.parquet     780 음식점(개업·폐업일, 행정동 부여 결과와 근거)
  bus_daily/<연도>.parquet 743 버스(날짜 × 정류소명 × 이용자유형 × 이용자수)
  station_dong.parquet    743 정류소명 × 행정동 매핑(가중치·근거·배분 여부)
  mapping_report.txt      매핑률 요약(H1 판정 자료)
원본 형식 주의(docs/조사/05_데이터확인.md): 793·780은 CP949, 780 폐업일자는 '20060206.0',
743은 정류소명 안 쉼표가 따옴표 없이 들어 있어 앞 1칸·뒤 2칸 고정으로 분리한다.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "interim"
F793 = RAW / "제주특별자치도 상가(상권) 정보.csv"
F780 = RAW / "제주특별자치도음식점목록(통합).csv"
F743 = RAW / "이용자유형별버스정류소이용인원현황.csv"
MANUAL = ROOT / "data" / "manual" / "station_manual.csv"  # 정류소명 수동 매핑(근거 포함)
REPORT = []


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line); REPORT.append(line)


API = OUT / "api"
# v3(2026-11-11): 최신 자료 우선. 공공데이터포털 API로 받은 상가(stdrYm)·음식점(행안부 인허가)이 있으면 원본 CSV 대신 쓴다.
STORE_COLS = {"bizesNm": "상호명", "indsLclsNm": "상권업종대분류명", "indsMclsNm": "상권업종중분류명", "indsSclsNm": "상권업종소분류명", "ksicNm": "표준산업분류명",
              "ctprvnNm": "시도명", "signguNm": "시군구명", "adongNm": "행정동명", "ldongNm": "법정동명", "adongCd": "행정동코드", "ldongCd": "법정동코드",
              "lnoAdr": "지번주소", "rdnmAdr": "도로명주소", "newZipcd": "신우편번호", "lon": "경도", "lat": "위도"}
FOOD_COLS = {"BPLC_NM": "사업장명", "BZSTAT_SE_NM": "업종구분소분류", "LCPMT_YMD": "인허가일자", "SALS_STTS_NM": "영업상태명", "DTL_SALS_STTS_NM": "상세영업상태명",
             "CLSBIZ_YMD": "폐업일자", "LOTNO_ADDR": "소재지전체주소", "ROAD_NM_ADDR": "도로명전체주소", "ROAD_NM_ZIP": "도로명우편번호", "DAT_UPDT_PNT": "데이터갱신일자"}
SOURCE = {}


def _api_files(sub):
    return sorted((API / sub).rglob("*.parquet")) if (API / sub).exists() else []


def load_stores():
    fs = _api_files("store")
    if fs:
        a = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True).drop_duplicates("bizesId")
        SOURCE["stores"] = f"상가 API(기준 {a['stdrYm'].iloc[0]})"
        return a.rename(columns=STORE_COLS)[list(STORE_COLS.values())].astype(str)
    SOURCE["stores"] = "793 CSV"
    return pd.read_csv(F793, encoding="cp949", dtype=str)


def load_restaurants():
    parts = []
    for sub, kind in (("general_restaurants", "일반음식점"), ("rest_cafes", "휴게음식점")):
        fs = [f for f in _api_files("food") if f.parent.name.startswith(sub)]
        if fs:
            parts.append(pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True).assign(업종구분대분류=kind))
    if len(parts) == 2:
        a = pd.concat(parts, ignore_index=True).drop_duplicates("MNG_NO", keep="last").rename(columns=FOOD_COLS)  # 갱신분(since_*)이 뒤에 와서 최신을 남긴다
        for c in ("인허가일자", "폐업일자"):
            a[c] = a[c].fillna("").str.replace("-", "", regex=False).replace("", None)
        SOURCE["restaurants"] = f"행안부 음식점 API(갱신 ~{a['데이터갱신일자'].max()[:10]})"
        return a[["사업장명", "업종구분대분류"] + [c for c in FOOD_COLS.values() if c != "사업장명"]].astype(object)
    SOURCE["restaurants"] = "780 CSV"
    return pd.read_csv(F780, encoding="cp949", dtype=str)


# ---------- 793 상가 ----------
def build_stores():
    s = load_stores()
    s["경도"], s["위도"] = s["경도"].astype(float), s["위도"].astype(float)
    s.to_parquet(OUT / "stores.parquet", index=False)
    say(f"[793] 점포 {len(s):,} · 행정동 {s['행정동명'].nunique()} · 법정동 {s['법정동명'].nunique()}")
    return s


# ---------- 780 음식점 → 행정동 ----------
def build_restaurants(stores):
    r = load_restaurants()
    r["open_date"] = pd.to_datetime(r["인허가일자"], format="%Y%m%d", errors="coerce")
    r["close_date"] = pd.to_datetime(r["폐업일자"].str.replace(r"\.0$", "", regex=True), format="%Y%m%d", errors="coerce")
    r["legal_dong"] = r["소재지전체주소"].fillna("").str.split().str[2]
    legal2admin = stores.groupby("법정동명")["행정동명"].agg(lambda x: Counter(x)).to_dict()
    post2admin = stores.dropna(subset=["신우편번호"]).groupby("신우편번호")["행정동명"].agg(lambda x: Counter(x)).to_dict()
    road = lambda a: (a.split() + ["", "", ""])[2] if isinstance(a, str) else ""  # '제주특별자치도 제주시 무근성안길 16' → '무근성안길'
    road2admin = stores.assign(road=stores["도로명주소"].map(road)).groupby("road")["행정동명"].agg(lambda x: Counter(x)).to_dict()
    r["road"] = r["도로명전체주소"].map(road)
    dongs, how = [], []
    r["post5"] = r["도로명우편번호"].fillna("").str.replace(r"\.0$", "", regex=True).str.zfill(5).replace("00000", "")  # '63166.0' → '63166'
    for legal, post, rd in zip(r["legal_dong"], r["post5"], r["road"]):
        cand = legal2admin.get(legal)
        if cand is None:
            dongs.append(None); how.append("법정동 없음")
        elif len(cand) == 1:
            dongs.append(next(iter(cand))); how.append("법정동 1:1")
        elif post in post2admin and set(post2admin[post]) & set(cand):
            pc = {k: v for k, v in post2admin[post].items() if k in cand}
            dongs.append(max(pc, key=pc.get)); how.append("우편번호")
        elif rd and rd in road2admin and set(road2admin[rd]) & set(cand):
            pc = {k: v for k, v in road2admin[rd].items() if k in cand}
            dongs.append(max(pc, key=pc.get)); how.append("도로명")
        else:
            dongs.append(max(cand, key=cand.get)); how.append("법정동 다수결(모호)")
    r["admin_dong"], r["dong_how"] = dongs, how
    r.to_parquet(OUT / "restaurants.parquet", index=False)
    say(f"[780] 음식점 {len(r):,} · 행정동 부여 방식", dict(Counter(how)))
    return r


# ---------- 743 버스 ----------
def build_bus():
    (OUT / "bus_daily").mkdir(exist_ok=True)
    cur_year, buf, n = None, [], 0

    def flush():
        if buf:
            d = pd.DataFrame(buf, columns=["base_date", "station_name", "user_type", "user_count"])
            d["user_count"] = d["user_count"].astype("int32")
            d.to_parquet(OUT / "bus_daily" / f"{cur_year}.parquet", index=False)
            buf.clear()

    with open(F743, encoding="utf-8-sig") as f:
        next(f)
        for line in f:
            date, _, rest = line.rstrip("\n").partition(",")
            name, utype, cnt = rest.rsplit(",", 2)
            if date[:4] != cur_year:
                flush(); cur_year = date[:4]
            buf.append((date, name.strip(), utype, int(float(cnt)))); n += 1
    flush()
    say(f"[743] 행 {n:,} → bus_daily/<연도>.parquet")


# ---------- 정류소명 → 행정동 ----------
def norm(x):
    return re.sub(r"[\s\(\)\[\]\.,·\-_/]", "", x or "")


def base(x):  # 612 이름 끝의 방향·보조 표기 괄호 제거: '한국병원(노형로 방향)' → '한국병원'
    return re.sub(r"\([^)]*\)\s*$", "", x or "").strip()


BOUNDARY = OUT / "admdong_jeju.geojson"


def _inside(ring, x, y):
    """점(x, y)이 다각형 고리 안에 있는가(반직선 교차 수)."""
    x1, y1 = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    c = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / np.where(y2 == y1, 1e-12, y2 - y1) + x1)
    return bool(c.sum() % 2)


def boundary_dong(lon, lat):
    """좌표마다 들어 있는 행정동 이름(경계 파일이 없으면 None, 경계 밖이면 NaN)."""
    if not BOUNDARY.exists():
        return None
    import json
    polys = []
    for f in json.loads(BOUNDARY.read_text(encoding="utf-8"))["features"]:
        g = f["geometry"]
        for pg in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            polys.append((f["properties"]["adm_nm"].split()[-1], [np.array(r) for r in pg]))
    out = []
    for x, y in zip(lon, lat):
        d = None
        if pd.notna(x) and pd.notna(y):
            for name, rings in polys:
                if _inside(rings[0], x, y) and not any(_inside(h, x, y) for h in rings[1:]):
                    d = name
                    break
        out.append(d)
    return pd.Series(out, index=lon.index)


def build_station_dong(stores):
    st = pd.read_parquet(OUT / "api" / "612_stations.parquet")
    st["lon"], st["lat"] = pd.to_numeric(st["longitude"], errors="coerce"), pd.to_numeric(st["latitude"], errors="coerce")
    admin = set(stores["행정동명"])
    # 612 주소 → 행정동: 주소 토큰 중 행정동 목록에 있는 것. 없으면 가장 가까운 793 점포의 행정동
    xy = stores[["경도", "위도"]].to_numpy(); sd = stores["행정동명"].to_numpy()
    def dong_of(row):
        for t in str(row["stationAddress"] or "").split():
            if t in admin:
                return t, "주소"
        if pd.notna(row["lon"]) and pd.notna(row["lat"]):
            i = np.argmin((xy[:, 0] - row["lon"]) ** 2 + (xy[:, 1] - row["lat"]) ** 2)
            return sd[i], "최근접 점포"
        return None, "좌표 없음"
    st[["dong", "dong_src"]] = st.apply(lambda r: pd.Series(dong_of(r)), axis=1)
    # 좌표가 행정동 경계 안에 들면 그 동으로(2026-11-16 문제 기록 33번). 612 주소 표기는 동이 틀린 경우가 있다(귀덕1리 '애월읍' → 경계로는 한림읍).
    # 경계: vuski/admdongkor ver20261001 제주 부분(app/build_map.py와 같은 원자료), data/interim/admdong_jeju.geojson
    poly = boundary_dong(st["lon"], st["lat"])
    if poly is not None:
        st["dong_src"] = np.where(poly.notna(), "행정동 경계", st["dong_src"])
        st["dong"] = poly.fillna(st["dong"])
    say("[612] 정류소 행정동 부여", dict(Counter(st["dong_src"])))
    by_norm, by_base, by_piece = defaultdict(list), defaultdict(list), defaultdict(list)
    for _, r in st.iterrows():
        by_norm[norm(r["stationName"])].append(r["dong"]); by_base[norm(base(r["stationName"]))].append(r["dong"])
        for piece in re.split(r"[/,]", re.sub(r"\([^)]*\)", "", r["stationName"] or "")):  # '아라주공아파트/아라스위첸아파트' → 조각별
            if norm(piece):
                by_piece[norm(piece)].append(r["dong"])
    # 743 정류소명 목록(이용자 합계 포함)
    tot, tot24 = Counter(), Counter()
    for f in sorted((OUT / "bus_daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["station_name", "user_count"])
        g = d.groupby("station_name")["user_count"].sum().to_dict()
        tot.update(g)
        if f.stem == "2024":
            tot24.update(g)
    manual = defaultdict(list)
    for r in pd.read_csv(MANUAL, dtype=str).fillna("").itertuples():
        if r.dong not in admin:
            raise ValueError(f"수동 매핑표의 행정동 오류: {r.station_name} → {r.dong}")
        manual[r.station_name].append((r.dong, float(r.weight or 1)))
    rows = []
    for name, users in tot.items():
        k = norm(name)
        if name in manual:
            w, how = dict(manual[name]), "수동"
        elif "우도" in name:  # 612에 우도 주소가 없음(06_EDA_H1H3.md), 743 이름은 우도봉입구·우도천진항뿐
            w, how = {"우도면": 1.0}, "우도 규칙"
        else:
            how, cands = None, []
            for label, c in [("이름 일치", by_norm.get(k)), ("기본 이름 일치", by_base.get(k)), ("양쪽 기본 이름", by_base.get(norm(base(name)))),
                             ("이름 조각", by_piece.get(norm(re.sub(r"\([^)]*\)", "", name).split("/")[0])))]:
                cands = [x for x in (c or []) if x]
                if cands:
                    how = label; break
            if not cands:
                rows.append((name, users, tot24.get(name, 0), None, 0.0, "미매핑", False)); continue
            w = Counter(cands)  # 후보가 여럿이면 612 정류소 수 비례로 나눈다(동 경계 양쪽 정류소가 많다)
        total = sum(w.values())
        for dong, v in w.items():
            rows.append((name, users, tot24.get(name, 0), dong, v / total, how, len(w) > 1))
    m = pd.DataFrame(rows, columns=["station_name", "users_total", "users_2024", "dong", "weight", "how", "ambiguous"])
    m.to_parquet(OUT / "station_dong.parquet", index=False)  # 이름 × 행정동(가중치 합 1). 미매핑은 dong 없음
    one = m.drop_duplicates("station_name")
    u, u24 = one["users_total"].sum(), one["users_2024"].sum()
    mapped = one[one["dong"].notna()]
    say(f"[743→행정동] 정류소명 {len(one):,} · 매핑 {len(mapped):,} ({len(mapped)/len(one)*100:.1f}%) · 이용자 기준 전체 {mapped['users_total'].sum()/u*100:.2f}% · 2024년 {mapped['users_2024'].sum()/u24*100:.2f}%")
    say("   방식별", dict(Counter(one["how"])), f"· 여러 동 배분 {int(one['ambiguous'].sum())}개(이용자 {one.loc[one['ambiguous'],'users_total'].sum()/u*100:.2f}%)")
    say("   2024 미매핑 상위", one[one["dong"].isna()].nlargest(15, "users_2024")[["station_name", "users_2024"]].values.tolist())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    steps = sys.argv[1:] or ["stores", "restaurants", "bus", "station"]
    stores = build_stores() if "stores" in steps or "restaurants" in steps or "station" in steps else None
    if "restaurants" in steps: build_restaurants(stores)
    if "bus" in steps: build_bus()
    if "station" in steps: build_station_dong(stores)
    (OUT / "mapping_report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
