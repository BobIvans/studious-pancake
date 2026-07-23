#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_04_runtime import scan_persistence_authority


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MPR-CLOSE-04 persistence authority")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = scan_persistence_authority(ROOT)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"approved_factory_only={report['approved_factory_only']}")
        print(f"unauthorized_runtime_sites={len(report['unauthorized_runtime_sites'])}")
    return 1 if args.strict and report["unauthorized_runtime_sites"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
