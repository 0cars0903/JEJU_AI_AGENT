# 동네 생활 진단 Agent

제주 43개 읍면동의 상가·음식점·유동인구·버스·기상 자료를 묶어, 도민의 질문에 과거 기록으로 답하는 AI Agent입니다.
미래 예측은 하지 않습니다. 답마다 근거 데이터, 기준 시점, 한계를 함께 보여 줍니다.

## 빠른 시작
| 순서 | Windows(센터 PC) | macOS |
|---|---|---|
| 1. 설치(처음 1회, 인터넷 필요) | `scripts\setup_windows.bat` | `sh scripts/setup_mac.sh` |
| 2. 실행 | `scripts\run_windows.bat` | `sh scripts/run_mac.sh` |
| 3. 접속 | 브라우저에서 http://localhost:8501 | 같음 |

필요 환경: Python 3.9. 표준 테이블(`data/tables/`)이 들어 있어 데이터를 내려받지 않아도 바로 동작합니다.

## LLM 경로
앱이 시작할 때 아래 순서로 고릅니다. 화면 맨 아래 안내 문구에 현재 경로가 나옵니다.

| 경로 | 조건 | LLM이 하는 일 |
|---|---|---|
| Claude(`claude-opus-5-5`) | 환경 변수 `ANTHROPIC_API_KEY`가 있을 때 | 계획, 숫자 없는 요약 |
| 로컬 Ollama(`qwen3:1.7b`, 제출본 기본) | Ollama가 실행 중일 때. `ollama pull qwen3:1.7b` 필요 | 계획 |
| LLM 없음 | 위 둘 다 없을 때 | 없음. 코드의 기본 계획으로 답함 |

어느 경로든 계산과 수치 문장은 코드가 맡습니다. 모델을 내려받지 못했거나 호출에 실패하면 기본 계획으로 넘어갑니다.

## 환경 변수
`.env.example`을 참고하세요. 앱 실행에는 환경 변수가 필요 없습니다. **실제 키를 코드, 문서, 영상에 넣지 마세요.**

## 폴더 구조
| 경로 | 내용 |
|---|---|
| `web/out/` | 화면 정적 빌드(질문하기, 동네 진단, 동네 비교). `app/api.py`가 제공하므로 Node가 필요 없습니다 |
| `web/src/`, `web/e2e/` | 화면 원본과 브라우저 시험. 고칠 때만 Node가 필요합니다 |
| `app/api.py` | FastAPI: 화면이 부르는 API와 정적 화면 제공 |
| `app/agent.py` | Agent: 해석 → 계획 → 점검 → 재계획 → 실행 → 검증 → 설명 |
| `app/tools.py` | 고정 도구 5종 |
| `app/build_tables.py`, `app/build_dong_tables.py`, `app/collect_api.py` | 데이터 수집과 표준 테이블 생성 |
| `data/tables/` | 앱이 읽는 표준 테이블 |
| `data/manual/station_manual.csv` | 정류소 수동 매핑표(근거 포함) |
| `tests/`, `eval/run_eval.py` | 시험과 평가셋 21문항 |
| `docs/제출/` | 기획서, 데이터 활용 명세, 결과 설명자료 |

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
- 평가셋: `python eval/run_eval.py rule`. 기대값을 원자료에서 계산하므로 `data/raw/`와 `data/interim/`이 필요합니다.

## 오류와 제약
| 증상 | 원인과 조치 |
|---|---|
| 화면 위쪽에 "LLM 없음"이 나옴 | Ollama가 꺼져 있습니다. 답은 기본 계획으로 나옵니다 |
| 지도 배경이 비어 있음 | 인터넷이 없으면 배경 지도를 받지 못합니다. 회색 점(점포 위치)과 동네 원은 그대로 동작합니다 |
| 코드를 고쳤는데 그대로임 | 앱을 다시 시작하세요 |

- 미래 예측, 매출·임대료, 시간대·실시간 질문은 자료가 없어 답하지 않습니다.
- 유동인구(583) 값은 API 문서에도 집계 단위 설명이 없어 비율·지수로만 씁니다. 손님 수가 아닙니다.
- 폐업·생존은 음식점(780)만 있습니다. 표본 오차가 커서 순위를 내지 않습니다.
- 정류소는 이름으로 동네에 연결합니다. 같은 이름이 떨어진 곳에 있으면 구분하지 못합니다.
- 시험 환경은 macOS, Python 3.9입니다. **Windows와 센터 PC에서는 아직 실행해 보지 않았습니다.**

## 사용 모델과 오픈소스
- 실행 중 LLM: Qwen3(`qwen3:1.7b`, Ollama, Apache License 2.0), 선택 시 Anthropic Claude API(`claude-opus-5-5`).
- 개발 지원: Anthropic Claude Code(구현), Google Gemini(설계·코드 교차 검토).
- 패키지: `requirements.txt`(FastAPI, uvicorn, pandas, pyarrow, requests, anthropic 등)와 `web/package.json`(Next.js, React, Tailwind CSS, shadcn/ui, Recharts, AnimateIcons, Pretendard).
- 화면 디자인: KRDS 디자인 토큰(https://www.krds.go.kr/tokens/transformed_tokens.json). 정부 사이트가 아닙니다.
- 지도 배경: 쓰지 않습니다. 점포 격자와 동네 원을 직접 그려 인터넷 없이 동작합니다.
- 데이터: 제주데이터허브 793·780·583·743·612·579. 자세한 내용은 `docs/제출/데이터활용명세.md`.
