from __future__ import annotations

from dataclasses import replace

from src.durability.mpr02_unified_authority_gate import (
    MPR02AuthorityEvidence,
    MPR02GateState,
    evaluate_mpr02_authority,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def good_evidence() -> MPR02AuthorityEvidence:
    return MPR02AuthorityEvidence(
        release_id="mpr02-release-001",
        database_identity_hash=DIGEST_A,
        schema_fingerprint=DIGEST_B,
        one_transactional_authority=True,
        renewable_leases=True,
        claim_generation_monotonic=True,
        fence_checked_before_side_effect=True,
        owner_boot_epoch_bound=True,
        stale_owner_rejected=True,
        heartbeat_timeout_ms=5_000,
        lease_ttl_ms=60_000,
        worst_case_protected_section_ms=30_000,
        outbox_states=("PENDING", "CLAIMED", "PUBLISHED", "DLQ"),
        outbox_claim_has_owner=True,
        outbox_claim_has_deadline=True,
        expired_outbox_claim_reclaimed=True,
        outbox_publish_idempotent=True,
        outbox_dlq_after_bounded_attempts=True,
        recovery_scans_claimed_and_pending=True,
        wallet_scope_serializable=True,
        reservation_cas_revision=True,
        double_reservation_race_rejected=True,
        failed_attempt_releases_or_settles_fee=True,
        aggregate_reserved_lamports=400,
        wallet_available_lamports=1_000,
        minimum_required_available_lamports=500,
        append_only_events=True,
        prev_hash_chain=True,
        event_sequence_unique=True,
        materialized_state_rebuilds_from_events=True,
        domain_integrity_checks=(
            "attempts",
            "capital",
            "leases",
            "outbox",
            "terminal_hash",
        ),
        replay_hash=DIGEST_C,
        atomic_backup_bundle=True,
        backup_manifest_bound_to_db_wal=True,
        backup_files_and_directory_fsynced=True,
        staged_restore_handles_wal_shm=True,
        previous_generation_preserved_on_failure=True,
        post_restore_semantic_replay=True,
        structured_concurrency=True,
        cancellation_safe_terminal_state=True,
        readiness_unready_before_cancel=True,
        no_owned_tasks_after_shutdown=True,
        timeout_cause_preserved=True,
        max_shutdown_ms=30_000,
        recovery_probes=(
            "crash_after_attempt_insert",
            "crash_after_capital_reservation",
            "crash_after_lease_claim",
            "crash_after_outbox_claim",
            "crash_after_backup_replace",
            "crash_during_restore",
            "timeout_after_lease_expiry",
        ),
    )


def test_mpr02_accepts_complete_sender_free_durable_authority() -> None:
    report = evaluate_mpr02_authority(good_evidence())

    assert report.ready is True
    assert report.state is MPR02GateState.READY_FOR_DURABLE_RUNTIME_INTEGRATION
    assert report.violations == ()
    assert report.to_dict()["safety_boundary"] == {
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_allowed": False,
    }


def test_mpr02_rejects_outbox_claim_without_recovery_lease() -> None:
    report = evaluate_mpr02_authority(
        replace(
            good_evidence(),
            outbox_states=("PENDING", "CLAIMED", "PUBLISHED"),
            outbox_claim_has_deadline=False,
            expired_outbox_claim_reclaimed=False,
            recovery_scans_claimed_and_pending=False,
        )
    )

    assert report.ready is False
    assert {violation.code for violation in report.violations} >= {
        "missing_outbox_state",
        "outbox_incomplete",
    }


def test_mpr02_rejects_lease_ttl_that_cannot_protect_cycle() -> None:
    report = evaluate_mpr02_authority(
        replace(
            good_evidence(),
            lease_ttl_ms=30_000,
            worst_case_protected_section_ms=30_000,
        )
    )

    assert [violation.code for violation in report.violations] == [
        "lease_ttl_too_short"
    ]


def test_mpr02_rejects_wallet_over_reservation() -> None:
    report = evaluate_mpr02_authority(
        replace(good_evidence(), aggregate_reserved_lamports=800)
    )

    assert report.ready is False
    assert report.violations[0].code == "capital_over_reserved"


def test_mpr02_rejects_missing_event_hash_chain_and_integrity() -> None:
    report = evaluate_mpr02_authority(
        replace(
            good_evidence(),
            prev_hash_chain=False,
            domain_integrity_checks=("attempts", "capital"),
        )
    )

    assert report.ready is False
    assert {violation.code for violation in report.violations} >= {
        "event_history_incomplete",
        "missing_domain_integrity_check",
    }


def test_mpr02_rejects_non_atomic_restore_and_stale_wal_risk() -> None:
    report = evaluate_mpr02_authority(
        replace(
            good_evidence(),
            atomic_backup_bundle=False,
            staged_restore_handles_wal_shm=False,
            previous_generation_preserved_on_failure=False,
        )
    )

    assert report.ready is False
    assert {violation.code for violation in report.violations} == {
        "backup_restore_incomplete"
    }


def test_mpr02_rejects_cancellation_without_terminalization() -> None:
    report = evaluate_mpr02_authority(
        replace(
            good_evidence(),
            cancellation_safe_terminal_state=False,
            no_owned_tasks_after_shutdown=False,
            max_shutdown_ms=120_000,
        )
    )

    assert report.ready is False
    assert {violation.code for violation in report.violations} >= {
        "cancellation_incomplete",
        "shutdown_deadline_too_large",
    }


def test_mpr02_rejects_missing_fault_injection_probe() -> None:
    report = evaluate_mpr02_authority(
        replace(good_evidence(), recovery_probes=("crash_after_attempt_insert",))
    )

    assert report.ready is False
    assert {violation.code for violation in report.violations} == {
        "missing_recovery_probe"
    }


def test_mpr02_rejects_live_signer_or_sender_boundary() -> None:
    report = evaluate_mpr02_authority(
        replace(
            good_evidence(),
            live_execution_allowed=True,
            signer_allowed=True,
            sender_allowed=True,
        )
    )

    assert report.ready is False
    assert [violation.code for violation in report.violations] == [
        "live_enabled",
        "sender_enabled",
        "signer_enabled",
    ]
