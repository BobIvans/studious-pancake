#!/usr/bin/env python3
"""Independent-process deterministic replay gate for PR-358."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = (
    "import json;"
    "from src.research.pr358_integrated import run_pr358_integrated_vertical;"
    "r=run_pr358_integrated_vertical();"
    "print(json.dumps({'hash':r['integrated_receipt_hash'],"
    "'execution_right':r['execution_right'],"
    "'customer_billing':r['customer_billing']},sort_keys=True))"
)


def _run_once() -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-c", SNIPPET],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout.strip())


def main() -> int:
    first = _run_once()
    second = _run_once()
    if first != second:
        print(json.dumps({"accepted": False, "first": first, "second": second}))
        return 1
    if (
        first.get("execution_right") is not False
        or first.get("customer_billing") is not False
    ):
        print(json.dumps({"accepted": False, "reason": "forbidden_effect"}))
        return 1
    print(json.dumps({"accepted": True, **first}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
