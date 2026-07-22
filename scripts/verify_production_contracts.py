#!/usr/bin/env python3
"""Offline verification of external API pins and consolidated production debt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.external_contracts.production_compatibility import (
    evaluate_production_compatibility,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config/production_debt_pr149.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    report = evaluate_production_compatibility(ROOT, args.manifest)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
