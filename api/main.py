"""FastAPI 앱 — web/(lovulive) 프론트가 붙을 백엔드.

⚠ D 검토용 초안(test-d-backtest 브랜치). D 가 다르게 가고 싶으면 갈아엎어도 됨.

실행:
    uv sync --extra web
    uv run uvicorn api.main:app --reload

데이터 소스는 두 가지다.
  · `?persona=disposition_prone` — core/synth 합성 거래 (기본값, 네트워크 불필요)
  · `?session=<sessionId>`       — POST /api/upload 로 올린 실 거래내역
session 이 있으면 persona 는 무시된다. 세션은 서버 메모리에만 있어서 재시작하면
사라진다(→ 404). api/service.py 의 _SESSIONS 주석 참조.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import service
from api.schemas import (
    BacktestResult,
    DiagnosisReport,
    InterventionReport,
    PersonaInfo,
    SimulateOrderRequest,
    UploadSummary,
)
from core.synth.personas import PRESETS

app = FastAPI(title="매매 브레이크 API", version="0.1.0-draft")

# lovulive(Next.js, 기본 3000번)가 로컬에서 바로 붙을 수 있게 — 배포 시 D 가 좁힐 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(service.PriceUnavailable)
def _handle_price_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """시세(pykrx) 장애는 서버 버그가 아니라 상류 의존성 실패 — 502 로 사유를 준다."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def _validate_source(persona: str, session: str | None) -> None:
    """session 이 주어지면 그쪽만 검사한다 (persona 는 무시되는 값이라 검사 의미 없음)."""
    if session is not None:
        if not service.has_session(session):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"모르는 세션: {session} — 서버가 재시작되면 업로드 세션이 사라집니다. "
                    "거래내역을 다시 업로드해주세요."
                ),
            )
        return
    if persona not in PRESETS:
        raise HTTPException(
            status_code=404,
            detail=f"모르는 페르소나: {persona} (사용 가능: {', '.join(PRESETS)})",
        )


@app.get("/api/personas", response_model=list[PersonaInfo])
def get_personas() -> list[PersonaInfo]:
    return service.list_personas()


@app.post("/api/upload", response_model=UploadSummary, response_model_by_alias=True)
async def post_upload(file: Annotated[UploadFile, File()]) -> UploadSummary:
    """거래내역 파일 업로드 → sessionId 발급.

    KB증권 export(.xls/.xlsx) 와 표준 거래내역 CSV(docs/schema.md §1) 를 받는다.
    """
    content = await file.read()
    try:
        return service.ingest_upload(file.filename or "upload", content)
    except service.UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/diagnose", response_model=DiagnosisReport, response_model_by_alias=True)
def get_diagnosis(persona: str = "mixed_realistic", session: str | None = None) -> DiagnosisReport:
    _validate_source(persona, session)
    return service.diagnose(persona, session_id=session)


@app.post("/api/simulate-order", response_model=InterventionReport, response_model_by_alias=True)
def post_simulate_order(
    order: SimulateOrderRequest,
    persona: str = "mixed_realistic",
    session: str | None = None,
) -> InterventionReport:
    _validate_source(persona, session)
    return service.simulate_order(persona, order, session_id=session)


@app.get("/api/backtest", response_model=BacktestResult, response_model_by_alias=True)
def get_backtest(persona: str = "mixed_realistic", session: str | None = None) -> BacktestResult:
    _validate_source(persona, session)
    return service.backtest(persona, session_id=session)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
