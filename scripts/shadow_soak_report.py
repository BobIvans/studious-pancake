#!/usr/bin/env python3
"""Build a deterministic PR-039 shadow-soak promotion evidence bundle."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evidence.shadow_soak import ShadowSoakAnalyzer, ShadowSoakThresholds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an offline PR-039 shadow-soak evidence bundle."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", help="path to a PR-013 shadow_outcomes SQLite DB")
    source.add_argument("--jsonl", help="path to an offline shadow outcome JSONL corpus")
    parser.add_argument("--corpus-id", default=None, help="optional stable corpus label")
    parser.add_argument("--min-samples", type=int, default=1)
    parser.add_argument("--min-duration-seconds", type=int, default=72 * 60 * 60)
    parser.add_argument("--max-false-positive-rate-bps", type=int, default=0)
    parser.add_argument("--output", default=None, help="write JSON bundle to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    thresholds = ShadowSoakThresholds(
        minimum_samples=args.min_samples,
        minimum_duration_seconds=args.min_duration_seconds,
        maximum_false_positive_rate_bps=args.max_false_positive_rate_bps,
    )
    if args.sqlite:
        analyzer = ShadowSoakAnalyzer.from_shadow_sqlite(
            args.sqlite,
            thresholds=thresholds,
            corpus_id=args.corpus_id,
        )
    else:
        analyzer = ShadowSoakAnalyzer.from_jsonl(
            args.jsonl,
            thresholds=thresholds,
            corpus_id=args.corpus_id,
        )
    bundle = analyzer.build_bundle()
    payload = bundle.to_json()
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0 if bundle.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
