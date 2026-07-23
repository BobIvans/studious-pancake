from __future__ import annotations

from dataclasses import replace

from src.pr220_durable_control_plane_recovery_gate import (
    REQUIRED_COMPONENT_HASHES,
    REQUIRED_FAULT_CASES,
    REQUIRED_FINDINGS,
    REQUIRED_GROUP_PROOFS,
    PR220Evidence,
    PR220GateState,
    evaluate_pr220_evidence,
)

HASH = "a" * 64


def _proofs(group: str) -> dict[str, bool]:
    return {key: True for key in REQUIRED_GROUP_PROOFS[group]}


def valid_evidence() -> PR220Evidence:
    return PR220Evidence(
        release_artifact_hash=HASH,
        control_plane_manifest_hash=HASH,
        findings_covered=REQUIRED_FINDINGS,
        component_hashes={key: HASH for key in REQUIRED_COMPONENT_HASHES},
        persistence_topology=_proofs("persistence_topology"),
        canonical_state_machine=_proofs("canonical_state_machine"),
        semantic_idempotency=_proofs("semantic_idempotency"),
        fencing_and_leases=_proofs("fencing_and_leases"),
        trusted_time=_proofs("trusted_time"),
        queues_reservations_outbox=_proofs("queues_reservations_outbox"),
        async_durability=_proofs("async_durability"),
        projection_archive_backup=_proofs("projection_archive_backup"),
        fault_cases_covered=REQUIRED_FAULT_CASES,
        accelerated_soak_hours=24,
        event_loop_lag_p99_ms=4.0,
        event_loop_lag_budget_ms=10.0,
        replay_mismatch_count=0,
        duplicate_terminal_count=0,
        double_side_effect_count=0,
        lost_reservation_count=0,
    )


def codes(report) -> set[str]:
    return {blocker.code for blocker in report.blockers}


def test_valid_evidence_qualifies_without_live_surface() -> None:
    report = evaluate_pr220_evidence(valid_evidence())

    assert report.state is PR220GateState.DURABLE_CONTROL_PLANE_QUALIFIED
    assert report.blockers == ()
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.private_key_material_allowed is False


def test_missing_findings_block_qualification() -> None:
    report = evaluate_pr220_evidence(
        replace(valid_evidence(), findings_covered=REQUIRED_FINDINGS[:-1])
    )

    assert "PR220_FINDINGS_INCOMPLETE" in codes(report)


def test_semantic_idempotency_conflict_must_not_replay_success() -> None:
    evidence = valid_evidence()
    group = dict(evidence.semantic_idempotency)
    group["canonical_request_digest_persisted"] = False
    group["conflicting_payload_returns_typed_conflict"] = False
    group["conflict_never_terminalizes_success"] = False

    report = evaluate_pr220_evidence(replace(evidence, semantic_idempotency=group))

    assert "PR220_SEMANTIC_IDEMPOTENCY_INCOMPLETE" in codes(report)


def test_stale_owner_and_stealable_lease_block_gate() -> None:
    evidence = valid_evidence()
    group = dict(evidence.fencing_and_leases)
    group["non_stealable_leases"] = False
    group["stale_owner_write_rejected"] = False
    group["fencing_token_required_on_every_write"] = False

    report = evaluate_pr220_evidence(replace(evidence, fencing_and_leases=group))

    assert "PR220_FENCING_AND_LEASES_INCOMPLETE" in codes(report)


def test_persisted_monotonic_deadlines_and_time_jump_block_gate() -> None:
    evidence = valid_evidence()
    group = dict(evidence.trusted_time)
    group["persisted_monotonic_deadlines_forbidden"] = False
    group["reboot_time_jump_does_not_extend_deadlines"] = False

    report = evaluate_pr220_evidence(replace(evidence, trusted_time=group))

    assert "PR220_TRUSTED_TIME_INCOMPLETE" in codes(report)


def test_missing_outbox_recovery_and_unknown_owner_blocks_gate() -> None:
    evidence = valid_evidence()
    group = dict(evidence.queues_reservations_outbox)
    group["outbox_claim_renew_ack_nack_retry_dlq_implemented"] = False
    group["unknown_has_durable_reconciliation_owner"] = False
    group["expiry_terminalizes_or_releases_lifecycle"] = False

    report = evaluate_pr220_evidence(replace(evidence, queues_reservations_outbox=group))

    assert "PR220_QUEUES_RESERVATIONS_OUTBOX_INCOMPLETE" in codes(report)


def test_event_loop_budget_and_fault_counters_are_fail_closed() -> None:
    report = evaluate_pr220_evidence(
        replace(
            valid_evidence(),
            event_loop_lag_p99_ms=15.0,
            event_loop_lag_budget_ms=10.0,
            duplicate_terminal_count=1,
            fault_cases_covered=REQUIRED_FAULT_CASES[:-1],
        )
    )

    assert "PR220_EVENT_LOOP_LAG_BUDGET_EXCEEDED" in codes(report)
    assert "PR220_FAULT_COUNTER_NONZERO" in codes(report)
    assert "PR220_FAULT_MATRIX_INCOMPLETE" in codes(report)


def test_backup_restore_and_live_requests_block_gate() -> None:
    evidence = valid_evidence()
    group = dict(evidence.projection_archive_backup)
    group["backup_manifest_published_atomically_with_fsync"] = False
    group["restore_requires_process_quiescence"] = False
    group["archive_remote_ack_append_only"] = False

    report = evaluate_pr220_evidence(
        replace(
            evidence,
            projection_archive_backup=group,
            live_execution_requested=True,
            signer_requested=True,
            sender_requested=True,
            private_key_material_present=True,
        )
    )

    assert "PR220_PROJECTION_ARCHIVE_BACKUP_INCOMPLETE" in codes(report)
    assert "PR220_LIVE_REQUESTED" in codes(report)
    assert "PR220_SIGNER_REQUESTED" in codes(report)
    assert "PR220_SENDER_REQUESTED" in codes(report)
    assert "PR220_PRIVATE_KEY_PRESENT" in codes(report)
