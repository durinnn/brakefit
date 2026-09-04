"""api/ 스모크 테스트 — 실제 HTTP 요청으로 엔드포인트가 진짜 응답하는지 확인.

DEMO_AS_OF 가 캐시 범위 안이라 네트워크 없이 재현된다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_헬스체크():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_페르소나_목록():
    r = client.get("/api/personas")
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()}
    assert keys == {
        "rational_baseline",
        "disposition_prone",
        "averaging_down_prone",
        "chasing_prone",
        "mixed_realistic",
    }


def test_진단_엔드포인트는_camelCase_필드로_응답한다():
    r = client.get("/api/diagnose", params={"persona": "disposition_prone"})
    assert r.status_code == 200
    body = r.json()

    assert set(body.keys()) == {
        "periodLabel",
        "totalTrades",
        "overallScore",
        "overallGrade",
        "metrics",
        "generatedAt",
        "headline",
        "body",
    }
    assert body["overallGrade"] in ("안정", "주의", "위험")
    assert {m["key"] for m in body["metrics"]} == {"disposition", "averaging_down", "chasing"}
    for m in body["metrics"]:
        assert 0.0 <= m["score"] <= 100.0
        assert 0.0 <= m["percentile"] <= 100.0
    # ANTHROPIC_API_KEY 없는 테스트 환경이므로 core/guard 폴백 템플릿 그대로 나와야 함
    assert body["headline"]
    assert body["body"]


def test_모르는_페르소나는_404():
    r = client.get("/api/diagnose", params={"persona": "does_not_exist"})
    assert r.status_code == 404


def test_개입_엔드포인트():
    r = client.post(
        "/api/simulate-order",
        params={"persona": "averaging_down_prone"},
        json={"ticker": "005930", "name": "삼성전자", "side": "BUY", "quantity": 5, "price": 70000},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "order",
        "riskScore",
        "riskLevel",
        "baseScore",
        "contributions",
        "warning",
        "suggestions",
    }
    assert body["riskLevel"] in ("LOW", "MEDIUM", "HIGH")
    assert len(body["contributions"]) == 3
    assert len(body["suggestions"]) >= 1
    assert set(body["warning"].keys()) == {"headline", "caseCount", "averageReturn", "description"}
    assert isinstance(body["warning"]["averageReturn"], float)
    # 사례가 없으면(caseCount=0) 평균도 0 — 그 외엔 core/metrics 의 return_pct 평균이라
    # 어느 룰이 dominant 인지에 따라 부호가 갈리므로 여기서는 존재 여부만 확인한다
    if body["warning"]["caseCount"] == 0:
        assert body["warning"]["averageReturn"] == 0.0


def test_백테스트_엔드포인트():
    r = client.get("/api/backtest", params={"persona": "chasing_prone"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "periodLabel",
        "interventionCount",
        "avoidedLoss",
        "missedGain",
        "netBenefit",
        "netBenefitRate",
        "hitRate",
        "cases",
    }
    for case in body["cases"]:
        assert case["biasKey"] in ("averaging_down", "chasing")


@pytest.mark.parametrize("persona", ["rational_baseline", "mixed_realistic"])
def test_세_엔드포인트_전부_같은_페르소나로_에러없이_돈다(persona):
    assert client.get("/api/diagnose", params={"persona": persona}).status_code == 200
    assert client.get("/api/backtest", params={"persona": persona}).status_code == 200
    r = client.post(
        "/api/simulate-order",
        params={"persona": persona},
        json={
            "ticker": "000660",
            "name": "SK하이닉스",
            "side": "BUY",
            "quantity": 1,
            "price": 200000,
        },
    )
    assert r.status_code == 200
