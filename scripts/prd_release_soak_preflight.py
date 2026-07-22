#!/usr/bin/env python3
"""Print the MEGA-PR D fail-closed preflight report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.release_soak_canary_prd import (
    default_blocked_preflight,
    report_from_json,
    report_to_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)
    if args.report_json:
        payload = json.loads(args.report_json.read_text(encoding="utf-8"))
        report = report_from_json(payload)
    else:
        report = default_blocked_preflight()
    print(report_to_json(report))
    return 0 if report.review_ready and not report.live_enabled else 1


if __name__ == "__main__":
    raise SystemExit(main())
