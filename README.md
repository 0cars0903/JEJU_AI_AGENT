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

권장: 설치 전에 [Ollama](https://ollama.com/download)를 설치하세요. 설치 스크립트가 Ollama를 찾으면 로컬 모델 `bge-m3`(질문 해석, 1.2GB)와 `qwen3:1.7b`(설명 문장, 1.4GB)를 함께 받습니다. 실행 스크립트는 시작할 때 어느 경로로 도는지 실행 창에 알려 줍니다.

기록을 남기지 않는 창은 물어본 질문 주소를 방문 기록에 쓰지 않고, 창을 닫으면 뒤로 가기 목록과 고른 동네도 지웁니다. 창이 열려 있는 동안에는 뒤로 가기 목록이 남으므로 방문자가 바뀌면 4번처럼 창을 닫습니다. Edge와 Chrome을 둘 다 찾지 못하면 기본 브라우저로 열고, 그때는 방문 기록을 직접 지워야 한다고 실행 창에 알려 줍니다.

## LLM 경로
질의 해석(M1)은 LLM이 아니라 문장 임베딩(Ollama `bge-m3`, CPU에서 실행)과 분류기로 합니다. 임베딩을 쓸 수 없으면 사전 규칙으로 해석합니다.

| 질의 해석 경로 | 조건 | 정확도(블라인드 150문항, Mac 측정) |
|---|---|---|
| 임베딩 + 분류기 | Ollama 실행 중이고 `bge-m3`가 있을 때 | 113/150(75%) |
| 사전 규칙 | 그 밖 | 94/150(63%) |

설명 문장은 앱이 시작할 때 아래 순서로 고릅니다.

| 경로 | 조건 | LLM이 하는 일 |
|---|---|---|
| Claude(`claude-opus-5-5`) | 환경 변수 또는 `.env`에 `ANTHROPIC_API_KEY`가 있을 때 | 계획 해설(판단 과정 한 문장), 전문가 모드(분석 코드 설계·해설) |
| 로컬 Ollama(`qwen3:1.7b`, 제출본 기본) | Ollama가 실행 중이고 `qwen3:1.7b`가 있을 때(설치 스크립트가 받음) | 계획 해설 |
| LLM 없음 | 위 둘 다 없을 때 | 없음. 코드 템플릿 문장으로 답함 |

인터넷이 없는 PC에서는 인터넷이 되는 PC에서 받은 모델 폴더(Windows `%USERPROFILE%\.ollama\models`, macOS `~/.ollama/models`)를 같은 위치에 복사하면 됩니다.

되묻기 선택지와 답의 수치 문장은 LLM 없이 코드가 만듭니다. 프롬프트와 출력 형식은 `app/prompts.py`에 모여 있습니다(출력은 도구 형식·JSON 스키마로 고정).

어느 경로든 계산과 수치 문장은 코드가 맡습니다. LLM 문장이 숫자·문체 검사를 통과하지 못하거나 호출에 실패하면 템플릿 문장으로 바꿉니다.

## 환경 변수와 API 키
`.env.example`을 참고하세요. **앱 실행에는 키가 필요 없습니다.** 답에 쓰는 자료는 미리 수집·가공해 `data/tables/`에 넣어 두었고, 실행 중에는 제주데이터허브 API를 부르지 않습니다.

| 키 | 언제 필요한가 | 제출물에 넣는가 |
|---|---|---|
| `JEJU_DATAHUB_KEY`(제주데이터허브 프로젝트키) | 자료를 새로 받을 때만(아래 '데이터 갱신') | 넣지 않습니다. 아래 방법으로 직접 발급합니다 |
| `DATA_ASOS_API_KEY`(공공데이터포털 기상청 ASOS) | 기상 자료를 새로 받을 때만(`app/collect_public.py`) | 넣지 않습니다. 공공데이터포털(https://www.data.go.kr)에서 활용 신청 뒤 받은 인증키를 `.env`에 적습니다 |
| `ANTHROPIC_API_KEY`(Claude) | Claude 경로를 쓸 때만. 없으면 로컬 Ollama 또는 템플릿 문장으로 답합니다 | 평가용 키만 최종 ZIP의 `.env`에 넣을 수 있습니다(사용 한도 설정, 평가 기간 뒤 폐기). 저장소·기획서·영상에는 넣지 않습니다 |

### 제주데이터허브 프로젝트키 발급·설정
제주데이터허브 이용안내 '데이터 활용'(https://jejudatahub.net/about/data-use) 절차를 따릅니다.
1. https://jejudatahub.net 에 회원가입하고 로그인합니다.
2. 마이페이지 > 프로젝트 관리 > [프로젝트 만들기]에서 프로젝트 이름을 넣어 등록합니다.
3. 쓸 API 데이터(583 유동인구, 579 일별 기상, 612 버스 정류소 등)의 상세 페이지에서 [프로젝트 담기]로 만든 프로젝트에 넣습니다.
4. 프로젝트 관리 상세 페이지의 '프로젝트키'를 복사합니다. 한 프로젝트키를 담은 모든 API 데이터에 같이 씁니다(재발급 가능).
5. 프로젝트 최상위 폴더에 `.env` 파일을 만들고 `JEJU_DATAHUB_KEY=<프로젝트키>`를 적습니다. `.env`는 git에 올라가지 않습니다.
6. 하루 호출 한도(쿼터)가 모자라면 마이페이지 > 프로젝트 관리 > 해당 프로젝트 > 활용데이터의 '변경 신청'으로 늘릴 수 있습니다.

### Claude 키 설정(선택)
- 키 만들기: https://console.anthropic.com 에서 키를 만들고 사용 한도를 먼저 설정합니다. 평가용 키는 참가자가 준비해 최종 ZIP에 함께 냅니다.
- 설정: 프로젝트 최상위 `.env`에 `ANTHROPIC_API_KEY=<키>`를 적고 실행 스크립트를 실행합니다. 앱이 시작할 때 `.env`를 읽고, 실행 창에 "Claude를 씁니다"가 나옵니다. 평가용 ZIP에는 이 `.env`가 들어 있습니다.
- 명령 창에서 `set ANTHROPIC_API_KEY=<키>`(Windows)나 `export`(macOS)로 정한 값이 있으면 그 값이 `.env`보다 먼저입니다.
- Claude를 끄려면 `.env`에서 그 줄을 지우거나 `LLM_BACKEND=ollama`를 적습니다.

**실제 키를 코드, 저장소, 기획서, 영상에 넣지 마세요.**

### 웹 데모(Vercel)와 로그인
설치 없이 여는 데모는 같은 코드를 Vercel에 올린 것입니다. 센터 PC 탑재본과 다른 점은 아래와 같습니다.

| 항목 | 센터 PC(로컬) | 웹 데모(Vercel) |
|---|---|---|
| 질문 해석 | `bge-m3` 임베딩 + 분류기(75%) | Ollama가 없어 사전 규칙(63%) |
| 설명 문장 | Ollama `qwen3:1.7b` 또는 Claude | Claude(키는 Vercel 환경 변수에만 둠) |
| Claude 기능(판단 과정 AI 설명, 전문가 모드) | 계정을 정하지 않으면 로그인 없이 씀 | **로그인해야 켜짐.** 질문과 답은 로그인 없이 쓸 수 있음 |
| 센터 CSV 넣기 | 300MB까지 | 요청 한 번에 4.5MB까지(Vercel 상한) |

데모 서버에 넣는 환경 변수(Vercel 프로젝트 Settings > Environment Variables):

| 변수 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | 데모 전용 Claude 키(사용 한도를 먼저 설정) |
| `JEJU_ACCOUNTS` | `아이디:해시,아이디:해시`. 해시는 `python -m app.auth hash`로 만듭니다(비밀번호는 저장하지 않음) |
| `JEJU_SESSION_SECRET` | 로그인 쿠키 서명 값. `python -m app.auth secret`으로 만듭니다 |
| `JEJU_EXPERT_DAILY` | 전문가 모드 하루 상한(서버 인스턴스마다, 기본 50) |
| `JEJU_WRITE_DIR` | `/tmp`(Vercel은 이 폴더에만 쓸 수 있음) |

- 공개 서버(Vercel)에서는 `JEJU_ACCOUNTS`가 빠져도 로그인을 요구합니다. 설정이 빠지면 Claude 기능이 꺼지는 쪽으로 동작합니다.
- 로그인은 한 IP에서 10분에 5번까지 틀릴 수 있습니다. 넘으면 10분 뒤 다시 시도합니다.
- 심사용 계정의 아이디와 비밀번호는 저장소와 기획서에 적지 않고 제출 ZIP 안내문에만 둡니다.

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
2. `.env`에 `JEJU_DATAHUB_KEY`를 넣고(발급은 위 '제주데이터허브 프로젝트키 발급·설정') API를 수집합니다.
   - 정류소: `python app/collect_api.py 612`
   - 기상: `python app/collect_api.py 579 --start 20230401 --end 20250330`
   - 유동인구: `python app/collect_api.py 583 --start 20231104 --end 20251103`
   - 호출 한도(데이터별 하루 1,000건)에 닿으면 멈춥니다. 같은 명령을 다음 날 실행하면 이어서 받습니다.
3. `python app/build_tables.py`, 이어서 `python app/build_dong_tables.py`를 실행합니다.

## 시험
- 시험: `python -m unittest discover -s tests`. LLM 없이 돕니다.
- 화면 시험: `cd web && npm run build && npx playwright test`(PC·폰 두 크기, LLM 없이 돎).
- 결과 생성 확인: `python app/result.py "질문"`.

## 오류와 제약
| 증상 | 원인과 조치 |
|---|---|
| 해설 문장이 템플릿으로만 나옴 | Ollama가 꺼져 있거나 `qwen3:1.7b`가 없습니다. 실행 창 첫 줄을 확인하세요. 수치 답은 그대로 나옵니다 |
| 질문을 자주 잘못 알아들음 | Ollama `bge-m3`가 없어 사전 규칙으로 해석 중입니다. `ollama pull bge-m3` 뒤 다시 실행하세요 |
| 코드를 고쳤는데 그대로임 | 앱을 다시 시작하세요 |

- 임대료·권리금과 실시간 질문은 자료가 없어 답하지 않습니다. 매출·시간대는 제주관광공사 카드 자료(업종 대분류 5개)로 답합니다. 카페 같은 세부 업종의 최신 매출은 답 화면의 센터 자료 요청 카드로 센터 CSV를 넣어야 볼 수 있습니다.
- 예측은 레시피 관문(이동 원점 검증, 기준선 짝 비교)을 통과한 경우에만 보여 줍니다.
- 유동인구(583) 값은 API 문서에도 집계 단위 설명이 없어 비율·지수로만 씁니다. 손님 수가 아닙니다.
- 폐업·생존은 음식점(780)만 있습니다. 표본 오차가 커서 순위를 내지 않습니다.
- 정류소는 이름으로 동네에 연결합니다. 같은 이름이 떨어진 곳에 있으면 구분하지 못합니다.
- 시험 환경은 macOS, Python 3.9입니다. Windows 실행 시험은 2026-11-13에 이상 없이 마쳤습니다. 센터 PC 실기에서는 아직 실행해 보지 않았습니다.

## 사용 모델과 오픈소스
- 실행 중 LLM: Qwen3(`qwen3:1.7b`, Ollama, Apache License 2.0), 선택 시 Anthropic Claude API(`claude-opus-5-5`).
- 문장 임베딩: BGE-M3(`bge-m3`, Ollama, MIT License).
- 개발 지원: Anthropic Claude Code(구현), Google Gemini(설계·코드 교차 검토).
- 패키지: `requirements.txt`(FastAPI, uvicorn, pandas, pyarrow, requests, anthropic 등)와 `web/package.json`(Next.js, React, Tailwind CSS, shadcn/ui, AnimateIcons, Pretendard).
- 화면 디자인: KRDS 디자인 토큰(https://www.krds.go.kr/tokens/transformed_tokens.json). 정부 사이트가 아닙니다.
- 데이터: 제주데이터허브 793·780·583·743·612·579.
