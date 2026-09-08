#!/usr/bin/env python3
"""Required behavioral regressions for the existing runtime and SQLite owner."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-socket",
            "--allow-unix-socket",
            "tests/test_mpr2601_validation_patch.py",
            "tests/test_mpr2601_registered_contract.py",
            "tests/test_mpr2601_durable_atomicity.py",
            "tests/test_mpr2601_terminal_recovery.py",
            "tests/test_mpr2601_scope_workers.py",
            "tests/test_pr04_repeated_installed_paper_service.py",
            "tests/test_pr057_durable_capital_reservations.py",
            "tests/test_pr02_unified_lifecycle_authority.py",
            "tests/test_mega_pr_a3_installed_durable_paper_service.py",
        ],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
