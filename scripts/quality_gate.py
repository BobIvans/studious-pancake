#!/usr/bin/env python3
"""Mandatory PR-024 static, format, type, and security quality gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _manifest_paths(path: Path) -> list[str]:
    paths: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            paths.append(line)
    if not paths:
        raise SystemExit(f"empty quality manifest: {path.relative_to(ROOT)}")
    missing = [item for item in paths if not (ROOT / item).exists()]
    if missing:
        raise SystemExit(f"quality manifest contains missing paths: {missing}")
    return paths


def _validate_quarantine() -> None:
    payload = json.loads(
        (ROOT / "config/quality_quarantine.json").read_text(encoding="utf-8")
    )
    entries = payload.get("entries", [])
    if not entries:
        raise SystemExit("quality quarantine must be explicit and non-empty")
    for entry in entries:
        path = entry.get("path")
        if not path or not (ROOT / path).is_file():
            raise SystemExit(f"invalid quarantine entry: {entry}")
        if entry.get("status") != "non-importable-quarantine":
            raise SystemExit(f"quarantine status is not fail-closed: {entry}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-dependency-audit",
        action="store_true",
        help="Run the online pip-audit gate in addition to deterministic checks.",
    )
    args = parser.parse_args()

    _validate_quarantine()
    _run(
        [
            sys.executable,
            "-m",
            "flake8",
            "arb_bot.py",
            "src",
            "scripts",
            "tests",
            "--count",
            "--select=E9,F63,F7,F82",
            "--show-source",
            "--statistics",
        ]
    )

    format_targets = _manifest_paths(ROOT / "config/format_targets.txt")
    _run([sys.executable, "-m", "black", "--check", *format_targets])
    _run([sys.executable, "-m", "mypy", "--config-file", "mypy.ini"])

    # Existing medium/low findings are triaged for PR-043. PR-024 makes any
    # new or existing HIGH severity/high-confidence finding a hard failure.
    _run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "arb_bot.py",
            "src",
            "scripts",
            "-x",
            "src/legacy_arb_bot.py,tests",
            "-lll",
            "-iii",
            "-q",
        ]
    )

    if args.with_dependency_audit:
        _run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                "requirements.txt",
                "--strict",
                "--progress-spinner",
                "off",
            ]
        )

    print("\nPR-024 quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
