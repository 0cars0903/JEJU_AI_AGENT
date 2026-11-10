"""평가셋 21문항 자동 채점. 기대값(gold)은 tools.py·build_dong_tables.py를 쓰지 않고 따로 계산한다.
채점: 상태·호출 도구·화면 답변에 기대 수치 문장이 그대로 있는가·금지 내용이 없는가.
독립성의 범위(이중 검토 008): 점포 수·법정동 1:1 음식점은 data/raw 원본에서 대조한다. 동네 배정(restaurants의 admin_dong, station_dong의 가중치)과
폐업률·생존율의 정의는 도구와 공유하므로 이 평가로 검증되지 않는다. 날씨 효과는 더미 회귀라는 다른 방법으로 다시 계산한다.
실행: .venv/bin/python eval/run_eval.py rule ollama:qwen2.5:7b ollama:qwen3:1.7b
출력: eval/results.json, 표준 출력 요약
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import agent  # noqa: E402

IN = ROOT / "data" / "interim"
st = pd.read_parquet(IN / "stores.parquet")
re_ = pd.read_parquet(IN / "restaurants.parquet")
sd = pd.read_parquet(IN / "station_dong.parquet")
b24 = pd.read_parquet(IN / "bus_daily" / "2024.parquet").merge(sd[["station_name", "dong", "weight"]], on="station_name")
b24 = b24[b24["dong"].notna()].assign(n=lambda x: x["user_count"] * x["weight"])
days24 = pd.read_parquet(IN / "bus_daily" / "2024.parquet", columns=["base_date"])["base_date"].nunique()
pop_all = pd.concat([pd.read_parquet(f) for f in glob.glob(str(IN / "api" / "583" / "*.parquet"))])
for c in ["resdPop", "workPop", "visitPop"]:
    pop_all[c] = pd.to_numeric(pop_all[c])
pop = pop_all[pop_all["baseDate"].str[:4] == "2024"]
RAW_ST = pd.read_csv(ROOT / "data" / "raw" / "제주특별자치도 상가(상권) 정보.csv", encoding="cp949", dtype=str, usecols=["행정동명", "법정동명"])
RAW_RE = pd.read_csv(ROOT / "data" / "raw" / "제주특별자치도음식점목록(통합).csv", encoding="cp949", dtype=str, usecols=["인허가일자", "폐업일자", "소재지전체주소"])
MOUNTAIN = {"어리목", "삼각봉", "사제비", "영실", "윗세오름", "한라산남벽", "진달래밭", "성판악", "한라생태숲"}


def raw_stores(d):
    return f"{(RAW_ST['행정동명'] == d).sum():,}곳"


def raw_open_close(dong, y):
    """법정동이 한 행정동에만 속하는 동네만 원본에서 바로 센다(노형동 = 법정동 노형동 + 해안동)."""
    pair = RAW_ST.drop_duplicates()
    n = pair.groupby("법정동명")["행정동명"].nunique()
    legal = [x for x in pair[pair["행정동명"] == dong]["법정동명"] if n[x] == 1]
    r = RAW_RE[RAW_RE["소재지전체주소"].fillna("").str.split().str[2].isin(legal)]
    return f"{y}년 음식점 개업 {(r['인허가일자'].str[:4] == str(y)).sum()}건, 폐업 {(r['폐업일자'].fillna('').str[:4] == str(y)).sum()}건"


def rain_flags():
    wx = pd.concat([pd.read_parquet(f) for f in glob.glob(str(IN / "api" / "579" / "*.parquet"))]).drop_duplicates()
    wx = wx[~wx["observatoryName"].isin(MOUNTAIN)]
    r = pd.to_numeric(wx["dailyRainfall"], errors="coerce").groupby(wx["baseDate"]).median()
    r.index = pd.to_datetime(r.index)
    return (r[(r.index >= "2023-11-01") & (r.index <= "2025-03-31")] >= 1.0)


def rain_ols(series):
    """연월 × 요일 더미 회귀(lstsq). stats.effect의 평균 차감과 수식이 같으면 값이 같아야 한다."""
    wet = rain_flags()
    d = pd.DataFrame({"y": np.log(series[series > 0])})
    d = d[d.index.isin(wet.index)]
    d["w"] = wet.reindex(d.index).astype(float)
    cell = d.index.strftime("%Y-%m") + "-" + d.index.dayofweek.astype(str)
    X = np.column_stack([d["w"].to_numpy(), pd.get_dummies(cell).to_numpy(dtype=float)])
    b = np.linalg.lstsq(X, d["y"].to_numpy(), rcond=None)[0][0]
    return round((np.exp(b) - 1) * 100, 1)


def rain_visit(dong):
    x = pop_all[pop_all["emd"] == dong].groupby("baseDate")["visitPop"].sum()
    x.index = pd.to_datetime(x.index)
    return rain_ols(x)


def rain_bus(dong):
    fr = []
    for y in ("2023", "2024", "2025"):
        b = pd.read_parquet(IN / "bus_daily" / f"{y}.parquet").merge(sd[sd["dong"] == dong][["station_name", "weight"]], on="station_name")
        fr.append((b["user_count"] * b["weight"]).groupby(b["base_date"]).sum())
    x = pd.concat(fr)
    x.index = pd.to_datetime(x.index)
    return rain_ols(x)


def word(p):
    return f"{abs(p)}% " + ("적었고" if p < 0 else "많았고")


def stores(d):
    return f"{(st['행정동명'] == d).sum():,}곳"


def minor_lq(d, col, name):
    x = st[st[col] == name]
    v = ((x["행정동명"] == d).sum() / (st["행정동명"] == d).sum()) / (len(x) / len(st))
    return ((x["행정동명"] == d).sum(), round(v, 2))


def opens(d, y, cats=None):
    r = re_[re_["admin_dong"] == d]
    if cats:
        r = r[r["업종구분소분류"].isin(cats)]
    return f"{y}년 ", int((r["open_date"].dt.year == y).sum()), int((r["close_date"].dt.year == y).sum())


def close_3y(d):
    r = re_[re_["admin_dong"] == d]
    k = n = 0
    for y in (2022, 2023, 2024):
        s = pd.Timestamp(f"{y}-01-01")
        a = r[(r["open_date"] < s) & (r["close_date"].isna() | (r["close_date"] >= s))]
        n += len(a)
        k += (a["close_date"].dt.year == y).sum()
    return round(k / n * 100, 1)


def km5(d):
    """표준 라이브러리 수준의 곱 극한(product-limit)을 stats.py와 따로 구현."""
    end = re_[["open_date", "close_date"]].max().max()
    r = re_[(re_["admin_dong"] == d) & (re_["open_date"] >= "2015-01-01") & (re_["open_date"] <= "2020-08-30")]
    t = ((r["close_date"].fillna(end) - r["open_date"]).dt.days / 365.25).clip(lower=0).to_numpy()
    e = r["close_date"].notna().to_numpy()
    s = 1.0
    for u in sorted(set(t[e & (t <= 5)])):
        s *= 1 - (e & (t == u)).sum() / (t >= u).sum()
    return round(s * 100, 1), len(r)


def bus(d):
    return round(b24[b24["dong"] == d]["n"].sum() / days24, 1)


def bus_type(d, t):
    x = b24[(b24["dong"] == d)]
    return round(x[x["user_type"] == t]["n"].sum() / days24, 1), round(x[x["user_type"] == t]["n"].sum() / x["n"].sum() * 100, 1)


def visit(d):
    x = pop[pop["emd"] == d]
    return round(x["visitPop"].sum() / x["resdPop"].sum(), 2)


def old(d):
    x = pop[pop["emd"] == d]
    return round(x[x["ageGroup"].isin(["60대", "70대이상"])]["resdPop"].sum() / x["resdPop"].sum() * 100, 1)


major = st.pivot_table(index="행정동명", columns="상권업종대분류명", aggfunc="size", fill_value=0)
lq_major = major.div(major.sum(1), axis=0) / (major.sum(0) / major.values.sum())
lodge = lq_major["숙박"].drop(["우도면", "추자면"]).sort_values(ascending=False)
CAFE = ["커피숍", "까페", "다방", "전통찻집", "키즈카페", "떡카페", "라이브카페"]
ccnt, clq = minor_lq("애월읍", "상권업종소분류명", "카페")
hansik = minor_lq("이도2동", "상권업종중분류명", "한식")
lodge_j = minor_lq("조천읍", "상권업종대분류명", "숙박")
km_no, km_non = km5("노형동")


def yr(d, y, cats=None):
    t, o, c = opens(d, y, cats)
    return f"{y}년", f"개업 {o}건, 폐업 {c}건"


F = lambda x: f"{x:,}"  # noqa: E731
EVAL = [
    ("Q01", "노형동 생활 진단해 줘", "ok", ["dong_profile"], [raw_stores("노형동"), f"{close_3y('노형동')}%", f"{km_no}%", f"표본 {km_non}건", f"{F(bus('노형동'))}명", f"{visit('노형동')}"], []),
    ("Q02", "애월읍 동네 전반적인 현황 알려줘", "ok", ["dong_profile"], [raw_stores("애월읍"), f"{F(bus('애월읍'))}명", f"{visit('애월읍')}"], []),
    ("Q03", "추자면 현황 어때?", "ok", ["dong_profile"], [raw_stores("추자면"), "표본 적음", f"표본 {km5('추자면')[1]}건"], []),
    ("Q04", "애월읍에 카페가 많은 편이야?", "ok", ["biz_diagnostic"], [f"{ccnt}곳", f"{clq}"], []),
    ("Q05", "최근 2년 노형동 음식점 개업·폐업은?", "ok", ["biz_diagnostic"], [raw_open_close("노형동", 2023), raw_open_close("노형동", 2024)], []),
    ("Q06", "이도2동 한식 현황 진단해 줘", "ok", ["biz_diagnostic"], [f"{hansik[0]}곳", f"{hansik[1]}"], []),
    ("Q07", "조천읍 숙박업 현황 알려줘", "ok", ["biz_diagnostic"], [f"{lodge_j[0]}곳", f"{lodge_j[1]}", "자료는 없습니다"], ["음식점 전체 기준"]),  # 음식점 수치가 숙박 답에 붙으면 안 된다. 요약의 "폐업 자료 없음"은 허용
    ("Q08", "연동 오가는 사람 구성은?", "ok", ["population_mix"], [f"{visit('연동')}", f"{old('연동')}%"], []),
    ("Q09", "비 오는 날 아라동 방문 인구는 어떻게 변해?", "ok", ["population_mix"], ["비 오는 날 방문 지수", word(rain_visit("아라동"))], []),
    ("Q10", "구좌읍 거주자 연령대 비율 알려줘", "ok", ["population_mix"], [f"{old('구좌읍')}%"], []),
    ("Q11", "한림읍 버스 이용 현황 어때?", "ok", ["bus_usage"], [f"{F(bus('한림읍'))}명"], []),
    ("Q12", "한림읍 어르신 버스 이용은 얼마나 돼?", "ok", ["bus_usage"], [f"일평균 {F(bus_type('한림읍', '경로')[0])}명", f"비중 {bus_type('한림읍', '경로')[1]}%"], []),
    ("Q13", "비 오는 날 노형동 버스 이용은?", "ok", ["bus_usage"], ["비 오는 날 버스 이용", word(rain_bus("노형동"))], []),
    ("Q14", "아라동과 이도2동 비교표 뽑아 줘", "ok", ["dong_profile"], ["[아라동]", "[이도2동]", raw_stores("아라동"), raw_stores("이도2동"), f"{F(bus('아라동'))}명", f"{F(bus('이도2동'))}명"], ["카페", "'아라동'"]),
    ("Q15", "숙박 비중이 가장 높은 동네 순위는?", "ok", ["compare_rank"], [f"1위 {lodge.index[0]} {lodge.iloc[0]:.2f}", f"2위 {lodge.index[1]} {lodge.iloc[1]:.2f}"], ["추자면"]),
    ("Q16", "음식점 폐업률 순위 알려줘", "ok", ["compare_rank"], ["순위를 내지 않습니다", f"일도1동 폐업률 {close_3y('일도1동')}%", f"구좌읍 폐업률 {close_3y('구좌읍')}%"], ["1위"]),
    ("Q17", "우리 동네 생활 진단해 줘", "clarify", [], ["어느 동네"], []),
    ("Q18", "서귀동 상권 어때?", "clarify", [], ["정방동", "천지동"], []),
    ("Q19", "내일 동문시장 매출 얼마나 나올까?", "out_of_scope", [], ["과거 기록만", "대신 이런 질문"], []),
    ("Q20", "지금 노형동 출근 시간대 혼잡해?", "out_of_scope", [], ["일 단위", "대신 이런 질문"], []),
    ("Q21", "연동 오가는 사람 구성이랑 버스는 어떻게 바뀌었나?", "ok", ["population_mix", "bus_usage"], [f"{visit('연동')}", f"{old('연동')}%", f"{F(bus('연동'))}명"], []),  # U3: 도구 2개 결합(2026-11-06 추가, Q01~Q20은 그대로)
]


def grade(mode):
    be, _, model = mode.partition(":")
    rows = []
    for qid, q, status, tools_, must, mustnot in EVAL:
        r = agent.run(q, backend=be, model=model or None)
        used = [c["name"] for t in r["trace"] if t["stage"] in ("실행", "실행 수정") for c in t["calls"] if c["ok"]]
        miss = [m for m in must if m not in r["answer"]]
        forbid = [m for m in mustnot if m in r["answer"]]
        tool_ok = tools_ is None or (set(tools_) <= set(used))
        extra_dong = [d for d in agent.tl.dongs() if d in r["answer"] and d not in q and status == "ok" and qid not in ("Q15", "Q16")]  # 질문에 없는 동네가 답에 나오면 범위를 넘은 것(순위 문항 제외)
        passed = r["status"] == status and not miss and not forbid and tool_ok and not extra_dong
        st_ = [t for t in r["trace"] if t["stage"] == "계획"]
        rows.append({"id": qid, "q": q, "pass": bool(passed), "status": r["status"], "expected_status": status, "used": used, "missing": miss, "forbidden": forbid, "extra_dong": extra_dong, "calls": len(used), "seconds": r["seconds"],
                     "first_plan_clean": bool(st_) and not st_[0].get("problems"), "replanned": any(t["stage"] == "재계획" for t in r["trace"]),
                     "code_filled": any("코드가 채웠다" in n for t in r["trace"] if t["stage"] == "계획 확정" for n in t.get("notes", [])), "llm_failed": any(t.get("source") == "LLM 실패" for t in r["trace"])})
    return rows


def main():
    path = ROOT / "eval" / "results.json"
    out = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}  # 다른 모드 결과는 남긴다
    for mode in sys.argv[1:] or ["rule"]:
        rows = grade(mode)
        out[mode] = rows
        planned = [x for x in rows if x["expected_status"] == "ok"]
        print(f"{mode}: 통과 {sum(x['pass'] for x in rows)}/{len(rows)} · 평균 {np.mean([x['seconds'] for x in planned]):.2f}초"
              f" · 1차 계획 문제 없음 {sum(x['first_plan_clean'] for x in planned)}/{len(planned)} · 재계획 {sum(x['replanned'] for x in planned)} · 코드 보충 {sum(x['code_filled'] for x in planned)} · LLM 실패 {sum(x['llm_failed'] for x in planned)} · 평균 도구 호출 {np.mean([x['calls'] for x in planned]):.1f}")
        for x in rows:
            if not x["pass"]:
                print("  실패", x["id"], x["q"], "|상태", x["status"], "|도구", x["used"], "|빠짐", x["missing"], "|금지", x["forbidden"], "|다른 동네", x["extra_dong"])
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
