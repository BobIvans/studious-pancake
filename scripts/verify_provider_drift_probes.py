#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_03_verifiers import emit_report, verify_provider_drift_probes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--offline-fixtures", action="store_true")
    args = parser.parse_args(argv)

    report = verify_provider_drift_probes()
    payload = report.to_dict()
    payload["facts"]["offline_fixtures_mode"] = bool(args.offline_fixtures)
    if args.as_json:
        import json
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(emit_report(report, as_json=False))
        print(f"offline_fixtures_mode={bool(args.offline_fixtures)}")
    if args.strict and not report.ok:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
