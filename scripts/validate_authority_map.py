#!/usr/bin/env python3
"""Validate the PR-01 authority, queue and package contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.authority_map import AuthorityMap, AuthorityMapError

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root containing config/runtime_authority_map.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        authority = AuthorityMap.load(root / "config/runtime_authority_map.json")
        errors = authority.validate_repository(root)
    except AuthorityMapError as exc:
        errors = (str(exc),)
    payload = {
        "schema_version": "pr01.authority-validation.v1",
        "valid": not errors,
        "product_state": (
            authority.product_state if not errors else "not-production-ready"
        ),
        "errors": list(errors),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
