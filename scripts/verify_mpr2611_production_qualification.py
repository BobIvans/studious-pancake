#!/usr/bin/env python3
"""Static/fail-closed verifier for the MPR-2611 qualification authority."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "config" / "mpr2611_qualification_authority.json"

EXPECTED_AUTHORITIES = {
    "qualification_plan": "src/qualification_pr176.py",
    "executed_qualification": "scripts/qualify_release.py",
    "evidence_validation": "src/production_qualification.py",
    "debt_closure_projection": "scripts/qualify_release.py",
    "release_review_eligibility": "scripts/qualify_release.py",
    "qualification_verifier": "scripts/verify_mpr2611_production_qualification.py",
    "repeated_run_verifier": "scripts/run_mpr2611_clean_qualification.py",
}

REQUIRED_SEMANTIC_ARTIFACTS = {
    "database_schema_fingerprint",
    "backup_restore_report_digest",
    "fault_injection_report_digest",
    "provider_drift_probe_report_digest",
    "shadow_campaign_report_digest",
    "finalized_economics_report_digest",
    "signer_canary_approval_bundle_digest",
    "sbom_digest",
    "config_generation_digest",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _literal_bool_assignments(path: Path) -> dict[str, set[bool]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, set[bool]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            if key_node.value not in {"release_claim_allowed", "live_enabled"}:
                continue
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, bool):
                found.setdefault(key_node.value, set()).add(value_node.value)
    return found


def verify(root: Path = ROOT) -> dict[str, Any]:
    reasons: list[str] = []
    authority_map = _load_json(root / MAP_PATH.relative_to(ROOT))

    if authority_map.get("schema_version") != "mpr-2611.qualification-authority-map.v1":
        reasons.append("AUTHORITY_MAP_SCHEMA_MISMATCH")
    if authority_map.get("authorities") != EXPECTED_AUTHORITIES:
        reasons.append("AUTHORITY_MAP_OWNER_MISMATCH")
    if authority_map.get("final_release_owner") != "MPR-2612":
        reasons.append("FINAL_RELEASE_OWNER_MISMATCH")
    if authority_map.get("release_claim_allowed") is not False:
        reasons.append("AUTHORITY_MAP_RELEASE_CLAIM_ENABLED")
    if authority_map.get("live_enabled") is not False:
        reasons.append("AUTHORITY_MAP_LIVE_ENABLED")

    owned = set(authority_map.get("mpr2611_owned_paths", []))
    for owner in authority_map.get("parallel_owners", {}).values():
        for path in owner.get("paths", []):
            if path in owned:
                reasons.append(f"PARALLEL_SCOPE_COLLISION:{path}")

    for path in EXPECTED_AUTHORITIES.values():
        if not (root / path).is_file():
            reasons.append(f"MISSING_AUTHORITY:{path}")

    source = (root / "src" / "production_qualification.py").read_text(encoding="utf-8")
    namespace: dict[str, Any] = {}
    exec(compile(source, "src/production_qualification.py", "exec"), namespace)
    semantic = set(namespace.get("SEMANTIC_ARTIFACTS", {}))
    missing_semantic = REQUIRED_SEMANTIC_ARTIFACTS.difference(semantic)
    reasons.extend(f"MISSING_SEMANTIC_ARTIFACT:{name}" for name in sorted(missing_semantic))

    qualify_path = root / "scripts" / "qualify_release.py"
    assignments = _literal_bool_assignments(qualify_path)
    if True in assignments.get("release_claim_allowed", set()):
        reasons.append("QUALIFIER_CAN_ENABLE_RELEASE_CLAIM")
    if True in assignments.get("live_enabled", set()):
        reasons.append("QUALIFIER_CAN_ENABLE_LIVE")

    qualify_text = qualify_path.read_text(encoding="utf-8")
    if "validate_semantic_evidence" not in qualify_text:
        reasons.append("CANONICAL_QUALIFIER_BYPASSES_SEMANTIC_VALIDATOR")
    if "production_qualification_passed" not in qualify_text:
        reasons.append("MISSING_PRODUCTION_QUALIFICATION_OUTPUT")
    if "eligible_for_release_review" not in qualify_text:
        reasons.append("MISSING_RELEASE_REVIEW_OUTPUT")

    files = sorted(set(EXPECTED_AUTHORITIES.values()) | {str(MAP_PATH.relative_to(ROOT))})
    evidence = {path: _sha256(root / path) for path in files if (root / path).is_file()}
    payload = {
        "schema_version": "mpr-2611.static-verification.v1",
        "accepted": not reasons,
        "reason_codes": sorted(set(reasons)),
        "release_claim_allowed": False,
        "live_enabled": False,
        "evidence_sha256": evidence,
    }
    return payload


def main() -> int:
    payload = verify()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
