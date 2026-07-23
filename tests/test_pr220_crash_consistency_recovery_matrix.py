from __future__ import annotations

from dataclasses import replace

from src.pr220_crash_consistency_recovery_matrix import (
    REQUIRED_CRASH_POINTS,
    REQUIRED_OUTBOX_TRANSITIONS,
    REQUIRED_RACE_SCENARIOS,
    REQUIRED_RECOVERY_SCENARIOS,
    REQUIRED_SAFETY_BOUNDARIES,
    AsyncDurabilityEvidence,
    BackupRestoreEvidence,
    IdempotencyLeaseEvidence,
    OutboxRecoveryEvidence,
    PR220CrashRecoveryEvidence,
    PR220GateState,
    StateReplayEvidence,
    TransactionAtomicityEvidence,
    TrustedTimeEvidence,
    evaluate_pr220_crash_recovery_evidence,
)

HASH = "b" * 64


def valid_evidence() -> PR220CrashRecoveryEvidence:
    return PR220CrashRecoveryEvidence(
        prior_pr220_gate_accepted=True,
        prior_pr220_gate_evidence_hash=HASH,
        release_generation_hash=HASH,
        transaction_atomicity=TransactionAtomicityEvidence(
            explicit_begin_immediate_or_serializable_writer=True,
            no_autocommit_multi_statement_paths=True,
            single_writer_authority=True,
            rowcount_checked_for_all_cas=True,
            committed_row_reread_before_external_effect=True,
            bool_float_nan_identity_rejected=True,
            canonical_length_prefixed_identity_hash=HASH,
            statement_level_crash_points=REQUIRED_CRASH_POINTS,
        ),
        state_replay=StateReplayEvidence(
            append_only_event_log_authoritative=True,
            recovery_never_mutates_state_without_event=True,
            terminal_states_immutable=True,
            rejected_is_terminal_with_policy=True,
            payload_digest_recomputed_from_stored_payload=True,
            hash_chain_verified=True,
            replay_reconstructs_materialized_tables=True,
            manual_tamper_detected=True,
            replay_equality_report_hash=HASH,
        ),
        idempotency_leases=IdempotencyLeaseEvidence(
            idempotency_namespace_bound=True,
            request_digest_bound_to_attempt_wallet_generation=True,
            conflicting_replay_returns_typed_conflict=True,
            process_boot_identity_persisted=True,
            non_stealable_lease=True,
            non_expired_fence_required_on_write=True,
            stale_owner_write_rejected=True,
            race_scenarios_passed=REQUIRED_RACE_SCENARIOS,
        ),
        trusted_time=TrustedTimeEvidence(
            portable_wall_epoch_deadlines=True,
            no_persisted_monotonic_reuse_across_boot=True,
            monotonic_duration_only_inside_process=True,
            maximum_ttl_revalidated=True,
            future_issued_authorization_rejected=True,
            reboot_time_jump_scenarios_passed=("reboot_time_jump_deadline_expiry",),
        ),
        outbox_recovery=OutboxRecoveryEvidence(
            durable_outbox_fsm=True,
            renewable_claim_lease=True,
            claim_fencing_token_required=True,
            retry_history_persisted=True,
            poison_messages_dead_lettered=True,
            operator_redrive_audited=True,
            unknown_has_durable_reconciliation_owner=True,
            callback_timeout_not_cancellation_proof=True,
            transitions_proven=REQUIRED_OUTBOX_TRANSITIONS,
        ),
        backup_restore=BackupRestoreEvidence(
            sqlite_backup_api_or_equivalent_online_safe_copy=True,
            wal_shm_handled=True,
            staged_generation_directory=True,
            manifest_published_atomically=True,
            directory_fsync_barrier=True,
            process_wide_quiescence_proven=True,
            semantic_replay_verified_before_pointer_swap=True,
            n_minus_one_generation_retained_for_rollback=True,
            restore_failure_boundaries_passed=(
                "stale_wal_restore",
                "torn_backup_manifest",
                "restore_pointer_swap_before_replay_verification",
            ),
            disaster_recovery_transcript_hash=HASH,
        ),
        async_durability=AsyncDurabilityEvidence(
            sqlite_file_io_outside_event_loop=True,
            bounded_writer_queue=True,
            writer_failure_closes_readiness=True,
            event_loop_lag_budget_ms=50,
            measured_max_event_loop_lag_ms=12,
            blocking_callback_deadline_enforced=True,
            callback_result_bound_to_operation_id_and_payload_hash=True,
        ),
        recovery_scenarios_passed=REQUIRED_RECOVERY_SCENARIOS,
        safety_boundaries=REQUIRED_SAFETY_BOUNDARIES,
    )


def violation_codes(report) -> set[str]:
    return {violation.code for violation in report.violations}


def test_complete_pr220_crash_matrix_qualifies_but_never_live() -> None:
    report = evaluate_pr220_crash_recovery_evidence(valid_evidence())

    assert report.state is PR220GateState.QUALIFIED
    assert report.durable_control_plane_qualified is True
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.private_key_material_allowed is False
    assert report.evidence_hash


def test_missing_prior_pr220_gate_blocks_follow_up_claim() -> None:
    evidence = replace(valid_evidence(), prior_pr220_gate_accepted=False)

    report = evaluate_pr220_crash_recovery_evidence(evidence)

    assert report.state is PR220GateState.BLOCKED
    assert "PR220_BASE_GATE_NOT_ACCEPTED" in violation_codes(report)


def test_autocommit_and_missing_crash_point_block_atomicity() -> None:
    atomicity = replace(
        valid_evidence().transaction_atomicity,
        no_autocommit_multi_statement_paths=False,
        statement_level_crash_points=REQUIRED_CRASH_POINTS[:-1],
    )
    evidence = replace(valid_evidence(), transaction_atomicity=atomicity)

    report = evaluate_pr220_crash_recovery_evidence(evidence)

    assert "AUTOCOMMIT_PATH_PRESENT" in violation_codes(report)
    assert "CRASH_POINT_MISSING" in violation_codes(report)


def test_replay_without_tamper_detection_or_hash_chain_blocks_recovery_truth() -> None:
    replay = replace(
        valid_evidence().state_replay,
        hash_chain_verified=False,
        manual_tamper_detected=False,
    )

    report = evaluate_pr220_crash_recovery_evidence(
        replace(valid_evidence(), state_replay=replay)
    )

    assert "HASH_CHAIN_NOT_VERIFIED" in violation_codes(report)
    assert "MANUAL_TAMPER_NOT_DETECTED" in violation_codes(report)


def test_semantic_idempotency_conflict_and_stale_owner_are_required() -> None:
    leases = replace(
        valid_evidence().idempotency_leases,
        conflicting_replay_returns_typed_conflict=False,
        stale_owner_write_rejected=False,
        race_scenarios_passed=REQUIRED_RACE_SCENARIOS[:-1],
    )

    report = evaluate_pr220_crash_recovery_evidence(
        replace(valid_evidence(), idempotency_leases=leases)
    )

    codes = violation_codes(report)
    assert "IDEMPOTENCY_CONFLICT_MASKED" in codes
    assert "STALE_OWNER_WRITE_ACCEPTED" in codes
    assert "RACE_SCENARIO_MISSING" in codes


def test_persisted_monotonic_deadline_reuse_is_blocked() -> None:
    trusted_time = replace(
        valid_evidence().trusted_time,
        no_persisted_monotonic_reuse_across_boot=False,
        reboot_time_jump_scenarios_passed=(),
    )

    report = evaluate_pr220_crash_recovery_evidence(
        replace(valid_evidence(), trusted_time=trusted_time)
    )

    assert "PERSISTED_MONOTONIC_REUSED" in violation_codes(report)
    assert "REBOOT_TIME_JUMP_SCENARIO_MISSING" in violation_codes(report)


def test_outbox_without_dlq_or_unknown_owner_is_not_qualified() -> None:
    outbox = replace(
        valid_evidence().outbox_recovery,
        poison_messages_dead_lettered=False,
        unknown_has_durable_reconciliation_owner=False,
        transitions_proven=REQUIRED_OUTBOX_TRANSITIONS[:-1],
    )

    report = evaluate_pr220_crash_recovery_evidence(
        replace(valid_evidence(), outbox_recovery=outbox)
    )

    codes = violation_codes(report)
    assert "POISON_NOT_DEAD_LETTERED" in codes
    assert "UNKNOWN_RECONCILIATION_OWNER_MISSING" in codes
    assert "OUTBOX_TRANSITION_MISSING" in codes


def test_restore_pointer_swap_requires_semantic_replay_and_rollback_generation() -> None:
    backup = replace(
        valid_evidence().backup_restore,
        semantic_replay_verified_before_pointer_swap=False,
        n_minus_one_generation_retained_for_rollback=False,
        restore_failure_boundaries_passed=("stale_wal_restore",),
    )

    report = evaluate_pr220_crash_recovery_evidence(
        replace(valid_evidence(), backup_restore=backup)
    )

    codes = violation_codes(report)
    assert "RESTORE_POINTER_SWAP_BEFORE_REPLAY" in codes
    assert "ROLLBACK_GENERATION_MISSING" in codes
    assert "RESTORE_FAILURE_BOUNDARY_MISSING" in codes


def test_event_loop_lag_budget_and_writer_readiness_are_enforced() -> None:
    async_evidence = replace(
        valid_evidence().async_durability,
        writer_failure_closes_readiness=False,
        measured_max_event_loop_lag_ms=60,
    )

    report = evaluate_pr220_crash_recovery_evidence(
        replace(valid_evidence(), async_durability=async_evidence)
    )

    codes = violation_codes(report)
    assert "WRITER_FAILURE_DOES_NOT_CLOSE_READINESS" in codes
    assert "EVENT_LOOP_LAG_BUDGET_EXCEEDED" in codes


def test_missing_safety_boundary_keeps_live_disabled_and_blocks_report() -> None:
    evidence = replace(
        valid_evidence(),
        safety_boundaries=REQUIRED_SAFETY_BOUNDARIES[:-1],
    )

    report = evaluate_pr220_crash_recovery_evidence(evidence)

    assert "SAFETY_BOUNDARY_MISSING" in violation_codes(report)
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.private_key_material_allowed is False
