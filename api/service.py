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

import re
import tempfile
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
from core.rules.base import INTERVENE_THRESHOLD, ProposedOrder
from core.synth.generator import generate_trades
from core.synth.personas import NOT_REAL_USER_DISCLAIMER, PRESETS

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
_SESSIONS: dict[str, pd.DataFrame] = {}

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
    return session_id in _SESSIONS


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
    if unresolved:
        warnings.append(
            "종목코드를 못 찾음: "
            + ", ".join(unresolved)
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
    _SESSIONS[session_id] = trades
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
    return trades, _session_as_of(trades), _session_universe(trades)


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
# ⚠ NOT_REAL_USER_DISCLAIMER — 프리셋 5종(n=5)짜리 기준이라 percentile 은 장식에
# 가깝다. 실 사용자 데이터가 쌓이면 거기서 다시 만들 것.
_reference_cache: dict[str, list[float]] | None = None


def _reference_scores() -> dict[str, list[float]]:
    global _reference_cache
    if _reference_cache is not None:
        return _reference_cache

    scores: dict[str, list[float]] = {"disposition_effect": [], "averaging_down": [], "chasing": []}
    for persona in PRESETS.values():
        trades = generate_trades(persona, tickers=DEMO_UNIVERSE, end=DEMO_AS_OF)
        result = build_engine(trades, as_of=DEMO_AS_OF)
        for mod in METRIC_MODULES:
            r = mod.compute(result.timeline, trades, result.episodes)
            scores[r.key].append(r.score_0_100)
    _reference_cache = scores
    return scores


def _percentile(key: str, score: float) -> float:
    ref = _reference_scores().get(key, [])
    if not ref:
        return 50.0
    below_or_equal = sum(1 for s in ref if s <= score)
    return round(below_or_equal / len(ref) * 100, 1)


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
    report = rules_engine.evaluate(order, metric_results, result.timeline, result.episodes)

    contributions = [
        RiskContribution(
            label=BIAS_KEY_LABEL[c.key],
            value=c.score,
            detail=c.evidence[0]["detail"] if c.evidence else f"{BIAS_KEY_LABEL[c.key]} 패턴 없음",
        )
        for c in report.contributions
    ]

    dominant = max(report.contributions, key=lambda c: c.score)
    dominant_metric = next((m for m in metric_results if m.key == dominant.key), None)

    if report.should_intervene and dominant.evidence:
        # 워터폴 순서(chasing → averaging_down → disposition)를 그대로 우선순위로 넘긴다 —
        # guard.get_order_fallback() 이 triggered_keys[0] 을 최우선 룰로 취급한다.
        triggered_keys = [c.key for c in report.contributions if c.triggered]
        coaching = generate_coaching(
            context="order_intervention",
            evidence=dominant.evidence,
            triggered_keys=triggered_keys,
        )
        headline, description = coaching.headline, coaching.body
    elif dominant.triggered:
        # 개별 룰은 트리거됐지만 합산 위험점수가 개입 기준(INTERVENE_THRESHOLD) 미만 —
        # case_count 는 그대로 실제 이력 건수를 보여주므로 headline 이 "이력 없음"이라고
        # 모순되게 말하지 않도록 분리해둔다.
        headline = f"{BIAS_KEY_LABEL[dominant.key]} 이력이 있지만 위험 수준은 아님"
        description = (
            "과거에 비슷한 패턴이 있었지만, 이번 주문의 종합 위험점수는 개입 기준에 못 미칩니다."
        )
    else:
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

    change_rate = 0.0
    holding = result.timeline[result.timeline["ticker"] == order.ticker]
    if not holding.empty:
        prev_close = holding.sort_values("date").iloc[-1]["close"]
        if prev_close:
            change_rate = round((order.price - prev_close) / prev_close * 100, 2)

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
        base_score=0.0,
        contributions=contributions,
        warning=warning,
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
    )


__all__ = [
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
]
