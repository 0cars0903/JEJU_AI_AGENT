"""동네 생활 진단 API. 질문 → M1 해석 → M2 계획 → M3 지시서 → 실행 → 검수 → 결과 생성.
실행: .venv/bin/python -m uvicorn app.api:app --port 8000 (web/out이 있으면 같은 주소에서 화면도 제공한다. Node 설치 불필요)
"""
import math
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import envfile  # noqa: E402

envfile.load()  # 평가용 키를 ZIP의 .env로 받는다. 이미 설정된 환경 변수가 우선
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "out"

app = FastAPI(title="동네 생활 진단 API")


def _user(request):
    """로그인한 아이디. 계정을 설정하지 않은 로컬이면 'local'(로그인 없이 Claude 기능 사용)."""
    import auth
    if not auth.required():
        return "local"
    return auth.verify(request.cookies.get(auth.COOKIE))


@app.on_event("startup")
def _warm_recipes():
    """R1 레시피 캐시를 별도 스레드에서 미리 채운다. 서버는 기다리지 않고 바로 뜬다(상태는 /api/health)."""
    import threading
    import recipes
    threading.Thread(target=recipes.warm, daemon=True).start()


def clean(x):
    """numpy 값과 NaN을 JSON에 넣을 수 있게 바꾼다."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [clean(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    return x


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, exc: RequestValidationError):
    """입력 형식 오류도 detail을 문자열 하나로 돌려준다(화면이 오류 문구를 한 가지 방식으로 읽게, 028 대조)."""
    return JSONResponse({"detail": "입력 형식이 맞지 않습니다. 질문은 200자 이하로 써 주세요."}, status_code=422)


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    return JSONResponse({"detail": "처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요."}, status_code=500)


class Ask(BaseModel):
    question: Optional[str] = Field(default=None, max_length=200)
    slots: Optional[dict] = None  # 추천 질문·단계별 선택·대표 질문의 버튼 값(app/guide.py). 있으면 해석하지 않는다
    dataset_id: Optional[str] = Field(default=None, max_length=32)  # F9: /api/dataset로 불러온 센터 CSV
    dataset_key: Optional[str] = Field(default=None, max_length=64)  # 파일을 넣을 때 받은 열쇠. 주소에는 넣지 않는다(문서 20 A7)


@app.post("/api/dataset")
async def dataset(request: Request, check_dong: Optional[str] = None, check_biz: Optional[str] = None):
    """F9 센터 자료 불러오기: 요청 본문이 CSV 파일 그대로(파일 이름은 X-Filename 머리글). 칸 이름으로 자료를 알아보고 집계해 둔다.
    응답: id·key(다시 계산할 때 함께 보내는 열쇠)·자료 이름·줄 수·기간·동네·업종·요청 조건과 맞지 않는 점(problems). 알아보지 못하면 422와 다시 받을 방법."""
    import center_csv
    from urllib.parse import unquote
    raw = await request.body()
    name = unquote(request.headers.get("x-filename", "upload.csv"))
    try:
        meta = center_csv.load(raw, name)
    except center_csv.CsvError as e:
        raise HTTPException(422, str(e))
    return clean({**meta, "problems": center_csv.check_request(meta, check_dong, check_biz)})


_M1 = {}


@app.post("/api/ask")
def ask(body: Ask, request: Request):
    """자유 입력(question) 또는 버튼 값(slots) → 해석 → 계획 → 지시서 → 실행 → 검수 → 결과 생성.
    응답: understood·card·suggestions·process·downloads, 추정할 수 없으면 status '선택필요'와 choose. 명세 docs/기획/07_화면API명세.md"""
    import m1
    import result
    question = (body.question or "").strip()
    if not question and not body.slots:
        raise HTTPException(422, "질문을 입력하거나 고를 항목을 골라 주세요.")
    b = llm.backend()  # 계획 해설: 키가 있으면 Claude, 없으면 켜져 있는 Ollama, 둘 다 없으면 템플릿(2026-11-13)
    on = (b == "claude" and _user(request) is not None) or (b == "ollama" and llm._ollama_alive())  # Claude는 로그인 뒤에만(데모)
    env = {"center_db": False}
    if body.dataset_id:
        import center_csv
        meta = center_csv.get(body.dataset_id)
        if not meta:
            raise HTTPException(422, "불러온 센터 자료를 찾지 못했습니다(하루가 지나 지워졌을 수 있어요). 파일을 다시 넣어 주세요.")
        if not center_csv.allowed(meta, body.dataset_key):
            raise HTTPException(422, "센터 자료로 계산한 결과는 파일을 넣은 브라우저에서만 볼 수 있어요. 파일을 다시 넣어 주세요.")
        env["center_card"] = body.dataset_id
    # (가) 기법 목록(설계 11-1절): 질문에 분석 기법 이름이 있으면 정해진 코드로 계산한다. 센터 CSV를 쓰는 질문은 기존 경로로 보낸다
    import techniques
    if not body.dataset_id and ((body.slots or {}).get("topic") == "technique" or (not body.slots and techniques.detect(question))):
        if (body.slots or {}).get("topic") == "technique" and not question:
            question = techniques.EXAMPLES.get(body.slots.get("method"), "")
        return clean(techniques.answer(question, body.slots))
    if body.slots:
        try:
            return clean(result.respond(question or None, env, llm_on=on, slots=body.slots))
        except ValueError as e:
            raise HTTPException(422, str(e))
    if "m" not in _M1:
        _M1["m"] = m1.M1()
    return clean(result.respond(question, env, llm_on=on, interpret=_M1["m"].interpret))


@app.get("/api/map")
def jeju_map():
    """제주 행정동 43곳 경계(SVG 경로, app/build_map.py). 지도 배경 타일 없음. 출처 표기(attribution) 포함."""
    import json as _json
    if "map" not in _CACHE:
        _CACHE["map"] = _json.loads((ROOT / "data" / "tables" / "jeju_map.json").read_text(encoding="utf-8"))
    return _CACHE["map"]


@app.get("/api/summary")
def dong_summary(dong: str = Query(..., max_length=10)):
    """패턴 A 첫 화면 '동네 한눈에': 질문형 카드 3장(하루 방문·카드 매출·가게 수)과 지도 색칠 값."""
    import qtuple as Q
    import v3
    if dong not in Q.DONGS:
        raise HTTPException(422, f"알 수 없는 동네: {dong}")
    return clean(v3.summary(dong))


_CACHE = {}


@app.get("/api/guide")
def guide_view():
    """질문 유도 목록: 단계별 선택의 주제와 칸별 선택지, 동네 목록, 대표 질문(버튼 값 포함)."""
    import guide
    return guide.catalog_view()


class Interpret(BaseModel):
    question: str = Field(..., max_length=300)



@app.post("/api/interpret")
def interpret(body: Interpret):
    """W2 M1 질의 해석: 질문 Tuple + 의도 확인 카드 + 확신도 + 쓴 경로(B3 / 사전 규칙 대체) + 처리 시간."""
    q = body.question.strip()
    if not q:
        raise HTTPException(422, "질문을 입력해 주세요.")
    if "m" not in _M1:
        import m1
        _M1["m"] = m1.M1()
    return clean(_M1["m"].interpret(q))


@app.get("/api/catalog")
def catalog(q: str = Query(default="", max_length=50)):
    """S0 자료 탐색(T11): 자료 목록(data/catalog.json)에서 이름·영역·열에 검색어가 든 자료를 돌려준다."""
    import json as _json
    rows = _json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    words = [w for w in re.split(r"\s+", q.strip()) if w]
    hit = [r for r in rows if all(w in f"{r['name']} {r.get('domain', '')} {r.get('columns') or ''}" for w in words)] if words else rows
    keep = ["id", "name", "source", "space", "time", "domain", "period", "export", "access"]
    return clean({"query": q, "count": len(hit), "items": [{k: r.get(k) for k in keep} for r in hit[:20]]})


class Expert(BaseModel):
    question: str = Field(..., max_length=500)


class Login(BaseModel):
    id: str = Field(..., max_length=64)
    password: str = Field(..., max_length=200)


@app.get("/api/me")
def me(request: Request):
    """로그인 상태. login_required가 False면(로컬) 로그인 화면을 보이지 않는다."""
    import auth
    import expert
    uid = _user(request)
    return {"login_required": auth.required(), "logged_in": uid is not None and uid != "local", "id": uid if uid != "local" else None,
            "claude": expert.enabled()}


@app.post("/api/login")
def do_login(body: Login, request: Request):
    import auth
    from fastapi.responses import JSONResponse as J
    if not auth.required():
        raise HTTPException(404, "이 환경은 로그인이 필요 없어요.")
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    try:
        token, why = auth.login(body.id.strip(), body.password, ip)
    except RuntimeError:
        raise HTTPException(503, "로그인 설정이 끝나지 않았어요(관리자 확인 필요).")
    if not token:
        raise HTTPException(401, why)
    r = J({"logged_in": True, "id": body.id.strip()})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    r.set_cookie(auth.COOKIE, token, max_age=auth.TTL, httponly=True, secure=secure, samesite="lax", path="/")
    return r


@app.post("/api/logout")
def do_logout():
    import auth
    from fastapi.responses import JSONResponse as J
    r = J({"logged_in": False})
    r.delete_cookie(auth.COOKIE, path="/")
    return r


@app.get("/api/expert/status")
def expert_status(request: Request):
    """전문가 모드(설계 11-2절) 사용 가능 여부. Claude 키가 있고, 데모에서는 로그인했을 때만 켜진다."""
    import auth
    import expert
    uid = _user(request)
    return {"enabled": expert.enabled() and uid is not None, "available": expert.enabled(),
            "login_required": auth.required() and uid is None, "daily_limit": expert.DAILY}


@app.post("/api/expert")
def expert_ask(body: Expert, request: Request):
    """전문가 모드: 요청 → Claude가 계획·코드 설계 → 검사·격리 실행 → 해설 → 숫자 대조. 데모에서는 로그인 필요."""
    import expert
    uid = _user(request)
    if uid is None:
        raise HTTPException(401, "전문가 모드는 로그인한 뒤에 쓸 수 있어요.")
    q = body.question.strip()
    if not q:
        raise HTTPException(422, "요청을 입력해 주세요.")
    return clean(expert.ask(q, user=uid))


@app.get("/api/health")
def health():
    import recipes
    return {"status": "ok", "web_built": OUT.exists(), "recipes": recipes.WARM}


if OUT.exists():
    app.mount("/", StaticFiles(directory=OUT, html=True), name="web")
