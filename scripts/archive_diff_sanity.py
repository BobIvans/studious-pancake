#!/usr/bin/env python3
"""Compare repository ZIP archives and fail identical uploads when required."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.readiness.debt_closure_map import compare_archives  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two ZIP archives by file manifest and SHA-256 hashes."
    )
    parser.add_argument("--previous", required=True, help="older ZIP archive path")
    parser.add_argument("--current", required=True, help="newer ZIP archive path")
    parser.add_argument(
        "--require-change",
        action="store_true",
        help="exit non-zero when the archives are byte-for-byte equivalent",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    report = compare_archives(args.previous, args.current)
    payload = report.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"archive_diff_identical={str(report.identical).lower()}")
        print(f"archive_diff_has_changes={str(report.has_changes).lower()}")
        print(f"added={len(report.added)}")
        print(f"removed={len(report.removed)}")
        print(f"changed={len(report.changed)}")
    if args.require_change and report.identical:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
