#!/usr/bin/env python3
"""Single local equivalent of mandatory repository verification."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]

SAFE_ENV: Final = {
    "PAPER_TRADING_ONLY": "true",
    "LIVE_TRADING_ENABLED": "false",
    "JITO_ENABLED": "false",
    "KAMINO_LIQUIDATION_ENABLED": "false",
}

QUALITY_COMMAND: Final[list[str]] = [
    sys.executable,
    "scripts/quality_gate.py",
]

PACKAGE_SMOKE_COMMAND: Final[list[str]] = [
    sys.executable,
    "scripts/package_smoke.py",
]

# Public by design: tests inspect the final offline pytest command.
COMMANDS: Final[list[list[str]]] = [
    [
        sys.executable,
        "-m",
        "pip",
        "check",
    ],
    [
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "arb_bot.py",
        "src",
        "scripts",
        "tests",
    ],
    [
        sys.executable,
        "arb_bot.py",
        "status",
        "--json",
    ],
    [
        sys.executable,
        "arb_bot.py",
        "capabilities",
        "--json",
    ],
    [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_pr023_runtime_truth.py",
        "tests/test_launcher_startup_smoke.py",
        "tests/test_import_smoke.py",
        "tests/test_quality_quarantine.py",
        "tests/test_pr087_package_boundary.py",
        "tests/test_pr101_marginfi_complete_protocol_evidence.py",
        "tests/test_pr106_canonical_sender_lifecycle_disabled.py",
        "tests/test_pr115_simulation_owned_economic_proof.py",
        "tests/test_pr116_coherent_marginfi_snapshot_oracle.py",
        "tests/test_pr121_single_durable_lifecycle_truth.py",
        "tests/test_pr120_secret_resolver_config_jito.py",
        "tests/test_pr125_lst_governance_policy.py",
        "-q",
        "--disable-socket",
        "--allow-unix-socket",
    ],
    [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        "not live and not manual",
        "--disable-socket",
        "--allow-unix-socket",
        "-q",
    ],
]


def run(command: list[str]) -> None:
    """Run a mandatory verification command and fail immediately on error."""
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


def ensure_clean_source_tree() -> None:
    """Fail if repository verification leaves generated files behind."""
    if not (ROOT / ".git").is_dir():
        return
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if completed.stdout.strip():
        print(completed.stdout, end="")
        raise SystemExit("repository verification left a dirty source tree")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-dependency-audit",
        action="store_true",
        help="Skip the network-backed dependency vulnerability audit.",
    )
    args = parser.parse_args()

    run(COMMANDS[0])

    quality_command = list(QUALITY_COMMAND)
    if not args.skip_dependency_audit:
        quality_command.append("--with-dependency-audit")
    run(quality_command)
    run(PACKAGE_SMOKE_COMMAND)

    for command in COMMANDS[1:]:
        run(command)

    ensure_clean_source_tree()

    print(
        "\nRepository verification passed. " "Live trading readiness was not evaluated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
