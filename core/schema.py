"""표준 거래내역 스키마 — 모든 파서의 출력 형태.

이 파일이 파이프라인의 첫 번째 데이터 계약이다.
증권사가 몇 곳이든, 화면이 몇 개든, 파서는 전부 이 표를 뱉는다.
엔진(A) 이후는 원본 포맷을 전혀 모른다.

※ docs/schema.md 가 정본이고 이 파일은 그것의 코드 표현이다.
   컬럼을 바꾸려면 문서부터 PR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pandas as pd

Side = Literal["BUY", "SELL"]

#: 표준 거래내역 컬럼 (순서 고정 — 하위 모듈이 위치로 참조해도 되게)
TRADE_COLUMNS: list[str] = [
    "trade_id",    # str   행 고유 ID. "{source}:{sheet}:{row}" 형태
    "traded_at",   # date  체결일 (시각 정보가 있으면 traded_time 에 별도 보관)
    "ticker",      # str   종목코드 6자리. 화면에 없으면 None → resolve_tickers() 로 채움
    "name",        # str   종목명 (원본 표기 그대로)
    "side",        # str   "BUY" | "SELL"
    "quantity",    # int   체결수량 (항상 양수)
    "price",       # float 체결단가
    "amount",      # float 정산금액. 매수=출금액, 매도=입금액
    "fee",         # float 수수료. 화면에 없으면 None (0 으로 채우지 말 것 — 아래 주의 참조)
    "tax",         # float 제세금. 위와 동일
    "source",      # str   어느 파일/화면에서 왔는지
    "source_row",  # int   원본 행 번호 (역추적용)
    "note",        # str   원본 '내용' 텍스트 등 판정 근거
]

#: fee/tax 가 None 인 것과 0 인 것은 의미가 다르다.
#: None = "이 화면은 수수료를 안 알려준다" → 실현손익이 gross 라는 뜻
#: 0    = "수수료가 실제로 0원이었다"
#: 이 구분을 뭉개면 지표·백테스트 수치가 전부 흔들린다. docs/schema.md §수수료 참조.

NUMERIC_COLUMNS = ("quantity", "price", "amount", "fee", "tax")


@dataclass
class SkippedRow:
    """파서가 버린 행과 그 이유. 검증 리포트에 그대로 실린다."""

    row: int
    reason: str
    preview: str = ""


@dataclass
class ParseResult:
    """파서의 표준 반환값 — 데이터 + 무슨 일이 있었는지."""

    trades: pd.DataFrame
    skipped: list[SkippedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    # ── 리포트 ──────────────────────────────────────────────────────────
    @property
    def period(self) -> tuple[date, date] | None:
        if self.trades.empty:
            return None
        col = self.trades["traded_at"]
        return col.min(), col.max()

    def report(self) -> str:
        """사람이 읽는 검증 리포트. 파서를 돌릴 때마다 이걸 찍어보고 눈으로 확인한다."""
        lines = [
            f"파일        : {self.source}",
            f"거래 건수   : {len(self.trades)}건",
        ]
        if (p := self.period) is not None:
            lines.append(f"기간        : {p[0]} ~ {p[1]}")
        if not self.trades.empty:
            lines.append(f"종목 수     : {self.trades['name'].nunique()}개")
            counts = self.trades["side"].value_counts().to_dict()
            lines.append(f"매수/매도   : {counts.get('BUY', 0)} / {counts.get('SELL', 0)}")
            missing = int(self.trades["ticker"].isna().sum())
            if missing:
                lines.append(f"종목코드 미해결: {missing}건  ← resolve_tickers() 필요")

        lines.append(f"스킵된 행   : {len(self.skipped)}개")
        for s in self.skipped[:20]:
            lines.append(f"  [{s.row:>4}] {s.reason}" + (f"  · {s.preview}" if s.preview else ""))
        if len(self.skipped) > 20:
            lines.append(f"  ... 외 {len(self.skipped) - 20}개")

        if self.warnings:
            lines.append("경고        :")
            lines.extend(f"  ! {w}" for w in self.warnings)
        return "\n".join(lines)


def empty_trades() -> pd.DataFrame:
    """빈 표준 거래내역 (컬럼과 dtype 은 갖춘 상태)."""
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in TRADE_COLUMNS})
    return coerce(df)


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼 순서·dtype 을 표준에 맞춘다."""
    for col in TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[TRADE_COLUMNS].copy()
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["quantity"] = df["quantity"].astype("Int64")
    df["source_row"] = pd.to_numeric(df["source_row"], errors="coerce").astype("Int64")
    return df.reset_index(drop=True)


def validate(df: pd.DataFrame) -> list[str]:
    """표준 거래내역이 말이 되는지 검사. 문제 목록을 돌려준다 (빈 리스트면 통과).

    엔진(A)에 넘기기 직전에 반드시 통과시킬 것.
    """
    problems: list[str] = []

    missing = [c for c in TRADE_COLUMNS if c not in df.columns]
    if missing:
        return [f"컬럼 누락: {missing}"]
    if df.empty:
        return problems

    if (bad := df.loc[~df["side"].isin(("BUY", "SELL"))]).shape[0]:
        problems.append(f"side 값이 BUY/SELL 이 아닌 행 {len(bad)}개: {bad.index.tolist()[:5]}")
    if (bad := df.loc[df["quantity"].isna() | (df["quantity"] <= 0)]).shape[0]:
        problems.append(f"수량이 0 이하이거나 비어있는 행 {len(bad)}개: {bad.index.tolist()[:5]}")
    if (bad := df.loc[df["price"].isna() | (df["price"] <= 0)]).shape[0]:
        problems.append(f"단가가 0 이하이거나 비어있는 행 {len(bad)}개: {bad.index.tolist()[:5]}")
    if df["trade_id"].duplicated().any():
        dupes = df.loc[df["trade_id"].duplicated(), "trade_id"].tolist()[:5]
        problems.append(f"trade_id 중복: {dupes}")
    if df["traded_at"].isna().any():
        problems.append(f"체결일이 비어있는 행 {int(df['traded_at'].isna().sum())}개")

    # 단가×수량 과 정산금액의 정합성 — 수수료/세금이 어디에 반영됐는지 알려주는 신호
    known = df.dropna(subset=["amount", "price", "quantity"])
    if not known.empty:
        gross = known["price"] * known["quantity"]
        gap = (known["amount"] - gross).abs()
        off = known.loc[gap > gross.abs() * 0.005 + 1]
        if len(off):
            problems.append(
                f"단가×수량 과 정산금액이 0.5% 넘게 어긋나는 행 {len(off)}개 — "
                "정산금액에 수수료·세금이 이미 반영된 화면일 수 있음 (docs/schema.md §수수료 확인)"
            )
    return problems
