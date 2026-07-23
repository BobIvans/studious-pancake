#!/usr/bin/env python3
"""Focused MEGA-PR-01 offline verifier.

The verifier intentionally runs only compile and focused unit probes. It does not
contact providers, build transactions, access private keys, sign or submit.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = [
    [
        sys.executable,
        "-m",
        "py_compile",
        "src/mega_pr01_canonical_runtime_paper_core.py",
        "tests/test_mega_pr01_canonical_runtime_paper_core.py",
    ],
    [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_mega_pr01_canonical_runtime_paper_core.py",
    ],
]


def main() -> int:
    for command in COMMANDS:
        print(f"$ {' '.join(command)}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode
    print("MEGA-PR-01 canonical runtime paper core verifier passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
