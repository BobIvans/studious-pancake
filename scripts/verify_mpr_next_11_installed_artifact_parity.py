#!/usr/bin/env python3
"""Fail-closed MPR-NEXT-11 installed-artifact parity verifier scaffold.

This script is intentionally a start-point contract. It should be replaced with
a real verifier that runs against an installed wheel/console command surface,
not only the source checkout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

SCHEMA_VERSION = "mpr-next-11.installed-artifact-parity.v0"
REQUIRED_COMMANDS = [
    "flashloan-bot --help",
    "flashloan-bot status --json",
    "flashloan-bot capabilities --json",
    "flashloan-bot config doctor --json",
    "flashloan-bot run --mode paper --json",
]


@dataclass(frozen=True)
class VerificationResult:
    schema_version: str
    ok: bool
    reason: str
    required_commands: list[str]
    violations: list[str]


def verify_installed_artifact_parity(repo_root: Path) -> VerificationResult:
    violations = [
        "real installed-wheel command execution is not implemented yet",
        "console-command surface has not been proven independent of source PYTHONPATH",
        "missing-dependency behavior has not been normalized into release evidence",
    ]
    return VerificationResult(
        schema_version=SCHEMA_VERSION,
        ok=False,
        reason="mpr_next_11_installed_artifact_parity_not_implemented",
        required_commands=REQUIRED_COMMANDS,
        violations=violations,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = verify_installed_artifact_parity(Path(args.repo_root).resolve())
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(f"{result.schema_version}: ok={result.ok} reason={result.reason}")
        for violation in result.violations:
            print(f"- {violation}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
