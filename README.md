# 동네 생활 진단 Agent

제주 43개 읍면동의 상가·음식점·유동인구·버스·기상 자료로 도민의 질문에 답하는 AI Agent입니다.
질문을 해석해 볼 자료와 분석 방법을 정하고, 계산과 검수를 거쳐 답 카드로 보여 줍니다. 답마다 근거 데이터, 기준 시점, 한계를 함께 보여 줍니다.

처리 순서: M1 질의 해석 → M2 계획 → M3 작업 지시서 → Sub 실행(조회·EDA·학습·통계 검정) → 검수 → 결과 생성.

## 빠른 시작
| 순서 | Windows(센터 PC) | macOS |
|---|---|---|
| 1. 설치(처음 1회, 인터넷 필요) | `scripts\setup_windows.bat` | `sh scripts/setup_mac.sh` |
| 2. 실행 | `scripts\run_windows.bat` | `sh scripts/run_mac.sh` |
| 3. 접속 | 실행하면 기록을 남기지 않는 브라우저 창(Edge InPrivate, 없으면 Chrome 시크릿)이 http://localhost:8501 로 열립니다 | 같음(Chrome 시크릿, 없으면 Edge InPrivate) |
| 4. 방문자가 바뀔 때 | 브라우저 창을 닫고 `scripts\run_windows.bat`을 다시 실행합니다(서버는 그대로 쓰고 새 창만 엽니다) | 창을 닫고 `sh scripts/run_mac.sh`를 다시 실행 |

필요 환경: Python 3.9. 표준 테이블(`data/tables/`)이 들어 있어 데이터를 내려받지 않아도 바로 동작합니다.

기록을 남기지 않는 창은 물어본 질문 주소를 방문 기록에 쓰지 않고, 창을 닫으면 뒤로 가기 목록과 고른 동네도 지웁니다. 창이 열려 있는 동안에는 뒤로 가기 목록이 남으므로 방문자가 바뀌면 4번처럼 창을 닫습니다. Edge와 Chrome을 둘 다 찾지 못하면 기본 브라우저로 열고, 그때는 방문 기록을 직접 지워야 한다고 실행 창에 알려 줍니다.

## LLM 경로
앱이 시작할 때 아래 순서로 고릅니다. 질의 해석(M1)은 LLM이 아니라 문장 임베딩(Ollama `bge-m3`)과 분류기로 하고, 임베딩을 쓸 수 없으면 사전 규칙으로 해석합니다.

| 경로 | 조건 | LLM이 하는 일 |
|---|---|---|
| Claude(`claude-opus-5-5`) | 환경 변수 `ANTHROPIC_API_KEY`가 있을 때 | 되묻기 선택지 문장, 계획 해설 |
| 로컬 Ollama(`qwen3:1.7b`, 제출본 기본) | Ollama가 실행 중일 때. `ollama pull qwen3:1.7b` 필요 | 되묻기 선택지 문장, 계획 해설 |
| LLM 없음 | 위 둘 다 없을 때 | 없음. 코드 템플릿 문장으로 답함 |

어느 경로든 계산과 수치 문장은 코드가 맡습니다. LLM 문장이 숫자·문체 검사를 통과하지 못하거나 호출에 실패하면 템플릿 문장으로 바꿉니다.

## 환경 변수
`.env.example`을 참고하세요. 앱 실행에는 환경 변수가 필요 없습니다. **실제 키를 코드, 문서, 영상에 넣지 마세요.**

## 폴더 구조
| 경로 | 내용 |
|---|---|
| `web/out/` | 화면 정적 빌드. `app/api.py`가 제공하므로 Node가 필요 없습니다 |
| `web/src/` | 화면 원본. 고칠 때만 Node가 필요합니다 |
| `app/api.py` | FastAPI: `/api/ask`(질문), `/api/interpret`(해석), `/api/catalog`(자료 탐색), 정적 화면 제공 |
| `app/m1.py`, `app/qparse.py`, `app/qtuple.py` | M1 질의 해석: 질문 Tuple, 의도 확인 카드, 범위 밖 조기 반환 |
| `app/planner.py`, `app/runner.py` | M2 계획, M3 작업 지시서와 Sub 실행 |
| `app/recipes.py`, `app/s6.py` | S3 레시피형 학습·검증·추론, S6 통계 검정 |
| `app/verify.py`, `app/result.py` | 검수(오류 6유형·되돌림), 결과 생성(답 카드·판단 과정·내려받기) |
| `app/textcheck.py`, `app/places.py` | 답 문장 숫자 대조·금지 표현, 업종 대응표 |
| `app/build_tables.py`, `app/build_dong_tables.py`, `app/collect_api.py` | 데이터 수집과 표준 테이블 생성 |
| `data/tables/` | 앱이 읽는 표준 테이블 |
| `data/manual/station_manual.csv` | 정류소 수동 매핑표(근거 포함) |
| `tests/` | 단위 시험 |
| `models/` | M1 분류기(`m1_intent.json`), 레시피(`recipes.json`) |

## 데이터 갱신
앱만 쓸 때는 필요 없습니다. 원본은 크기 때문에 넣지 않았습니다.
1. 제주데이터허브에서 파일 793·780·743을 받아 `data/raw/`에 둡니다.
2. `.env`에 `JEJU_DATAHUB_KEY`를 넣고 API를 수집합니다.
   - 정류소: `python app/collect_api.py 612`
   - 기상: `python app/collect_api.py 579 --start 20230401 --end 20250330`
   - 유동인구: `python app/collect_api.py 583 --start 20231104 --end 20251103`
   - 호출 한도(데이터별 하루 1,000건)에 닿으면 멈춥니다. 같은 명령을 다음 날 실행하면 이어서 받습니다.
3. `python app/build_tables.py`, 이어서 `python app/build_dong_tables.py`를 실행합니다.

## 시험
- 시험: `python -m unittest discover -s tests`. LLM 없이 돕니다.
- 결과 생성 확인: `python app/result.py "질문"`.

## 오류와 제약
| 증상 | 원인과 조치 |
|---|---|
| 해설 문장이 템플릿으로만 나옴 | Ollama가 꺼져 있습니다. 수치 답은 그대로 나옵니다 |
| 코드를 고쳤는데 그대로임 | 앱을 다시 시작하세요 |

- 매출·임대료, 실시간 질문은 자료가 없어 답하지 않습니다. 시간대 질문은 센터 자료가 있어야 답합니다.
- 예측은 레시피 관문(이동 원점 검증, 기준선 짝 비교)을 통과한 경우에만 보여 줍니다.
- 유동인구(583) 값은 API 문서에도 집계 단위 설명이 없어 비율·지수로만 씁니다. 손님 수가 아닙니다.
- 폐업·생존은 음식점(780)만 있습니다. 표본 오차가 커서 순위를 내지 않습니다.
- 정류소는 이름으로 동네에 연결합니다. 같은 이름이 떨어진 곳에 있으면 구분하지 못합니다.
- 시험 환경은 macOS, Python 3.9입니다. **Windows와 센터 PC에서는 아직 실행해 보지 않았습니다.**

## 사용 모델과 오픈소스
- 실행 중 LLM: Qwen3(`qwen3:1.7b`, Ollama, Apache License 2.0), 선택 시 Anthropic Claude API(`claude-opus-5-5`).
- 문장 임베딩: BGE-M3(`bge-m3`, Ollama, MIT License).
- 개발 지원: Anthropic Claude Code(구현), Google Gemini(설계·코드 교차 검토).
- 패키지: `requirements.txt`(FastAPI, uvicorn, pandas, pyarrow, requests, anthropic 등)와 `web/package.json`(Next.js, React, Tailwind CSS, shadcn/ui, AnimateIcons, Pretendard).
- 화면 디자인: KRDS 디자인 토큰(https://www.krds.go.kr/tokens/transformed_tokens.json). 정부 사이트가 아닙니다.
- 데이터: 제주데이터허브 793·780·583·743·612·579.
