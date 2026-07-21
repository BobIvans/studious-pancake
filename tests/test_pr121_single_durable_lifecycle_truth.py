from __future__ import annotations

import json

import pytest

from src.durability.single_truth import (
    PR121_READY_STATE,
    REQUIRED_BACKUP_FEATURES,
    REQUIRED_FAILURE_INJECTIONS,
    REQUIRED_OUTBOX_FEATURES,
    REQUIRED_RESTORE_FEATURES,
    REQUIRED_STATE_COMPONENTS,
    REQUIRED_TRANSACTION_BINDINGS,
    SingleTruthError,
    SingleTruthPackage,
    SingleTruthReadinessState,
    assert_single_durable_lifecycle_truth,
    evaluate_single_durable_lifecycle_truth,
)

HASHES = {
    "pr100_canonical_execution_evidence_sha256": "0123456789abcdef" * 4,
    "lifecycle_store_sha256": "abcdef0123456789" * 4,
    "outbox_schema_sha256": "00112233445566778899aabbccddeeff" * 2,
    "backup_restore_sha256": "ffeeddccbbaa99887766554433221100" * 2,
    "failure_corpus_sha256": "1234567890abcdef" * 4,
    "pr121_review_sha256": "fedcba0987654321" * 4,
}


def _package(**overrides: object) -> SingleTruthPackage:
    values: dict[str, object] = {
        "authoritative_store": "sqlite",
        "state_components": {name: True for name in REQUIRED_STATE_COMPONENTS},
        "transaction_bindings": {name: True for name in REQUIRED_TRANSACTION_BINDINGS},
        "outbox_features": {name: True for name in REQUIRED_OUTBOX_FEATURES},
        "backup_features": {name: True for name in REQUIRED_BACKUP_FEATURES},
        "restore_features": {name: True for name in REQUIRED_RESTORE_FEATURES},
        "failure_scenarios": {name: True for name in REQUIRED_FAILURE_INJECTIONS},
        "jsonl_authoritative": False,
        "legacy_shadow_store_authoritative": False,
        "process_lock_enforced": True,
        "process_epoch_recorded": True,
        "busy_retry_bounds": True,
        "thread_safety_reviewed": True,
        "outbox_lease_fencing_enforced": True,
        "outbox_retry_schedule_persisted": True,
        "outbox_dead_letter_reviewed": True,
        "outbox_poison_quarantine": True,
        "backup_destination_overwrite_atomic": True,
        "backup_manifest_signed": True,
        "backup_external_anchor_recorded": True,
        "retention_policy_reviewed": True,
        "concurrent_runner_tested": True,
        "recovery_replay_tested": True,
        "dirty_tail_jsonl_regression_tested": True,
        "human_reviewed": True,
        "live_execution_allowed": False,
        "paper_runtime_migration_enabled": False,
        **HASHES,
    }
    values.update(overrides)
    return SingleTruthPackage(**values)


def test_pr121_complete_package_is_review_ready_but_never_live() -> None:
    result = evaluate_single_durable_lifecycle_truth(_package())

    assert result.state is SingleTruthReadinessState.REVIEW_READY
    assert result.state.value == PR121_READY_STATE
    assert result.review_ready is True
    assert result.live_execution_allowed is False
    assert result.paper_runtime_migration_enabled is False
    assert result.blockers == ()
    assert result.metrics_summary["authoritative_store"] == "sqlite"


def test_pr121_jsonl_or_legacy_authority_blocks_single_truth() -> None:
    result = evaluate_single_durable_lifecycle_truth(
        _package(jsonl_authoritative=True, legacy_shadow_store_authoritative=True)
    )

    assert "JSONL_STILL_AUTHORITATIVE" in result.blockers
    assert "LEGACY_SHADOW_STORE_STILL_AUTHORITATIVE" in result.blockers


def test_pr121_requires_atomic_transaction_bindings() -> None:
    bindings = {name: True for name in REQUIRED_TRANSACTION_BINDINGS}
    bindings["reservation_update"] = False

    result = evaluate_single_durable_lifecycle_truth(
        _package(transaction_bindings=bindings)
    )

    assert "TRANSACTION_BINDING_MISSING:reservation_update" in result.blockers


def test_pr121_outbox_must_have_failure_lifecycle() -> None:
    features = {name: True for name in REQUIRED_OUTBOX_FEATURES}
    features["dead_letter"] = False
    features["reschedule"] = False
    result = evaluate_single_durable_lifecycle_truth(
        _package(
            outbox_features=features,
            outbox_retry_schedule_persisted=False,
            outbox_dead_letter_reviewed=False,
        )
    )

    assert "OUTBOX_FEATURE_MISSING:dead_letter" in result.blockers
    assert "OUTBOX_FEATURE_MISSING:reschedule" in result.blockers
    assert "OUTBOX_RETRY_SCHEDULE_NOT_PERSISTED" in result.blockers
    assert "OUTBOX_DEAD_LETTER_REVIEW_MISSING" in result.blockers


def test_pr121_backup_restore_must_be_atomic_and_validated() -> None:
    backup = {name: True for name in REQUIRED_BACKUP_FEATURES}
    restore = {name: True for name in REQUIRED_RESTORE_FEATURES}
    backup["atomic_rename"] = False
    restore["validate_before_overwrite"] = False
    result = evaluate_single_durable_lifecycle_truth(
        _package(
            backup_features=backup,
            restore_features=restore,
            backup_destination_overwrite_atomic=False,
            backup_manifest_signed=False,
            backup_external_anchor_recorded=False,
        )
    )

    assert "BACKUP_FEATURE_MISSING:atomic_rename" in result.blockers
    assert "RESTORE_FEATURE_MISSING:validate_before_overwrite" in result.blockers
    assert "BACKUP_DESTINATION_NOT_ATOMIC" in result.blockers
    assert "BACKUP_MANIFEST_NOT_SIGNED" in result.blockers
    assert "BACKUP_EXTERNAL_ANCHOR_MISSING" in result.blockers


def test_pr121_failure_injection_and_jsonl_tail_regression_are_required() -> None:
    scenarios = {name: True for name in REQUIRED_FAILURE_INJECTIONS}
    scenarios["poison_outbox_item"] = False
    result = evaluate_single_durable_lifecycle_truth(
        _package(
            failure_scenarios=scenarios,
            concurrent_runner_tested=False,
            recovery_replay_tested=False,
            dirty_tail_jsonl_regression_tested=False,
        )
    )

    assert "FAILURE_INJECTION_MISSING:poison_outbox_item" in result.blockers
    assert "CONCURRENT_RUNNER_NOT_TESTED" in result.blockers
    assert "RECOVERY_REPLAY_NOT_TESTED" in result.blockers
    assert "DIRTY_TAIL_JSONL_REGRESSION_NOT_TESTED" in result.blockers


def test_pr121_live_or_runtime_migration_enable_blocks_review_gate() -> None:
    result = evaluate_single_durable_lifecycle_truth(
        _package(live_execution_allowed=True, paper_runtime_migration_enabled=True)
    )

    assert "LIVE_EXECUTION_ALLOWED" in result.blockers
    assert "PAPER_RUNTIME_MIGRATION_ENABLED_IN_REVIEW_GATE" in result.blockers
    assert result.live_execution_allowed is False
    assert result.paper_runtime_migration_enabled is False


def test_pr121_assertion_uses_stable_fail_closed_prefix() -> None:
    with pytest.raises(SingleTruthError) as exc_info:
        assert_single_durable_lifecycle_truth(
            _package(authoritative_store="jsonl", jsonl_authoritative=True)
        )

    assert str(exc_info.value).startswith("PR121_SINGLE_TRUTH_BLOCKED:")


def test_pr121_result_is_stable_json_serialisable() -> None:
    result = evaluate_single_durable_lifecycle_truth(_package())
    encoded = json.dumps(result.to_dict(), sort_keys=True)

    assert "single-durable-lifecycle-truth-review-ready" in encoded
    assert "package_sha256" in encoded


def test_pr121_rejects_placeholder_evidence_hashes() -> None:
    with pytest.raises(SingleTruthError, match="non-placeholder sha256"):
        _package(pr121_review_sha256="0" * 64)
