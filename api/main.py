"""FastAPI 앱 — web/(lovulive) 프론트가 붙을 백엔드.

⚠ D 검토용 초안(test-d-backtest 브랜치). D 가 다르게 가고 싶으면 갈아엎어도 됨.

실행:
    uv sync --extra web
    uv run uvicorn api.main:app --reload

지금은 core/synth 페르소나만 데이터 소스로 지원한다(?persona=disposition_prone 등).
실 CSV 업로드는 core/parser 를 붙이면 되는데 아직 라우팅을 안 짬.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api import service
from api.schemas import (
    BacktestResult,
    DiagnosisReport,
    InterventionReport,
    PersonaInfo,
    SimulateOrderRequest,
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


def _validate_persona(persona: str) -> None:
    if persona not in PRESETS:
        raise HTTPException(
            status_code=404,
            detail=f"모르는 페르소나: {persona} (사용 가능: {', '.join(PRESETS)})",
        )


@app.get("/api/personas", response_model=list[PersonaInfo])
def get_personas() -> list[PersonaInfo]:
    return service.list_personas()


@app.get("/api/diagnose", response_model=DiagnosisReport, response_model_by_alias=True)
def get_diagnosis(persona: str = "mixed_realistic") -> DiagnosisReport:
    _validate_persona(persona)
    return service.diagnose(persona)


@app.post("/api/simulate-order", response_model=InterventionReport, response_model_by_alias=True)
def post_simulate_order(
    order: SimulateOrderRequest, persona: str = "mixed_realistic"
) -> InterventionReport:
    _validate_persona(persona)
    return service.simulate_order(persona, order)


@app.get("/api/backtest", response_model=BacktestResult, response_model_by_alias=True)
def get_backtest(persona: str = "mixed_realistic") -> BacktestResult:
    _validate_persona(persona)
    return service.backtest(persona)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
