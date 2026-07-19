#!/usr/bin/env python3
"""Single local equivalent of the mandatory GitHub Actions verification."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

SAFE_ENV = {
    "PAPER_TRADING_ONLY": "true",
    "LIVE_TRADING_ENABLED": "false",
    "JITO_ENABLED": "false",
    "KAMINO_LIQUIDATION_ENABLED": "false",
}


def run(command: list[str]) -> None:
    """Run one mandatory verification command and fail immediately on error."""
    print(f"\n$ {' '.join(command)}", flush=True)

    env = os.environ.copy()
    env.update(SAFE_ENV)

    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
    )

    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-dependency-audit",
        action="store_true",
        help="Skip only the network-backed pip-audit step for offline development.",
    )
    args = parser.parse_args()

    run([sys.executable, "-m", "pip", "check"])

    quality_command = [sys.executable, "scripts/quality_gate.py"]
    if not args.skip_dependency_audit:
        quality_command.append("--with-dependency-audit")
    run(quality_command)

    run(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "arb_bot.py",
            "src",
            "scripts",
            "tests",
        ]
    )

    # PR-023 runtime-truth contract.
    run([sys.executable, "arb_bot.py", "status", "--json"])
    run([sys.executable, "arb_bot.py", "capabilities", "--json"])

    # Focused PR-023/PR-024 smoke and architectural checks.
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_pr023_runtime_truth.py",
            "tests/test_launcher_startup_smoke.py",
            "tests/test_import_smoke.py",
            "tests/test_quality_quarantine.py",
            "-q",
            "--disable-socket",
            "--allow-unix-socket",
        ]
    )

    # Complete offline non-live suite.
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "not live and not manual",
            "--disable-socket",
            "--allow-unix-socket",
            "-q",
        ]
    )

    print(
        "\nRepository verification passed. "
        "Live trading readiness was not evaluated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
