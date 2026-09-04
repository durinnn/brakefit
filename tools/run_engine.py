"""core/engine 를 실제로 돌려보는 CLI — A/팀이 손으로 확인할 때 쓴다.

사용법:
    python tools/run_engine.py --csv fixtures/synth/disposition_prone.csv
    python tools/run_engine.py --persona disposition_prone   # core/synth 를 그 자리에서 생성해 실행
    python tools/run_engine.py --csv <파일> --out-dir out/   # timeline.csv / episodes.csv 로 저장

--csv 는 core/schema.TRADE_COLUMNS 형태(파서·synth 공통 출력)의 CSV 여야 한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from core import schema
from core.engine.engine import build


def _load_from_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["traded_at"])
    df["traded_at"] = df["traded_at"].dt.date
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)  # 앞자리 0 유실 방지
    return schema.coerce(df)


def _load_from_persona(key: str) -> pd.DataFrame:
    from core.synth.generator import generate_trades
    from core.synth.personas import PRESETS

    if key not in PRESETS:
        raise SystemExit(f"모르는 페르소나: {key} (사용 가능: {', '.join(PRESETS)})")
    return generate_trades(PRESETS[key])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="TRADE_COLUMNS 형태 CSV 경로")
    parser.add_argument("--persona", help="core/synth 페르소나 키 (예: disposition_prone)")
    parser.add_argument("--out-dir", type=Path, help="timeline.csv/episodes.csv 저장 위치")
    args = parser.parse_args()

    if bool(args.csv) == bool(args.persona):
        parser.error("--csv 또는 --persona 중 하나만 지정할 것")

    trades = _load_from_csv(args.csv) if args.csv else _load_from_persona(args.persona)

    problems = schema.validate(trades)
    if problems:
        print("trades 가 schema.validate() 를 통과 못 함:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)

    result = build(trades)
    print(result.report())

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        result.timeline.to_csv(args.out_dir / "timeline.csv", index=False)
        result.episodes.to_csv(args.out_dir / "episodes.csv", index=False)
        print(f"\n-> {args.out_dir}/timeline.csv, episodes.csv 저장됨")


if __name__ == "__main__":
    main()
