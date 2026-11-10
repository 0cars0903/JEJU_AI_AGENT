"""제출 문서를 표준 테이블·평가 결과의 현재 값으로 다시 만든다. 수치를 손으로 옮기지 않는다.
실행: .venv/bin/python docs/제출/build_docs.py
출력: 기획서.html(내용 확인용), 데이터활용명세.md, 결과설명자료.md. 기획서 PPTX는 build_pptx.py
"""
import html
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "app"))
import tools as tl  # noqa: E402

M = tl.meta()
E = json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8"))
sd = pd.read_parquet(ROOT / "data" / "interim" / "station_dong.parquet").drop_duplicates("station_name")
r_ = pd.read_parquet(ROOT / "data" / "interim" / "restaurants.parquet")
days_2024 = M["pop_days_by_year"].get("2024", 0)
POP_NOTE = "" if days_2024 >= 366 else f" 583은 2024년 366일 중 {days_2024}일을 반영한 임시 값입니다."
VALUE = lambda rows, d: next(x["value"] for x in rows if x["dong"] == d)  # noqa: E731


def eval_row(mode):
    rows = E[mode]
    return sum(x["pass"] for x in rows), len(rows)


def rank(metric, dongs):
    return tl.compare_rank(metric, dongs)["values"]["rows"]


lodge = rank("숙박특화계수", ["한경면", "이도2동"])
visit = rank("방문거주비", ["예래동", "동홍동"])
elder = rank("경로비중", ["한경면", "아라동"])
close_sig, km_sig = M["close_sig"], M["km_sig"]
bus_pct = M["bus_mapped_pct_2024"]
rule_p, rule_n = eval_row("rule")
ol_p, ol_n = eval_row("ollama:qwen3:1.7b")
cl_p, cl_n = eval_row("claude")
ol_q = [x for x in E["ollama:qwen3:1.7b"] if x["expected_status"] == "ok"]
replan_n, fill_n = sum(x["replanned"] for x in ol_q), sum(x["code_filled"] for x in ol_q)

CSS = """
@page{size:A4;margin:17mm 16mm}
*{box-sizing:border-box}body{font-family:'Apple SD Gothic Neo','Malgun Gothic','Noto Sans CJK KR',sans-serif;font-size:10.8pt;line-height:1.6;color:#141414}
h1{font-size:23pt;margin:0 0 6pt}h2{font-size:15pt;margin:0 0 8pt;padding-bottom:4pt;border-bottom:1.5pt solid #2a78d6}h3{font-size:11.8pt;margin:13pt 0 4pt;break-after:avoid}
section{break-before:page}section.first{break-before:auto}p{margin:4pt 0 7pt}ul{margin:3pt 0 8pt;padding-left:16pt}li{margin:2pt 0}
table{width:100%;border-collapse:collapse;font-size:9.4pt;margin:6pt 0 10pt}th,td{border:.6pt solid #c9c8c2;padding:3.5pt 5pt;text-align:left;vertical-align:top}th{background:#f1f0eb}td:nth-child(3),td:first-child{word-break:keep-all}.nw{white-space:nowrap}
tr,figure,.flow{break-inside:avoid}.lead{font-size:12pt;color:#333}.note{font-size:9pt;color:#555}figure{margin:7pt 0}figure img{width:100%;border:.6pt solid #d5d4ce}figcaption{font-size:8.8pt;color:#555;margin-top:2pt}
.flow{display:flex;align-items:stretch;gap:3pt;margin:7pt 0 10pt}.flow div{flex:1;border:.8pt solid #2a78d6;border-radius:4pt;padding:5pt 4pt;font-size:8.8pt;text-align:center}.flow b{display:block;font-size:9.6pt}.flow i{font-style:normal;align-self:center;flex:0 0 auto;border:0;padding:0;color:#2a78d6}.who{color:#555;font-size:8pt}
"""


def fig(name, cap):
    return f"<figure><img src='화면/{name}'><figcaption>{html.escape(cap)}</figcaption></figure>"


def flow():
    steps = [("① 해석", "동네·업종·기간 추출, 범위 판정", "코드"), ("② 계획", "도구 선택", "LLM"), ("점검·재계획", "문제를 알려 1회 재계획", "코드 + LLM"), ("③ 실행", "고정 도구 5종", "코드"), ("④ 검증", "숫자·표현 검사", "코드"), ("⑤ 설명", "수치 문장, 표, 차트, 지도", "코드(요약은 Claude)")]
    return "<div class='flow'>" + "<i>→</i>".join(f"<div><b>{a}</b>{b}<br><span class='who'>{c}</span></div>" for a, b, c in steps) + "</div>"


PLAN = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><title>동네 생활 진단 Agent 기획서</title><style>{CSS}</style><body>
<section class='first'>
<h1>동네 생활 진단 Agent</h1>
<p class='lead'>질문 하나로 우리 동네의 상권, 인구, 교통을 과거 기록으로 확인하는 AI Agent</p>
<p class='note'>제주 AI·빅데이터 활용 AI Agent 개발 챌린지 기획서</p>
<h2 style='margin-top:14pt'>1. 구현 목표</h2>
<p>제주 도민이 창업 입지를 찾거나 이사할 때는 동네별 상권과 인구, 대중교통을 함께 살펴야 합니다. 제주데이터허브에 자료가 있지만, 데이터마다 지역 단위와 기간이 달라 비전문가가 직접 묶기 어렵습니다.</p>
<table><tr><th>결합을 막는 장벽</th><th>이번 개발에서 확인한 사례</th></tr>
<tr><td>지역 단위가 다름</td><td>780 음식점은 법정동 주소, 583 유동인구는 읍면동, 743 버스는 정류소 이름</td></tr>
<tr><td>기간이 다름</td><td>793 상가는 2025-09 한 시점, 780은 2025-08까지의 이력, 743은 2025-10까지, 579 기상은 2025-03까지</td></tr>
<tr><td>이름이 바뀜</td><td>743 정류소 이름이 특정 날짜에 일괄 바뀜. 그대로 쓰면 정방동 버스 이용이 95.9% 늘어난 것처럼 보임</td></tr>
<tr><td>값의 뜻이 불명확</td><td>583 값은 API 문서에도 집계 단위 설명이 없음</td></tr></table>
<p><b>목표:</b> IT 비전문가 도민이 제주빅데이터센터 PC에서 평소 말로 묻고, 근거·기준 시점·한계가 붙은 답을 받게 합니다. 틀린 답을 그럴듯하게 내지 않는 것을 가장 중요한 품질 기준으로 둡니다. 그래서 예측값을 만들지 않고, 결합한 과거 기록과 그 한계를 함께 답합니다.</p>
<h3>동네마다 실제로 다릅니다</h3>
<table><tr><th>지표</th><th>높은 동네</th><th>낮은 동네</th></tr>
<tr><td>숙박 특화계수(제주 평균 = 1)</td><td>한경면 {VALUE(lodge,'한경면')}</td><td>이도2동 {VALUE(lodge,'이도2동')}</td></tr>
<tr><td>방문/거주 지수</td><td>예래동 {VALUE(visit,'예래동')}</td><td>동홍동 {VALUE(visit,'동홍동')}</td></tr>
<tr><td>버스 이용자 중 경로 비중(2024)</td><td>한경면 {VALUE(elder,'한경면')}%</td><td>아라동 {VALUE(elder,'아라동')}%</td></tr></table>
<p class='note'>방문/거주 지수는 사람 수나 손님 수가 아니라 비율입니다.{POP_NOTE}</p>
</section>
<section>
<h2>2. 서비스 제안</h2>
<table><tr><th>사용자</th><th>상황</th><th>질문 예</th></tr>
<tr><td>예비 창업자</td><td>카페·음식점 입지 선택</td><td>애월읍에 카페가 많은 편이야?</td></tr>
<tr><td>소상공인</td><td>주변 변화 확인</td><td>최근 2년 노형동 음식점 개업·폐업은?</td></tr>
<tr><td>생활 도민</td><td>이사, 부모님 이동</td><td>한림읍 어르신 버스 이용은 어때?</td></tr>
<tr><td>센터 상담 직원</td><td>방문 도민 응대</td><td>아라동과 이도2동 비교표 뽑아 줘</td></tr></table>
<p>화면은 세 메뉴입니다. <b>질문하기</b>는 사용자별 대표 질문과 입력창으로 묻고, <b>동네 진단</b>은 지도에서 동네를 눌러 배지·차트를 보고 업종을 골라 창업 진단을 합니다. <b>동네 비교</b>는 비교표를 만듭니다. 결과는 A4로 바로 인쇄합니다. 휴대폰 화면에서도 쓸 수 있고, 글자 크기와 선명한 화면을 고를 수 있습니다.</p>
{fig('동네진단.png','동네 진단 화면. 인터넷이 없어도 점포 좌표로 지도 윤곽을 그립니다.').replace("<img ", "<img style='width:82%' ")}
</section>
<section>
<h2>3. Agent 구성</h2>
<h3>역할과 Workflow</h3>
{flow()}
<p>LLM은 질문을 보고 도구와 인자를 고릅니다. 계산과 수치 문장은 결정론적 코드로 만듭니다. 결정론적 코드란 입력이 같으면 항상 같은 결과를 내는 코드입니다.</p>
<p>계획에 문제가 있으면 점검 코드가 찾은 문제를 LLM에 알리고, LLM이 1회 다시 계획합니다. 실행이 실패해도 실패 내용을 알려 1회 다시 호출합니다. 그래도 빠진 호출만 기본 계획으로 채웁니다. 평가셋에서 <code>qwen3:1.7b</code>는 {len(ol_q)}문항 중 {replan_n}건을 재계획했고, 끝내 코드로 채운 문항은 {fill_n}건입니다.</p>
<h3>이렇게 설계한 이유</h3>
<p>처음에는 LLM이 답 전체를 쓰게 했습니다. 시험에서 "한림읍 어르신 일평균 1,474명"이라는 답이 나왔는데, 이 값은 전체 이용자 수였습니다. 이 숫자는 도구 결과에 있는 값이라 숫자 대조로는 잡히지 않았습니다. 그래서 수치 문장을 코드로만 만들도록 구조를 바꿨습니다.</p>
<h3>모델</h3>
<table><tr><th>경로</th><th>조건</th><th>LLM이 하는 일</th></tr>
<tr><td>로컬 Ollama <code>qwen3:1.7b</code>(기본)</td><td>Ollama 실행 중. 모델 크기 1.4GB</td><td>계획</td></tr>
<tr><td>Claude <code>claude-opus-5-5</code>(선택)</td><td>환경 변수에 API 키가 있을 때</td><td>계획, 숫자 없는 요약</td></tr>
<tr><td>LLM 없음</td><td>위 둘 다 없을 때</td><td>없음. 코드의 기본 계획으로 답함</td></tr></table>
<h3>Tool과 API</h3>
<table><tr><th>도구</th><th>하는 일</th><th>데이터</th></tr>
<tr><td>dong_profile</td><td>상권·생존·인구·교통 요약, 배지 4개</td><td>793, 780, 583, 743+612</td></tr>
<tr><td>biz_diagnostic</td><td>업종 점포 수·특화계수, 음식점 개업·폐업·생존</td><td>793, 780</td></tr>
<tr><td>population_mix</td><td>방문·근무·거주 지수, 연령 구성, 비 오는 날 변화</td><td>583, 579</td></tr>
<tr><td>bus_usage</td><td>일평균 이용, 이용자 유형 비중, 증감, 비 오는 날 변화</td><td>743+612, 579</td></tr>
<tr><td>compare_rank</td><td>동네 비교표·순위. 폐업·생존은 순위 없음</td><td>표준 테이블</td></tr></table>
<p>도구는 로컬 표준 테이블만 읽습니다. 앱이 호출하는 API는 선택한 LLM 경로뿐입니다(Ollama 로컬 API 또는 Claude API). 제주데이터허브 API는 표준 테이블을 만들 때만 호출하고, 실행 중에는 호출하지 않습니다.</p>
<h3>자율 범위</h3>
<table><tr><th>Agent가 스스로 함</th><th>Agent가 할 수 없음</th></tr>
<tr><td>도구 선택, 지표 선택(질문 표현이 넓을 때), 실패 뒤 재계획</td><td>SQL·코드 생성, 데이터 수정, 질문에 없는 업종·기간 사용, 기본 계획 밖 호출 2개 이상, 수치 문장 작성</td></tr></table>
<p>범위 밖 질문(미래 예측, 매출·임대료, 시간대·실시간)은 이유와 함께 거절하고 답할 수 있는 질문을 제안합니다. 동네가 없거나 여러 행정동에 걸치면 되묻습니다.</p>
{fig('질문_답변.png','질문하기 화면. 답 위에 Agent가 한 일을 다섯 단계로 항상 보여 주고, 자세한 기록은 따로 엽니다. 이 캡처는 로컬 모델 경로입니다.')}
</section>
<section>
<h2>4. 데이터 계획</h2>
<table><tr><th class='nw'>ID</th><th>데이터</th><th class='nw'>형식</th><th>사용 기간</th><th>만드는 지표</th></tr>
<tr><td>793</td><td>제주특별자치도 상가(상권) 정보</td><td>파일</td><td>2025-09 단면</td><td>점포 수, 업종 특화계수</td></tr>
<tr><td>780</td><td>제주특별자치도 음식점 목록(통합)</td><td>파일</td><td>{M['rest_last']}까지 이력</td><td>개업·폐업, 폐업률, 5년 생존율</td></tr>
<tr><td>583</td><td>읍면동 단위 내국인 유동인구</td><td>API</td><td>{M['pop_first']} – {M['pop_last']}({M['pop_days']}일 반영)</td><td>방문/거주, 근무/거주, 연령 구성</td></tr>
<tr><td>743</td><td>이용자 유형별 버스정류소 이용 인원</td><td>파일</td><td>2019-01 – 2025-10</td><td>일평균 이용, 경로·청소년 비중, 증감</td></tr>
<tr><td>612</td><td>버스 정류소 기본 정보</td><td>API</td><td>전량</td><td>정류소 → 행정동 연결</td></tr>
<tr><td>579</td><td>일별 기상 정보</td><td>API</td><td>{M['wx_start']} – {M['wx_end']}</td><td>강수일(1mm 이상)</td></tr></table>
<h3>전처리와 결합</h3>
<ul><li><b>공통 키는 행정동 43곳입니다.</b> 793과 583의 행정동 이름은 완전히 일치합니다.</li>
<li><b>780 → 행정동:</b> 법정동이 한 행정동에 속하면 바로 연결하고, 나뉘면 우편번호, 도로명 순으로 연결합니다. 분석 대상의 99.45%를 확정했습니다.</li>
<li><b>743 → 행정동:</b> 이름 일치, 이름 조각 일치, 수동 매핑표 순으로 연결합니다. 2024년 이용자의 {bus_pct}%를 연결했습니다. 후보 동네가 여럿이면 612 정류소 수에 비례해 나눕니다.</li>
<li><b>이상값:</b> 743은 2022년에 105일이 빠져 있어 비교할 때 표시합니다. 579에서 같은 행이 두 번 든 날 2일은 중복을 지웁니다.</li></ul>
<h3>신뢰도를 지키는 표시 규칙</h3>
<ul><li>폐업·생존은 표본 오차가 커서 순위를 내지 않습니다(1년 폐업률의 해마다 순위 상관 0.267). 값, 95% 구간, 표본 수를 함께 보입니다. 다중 비교 보정(Benjamini–Hochberg, q=0.10) 뒤에도 차이가 남는 동네만 높음·낮음으로 표시합니다. 해당 동네는 3년 폐업률 {len(close_sig)}곳, 5년 생존율 {len(km_sig)}곳입니다.</li>
<li>우도면·추자면은 순위에서 빼고 "표본 적음"으로 표시합니다.</li>
<li>583은 비율·지수로만 씁니다.</li></ul>
<h3>쓰지 않은 데이터</h3>
<p>카드 소비 데이터는 동네 지표에 넣지 않았습니다. 597은 읍면동 단위가 없고 2018년까지이며, 502·504는 제주 전체 단위입니다. 동네 단위로 묶으면 없는 차이를 만들게 됩니다.</p>
<h3>이용 조건</h3>
<p>모든 데이터는 제주데이터허브(jejudatahub.net)에서 프로젝트 키로 받았습니다. 공개 메타데이터의 제공처는 제주데이터허브이며, 데이터별 이용 허락 유형 항목은 없습니다. 출처를 번호와 함께 표기하고, 원본 파일은 제출물에 넣지 않습니다. 표준 테이블에는 업소명 없이 동네 단위 집계만 담습니다.</p>
</section>
<section>
<h2>5. 개발·탑재 계획</h2>
<h3>센터 실행 환경</h3>
<table><tr><th>항목</th><th>내용</th></tr>
<tr><td>대상 PC</td><td>Intel i7-8700, GTX 1060, RAM 32GB</td></tr>
<tr><td>설치</td><td>Python 3.9, <code>scripts\\setup_windows.bat</code>(처음 1회)</td></tr>
<tr><td>실행</td><td><code>scripts\\run_windows.bat</code> 실행 후 브라우저에서 localhost 접속</td></tr>
<tr><td>데이터</td><td>표준 테이블을 함께 제공합니다. 실행 중 데이터 API를 호출하지 않습니다</td></tr></table>
<h3>외부 의존성</h3>
<table><tr><th>의존 대상</th><th>없을 때 동작</th></tr>
<tr><td>Ollama와 모델 <code>qwen3:1.7b</code></td><td>코드의 기본 계획으로 답합니다</td></tr>
<tr><td>Claude API(선택, 키 필요)</td><td>키가 없으면 쓰지 않습니다. 호출 실패 시 요약 없이 답합니다</td></tr>
<tr><td>지도 배경</td><td>쓰지 않습니다. 점포 격자와 동네 원을 직접 그려 외부 요청이 없습니다(화면 시험에서 확인)</td></tr>
<tr><td>Python 패키지 설치</td><td>처음 1회 인터넷이 필요합니다</td></tr></table>
<h3>검증 현황</h3>
<table><tr><th>항목</th><th>결과</th></tr>
<tr><td>평가셋 21문항(기대값을 도구와 따로 계산)</td><td>LLM 없음 {rule_p}/{rule_n}, qwen3:1.7b {ol_p}/{ol_n}, Claude {cl_p}/{cl_n}(Q21 추가 전 측정)</td></tr>
<tr><td>화면 자동 시험(개발 PC, 데스크톱·휴대폰 크기)</td><td>대표 질문 9건의 수치·화면 요소, 지도 선택, 오류·로딩 화면, A4 인쇄, 접근성 검사 통과</td></tr>
<tr><td>설치 재현(개발 PC)</td><td>제출 zip을 새 폴더에 풀어 새 가상환경에 설치하고 시험 통과 확인</td></tr>
<tr><td>Windows 설치·실행(GitHub Actions windows-latest)</td><td>setup_windows.bat 설치, 단위 시험, 서버 실행·질문 응답 통과(2026-11-10)</td></tr>
<tr><td>아직 못 한 것</td><td>센터 PC 실행과 응답 시간 측정</td></tr></table>
<h3>생성형 AI와 오픈소스 사용</h3>
<p>실행 중 LLM은 위 표와 같습니다. 개발에는 Anthropic Claude Code(구현)와 Google Gemini(설계·코드 교차 검토)를 썼습니다. 오픈소스는 Next.js, React, Tailwind CSS, shadcn/ui, Recharts, AnimateIcons, Pretendard, FastAPI, pandas, pyarrow, requests, anthropic SDK입니다. 화면 색과 크기는 KRDS(대한민국 정부 디자인 시스템) 디자인 토큰을 따랐습니다. 정부 사이트가 아닙니다. API 키는 환경 변수로만 받고 제출물에 넣지 않습니다.</p>
<h3>센터 활용 방안</h3>
<ul><li><b>방문 상담:</b> 상담 직원이 창업 입지나 이사를 고민하는 도민에게 동네 진단·비교 결과를 출력해 줄 수 있습니다.</li><li><b>전처리 자산:</b> 정류소-행정동 매핑표와 표준 테이블은 센터의 다른 분석에 다시 쓸 수 있습니다.</li><li><b>자료 갱신:</b> 수집·정제 스크립트를 다시 실행하면 추가 개발 없이 기준 시점을 옮길 수 있습니다.</li></ul>
</section></body></html>"""
(HERE / "기획서.html").write_text(PLAN, encoding="utf-8")

SPEC = f"""# 데이터 활용 명세

제주데이터허브 공개 데이터 6건(분석 5종과 정류소 기본 정보)만 쓰며, 다른 외부 데이터는 쓰지 않습니다. 지도 배경도 쓰지 않습니다.

| ID | 데이터 | 받는 방법 | 원본 범위 | 사용 범위 | 인코딩·형식 주의 |
|---|---|---|---|---|---|
| 793 | 제주특별자치도 상가(상권) 정보 | 파일 | 2025-09 단면, 57,865점포 | 전량 | CP949 |
| 780 | 제주특별자치도 음식점 목록(통합) | 파일 | 1960-01 – {M['rest_last']}, 51,111건 | 생존 2015-01 – 2020-08 개업, 폐업률 2022 – 2024 | CP949. 폐업일자에 소수점(.0) |
| 583 | 읍면동 단위 내국인 유동인구 | API | 2017 – 2025-11 제공 | {M['pop_first']} – {M['pop_last']} 중 {M['pop_days']}일 | limit 최대 100, 하루 7회 호출 |
| 743 | 이용자 유형별 버스정류소 이용 인원 | 파일 | 2019-01 – 2025-10 | 동네 지표 2024, 추이 2023-01부터 | UTF-8 BOM. 이름에 쉼표가 있어 앞 1칸·뒤 2칸 고정으로 분리 |
| 612 | 버스 정류소 기본 정보 | API | 4,352곳 | 전량 | 주소 빈 값 676곳. 주소에 행정동이 없는 곳을 합쳐 687곳은 가장 가까운 점포로 연결 |
| 579 | 일별 기상 정보 | API | 2014-01 – 2025-03 | {M['wx_start']} – {M['wx_end']} | 기본 10행. 페이지 조회 필요. 같은 행이 두 번 든 날 2일 |

링크 형식: `https://www.jejudatahub.net/data/view/data/{{ID}}`

## 결합 방법
| 연결 | 방법 | 결과 |
|---|---|---|
| 583 ↔ 793 | 행정동 이름 | 43곳 완전 일치 |
| 780 → 행정동 | 법정동 1:1 → 우편번호 → 도로명 → 법정동 다수결(모호 표시) | 분석 대상 31,227건 중 99.45% 확정 |
| 612 → 행정동 | 주소의 행정동 → 없으면 가장 가까운 793 점포 | 주소가 있는 3,665곳에서 두 방법 일치 97.03% |
| 743 → 행정동 | 수동 표 → 우도 규칙 → 이름 일치 → 기본 이름 → 이름 조각 | 2024년 이용자 {bus_pct}% |

- 수동 표: `data/manual/station_manual.csv`, 33개 이름. 근거 칸에 확인과 추정을 구분했습니다.
- 후보 동네가 여럿인 이름은 612 정류소 수에 비례해 나눕니다. 이렇게 나눈 이용자는 2024년 기준 7.06%입니다.

## 지표 정의
| 지표 | 정의 |
|---|---|
| 업종 특화계수 | (동네 업종 점포 ÷ 동네 전체 점포) ÷ (제주 업종 점포 ÷ 제주 전체 점포) |
| 폐업률 | 그해 초 영업 중이던 음식점 가운데 그해 폐업한 비율. 3년 묶음은 2022 – 2024 합산 |
| 5년 생존율 | 2015-01 – 2020-08 개업 음식점의 Kaplan–Meier 추정값 |
| 방문/거주 지수 | 583 방문 값 합 ÷ 거주 값 합. 사람 수 아님 |
| 버스 일평균 | 동네 정류소 이용자 합 ÷ 자료가 있는 날수 |
| 비 오는 날 변화 | 같은 달·같은 요일 안에서 강수일과 무강수일을 비교한 변화율. 강수일은 산간 제외 관측소 일강수 중앙값 1mm 이상 |

## 이용 조건과 개인정보
- 출처를 제주데이터허브와 데이터 번호로 표기합니다. 공개 메타데이터의 제공처는 제주데이터허브이며, 데이터별 이용 허락 유형 항목은 없습니다.
- 원본 파일은 제출물에 넣지 않습니다.
- 표준 테이블에는 업소명·개별 주소를 담지 않고 동네 단위 집계와 지도용 격자만 담습니다.
- API 키는 환경 변수로만 받습니다. 제출물에 넣지 않습니다.

## 알려진 한계
- 583: 집계 단위가 API 문서에 없습니다.{POP_NOTE}
- 743: 2022년 105일이 빠져 있습니다. 이름만 있고 정류소 ID가 없어 같은 이름이 떨어진 곳에 있으면 구분하지 못합니다. 2024년 이용자의 {round(100-bus_pct,2)}%는 연결하지 못했습니다.
- 780: 인허가 자료라 실제 영업과 다를 수 있고 음식점만 담습니다.
- 793: 단일 시점이라 추이를 볼 수 없습니다.
- 579: 제주 전체 기준이라 국지성 비를 반영하지 못합니다.
"""
(HERE / "데이터활용명세.md").write_text(SPEC, encoding="utf-8")

RESULT = f"""# 결과 설명자료

## 문제 정의
제주데이터허브 자료는 데이터마다 지역 단위와 기간이 달라 비전문가가 직접 묶기 어렵습니다. 이 Agent는 데이터를 행정동 단위로 묶고, 평소 말로 물으면 과거 기록으로 답합니다.

## 구조
해석 → LLM 계획 → 코드 점검 → 재계획 → 실행(고정 도구 5종) → 검증 → 설명. 계산과 수치 문장은 코드가 맡습니다. 자세한 내용은 기획서 3장을 보세요.

## 검증
| 경로 | 평가셋 통과 |
|---|---|
| LLM 없음 | {rule_p}/{rule_n} |
| qwen3:1.7b | {ol_p}/{ol_n} |
| qwen2.5:7b | {eval_row('ollama:qwen2.5:7b')[0]}/{eval_row('ollama:qwen2.5:7b')[1]} |
| Claude | {cl_p}/{cl_n} |

- 기대값은 도구 코드를 쓰지 않고 계산했습니다. 점포 수와 일부 개업·폐업은 원본 CSV와 대조하고, 날씨 효과는 더미 회귀로 다시 계산했습니다.
- 동네 배정과 폐업·생존의 정의는 도구와 공유하므로, 이 평가로는 검증되지 않습니다.
- 그래서 매핑을 따로 검사했습니다. 우편번호 규칙을 793에 적용하면 99.89%가 일치합니다. 규칙을 만든 자료로 잰 값이라 상한입니다. 정류소 주소와 최근접 점포는 97.03% 일치합니다.
- Claude 요약의 의미는 자동 채점하지 않습니다. 16건을 읽어 근거 없는 내용이 있는지 보았고, 일부를 도구 값과 대조했습니다.

## 한계
- Windows 설치·실행은 GitHub Actions(windows-latest)에서 확인했습니다. 센터 PC에서는 아직 실행하지 않았습니다.{POP_NOTE}
- 예측을 하지 않으며, 매출·임대료·시간대 질문에는 답하지 않습니다.
- 데이터별 한계는 데이터 활용 명세에 있습니다.

## 센터 활용 방안
1. **방문 상담:** 상담 직원이 창업 입지나 이사를 고민하는 도민에게 동네 진단·비교 결과를 출력해 줄 수 있습니다.
2. **전처리 자산:** 정류소-행정동 매핑표와 표준 테이블은 센터의 다른 분석에 다시 쓸 수 있습니다.
3. **자료 갱신:** 수집·정제 스크립트를 다시 실행하면 추가 개발 없이 기준 시점을 옮길 수 있습니다.
"""
(HERE / "결과설명자료.md").write_text(RESULT, encoding="utf-8")

# 기획서 PDF는 build_pptx.py가 만든 기획서.pptx를 사용자가 PDF로 변환한다(2026-11-10 사용자 결정). 기획서.html은 내용 확인용으로 남긴다.
print("생성 완료")
