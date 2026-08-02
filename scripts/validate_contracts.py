#!/usr/bin/env python3
"""Compatibility entry point for repository contract validation.

The canonical validator lives in :mod:`src.external_contracts.cli`.  This
script preserves the historical CI entry point and its optional plan-only
argument while delegating the actual repository contract checks to the
canonical registry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.external_contracts.cli import main as external_contracts_main


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plan",
        nargs="?",
        type=Path,
        help="optional Markdown plan checked by plan-only CI",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root used to resolve and constrain the plan path",
    )
    return parser


def _validate_plan(plan: Path, root: Path) -> None:
    resolved_root = root.resolve()
    candidate = plan if plan.is_absolute() else resolved_root / plan
    candidate = candidate.resolve()

    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SystemExit(f"plan path escapes repository root: {plan}") from exc

    if not candidate.is_file():
        raise SystemExit(f"plan file does not exist: {candidate}")

    try:
        text = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"plan file is not valid UTF-8: {candidate}") from exc

    if not text.strip():
        raise SystemExit(f"plan file is empty: {candidate}")
    if not any(line.lstrip().startswith("#") for line in text.splitlines()):
        raise SystemExit(f"plan file must contain a Markdown heading: {candidate}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.plan is not None:
        _validate_plan(args.plan, args.root)
    return external_contracts_main(["validate"])


if __name__ == "__main__":
    raise SystemExit(main())
