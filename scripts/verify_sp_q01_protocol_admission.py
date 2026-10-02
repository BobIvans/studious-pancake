#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lending.sp_q01_protocol_admission import (
    SCHEMA as ADMISSION_SCHEMA,
    admission_artifact_bundle_sha256,
    admission_receipt_sha256,
    expected_identity,
    validate_protocol_admission_receipt,
)
from src.runtime.core_v1_dependency_resolver import (
    LEGACY_SCHEMA,
    SCHEMA as MANIFEST_SCHEMA,
    resolve_installed_core_v1_dependencies,
)
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CoreV1ReleaseProfile,
)


def _fixture(role: str, now: datetime) -> dict[str, object]:
    identity = expected_identity(role)
    observed = now - timedelta(minutes=30)
    valid_until = now + timedelta(hours=1)
    payload: dict[str, object] = {
        "schema_version": ADMISSION_SCHEMA,
        "role": role,
        "lender_id": identity.lender_id,
        "program_id": identity.program_id,
        "upstream_repository": identity.upstream_repository,
        "upstream_commit": identity.upstream_commit,
        "interface_blobs": list(identity.interface_blobs),
        "build_artifact_sha256": ("a" if role == "PRIMARY" else "b") * 64,
        "deployed_programdata_sha256": ("c" if role == "PRIMARY" else "d") * 64,
        "availability_status": "OBSERVED_AVAILABLE",
        "rooted": True,
        "observed_root_slot": 100,
        "max_root_lag_slots": 2,
        "accounts": [
            {
                "address": identity.required_account,
                "owner": identity.required_account_owner,
                "data_sha256": "e" * 64,
                "slot": 99,
                "executable": False,
            }
        ],
        "observed_at_utc": observed.isoformat(),
        "valid_until_utc": valid_until.isoformat(),
    }
    artifact = admission_artifact_bundle_sha256(payload)
    payload["artifact_bundle_sha256"] = artifact
    payload["manual_review"] = {
        "review_id": f"synthetic-{role.lower()}-review",
        "reviewers": ["offline-verifier"],
        "reviewed_at_utc": now.isoformat(),
        "approved": True,
        "reviewed_artifact_sha256": artifact,
    }
    payload["receipt_sha256"] = admission_receipt_sha256(payload)
    return payload


def verify() -> dict[str, object]:
    errors: list[str] = []
    now = datetime.now(UTC)

    if MANIFEST_SCHEMA != "core-v1.financing-evidence-manifest.v2":
        errors.append("SP_Q01_MANIFEST_V2_NOT_ACTIVE")
    if LEGACY_SCHEMA != "core-v1.financing-evidence-manifest.v1":
        errors.append("SP_Q01_LEGACY_SCHEMA_NOT_EXPLICIT")

    receipts = {}
    for role in ("PRIMARY", "RENT"):
        payload = _fixture(role, now)
        receipt = validate_protocol_admission_receipt(
            payload,
            role=role,
            now_utc=now,
        )
        receipts[role] = receipt.receipt_sha256

    marginfi = CoreV1ReleaseProfile(
        profile_id="marginfi-policy-check",
        strategy="circular_arbitrage",
        lender="marginfi",
        router="jupiter",
        cluster="mainnet-beta",
        genesis_hash="synthetic",
        transport="rpc",
        profile_generation=1,
    )
    resolution = resolve_installed_core_v1_dependencies(marginfi, {})
    if resolution.dependencies is not None or resolution.blocker != CORE_V1_BLOCKED_EXTERNAL:
        errors.append("SP_Q01_MARGINFI_POLICY_DRIFT")

    baseline = json.loads(
        (ROOT / "release_artifacts/sp_q01/BASELINE.json").read_text(
            encoding="utf-8"
        )
    )
    matrix = json.loads(
        (
            ROOT
            / "release_artifacts/sp_q01/REQUIREMENT_EVIDENCE_MATRIX.json"
        ).read_text(encoding="utf-8")
    )
    if baseline.get("selected_goal") != "SP-Q01":
        errors.append("SP_Q01_BASELINE_GOAL_MISMATCH")
    if not any(
        row.get("status") == "EXTEND"
        and row.get("blocker_after")
        == "REAL_ROOTED_DEPLOYMENT_ACCOUNT_BUILD_AND_REVIEW_RECEIPT_NOT_SUPPLIED"
        for row in matrix.get("rows", [])
    ):
        errors.append("SP_Q01_RESIDUAL_BLOCKER_NOT_PRESERVED")

    return {
        "schema": "sp-q01.verification.v1",
        "ok": not errors,
        "errors": errors,
        "manifest_schema": MANIFEST_SCHEMA,
        "admission_schema": ADMISSION_SCHEMA,
        "synthetic_receipts": receipts,
        "marginfi_paused": True,
        "primary_role": "jupiter-lend",
        "rent_role": "slumlord",
        "real_operational_qualification": False,
        "live": False,
        "sign": False,
        "send": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
