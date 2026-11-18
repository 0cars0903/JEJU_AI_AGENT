"""흐름 기법(문제 기록 56번, 마스터 2026-11-17 '기법 이름이 없어도 질문의 분석 흐름을 보고 다채로운 기법으로').

일반 답(질문 담당 Agent·단계형 Agent의 답)에, 질문의 흐름에 맞는 통계 기법 하나를 정해진 코드(techniques.RUN)로 계산해 기존 'Agent 분석·예상' 블록의 줄로 넣는다.
마스터 2026-11-17: 별도 칸·'더 본 분석' 같은 이름으로 따로 표시하지 않고 기존 방식에 흡수한다(줄 꼬리표는 기존과 같은 'Agent 계산 · 기법 이름').
기법을 고르는 방식은 둘이고, 같은 흐름표(FLOW)를 쓴다. 차이를 재려고 둘 다 둔다(마스터: '코드 표'와 '모델이 표의 기능을 수행'의 차이 검증).
- code: 흐름표의 정규식(질문 낱말)과 조건(동네·지표)만으로 고른다. 모델 호출 없음.
- model: 로컬 판단 모델(qwen2.5:7b)에게 흐름표 설명을 주고 하나를 고르게 한다. 코드는 조건(동네 필요 등)만 확인한다.
환경변수 JEJU_MORE = off | code | model (기본 code: 2026-11-17 판정 309문항 코드 224 대 모델 178, 71 대 25, p < 0.001, 모델은 고르기에 중앙값 1.1초 더 듦).
"""
import json
import os
import re
import time

import techniques as T

# 흐름표: (기법 키, 도민 말로 쓴 질문 흐름, 질문 낱말 정규식, 동네가 꼭 있어야 하는지)
# 기법의 계산 조건은 techniques.t_* 의 Reject와 같다. 순서 = 둘 이상 맞을 때 먼저 고르는 순서.
FLOW = [
    ("surv", "가게가 몇 년 버티는지, 오래 가는지, 문을 닫는지·창업하면 위험한지, 생존율을 묻는 흐름(음식점)",
     r"버티|오래\s*가|살아남|문\s*닫|폐업|망하|창업|차려도|열어도|개업해도|생존", True),
    ("sat", "이 동네에 이 업종 가게가 수요(매출·방문)에 비해 많은지, 포화인지, 경쟁이 심한지를 묻는 흐름",
     r"포화|과밀|경쟁이?\s*(심|치열|세)|레드\s*오션|너무\s*많", True),
    ("lq", "이 동네에 어떤 가게가 몰려 있는지, 특정 업종이 다른 동네보다 많은 편인지, 한 동네의 가게 수·새로 연 가게 수를 묻는 흐름",
     r"(많은|몰린|몰려|흔한|넘쳐|포화|경쟁)\S*\s*(편|업종|가게|곳)?|어떤\s*가게|무슨\s*가게|뭐가\s*많|몇\s*(개|곳|군데|집)|얼마나\s*있|점포\s*수|가게\s*수|개업|새로\s*(생|연|문)|강세", True),
    ("hhi", "동네 가게 종류가 고르게 섞였는지, 한 업종에 쏠렸는지를 묻는 흐름",
     r"다양|골고루|고르게|쏠|한\s*업종|종류가\s*(많|적)", True),
    ("decomp", "몇 월이 잘 되는지, 계절을 타는지, 대목·비수기가 언제인지, 방문객이 요즘 어떻게 흘러가는지를 묻는 흐름",
     r"몇\s*월|월별|추이|흐름|예상|계절|성수기|비수기|대목|여름|겨울|봄|가을|언제\s*(잘|많|사람|손님|장사)|방문|일평균|발길|유동|찾아\s*(오|와)|사람.*많", False),
    ("change", "한 동네·업종의 매출·장사·분위기가 어떤지, 늘었는지 줄었는지, 왜 변했는지(손님 수 때문인지 1건 금액 때문인지)를 묻는 흐름",
     r"매출|장사|벌이|객단가|잘\s*(되|돼|나가)|분위기|이용\s*건수|결제|손님.*(늘|줄)|왜\s*(줄|늘|떨어)|요즘\s*(어때|어떤)|사정|상권|소비|커지", False),
    ("outlier", "특별히 튀었던 달, 갑자기 많거나 적었던 때를 묻는 흐름",
     r"튀|갑자기|유독|이상하게|특히\s*(많|적)|반짝", False),
    ("test", "작년보다 정말 달라진 건지, 두 동네 차이가 우연이 아닌지를 묻는 흐름",
     r"작년보다|지난해보다|전년|정말\s*(늘|줄|달라|차이)|진짜\s*(늘|줄|달라|차이)|차이가\s*(있|나)", False),
    ("corr", "사람이 많으면 매출도 많은지처럼 두 지표가 같이 움직이는지를 묻는 흐름",
     r"(사람|방문|유동|발길|손님).*(많으면|늘면|많은\s*곳|따라).*(매출|장사|가게)|같이\s*(늘|줄|움직)|비례", False),
    ("regress", "무엇이 매출을 좌우하는지, 매출이 높은 동네는 무엇 때문인지를 묻는 흐름",
     r"무엇\s*때문|뭐\s*때문|좌우|결정하|영향", False),
    ("cluster", "우리 동네와 비슷한 동네, 동네를 성격별로 묶으면 어디와 같은 무리인지를 묻는 흐름",
     r"비슷한\s*(동네|곳|상권)|닮은|유사한|같은\s*유형|성격이\s*비슷", False),
    ("dist", "우리 동네 값이 제주 전체에서 높은 편인지 낮은 편인지, 어느 동네가 가장 많거나 적은지·순위처럼 동네들 사이의 위치를 묻는 흐름",
     r"높은\s*편|낮은\s*편|많은\s*편|적은\s*편|비싼\s*편|어느\s*정도|평균보다|수준|중간|가장|제일|최다|최소|상위|하위|순위|\d+\s*위|어디(야|예요|인가|인지|입니까)", False),
    ("shift", "이 동네 매출 성장이 제주 전체 흐름 때문인지 동네 자체 힘 때문인지를 묻는 흐름(2017~2021 자료)",
     r"제주\s*전체\s*(흐름|탓|때문)|동네\s*(자체|힘)|덕분", True),
]
# 붙이지 않는 흐름(두 방식 공통): 공개 자료로 계산할 수 없거나 통계 기법이 도움이 안 되는 질문
NONE_FLOW = "비·날씨 효과, 시간대·밤·주말·요일, 성별·나이, 버스, 맛집·추천·별점·시세·권리금·임대료, 가게 하나의 정보처럼 동네 단위 통계가 아닌 질문"
NONE_RX = re.compile(r"비\s*(오|올|와)|날씨|기온|강수|시\s*쯤|시에|시간대|오전|오후|밤|새벽|주말|평일|요일|남녀|성별|\d0대|나이|청년|버스|정류|맛집|추천|별점|후기|시세|권리금|임대료|월세")
# 순위 질문(동네 이름 없이 '가장·순위')은 분포가 먼저다(코드 표 순서 규칙)
# 코드 표 보강(2026-11-17 마스터 '코드 표의 약점 개선', 조정용 304 오류 유형에서): 순서 규칙과 낱말
VAGUE_RX = re.compile(r"우리\s*동네|근처|여기|이쪽|그\s*동네|주변|시내\s*쪽|서울|부산|강남|홍대|해운대|사장님|특정\s*(카페|가게|식당)|비\s*온")
PAIR_RX = re.compile(r"중에|중\s*(어디|어느)|어디가\s*더|보다\s*더")
WITH_RX = re.compile(r"같이|함께|랑\s*.*같이|하고\s*.*같이")
PER_RX = re.compile(r"건당|객단가|한\s*번\s*(가면|에)\s*돈|1인당|평균\s*결제")
TOUR_RX = re.compile(r"관광객|외국인|외지인|외국\s*손님|관광\s*비중")
RANK_RX = re.compile(r"가장|제일|최다|최소|상위|하위|순위|\d+\s*위|어디(야|예요|인가|인지|입니까)")
KEYS = [k for k, *_ in FLOW]
NEED_DONG = {k for k, _, _, nd in FLOW if nd}


def slots_of(question):
    """동네·업종·지표(측정과 서비스가 같은 입력을 쓰도록 질문에서 읽는다). 서비스에서는 답의 slots가 있으면 그쪽을 먼저 쓴다."""
    import qparse
    dongs = qparse.find_places(question)[0]
    tg = qparse.find_targets(question)
    metrics = [m for m, (_, pat, _) in T.METRIC.items() if re.search(pat, question or "")]
    if VISIT_RX.search(question or "") and "visit" not in metrics:  # '발길·붐벼'도 방문(기법 사전 METRIC에는 없는 도민 말)
        metrics.insert(0, "visit")
    return {"space": dongs, "target": tg[0] if tg else None, "metrics": metrics}


VISIT_RX = re.compile(r"발길|붐비|붐벼|북적|한산|사람\s*(많|적)")


def _ok_cond(tech, s):
    if tech in NEED_DONG and not s.get("space"):
        return False
    if tech == "surv" and s.get("target") not in (None, "음식점", "한식", "일식", "중식", "카페", "치킨", "분식"):
        return False
    return True


def pick_code(question, s):
    """흐름표 정규식으로 고른다. 맞는 기법이 없거나 조건이 안 맞으면 None."""
    q = question or ""
    if NONE_RX.search(q) or (VAGUE_RX.search(q) and not s.get("space")) or re.search(r"서울|부산|강남|홍대|해운대|사장님", q):
        return None, "붙이지 않는 흐름"
    if len(s.get("space") or []) >= 2 and PAIR_RX.search(q):
        return "test", "두 동네 중 어디가 더(차이가 우연인지)"
    if len(s.get("metrics") or []) >= 2 and WITH_RX.search(q):
        return "corr", "두 지표를 같이(같이 움직이는지)"
    if PER_RX.search(q):
        return "change", "건당 금액(건수와 건당 금액으로 나누기)"
    if TOUR_RX.search(q):
        return "dist", "관광객·외국인 비중의 동네 사이 위치"
    if RANK_RX.search(q) and not s.get("space"):
        return "dist", "순위·위치(동네 이름 없음)"
    for k, _, pat, _ in FLOW:
        if re.search(pat, q) and _ok_cond(k, s):
            return k, f"흐름표 '{k}' 낱말"
    return None, "흐름표에 맞는 낱말 없음"


S_PICK = ("너는 제주 상권 질문에 덧붙일 통계 분석 하나를 고른다. 질문에 기법 이름이 없어도, 질문이 묻는 흐름이 아래 흐름 중 하나와 맞으면 그 기법을 고른다. "
          "맞는 흐름이 없으면 none을 고른다. 단순히 숫자 하나를 묻는 질문이라도 흐름이 맞으면 고른다. JSON만 쓴다: {\"tech\": 키 또는 \"none\", \"why\": 한 문장}.\n흐름:\n"
          + "\n".join(f"- {k}: {d}" + (" (동네 이름이 있어야 함)" if nd else "") for k, d, _, nd in FLOW)
          + f"\n- none: {NONE_FLOW}. 동네 이름 없이 '가장·순위'를 물으면 dist를 먼저 생각한다.")
F_PICK = {"type": "object", "properties": {"tech": {"type": "string", "enum": KEYS + ["none"]}, "why": {"type": "string"}}, "required": ["tech"]}


def pick_model(question, s, chat=None):
    """판단 모델이 흐름표 설명을 읽고 고른다. 코드는 조건(동네 필요 등)만 확인한다."""
    import analyst
    a = analyst._ask(chat, S_PICK, f"질문: {question}\n읽은 동네: {', '.join(s.get('space') or []) or '없음'} / 업종: {s.get('target') or '없음'}", F_PICK, max_tokens=120)
    k = a.get("tech")
    if k not in KEYS:
        return None, str(a.get("why") or "모델이 none")[:80]
    if not _ok_cond(k, s):
        return None, f"모델이 '{k}'를 골랐지만 조건(동네 등)이 없음"
    return k, str(a.get("why") or "")[:80]


def mode():
    m = os.environ.get("JEJU_MORE", "code")
    return m if m in ("code", "model", "examples", "agent", "student") else "off"


# ---------------------------------------------------------------- 문제 기록 59번(2026-11-17): 모델이 분석 흐름을 이해해 기법을 고르는 두 방식
# (1) examples = 예시 증류(56번 계획): 교사(Opus)가 조정용 일반 질문 304개에 쓴 '의도 → 흐름 → 기법'(data/plans/teacher_techs_304.jsonl) 중
#     질문이 가장 비슷한 3개를 7B에게 보여 주고 기법을 최대 2개 고르게 한다.
# (2) agent = 분석 질문 생성 + 기법 카드 검색 + 의미 순 정렬(InsightPilot·QUIS, Gorilla 계열 도구 검색, Top-K Insights):
#     7B가 기법 이름 대신 '이어서 볼 분석 질문'을 만들고 → 각 분석 질문에 가까운 기법 카드 3장 중 하나를 고르고 → 엔진이 계산해 의미가 약한 결과는 뺀다.
# 두 방식 모두 코드는 계산 조건(동네 필요·업종 자료 범위)만 점검하고 기법을 고르지 않는다.
from pathlib import Path  # noqa: E402

PLANS = Path(__file__).resolve().parents[1] / "data" / "plans"
CARDS = {  # 기법 카드: 목적 / 이런 질문 / 필요한 자료 / 결과 읽는 법
    "change": "변화 분해: 한 동네·업종의 카드 매출이 1년 전보다 늘거나 준 것을 결제 건수(손님 수)와 건당 금액으로 나눈다. 이런 질문: 장사 잘돼? 매출 줄었어? 손님이 줄었나 객단가가 줄었나? 자료: 월 카드 매출. 읽는 법: 어느 쪽이 변화를 이끌었는지.",
    "decomp": "시계열 분해: 월별 값을 추세·계절·나머지로 나눈다. 이런 질문: 몇 월이 대목이야? 계절 타? 요즘 흐름이 올라가? 방문객 추이는? 자료: 월 카드 매출 또는 하루 방문. 읽는 법: 계절지수가 높은 달·낮은 달, 추세 변화율.",
    "outlier": "이상치: 평소와 다르게 튄 달을 찾는다. 이런 질문: 유독 장사 안 된 달이 있었어? 갑자기 사람이 몰린 때는? 자료: 월별 값. 읽는 법: 튄 달과 크기.",
    "test": "두 집단 검정: 최근 12개월과 그 전 12개월, 또는 두 동네의 차이가 우연인지 본다. 이런 질문: 작년보다 정말 늘었어? 두 동네 차이가 진짜야? 자료: 월별 값. 읽는 법: p값이 작으면 우연이 아닌 차이.",
    "corr": "상관: 두 지표가 같이 움직이는지 본다. 이런 질문: 사람이 많으면 매출도 많아? 가게 수와 매출이 같이 늘어? 자료: 월별 또는 동네별 두 지표. 읽는 법: 상관계수(-1~1).",
    "regress": "회귀: 동네 43곳의 카드 매출을 방문·가게 수 같은 동네 값으로 설명한다. 이런 질문: 매출 높은 동네는 뭐 때문이야? 무엇이 매출을 좌우해? 자료: 동네별 값. 읽는 법: 계수와 설명력(R²).",
    "cluster": "군집: 동네 43곳을 방문·매출·가게 수·생존율·관광객 비중이 비슷한 무리로 묶는다. 이런 질문: 우리 동네랑 비슷한 동네는? 동네 유형은? 자료: 동네별 값. 읽는 법: 같은 무리의 동네와 무리의 특징.",
    "dist": "분포: 동네 43곳의 값이 어떻게 흩어졌는지, 이 동네가 어디쯤인지 본다. 이런 질문: 우리 동네 매출 높은 편이야? 가장 많은 동네는? 관광객 비중 순위는? 자료: 동네별 값. 읽는 법: 중간값·사분위·이 동네의 위치.",
    "lq": "입지계수: 이 동네에 어떤 업종이 제주 전체보다 몰렸는지 본다. 이런 질문: 이 동네에 카페 많은 편이야? 무슨 가게가 많아? 경쟁 심해? 자료: 업종별 가게 수(동네 필요). 읽는 법: 1보다 크면 제주보다 몰림.",
    "sat": "포화도: 이 동네 이 업종의 가게 1곳당 수요(카드 매출, 세부 업종은 하루 방문)를 43개 동네 중간값과 견준다. 이런 질문: 카페 포화야? 경쟁 심해? 가게가 너무 많아? 자료: 가게 수·매출·방문(동네 필요). 읽는 법: 1보다 작으면 포화 쪽.",
    "hhi": "업종 다양성: 동네 가게 종류가 고르게 섞였는지 본다. 이런 질문: 가게 종류가 다양해? 한 업종에 쏠렸어? 자료: 업종별 가게 수(동네 필요). 읽는 법: 점수가 높을수록 고르게 섞임.",
    "surv": "생존분석: 음식점이 문을 연 뒤 몇 년 버티는지 본다. 이런 질문: 식당 차리면 오래 버텨? 폐업 많아? 자료: 음식점 인허가 개업·폐업(동네 필요, 음식점만). 읽는 법: 5년 생존율과 95% 구간.",
    "shift": "변이할당: 이 동네 매출 변화를 제주 전체 성장·업종 구성·동네 고유 효과로 나눈다(2017~2021 자료). 이런 질문: 우리 동네가 큰 건 제주 전체 덕이야, 동네 힘이야? 자료: 세부 업종 카드 매출(동네 필요). 읽는 법: 동네 고유 효과의 크기와 부호.",
}
CARD_Q = {  # 카드 검색용 짧은 분석 질문 예(정답 라벨과 무관하게 Claude가 씀, 2026-11-17). 점수 = 기법별 예 중 가장 가까운 것
    "change": ["이 동네 매출이 1년 전보다 늘었나 줄었나?", "매출 변화는 손님 수 때문인가 건당 금액 때문인가?", "요즘 장사가 잘되는 편인가?", "결제 건수와 객단가는 어떻게 변했나?", "이 업종 카드 매출이 최근 어떻게 바뀌었나?"],
    "decomp": ["몇 월에 매출이 가장 높은가?", "방문객 수는 최근 몇 달 동안 어떻게 변했나?", "계절에 따라 손님이 달라지나?", "성수기와 비수기는 언제인가?", "하루 방문객 추이가 올라가는 중인가?", "월별 흐름은 어떤가?"],
    "outlier": ["유독 매출이 낮았던 달이 있었나?", "갑자기 방문객이 몰린 달은 언제인가?", "평소와 다르게 튄 달은?"],
    "test": ["작년보다 정말 늘었다고 볼 수 있나?", "두 동네의 차이가 우연이 아닌가?", "최근 12개월과 그 전 12개월이 다른가?"],
    "corr": ["방문객이 많은 달에 매출도 많은가?", "가게 수와 매출이 같이 늘어나는가?", "두 지표가 함께 움직이나?"],
    "regress": ["매출이 높은 동네는 무엇 때문인가?", "방문과 가게 수 중 무엇이 매출을 더 좌우하나?", "동네 매출 차이를 설명하는 요인은?"],
    "cluster": ["이 동네와 비슷한 동네는 어디인가?", "동네들을 성격별로 묶으면 이 동네는 어떤 유형인가?", "비슷한 상권은 어디인가?"],
    "dist": ["이 동네 값은 제주 다른 동네와 비교해 높은 편인가?", "가장 많은 동네와 적은 동네는?", "동네 순위에서 이 동네는 어디쯤인가?", "관광객 비중이 높은 동네는?", "이 동네 방문객 수는 다른 동네보다 많은가?"],
    "lq": ["이 동네에 카페가 다른 동네보다 몰린 편인가?", "이 동네에 어떤 가게가 많이 몰려 있나?", "이 업종 경쟁이 심한 동네인가?", "이 동네의 특화 업종은?"],
    "sat": ["이 동네에 이 업종이 포화인가?", "가게 수에 비해 손님이 충분한가?", "경쟁이 너무 심한가?"],
    "hhi": ["이 동네 가게 종류는 다양한가?", "한 업종에 쏠려 있나?", "업종 구성이 고르게 섞였나?"],
    "surv": ["이 동네 식당은 몇 년 버티나?", "가게 폐업률이 다른 동네와 어떻게 다른가?", "창업하면 오래 살아남을 수 있나?", "5년 생존율은?"],
    "shift": ["이 동네 매출 성장은 제주 전체 흐름 덕인가 동네 힘인가?", "업종 구성 때문에 성장했나?"],
}
_EMB = {}


def _embed(texts):
    """bge-m3 임베딩(CPU, Ollama). 서비스와 측정이 같은 함수를 쓴다."""
    import numpy as np
    import llm
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat").replace("/api/chat", "/api/embed")
    out = []
    for i in range(0, len(texts), 32):
        r = llm.http().post(url, headers=llm.ollama_headers(), json={"model": "bge-m3", "input": texts[i:i + 32], "options": {"num_gpu": 0}}, timeout=600)
        out += r.json()["embeddings"]
    v = np.array(out, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _bank(name, texts):
    """예시·카드 임베딩을 한 번만 계산해 data/plans/emb_<name>.npy에 둔다(문장이 바뀌면 다시 계산)."""
    import hashlib
    import numpy as np
    key = hashlib.md5("\n".join(texts).encode("utf-8")).hexdigest()[:10]
    if _EMB.get(name, (None,))[0] == key:
        return _EMB[name][1]
    f = PLANS / f"emb_{name}_{key}.npy"
    v = np.load(f) if f.exists() else _embed(texts)
    if not f.exists():
        np.save(f, v)
    _EMB[name] = (key, v)
    return v


def _teacher():
    f = PLANS / "teacher_techs_304.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


S_EX = ("너는 제주 상권 질문의 답에 덧붙일 통계 분석을 고른다. 기법 이름이 질문에 없어도, 질문한 사람이 알고 싶은 것(의도)과 그걸 알기 위한 분석 흐름을 먼저 생각하고 "
        "그 흐름에 맞는 기법을 0~2개 고른다. 도움이 안 되거나 공개 자료로 계산할 수 없으면 빈 목록. 아래 비슷한 질문의 좋은 예시를 참고한다. "
        "JSON만: {\"intent\": 한 문장, \"flow\": 한 문장, \"techs\": [키...]}.\n기법:\n" + "\n".join(f"- {k}: {d}" for k, d, _, _ in FLOW))
F_EX = {"type": "object", "properties": {"intent": {"type": "string"}, "flow": {"type": "string"},
                                         "techs": {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": KEYS}}}, "required": ["techs"]}


# 질문 범위 점검(2026-11-17 쓸모 판정에서 나온 무용한 줄의 원인: 물은 지표와 다른 지표 분석, 동네 하나를 물었는데 43개 동네 전체 분석).
# 코드는 기법을 고르지 않고 '이 질문에 계산할 수 있는 기법 목록'만 정한다. 모델은 그 목록(JSON 스키마 enum) 안에서 고른다.
FAM = {"stores": re.compile(r"가게|점포|업소|매장|몇\s*(개|곳|군데|집)|개업|새로\s*(생|연|문)|많은\s*편|몰"),
       "close": re.compile(r"폐업|생존|버티|오래\s*가|살아남|문\s*(닫|을\s*닫)|망하"),
       "sales": re.compile(r"매출|장사|결제|건당|객단가|소비|카드|돈|벌|팔|잘\s*(되|돼|나가)|분위기|사정|상권|이용\s*건수"),
       "visit": re.compile(r"방문|발길|사람|유동|인구|붐비|북적|찾아|관광객|손님")}


def allowed(question, s):
    """질문 범위에 맞는 기법 목록(코드 점검). 지표 낱말이 없으면 모든 기법을 허용한다."""
    q = question or ""
    fam = {k for k, rx in FAM.items() if rx.search(q)}
    out = []
    for k in KEYS:
        if not _ok_cond(k, s):
            continue
        if k == "change" and fam and "sales" not in fam:
            continue
        if k in ("decomp", "outlier", "test") and fam and not fam & {"sales", "visit"}:
            continue
        if k == "surv" and "close" not in fam:
            continue
        if k in ("lq", "hhi") and fam and not fam & {"stores"} and not s.get("target"):
            continue
        if k == "corr" and not (len(fam) >= 2 or re.search(r"같이|함께|관계|따라|비례", q)):
            continue
        if k == "regress" and not re.search(r"때문|좌우|영향|이유|원인|결정", q):
            continue
        if k == "cluster" and not re.search(r"비슷|닮|유사|유형|성격|묶", q):
            continue
        if k == "shift" and not re.search(r"성장|덕분|덕|제주\s*전체\s*(흐름|때문)|동네\s*(힘|자체)", q):
            continue
        out.append(k)
    return out


def pick_examples(question, s, chat=None, k=3):
    """예시 증류: 비슷한 교사 예시 k개를 보고 7B가 기법을 0~2개 고른다(같은 질문 문장은 예시에서 뺀다)."""
    import analyst
    ex = ""
    if k:  # k = 0: 학습 증류 모델(student)은 예시 없이 같은 지시문으로 고른다(58번)
        rows = _teacher()
        if not rows:
            return [], "교사 예시 없음"
        v = _bank("teacher", [r["q"] for r in rows])
        sim = v @ _embed([question])[0]
        picks = [i for i in sim.argsort()[::-1] if rows[i]["q"].strip() != (question or "").strip()][:k]
        ex = "\n".join(f"질문: {rows[i]['q']}\n" + json.dumps({"intent": rows[i].get("intent"), "flow": rows[i].get("flow"), "techs": rows[i].get("techs") or []}, ensure_ascii=False) for i in picks)
    ok = allowed(question, s) if os.environ.get("JEJU_MORE_SCOPE", "1") == "1" else [t for t in KEYS if _ok_cond(t, s)]
    if not ok:
        return [], "질문 범위에 맞는 기법 없음"
    schema = {**F_EX, "properties": {**F_EX["properties"], "techs": {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": ok}}}}
    a = analyst._ask(chat, S_EX + ("\n\n예시:\n" + ex if ex else ""), f"질문: {question}\n읽은 동네: {', '.join(s.get('space') or []) or '없음'} / 업종: {s.get('target') or '없음'}\n이 질문에 계산할 수 있는 기법: {', '.join(ok)}", schema, max_tokens=250)
    techs = [t for t in dict.fromkeys(a.get("techs") or []) if t in ok][:2]
    return techs, str(a.get("flow") or a.get("intent") or "")[:100]


S_SUBQ = ("너는 제주 상권 분석가다. 도민의 질문을 보고, 그 사람이 진짜 알고 싶은 것을 생각한 뒤 '이 답을 해석하려면 이어서 무엇을 봐야 하나'를 분석 질문 1~3개로 쓴다. "
          "원래 질문을 다시 쓰지 않는다. 분석 질문은 다음 다섯 가지 중에서 질문에 맞는 것을 고른다: "
          "비교(제주 다른 동네보다 많은 편인가·몰린 편인가), 추세(시간에 따라 늘었나·몇 월에 높은가·계절을 타나), 원인(손님 수 때문인가 건당 금액 때문인가·무엇이 좌우하나), "
          "위치(제주 43개 동네 중 어디쯤인가·비슷한 동네는 어디인가), 지속(가게가 몇 년 버티나·폐업이 많은가). "
          "짧은 한국어 문장, 통계 기법 이름은 쓰지 않는다(예: '노형동 카페가 제주 다른 동네보다 몰린 편인가?', '애월읍 식당 매출은 몇 월에 높은가?'). "
          "JSON만: {\"intent\": 한 문장, \"subqs\": [문장...]}")
F_SUBQ = {"type": "object", "properties": {"intent": {"type": "string"}, "subqs": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}, "required": ["subqs"]}
S_CARD = ("너는 분석 질문마다 계산할 기법을 하나 고른다. 각 분석 질문 아래 후보 기법 카드 3장이 있다. 카드의 목적과 '이런 질문'이 분석 질문의 뜻에 가장 가까운 것을 고른다. "
          "세 카드 모두 분석 질문과 전혀 관계없을 때만 none. JSON만: {\"picks\": [키 또는 \"none\", ...]} (분석 질문 순서대로, 분석 질문 수만큼).")


def pick_agent(question, s, chat=None):
    """추천안: 분석 질문 생성(7B) → 질문마다 가까운 기법 카드 3장 → 7B가 하나 고름. 계산·의미 정렬은 attach가 한다."""
    import analyst
    a = analyst._ask(chat, S_SUBQ, f"질문: {question}\n읽은 동네: {', '.join(s.get('space') or []) or '없음'} / 업종: {s.get('target') or '없음'}", F_SUBQ, max_tokens=250)
    subqs = [x.strip() for x in (a.get("subqs") or []) if isinstance(x, str) and x.strip()][:3]
    if not subqs:
        return [], "분석 질문 없음", []
    keys = list(CARDS)
    ex = [(k, t) for k in keys for t in CARD_Q[k] + [CARDS[k]]]
    ev = _bank("cardq", [t for _, t in ex])
    qv = _embed(subqs)
    cand = []
    for q in qv:
        sc = ev @ q
        best = {}
        for (k, _), v in zip(ex, sc):
            best[k] = max(best.get(k, -1.0), float(v))
        cand.append(sorted(keys, key=lambda k: -best[k])[:3])
    msg = "\n".join(f"분석 질문 {n + 1}: {sq}\n" + "\n".join(f"  - {k}: {CARDS[k]}" for k in c) for n, (sq, c) in enumerate(zip(subqs, cand)))
    F_CARD = {"type": "object", "properties": {"picks": {"type": "array", "maxItems": len(subqs), "items": {"type": "string", "enum": keys + ["none"]}}}, "required": ["picks"]}
    b = analyst._ask(chat, S_CARD, msg, F_CARD, max_tokens=80)
    picks = [p for p, c in zip(b.get("picks") or [], cand) if p in c]
    techs = [t for t in dict.fromkeys(picks) if _ok_cond(t, s)]
    return techs, str(a.get("intent") or "")[:100], subqs


def meaning(tech, nums):
    """결과가 얼마나 의미 있는지(0~1, Top-K Insights의 유의성 점수를 기법별 숫자로 단순화). 0.35 미만이면 보여 주지 않는다."""
    n = nums or {}
    f = lambda k, d=0.0: float(n.get(k) if n.get(k) is not None else d)  # noqa: E731
    if tech == "test":
        return 1.0 if f("p", 1) < 0.05 else 0.3
    if tech == "corr":
        r = abs(f("pearson"))
        return 1.0 if r >= 0.5 else 0.6 if r >= 0.3 else 0.3
    if tech == "outlier":
        return 1.0 if f("outliers") > 0 else 0.2
    if tech == "regress":
        return 1.0 if f("r2") >= 0.3 else 0.4
    if tech == "cluster":
        return 0.8 if f("silhouette") >= 0.25 else 0.4
    if tech == "change":
        return 1.0 if abs(f("sales_change_pct")) >= 3 else 0.6
    if tech == "decomp":
        return 1.0 if f("season_max") - f("season_min") >= 10 else 0.5
    if tech == "lq":
        return 1.0 if f("lq_top") >= 1.5 else 0.6
    return {"surv": 0.8, "hhi": 0.7, "shift": 0.7, "dist": 0.6}.get(tech, 0.5)


def run(question, tech, s):
    """기법 하나를 계산한다. 돌려주는 값: (분석 블록에 넣을 줄, 방법, 그림 목록) 또는 None(계산 거부·오류)."""
    tgt, note = s.get("target"), None
    import v3
    big, lim = v3.biz5_of(tgt)
    if lim and "stores" not in (s.get("metrics") or []) and tech not in ("lq", "hhi", "surv"):
        # 카페처럼 카드 매출이 대분류로만 있는 업종: 대분류 이름으로 계산하고 그렇게 밝힌다(문제 기록 57·58번 자료 적합성 점검)
        parent = {"음식점업": "음식점", "소매업": "소매", "숙박업": "숙박"}.get(big)
        note = f"{tgt}만의 카드 매출 자료가 없어 {big} 전체({tgt} 포함)로 계산했어요."
        tgt = parent
    q2 = question
    if s.get("metrics") and s["metrics"][0] == "visit" and not re.search(T.METRIC["visit"][1], q2 or ""):
        q2 = f"{q2} (방문)"  # 기법 사전이 지표를 질문 낱말로 읽으므로 방문을 드러낸다
    try:
        r = T.answer(q2, {"method": tech, "space": s.get("space") or [], "target": tgt})
    except Exception:  # noqa: BLE001 — 덧붙이는 칸이므로 실패하면 붙이지 않는다
        return None
    a = r.get("answer") or {}
    if (a.get("conclusion") or {}).get("tag") == "계산하지 않음":
        return None
    name, plain = T.TECH[tech][0], T.PLAIN[tech]
    src = next((x.get("source") for b in a.get("blocks") or [] for x in b.get("lines") or [] if x.get("source")), None)
    lines = [{"text": a["conclusion"]["text"], "tag": f"Agent 계산 · {name}", "block": "analysis", "layer": "L3", "source": src}]
    lines += [{**x, "block": "analysis"} for b in a.get("blocks") or [] for x in b.get("lines") or [] if x.get("tag") != "주의"][:2]  # 결론 + 계산 결과 2줄
    if note:
        lines.append({"text": note, "tag": "주의", "block": "analysis", "layer": "L5", "source": None})
    return lines, (a.get("methods") or []), (a.get("views") or []), meaning(tech, r.get("numbers"))


def unfit(question, s):
    """자료 적합성 관문(모든 방식 공통, 기법을 고르지 않음): 기법이 계산할 수 없는 자료(시간대·주말·하루 날씨·성별·나이·버스·시세·맛집)나
    제주 밖·정할 수 없는 장소('우리 동네'·'근처')를 묻는 질문이면 이유를, 아니면 None."""
    q = question or ""
    if NONE_RX.search(q):
        return "기법이 계산할 수 없는 자료(시간대·주말·하루 날씨·성별·나이·버스·시세·추천)"
    if re.search(r"서울|부산|강남|홍대|해운대|전국|광역|사장님", q) or (VAGUE_RX.search(q) and not s.get("space")):
        return "제주 밖이거나 정할 수 없는 장소"
    return None


def choose(question, s, how, chat=None):
    """기법 고르기(방식별). 돌려주는 값: (기법 목록, 이유, 분석 질문 목록). 모델 방식은 자료 적합성 관문을 먼저 거친다."""
    if how in ("examples", "agent", "student"):
        why = unfit(question, s)
        if why:
            return [], why, []
    if how == "student":
        ks, why = pick_examples(question, s, chat=chat, k=0)
        return ks, why, []
    if how == "model":
        k, why = pick_model(question, s, chat=chat)
        return ([k] if k else []), why, []
    if how == "examples":
        ks, why = pick_examples(question, s, chat=chat)
        return ks, why, []
    if how == "agent":
        return pick_agent(question, s, chat=chat)
    k, why = pick_code(question, s)
    return ([k] if k else []), why, []


def compute(question, techs, s, how):
    """고른 기법을 계산한다. agent 방식은 의미 점수 0.35 미만을 빼고 점수 순 상위 2개(Top-K Insights)."""
    got = []
    for i, t in enumerate(techs):
        g = run(question, t, s)
        if g:
            got.append((t, g, i))
    if how == "agent":
        got = sorted([x for x in got if x[1][3] >= 0.35], key=lambda x: (-x[1][3], x[2]))[:2]
    return got


def attach(resp, question, how=None, chat=None):
    """일반 답의 분석 블록에 흐름 기법 결과 줄을 넣는다. 기법 답·되묻기·오류 답에는 넣지 않는다."""
    how = how or mode()
    if how == "off" or not isinstance(resp, dict) or resp.get("status") not in ("성공", "no_significant_effect"):
        return resp
    a = resp.get("answer")
    if not isinstance(a, dict) or not isinstance(a.get("blocks"), list) or (resp.get("understood") or {}).get("slots", {}).get("topic") == "technique":
        return resp
    t0 = time.perf_counter()
    s = slots_of(question)
    us = (resp.get("understood") or {}).get("slots") or {}
    if us.get("space"):
        s["space"] = us["space"]
    if us.get("target"):
        s["target"] = us["target"]
    techs, why, subqs = choose(question, s, how, chat=chat)
    got = compute(question, techs, s, how)
    resp["more"] = {"how": how, "techs": techs, "shown": [t for t, _, _ in got], "why": why, "subqs": subqs, "sec": round(time.perf_counter() - t0, 2)}
    if got:
        tgt = next((b for b in a["blocks"] if b.get("id") == "analysis"), None)
        if tgt is None:  # 분석 블록이 없는 답: 같은 이름의 블록을 만든다(기존 답과 같은 제목)
            tgt = {"id": "analysis", "title": "Agent 분석·예상", "lines": []}
            a["blocks"].append(tgt)
        for _, (lines, methods, views, _m), _ in got:
            tgt["lines"] = list(tgt.get("lines") or []) + lines
            a["methods"] = (a.get("methods") or []) + methods
    return resp


if __name__ == "__main__":
    import sys
    for q in sys.argv[1:]:
        s = slots_of(q)
        print(json.dumps({"q": q, "s": s, "code": pick_code(q, s)}, ensure_ascii=False))
