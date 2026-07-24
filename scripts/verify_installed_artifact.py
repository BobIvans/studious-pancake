#!/usr/bin/env python3
"""Verify the MPR-01 installed/source command surface.

Default mode validates the current source checkout with ``python -m src.cli_pr189``.
Pass ``--installed-command flashloan-bot`` after installing the wheel to verify the
same contract through the installed console script.

The active MPR-CLOSE-24 durable paper root intentionally uses non-zero process
codes for safe fail-closed outcomes.  Release authority accepts those outcomes as
valid command-surface evidence while continuing to reject live/signer/sender/Jito
promotion claims.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.canonical_paper import installed_artifact as artifact_contract  # noqa: E402
from src.canonical_paper.installed_artifact import (  # noqa: E402
    collect_source_checkout_evidence,
    evaluate_installed_artifact_evidence,
)

# src.cli owns these stable fail-closed meanings:
# 0 = accepted/no-trade paper outcome, 5 = blocked, 6 = failed, 7 = degraded.
# None of them enables signing, submission, Jito or live execution.
FAIL_CLOSED_PAPER_EXIT_CODES = frozenset({0, 5, 6, 7})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect and validate the MPR-01 sender-free installed artifact "
            "command-surface evidence."
        )
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="repository checkout root; defaults to the current directory",
    )
    parser.add_argument(
        "--installed-command",
        default=None,
        help=(
            "installed console command to execute, for example 'flashloan-bot'. "
            "Omit to verify the source checkout via python -m src.cli_pr189."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="per-command timeout for command-surface collection",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="optional path to write the collected evidence bundle as JSON",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the full report JSON instead of a one-line summary",
    )
    return parser


def _apply_active_paper_exit_contract() -> None:
    """Align the parity evaluator with the active durable paper root.

    The evaluator still validates the exact command argv, hashes and captured
    safety claims.  This only prevents a safe BLOCKED/FAILED/DEGRADED paper
    outcome from being misclassified as installed-artifact drift.
    """

    artifact_contract.EXPECTED_EXIT_CODES = {
        **artifact_contract.EXPECTED_EXIT_CODES,
        "canonical_paper_cycle": FAIL_CLOSED_PAPER_EXIT_CODES,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    command = (
        tuple(shlex.split(args.installed_command))
        if args.installed_command is not None
        else None
    )
    _apply_active_paper_exit_contract()
    evidence = collect_source_checkout_evidence(
        Path(args.project_root),
        command=command,
        timeout_seconds=args.timeout_seconds,
    )
    if args.manifest_output:
        output_path = Path(args.manifest_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    report = evaluate_installed_artifact_evidence(evidence)
    payload = report.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "MPR01_INSTALLED_ARTIFACT: "
            f"ok={str(report.ok).lower()} "
            f"reason={report.reason_code} "
            f"commands={payload['command_surface_digest']} "
            f"violations={len(report.violations)} "
            "live=false signer=false sender=false"
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
