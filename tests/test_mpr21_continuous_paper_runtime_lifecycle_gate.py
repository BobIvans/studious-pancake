from __future__ import annotations

from dataclasses import replace

from src.mpr21_continuous_paper_runtime_lifecycle_gate import (
    REQUIRED_CARRY_FORWARD_FINDINGS,
    REQUIRED_FAULT_SCENARIOS,
    REQUIRED_NEW_FINDINGS,
    BoundedRetentionEvidence,
    MPR21Evidence,
    MPR21GateState,
    MPR21RuntimeMode,
    QueueLifecycleEvidence,
    ShutdownEvidence,
    StructuredConcurrencyEvidence,
    TimingReadinessEvidence,
    evaluate_mpr21_evidence,
)

HASH = "a" * 64


def valid_evidence() -> MPR21Evidence:
    return MPR21Evidence(
        mpr18_accepted=True,
        mpr18_evidence_hash=HASH,
        mpr19_accepted=True,
        mpr19_evidence_hash=HASH,
        findings_covered=REQUIRED_NEW_FINDINGS,
        carry_forward_findings_covered=REQUIRED_CARRY_FORWARD_FINDINGS,
        runtime_modes=(MPR21RuntimeMode.PAPER, MPR21RuntimeMode.SHADOW),
        installed_mpr18_composition_used=True,
        mpr19_authority_used=True,
        queue_lifecycle=QueueLifecycleEvidence(
            durable_attempt_authority=True,
            enqueue_claim_expire_complete_reject_single_fsm=True,
            queue_identity_bound_to_attempt=True,
            idempotency_key_bound_to_attempt_and_payload=True,
            atomic_expiry_terminalizes_or_releases=True,
            expiry_uses_async_lock=True,
            expired_item_reinsertion_proven=True,
            no_pending_leak_after_expiry=True,
            exactly_one_durable_outcome_per_item=True,
            result_committed_before_terminal_tracker=True,
            result_sink_failure_keeps_recoverable_nonterminal=True,
            independent_tracker_truth_removed=True,
        ),
        bounded_retention=BoundedRetentionEvidence(
            terminal_tracker_durable_bounded=True,
            result_sink_durable_bounded=True,
            supervisor_reports_durable_bounded=True,
            rejection_aggregation_bounded=True,
            cursor_pagination_deterministic=True,
            retention_policy_hash=HASH,
            max_terminal_records=10_000,
            max_result_records=10_000,
            max_supervisor_reports=1_000,
            measured_peak_memory_bytes=64 * 1024 * 1024,
            memory_budget_bytes=128 * 1024 * 1024,
        ),
        structured_concurrency=StructuredConcurrencyEvidence(
            mandatory_workers=("detector", "consumer", "durable_writer"),
            worker_generation_id="boot-1:generation-7",
            worker_crash_sets_unready=True,
            fatal_evidence_persisted=True,
            bounded_restart_backoff=True,
            restart_creates_new_generation=True,
            worker_death_not_masked_as_success=True,
            cleanup_errors_not_suppressed=True,
            incomplete_work_ids_persisted=True,
            durable_recovery_plan_persisted=True,
        ),
        shutdown=ShutdownEvidence(
            admission_closed_first=True,
            bounded_critical_commits=True,
            no_second_unbounded_drain=True,
            absolute_deadline_ms=30_000,
            measured_worst_case_shutdown_ms=12_000,
            hanging_handler_test_passed=True,
            full_queue_test_passed=True,
            slow_writer_test_passed=True,
            terminal_shutdown_outcome_persisted=True,
        ),
        timing_readiness=TimingReadinessEvidence(
            timing_fields_finite_positive=True,
            nan_infinity_rejected=True,
            future_causal_timestamp_rejected=True,
            ttl_uses_monotonic_clock_in_boot_domain=True,
            persisted_deadlines_use_utc_and_generation=True,
            wall_clock_rollback_cannot_make_ready=True,
            readiness_has_distinct_live_ready_paper_live_gate=True,
            readiness_requires_worker_generation=True,
            readiness_requires_queue_backlog_slo=True,
            readiness_requires_provider_root_freshness=True,
            readiness_requires_recent_durable_terminal_cycle=True,
            management_listener_not_sufficient=True,
            container_health_fails_when_worker_dead=True,
            latest_terminal_cycle_age_ms=5_000,
            max_terminal_cycle_age_ms=30_000,
        ),
        fault_scenarios_passed=REQUIRED_FAULT_SCENARIOS,
        workload_readiness_timeline_hash=HASH,
        transition_model_hash=HASH,
        memory_backpressure_profile_hash=HASH,
    )


def _codes(report):
    return {violation.code for violation in report.violations}


def test_valid_evidence_qualifies_but_never_enables_live_surface():
    report = evaluate_mpr21_evidence(valid_evidence())

    assert report.state is MPR21GateState.CONTINUOUS_SENDER_FREE_RUNTIME_QUALIFIED
    assert report.ready
    assert report.violations == ()
    assert not report.transaction_signer_allowed
    assert not report.sender_allowed
    assert not report.live_execution_allowed
    assert not report.private_key_material_allowed


def test_requires_mpr18_and_mpr19_dependencies():
    evidence = replace(valid_evidence(), mpr18_accepted=False, mpr19_accepted=False)

    report = evaluate_mpr21_evidence(evidence)

    assert report.state is MPR21GateState.BLOCKED
    assert {"MPR18_REQUIRED", "MPR19_REQUIRED"} <= _codes(report)


def test_missing_findings_and_modes_block_qualification():
    evidence = replace(
        valid_evidence(),
        findings_covered=REQUIRED_NEW_FINDINGS[:-1],
        carry_forward_findings_covered=REQUIRED_CARRY_FORWARD_FINDINGS[:-1],
        runtime_modes=(MPR21RuntimeMode.PAPER,),
    )

    report = evaluate_mpr21_evidence(evidence)

    assert report.missing_new_findings == (REQUIRED_NEW_FINDINGS[-1],)
    assert report.missing_carry_forward_findings == (REQUIRED_CARRY_FORWARD_FINDINGS[-1],)
    assert "MODE_COVERAGE" in _codes(report)


def test_queue_expiry_pending_leak_blocks_gate():
    q = replace(
        valid_evidence().queue_lifecycle,
        atomic_expiry_terminalizes_or_releases=False,
        no_pending_leak_after_expiry=False,
        result_sink_failure_keeps_recoverable_nonterminal=False,
    )
    evidence = replace(valid_evidence(), queue_lifecycle=q)

    report = evaluate_mpr21_evidence(evidence)

    assert "QUEUE_LIFECYCLE" in _codes(report)
    assert not report.ready


def test_unbounded_memory_or_retention_blocks_gate():
    retention = replace(
        valid_evidence().bounded_retention,
        terminal_tracker_durable_bounded=False,
        measured_peak_memory_bytes=129 * 1024 * 1024,
    )
    evidence = replace(valid_evidence(), bounded_retention=retention)

    report = evaluate_mpr21_evidence(evidence)

    assert {"BOUNDED_RETENTION", "MEMORY_BUDGET_EXCEEDED"} <= _codes(report)


def test_worker_death_cannot_look_successful_or_ready():
    concurrency = replace(
        valid_evidence().structured_concurrency,
        worker_crash_sets_unready=False,
        worker_death_not_masked_as_success=False,
        mandatory_workers=("detector",),
    )
    evidence = replace(valid_evidence(), structured_concurrency=concurrency)

    report = evaluate_mpr21_evidence(evidence)

    assert {"STRUCTURED_CONCURRENCY", "MISSING_MANDATORY_WORKERS"} <= _codes(report)


def test_shutdown_absolute_deadline_is_enforced():
    shutdown = replace(
        valid_evidence().shutdown,
        no_second_unbounded_drain=False,
        measured_worst_case_shutdown_ms=31_000,
    )
    evidence = replace(valid_evidence(), shutdown=shutdown)

    report = evaluate_mpr21_evidence(evidence)

    assert {"SHUTDOWN", "SHUTDOWN_DEADLINE_EXCEEDED"} <= _codes(report)


def test_readiness_rejects_nan_wall_clock_rollback_and_management_only_health():
    timing = replace(
        valid_evidence().timing_readiness,
        nan_infinity_rejected=False,
        wall_clock_rollback_cannot_make_ready=False,
        management_listener_not_sufficient=False,
        container_health_fails_when_worker_dead=False,
        latest_terminal_cycle_age_ms=60_000,
    )
    evidence = replace(valid_evidence(), timing_readiness=timing)

    report = evaluate_mpr21_evidence(evidence)

    assert {"TIMING_READINESS", "STALE_TERMINAL_CYCLE"} <= _codes(report)


def test_fault_matrix_and_live_surface_are_fail_closed():
    evidence = replace(
        valid_evidence(),
        fault_scenarios_passed=REQUIRED_FAULT_SCENARIOS[:-1],
        live_execution_requested=True,
        sender_requested=True,
        private_key_material_present=True,
    )

    report = evaluate_mpr21_evidence(evidence)

    assert {"MISSING_FAULT_SCENARIOS", "LIVE_SURFACE_FORBIDDEN"} <= _codes(report)
