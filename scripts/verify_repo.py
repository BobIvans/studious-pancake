#!/usr/bin/env python3
"""Deterministic offline repository baseline verifier."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_ENV = {
    "PAPER_TRADING_ONLY": "true",
    "LIVE_TRADING_ENABLED": "false",
    "JITO_ENABLED": "false",
    "KAMINO_LIQUIDATION_ENABLED": "false",
}

COMMANDS = [
    [sys.executable, "-m", "pip", "check"],
    [sys.executable, "-m", "compileall", "-q", "arb_bot.py", "src", "scripts", "tests"],
    [sys.executable, "-m", "pytest", "tests/test_import_smoke.py", "-q", "--disable-socket", "--allow-unix-socket"],
    [sys.executable, "-m", "pytest", "-m", "not live and not manual", "--disable-socket", "--allow-unix-socket", "-q"],
]


def run(command: list[str]) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}", flush=True)
    env = os.environ.copy()
    env.update(SAFE_ENV)
    completed = subprocess.run(command, cwd=ROOT, env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    for command in COMMANDS:
        run(command)
    print("\nRepository baseline checks passed. Live trading readiness was not evaluated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
