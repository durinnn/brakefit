"""api/main.py 가 쓰는 비즈니스 로직 — core/* 를 조립해서 api/schemas 형태로 만든다.

⚠ D 검토용 초안(test-d-backtest 브랜치).

데이터 소스는 두 가지다.
  · **페르소나**(?persona=) — core/synth 합성 거래. 기본값이고 데모의 메인 경로다.
    as_of/유니버스가 DEMO_* 로 고정돼 있어 캐시만으로 네트워크 없이 돈다.
  · **세션**(?session=) — 사용자가 POST /api/upload 로 올린 실 거래내역.
    as_of/유니버스는 업로드된 거래에서 뽑는다(§_resolve_trades).

두 경로는 `_resolve_trades()` 한 곳에서만 갈라진다. 그 아래(engine→metrics→rules→
backtest)는 데이터 출처를 전혀 모른다 — docs/schema.md §1 이 유일한 계약이다.
"""

from __future__ import annotations

import logging
import re
import tempfile
from collections import OrderedDict
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from api.schemas import (
    BIAS_KEY_LABEL,
    BIAS_KEY_TO_FRONTEND,
    BacktestResult,
    BiasMetric,
    BlockedCase,
    DiagnosisReport,
    InterventionReport,
    PatternWarning,
    PendingOrder,
    PersonaInfo,
    RiskContribution,
    SimulateOrderRequest,
    UniverseItem,
    UploadSummary,
)
from core import schema
from core.backtest.backtest import run as run_backtest
from core.engine.engine import build as build_engine
from core.guard.guard import generate as generate_coaching
from core.metrics import averaging_down, chasing, disposition
from core.parser import kb_hts
from core.parser.reader import UnreadableExport
from core.rules import engine as rules_engine
from core.rules.base import (
    INTERVENE_THRESHOLD,
    ProposedOrder,
    ReferenceClose,
    reference_close,
)
from core.synth.generator import generate_trades
from core.synth.personas import NOT_REAL_USER_DISCLAIMER, PRESETS

logger = logging.getLogger(__name__)

METRIC_MODULES = (disposition, averaging_down, chasing)

# 데모 유니버스를 작게 잡아서(3종목) 응답 속도를 확보한다 — 캐시가 있어도
# 8종목보다 3종목이 매 요청마다 더 가볍다.
DEMO_UNIVERSE = {"005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER"}
DEMO_AS_OF = date(2026, 8, 18)  # data/cache/prices/ 캐시 범위 안 — 네트워크 불필요

GRADE_THRESHOLDS = (40.0, 70.0)  # score < 40 안정 / < 70 주의 / else 위험
RISK_LEVEL_THRESHOLDS = (INTERVENE_THRESHOLD * 0.6, INTERVENE_THRESHOLD)  # LOW / MEDIUM / HIGH


def list_personas() -> list[PersonaInfo]:
    return [
        PersonaInfo(key=p.key, name=p.name, description=p.description) for p in PRESETS.values()
    ]


def _persona_trades(persona_key: str) -> pd.DataFrame:
    if persona_key not in PRESETS:
        raise KeyError(f"모르는 페르소나: {persona_key} (사용 가능: {', '.join(PRESETS)})")
    return generate_trades(PRESETS[persona_key], tickers=DEMO_UNIVERSE, end=DEMO_AS_OF)


def _period_label(trades: pd.DataFrame) -> str:
    if trades.empty:
        return "-"
    start, end = trades["traded_at"].min(), trades["traded_at"].max()
    return f"{start:%Y.%m.%d} ~ {end:%Y.%m.%d}"


# ── 업로드 세션 ──────────────────────────────────────────────────────────────
# {session_id: 표준 거래내역(docs/schema.md §1)}. **프로세스 메모리에만 있다.**
# DB 를 안 붙이는 건 의도된 축소다(AGENTS.md — 범위를 늘리는 제안보다 줄이는 제안).
# 그래서 서버가 재시작되면(Render 무료 플랜은 유휴 시 슬립 → 콜드스타트) 세션이 전부
# 사라지고 이후 요청은 404 가 된다. 프론트는 404 를 받으면 "다시 업로드" 로 안내할 것.
#
# OrderedDict 인 이유: 배포처인 Render 무료 인스턴스는 메모리 512MB 뿐인데 세션은
# DataFrame 을 통째로 들고 있어서, 아무도 안 지우면 업로드가 쌓이는 만큼 그대로
# 늘어나 OOM 으로 프로세스가 죽는다(= 살아있던 다른 세션까지 전멸). 그래서 LRU 로
# MAX_SESSIONS 개만 유지한다 — 밀려난 세션은 재업로드하면 되는 404 로 끝나지만,
# OOM 은 서비스 전체가 내려간다.
_SESSIONS: OrderedDict[str, pd.DataFrame] = OrderedDict()

# {session_id: 업로드 시점 경고}. _SESSIONS 와 같은 생애주기로 붙어 다닌다.
# DataFrame 과 한 자료구조로 묶지 않은 건, 세션 저장소를 "표준 거래내역 그 자체"로
# 보는 기존 코드·테스트(_SESSIONS[sid] 를 DataFrame 으로 읽음)를 깨지 않기 위해서다.
_SESSION_WARNINGS: dict[str, list[str]] = {}

#: 동시에 들고 있을 업로드 세션 수 상한. 데모 동시 사용자 규모(수 명)의 여유분이다.
MAX_SESSIONS = 50

#: 업로드 파일 크기 상한(5MB). 증권사 export 는 수년치라도 수백KB 수준이라 넉넉하고,
#: 이걸 안 막으면 큰 파일 하나가 read() 한 방에 메모리에 통째로 올라가 위와 같은
#: 이유로 무료 인스턴스를 넘어뜨린다.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: 업로드 파일을 KB export 로 읽어볼 때 시도하는 매핑 순서. 어느 화면인지는 파일만
#: 봐서는 모르므로 위에서부터 시도해서 **거래 행이 나오는 첫 매핑**을 채택한다.
#: 0377(종목별주문/체결집계)은 매매일자 컬럼이 아예 없어 거래를 만들 수 없으므로
#: 여기에 없다 — kb_0377_executions.yaml 하단 주석 참조.
KB_MAPPINGS = (
    "kb_transaction_ledger.yaml",
    "kb_0112_transactions.yaml",
    "kb_0330_realized_pnl.yaml",
)

#: 표준 거래내역 CSV 로 읽을 때 반드시 있어야 하는 컬럼 (docs/schema.md §1).
CSV_REQUIRED_COLUMNS = ("traded_at", "name", "side", "quantity", "price")

#: 시세 조회 실패를 502 로 승격시킬지 판단하는 힌트. core/synth/prices.py 가 던지는
#: ValueError 메시지와 pykrx/네트워크 계층 예외를 잡는다 — 나머지 예외는 그대로
#: 올려보낸다(AGENTS.md "예외는 삼키지 않는다": 진짜 버그를 502 로 숨기지 않기 위함).
_PRICE_ERROR_HINTS = ("pykrx", "시세", "종가")

#: kb_hts.resolve_tickers() 가 "조회 실패 사유" 를 unresolved 에 끼워넣을 때 쓰는 접두어.
#: 종목명과 구분하는 유일한 단서라 여기서 상수로 박아둔다(_fill_tickers 주석 참조).
_TICKER_LOOKUP_FAILURE_PREFIX = "pykrx 조회 실패"


class UploadRejected(ValueError):
    """업로드 파일을 표준 거래내역으로 만들지 못했을 때 (→ HTTP 400)."""


class SessionNotFound(LookupError):
    """모르는 session id (→ HTTP 404). 서버 재시작으로 날아갔을 수도 있다."""


class PriceUnavailable(RuntimeError):
    """pykrx 시세를 못 받아 계산을 끝낼 수 없을 때 (→ HTTP 502).

    페르소나 경로는 data/cache/prices 안에서만 놀아서 여기 안 걸리지만, 업로드된 실
    종목은 캐시에 없어 네트워크를 탄다. 그게 실패하면 서버 버그가 아니라 외부 의존성
    장애이므로 500 이 아니라 502 로 사유를 그대로 돌려준다.
    """


def has_session(session_id: str) -> bool:
    """존재 확인도 '사용'으로 친다 — 진단 직전 검사에서 LRU 순서를 갱신해야
    바로 뒤따라 오는 _resolve_trades() 가 밀려난 세션을 만나지 않는다."""
    if session_id not in _SESSIONS:
        return False
    _SESSIONS.move_to_end(session_id)
    return True


def _store_session(session_id: str, trades: pd.DataFrame, warnings: list[str]) -> None:
    """세션 저장 + 상한 초과분(가장 오래 안 쓴 것부터) 정리."""
    _SESSIONS[session_id] = trades
    _SESSION_WARNINGS[session_id] = list(warnings)
    _SESSIONS.move_to_end(session_id)
    while len(_SESSIONS) > MAX_SESSIONS:
        evicted, _ = _SESSIONS.popitem(last=False)
        _SESSION_WARNINGS.pop(evicted, None)  # 같이 안 지우면 경고만 영원히 쌓인다


def _merge_warnings(*groups: list[str]) -> list[str]:
    """여러 단계의 경고를 순서 유지 + 중복 제거로 합친다.

    업로드 시점 경고와 엔진 경고는 같은 사실을 다른 말로 두 번 적기도 하지만
    (ticker 미해결 등), 문구가 완전히 같을 때만 접는다 — 다르게 적힌 두 줄은
    각각 다른 정보를 담고 있어서 임의로 지우면 사용자가 사유를 잃는다.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for w in group:
            if w not in seen:
                seen.add(w)
                merged.append(w)
    return merged


def _safe_filename(filename: str) -> str:
    """업로드 파일명을 임시 경로에 쓸 수 있는 형태로 정리한다.

    trade_id/source 에 그대로 실리는 값이라 원본 이름을 최대한 살리되, 경로 조작
    (`../`)과 제어문자는 여기서 끊는다.
    """
    name = Path(filename or "upload").name
    name = re.sub(r"[^\w.\-가-힣]", "_", name).strip("._") or "upload"
    return name[:80]


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _parse_kb_export(
    path: Path, reasons: list[str]
) -> tuple[pd.DataFrame, list[schema.SkippedRow], list[str]] | None:
    """KB export 매핑을 순서대로 시도. 거래 행이 나오는 첫 매핑을 채택한다."""
    for mapping in KB_MAPPINGS:
        try:
            result = kb_hts.parse(path, kb_hts.MAPPING_DIR / mapping)
        except UnreadableExport as exc:
            reasons.append(f"{mapping}: {_first_line(exc)}")
            continue
        except Exception as exc:  # 파일이 깨졌거나 예상 밖 구조 — 사유를 남기고 다음 매핑
            reasons.append(f"{mapping}: 읽는 중 오류 ({type(exc).__name__}: {_first_line(exc)})")
            continue
        if result.trades.empty:
            reasons.append(
                f"{mapping}: 헤더는 맞았지만 거래 행이 0건 (스킵 {len(result.skipped)}건)"
            )
            continue
        return result.trades, result.skipped, list(result.warnings)
    return None


def _parse_standard_csv(
    path: Path, reasons: list[str]
) -> tuple[pd.DataFrame, list[schema.SkippedRow], list[str]] | None:
    """표준 거래내역 CSV(docs/schema.md §1 = fixtures/synth/*.csv 형식)로 읽어본다.

    데모 때 fixture 를 그대로 올려 시연할 수 있게 하는 경로다.

    ⚠ `dtype=str` 로 읽는 이유: 종목코드 '035720' 을 pandas 가 정수 35720 으로
    추론해버리면 앞자리 0 이 날아가서 pykrx 조회가 통째로 실패한다(에러 없이 "그런
    종목 없음"으로 조용히 틀리는 유형). 숫자 변환은 schema.coerce() 에 맡긴다.
    """
    try:
        raw = pd.read_csv(path, dtype=str)
    except Exception as exc:
        reasons.append(f"표준 거래내역 CSV: 읽기 실패 ({type(exc).__name__}: {_first_line(exc)})")
        return None

    missing = [c for c in CSV_REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        reasons.append(f"표준 거래내역 CSV: 필수 컬럼 없음 {missing} (docs/schema.md §1 참조)")
        return None

    # schema.coerce() 의 traded_at 정규화는 datetime 계열만 date 로 바꾼다.
    # CSV 에서 온 문자열은 여기서 한 번 datetime64 로 만들어줘야 date 가 된다.
    raw["traded_at"] = pd.to_datetime(raw["traded_at"], errors="coerce")
    if "ticker" in raw.columns:
        raw["ticker"] = raw["ticker"].map(kb_hts.normalize_ticker)

    frame = schema.coerce(raw)
    frame["source_row"] = frame["source_row"].fillna(pd.Series(frame.index, dtype="Int64"))
    frame["source"] = frame["source"].fillna(path.name)

    bad = (
        frame["traded_at"].isna()
        | ~frame["side"].isin(("BUY", "SELL"))
        | frame["quantity"].isna()
        | (frame["quantity"].fillna(0) <= 0)
        | frame["price"].isna()
        | (frame["price"].fillna(0) <= 0)
    )
    skipped = [
        schema.SkippedRow(int(i) + 2, "체결일·매매구분·수량·단가 중 빠진 값이 있음")
        for i in frame.index[bad]  # +2: 1-based + 헤더 행
    ]
    trades = frame.loc[~bad].reset_index(drop=True)

    # 사용자 CSV 에 trade_id 가 없거나 겹치면 schema.validate() 가 막는다 — 여기서 채운다.
    if trades["trade_id"].isna().any() or trades["trade_id"].duplicated().any():
        trades["trade_id"] = [f"{path.name}:csv:{i}" for i in range(len(trades))]
    return trades, skipped, []


def _fill_tickers(trades: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """종목코드가 빈 행을 종목명으로 역매핑한다 (KB 거래내역 화면에는 코드가 없다)."""
    if not trades["ticker"].isna().any():
        return trades
    # 이미 코드가 붙은 행은 지키려고 캐시에 미리 넣는다 — resolve_tickers() 는
    # ticker 컬럼을 통째로 다시 쓰기 때문에, 안 넣으면 알던 코드까지 날아간다.
    cache = {
        str(name): str(ticker)
        for name, ticker in zip(trades["name"], trades["ticker"], strict=False)
        if isinstance(ticker, str) and ticker
    }
    resolved, unresolved = kb_hts.resolve_tickers(trades, cache=cache)
    # resolve_tickers() 의 unresolved 는 두 종류가 한 리스트에 섞여서 온다 —
    # 조회 자체가 실패한 사유("pykrx 조회 실패: ...") 와 진짜 못 찾은 종목명.
    # 그대로 이어붙이면 "종목코드를 못 찾음: pykrx 조회 실패: ..., 삼성전자" 처럼
    # 사유가 종목명인 것처럼 읽힌다. 파서는 B 소유라 손대지 않고 여기서 가른다.
    lookup_failures = [u for u in unresolved if u.startswith(_TICKER_LOOKUP_FAILURE_PREFIX)]
    missing_names = [u for u in unresolved if not u.startswith(_TICKER_LOOKUP_FAILURE_PREFIX)]
    if lookup_failures:
        warnings.append(
            "시세 서버 조회 실패로 종목코드 자동 매핑 불가 — "
            + "; ".join(lookup_failures)
            + " (종목코드가 없는 거래는 진단·백테스트에서 제외됩니다)"
        )
    if missing_names:
        warnings.append(
            "종목코드를 못 찾음: "
            + ", ".join(missing_names)
            + " — 해당 종목은 진단·백테스트에서 제외됩니다 "
            "(0377 종목별주문/체결집계 export 로 코드 사전을 만들면 해결됩니다)"
        )
    return resolved


def ingest_upload(filename: str, content: bytes) -> UploadSummary:
    """업로드 파일 → 표준 거래내역 → 세션 저장. 실패하면 UploadRejected(400)."""
    if not content.strip():
        raise UploadRejected("빈 파일입니다. 증권사에서 받은 거래내역 파일을 올려주세요.")

    reasons: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / _safe_filename(filename)
        path.write_bytes(content)

        source = "kb_export"
        parsed = _parse_kb_export(path, reasons)
        if parsed is None:
            source = "standard_csv"
            parsed = _parse_standard_csv(path, reasons)

    if parsed is None:
        raise UploadRejected(
            "거래내역을 읽지 못했습니다. 시도한 형식과 사유:\n- " + "\n- ".join(reasons)
        )

    trades, skipped, warnings = parsed
    if trades.empty:
        raise UploadRejected(
            f"매매 거래가 0건입니다 (버려진 행 {len(skipped)}개). "
            "조회 기간을 계좌개설일까지 넓혀서 다시 export 해보세요."
        )

    trades = _fill_tickers(trades, warnings)
    trades = trades.sort_values(["traded_at", "source_row"]).reset_index(drop=True)

    # 여기서 막지 않으면 나중에 engine.build() 가 같은 검사로 ValueError 를 던져
    # 진단 요청이 500 으로 죽는다. 업로드 시점에 사유를 알려주는 편이 낫다.
    if problems := schema.validate(trades):
        raise UploadRejected(
            "거래내역이 스키마 검사를 통과하지 못했습니다:\n- " + "\n- ".join(problems)
        )

    session_id = uuid4().hex
    _store_session(session_id, trades, warnings)
    return UploadSummary(
        session_id=session_id,
        trade_count=len(trades),
        skipped_count=len(skipped),
        period=_period_label(trades),
        warnings=warnings,
        source=source,
    )


def _session_as_of(trades: pd.DataFrame) -> date:
    """세션의 기준일 = 마지막 체결일. 그 이후 시세는 룩어헤드라 볼 이유가 없다."""
    return max(trades["traded_at"].dropna())


def _session_universe(trades: pd.DataFrame) -> dict[str, str]:
    known = trades.dropna(subset=["ticker"])
    return {str(t): str(n) for t, n in zip(known["ticker"], known["name"], strict=False)}


def _resolve_trades(
    persona_key: str, session_id: str | None = None
) -> tuple[pd.DataFrame, date, dict[str, str]]:
    """데이터 소스를 고르는 유일한 지점 → (거래내역, 기준일, 유니버스).

    유니버스는 지금은 페르소나 생성기만 쓰지만(룰·엔진은 trades 에서 종목을 직접
    읽는다), 소스별 메타를 한 곳에 모아두려고 같이 돌려준다.
    """
    if session_id is None:
        return _persona_trades(persona_key), DEMO_AS_OF, DEMO_UNIVERSE
    trades = _SESSIONS.get(session_id)
    if trades is None:
        raise SessionNotFound(
            f"모르는 세션: {session_id} — 서버가 재시작되면 업로드 세션이 사라집니다. "
            "거래내역을 다시 업로드해주세요."
        )
    _SESSIONS.move_to_end(session_id)  # 방금 쓴 세션이 LRU 에서 제일 늦게 밀리도록
    return trades, _session_as_of(trades), _session_universe(trades)


def _upload_warnings(session_id: str | None) -> list[str]:
    """업로드 시점 경고(파서 경고·ticker 미해결 등). 페르소나 경로는 항상 빈 목록이다."""
    if session_id is None:
        return []
    return list(_SESSION_WARNINGS.get(session_id, []))


def _guarded(fn, *args, **kwargs):
    """시세 실패를 PriceUnavailable(502) 로 바꾼다. 그 외 예외는 그대로 올린다."""
    try:
        return fn(*args, **kwargs)
    except PriceUnavailable:
        raise
    except Exception as exc:
        if isinstance(exc, OSError) or any(h in str(exc) for h in _PRICE_ERROR_HINTS):
            raise PriceUnavailable(f"시세를 가져오지 못했습니다: {_first_line(exc)}") from exc
        raise


def _grade(score: float) -> str:
    if score < GRADE_THRESHOLDS[0]:
        return "안정"
    if score < GRADE_THRESHOLDS[1]:
        return "주의"
    return "위험"


# ── percentile 기준선 ────────────────────────────────────────────────────────
# ⚠ NOT_REAL_USER_DISCLAIMER — 합성 페르소나로 만든 기준이라 percentile 은 참고용이다.
# 실 사용자 데이터가 쌓이면 거기서 다시 만들 것.
#
# **기준선은 피측정치와 똑같은 생성 조건으로 만든다** — 유니버스도 n_episodes 도
# _persona_trades() 와 같다. 이전 버전은 기준선만 8종목(DEFAULT_UNIVERSE)·300
# episode 로 넓혔는데, 그러면 백분위를 매기는 대상(DEMO_UNIVERSE 3종목·40 episode)과
# 모집단이 달라져서 서로 다른 분포를 비교하게 된다. chasing 점수가 종목 수·에피소드
# 수에 체계적으로 반응하는 탓에 기준선이 통째로 낮게 깔렸고, 그 결과 대조군
# rational_baseline(16.67점)이 "상위 80%" 로 표시됐다 — 분산이 아니라 정의의 문제라
# 표본을 넓히는 걸로는 안 풀린다.
#
# 분산은 대신 **seed 를 여러 개 돌려 표본 수로** 잡는다. 페르소나 5종 × seed 4개 = 20
# 표본(백분위는 5% 단위). 오프셋은 고정 목록이라 결과가 결정론적이고, 오프셋 0 은
# 데모가 실제로 보여주는 그 거래내역이라 피측정치가 항상 기준선 안에 들어간다.
# seed 개수가 4개인 건 프리워밍 예산(3초) 때문이다 — 로컬 측정으로 4개 2.4~2.6s,
# 5개 2.9~3.5s, 6개 3.5~5.0s 였고(비용의 대부분은 metrics 계산), 세 경우 모두
# 페르소나 간 백분위 순위는 같았다. 예산이 늘면 오프셋만 추가하면 된다.
#
# 이 함수는 서버 기동 시 한 번 프리워밍되고 이후 캐시된 값을 쓴다.
_REFERENCE_SEED_OFFSETS = (0, 10, 20, 30)

_reference_cache: dict[str, list[float]] | None = None


def _reference_scores() -> dict[str, list[float]]:
    global _reference_cache
    if _reference_cache is not None:
        return _reference_cache

    scores: dict[str, list[float]] = {"disposition_effect": [], "averaging_down": [], "chasing": []}
    for persona in PRESETS.values():
        for offset in _REFERENCE_SEED_OFFSETS:
            # n_episodes·유니버스는 건드리지 않는다 — 바꾸는 순간 모집단이 갈린다(위 주석).
            ref_persona = replace(persona, seed=persona.seed + offset)
            trades = generate_trades(ref_persona, tickers=DEMO_UNIVERSE, end=DEMO_AS_OF)
            result = build_engine(trades, as_of=DEMO_AS_OF)
            for mod in METRIC_MODULES:
                r = mod.compute(result.timeline, trades, result.episodes)
                scores[r.key].append(r.score_0_100)
    _reference_cache = scores
    return scores


def _percentile(key: str, score: float) -> float:
    """기준선 표본 중 이 점수 **이하**인 비율(%). 점수가 높을수록(=편향이 심할수록) 커진다.

    ⚠ 프론트(web/src/components/BiasMetricCard.tsx)는 이 값을 "상위 N%" 로 찍는데,
    한국어 "상위 1%" 는 보통 극단(=제일 심한 쪽)을 뜻하므로 방향이 반대로 읽힌다.
    표기·환산은 web 오너(D) 결정 사항이라 여기서는 값의 정의만 명시해둔다.
    """
    ref = _reference_scores().get(key, [])
    if not ref:
        return 50.0
    below_or_equal = sum(1 for s in ref if s <= score)
    return round(below_or_equal / len(ref) * 100, 1)


# ── ⓪ 주문 유니버스 ─────────────────────────────────────────────────────────


def _reference_close(ticker: str, as_of: date) -> ReferenceClose | None:
    """주문 폼의 기본값·표시용 등락률이 공유하는 기준 종가. 못 구하면 사유를 로그로.

    ⚠ 룰(core/rules/base.reference_close)과 **같은 함수**를 쓴다. 예전에는 유니버스만
    as_of 당일을 포함하고 룰은 뺐는데, 그래서 주문 폼에 뜬 기준 종가(268,500 · 08-18)
    와 판정 결과의 changeRate 기준(274,500 · 08-14)이 서로 다른 날을 가리켰다.

    예외를 502 로 승격시키지 않고 None 으로 삼키는 게 여기서는 맞다. 이 값은 표시용
    (주문 폼 기본값·등락률)이라, 시세 한 종목을 못 구했다고 종목 목록 전체를 못 주는
    게 더 나쁘다. 사유를 잃지 않도록 로그에는 남긴다.
    """
    ref, warning = reference_close(ticker, as_of)
    if warning:
        logger.warning("기준 종가 없이 진행: %s", warning)
    return ref


def universe(persona_key: str, *, session_id: str | None = None) -> list[UniverseItem]:
    """모의 주문 폼이 고를 수 있는 종목 목록.

    페르소나면 DEMO_UNIVERSE, 업로드 세션이면 그 사람이 실제로 거래한 종목이다
    (_resolve_trades 가 이미 갈라준다). 거래한 적 없는 종목은 timeline 이 없어서
    브레이크 룰이 전부 skip 되므로 — 판정할 수 없는 종목을 고를 수 있게 두면
    "브레이크가 안 걸리네" 로 오해하게 된다.
    """
    _trades, as_of, tickers = _resolve_trades(persona_key, session_id)
    items: list[UniverseItem] = []
    for ticker, name in tickers.items():
        ref = _reference_close(ticker, as_of)
        items.append(
            UniverseItem(
                ticker=ticker,
                name=name,
                last_close=round(ref.close, 2) if ref else None,
                last_date=ref.date.isoformat() if ref else None,
            )
        )
    return items


# ── ① 진단 ───────────────────────────────────────────────────────────────────


def diagnose(persona_key: str, *, session_id: str | None = None) -> DiagnosisReport:
    trades, as_of, _universe = _resolve_trades(persona_key, session_id)
    result = _guarded(build_engine, trades, as_of=as_of)

    metric_results = [
        mod.compute(result.timeline, trades, result.episodes) for mod in METRIC_MODULES
    ]
    metrics = [
        BiasMetric(
            key=BIAS_KEY_TO_FRONTEND[m.key],
            name=BIAS_KEY_LABEL[m.key],
            score=m.score_0_100,
            percentile=_percentile(m.key, m.score_0_100),
            summary=m.evidence[0]["detail"] if m.evidence else "특이 이력 없음",
            sample_count=len(m.evidence),
            delta=None,  # 과거 진단 스냅샷을 저장하는 곳이 없어서 v1 은 항상 None
        )
        for m in metric_results
    ]
    # 개요 점수 = core/rules 의 MAX_CONTRIBUTION 가중치(40/35/25)를 그대로 재사용
    weights = {"chasing": 40.0, "averaging_down": 35.0, "disposition_effect": 25.0}
    overall = sum(m.score_0_100 * weights[m.key] for m in metric_results) / sum(weights.values())

    combined_evidence = [item for m in metric_results for item in m.evidence]
    coaching = generate_coaching(context="report_summary", evidence=combined_evidence)

    return DiagnosisReport(
        period_label=_period_label(trades),
        total_trades=len(trades),
        overall_score=round(overall, 1),
        overall_grade=_grade(overall),
        metrics=metrics,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        headline=coaching.headline,
        body=coaching.body,
        # 업로드 시점 경고(파서·ticker) + 엔진 경고(과매도 클램프·시세 결측)를 같이 준다.
        # 페르소나 경로는 둘 다 비어서 빈 배열로 나간다.
        warnings=_merge_warnings(_upload_warnings(session_id), result.warnings),
    )


# ── ② 개입 ───────────────────────────────────────────────────────────────────


def simulate_order(
    persona_key: str, order_req: SimulateOrderRequest, *, session_id: str | None = None
) -> InterventionReport:
    trades, as_of, _universe = _resolve_trades(persona_key, session_id)
    result = _guarded(build_engine, trades, as_of=as_of)
    metric_results = [
        mod.compute(result.timeline, trades, result.episodes) for mod in METRIC_MODULES
    ]

    order = ProposedOrder(
        ticker=order_req.ticker,
        name=order_req.name,
        side=order_req.side,
        quantity=order_req.quantity,
        price=order_req.price,
    )
    # as_of 를 같이 넘긴다 — 룰이 "지금 보유 중인가 / 기준 종가를 어디까지 볼지"를 정할 때
    # 기준 시점이 필요하다(core/rules/chasing_rule.py 모듈 docstring).
    report = rules_engine.evaluate(order, metric_results, result.timeline, result.episodes, as_of)
    for w in report.warnings:
        # 룰이 판정을 못 한 사유(시세 조회 실패 등). 응답 스키마에는 아직 자리가 없어
        # 로그로만 남긴다 — 그래도 삼키지는 않는다(AGENTS.md).
        logger.warning("판정 경고 [%s %s]: %s", order.ticker, order.side, w)

    contributions = [
        RiskContribution(
            label=BIAS_KEY_LABEL[c.key],
            value=c.score,
            detail=c.evidence[0]["detail"] if c.evidence else f"{BIAS_KEY_LABEL[c.key]} 패턴 없음",
        )
        for c in report.contributions
    ]

    # 지배 편향은 "발동한 룰 중 기여 최대" — 개입 조건이 triggered 기준이라(core/rules/engine.py)
    # 과거 점수만 높고 이번 주문에선 발동하지 않은 룰이 팝업 문구를 가져가면 안 된다.
    # 아무 룰도 발동 안 한 경우에만 기존대로 전체 중 최대를 쓴다(전부 0점이면 워터폴 첫 룰).
    triggered = [c for c in report.contributions if c.triggered]
    dominant = max(triggered or report.contributions, key=lambda c: c.score)
    dominant_metric = next((m for m in metric_results if m.key == dominant.key), None)

    if report.should_intervene and dominant.evidence:
        # 워터폴 순서(chasing → averaging_down → disposition)를 그대로 우선순위로 넘긴다 —
        # guard.get_order_fallback() 이 triggered_keys[0] 을 최우선 룰로 취급한다.
        triggered_keys = [c.key for c in triggered]
        coaching = generate_coaching(
            context="order_intervention",
            evidence=dominant.evidence,
            triggered_keys=triggered_keys,
        )
        headline, description = coaching.headline, coaching.body
    else:
        # 발동한 룰이 하나라도 있으면 should_intervene 이 True 이므로 여기는 "아무것도
        # 발동 안 함" 뿐이다 — 예전의 "발동은 했는데 점수가 임계 미만" 상태는 사라졌다.
        headline = "과거 패턴 이력 없음"
        description = "이번 주문은 과거 편향 패턴과 뚜렷이 겹치지 않습니다."

    warning = PatternWarning(
        headline=headline,
        case_count=len(dominant_metric.evidence) if dominant_metric else 0,
        average_return=_average_return(dominant_metric),
        description=description,
    )

    risk_score = report.risk_score
    if risk_score < RISK_LEVEL_THRESHOLDS[0]:
        risk_level = "LOW"
    elif risk_score < RISK_LEVEL_THRESHOLDS[1]:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    # 표시용 등락률도 룰이 판정에 쓴 것과 **같은 종가**를 기준으로 한다. 예전에는
    # timeline 마지막 행의 close 를 썼는데(= 보유 기간에만 존재 + 청산된 옛 에피소드면
    # stale), 화면의 "기준 종가 대비 %"와 추격매수 룰의 급등률이 서로 다른 숫자를
    # 가리켰다. 미보유 종목은 아예 0.0% 로 나갔고.
    # /api/universe 의 lastClose 와도 같은 헬퍼다 — 폼에 뜬 종가와 팝업의 기준이 갈리면
    # 사용자에겐 그냥 틀린 숫자로 보인다.
    ref = _reference_close(order.ticker, as_of)
    change_rate = round((order.price - ref.close) / ref.close * 100, 2) if ref else 0.0

    return InterventionReport(
        order=PendingOrder(
            ticker=order.ticker,
            name=order.name,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            change_rate=change_rate,
        ),
        risk_score=risk_score,
        risk_level=risk_level,
        should_intervene=report.should_intervene,
        base_score=0.0,
        contributions=contributions,
        warning=warning,
        # 지배 편향을 프론트가 contributions 의 value 최댓값으로 되짚지 않게 그대로 싣는다.
        # label 문자열로 룰을 역추적하는 코드는 라벨을 바꾸는 순간 조용히 틀린다.
        dominant_key=BIAS_KEY_TO_FRONTEND[dominant.key] if report.should_intervene else None,
        suggestions=_suggestions(
            report.should_intervene, dominant.key if report.should_intervene else None
        ),
    )


def _average_return(dominant_metric) -> float:
    """dominant_metric.evidence 의 return_pct 평균(%).

    return_pct 는 "매수/판정 시점의 평가손익률·급등률" 이지, 그 이후 실제
    수익률이 아니다(사후 성과 추적은 core/backtest 영역 — 별도 논의 필요).
    evidence 에 return_pct 가 없는 항목은 평균에서 제외한다.
    """
    if dominant_metric is None:
        return 0.0
    returns = [e["return_pct"] for e in dominant_metric.evidence if "return_pct" in e]
    return round(sum(returns) / len(returns), 2) if returns else 0.0


def _suggestions(should_intervene: bool, dominant_key: str | None) -> list[str]:
    if not should_intervene:
        return ["평소 패턴과 크게 다르지 않습니다. 계획대로 진행해도 좋습니다."]
    canned = {
        "averaging_down": [
            "손실 원인을 다시 점검한 뒤 결정하세요.",
            "분할 매수 대신 관망을 고려해보세요.",
        ],
        "chasing": [
            "급등 직후보다는 눌림목을 기다려보세요.",
            "추격 대신 지정가 주문으로 바꿔보세요.",
        ],
        "disposition_effect": ["목표 수익률을 미리 정해두고 지켜보세요."],
    }
    return canned.get(dominant_key, ["잠시 멈추고 다시 검토해보세요."])


# ── ③ 증명 ───────────────────────────────────────────────────────────────────


def backtest(persona_key: str, *, session_id: str | None = None) -> BacktestResult:
    trades, as_of, _universe = _resolve_trades(persona_key, session_id)
    result = _guarded(run_backtest, trades, as_of=as_of)

    return BacktestResult(
        period_label=_period_label(trades),
        intervention_count=result.intervention_count,
        avoided_loss=result.avoided_loss,
        missed_gain=result.missed_gain,
        net_benefit=result.net_benefit,
        net_benefit_rate=round(result.net_benefit_rate, 2),
        hit_rate=round(result.hit_rate, 1),
        cases=[
            BlockedCase(
                date=c.traded_at.isoformat(),
                name=c.name,
                impact=c.impact,
                bias_key=BIAS_KEY_TO_FRONTEND[c.bias_key],
            )
            for c in result.cases
        ],
        warnings=_merge_warnings(_upload_warnings(session_id), result.warnings),
    )


__all__ = [
    "MAX_SESSIONS",
    "MAX_UPLOAD_BYTES",
    "NOT_REAL_USER_DISCLAIMER",
    "PriceUnavailable",
    "SessionNotFound",
    "UploadRejected",
    "backtest",
    "diagnose",
    "has_session",
    "ingest_upload",
    "list_personas",
    "simulate_order",
    "universe",
]
