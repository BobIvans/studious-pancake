#!/usr/bin/env python3
"""Materialize a final release-evidence bundle and compute fail-closed qualification.

Default invocation preserves the legacy PR-186 dry-run qualification plan contract.
Pass ``--execute --profile production`` to run the MPR-CLOSE-06 release bundle
materialization flow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
EXIT_BLOCKED = 3
EXIT_FAILED = 2

SCHEMA_VERSION = "mpr-close-06.release-qualification.v1"
BUNDLE_SCHEMA_VERSION = "mpr-close-06.release-bundle.v1"
HUMAN_REVIEW_SCHEMA_VERSION = "mpr-close-06.human-review-manifest.v1"


def _bootstrap_repo_imports() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


REQUIRED_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "runtime_wheel_digest": ("dist/*.whl",),
    "runtime_image_digest": (
        "release_artifacts/runtime-image-digest.txt",
        ".runtime/evidence/runtime-image-digest.txt",
    ),
    "signer_image_digest": (
        "release_artifacts/signer-image-digest.txt",
        ".runtime/evidence/signer-image-digest.txt",
    ),
    "sbom_digest": ("release_artifacts/sbom.json", ".runtime/evidence/sbom.json"),
    "dependency_lock_wheelhouse_digest": (
        "requirements.lock",
        "poetry.lock",
        "release_artifacts/wheelhouse-manifest.json",
        ".runtime/evidence/wheelhouse-manifest.json",
    ),
    "capability_manifest_digest": ("src/resources/capabilities.json",),
    "production_surface_manifest_digest": ("src/resources/production_surface_manifest.json",),
    "runtime_authority_map_digest": (
        "config/runtime_authority_map.json",
        "src/resources/runtime_authority_map.json",
    ),
    "config_generation_digest": (
        "config/production_cutover_manifest.json",
        ".runtime/evidence/config-generation-digest.json",
    ),
    "database_schema_fingerprint": (
        "release_artifacts/database-schema-fingerprint.json",
        ".runtime/evidence/database-schema-fingerprint.json",
    ),
    "backup_restore_report_digest": (
        "release_artifacts/backup-restore-report.json",
        ".runtime/evidence/backup-restore-report.json",
    ),
    "fault_injection_report_digest": (
        "release_artifacts/fault-injection-report.json",
        ".runtime/evidence/fault-injection-report.json",
    ),
    "provider_drift_probe_report_digest": (
        "release_artifacts/provider-drift-report.json",
        ".runtime/evidence/provider-drift-report.json",
    ),
    "shadow_campaign_report_digest": (
        "release_artifacts/shadow-soak-report.json",
        ".runtime/evidence/shadow-soak-report.json",
    ),
    "finalized_economics_report_digest": (
        "release_artifacts/finalized-economics-report.json",
        ".runtime/evidence/finalized-economics-report.json",
    ),
    "signer_canary_approval_bundle_digest": (
        "release_artifacts/signer-canary-approval-bundle.json",
        ".runtime/evidence/signer-canary-approval-bundle.json",
    ),
}

DEBT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "runtime.product-state": (
        "capability_manifest_digest",
        "runtime_authority_map_digest",
    ),
    "runtime.live-entrypoint": ("capability_manifest_digest",),
    "packaging.source-wheel-parity": ("runtime_wheel_digest",),
    "runtime.canonical-vertical-wiring": (
        "runtime_authority_map_digest",
        "shadow_campaign_report_digest",
        "finalized_economics_report_digest",
    ),
    "runtime.legacy-ingest-removal": ("runtime_authority_map_digest",),
    "execution.exact-simulation-binding": (
        "shadow_campaign_report_digest",
        "finalized_economics_report_digest",
    ),
    "execution.canonical-transaction-proof": (
        "shadow_campaign_report_digest",
        "finalized_economics_report_digest",
    ),
    "execution.finalized-settlement-binding": (
        "finalized_economics_report_digest",
        "shadow_campaign_report_digest",
    ),
    "economics.capital-reservations": ("finalized_economics_report_digest",),
    "accounts.lifecycle-rent-wsol": ("shadow_campaign_report_digest",),
    "durability.single-truth-cutover": (
        "database_schema_fingerprint",
        "backup_restore_report_digest",
    ),
    "data.rpc-rooted-quorum": ("provider_drift_probe_report_digest",),
    "data.oracle-slot-coherence": ("provider_drift_probe_report_digest",),
    "external.solana-v0-rpc": ("provider_drift_probe_report_digest",),
    "external.jupiter-swap-v2": ("provider_drift_probe_report_digest",),
    "external.helius-webhook-auth": ("provider_drift_probe_report_digest",),
    "external.jito-low-latency": ("provider_drift_probe_report_digest",),
    "external.marginfi-v2": ("provider_drift_probe_report_digest",),
    "external.kamino-klend": ("provider_drift_probe_report_digest",),
    "lending.kamino-supported-combinations": ("provider_drift_probe_report_digest",),
    "external.okx-signed-discovery": ("provider_drift_probe_report_digest",),
    "external.openocean-whitelist-discovery": ("provider_drift_probe_report_digest",),
    "external.odos-immutable-transaction": ("provider_drift_probe_report_digest",),
    "submission.jito-unbundling-protection": (
        "provider_drift_probe_report_digest",
        "signer_canary_approval_bundle_digest",
    ),
    "evidence.real-shadow-soak": ("shadow_campaign_report_digest",),
    "evidence.provider-drift-probes": ("provider_drift_probe_report_digest",),
    "evidence.finalized-economic-proof": ("finalized_economics_report_digest",),
    "deployment.image-provenance": (
        "runtime_image_digest",
        "sbom_digest",
        "dependency_lock_wheelhouse_digest",
    ),
    "operations.slo-readiness": ("shadow_campaign_report_digest",),
    "security.signer-isolation": ("signer_canary_approval_bundle_digest",),
    "security.secret-incident-drill": ("signer_canary_approval_bundle_digest",),
    "data.lineage-quarantine": (
        "shadow_campaign_report_digest",
        "provider_drift_probe_report_digest",
    ),
    "canary.permit-budget-latches": ("signer_canary_approval_bundle_digest",),
    "canary.second-human-approval": ("signer_canary_approval_bundle_digest",),
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git_head_commit(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    raw = head.read_text(encoding="utf-8").strip()
    if raw.startswith("ref: "):
        ref = raw[5:]
        target = root / ".git" / ref
        if target.is_file():
            return target.read_text(encoding="utf-8").strip() or None
        return None
    return raw or None


def _glob_matches(root: Path, pattern: str) -> list[Path]:
    return sorted(
        path for path in root.glob(pattern) if path.is_file() and not path.is_symlink()
    )


def _first_existing(root: Path, candidates: Iterable[str]) -> Path | None:
    for candidate in candidates:
        if "*" in candidate or "?" in candidate or "[" in candidate:
            matches = _glob_matches(root, candidate)
            if matches:
                return matches[0]
            continue
        path = root / candidate
        if path.is_file() and not path.is_symlink():
            return path
    return None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    finally:
        tmp = Path(tmp_name)
        if tmp.exists():
            tmp.unlink()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_release_artifacts(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    artifacts: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for artifact_id, candidates in REQUIRED_ARTIFACTS.items():
        matched = _first_existing(root, candidates)
        if matched is None:
            record = {
                "id": artifact_id,
                "status": "missing",
                "path": None,
                "sha256": None,
                "size_bytes": None,
            }
        else:
            record = {
                "id": artifact_id,
                "status": "present",
                "path": matched.relative_to(root).as_posix(),
                "sha256": _sha256_file(matched),
                "size_bytes": matched.stat().st_size,
            }
        artifacts.append(record)
        by_id[artifact_id] = record
    return artifacts, by_id


def resolve_debt_items(
    inventory: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    *,
    product_state: str,
    live_mode_available: bool,
) -> dict[str, dict[str, Any]]:
    resolutions: dict[str, dict[str, Any]] = {}
    for item in inventory.get("items", []):
        item_id = item["id"]
        required = DEBT_REQUIREMENTS.get(item_id, ())
        missing = [
            artifact_id for artifact_id in required if artifacts.get(artifact_id, {}).get("status") != "present"
        ]
        notes: list[str] = []
        resolved = not missing
        if item_id == "runtime.product-state":
            resolved = resolved and product_state in {
                "paper-shadow-production-ready",
                "bounded-canary-ready",
                "production-ready",
            }
            if not resolved:
                notes.append(f"product_state={product_state}")
        if item_id == "runtime.live-entrypoint":
            resolved = resolved and live_mode_available
            if not live_mode_available:
                notes.append("live_mode_available=false")
        if missing:
            notes.append("missing_artifacts=" + ",".join(sorted(missing)))
        resolutions[item_id] = {
            "resolved": resolved,
            "required_artifacts": list(required),
            "evidence_digests": [
                artifacts[artifact_id]["sha256"]
                for artifact_id in required
                if artifacts.get(artifact_id, {}).get("status") == "present"
            ],
            "notes": notes or ["evidence-materialized"],
        }
    return resolutions


def build_release_bundle(
    root: Path,
    *,
    release_id: str,
    output_path: Path,
    profile: str,
) -> dict[str, Any]:
    from scripts.verify_pr200_production_cutover import validate_manifest

    capabilities = _load_json(root / "src" / "resources" / "capabilities.json")
    inventory = _load_json(root / "src" / "resources" / "production_debt.json")
    runtime_authority = _load_json(root / "config" / "runtime_authority_map.json")
    cutover_manifest = _load_json(root / "config" / "production_cutover_manifest.json")
    pr200 = validate_manifest(cutover_manifest)

    bundle_dir = root / "release_artifacts" / "final" / release_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    human_review = {
        "schema_version": HUMAN_REVIEW_SCHEMA_VERSION,
        "release_id": release_id,
        "review_status": "pending-human-review",
        "reviewers": [],
        "notes": [],
    }
    _atomic_write(bundle_dir / "human_review_manifest.json", human_review)

    artifacts, artifacts_by_id = collect_release_artifacts(root)
    review_path = bundle_dir / "human_review_manifest.json"
    artifacts.append(
        {
            "id": "human_review_manifest",
            "status": "present",
            "path": review_path.relative_to(root).as_posix(),
            "sha256": _sha256_file(review_path),
            "size_bytes": review_path.stat().st_size,
        }
    )

    product_state = str(capabilities.get("product_state", "unknown"))
    runtime_modes = capabilities.get("runtime_modes", {})
    live_mode_available = bool(runtime_modes.get("live", {}).get("available"))

    debt_resolution = resolve_debt_items(
        inventory,
        artifacts_by_id,
        product_state=product_state,
        live_mode_available=live_mode_available,
    )

    bundle_manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "release_id": release_id,
        "profile": profile,
        "produced_at": _utc_now(),
        "source_commit": _git_head_commit(root),
        "product_state": product_state,
        "live_mode_available": live_mode_available,
        "pr200_cutover": pr200,
        "artifacts": artifacts,
        "runtime_authority_map_digest": _sha256_bytes(
            _canonical_json(runtime_authority)
        ),
        "production_debt_inventory_digest": _sha256_bytes(_canonical_json(inventory)),
        "debt_resolution": debt_resolution,
    }
    bundle_manifest_path = bundle_dir / "bundle_manifest.json"
    _atomic_write(bundle_manifest_path, bundle_manifest)

    resolved_items = sorted(
        item_id for item_id, info in debt_resolution.items() if info["resolved"]
    )
    unresolved_items = sorted(
        item_id for item_id, info in debt_resolution.items() if not info["resolved"]
    )
    missing_artifacts = sorted(
        artifact["id"] for artifact in artifacts if artifact["status"] != "present"
    )
    qualification = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "profile": profile,
        "executed_at": _utc_now(),
        "bundle_path": bundle_dir.relative_to(root).as_posix(),
        "bundle_manifest_path": bundle_manifest_path.relative_to(root).as_posix(),
        "bundle_manifest_sha256": _sha256_file(bundle_manifest_path),
        "source_commit": _git_head_commit(root),
        "product_state": product_state,
        "live_mode_available": live_mode_available,
        "promotion_state": (
            "blocked_pending_evidence"
            if missing_artifacts or unresolved_items or not pr200["accepted"]
            else "qualified"
        ),
        "qualified": not missing_artifacts and not unresolved_items and pr200["accepted"],
        "release_claim_allowed": False,
        "missing_artifacts": missing_artifacts,
        "resolved_debt_items": resolved_items,
        "open_debt_items": unresolved_items,
        "debt_resolution": debt_resolution,
        "pr200_cutover": pr200,
    }
    _atomic_write(output_path, qualification)
    return qualification


def _legacy_dry_run(args: argparse.Namespace) -> int:
    _bootstrap_repo_imports()
    from src.qualification_pr176 import build_default_qualification_plan
    from src.qualification_pr186 import qualification_plan_document, source_tree_identity

    root = Path(args.project_root).resolve()
    source = source_tree_identity(root)
    plan = build_default_qualification_plan(root)
    payload = qualification_plan_document(plan, source)
    _write_or_print(payload, args.output)
    return 0


def _write_or_print(payload: dict[str, Any], path: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile", action="append", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--release-id", default=None)
    parser.add_argument("--project-root", default=str(ROOT))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.project_root).resolve()
    selected_profiles = tuple(sorted(set(args.profile or ["production"])))
    try:
        if not args.execute:
            return _legacy_dry_run(args)
        if selected_profiles != ("production",):
            payload = {
                "schema_version": SCHEMA_VERSION,
                "qualified": False,
                "release_claim_allowed": False,
                "reason_codes": ["unsupported_profile_selection"],
                "selected_profiles": list(selected_profiles),
            }
            _write_or_print(payload, args.output)
            return EXIT_FAILED
        output = Path(args.output or root / ".runtime" / "release-qualification.json")
        release_id = args.release_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        qualification = build_release_bundle(
            root,
            release_id=release_id,
            output_path=output,
            profile="production",
        )
        print(json.dumps(qualification, indent=2, sort_keys=True))
        return 0 if qualification["qualified"] else EXIT_BLOCKED
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "qualified": False,
            "release_claim_allowed": False,
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }
        _write_or_print(payload, args.output)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
