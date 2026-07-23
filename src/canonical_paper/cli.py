"""CLI boundary for the canonical MEGA-PR-01 sender-free paper platform."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .model import PaperOutcome, PaperPlatformError, RecordingError
from .platform import CanonicalPaperConfig, CanonicalPaperPlatform
from .source import digest_config_file

EXIT_CONFIGURATION_ERROR = 2
EXIT_PAPER_BLOCKED = 5
EXIT_PAPER_FAILED = 6


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashloan-bot run --mode paper",
        description="Run one bounded canonical sender-free recorded paper cycle.",
    )
    parser.add_argument("--config-file", default=None)
    parser.add_argument("--db-path", default=".runtime/canonical-paper.sqlite3")
    parser.add_argument("--recording", default=None)
    parser.add_argument("--min-profit-lamports", type=int, default=10_000)
    parser.add_argument("--max-slot-skew", type=int, default=8)
    parser.add_argument("--max-bytes", type=int, default=256 * 1024)
    parser.add_argument("--max-items", type=int, default=64)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        config_path = Path(args.config_file) if args.config_file else None
        config = CanonicalPaperConfig(
            db_path=Path(args.db_path),
            recording_path=Path(args.recording) if args.recording else None,
            config_digest=digest_config_file(config_path),
            min_profit_lamports=args.min_profit_lamports,
            max_slot_skew=args.max_slot_skew,
            max_bytes=args.max_bytes,
            max_items=args.max_items,
        )
        report = CanonicalPaperPlatform(config).run_once()
        payload = report.to_dict()
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                "CANONICAL_PAPER_CYCLE: "
                f"outcome={payload['outcome']} "
                f"reason={payload['reason_code']} "
                f"accepted={payload['accepted_count']} "
                f"rejected={payload['rejected_count']} "
                f"cycle={payload['cycle_id']} "
                "live=false signer=false sender=false"
            )
        return 0 if report.outcome is not PaperOutcome.BLOCKED else EXIT_PAPER_BLOCKED
    except (ValueError, RecordingError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "mega-pr-01.canonical-paper-cli-error.v1",
                    "status": "CONFIGURATION_ERROR",
                    "reason_code": getattr(exc, "reason_code", "invalid_configuration"),
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return EXIT_CONFIGURATION_ERROR
    except PaperPlatformError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "mega-pr-01.canonical-paper-cli-error.v1",
                    "status": "BLOCKED",
                    "reason_code": exc.reason_code,
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return EXIT_PAPER_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
