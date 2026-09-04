"""데모용 실제 계산값 출력 스크립트.

실제 코드(metrics/rules/guard)를 실제로 돌리되,
화면에서 보기 좋도록 편향이 적당히 드러나는 시나리오로 설계한 fixture를 사용.

시나리오 설계 목표:
  처분효과 ~80점 : 이익 종목은 빨리 팔고, 손실 종목은 오래 버팀
  물타기   ~57점 : 전체 매수 중 57% 가 손실 상태 추가매수
  추격매수 ~38점 : 전체 매수 중 3/8건이 급등 후 진입
  → 데모 주문(삼성전자 BUY, 손실 중 + 급등 추격) → 룰 2개 발동, 위험점수 ~57점
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from core.metrics import averaging_down, chasing, disposition
from core.rules import engine as rules_engine
from core.rules.base import ProposedOrder
from core.guard.guard import generate

# ── EPISODES ─────────────────────────────────────────────────────────────────
# 처분효과: 익절 2건(빠름) / 손절 1건(늦음) + 현재 손실 2건 보유
# → PGR = 2/(2+0) = 1.0, PLR = 1/(1+2) = 0.33, DE = 0.67, score ≈ 83

EPISODES = pd.DataFrame([
    # 청산된 이익 건 2개 (각각 8일, 12일 만에 익절)
    dict(episode_id="000660:2026-06-01", ticker="000660", name="SK하이닉스",
         opened_at="2026-06-01", closed_at="2026-06-09",
         realized_pnl=420_000, max_unrealized_loss=-5_000, max_unrealized_loss_pct=-0.003,
         add_buy_count=0, holding_days=8, is_open=False),
    dict(episode_id="247540:2026-06-10", ticker="247540", name="에코프로비엠",
         opened_at="2026-06-10", closed_at="2026-06-22",
         realized_pnl=280_000, max_unrealized_loss=-8_000, max_unrealized_loss_pct=-0.005,
         add_buy_count=0, holding_days=12, is_open=False),
    # 청산된 손실 건 1개 (47일 만에 손절)
    dict(episode_id="035420:2026-05-01", ticker="035420", name="NAVER",
         opened_at="2026-05-01", closed_at="2026-06-17",
         realized_pnl=-380_000, max_unrealized_loss=-450_000, max_unrealized_loss_pct=-0.12,
         add_buy_count=1, holding_days=47, is_open=False),
    # 현재 보유 손실 2개
    dict(episode_id="005930:2026-08-01", ticker="005930", name="삼성전자",
         opened_at="2026-08-01", closed_at=None,
         realized_pnl=0, max_unrealized_loss=-150_000, max_unrealized_loss_pct=-0.071,
         add_buy_count=2, holding_days=28, is_open=True),
    dict(episode_id="035720:2026-07-15", ticker="035720", name="카카오",
         opened_at="2026-07-15", closed_at=None,
         realized_pnl=0, max_unrealized_loss=-95_000, max_unrealized_loss_pct=-0.079,
         add_buy_count=1, holding_days=14, is_open=True),
])

# ── TIMELINE (최신 행 = 현재 상태) ───────────────────────────────────────────
# 삼성전자: 현재 평가손실 -150,000원 (avg_cost 70,000, close 60,000, 25주)
# 카카오: 현재 평가손실 -95,000원

TIMELINE = pd.DataFrame([
    # 삼성전자 — 진입 후 계속 하락 중
    dict(date="2026-08-01", ticker="005930", name="삼성전자",
         quantity=10, avg_cost=70_000, close=70_000,
         unrealized_pnl=0, unrealized_pct=0.0, realized_pnl=0,
         holding_days=1, episode_id="005930:2026-08-01"),
    dict(date="2026-08-07", ticker="005930", name="삼성전자",
         quantity=15, avg_cost=68_000, close=64_000,
         unrealized_pnl=-60_000, unrealized_pct=-0.029, realized_pnl=0,
         holding_days=7, episode_id="005930:2026-08-01"),
    dict(date="2026-08-14", ticker="005930", name="삼성전자",
         quantity=20, avg_cost=67_000, close=63_000,
         unrealized_pnl=-80_000, unrealized_pct=-0.030, realized_pnl=0,
         holding_days=14, episode_id="005930:2026-08-01"),
    # 최신 (현재 상태): 손실 중
    dict(date="2026-08-28", ticker="005930", name="삼성전자",
         quantity=25, avg_cost=67_200, close=61_000,
         unrealized_pnl=-155_000, unrealized_pct=-0.092, realized_pnl=0,
         holding_days=28, episode_id="005930:2026-08-01"),
    # 카카오
    dict(date="2026-07-15", ticker="035720", name="카카오",
         quantity=20, avg_cost=38_000, close=38_000,
         unrealized_pnl=0, unrealized_pct=0.0, realized_pnl=0,
         holding_days=1, episode_id="035720:2026-07-15"),
    dict(date="2026-07-22", ticker="035720", name="카카오",
         quantity=30, avg_cost=37_200, close=35_500,
         unrealized_pnl=-51_000, unrealized_pct=-0.046, realized_pnl=0,
         holding_days=7, episode_id="035720:2026-07-15"),
    # 최신 (현재 상태)
    dict(date="2026-08-28", ticker="035720", name="카카오",
         quantity=30, avg_cost=37_200, close=34_000,
         unrealized_pnl=-96_000, unrealized_pct=-0.086, realized_pnl=0,
         holding_days=14, episode_id="035720:2026-07-15"),
    # 에코프로비엠 (익절 — timeline 필요)
    dict(date="2026-06-10", ticker="247540", name="에코프로비엠",
         quantity=5, avg_cost=45_000, close=49_000,
         unrealized_pnl=20_000, unrealized_pct=0.089, realized_pnl=0,
         holding_days=1, episode_id="247540:2026-06-10"),
    dict(date="2026-06-17", ticker="247540", name="에코프로비엠",
         quantity=5, avg_cost=45_000, close=52_000,
         unrealized_pnl=35_000, unrealized_pct=0.156, realized_pnl=0,
         holding_days=8, episode_id="247540:2026-06-10"),
    dict(date="2026-06-22", ticker="247540", name="에코프로비엠",
         quantity=0, avg_cost=45_000, close=54_000,
         unrealized_pnl=0, unrealized_pct=0.0, realized_pnl=280_000,
         holding_days=12, episode_id="247540:2026-06-10"),
])

# ── TRADES ───────────────────────────────────────────────────────────────────
# 전체 매수 8건 중:
#   추격매수 3건 (prev_close 대비 +5% 이상): t2, t5, t7
#   물타기 4건 (손실 중 추가매수): t3, t4, t6, t8
#   진입 매수: t1(삼성전자), t_kakao(카카오), t_eco(에코프로비엠)

TRADES = pd.DataFrame([
    # 삼성전자 — 진입 매수
    dict(trade_id="t1", traded_at="2026-08-01", ticker="005930", name="삼성전자",
         side="BUY", quantity=10, price=70_000,
         amount=700_000, fee=None, tax=None, source="demo.csv", source_row=1, note="매수"),
    # 삼성전자 — 추격매수 (2026-08-07: 전일 종가 64,000 대비 +7.8% = 69,000)
    # 단, timeline에서 2026-08-07 이전 행 = 2026-08-01의 close=70,000
    # 69,000 < 70,000이면 추격 아님. 더 설득력 있게 하자.
    # 대신 에코프로비엠 추격 케이스를 쓰자.

    # 에코프로비엠 진입 (2026-06-10 전날 prev_close = 45,000, 매수가 48,600 = +8%)
    # timeline에 6/10 이전 행이 없으므로 skip됨 — 그래서 NAVER 케이스를 쓸 것
    # NAVER — 진입 매수
    dict(trade_id="t_naver1", traded_at="2026-05-01", ticker="035420", name="NAVER",
         side="BUY", quantity=10, price=200_000,
         amount=2_000_000, fee=None, tax=None, source="demo.csv", source_row=2, note="매수"),
    # NAVER — 추격매수 (전날 close 189,000 대비 +8.5% = 205,000)
    dict(trade_id="t_naver2", traded_at="2026-05-10", ticker="035420", name="NAVER",
         side="BUY", quantity=5, price=205_000,
         amount=1_025_000, fee=None, tax=None, source="demo.csv", source_row=3, note="매수"),
    # NAVER — 손실 중 물타기
    dict(trade_id="t_naver3", traded_at="2026-05-20", ticker="035420", name="NAVER",
         side="BUY", quantity=5, price=188_000,
         amount=940_000, fee=None, tax=None, source="demo.csv", source_row=4, note="매수"),
    # NAVER 손절
    dict(trade_id="t_naver_sell", traded_at="2026-06-17", ticker="035420", name="NAVER",
         side="SELL", quantity=20, price=181_000,
         amount=3_620_000, fee=None, tax=None, source="demo.csv", source_row=5, note="매도"),

    # SK하이닉스 진입 후 익절
    dict(trade_id="t_sk1", traded_at="2026-06-01", ticker="000660", name="SK하이닉스",
         side="BUY", quantity=5, price=195_000,
         amount=975_000, fee=None, tax=None, source="demo.csv", source_row=6, note="매수"),
    dict(trade_id="t_sk_sell", traded_at="2026-06-09", ticker="000660", name="SK하이닉스",
         side="SELL", quantity=5, price=279_000,
         amount=1_395_000, fee=None, tax=None, source="demo.csv", source_row=7, note="매도"),

    # 에코프로비엠 진입 후 익절
    dict(trade_id="t_eco1", traded_at="2026-06-10", ticker="247540", name="에코프로비엠",
         side="BUY", quantity=5, price=45_000,
         amount=225_000, fee=None, tax=None, source="demo.csv", source_row=8, note="매수"),
    dict(trade_id="t_eco_sell", traded_at="2026-06-22", ticker="247540", name="에코프로비엠",
         side="SELL", quantity=5, price=54_000,
         amount=270_000, fee=None, tax=None, source="demo.csv", source_row=9, note="매도"),

    # 삼성전자 물타기 (2026-08-07: timeline unrealized=-60,000 → 손실 중)
    dict(trade_id="t3", traded_at="2026-08-07", ticker="005930", name="삼성전자",
         side="BUY", quantity=5, price=63_000,
         amount=315_000, fee=None, tax=None, source="demo.csv", source_row=10, note="매수"),
    # 삼성전자 물타기 (2026-08-14: unrealized=-80,000 → 손실 중)
    dict(trade_id="t4", traded_at="2026-08-14", ticker="005930", name="삼성전자",
         side="BUY", quantity=5, price=62_500,
         amount=312_500, fee=None, tax=None, source="demo.csv", source_row=11, note="매수"),

    # 카카오 진입
    dict(trade_id="t_kakao1", traded_at="2026-07-15", ticker="035720", name="카카오",
         side="BUY", quantity=20, price=38_000,
         amount=760_000, fee=None, tax=None, source="demo.csv", source_row=12, note="매수"),
    # 카카오 물타기 (2026-07-22: unrealized=-51,000 → 손실 중)
    dict(trade_id="t_kakao2", traded_at="2026-07-22", ticker="035720", name="카카오",
         side="BUY", quantity=10, price=35_500,
         amount=355_000, fee=None, tax=None, source="demo.csv", source_row=13, note="매수"),
    # 카카오 추격매수 (2026-07-22 전날 close=38,000 → 위에서 35,500으로 샀으니 추격 아님)
    # NAVER 추격이 제대로 동작하는지 확인 필요
])

# NAVER timeline — 추격매수 판정에 필요
NAVER_TIMELINE = pd.DataFrame([
    dict(date="2026-05-01", ticker="035420", name="NAVER",
         quantity=10, avg_cost=200_000, close=200_000,
         unrealized_pnl=0, unrealized_pct=0.0, realized_pnl=0,
         holding_days=1, episode_id="035420:2026-05-01"),
    # 2026-05-09: close=189,000 (다음날 t_naver2 가 205,000에 매수 → +8.5% 추격)
    dict(date="2026-05-09", ticker="035420", name="NAVER",
         quantity=10, avg_cost=200_000, close=189_000,
         unrealized_pnl=-110_000, unrealized_pct=-0.055, realized_pnl=0,
         holding_days=9, episode_id="035420:2026-05-01"),
    # 2026-05-10: 추격매수 당일 close
    dict(date="2026-05-10", ticker="035420", name="NAVER",
         quantity=15, avg_cost=198_000, close=200_000,
         unrealized_pnl=30_000, unrealized_pct=0.015, realized_pnl=0,
         holding_days=10, episode_id="035420:2026-05-01"),
    # 2026-05-19: 다시 하락
    dict(date="2026-05-19", ticker="035420", name="NAVER",
         quantity=15, avg_cost=198_000, close=183_000,
         unrealized_pnl=-225_000, unrealized_pct=-0.076, realized_pnl=0,
         holding_days=19, episode_id="035420:2026-05-01"),
    # 2026-05-20: 물타기 당일 (손실 중)
    dict(date="2026-05-20", ticker="035420", name="NAVER",
         quantity=20, avg_cost=195_000, close=181_000,
         unrealized_pnl=-280_000, unrealized_pct=-0.072, realized_pnl=0,
         holding_days=20, episode_id="035420:2026-05-01"),
])

# NAVER episode 따로
NAVER_EPISODE = pd.DataFrame([
    dict(episode_id="035420:2026-05-01", ticker="035420", name="NAVER",
         opened_at="2026-05-01", closed_at="2026-06-17",
         realized_pnl=-380_000, max_unrealized_loss=-450_000, max_unrealized_loss_pct=-0.12,
         add_buy_count=2, holding_days=47, is_open=False),
])

FULL_TIMELINE = pd.concat([TIMELINE, NAVER_TIMELINE], ignore_index=True)
FULL_EPISODES = pd.concat([
    EPISODES[EPISODES["ticker"] != "035420"],
    NAVER_EPISODE,
], ignore_index=True)

# ── 지표 계산 ─────────────────────────────────────────────────────────────────

disp_result = disposition.compute(FULL_TIMELINE, TRADES, FULL_EPISODES)
avg_result = averaging_down.compute(FULL_TIMELINE, TRADES, FULL_EPISODES)
chase_result = chasing.compute(FULL_TIMELINE, TRADES, FULL_EPISODES)

metric_results = [disp_result, avg_result, chase_result]

# ── 브레이크 룰 (데모 주문: 삼성전자 BUY @64,050 — +5% 이상, 현재 손실 중) ──
# prev_close(2026-08-28) = 61,000 → +5% = 64,050

DEMO_ORDER = ProposedOrder(
    ticker="005930",
    name="삼성전자",
    side="BUY",
    quantity=5,
    price=64_050,  # 61,000 × 1.05 = 64,050
)

intervention = rules_engine.evaluate(DEMO_ORDER, metric_results, FULL_TIMELINE, FULL_EPISODES)

# ── LLM 가드레일 ──────────────────────────────────────────────────────────────

all_evidence = []
for c in intervention.contributions:
    if c.triggered:
        all_evidence.extend(c.evidence)

triggered_keys = [c.key for c in intervention.contributions if c.triggered]

coaching = generate(
    context="order_intervention",
    evidence=all_evidence,
    triggered_keys=triggered_keys,
)

# ── TypeScript 타입으로 변환 ──────────────────────────────────────────────────

KEY_MAP = {
    "disposition_effect": "disposition",
    "averaging_down": "averaging_down",
    "chasing": "chasing",
}
NAME_MAP = {
    "disposition_effect": "처분효과",
    "averaging_down": "물타기 지수",
    "chasing": "추격매수 계수",
}
LABEL_MAP = {
    "chasing": "추격매수",
    "averaging_down": "물타기",
    "disposition_effect": "처분효과",
}

def make_summary(r):
    if r.key == "disposition_effect":
        return f"이익 종목은 평균 10일 만에 팔고, 손실 종목은 평균 47일을 버텼습니다."
    if r.key == "averaging_down":
        return f"손실 구간 추가매수가 전체 매수의 {round(r.raw * 100)}%를 차지합니다."
    return f"전일 대비 +5% 이상 급등 후 매수한 사례가 {len(r.evidence)}건입니다."

overall = round((disp_result.score_0_100 + avg_result.score_0_100 + chase_result.score_0_100) / 3)
overall_grade = "위험" if overall >= 65 else "주의" if overall >= 40 else "안정"

diagnosis = {
    "periodLabel": "2026.05 ~ 2026.08 (데모 데이터)",
    "totalTrades": len(TRADES[TRADES["side"] == "BUY"]),
    "overallScore": overall,
    "overallGrade": overall_grade,
    "generatedAt": "2026-08-29T10:00:00+09:00",
    "metrics": [
        {
            "key": KEY_MAP[r.key],
            "name": NAME_MAP[r.key],
            "score": round(r.score_0_100),
            "percentile": max(1, 100 - round(r.score_0_100)),
            "sampleCount": len(r.evidence),
            "delta": None,
            "summary": make_summary(r),
        }
        for r in metric_results
    ],
}

risk_level = "HIGH" if intervention.risk_score >= 70 else "MEDIUM" if intervention.risk_score >= 40 else "LOW"

intervention_ts = {
    "order": {
        "ticker": DEMO_ORDER.ticker,
        "name": DEMO_ORDER.name,
        "side": DEMO_ORDER.side,
        "quantity": DEMO_ORDER.quantity,
        "price": DEMO_ORDER.price,
        "changeRate": round((DEMO_ORDER.price / 61_000 - 1) * 100, 1),
    },
    "riskScore": round(intervention.risk_score),
    "riskLevel": risk_level,
    "baseScore": 0,
    "contributions": [
        {
            "label": LABEL_MAP[c.key],
            "value": round(c.score, 1),
            "detail": c.evidence[0]["detail"] if c.evidence else "",
        }
        for c in intervention.contributions
        if c.triggered
    ],
    "warning": {
        "headline": coaching.headline,
        "caseCount": len(all_evidence),
        "averageReturn": -18,
        "description": coaching.body,
    },
    "suggestions": [
        "장 마감 후 종가로 재검토하기",
        "주문 수량을 절반(2~3주)으로 나누기",
        "24시간 쿨다운 후 알림 받기",
    ],
}

# ── 결과 출력 ──────────────────────────────────────────────────────────────────

print("=== DIAGNOSIS ===")
print(json.dumps(diagnosis, ensure_ascii=False, indent=2))
print("\n=== INTERVENTION ===")
print(json.dumps(intervention_ts, ensure_ascii=False, indent=2))
print("\n=== 요약 ===")
print(f"처분효과:  raw={disp_result.raw:.3f}, score={disp_result.score_0_100:.1f}")
print(f"물타기:    raw={avg_result.raw:.3f}, score={avg_result.score_0_100:.1f}")
print(f"추격매수:  raw={chase_result.raw:.3f}, score={chase_result.score_0_100:.1f}")
print(f"위험점수:  {intervention.risk_score:.1f} ({risk_level}), 개입={intervention.should_intervene}")
print(f"코칭 from_llm={coaching.from_llm}: {coaching.headline}")
