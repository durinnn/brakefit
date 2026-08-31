"""api/main.py 가 쓰는 비즈니스 로직 — core/* 를 조립해서 api/schemas 형태로 만든다.

⚠ D 검토용 초안(test-d-backtest 브랜치).

데이터 소스는 지금은 core/synth 페르소나만 지원한다(§persona). 실 CSV 업로드는
core/parser 를 붙이면 되는데(AGENTS.md 범위엔 있음), API 라우팅까지는 아직 안 짬 —
D 가 붙일지 B 가 이어서 할지는 팀 판단.
"""

from __future__ import annotations

from datetime import date, datetime

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
)
from core.backtest.backtest import run as run_backtest
from core.engine.engine import build as build_engine
from core.guard.guard import generate as generate_coaching
from core.metrics import averaging_down, chasing, disposition
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


def diagnose(persona_key: str) -> DiagnosisReport:
    trades = _persona_trades(persona_key)
    result = build_engine(trades, as_of=DEMO_AS_OF)

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

    return DiagnosisReport(
        period_label=_period_label(trades),
        total_trades=len(trades),
        overall_score=round(overall, 1),
        overall_grade=_grade(overall),
        metrics=metrics,
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )


# ── ② 개입 ───────────────────────────────────────────────────────────────────


def simulate_order(persona_key: str, order_req: SimulateOrderRequest) -> InterventionReport:
    trades = _persona_trades(persona_key)
    result = build_engine(trades, as_of=DEMO_AS_OF)
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
        description = "과거에 비슷한 패턴이 있었지만, 이번 주문의 종합 위험점수는 개입 기준에 못 미칩니다."
    else:
        headline = "과거 패턴 이력 없음"
        description = "이번 주문은 과거 편향 패턴과 뚜렷이 겹치지 않습니다."

    warning = PatternWarning(
        headline=headline,
        case_count=len(dominant_metric.evidence) if dominant_metric else 0,
        average_return=0.0,  # TODO: 지표 evidence 에 수익률 숫자가 아직 없음 (D/C 협의 필요)
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


def backtest(persona_key: str) -> BacktestResult:
    trades = _persona_trades(persona_key)
    result = run_backtest(trades, as_of=DEMO_AS_OF)

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
    "backtest",
    "diagnose",
    "list_personas",
    "simulate_order",
]
