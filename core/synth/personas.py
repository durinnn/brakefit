"""합성 페르소나 정의 — 편향 강도 파라미터 세트.

BiasKey 는 core/metrics 세 지표(disposition_effect/averaging_down/chasing)와
web(lovulive)/src/lib/types.ts 의 BiasKey 리터럴에 대응한다. 이름을 맞춰둬야
나중에 API 계약에서 헤맬 일이 없다.

아래 bias 값들은 임의로 고른 게 아니라 core/synth/generator.py 의 Monte Carlo
검증(페르소나별 300 trial × 40 episode)으로 확인된 조합이다 — "순수형" 페르소나는
자기 축만 강하고 나머지 둘은 대조군과 같은 수준이어야, 자기 지표만 올리고 남의
지표는 거의 안 건드리는 게 확인된다. 값을 바꾸면 재검증 필요(generator.py 모듈
docstring 참조).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    description: str
    disposition_bias: float  # 0~1. 처분효과 강도 — 손실 중 매도 회피 정도
    averaging_down_bias: float  # 0~1. 물타기 강도 — 손실 -5% 이하에서 추가매수 확률
    chasing_bias: float  # 0~1. 추격매수 강도 — 급등 직후 진입/추가매수 선호도
    n_episodes: int = 40
    seed: int = 0
    budget: float = 1_000_000  # 진입 1회 예산(원). 추가매수는 이 절반.
    max_add_buys: int = 5  # episode 당 추가매수 상한 — 장기 하락장에서 무한 물타기 방지


RATIONAL_BASELINE = Persona(
    key="rational_baseline",
    name="차분형(대조군)",
    description="세 편향 모두 약하다 — 점수·백분위 비교 기준선.",
    disposition_bias=0.10,
    averaging_down_bias=0.10,
    chasing_bias=0.10,
    seed=1000,
)

DISPOSITION_PRONE = Persona(
    key="disposition_prone",
    name="처분효과형",
    description="이익은 조금만 나도 바로 팔고, 손실은 원금 회복까지 붙들고 버틴다.",
    disposition_bias=0.85,
    averaging_down_bias=0.10,
    chasing_bias=0.10,
    seed=1001,
)

AVERAGING_DOWN_PRONE = Persona(
    key="averaging_down_prone",
    name="물타기형",
    description="손실이 커질수록 평단을 낮추겠다며 추가매수를 반복한다.",
    disposition_bias=0.10,
    averaging_down_bias=0.85,
    chasing_bias=0.10,
    seed=1002,
)

CHASING_PRONE = Persona(
    key="chasing_prone",
    name="추격매수형",
    description="이미 오른 종목에 뒤늦게 올라탄다.",
    disposition_bias=0.10,
    averaging_down_bias=0.10,
    chasing_bias=0.85,
    seed=1003,
)

MIXED_REALISTIC = Persona(
    key="mixed_realistic",
    name="복합형",
    description="세 편향이 중간 강도로 섞인 '평범한' 사용자 — 데모 기본값.",
    disposition_bias=0.55,
    averaging_down_bias=0.55,
    chasing_bias=0.55,
    seed=1004,
)

#: 실사용자 분포가 아니다 — AGENTS.md 규칙 6, 이 데이터를 쓰는 리포트에 각주로 노출할 것.
NOT_REAL_USER_DISCLAIMER = "실사용자 분포 아님 — 합성 페르소나로 생성된 데모용 데이터입니다."

PRESETS: dict[str, Persona] = {
    p.key: p
    for p in [
        RATIONAL_BASELINE,
        DISPOSITION_PRONE,
        AVERAGING_DOWN_PRONE,
        CHASING_PRONE,
        MIXED_REALISTIC,
    ]
}
