#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_STEPS = [
    "temp_write",
    "file_fsync",
    "atomic_rename",
    "dir_fsync",
    "publish_generation_pointer",
]


def build_report(report_path: Path | None) -> dict[str, object]:
    return {
        "accepted": False,
        "report_path": str(report_path) if report_path else None,
        "required_steps": REQUIRED_STEPS,
        "message": "Scaffold verifier added in MPR-CLOSE-04 start branch; backup/restore evidence still needs implementation.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify backup/restore evidence scaffold.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = build_report(args.report)
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
