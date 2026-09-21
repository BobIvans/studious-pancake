#!/usr/bin/env python3
"""Verify PR-353 current-head strategy closure evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.release_gate.pr353_strategy_closure import audit_pr353_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release_artifacts/final8/PR-353/current-head-evidence.json"
MATRIX = ROOT / "release_artifacts/final8/PR-353/FINAL_STRATEGY_DISPOSITION_MATRIX.json"
RESIDUAL = ROOT / "docs/qualification/FINAL_CURRENT_HEAD_RESIDUAL_MAP.json"


def verify() -> dict[str, object]:
    errors: list[str] = []
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        audit = audit_pr353_manifest(payload)
    except Exception as exc:
        return {"status": "FAIL", "errors": [str(exc)]}

    try:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        residual = json.loads(RESIDUAL.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "errors": [f"artifact-load:{exc}"]}

    if matrix.get("strategy_count") != audit.strategy_count:
        errors.append("strategy-matrix-count-mismatch")
    if matrix.get("final_verdict") != audit.final_verdict:
        errors.append("strategy-matrix-verdict-mismatch")
    if residual.get("nf_owner_count") != audit.nf_owner_count:
        errors.append("residual-map-nf-count-mismatch")
    if residual.get("owner_source") != (
        "src/release_gate/ultimate_mega1_closure.py::NF_TO_CLOSURE"
    ):
        errors.append("residual-map-owner-source-mismatch")
    for payload_name, item in (("matrix", matrix), ("residual", residual)):
        for field in ("production_ready", "live_enabled"):
            if item.get(field) is not False:
                errors.append(f"unsafe-flag:{payload_name}:{field}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "observed_main": audit.observed_main,
        "nf_owner_count": audit.nf_owner_count,
        "work_package_count": audit.work_package_count,
        "strategy_count": audit.strategy_count,
        "final_verdict": audit.final_verdict,
        "production_ready": False,
        "live_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify()
    print(json.dumps(result, sort_keys=True) if args.json else result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
