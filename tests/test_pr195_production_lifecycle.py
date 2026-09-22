from __future__ import annotations

import copy

import pytest

from src.production_lifecycle_pr195 import (
    PR195LifecycleError,
    PR195_SCHEMA_VERSION,
    live_capability_allowed,
    sender_capability_allowed,
    signer_capability_allowed,
    validate_durable_lifecycle_evidence,
)

_DIGEST = "a" * 64
_OTHER_DIGEST = "b" * 64


def _fault_drills() -> list[dict[str, str]]:
    scenarios = [
        "kill_9_after_state_before_event",
        "kill_9_after_event_before_projection",
        "two_process_duplicate_opportunity",
        "stale_fencing_token_commit",
        "disk_full_admission_latch",
        "read_only_db_admission_latch",
        "corrupt_wal_startup_refusal",
        "backup_restore_chain_hash",
    ]
    return [
        {
            "scenario": scenario,
            "result": "passed",
            "evidence_hash": _DIGEST,
        }
        for scenario in scenarios
    ]


def _evidence() -> dict[str, object]:
    return {
        "schema_version": PR195_SCHEMA_VERSION,
        "release_hash": _DIGEST,
        "authorities": [
            {
                "name": "canonical-lifecycle",
                "role": "canonical_lifecycle",
                "storage": "sqlite-wal",
                "write_enabled": True,
                "production_surface": True,
            },
            {
                "name": "legacy-jsonl-reader",
                "role": "legacy_reader",
                "storage": "jsonl-archive",
                "write_enabled": False,
                "production_surface": False,
            },
        ],
        "database": {
            "engine": "sqlite-wal",
            "schema_fingerprint": _OTHER_DIGEST,
            "forward_only_migrations": True,
            "unknown_schema_blocks_startup": True,
            "begin_immediate_required": True,
            "fsync_on_commit": True,
            "busy_timeout_ms": 5000,
            "shared_connection_serialized": True,
            "disk_full_latch_enabled": True,
            "corruption_latch_enabled": True,
        },
        "state_machine": {
            "single_append_transition_primitive": True,
            "revision_unique": True,
            "event_id_unique": True,
            "event_chain_hash": _DIGEST,
            "materialized_projection_replay_verified": True,
            "terminal_states_are_irreversible": True,
            "partial_transition_impossible": True,
        },
        "idempotency": {
            "durable_unique_keys": True,
            "retention_days": 7,
            "expiry_releases_pending": True,
            "terminal_compaction_bounded": True,
            "duplicate_policy": "same-outcome-idempotent",
            "pending_release_is_atomic_with_queue_expiry": True,
        },
        "leases": {
            "monotonic_time_domain": True,
            "fencing_tokens": True,
            "cas_renewal": True,
            "stale_owner_rejected": True,
            "side_effects_require_fence": True,
        },
        "capital": {
            "wallet_revision_fencing": True,
            "aggregate_balance_constraint": True,
            "attempt_and_reservation_atomic": True,
            "negative_headroom_latches": True,
            "deterministic_or_unique_reservation_ids": True,
            "recovery_snapshot_is_single_transaction": True,
        },
        "outbox": {
            "durable_before_ack": True,
            "claim_fenced": True,
            "nack_supported": True,
            "max_attempts": 5,
            "dlq_supported": True,
            "poison_event_alerts": True,
        },
        "restore": {
            "validates_temp_sibling_before_replace": True,
            "previous_generation_preserved": True,
            "authenticated_backup_manifest_required": True,
            "restored_chain_hash_matches": True,
            "open_database_overwrite_forbidden": True,
        },
        "fault_drills": _fault_drills(),
        "live_enabled": False,
        "signer_enabled": False,
        "sender_enabled": False,
    }


def _codes(report) -> set[str]:
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_pr195_accepts_complete_durable_lifecycle_evidence() -> None:
    report = validate_durable_lifecycle_evidence(_evidence())

    assert report.ok is True
    assert report.diagnostics == ()
    assert len(report.evidence_hash) == 64
    assert live_capability_allowed() is False
    assert signer_capability_allowed() is False
    assert sender_capability_allowed() is False


def test_pr195_rejects_multiple_or_noncanonical_writers() -> None:
    evidence = _evidence()
    authorities = copy.deepcopy(evidence["authorities"])
    authorities.append(
        {
            "name": "shadow-writer",
            "role": "legacy_reader",
            "storage": "sqlite-wal",
            "write_enabled": True,
            "production_surface": True,
        }
    )
    authorities.append(
        {
            "name": "second-canonical",
            "role": "canonical_lifecycle",
            "storage": "sqlite-wal",
            "write_enabled": True,
            "production_surface": True,
        }
    )
    evidence["authorities"] = authorities

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "CANONICAL_WRITER_COUNT_INVALID" in _codes(report)
    assert "NON_CANONICAL_WRITER" in _codes(report)


def test_pr195_rejects_jsonl_authority_and_test_fixture_surface() -> None:
    evidence = _evidence()
    evidence["authorities"] = [
        {
            "name": "jsonl-authority",
            "role": "canonical_lifecycle",
            "storage": "jsonl",
            "write_enabled": True,
            "production_surface": True,
        },
        {
            "name": "memory-fixture",
            "role": "test_fixture",
            "storage": "memory",
            "write_enabled": False,
            "production_surface": True,
        },
    ]

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "JSONL_AUTHORITY_WRITE_ENABLED" in _codes(report)
    assert "TEST_FIXTURE_ON_PRODUCTION_SURFACE" in _codes(report)


def test_pr195_rejects_unsafe_database_contract() -> None:
    evidence = _evidence()
    evidence["database"] = {
        "engine": "sqlite",
        "schema_fingerprint": _DIGEST,
        "forward_only_migrations": False,
        "unknown_schema_blocks_startup": False,
        "begin_immediate_required": False,
        "fsync_on_commit": False,
        "busy_timeout_ms": 0,
        "shared_connection_serialized": False,
        "disk_full_latch_enabled": False,
        "corruption_latch_enabled": False,
    }

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "UNSUPPORTED_LIFECYCLE_ENGINE" in _codes(report)
    assert "MIGRATIONS_NOT_FORWARD_ONLY" in _codes(report)
    assert "FSYNC_POLICY_MISSING" in _codes(report)
    assert "SHARED_CONNECTION_NOT_SERIALIZED" in _codes(report)
    assert "DISK_FULL_LATCH_MISSING" in _codes(report)


def test_pr195_rejects_queue_expiry_without_pending_release() -> None:
    evidence = _evidence()
    idempotency = copy.deepcopy(evidence["idempotency"])
    idempotency["expiry_releases_pending"] = False
    idempotency["terminal_compaction_bounded"] = False
    idempotency["pending_release_is_atomic_with_queue_expiry"] = False
    evidence["idempotency"] = idempotency

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "EXPIRY_DOES_NOT_RELEASE_PENDING" in _codes(report)
    assert "TERMINAL_DEDUPE_UNBOUNDED" in _codes(report)
    assert "EXPIRY_NOT_ATOMIC_WITH_QUEUE" in _codes(report)


def test_pr195_rejects_unfenced_leases_and_capital_reservations() -> None:
    evidence = _evidence()
    leases = copy.deepcopy(evidence["leases"])
    leases["fencing_tokens"] = False
    leases["stale_owner_rejected"] = False
    evidence["leases"] = leases
    capital = copy.deepcopy(evidence["capital"])
    capital["aggregate_balance_constraint"] = False
    capital["attempt_and_reservation_atomic"] = False
    capital["negative_headroom_latches"] = False
    evidence["capital"] = capital

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "FENCING_TOKEN_MISSING" in _codes(report)
    assert "STALE_OWNER_NOT_REJECTED" in _codes(report)
    assert "AGGREGATE_BALANCE_CONSTRAINT_MISSING" in _codes(report)
    assert "RESERVATION_NOT_ATOMIC_WITH_ATTEMPT" in _codes(report)
    assert "NEGATIVE_HEADROOM_NOT_LATCHED" in _codes(report)


def test_pr195_rejects_outbox_without_ack_durability_or_dlq() -> None:
    evidence = _evidence()
    outbox = copy.deepcopy(evidence["outbox"])
    outbox["durable_before_ack"] = False
    outbox["nack_supported"] = False
    outbox["max_attempts"] = 0
    outbox["dlq_supported"] = False
    evidence["outbox"] = outbox

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "ACK_BEFORE_DURABLE_COMMIT" in _codes(report)
    assert "OUTBOX_NACK_MISSING" in _codes(report)
    assert "OUTBOX_MAX_ATTEMPTS_INVALID" in _codes(report)
    assert "OUTBOX_DLQ_MISSING" in _codes(report)


def test_pr195_rejects_restore_that_can_destroy_existing_db() -> None:
    evidence = _evidence()
    restore = copy.deepcopy(evidence["restore"])
    restore["validates_temp_sibling_before_replace"] = False
    restore["previous_generation_preserved"] = False
    restore["open_database_overwrite_forbidden"] = False
    evidence["restore"] = restore

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "RESTORE_NOT_TEMP_VALIDATED" in _codes(report)
    assert "RESTORE_DESTROYS_PREVIOUS_GENERATION" in _codes(report)
    assert "OPEN_DB_OVERWRITE_ALLOWED" in _codes(report)


def test_pr195_rejects_missing_or_failed_fault_drills() -> None:
    evidence = _evidence()
    drills = _fault_drills()
    drills = [item for item in drills if item["scenario"] != "backup_restore_chain_hash"]
    drills[0]["result"] = "failed"
    evidence["fault_drills"] = drills

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "FAULT_DRILL_NOT_PASSED" in _codes(report)
    assert "FAULT_DRILL_MISSING" in _codes(report)


def test_pr195_rejects_live_signer_sender_enablement() -> None:
    evidence = _evidence()
    evidence["live_enabled"] = True
    evidence["signer_enabled"] = True
    evidence["sender_enabled"] = True

    report = validate_durable_lifecycle_evidence(evidence)

    assert report.ok is False
    assert "LIVE_ENABLED_IN_PR195" in _codes(report)
    assert "SIGNER_ENABLED_IN_PR195" in _codes(report)
    assert "SENDER_ENABLED_IN_PR195" in _codes(report)


def test_pr195_rejects_invalid_schema_and_hash_shape() -> None:
    evidence = _evidence()
    evidence["schema_version"] = "wrong"

    with pytest.raises(PR195LifecycleError, match="unsupported"):
        validate_durable_lifecycle_evidence(evidence)

    evidence = _evidence()
    evidence["release_hash"] = "not-a-hash"
    with pytest.raises(PR195LifecycleError, match="sha256"):
        validate_durable_lifecycle_evidence(evidence)
