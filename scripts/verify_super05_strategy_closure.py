#!/usr/bin/env python3
"""Verify SUPER-05 code closure while preserving operational blockers."""

from __future__ import annotations

import json
from pathlib import Path

from src.super05_strategy_closure import evaluate_super05


def main() -> int:
    report = evaluate_super05(root=Path.cwd())
    print(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if (
        not report.implementation_complete
        or report.live_enabled
        or report.release_claim_allowed
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
