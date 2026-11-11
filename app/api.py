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
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "out"

app = FastAPI(title="동네 생활 진단 API")


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


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    return JSONResponse({"detail": "처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요."}, status_code=500)


class Ask(BaseModel):
    question: Optional[str] = Field(default=None, max_length=200)
    slots: Optional[dict] = None  # 추천 질문·단계별 선택·대표 질문의 버튼 값(app/guide.py). 있으면 해석하지 않는다


_M1 = {}


@app.post("/api/ask")
def ask(body: Ask):
    """자유 입력(question) 또는 버튼 값(slots) → 해석 → 계획 → 지시서 → 실행 → 검수 → 결과 생성.
    응답: understood·card·suggestions·process·downloads, 추정할 수 없으면 status '선택필요'와 choose. 명세 docs/기획/07_화면API명세.md"""
    import m1
    import result
    question = (body.question or "").strip()
    if not question and not body.slots:
        raise HTTPException(422, "질문을 입력하거나 고를 항목을 골라 주세요.")
    on = llm.backend() != "rule" and llm._ollama_alive()
    if body.slots:
        try:
            return clean(result.respond(question or None, {"center_db": False}, llm_on=on, slots=body.slots))
        except ValueError as e:
            raise HTTPException(422, str(e))
    if "m" not in _M1:
        _M1["m"] = m1.M1()
    return clean(result.respond(question, {"center_db": False}, llm_on=on, interpret=_M1["m"].interpret))


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


@app.get("/api/health")
def health():
    import recipes
    return {"status": "ok", "web_built": OUT.exists(), "recipes": recipes.WARM}


if OUT.exists():
    app.mount("/", StaticFiles(directory=OUT, html=True), name="web")
