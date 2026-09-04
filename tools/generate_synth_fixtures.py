"""fixtures/synth/*.csv 를 생성한다 — core/synth 페르소나 5종의 합성 거래내역.

A(엔진)·C(지표)·D(백테스트)가 core/synth 를 직접 안 돌려도 바로 개발에 쓸 수 있게
CSV 로 미리 구워둔다. 유니버스나 기간을 바꾸면 이 스크립트를 다시 돌려서 갱신할 것
(생성 로직은 core/synth 소유 — 이 스크립트는 그걸 호출해서 파일로 떨어뜨리기만 한다).

처음 실행하면 pykrx 로 실제 종가를 받아 data/cache/prices/ 에 캐싱한다(그 캐시는
커밋 대상 — .gitignore 참조, 데모 당일 KRX 장애 대비). 캐시가 있으면 네트워크 없이도
재실행된다.

사용:
    uv run python tools/generate_synth_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

from core import schema
from core.synth.generator import generate_all_presets
from core.synth.personas import NOT_REAL_USER_DISCLAIMER

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "synth"


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    presets = generate_all_presets()

    for key, df in presets.items():
        problems = schema.validate(df)
        if problems:
            raise SystemExit(f"{key}: schema.validate() 실패 — {problems}")

        path = FIXTURES_DIR / f"{key}.csv"
        df.to_csv(path, index=False)
        period = f"{df['traded_at'].min()} ~ {df['traded_at'].max()}" if len(df) else "-"
        print(f"{key:24s} {len(df):4d}건  {period}  -> {path.relative_to(FIXTURES_DIR.parents[1])}")

    print(f"\n⚠ {NOT_REAL_USER_DISCLAIMER}")


if __name__ == "__main__":
    main()
