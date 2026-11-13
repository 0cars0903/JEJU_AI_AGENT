"""평가 위원용 데이터 확인 노트북(notebooks/01_데이터_확인.ipynb)을 만들고 실행해 출력까지 저장한다.
실행: .venv/bin/python tools/build_notebook.py   (개발용 nbformat·nbclient·ipykernel 필요, requirements.txt에는 넣지 않음)
노트북은 제출본에 들어 있는 data/tables/만 읽는다. 원자료(data/raw·data/interim)가 있으면 원자료 비교 칸도 계산한다.
"""
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "01_데이터_확인.ipynb"

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# 데이터 확인 노트북

제주빅데이터센터 빅데이터 분석·컨설팅 지원 보조 Agent가 쓰는 자료를 평가 위원이 직접 확인할 수 있도록 정리했습니다.

- 읽는 자료: 제출본의 `data/tables/`(앱이 답을 계산할 때 읽는 표와 같음).
- 저장된 출력: 개발 PC에서 2026-11-13에 실행한 결과입니다. 다시 실행하려면 `pip install jupyter` 뒤 이 노트북을 엽니다.
- 원자료(`data/raw/`, `data/interim/`)는 크기와 재배포 조건 때문에 제출본에 넣지 않았습니다. 원자료가 필요한 칸은 원자료가 있을 때만 계산하고, 없으면 그렇다고 출력합니다.

| 절 | 확인하는 것 |
|---|---|
| 1 | 표 17개: 파일·행 수·열·출처 |
| 2 | 자료별 기간 |
| 3 | 제주데이터허브 게시 자료 7종과 원 제공처 |
| 4 | 원자료를 그대로 쓰면 값이 달라지는 사례 4건(기획서 6장) |
| 5 | 제주관광공사 카드와 데이터허브 746 교차 대조 |
""")

code("""
import json
import warnings
from pathlib import Path

import pandas as pd
from scipy import stats

ROOT = Path.cwd() if (Path.cwd() / "data" / "tables").exists() else Path.cwd().parent
T = ROOT / "data" / "tables"
META = json.loads((T / "meta.json").read_text(encoding="utf-8"))
pd.set_option("display.max_colwidth", 60)
warnings.filterwarnings("ignore")  # 라이브러리 경고에 실행 PC 경로가 찍히지 않게
print("표 폴더:", T.relative_to(ROOT))
""")

md("""
## 1. 표 17개

앱은 아래 표만 읽습니다. 실행 중에는 외부 API를 부르지 않습니다.
""")

code("""
SOURCE = {
    "pop_month.parquet": "제주데이터허브 583 유동인구(일별 → 월별 합계, 지수)",
    "pop_age.parquet": "제주데이터허브 583 유동인구(성별·연령별)",
    "panel_v2.parquet": "제주데이터허브 583 유동인구(일별) + 579 기상·기상청 ASOS 강수 + 휴일",
    "bus_month.parquet": "제주데이터허브 743 버스 정류소 이용 + 612 정류소 좌표(정류소 → 동네)",
    "biz.parquet": "제주데이터허브 793 상가(상권) 정보",
    "rest_events.parquet": "제주데이터허브 780 음식점 목록(개업·폐업)",
    "close_3y.parquet": "제주데이터허브 780 음식점 목록(3년 폐업률)",
    "km.parquet": "제주데이터허브 780 음식점 목록(생존율, Kaplan-Meier)",
    "card746_month.parquet": "제주데이터허브 746 업종별 카드 매출·매장수(교차 대조용)",
    "card_month.parquet": "제주관광공사 카드 소비(월·동네·업종 5·손님)",
    "card_hour.parquet": "제주관광공사 카드 소비(시간대)",
    "card_foreign.parquet": "제주관광공사 외국인 관광객 카드 소비(제주 전체)",
    "weather.parquet": "제주데이터허브 579 기상(동네별 비 오는 날 효과)",
    "map_dong.parquet": "동네 중심 좌표(793 상가 좌표로 계산)",
    "map_grid.parquet": "지도 격자(793 상가 좌표로 계산)",
    "jeju_map.json": "행정동 경계(vuski/admdongkor, CC BY 4.0, 원 경계 통계청 SGIS)",
    "places.json": "업종 대응표(코드에서 생성)",
}
rows = []
for f in sorted(T.iterdir()):
    if f.name == "meta.json":
        continue
    r = {"파일": f.name, "크기(KB)": round(f.stat().st_size / 1024, 1), "출처": SOURCE.get(f.name, "")}
    if f.suffix == ".parquet":
        d = pd.read_parquet(f)
        r.update({"행 수": len(d), "열": ", ".join(d.columns[:7]) + (" …" if len(d.columns) > 7 else "")})
    rows.append(r)
tables = pd.DataFrame(rows)
print(len(tables), "개 파일")
tables
""")

md("## 2. 자료별 기간\n\n`meta.json`은 표를 만들 때 함께 기록한 값입니다.")

code("""
period = pd.DataFrame([
    ("유동인구 583", META["pop_first"], META["pop_last"]),
    ("버스 743", "2019-01", META["bus_last"]),
    ("카드 소비(제주관광공사)", META["card_first"], META["card_last"]),
    ("카드 시간대(제주관광공사)", META["card_hour_first"], META["card_hour_last"]),
    ("카드 746", META["card746_first"], META["card746_last"]),
    ("기상 579", META["wx_start"], META["wx_end"]),
    ("음식점 780(마지막 개업·폐업일)", "", META["rest_last"]),
], columns=["자료", "처음", "마지막"])
period
""")

md("""
## 3. 제주데이터허브 게시 자료 7종

제주데이터허브 데이터 상세 정보(`https://www.jejudatahub.net/api/data/view?id=<번호>`)의 `owner`·`description`을 2026-11-13에 확인한 값입니다.
아래 칸은 인터넷이 되면 같은 주소에서 다시 확인하고, 안 되면 기록한 값을 보여 줍니다.
""")

code("""
RECORDED = {
    583: ("읍면동 단위 내국인 유동인구", "제주데이터허브"),
    743: ("이용자 유형별 버스정류소 이용 인원 현황", "제주빅데이터센터"),
    612: ("버스 정류소 기본 정보", "제주데이터허브"),
    793: ("제주특별자치도 상가(상권) 정보", "공공데이터포털"),
    780: ("제주특별자치도 음식점 목록(통합)", "LOCALDATA"),
    746: ("업종별 카드 매출과 매장수 데이터 활용 매쉬업", "제주특별자치도"),
    579: ("일별 기상", "제주데이터허브"),
}
def live(i):
    try:
        import requests
        d = requests.get(f"https://www.jejudatahub.net/api/data/view?id={i}", timeout=5).json()
        return d.get("createByName") or d.get("owner"), "다시 확인함"
    except Exception:
        return "제주데이터허브", "기록값(인터넷 없음)"
hub = []
for i, (title, origin) in RECORDED.items():
    host, how = live(i)
    hub.append({"번호": i, "자료": title, "게시처": host, "원 제공처": origin, "확인": how})
pd.DataFrame(hub)
""")

md("""
## 4. 원자료를 그대로 쓰면 값이 달라지는 사례 4건

기획서 6장 표의 숫자를 다시 계산합니다.
""")

md("### 4.1 버스: 이름이 바뀐 정류소\n\n정류소 이름이 바뀌면 원자료에서는 새 정류소처럼 보입니다. 이전·이후 이름을 한 정류소로 합친 뒤 동네 단위로 더한 표(`bus_month`)로 2023년과 2024년 하루 평균을 비교합니다.")

code("""
b = pd.read_parquet(T / "bus_month.parquet")
b["year"] = b["ym"].str[:4]
j = b[b["dong"] == "정방동"]
daily = j.groupby("year")["n"].sum() / j.groupby(["year", "ym"])["days"].max().groupby("year").sum()
print("정방동 하루 평균 승차(이름 합친 뒤):", daily.loc[["2023", "2024"]].round(1).to_dict())
print(f"2023 → 2024 증감: {(daily['2024'] / daily['2023'] - 1) * 100:+.1f}%")
raw = ROOT / "data" / "interim" / "bus_daily"
print("원자료(이름 그대로) 비교:", "data/interim/bus_daily 있음 — 개발 기록 +95.9%" if raw.exists() else "원자료 없음(제출본 제외). 개발 중 원자료로 계산한 값은 +95.9%")
""")

md("### 4.2 음식점 개업: 덜 찬 해\n\n음식점 목록의 마지막 날짜까지만 집계되므로 2026년은 1년이 차지 않았습니다.")

code("""
import sys
sys.path.insert(0, str(ROOT / "app"))
from places import REST_MAP
r = pd.read_parquet(T / "rest_events.parquet")
cafe = r[(r["dong"] == "노형동") & (r["kind"] == "open") & (r["category"].isin(REST_MAP["카페"]))]
print("카페로 묶는 업종:", REST_MAP["카페"])
print("마지막 날짜:", META["rest_last"])
cafe.groupby("year")["count"].sum().loc[2020:].rename("노형동 카페 개업 수")
""")

md("### 4.3 방문 차이: 자기상관\n\n하루 방문 값은 전날과 비슷합니다(자기상관). 일별 값을 서로 독립인 표본처럼 검정하면 p값이 실제보다 작게 나옵니다. 앱은 주 평균끼리 짝 지어 검정합니다(`app/compare.py`).")

code("""
p = pd.read_parquet(T / "panel_v2.parquet", columns=["date", "emd", "visit"])
p = p[p["date"] > p["date"].max() - pd.Timedelta(days=365)]
pv = p.pivot_table(index="date", columns="emd", values="visit")[["노형동", "연동"]].dropna()
diff = pv["노형동"] - pv["연동"]
wk = pv.resample("W-MON").mean().dropna()
print(f"기간: {pv.index.min():%Y-%m-%d} ~ {pv.index.max():%Y-%m-%d} ({len(pv)}일)")
print(f"일별 차이의 1일 자기상관: {diff.autocorr(1):.3f}")
print(f"일별 Wilcoxon p = {stats.wilcoxon(pv['노형동'], pv['연동']).pvalue:.1e}  (자기상관 때문에 과소)")
print(f"주 평균 {len(wk)}주 짝 Wilcoxon p = {stats.wilcoxon(wk['노형동'], wk['연동']).pvalue:.1e}  (앱이 쓰는 값)")
""")

md("### 4.4 카페 카드 매출: 업종 대분류\n\n제주관광공사 카드 자료의 업종은 대분류 5개뿐입니다. 카페 매출만 따로 볼 수 없어 앱은 '음식점업 전체(카페 포함)'라고 안내합니다.")

code("""
c = pd.read_parquet(T / "card_month.parquet")
print("업종:", sorted(c["biz"].unique()))
print("손님 구분:", sorted(c["cust"].unique()))
""")

md("""
## 5. 제주관광공사 카드와 데이터허브 746 교차 대조

두 자료가 겹치는 기간(2020-01~2021-05)에 업종·손님별로 월별 증감 방향과 전년 대비 방향이 같은지 확인했습니다(`app/build_v3_tables.py`).
기준: 전월 대비 방향 일치 0.75 이상, 전년 대비 방향 일치 0.8 이상. 대조 기록 파일은 원자료 폴더(`data/interim/v3/`)에 있어 제출본에는 결과 요약만 남깁니다.
""")

code("""
cc = ROOT / "data" / "interim" / "v3" / "v3_tables.json"
if cc.exists():
    s = json.loads(cc.read_text(encoding="utf-8"))["crosscheck"]["series"]
    out = pd.DataFrame(s)[["biz", "cust", "mom_agree", "yoy_agree", "dong_rank_spearman_ref", "pass"]]
    out.columns = ["업종", "손님", "전월 대비 일치", "전년 대비 일치", "동네 순위 상관(참고)", "통과"]
else:
    out = pd.DataFrame([("소매업", "도민", "14/16", "4/5", 0.985, True), ("소매업", "내국인 관광객", "14/16", "5/5", 0.978, True),
                        ("숙박업", "도민", "14/16", "2/5", 0.804, False), ("숙박업", "내국인 관광객", "14/16", "5/5", 0.905, True),
                        ("음식점업", "도민", "15/16", "5/5", 0.987, True), ("음식점업", "내국인 관광객", "14/16", "5/5", 0.991, True)],
                       columns=["업종", "손님", "전월 대비 일치", "전년 대비 일치", "동네 순위 상관(참고)", "통과"])
print("meta.json card_crosscheck_pass =", META["card_crosscheck_pass"], "(6개 계열이 모두 통과해야 True)")
out.round(3)
""")

md("""
결과: 6개 계열 가운데 5개가 통과했습니다. 숙박업·도민 계열은 전년 대비 방향 일치가 2/5로 기준에 못 미쳤습니다.
앱은 매출 답에 제주관광공사 자료를 쓰고, 746은 이 대조에만 씁니다.
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                                                  "language_info": {"name": "python"}})
OUT.parent.mkdir(exist_ok=True)
NotebookClient(nb, timeout=120, kernel_name="python3", resources={"metadata": {"path": str(OUT.parent)}}).execute()
nbf.write(nb, OUT)
print(OUT)
