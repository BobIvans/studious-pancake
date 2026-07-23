#!/usr/bin/env python3
"""Verify that PR-194 production invariants survive ``python -O``.

The script is intentionally offline and sender-free. It does not import runtime
providers, wallets, RPC clients, Jito, Helius, Jupiter, MarginFi, or signer code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pr194_optimize_invariant_gate_lib import (  # noqa: E402
    PRODUCTION_CRITICAL_PATHS,
    build_evidence,
    normalize_repository_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic PR-194 optimize-mode evidence.",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help=(
            "Repository path to scan. May be repeated. Defaults to the "
            "PR-194 production-critical package and verification surface."
        ),
    )
    args = parser.parse_args(argv)

    selected_paths = args.paths or PRODUCTION_CRITICAL_PATHS
    paths = tuple(normalize_repository_path(path) for path in selected_paths)
    evidence = build_evidence(ROOT, paths)
    if args.json or not evidence["ready"]:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print("PR-194 optimize-mode invariant gate passed.")
    return 0 if evidence["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
