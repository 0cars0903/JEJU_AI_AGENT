"""v3 1단계 자료층: 제주관광공사 카드 소비(A·B·F)와 허브 746을 표로 만들고 겹치는 기간을 교차 대조한다.

설계 `docs/기획/v3_설계.md` 3절. 원본 `data/raw/`(읽기 전용), 결과 `data/tables/`(앱 동봉), 대조 기록 `data/interim/v3/`.

  A  카드 관광 읍면동 리 월별 통계_2020-01~2026-09.csv : 시간대 칸이 빠진 시간대별 줄 → 합쳐서 월 값
  B  카드 관광 읍면동 리 월별 통계_2024-10~2026-09.csv : A + 시간대 + 외국인
  F  외국인 관광객 권역별 카드 소비_2020-01~2026-08.csv : 제주 전체 × 업종 5 × 출신지역
  746 주제1_업종별 카드 매출과 매장수(비씨카드) : 법정동 72 → 행정동 43 (793 상가 수 비율로 나눔)

실행: .venv/bin/python app/build_v3_tables.py
"""
import glob

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT, LOG = ROOT / "data" / "raw", ROOT / "data" / "tables", ROOT / "data" / "interim" / "v3"
def _latest(pattern, hourly=None):
    """data/raw/에서 이름 끝 월(…~YYYY-MM)이 가장 늦은 파일. hourly=True/False면 시간대 칸 유무로 고른다(갱신 파일을 넣으면 자동으로 바뀜)."""
    fs = []
    for f in RAW.glob(pattern):
        if hourly is not None:
            head = f.open(encoding="utf-8-sig", errors="ignore").readline()
            if ("시간대" in head) != hourly:
                continue
        fs.append((f.stem.split("~")[-1], f.stem.split("_")[-1].split("~")[0], f))
    if not fs:
        raise FileNotFoundError(pattern)
    return sorted(fs, key=lambda x: (x[0], [-ord(c) for c in x[1]]))[-1][2]


FA = _latest("카드 관광 읍면동 리 월별 통계_*.csv", hourly=False)
FB = _latest("카드 관광 읍면동 리 월별 통계_*.csv", hourly=True)
FF = _latest("외국인 관광객 권역별 카드 소비_*.csv")
F793 = RAW / "제주특별자치도 상가(상권) 정보.csv"

BIZ5 = ["소매업", "숙박업", "음식점업", "기타서비스업", "예술스포츠여가업"]
# 746 업종코드(표준산업분류) → 관광공사 대분류 5. 소매·숙박·음식점은 코드 앞자리로 분명하다.
# 나머지는 관광공사 분류 기준이 공개되지 않아 추정이다(교차 대조에서는 쓰지 않는다).
BIZ_CERTAIN = {"G47": "소매업", "I55": "숙박업", "I56": "음식점업"}
BIZ_GUESS = {"R91": "예술스포츠여가업", "S96": "기타서비스업", "N75": "기타서비스업", "L69": "기타서비스업",
             "H49": "기타서비스업", "H50": "기타서비스업", "H51": "기타서비스업"}
# 746 이용자 구분 → 관광공사 관광객 구분
CUST746 = {"제주도민": "도민", "내국인": "내국인 관광객", "중국": "외국인 관광객", "일본": "외국인 관광객",
           "동남아": "외국인 관광객", "기타외국": "외국인 관광객", "법인": "법인"}
OVERLAP = ("2020-01", "2021-05")
# 대조 기준(대조 전에 고정, 설계 3-4절)
MOM_MIN, YOY_MIN = 0.75, 0.8


def read(f, **k):
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(f, encoding=enc, **k)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없음: {f}")


def ym(s):
    s = s.astype(str)
    return s.str[:4] + "-" + s.str[4:6]


def build_card():
    a = read(FA, dtype={"기준연월": str, "읍면동코드": str})
    a = a.rename(columns={"기준연월": "ym", "관광객구분": "cust", "읍면동명": "dong", "업종명": "biz",
                          "카드 매출액(원)": "amt", "이용건수": "cnt"})
    a["ym"] = ym(a["ym"])
    # 같은 값의 줄도 서로 다른 시간대일 수 있어 지우지 않고 모두 더한다(설계 3-2절)
    m = a.groupby(["ym", "dong", "biz", "cust"], as_index=False)[["amt", "cnt"]].sum()
    m.to_parquet(OUT / "card_month.parquet", index=False)

    b = read(FB, dtype={"기준연월": str, "읍면동코드": str, "시간대": str})
    b = b.rename(columns={"기준연월": "ym", "관광객구분": "cust", "읍면동명": "dong", "업종명": "biz",
                          "카드 매출액(원)": "amt", "이용건수": "cnt", "시간대": "hour"})
    b["ym"] = ym(b["ym"])
    b["hour"] = b["hour"].astype(int)
    h = b.groupby(["ym", "dong", "biz", "cust", "hour"], as_index=False)[["amt", "cnt"]].sum()
    h.to_parquet(OUT / "card_hour.parquet", index=False)

    f = read(FF, dtype={"기준연월": str})
    f = f.rename(columns={"기준연월": "ym", "업종명": "biz", "출신지역": "origin", "이용건수": "cnt", "소비금액(원)": "amt"})
    f["ym"] = ym(f["ym"])
    f = f[["ym", "biz", "origin", "amt", "cnt"]]
    f.to_parquet(OUT / "card_foreign.parquet", index=False)

    # 확인: 2024-10 이후 A(도민·내국인) 합 = B 합
    k = ["ym", "dong", "biz", "cust"]
    x = m[m["ym"] >= "2024-10"].set_index(k)["amt"]
    y = h[h["cust"] != "외국인 관광객"].groupby(k)["amt"].sum()
    same = float((x.reindex(y.index) == y).mean())
    return {
        "card_month": {"rows": len(m), "ym": [m["ym"].min(), m["ym"].max()], "months": int(m["ym"].nunique()),
                       "dongs": int(m["dong"].nunique()), "biz": sorted(m["biz"].unique()), "cust": sorted(m["cust"].unique()),
                       "raw_rows": len(a)},
        "card_hour": {"rows": len(h), "ym": [h["ym"].min(), h["ym"].max()], "cust": sorted(h["cust"].unique())},
        "card_foreign": {"rows": len(f), "ym": [f["ym"].min(), f["ym"].max()], "origin": sorted(f["origin"].unique())},
        "check_A_equals_B_domestic": same,
    }, m


def dong_weights():
    """법정동 → 행정동 비율. 793 상가 수 비율로 나눈다(추정: 매출이 가게 수에 비례한다고 가정)."""
    st = ROOT / "data" / "interim" / "stores.parquet"  # build_tables.py 결과(상가 API가 있으면 최신 기준)
    s = pd.read_parquet(st, columns=["행정동명", "법정동명"]) if st.exists() else read(F793, dtype=str, usecols=["행정동명", "법정동명"])
    t = s.groupby(["법정동명", "행정동명"]).size().rename("n").reset_index()
    t["w"] = t["n"] / t.groupby("법정동명")["n"].transform("sum")
    return t.rename(columns={"법정동명": "bdong", "행정동명": "dong"})[["bdong", "dong", "w"]]


def build_746(w):
    # 같은 연도 파일이 둘이면 하나만 쓴다. `_17 (1).csv`는 `_17.csv`에서 이용자수·이용건수 칸만 뺀 같은 자료다(2026-11-11 확인).
    files = sorted(glob.glob(str(RAW / "*주제1*매쉬업결과_*.csv")), key=lambda f: (" (" in f, f))
    seen, used, parts = set(), [], []
    for f in files:
        year = Path(f).stem.split("_")[-1].split(" ")[0]
        if year in seen:
            used.append({"file": Path(f).name, "skipped": f"같은 연도({year}) 파일을 이미 씀"})
            continue
        seen.add(year)
        d = read(f, dtype={"업종코드": str})
        parts.append(d)
        used.append({"file": Path(f).name, "rows": len(d), "ym": [d["년월"].min(), d["년월"].max()]})
    d = pd.concat(parts, ignore_index=True)
    before = len(d)
    d = d.drop_duplicates()  # 같은 달이 두 파일에 겹칠 때 대비(완전히 같은 줄만)
    d = d.rename(columns={"년월": "ym", "읍면동명": "bdong", "업종코드": "code", "업종명": "biz42", "이용자 구분": "user", "이용금액": "amt"})
    d["ym"] = d["ym"].astype(str).str[:7]
    d["biz"] = d["code"].str[:3].map({**BIZ_CERTAIN, **BIZ_GUESS})
    d["biz_certain"] = d["code"].str[:3].isin(BIZ_CERTAIN)
    d["cust"] = d["user"].map(CUST746)
    g = d.groupby(["ym", "bdong", "biz", "biz_certain", "biz42", "cust"], as_index=False)["amt"].sum()
    g = g.merge(w, on="bdong", how="left")
    miss = sorted(g.loc[g["dong"].isna(), "bdong"].unique())
    g["amt"] = g["amt"] * g["w"]
    out = g.dropna(subset=["dong"]).groupby(["ym", "dong", "biz", "biz_certain", "biz42", "cust"], as_index=False)["amt"].sum()
    out.to_parquet(OUT / "card746_month.parquet", index=False)
    return {"files": used, "rows_raw": before, "dup_rows_removed": before - len(d), "rows": len(out),
            "ym": [out["ym"].min(), out["ym"].max()], "months": int(out["ym"].nunique()),
            "bdong_unmapped": miss, "split_bdong": sorted(w.loc[w["w"] < 1, "bdong"].unique())}, out


def sign_agree(x, y):
    dx, dy = np.sign(np.diff(x)), np.sign(np.diff(y))
    return int((dx == dy).sum()), len(dx)


def crosscheck(m, c):
    lo, hi = OVERLAP
    res = []
    for biz in BIZ_CERTAIN.values():
        for cust in ["도민", "내국인 관광객"]:
            a = m[(m["biz"] == biz) & (m["cust"] == cust) & m["ym"].between(lo, hi)].groupby("ym")["amt"].sum()
            b = c[(c["biz"] == biz) & (c["cust"] == cust) & c["ym"].between(lo, hi)].groupby("ym")["amt"].sum()
            j = pd.concat([a, b], axis=1, keys=["kto", "bc"]).dropna()
            mom_ok, mom_n = sign_agree(j["kto"].values, j["bc"].values)
            yoy = []
            for mm in ["01", "02", "03", "04", "05"]:
                y1, y0 = f"2021-{mm}", f"2020-{mm}"
                if y1 in j.index and y0 in j.index:
                    yoy.append(np.sign(j.loc[y1, "kto"] - j.loc[y0, "kto"]) == np.sign(j.loc[y1, "bc"] - j.loc[y0, "bc"]))
            # 동네 순위 상관(참고값): 겹치는 기간 합계로 동네 순위
            da = m[(m["biz"] == biz) & (m["cust"] == cust) & m["ym"].between(lo, hi)].groupby("dong")["amt"].sum()
            db = c[(c["biz"] == biz) & (c["cust"] == cust) & c["ym"].between(lo, hi)].groupby("dong")["amt"].sum()
            dd = pd.concat([da, db], axis=1, keys=["kto", "bc"]).dropna()
            res.append({
                "biz": biz, "cust": cust, "months": len(j),
                "mom_agree": f"{mom_ok}/{mom_n}", "mom_rate": round(mom_ok / mom_n, 3) if mom_n else None,
                "yoy_agree": f"{int(sum(yoy))}/{len(yoy)}", "yoy_rate": round(sum(yoy) / len(yoy), 3) if yoy else None,
                "level_ratio_kto_over_bc": round(float(j["kto"].sum() / j["bc"].sum()), 2),
                "dong_rank_spearman_ref": round(float(dd["kto"].rank().corr(dd["bc"].rank())), 3), "dongs": len(dd),
                "pass": bool(mom_n and mom_ok / mom_n >= MOM_MIN and yoy and sum(yoy) / len(yoy) >= YOY_MIN),
            })
    return {"overlap": OVERLAP, "criteria": {"mom_min": MOM_MIN, "yoy_min": YOY_MIN, "rank_corr": "참고값"},
            "series": res, "all_pass": all(r["pass"] for r in res)}


def main():
    OUT.mkdir(exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    meta_card, m = build_card()
    w = dong_weights()
    meta746, c = build_746(w)
    cc = crosscheck(m, c)
    report = {"card": meta_card, "card746": meta746, "crosscheck": cc}
    (LOG / "v3_tables.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    meta_path = OUT / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["card_first"], meta["card_last"] = meta_card["card_month"]["ym"]
    meta["card_hour_first"], meta["card_hour_last"] = meta_card["card_hour"]["ym"]
    meta["card_foreign_last"] = meta_card["card_foreign"]["ym"][1]
    meta["card746_first"], meta["card746_last"] = meta746["ym"]
    meta["card_crosscheck_pass"] = cc["all_pass"]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "crosscheck"}, ensure_ascii=False, default=str)[:1500])
    for r in cc["series"]:
        print(r)
    print("all_pass", cc["all_pass"])


if __name__ == "__main__":
    main()
