#!/usr/bin/env python3
"""Verify PR-359 Wave 15 INST-01 bounded market-institution semantics."""

from __future__ import annotations

import json
from typing import Any, Mapping

from src.research.pr359_wave15_institution import run_inst01_vertical


def verify() -> Mapping[str, Any]:
    first = run_inst01_vertical()
    second = run_inst01_vertical()
    errors: list[str] = []
    if first["integrated_receipt_hash"] != second["integrated_receipt_hash"]:
        errors.append("PR359_NONDETERMINISTIC_REPLAY")
    if first["verdict"]["total_unilateral_checks"] != 5250:
        errors.append("PR359_FINITE_CHECK_COUNT_MISMATCH")
    if not first["verdict"]["first_price_counterexample_found"]:
        errors.append("PR359_FIRST_PRICE_COUNTEREXAMPLE_MISSING")
    if first["verdict"]["critical_price_max_tested_gain"] != 0:
        errors.append("PR359_CRITICAL_PRICE_FINITE_GAIN_FOUND")
    if first["accepted_receipt"]["status"] != "ACCEPTED_SYNTHETIC":
        errors.append("PR359_ACCEPTED_PATH_FAILED")
    if first["accepted_receipt"]["payment_is_real"] is not False:
        errors.append("PR359_REAL_PAYMENT_OVERCLAIM")
    if (
        first["wrong_well_hashed_verification"]["reason"]
        != "SEMANTIC_VALIDATION_FAILED"
    ):
        errors.append("PR359_SEMANTIC_RESOLVER_FAILED")
    if first["unknown_receipt"]["status"] != "HELD_UNKNOWN":
        errors.append("PR359_UNKNOWN_NOT_PRESERVED")
    if any(first["effect_boundary"].values()):
        errors.append("PR359_EFFECT_BOUNDARY_BREACH")
    if first["verdict"]["production_ready"] or first["verdict"]["live_enabled"]:
        errors.append("PR359_LIVE_OR_PRODUCTION_OVERCLAIM")
    return {
        "roadmap_id": "PR-359",
        "accepted": not errors,
        "errors": errors,
        "integrated_receipt_hash": first["integrated_receipt_hash"],
        "total_unilateral_checks": first["verdict"]["total_unilateral_checks"],
        "verdict": first["verdict"]["verdict"],
        "scope": first["verdict"]["scope"],
        "production_ready": False,
        "live_enabled": False,
        "execution_right": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
