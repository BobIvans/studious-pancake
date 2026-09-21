#!/usr/bin/env python3
"""Verify current-head MEGA8 dependency reconciliation and stale-evidence retirement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.release_gate.mega8_dependency_closure import verify_current_manifests

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "release_artifacts" / "mega8" / "dependency_reconciliation.json"


def verify() -> dict[str, object]:
    return verify_current_manifests(ROOT, RECEIPT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("MEGA8 dependency closure:", "PASS" if result["accepted"] else "FAIL")
        for error in result["errors"]:
            print(f"- {error}")
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
