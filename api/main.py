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
import threading
import time
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
    UniverseItem,
    UploadSummary,
)
from core.synth.personas import PRESETS

logger = logging.getLogger(__name__)


#: 프리워밍 스레드 핸들. 테스트가 join() 으로 완료를 기다리는 용도 — 운영에서는
#: 아무도 안 본다(데몬 스레드라 프로세스가 죽을 때 같이 죽는다).
_prewarm_thread: threading.Thread | None = None


def _route_logs_to_uvicorn() -> None:
    """`api.*` 로거를 uvicorn 핸들러에 붙인다 — 안 붙이면 로그가 통째로 사라진다.

    ⚠ 실측으로 알아낸 것: uvicorn 은 자기 로거(uvicorn / uvicorn.error / uvicorn.access)
    만 설정하고 root 는 건드리지 않는다. root 에 핸들러가 없으면 logging.lastResort 가
    WARNING 이상만 stderr 로 흘리므로, 우리 logger.info(프리워밍 진행 상황)는 Render
    로그에 한 줄도 안 찍힌다. 그렇다고 basicConfig() 로 root 를 손대면 남의 로거까지
    설정을 바꾸게 되니, 우리 패키지 로거 하나에만 uvicorn 핸들러를 빌려 붙인다.

    ⚠ 핸들러는 "uvicorn" 에서 가져온다 — "uvicorn.error" 는 uvicorn 기본 LOGGING_CONFIG
    에서 핸들러 없이 부모("uvicorn")로 propagate 만 하게 돼 있어서, 거기서 찾으면 항상
    빈 리스트다(이걸 몰라서 한 번 헛짚었다).
    """
    handlers = logging.getLogger("uvicorn").handlers or logging.getLogger("uvicorn.error").handlers
    api_logger = logging.getLogger("api")
    if handlers and not api_logger.handlers:
        api_logger.handlers = list(handlers)
        api_logger.setLevel(logging.INFO)


def _prewarm_personas() -> None:
    """페르소나 5종의 진단·백테스트를 미리 계산해 service 쪽 캐시를 채운다.

    Render 무료 인스턴스에서 /api/backtest 가 16초였다(콜드·웜 구분 없이). 페르소나
    결과는 결정론적이라 캐시가 정답인데, 캐시는 "누군가 한 번 눌러야" 채워진다 —
    그 한 번이 하필 심사 시연이면 의미가 없다. 그래서 기동 직후에 우리가 먼저 누른다.

    ⚠ 반드시 **데몬 스레드**로 돌린다. 이 계산은 로컬에서도 7초대(Render 는 훨씬 더)라
    lifespan 안에서 동기로 하면 Render 헬스체크가 기동 실패로 판단할 수 있다. 서버는
    먼저 뜨고 캐시는 뒤따라 채워지는 편이 맞다 — 그 사이 들어온 요청은 예전처럼
    직접 계산할 뿐이고(같은 키를 중복 계산해도 값이 같아서 무해), 캐시가 채워진
    뒤부터 빨라진다.
    """
    started = time.perf_counter()
    for key in PRESETS:
        t0 = time.perf_counter()
        service.diagnose(key)
        service.backtest(key)
        logger.info("프리워밍: %s 완료 (%.2fs)", key, time.perf_counter() - t0)
    logger.info(
        "프리워밍: 페르소나 %d종 전부 완료 (%.2fs)", len(PRESETS), time.perf_counter() - started
    )


def _prewarm_personas_guarded() -> None:
    """프리워밍 실패가 서버를 못 죽이게 막는다 — 캐시는 어디까지나 가속 장치다.

    실패하면 해당 페르소나는 요청 때 예전처럼 직접 계산될 뿐이다. 대신 사유를 삼키지는
    않는다(AGENTS.md) — 스택을 남긴다. 스레드 안에서 안 잡으면 threading 기본 훅이
    stderr 로만 뱉고 우리 로그 포맷 밖으로 새어 나간다.
    """
    try:
        _prewarm_personas()
    except Exception:
        logger.exception("페르소나 프리워밍 실패 — 해당 요청에서 직접 계산된다")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """기동 시 percentile 기준선을 미리 계산하고, 페르소나 결과는 뒤에서 데운다.

    _reference_scores() 는 페르소나 5종 × seed 4개 = 20벌을 생성해서 engine·metrics 를
    돌리므로 첫 호출이 무겁다(로컬 측정 2.4~2.6초). Render 무료 플랜은 유휴 시 슬립 →
    콜드스타트라, 안 데워두면 시연 중 첫 /api/diagnose 가 그 비용을 그대로 뒤집어쓴다.
    이건 기동을 막고서라도 먼저 한다 — 뒤이어 도는 프리워밍이 이 값을 필요로 한다.

    실패해도 서버는 떠야 한다(기준선은 percentile 장식용이고, 실패해도 _percentile()
    이 50.0 폴백을 준다). 대신 사유 없이 삼키지는 않는다 — logging.exception 으로
    스택을 남긴다(AGENTS.md "예외는 삼키지 않는다").
    """
    global _prewarm_thread
    _route_logs_to_uvicorn()
    try:
        service._reference_scores()
    except Exception:
        logger.exception("기준선 프리워밍 실패 — 첫 진단 요청에서 다시 시도된다")
    _prewarm_thread = threading.Thread(
        target=_prewarm_personas_guarded, name="persona-prewarm", daemon=True
    )
    _prewarm_thread.start()
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


@app.get("/api/universe", response_model=list[UniverseItem], response_model_by_alias=True)
def get_universe(
    persona: str = "mixed_realistic", session: str | None = None
) -> list[UniverseItem]:
    """모의 주문 폼(/trade)의 종목 select 재료 — 이 데이터 소스로 판정 가능한 종목만.

    lastClose 는 as_of 이하의 마지막 종가라 폼 기본가로 그대로 써도 룩어헤드가 아니다.
    """
    _validate_source(persona, session)
    return service.universe(persona, session_id=session)


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
