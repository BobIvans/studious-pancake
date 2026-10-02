#!/usr/bin/env python3
"""Run one typed OCC qualify_and_report request against current studious-pancake."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.occ_memory_qualification_bridge import execute_request, read_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--operator-profile", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = execute_request(
            read_json(args.request),
            read_json(args.operator_profile),
            adapter_root=ROOT,
        )
    except (OSError, ValueError, KeyError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "ERROR", "reason": reason}, sort_keys=True))
        return 2

    receipt = result["receipt"]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["domain_verdict"] == "PAPER_PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
