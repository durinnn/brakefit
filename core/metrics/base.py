"""지표 모듈 공통 반환 타입.

docs/schema.md §4 의 코드 표현. C 가 확립하고 B 가 ②③(물타기·추격매수)에서
이 형태를 그대로 복제한다. 컬럼/필드를 바꾸려면 문서부터 PR.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MetricResult:
    """편향 지표 하나의 계산 결과.

    evidence 안의 숫자만 LLM 가드레일이 코칭 문구에 쓸 수 있다 (가드레일 화이트리스트).
    """

    key: str              # "disposition_effect" | "averaging_down" | "chasing"
    raw: float             # 원래 스케일의 값 (예: DE = PGR - PLR)
    score_0_100: float      # 정규화 점수. 높을수록 편향이 강함
    evidence: list[dict] = field(default_factory=list)
