"""동네 생활 진단 API와 화면 제공. 분석·Agent 로직은 agent.py·tools.py를 그대로 부르고, 여기서는 화면이 쓰기 좋은 형태로만 묶는다.
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
import agent  # noqa: E402
import llm  # noqa: E402
import tools as tl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "out"
METRICS = [("점포수", "점포 수", "곳"), ("방문거주비", "방문/거주 지수", ""), ("버스일평균", "버스 일평균 이용", "명"), ("고령비중", "거주 60대 이상 비중", "%"), ("숙박특화계수", "숙박 특화계수", "")]
COMPARE_NAMES = {"stores": "점포 수(곳)", "close_3y_pct": "음식점 3년 폐업률(%)", "close_label": "폐업률 판정", "survival_5y_pct": "음식점 5년 생존율(%)", "survival_n": "생존율 표본(건)", "survival_label": "생존율 판정",
                 "visit_index": "방문/거주 지수", "work_index": "근무/거주 지수", "old_pct": "거주 60대 이상 비중(%)", "young_pct": "거주 20~30대 비중(%)", "bus_daily": "버스 일평균 이용(명)"}
# 앞 질문의 동네를 이어받지 않는 말. 다른 곳이나 제주 전체를 묻는 질문에 앞 동네를 붙이면 질문과 다른 답이 된다(이중 검토 011).
NO_CARRY = re.compile(r"비슷한|다른\s*(동네|곳|지역)|주변|인근|제주\s*전체|도\s*전체")
COMPARE_WORD = re.compile(r"비교|차이|대비")
CATEGORIES = ["카페", "한식", "일식", "중식", "치킨", "분식", "횟집", "주점", "편의점", "숙박", "소매", "미용", "약국", "학원", "병원"]

app = FastAPI(title="동네 생활 진단 API")


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


def checked(result):
    """도구가 돌려준 오류를 화면이 처리할 수 있는 오류로 바꾼다."""
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    return JSONResponse({"detail": "처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요."}, status_code=500)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=200)
    context_dongs: list[str] = Field(default_factory=list, max_length=4)


def carry_context(question, context):
    """동네 없이 이어 묻는 질문에 앞 질문의 동네를 붙인다. 붙였으면 화면에 그대로 알린다."""
    if not context or NO_CARRY.search(question):
        return question, []
    it = agent.interpret(question)
    if it["scope"] == "out" or it["ambiguous"]:
        return question, []
    known = [d for d in context if d in tl.dongs() and d not in it["dongs"]]
    if it["dongs"]:  # "이도2동과 비교해 줘": 앞 동네와 합쳐야 비교표가 나온다. 비교가 아니면 새로 말한 동네만 본다
        if COMPARE_WORD.search(question) and len(it["dongs"]) == 1 and known:
            known = known[:3]
            return " ".join(known) + " " + question, known
        return question, []
    if it["topic"]["rank"] and len(known) < 2:  # 두 동네를 보던 중의 "어디가 더 많아?"만 그 안에서 답한다. 나머지 순위 질문은 제주 전체 순위다
        return question, []
    return (" ".join(known) + " " + question, known) if known else (question, [])


@app.post("/api/ask")
def ask(body: Ask):
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "질문을 입력해 주세요.")
    effective, carried = carry_context(question, body.context_dongs)
    result = agent.run(effective)
    return clean({**result, "question": question, "effective_question": effective, "carried_dongs": carried})


@app.get("/api/meta")
def meta():
    be = llm.backend()
    label = {"claude": "Claude", "ollama": f"로컬 모델({llm.DEFAULT_OLLAMA_MODEL})", "rule": "LLM 없음(기본 계획)"}.get(be, be)
    m = tl.meta()
    j = tl.T("km").query("dong == '제주 전체'").sort_values("year")
    pop = tl.T("pop_month").groupby("ym")[["visit", "resd"]].sum()
    return clean({
        "backend": be, "backend_label": label, "dongs": tl.dongs(), "categories": CATEGORIES,
        "metrics": [{"key": k, "label": n, "unit": u} for k, n, u in METRICS],
        "jeju_survival": [{"year": int(y), "pct": round(float(p), 1)} for y, p in zip(j["year"], j["survival_pct"])],
        "jeju_visit": {ym: round(float(v), 2) for ym, v in (pop["visit"] / pop["resd"]).items()},
        "pop_days": m.get("pop_days"), "pop_last": m.get("pop_last"), "bus_last": m.get("bus_last"), "rest_last": m.get("rest_last"),
    })


@app.get("/api/map")
def map_data():
    d = tl.T("map_dong")
    values = {k: tl._metric(k) for k, _, _ in METRICS}
    rows = [{"dong": r.dong, "lon": round(float(r.lon), 5), "lat": round(float(r.lat), 5), "values": {k: values[k].get(r.dong) for k in values}} for r in d.itertuples()]
    g = tl.T("map_grid")
    return clean({"dongs": rows, "grid": [[round(float(a), 3), round(float(b), 3)] for a, b in zip(g["lon"], g["lat"])]})


@app.get("/api/dong/{dong}")
def dong_detail(dong: str, category: Optional[str] = Query(default=None, max_length=30)):
    profile = checked(tl.dong_profile(dong))
    name = profile["dong"]
    out = {"profile": profile, "biz": checked(tl.biz_diagnostic(name, start_year=2019, end_year=2024)), "population": checked(tl.population_mix(name)), "bus": tl.bus_usage(name)}
    if category:
        out["category_biz"] = checked(tl.biz_diagnostic(name, category=category, start_year=2019, end_year=2024))
    return clean(out)


@app.get("/api/compare")
def compare(dongs: list[str] = Query(default=[])):
    names = list(dict.fromkeys(dongs))
    if not 2 <= len(names) <= 4:
        raise HTTPException(422, "비교할 동네를 2곳 이상 4곳 이하로 골라 주세요.")
    ps = [checked(tl.dong_profile(d)) for d in names]
    rows = [{"label": label, "values": {p["dong"]: (f"{p['values'][k]:,}" if isinstance(p["values"][k], (int, float, np.integer, np.floating)) else str(p["values"][k])) for p in ps}} for k, label in COMPARE_NAMES.items()]
    rows.append({"label": "특화계수 최고 업종", "values": {p["dong"]: f"{p['values']['top_lq'][0]['major']} {p['values']['top_lq'][0]['lq']}" for p in ps}})
    return clean({"dongs": [p["dong"] for p in ps], "rows": rows, "profiles": ps, "limits": list(dict.fromkeys(x for p in ps for x in p["limits"]))})


class Interpret(BaseModel):
    question: str = Field(..., max_length=300)


_m1 = None


@app.post("/api/interpret")
def interpret(body: Interpret):
    """W2 M1 질의 해석: 질문 Tuple + 의도 확인 카드 + 확신도 + 쓴 경로(B3 / 사전 규칙 대체) + 처리 시간."""
    global _m1
    q = body.question.strip()
    if not q:
        raise HTTPException(422, "질문을 입력해 주세요.")
    if _m1 is None:
        import m1
        _m1 = m1.M1()
    return clean(_m1.interpret(q))


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
    return {"status": "ok", "web_built": OUT.exists()}


if OUT.exists():
    app.mount("/", StaticFiles(directory=OUT, html=True), name="web")
