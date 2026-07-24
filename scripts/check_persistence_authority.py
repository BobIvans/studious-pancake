#!/usr/bin/env python3
"""Check MPR-NEXT-12 direct DB-connect policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.persistence_authority_mpr_next_12 import evaluate_persistence_authority


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="return non-zero when unapproved active direct DB connects remain",
    )
    args = parser.parse_args(argv)

    report = evaluate_persistence_authority(root=args.root)
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"accepted={report.accepted}")
        print(f"total_occurrences={report.total_occurrences}")
        print(f"unapproved_occurrences={report.unapproved_occurrences}")
        for blocker in report.blockers:
            print(f"BLOCKER: {blocker}")
    if args.require_clean and not report.accepted:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
