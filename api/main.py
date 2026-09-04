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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """기동 시 percentile 기준선을 미리 계산해둔다.

    _reference_scores() 는 페르소나 5종을 전부 생성해서 engine·metrics 를 돌리므로
    첫 호출이 무겁다. Render 무료 플랜은 유휴 시 슬립 → 콜드스타트라, 안 데워두면
    시연 중 첫 /api/diagnose 가 그 비용을 그대로 뒤집어쓴다.

    실패해도 서버는 떠야 한다(기준선은 percentile 장식용이고, 실패해도 _percentile()
    이 50.0 폴백을 준다). 대신 사유 없이 삼키지는 않는다 — logging.exception 으로
    스택을 남긴다(AGENTS.md "예외는 삼키지 않는다").
    """
    try:
        service._reference_scores()
    except Exception:
        logger.exception("기준선 프리워밍 실패 — 첫 진단 요청에서 다시 시도된다")
    yield


app = FastAPI(title="매매 브레이크 API", version="0.1.0-draft", lifespan=lifespan)

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
    # 파일은 이미 통째로 메모리에 올라와 있다 — 크기 검사를 여기서 하는 건 이번 요청을
    # 막기 위해서가 아니라, 큰 파일이 세션에 눌러앉아 무료 인스턴스(512MB)를 계속
    # 갉아먹는 걸 막기 위해서다. 상한 근거는 api/service.MAX_UPLOAD_BYTES 주석 참조.
    if len(content) > service.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"업로드 파일은 {service.MAX_UPLOAD_BYTES // 1024 // 1024}MB 이하만 허용됩니다 "
                f"(받은 크기: {len(content) / 1024 / 1024:.1f}MB). "
                "조회 기간을 좁혀서 다시 export 해주세요."
            ),
        )
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
