#!/usr/bin/env python3
"""Validate the fail-closed PR-200 production cutover gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = "pr200.production-cutover-gate.v1"

REQUIRED_TOP_LEVEL: Final = {
    "schema_version",
    "promotion_state",
    "live_trading_enabled",
    "cutover_unit",
    "required_release_artifacts",
    "isolation",
    "readiness",
    "slo_budgets",
    "fault_injection",
    "backup_restore",
    "rollback",
    "legacy_execution_surface",
}

REQUIRED_RELEASE_ARTIFACTS: Final = {
    "runtime_wheel_digest",
    "runtime_image_digest",
    "sbom_digest",
    "config_generation_digest",
    "capability_manifest_digest",
    "program_idl_hashes",
    "database_schema_fingerprint",
    "shadow_campaign_report_digest",
    "fault_injection_report_digest",
    "backup_restore_report_digest",
}

REQUIRED_READINESS_BLOCKERS: Final = {
    "dead_strategy",
    "stale_rooted_data",
    "db_degraded",
    "release_latch",
    "signer_unavailable",
    "outstanding_unknown_attempt",
    "provider_budget_exhausted",
}

REQUIRED_SLO_BUDGETS: Final = {
    "event_loop_lag_p99_ms",
    "opportunity_age_p99_ms",
    "queue_depth_max",
    "db_commit_p99_ms",
    "rto_seconds",
    "signed_intent_rpo",
    "unknown_submission_count_before_promotion",
    "soak_memory_fd_growth",
}

REQUIRED_FAULT_INJECTIONS: Final = {
    "kill_after_state_row_before_event_row",
    "kill_after_submission_accept_before_db_ack",
    "dual_process_attempt_creation",
    "clock_jump_suspend_reboot",
    "disk_full_read_only_db",
    "corrupt_wal_or_torn_tail",
    "duplicate_webhook",
    "lost_webhook",
    "provider_429_5xx_across_replicas",
    "dns_resolves_private_or_link_local",
    "strategy_generator_raises",
    "sigterm_with_non_empty_queue",
    "blockhash_expires_before_send",
    "jito_ack_without_chain_record",
    "landed_failed_transaction",
    "oversized_v0_message",
    "malicious_allowed_program_instruction",
    "token_2022_unknown_extension",
    "backup_during_wal_writes",
}

REQUIRED_PRODUCTION_EXCLUSIONS: Final = {
    "arb_bot.py",
    "src/execution/senders",
    "src/execution/live_control.py",
    "src/execution/shadow.py",
}


class ProductionCutoverError(ValueError):
    """Raised when the cutover manifest no longer blocks unsafe promotion."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProductionCutoverError(message)


def _dict(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    _require(isinstance(value, dict), f"{key} must be an object")
    return value


def _object_list(mapping: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = mapping.get(key)
    _require(isinstance(value, list), f"{key} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        _require(isinstance(item, dict), f"{key} entries must be objects")
        result.append(item)
    return result


def _string_set(mapping: dict[str, Any], key: str) -> set[str]:
    value = mapping.get(key)
    _require(isinstance(value, list), f"{key} must be a list")
    result: set[str] = set()
    for item in value:
        _require(isinstance(item, str) and bool(item), f"{key} entries must be strings")
        result.add(item)
    return result


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductionCutoverError(f"{path}: invalid JSON") from exc
    _require(isinstance(loaded, dict), f"{path}: top-level value must be an object")
    return loaded


def _validate_cutover_unit(manifest: dict[str, Any]) -> None:
    cutover = _dict(manifest, "cutover_unit")
    _require(
        cutover.get("requires_signed_release_manifest") is True,
        "signed release manifest must be required",
    )
    _require(
        cutover.get("release_manifest_must_bind_wheel_image_config_and_evidence")
        is True,
        "release manifest must bind wheel/image/config/evidence",
    )
    _require(
        cutover.get("signing_key_source") == "external-secret-provider",
        "production signing key must come from an external secret provider",
    )
    _require(
        cutover.get("generated_production_key_allowed") is False,
        "generated production keys must be forbidden",
    )
    _require(
        cutover.get("promotion_requires_outstanding_unknown_attempts") == 0,
        "promotion must require zero UNKNOWN attempts",
    )


def _validate_release_artifacts(manifest: dict[str, Any]) -> list[str]:
    artifacts = _object_list(manifest, "required_release_artifacts")
    artifact_ids = {str(item.get("id")) for item in artifacts}
    missing = REQUIRED_RELEASE_ARTIFACTS - artifact_ids
    _require(not missing, f"missing release artifacts: {sorted(missing)}")

    blockers: list[str] = []
    for item in artifacts:
        artifact_id = item.get("id")
        _require(
            isinstance(artifact_id, str) and bool(artifact_id),
            "artifact id required",
        )
        _require(
            item.get("required_before_promotion") is True,
            f"{artifact_id} must block promotion",
        )
        blocker = item.get("promotion_blocker")
        _require(
            isinstance(blocker, str) and blocker.startswith("MISSING_"),
            f"{artifact_id} must have a stable missing-evidence blocker",
        )
        blockers.append(blocker)
    return blockers


def _validate_isolation(manifest: dict[str, Any]) -> None:
    isolation = _dict(manifest, "isolation")
    runtime = _dict(isolation, "runtime")
    signer = _dict(isolation, "signer")

    for key in (
        "digest_pinned_image_required",
        "read_only_root_filesystem_required",
        "egress_allowlist_required",
        "deny_arbitrary_internet",
    ):
        _require(runtime.get(key) is True, f"runtime {key} must be true")
    _require(
        bool(_string_set(runtime, "approved_egress_purposes")),
        "runtime approved egress purposes must not be empty",
    )

    _require(
        signer.get("separate_process_required") is True,
        "signer must be a separate process/service",
    )
    for key in (
        "shared_internet_egress_allowed",
        "private_key_environment_allowed",
        "shared_runtime_filesystem_allowed",
    ):
        _require(signer.get(key) is False, f"signer {key} must be false")


def _validate_readiness(manifest: dict[str, Any]) -> None:
    readiness = _dict(manifest, "readiness")
    liveness_endpoint = readiness.get("liveness_endpoint")
    readiness_endpoint = readiness.get("readiness_endpoint")
    _require(
        isinstance(liveness_endpoint, str) and liveness_endpoint.startswith("/"),
        "bad liveness endpoint",
    )
    _require(
        isinstance(readiness_endpoint, str) and readiness_endpoint.startswith("/"),
        "bad readiness endpoint",
    )
    _require(
        liveness_endpoint != readiness_endpoint,
        "liveness and readiness endpoints must be distinct",
    )
    _require(readiness.get("must_be_distinct") is True, "distinct probes required")
    blockers = _string_set(readiness, "readiness_blocks_on")
    missing = REQUIRED_READINESS_BLOCKERS - blockers
    _require(not missing, f"missing readiness blockers: {sorted(missing)}")


def _validate_slo_budgets(manifest: dict[str, Any]) -> None:
    budgets = _dict(manifest, "slo_budgets")
    missing = REQUIRED_SLO_BUDGETS - set(budgets)
    _require(not missing, f"missing SLO budgets: {sorted(missing)}")
    for key in REQUIRED_SLO_BUDGETS:
        budget = _dict(budgets, key)
        _require(budget.get("evidence_required") is True, f"{key} needs evidence")
        max_value = budget.get("max")
        _require(
            _is_number(max_value) and max_value >= 0,
            f"{key} must define a numeric max budget",
        )
    _require(
        _dict(budgets, "event_loop_lag_p99_ms").get("max", 0) > 0,
        "event loop lag p99 budget must be positive",
    )
    _require(
        _dict(budgets, "unknown_submission_count_before_promotion").get("max") == 0,
        "UNKNOWN submissions must be zero before promotion",
    )
    _require(
        _dict(budgets, "signed_intent_rpo").get("max") == 0,
        "signed intent RPO must be zero",
    )


def _validate_fault_injection(manifest: dict[str, Any]) -> None:
    cases = _object_list(manifest, "fault_injection")
    case_ids = {str(item.get("id")) for item in cases}
    missing = REQUIRED_FAULT_INJECTIONS - case_ids
    _require(not missing, f"missing fault injections: {sorted(missing)}")
    for item in cases:
        case_id = item.get("id")
        _require(isinstance(case_id, str) and bool(case_id), "fault id required")
        _require(
            item.get("required_before_promotion") is True,
            f"{case_id} must block promotion",
        )
        invariant = item.get("expected_invariant")
        _require(
            isinstance(invariant, str) and bool(invariant),
            f"{case_id} must document expected invariant",
        )


def _validate_backup_restore(manifest: dict[str, Any]) -> None:
    backup = _dict(manifest, "backup_restore")
    for key in (
        "online_backup_required",
        "wal_checkpoint_required",
        "restore_drill_required",
        "event_chain_verification_required",
        "corruption_drill_required",
    ):
        _require(backup.get(key) is True, f"backup/restore {key} must be true")


def _validate_rollback(manifest: dict[str, Any]) -> None:
    rollback = _dict(manifest, "rollback")
    _require(rollback.get("mode") == "drain-only", "rollback must be drain-only")
    _require(rollback.get("old_writer_allowed") is False, "old writer forbidden")
    for key in (
        "outstanding_signed_intents_must_be_zero",
        "unknown_attempts_must_be_zero",
        "database_remains_source_of_truth",
    ):
        _require(rollback.get(key) is True, f"rollback {key} must be true")


def _validate_legacy_surface(manifest: dict[str, Any]) -> None:
    legacy = _dict(manifest, "legacy_execution_surface")
    _require(
        legacy.get("source_only_live_paths_allowed_in_production_image") is False,
        "source-only live paths must be forbidden in the production image",
    )
    exclusions = _string_set(legacy, "production_image_must_exclude")
    missing = REQUIRED_PRODUCTION_EXCLUSIONS - exclusions
    _require(not missing, f"missing production exclusions: {sorted(missing)}")


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    missing_top_level = REQUIRED_TOP_LEVEL - set(manifest)
    _require(not missing_top_level, f"missing sections: {sorted(missing_top_level)}")
    _require(manifest["schema_version"] == SCHEMA_VERSION, "bad schema version")
    _require(
        manifest["promotion_state"] == "blocked_pending_evidence",
        "repository gate must stay blocked until evidence is materialized",
    )
    _require(
        manifest["live_trading_enabled"] is False,
        "PR-200 gate must not enable live trading by itself",
    )

    _validate_cutover_unit(manifest)
    blockers = _validate_release_artifacts(manifest)
    _validate_isolation(manifest)
    _validate_readiness(manifest)
    _validate_slo_budgets(manifest)
    _validate_fault_injection(manifest)
    _validate_backup_restore(manifest)
    _validate_rollback(manifest)
    _validate_legacy_surface(manifest)

    return {
        "accepted": True,
        "schema_version": SCHEMA_VERSION,
        "promotion_state": "blocked_pending_evidence",
        "live_trading_enabled": False,
        "release_artifact_count": len(REQUIRED_RELEASE_ARTIFACTS),
        "fault_injection_count": len(REQUIRED_FAULT_INJECTIONS),
        "promotion_blockers": sorted(blockers),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/production_cutover_manifest.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    evidence = validate_manifest(load_manifest(args.manifest))
    if args.json:
        print(json.dumps(evidence, sort_keys=True))
    else:
        print("PR-200 production cutover gate validated: promotion is blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
