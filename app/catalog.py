"""W1 자료 목록 + 지표 사전 생성 (docs/기획/05_Agent구조_v2.md 6절·14절, 2026-11-11 구현).

- 자료 목록(data/catalog.json): 센터 73종 + 공개 6종. 자료마다 축 값(공간 단위, 시간 단위, 지표 영역, 세분, 기간, 반출, 접근 경로, 담당 Sub·레시피)을 단다.
  M2 자료 매칭(Faceted)과 S0 자료 탐색(T11 답)이 이 파일을 읽는다.
  센터 자료의 축 값은 명세의 열 이름·설명에서 규칙으로 뽑는다(명세 기준, 실제 자료로 확인하지 못함).
- 지표 사전(data/metric_dict.json): 질문 Tuple의 지표 → 표·열·집계·축(공개 경로) + 센터 경로 자료.
실행: .venv/bin/python app/catalog.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import qtuple as Q  # noqa: E402

OUT_CAT, OUT_MET = ROOT / "data" / "catalog.json", ROOT / "data" / "metric_dict.json"

SPACE_RULES = [(r"격자", "격자"), (r"정류(소|장)", "정류소"), (r"노선", "노선"), (r"링크", "도로 링크"), (r"행정동|읍면동|emd", "읍면동"),
               (r"법정동", "법정동"), (r"관측소|지점", "관측소"), (r"시군구|지역구분|시도|지역", "시·지역구분")]
TIME_RULES = [(r"시간대|시간\b|,\s*시간|base_hour|일시|시각", "시간"), (r"날짜|일자|승차일|배출일|기준일", "일"), (r"년월|,\s*월\b|^월|\b월\b", "월")]
DOMAIN_RULES = [(r"카드", "카드 매출"), (r"포스|POS|외식업", "외식업 매출(POS)"), (r"유동인구", "유동인구"), (r"버스|승하차", "버스 이용"),
                (r"와이파이", "와이파이"), (r"날씨|기상|관측소", "날씨"), (r"교통량|도로", "교통량"), (r"폐기물|쓰레기|종량제", "폐기물"),
                (r"거래처|기업|매입|매출처|판매", "기업 거래"), (r"통신|기지국", "통신")]
BREAK_RULES = [(r"연령", "연령대"), (r"성별", "성별"), (r"국적", "국적"), (r"이용자\s*구분|이용자구분|사용자구분", "이용자구분"), (r"업종", "업종"),
               (r"요일", "요일"), (r"관광구분|내국인|외국인", "관광객 구분"), (r"시간대", "시간대"), (r"승하차유형", "승하차")]
RECIPES = {"유동인구": ["R1", "R3", "R5", "R6", "R8"], "버스 이용": ["R2", "R8"], "카드 매출": ["R9"], "외식업 매출(POS)": ["R9"]}


def first(rules, text, default):
    return next((v for p, v in rules if re.search(p, text)), default)


def xlsx_columns():
    """원본 명세 엑셀(시트마다 자료 1종)에서 데이터명 → 한글 열 이름 목록. CSV에 열이 빠진 자료를 채운다."""
    import zipfile
    import xml.etree.ElementTree as ET
    m = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(ROOT / "data" / "raw" / "제주빅데이터센터_데이터명세_v12_20260128.xlsx")
    ss = ["".join(t.text or "" for t in si.iter(m + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(m + "si")]
    out = {}
    for n in z.namelist():
        if not n.startswith("xl/worksheets/sheet"):
            continue
        rows = []
        for row in ET.fromstring(z.read(n)).iter(m + "row"):
            v = [ss[int(c.find(m + "v").text)] if c.get("t") == "s" else c.find(m + "v").text for c in row.findall(m + "c") if c.find(m + "v") is not None]
            rows.append(v)
        name = next((r[1].strip() for r in rows if len(r) > 1 and r[0].strip() == "데이터명(한글)"), None)
        hdr = next((i for i, r in enumerate(rows) if r and r[0].strip() == "No" and len(r) > 2), None)
        if name and hdr is not None:
            out[name] = [r[2].strip() for r in rows[hdr + 1:] if len(r) > 2 and r[0].strip().isdigit()]
    return out


def center_rows():
    c = pd.read_csv(ROOT / "docs" / "조사" / "센터데이터_목록.csv")
    xc = xlsx_columns()
    rows = []
    for i, r in c.iterrows():
        name, cols, desc = str(r["데이터명"]), str(r["컬럼"]) if r["컬럼"] == r["컬럼"] else "", str(r["설명"])
        if not cols and name in xc:
            cols = ", ".join(xc[name])  # CSV에 빠진 열을 원본 명세 엑셀에서 채움
        text = f"{name} {cols}"
        period = re.search(r"기간:\s*(.+?)(?:\s{2,}-|\s*$)", desc)
        dom = first(DOMAIN_RULES, text, "기타")
        rows.append({
            "id": f"C{r['No']}" if r["No"] != "-" else f"C-ref{i}", "no": r["No"], "name": name, "source": "센터", "category": r["카테고리"],
            "space": first(SPACE_RULES, cols or name, "제주 전체" if cols else "미확인(명세에 열 없음)"),
            "time": first(TIME_RULES, cols, "단면") if cols else ("월" if "월 기준" in desc else "일" if "일일" in desc or "일 기준" in desc else "미확인(명세에 열 없음)"),
            "domain": dom, "breakdown": sorted({v for p, v in BREAK_RULES if re.search(p, cols)}),
            "period": period.group(1).strip() if period else None, "export": r["반출"], "columns": cols or None,
            "access": "센터 DB(SQL, 파티션 pt_year·pt_month) — 명세 기준, 실행 미검증", "subs": ["S1", "S5", "S2"] + (["S3"] if dom in RECIPES else []),
            "recipes": RECIPES.get(dom, []), "facet_source": "명세 열 이름·설명에서 규칙으로 추출"})
    return rows


def public_rows():
    meta = json.loads((ROOT / "data" / "tables" / "meta.json").read_text(encoding="utf-8"))
    return [
        {"id": "P583", "no": "583", "name": "유동인구(읍면동, 일)", "source": "공개(데이터허브 API)", "space": "읍면동", "time": "일", "domain": "유동인구",
         "breakdown": ["연령대", "성별"], "period": f"2023-11-04~{meta.get('pop_last')}(표), 수집 계속", "export": "가능", "recipes": ["R1", "R3", "R5", "R6"],
         "access": "data/tables/pop_month.parquet·pop_age.parquet, data/interim/api/583"},
        {"id": "P743", "no": "743", "name": "버스 정류소 이용(일)", "source": "공개(데이터허브 파일)", "space": "정류소→읍면동", "time": "일", "domain": "버스 이용",
         "breakdown": ["이용자구분"], "period": f"~{meta.get('bus_last')}", "export": "가능", "recipes": ["R2"], "access": "data/tables/bus_month.parquet, data/raw/이용자유형별버스정류소이용인원현황.csv"},
        {"id": "P612", "no": "612", "name": "버스 정류소 좌표", "source": "공개(데이터허브 API)", "space": "정류소", "time": "단면", "domain": "버스 이용", "breakdown": [],
         "period": "단면", "export": "가능", "recipes": [], "access": "data/interim/api/612_stations.parquet, data/interim/station_dong.parquet"},
        {"id": "P780", "no": "780", "name": "음식점 인허가·폐업", "source": "공개(데이터허브·행안부 API)", "space": "법정동→읍면동", "time": "일", "domain": "점포 개업·폐업",
         "breakdown": ["업종"], "period": f"1960~{meta.get('rest_last')}", "export": "가능", "recipes": ["R4", "R7"], "access": "data/tables/rest_events.parquet·close_3y.parquet·km.parquet"},
        {"id": "P793", "no": "793", "name": "상가(상권) 정보", "source": "공개(데이터허브·공공데이터포털)", "space": "읍면동", "time": "단면", "domain": "점포 수",
         "breakdown": ["업종"], "period": "2025-09 단면", "export": "가능", "recipes": ["R5"], "access": "data/tables/biz.parquet"},
        {"id": "P579", "no": "579/ASOS", "name": "일별 기상", "source": "공개(데이터허브 API·기상청)", "space": "관측소→섬 중앙값", "time": "일", "domain": "날씨",
         "breakdown": [], "period": "2023-04-01~2026-11-09", "export": "가능", "recipes": ["R1", "R3"], "access": "data/interim/api/579, data/interim/api/asos"},
    ]


METRICS = {  # 05 문서 14절(지표 사전). public: 공개 경로 표·열·집계·축 / center: 센터 경로 자료(명세 기준)
    "점포수": {"public": {"table": "biz", "column": "count", "agg": "합계", "space": "dong", "time": "단면", "axes": ["major", "middle", "minor"]}, "center": None, "coverage": "793 전 업종"},
    "특화계수": {"public": {"table": "biz", "column": "count", "agg": "(동네 업종 비중) ÷ (제주 업종 비중)", "space": "dong", "time": "단면", "axes": ["major", "minor"]}, "center": None},
    "개업수": {"public": {"table": "rest_events", "column": "count", "agg": "합계(kind=open)", "space": "dong", "time": "year", "axes": ["category"]}, "center": None, "coverage": "음식점만"},
    "폐업수": {"public": {"table": "rest_events", "column": "count", "agg": "합계(kind=close)", "space": "dong", "time": "year", "axes": ["category"]}, "center": None, "coverage": "음식점만"},
    "폐업률": {"public": {"table": "close_3y", "column": "rate_pct", "agg": "값(구간 lo_pct·hi_pct)", "space": "dong", "time": "2022~2024 묶음", "axes": []}, "center": None, "coverage": "음식점만"},
    "5년생존율": {"public": {"table": "km", "column": "survival_pct", "agg": "year=5 값(year는 경과 연수 1~5)", "space": "dong", "time": "코호트 2015-01~2020-08", "axes": []}, "center": None},
    "조건부생존": {"public": {"table": "km", "column": "survival_pct", "agg": "year=5 ÷ year=2", "space": "dong", "time": "코호트", "axes": []}, "center": None},
    "일평균방문": {"public": {"table": "pop_month", "column": "visit", "agg": "합계 ÷ days", "space": "dong", "time": "ym", "axes": []}, "center": "C4-11"},
    "방문거주비": {"public": {"table": "pop_month", "column": "visit÷resd", "agg": "비", "space": "dong", "time": "ym", "axes": []}, "center": "C4-11"},
    "근무거주비": {"public": {"table": "pop_month", "column": "work÷resd", "agg": "비", "space": "dong", "time": "ym", "axes": []}, "center": "C4-11"},
    "거주연령구성": {"public": {"table": "pop_age", "column": "resd", "agg": "비중", "space": "dong", "time": "year(2023·2025 부분 연도)", "axes": ["ageGroup", "gender"]}, "center": "C4-11"},
    "방문연령구성": {"public": {"table": "pop_age", "column": "visit", "agg": "비중", "space": "dong", "time": "year", "axes": ["ageGroup", "gender"]}, "center": "C4-11"},
    "고령비중": {"public": {"table": "pop_age", "column": "resd", "agg": "60대 이상 비중", "space": "dong", "time": "year", "axes": []}, "center": "C4-11"},
    "청년비중": {"public": {"table": "pop_age", "column": "resd", "agg": "20~30대 비중", "space": "dong", "time": "year", "axes": []}, "center": "C4-11"},
    "버스일평균": {"public": {"table": "bus_month", "column": "n", "agg": "합계 ÷ days", "space": "dong", "time": "ym", "axes": ["user_type"]}, "center": "C3-04"},
    "경로비중": {"public": {"table": "bus_month", "column": "n", "agg": "user_type=경로 비중", "space": "dong", "time": "ym", "axes": []}, "center": "C3-04"},
    "경로일평균": {"public": {"table": "bus_month", "column": "n", "agg": "user_type=경로 합계 ÷ days", "space": "dong", "time": "ym", "axes": []}, "center": "C3-04"},
    "정류소일이용": {"public": {"table": "raw 743", "column": "user_count", "agg": "정류소별 합계 ÷ 일수", "space": "station_name", "time": "base_date", "axes": ["user_type"]}, "center": "C3-04"},
    "시간대방문": {"public": None, "center": "C4-11", "note": "센터에서만 가능"},
    "시간대버스": {"public": None, "center": "C3-04", "note": "센터에서만 가능"},
    "매출": {"public": None, "center": "C1-07", "note": "센터에서만 가능(반출 불가, 집계만)"},
    "자료목록": {"public": {"table": "catalog", "column": "-", "agg": "검색", "space": "-", "time": "-", "axes": []}, "center": None},
}


def main():
    cat = center_rows() + public_rows()
    # 센터 핵심 자료는 명세 열로 직접 확인한 값으로 덮어쓴다(05 문서 6절)
    fix = {"C4-11": {"space": "읍면동", "time": "시간"}, "C3-04": {"space": "정류소", "time": "시간"}, "C3-02": {"space": "노선", "time": "시간"},
           "C1-07": {"space": "읍면동", "time": "월"}, "C1-14": {"space": "법정동", "time": "월"}, "C5-02": {"space": "관측소", "time": "일"}}
    for r in cat:
        r.update(fix.get(r["id"], {}))
    assert len(cat) == 79 and all(r["space"] and r["time"] for r in cat)
    OUT_CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [m for m in METRICS if m not in Q.METRICS]
    missing = [m for m in Q.METRICS if m not in METRICS]
    OUT_MET.write_text(json.dumps(METRICS, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print({"catalog": len(cat), "space": Counter(r["space"] for r in cat), "time": Counter(r["time"] for r in cat), "domain": Counter(r["domain"] for r in cat),
           "metric_dict": len(METRICS), "사전에 없는 지표": bad, "사전에서 빠진 지표": missing})


if __name__ == "__main__":
    main()
