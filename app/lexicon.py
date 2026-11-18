"""질의 파악용 사전 9종 생성 (2026-11-11 사용자 지시: "지명 사전처럼 미리 사전으로 구성할 필요성이 있는 리스트 도출").

제주어는 지원 범위에서 뺀다(사용자 결정). 사전은 표준어·흔한 구어·줄임말만 담는다.
자료에서 자동으로 만드는 사전(근거 파일이 있는 것)과 손으로 쓰는 사전(근거: 05 문서 지표 사전·질의 유형 정의)을 나눈다.
시험 문항(021·022·023)은 보지 않고 만든다.
산출: data/lexicon/*.json, 요약 data/lexicon/summary.json
실행: .venv/bin/python app/lexicon.py
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import qtuple as Q  # noqa: E402
from places import REST_MAP  # noqa: E402

IN, OUT = ROOT / "data" / "interim", ROOT / "data" / "lexicon"


def majority(pairs):
    """이름 → 행정동 후보 빈도. 70% 이상 한 동네면 그 동네, 아니면 후보 목록(되묻기용)."""
    out = {}
    for name, cnt in pairs.items():
        tot = sum(cnt.values())
        top, n = cnt.most_common(1)[0]
        out[name] = {"dong": top, "share": round(n / tot, 2)} if n / tot >= 0.7 else {"candidates": [d for d, _ in cnt.most_common(4)]}
    return out


SUFFIX = r"(남항|북항|동항|서항|항|포구|해수욕장|해변|초등학교|중학교|고등학교|학교|오름|공원|시장|마을|리사무소|복지회관|주민센터|사무소|우체국|농협|지구|부영|아파트|[0-9]+차|빌라|단지|관광단지|입구|종점|회관|성당|교회|사거리|삼거리)$"


def build_places():
    pairs = defaultdict(Counter)
    src = Counter()
    # ① 기존 법정동 → 행정동(places.json)
    for k, v in json.loads((ROOT / "data" / "tables" / "places.json").read_text(encoding="utf-8")).items():
        for d in v:
            pairs[k][d] += 1
            if k.endswith(("동", "리")) and len(k) >= 3:
                pairs[k[:-1]][d] += 1  # '강정동' → '강정'(법정동 어간)
        src["법정동(places.json)"] += 1
    # ② 상가(793) 지번 주소의 리 이름
    s = pd.read_parquet(IN / "stores.parquet", columns=["행정동명", "지번주소"])
    ri = s["지번주소"].str.extract(r"\s([가-힣0-9]+리)\s")[0]
    for name, d in zip(ri, s["행정동명"]):
        if isinstance(name, str):
            pairs[name][d] += 1
            pairs[name[:-1]][d] += 1  # '상귀리' → '상귀'
    src["리 이름(793 지번주소)"] = int(ri.dropna().nunique())
    # ③ 정류소명(612·743 매핑표): 괄호·방향·'입구' 등을 떼고 관광지·시설 이름을 살린다
    sd = pd.read_parquet(IN / "station_dong.parquet")
    sd = sd[sd["dong"].notna()]
    n0 = 0
    for name, d, w in zip(sd["station_name"], sd["dong"], sd["weight"]):
        base = re.sub(r"\(.*?\)|\[.*?\]", "", str(name)).strip()
        base = re.sub(r"(입구|사거리|삼거리|오거리|교차로|정류장|정류소|버스정류장|동쪽|서쪽|남쪽|북쪽|방면)$", "", base).strip()
        if len(base) >= 2:
            ww = float(w) if w == w else 1
            pairs[base][d] += ww
            n0 += 1
            # 시설 접미어를 떼어 어간도 등록(예: 모슬포남항 → 모슬포, 삼화지구 → 삼화, 표선해수욕장 → 표선)
            stem = base
            for _ in range(2):
                stem = re.sub(SUFFIX, "", stem).strip()
            if 2 <= len(stem) < len(base):
                pairs[stem][d] += ww
            if " " in base:
                pairs[base.split()[0]][d] += ww
    src["정류소명(612·743)"] = int(sd["station_name"].nunique())
    # ④ 행정동 이름과 '동' 뺀 이름, 기존 별칭
    for d in Q.DONGS:
        pairs[d][d] += 100
    for k, d in Q.DONG_ALIAS.items():
        pairs[k][d] += 100
    places = majority(pairs)
    # 출처가 확실한 이름(행정동·법정동·리와 그 어간): 2글자여도 지명으로 인정한다(qparse.place_ok)
    trusted = set(Q.DONGS) | set(Q.DONG_ALIAS)
    for k in json.loads((ROOT / "data" / "tables" / "places.json").read_text(encoding="utf-8")):
        trusted |= {k, k[:-1] if k.endswith(("동", "리")) and len(k) >= 3 else k}
    trusted |= {n for n in ri.dropna().unique()} | {n[:-1] for n in ri.dropna().unique() if len(n) >= 3}
    (OUT / "places_trusted.json").write_text(json.dumps(sorted(trusted), ensure_ascii=False), encoding="utf-8")
    for k in trusted:
        if k[:-0] and k not in pairs and k[:-1] in pairs:
            pass
    # 동네 이름 자체와 너무 흔한 일반어는 뺀다
    stop = {"제주", "서귀포", "제주시", "서귀포시", "시청", "시장", "학교", "병원", "마을", "중앙", "입구", "농협", "우체국"}
    places = {k: v for k, v in places.items() if k not in stop and len(k) >= 2}
    return places, src


def build_biz():
    s = pd.read_parquet(IN / "stores.parquet", columns=["상권업종대분류명", "상권업종중분류명", "상권업종소분류명"])
    rest_group = {c: g for g, cats in REST_MAP.items() if cats for c in cats}
    biz = {}
    for (a, b, c), n in s.value_counts().items():
        biz[c] = {"major": a, "middle": b, "stores_793": int(n), "rest_group": rest_group.get(c)}
    r = pd.read_parquet(IN / "restaurants.parquet", columns=["업종구분소분류"])
    for c, n in r["업종구분소분류"].value_counts().items():
        biz.setdefault(c, {}).update({"rest_780": int(n), "rest_group": rest_group.get(c, "기타")})
    # 손으로 쓰는 구어 동의어(표준어) → 대표 업종
    colloquial = {"카페": ["커피숍", "커피집", "디저트카페", "베이커리카페", "빵집", "베이커리"], "한식": ["백반집", "고깃집", "고기집", "국밥집", "한식당"],
                  "일식": ["초밥집", "스시", "일식집", "돈가스"], "횟집": ["횟집", "회센터", "횟집"], "중식": ["중국집", "짜장면집", "중식당"],
                  "치킨": ["치킨집", "통닭집"], "분식": ["분식집", "김밥집", "떡볶이집"], "주점": ["술집", "호프", "포차", "이자카야", "와인바", "칵테일바", "라운지바"],  # 2026-11-14: '바' 한 글자는 '알려바·해바'의 말끝과 겹쳐 뺌,
                  "편의점": ["편의점"], "음식점": ["음식점", "식당", "밥집", "외식업", "요식업"], "숙박": ["숙박업소", "숙박업", "숙박", "펜션", "게스트하우스", "호텔", "민박", "숙소"], "소매": ["소매점", "소매업", "소매", "작은 가게", "구멍가게", "슈퍼", "마트"],
                  "미용": ["미용실", "헤어샵", "네일샵"], "학원": ["학원", "교습소"], "약국": ["약국"], "병원": ["병원", "의원", "치과", "한의원"]}
    # 지표별 지원 범위: 점포 수·특화계수는 793 전 업종, 개업·폐업·생존은 780 음식점만
    coverage = {"점포수": "793 상가 전 업종(소분류 %d종)" % sum(1 for v in biz.values() if "stores_793" in v),
                "특화계수": "793 상가 전 업종", "개업수": "780 음식점(휴게·일반)만", "폐업수": "780 음식점만", "폐업률": "780 음식점만", "5년생존율": "780 음식점만"}
    return {"categories": biz, "colloquial": colloquial, "coverage_by_metric": coverage}


METRIC_WORDS = {  # 지표 표현 → 지표(05 문서 14절 지표 사전 이름)
    "점포수": ["몇 곳", "몇 개", "몇 군데", "가게 수", "점포 수", "매장 수", "업소 수", "얼마나 있"],
    "특화계수": ["많은 편", "비중이 높", "몰려 있", "특화", "집중"],
    "개업수": ["개업", "새로 생긴", "새로 문 연", "오픈", "창업한", "새로 많이 생긴", "새로 제일 많이 생긴", "새로 가장 많이 생긴", "새로 생기는", "새로 많이 여는", "새로 여는", "새로 열", "새로 많이 열"], "폐업수": ["폐업", "문 닫은", "문 닫는", "없어진", "사라진"],
    "폐업률": ["폐업률", "문 닫는 비율", "망하는 비율", "폐업 위험", "폐업 확률", "폐업 비율"], "5년생존율": ["생존율", "오래 버티", "살아남", "몇 년 가"],
    "일평균방문": ["유동인구", "방문", "오가는 사람", "사람이 많", "붐비", "북적", "손님", "인파", "사람이 몰리", "사람 몰리", "사람이 많이 몰리", "사람들이 몰리", "인파가 몰리", "발길", "몰리는", "많이 몰리"],  # 2026-11-17: '사람이 몰리는'을 점포 수로 읽던 결함(가게가 '몰려 있'은 특화계수)
    "방문거주비": ["외부에서 오는", "방문객 비율"], "근무거주비": ["직장인", "출근하는", "근무 인구"],
    "거주연령구성": ["사는 사람 나이", "주민 연령", "거주 연령"], "방문연령구성": ["오가는 사람 나이", "방문객 연령"],
    "고령비중": ["어르신 비율", "노인 비율", "고령"], "청년비중": ["청년 비율", "젊은 사람 비율", "20대", "30대"],
    "버스일평균": ["버스 이용", "버스 타는", "버스 승객", "대중교통 이용", "버스", "대중교통"], "경로일평균": ["어르신 버스", "노인 버스", "경로 승객"],
    "정류소일이용": ["정류장 이용", "정류소 이용", "정류장별"], "시간대방문": ["몇 시", "시간대", "피크 시간", "가장 붐비는 시간"],
    "매출": ["매출", "매출액", "카드 사용", "소비", "장사 잘", "벌이"],
    "시장추이": ["시장", "시장 규모", "업계", "업종 전망"], "매출성장": ["뜨는", "요즘 뜨는", "많이 는", "많이 오른", "많이 늘어난", "성장하는", "급성장"],
    "업종비교": ["업종별", "어떤 업종", "무슨 업종", "업종 중에", "업종끼리"],
    "이용건수": ["결제 건수", "이용 건수", "카드 건수", "몇 건"], "건당금액": ["건당", "객단가", "1건당", "한 번에 얼마", "결제 금액"],
    "관광객비중": ["관광객 비중", "관광객 손님", "관광객이 많", "관광객 매출", "도민 손님", "관광객 비율",
              "손님 중에 관광객", "손님 중 관광객"],  # 문서 20 A1: '손님'만 읽어 방문으로 답하던 말
    "외국인매출": ["외국인 매출", "외국인 손님", "외국인 관광객 소비", "외국인 소비", "외국인 관광객 매출", "외국 손님", "외국인 결제", "외국 관광객 결제", "외국 손님들 결제"], "자료목록": ["자료 있", "데이터 있", "데이터셋", "어떤 자료", "자료 목록"],
}
POP_WORDS = {"어르신": ["어르신", "노인", "고령자", "65세 이상", "60대 이상"], "청년": ["청년", "젊은 사람", "2030", "20대", "30대"],
             "어린이": ["어린이", "아이들", "아동"], "청소년": ["청소년", "학생", "10대"]}
COND_WORDS = {"비": ["비 오는", "비 올", "비 오면", "비가 오", "우천", "장마", "호우", "소나기"], "맑음": ["맑은 날", "화창한"],
              "주말": ["주말", "토요일", "일요일", "토일"], "평일": ["평일", "주중"], "여름": ["여름", "7월", "8월", "휴가철"], "겨울": ["겨울", "12월", "1월", "2월"],
              "봄": ["봄", "벚꽃"], "가을": ["가을", "단풍"], "성수기": ["성수기", "관광철", "피서철"], "비수기": ["비수기"], "강풍": ["바람 센", "강풍", "태풍"],
              "공휴일": ["공휴일", "빨간 날", "연휴", "명절", "설날", "추석", "어린이날", "징검다리"]}
TIME_WORDS = {"최근1년": ["최근 1년", "요즘", "요새", "올해", "작년부터"], "최근3년": ["최근 3년", "지난 3년", "몇 년 사이", "2~3년"],
              "최근5년": ["최근 5년", "지난 5년"], "다음분기": ["다음 분기", "3개월 뒤", "석 달 뒤"], "다음달": ["다음 달", "담달", "한 달 뒤"],
              "다음주": ["다음 주", "다음주", "일주일 뒤"], "지금": ["지금", "현재 실시간", "실시간"]}
INTENT_WORDS = {  # 질의 유형 표현(동사·어미 중심). 표준어·흔한 구어만
    "T2": ["비교", "어디가 더", "중에 어디", "차이", "vs"], "T3": ["순위", "가장 많은 동네", "제일 많은 곳", "상위", "top"],
    "T4": ["늘고", "늘어나", "늘었", "줄고", "줄어들", "줄었", "추세", "추이", "변화", "변했", "증가", "감소", "흐름"],
    "T5": ["구성", "비율", "비중", "나이대", "연령대", "성별"], "T6": ["비 오는 날", "주말에", "날씨에 따라", "~하면 어떻게", "영향"],
    "T7": ["관계", "상관", "일수록", "할수록", "연관"], "T8": ["예상", "예측", "될까", "전망", "앞으로", "다음 주", "다음 달", "다음 분기"],
    "T9": ["비슷한", "유사한", "닮은", "같은 유형", "어떤 유형", "어떤 동네야"], "T10": ["진단", "전반", "종합", "한눈에", "전체적으로"],
    "T11": ["자료 있", "데이터 있", "제공해", "어디서 볼", "반출"], "T13": ["몇 시", "시간대", "피크", "가장 붐비는 시간"],
    "T14": ["찾아줘", "골라줘", "추천해", "조건에 맞는", "높고", "낮고", "많고", "적고"], "T15": ["급증", "급감", "갑자기", "확 늘", "확 줄", "이례적", "이상하게"],
}
OUT_TOPICS = {  # 자료가 없는 주제(범위 밖). 열린 집합이라 목록 밖은 '지표·자료 목록에 없는 명사'로 판정한다(05 문서 3-3 완화 규칙)
    "임대료·시세": ["임대료", "월세", "전세", "보증금", "권리금", "시세", "집값", "땅값", "아파트값"],
    "실시간": ["실시간", "지금 바로", "현재 혼잡", "CCTV", "내비"],
    "개인정보": ["연락처", "전화번호", "주소 알려", "사장님 이름", "개인 정보", "소득", "세금", "납세"],
    "이익": ["순이익", "영업이익", "마진", "수익률"],  # v3: 매출·객단가는 카드 자료로 답한다. 이익은 자료 없음
    "미래 단정": ["망할까", "대박", "성공할까", "확실히"],
}


def build_datasets():
    c = pd.read_csv(ROOT / "docs" / "조사" / "센터데이터_목록.csv")
    rows = [{"no": r["No"], "name": r["데이터명"], "category": r["카테고리"], "export": r["반출"], "columns": r["컬럼"], "source": "센터"} for _, r in c.iterrows()]
    pub = [("583", "유동인구(읍면동, 일)"), ("743", "버스 정류소 이용(일)"), ("612", "버스 정류소 좌표"), ("780", "음식점 인허가·폐업"), ("793", "상가(상권) 정보"), ("579/ASOS", "일별 기상")]
    rows += [{"no": n, "name": nm, "source": "공개(허브·공공데이터포털)"} for n, nm in pub]
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    places, psrc = build_places()
    biz = build_biz()
    ds = build_datasets()
    files = {"places": places, "biz": biz, "metrics": METRIC_WORDS, "population": POP_WORDS, "conditions": COND_WORDS,
             "time": TIME_WORDS, "intent": INTENT_WORDS, "out_of_scope": OUT_TOPICS, "datasets": ds}
    for k, v in files.items():
        (OUT / f"{k}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    amb = sum(1 for v in places.values() if "candidates" in v)
    summary = {"places": {"names": len(places), "ambiguous(되묻기)": amb, "sources": psrc}, "biz": {"categories": len(biz["categories"]), "colloquial_groups": len(biz["colloquial"])},
               "metrics": sum(map(len, METRIC_WORDS.values())), "population": sum(map(len, POP_WORDS.values())), "conditions": sum(map(len, COND_WORDS.values())),
               "time": sum(map(len, TIME_WORDS.values())), "intent": sum(map(len, INTENT_WORDS.values())), "out_of_scope": sum(map(len, OUT_TOPICS.values())), "datasets": len(ds)}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
