#!/usr/bin/env python3
"""Independent-process deterministic replication gate for PR-356."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from src.research.pr356_integrated_loop import run_integrated_science_fixture


def emit() -> int:
    payload = run_integrated_science_fixture()
    print(payload["integrated_receipt_hash"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    if args.emit:
        return emit()

    command = [sys.executable, __file__, "--emit"]
    first = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    second = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    payload = {
        "accepted": bool(first) and first == second,
        "first_receipt_hash": first,
        "second_receipt_hash": second,
        "independent_processes": 2,
        "execution_right": False,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
