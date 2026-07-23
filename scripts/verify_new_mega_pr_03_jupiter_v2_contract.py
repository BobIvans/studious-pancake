#!/usr/bin/env python3
"""Fail-closed scaffold for NEW-MEGA-PR-03 Jupiter V2 contract verification.

This scaffold intentionally blocks until the canonical runtime is wired to one
strict Jupiter Swap V2 `/build` DTO with rooted height/slot evidence and no
reachable V1, hybrid, or ExactOut request paths.
"""
from __future__ import annotations

import json


def main() -> int:
    report = {
        "accepted": False,
        "promotion_state": "blocked_pending_new_mega_pr_03_implementation",
        "scope": "jupiter_v2_contract",
        "required": [
            "canonical_v2_build_dto_only",
            "no_v1_or_hybrid_paths",
            "request_validation_before_quota",
            "strict_route_plan_validation",
            "positive_last_valid_block_height",
            "exact_in_only_no_swap_mode",
        ],
        "reason": "Scaffold only: strict Jupiter V2 contract is not yet materialized.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
