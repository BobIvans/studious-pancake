from __future__ import annotations

import pytest

from src.runtime_orchestration_pr142 import (
    CandidateRejectionPolicy,
    ComponentContract,
    ComponentCriticality,
    DatabaseActorEvidence,
    FaultInjectionEvidence,
    PR142RuntimeError,
    QueueTrackerEvidence,
    ResourceBounds,
    RuntimeOrchestrationEvidence,
    ShutdownProtocolEvidence,
    StageBudget,
    assert_pr142_runtime_orchestration_review_ready,
    evaluate_pr142_runtime_orchestration,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


STAGES = (
    "discovery",
    "exact_quote",
    "capital",
    "planning",
    "compile",
    "simulation",
    "reconciliation",
    "journal_export",
)
COMPONENTS = (
    "discovery_loop",
    "candidate_processor",
    "provider_clients",
    "lifecycle_writer",
    "observability_exporter",
    "health_readiness_server",
)
FAULTS = (
    "stage_hang",
    "child_task_crash",
    "cancellation_during_db_commit",
    "cancellation_during_provider_request",
    "queue_full",
    "tracker_expiration",
    "sigterm_during_stage",
    "second_runtime_process",
    "db_busy_locked",
    "event_loop_lag",
    "provider_swallowed_cancelled_error",
)
SHUTDOWN = (
    "stop_new_discovery",
    "stop_new_reservations",
    "preserve_ambiguous_submission",
    "drain_journal_outbox",
    "checkpoint",
    "close_clients",
    "readiness_false_before_exit",
)


def complete_evidence(**overrides):
    evidence = RuntimeOrchestrationEvidence(
        stage_budgets=tuple(
            StageBudget(
                stage_name=name,
                timeout_ms=2_000,
                cancellation_budget_ms=500,
                max_attempts=1,
                max_external_calls=3,
                lease_refresh_ms=1_000,
                terminal_reason=f"{name}_deadline",
            )
            for name in STAGES
        ),
        component_contracts=tuple(
            ComponentContract(
                component_name=name,
                criticality=ComponentCriticality.CRITICAL,
                owned_by_supervisor=True,
                failure_changes_readiness=True,
                exception_history_limit=32,
                restart_limit=1,
                cancellation_propagates=True,
            )
            for name in COMPONENTS
        ),
        resource_bounds=ResourceBounds(
            active_tasks_max=64,
            provider_requests_max=16,
            candidate_queue_max=1_000,
            evidence_blob_bytes_max=1_048_576,
            exception_history_max=128,
            log_records_max=10_000,
            cache_entries_max=50_000,
            pending_outbox_max=1_000,
            db_connections_max=4,
            file_descriptors_max=512,
        ),
        queue_tracker=QueueTrackerEvidence(
            queue_capacity=1_000,
            pending_ttl_ms=60_000,
            terminal_ttl_ms=3_600_000,
            terminal_retention_max=50_000,
            expired_items_release_pending=True,
            persistent_dedup_enabled=True,
            drop_reason_durable=True,
            backpressure_metrics=True,
        ),
        database_actor=DatabaseActorEvidence(
            dedicated_writer_actor=True,
            bounded_command_queue=True,
            command_queue_capacity=1_000,
            no_blocking_db_in_event_loop=True,
            explicit_reader_connections=True,
            process_lock_or_leader_lease=True,
            rejects_second_writer_process=True,
            topology_in_readiness=True,
            evidence_hash=HASH_A,
        ),
        shutdown_protocol=ShutdownProtocolEvidence(
            implemented_steps=SHUTDOWN,
            drain_timeout_ms=30_000,
            checkpoint_hash=HASH_B,
            cancellation_preserves_ambiguous_state=True,
            no_orphan_tasks_proven=True,
            cancelled_error_propagates=True,
        ),
        fault_injection=FaultInjectionEvidence(
            covered_faults=FAULTS,
            no_task_leak=True,
            no_queue_leak=True,
            no_file_descriptor_leak=True,
            readiness_changes_on_critical_task_death=True,
            evidence_hash=HASH_C,
        ),
        continuous_run_until_stopped=True,
        structured_concurrency=True,
        candidate_rejection_policy=CandidateRejectionPolicy.CONTINUE,
        stop_on_first_blocked_candidate_contract_enforced=True,
        policy_snapshot_hash=HASH_D,
        implementation_evidence_hash="e" * 64,
    )
    values = {
        "stage_budgets": evidence.stage_budgets,
        "component_contracts": evidence.component_contracts,
        "resource_bounds": evidence.resource_bounds,
        "queue_tracker": evidence.queue_tracker,
        "database_actor": evidence.database_actor,
        "shutdown_protocol": evidence.shutdown_protocol,
        "fault_injection": evidence.fault_injection,
        "continuous_run_until_stopped": evidence.continuous_run_until_stopped,
        "structured_concurrency": evidence.structured_concurrency,
        "candidate_rejection_policy": evidence.candidate_rejection_policy,
        "stop_on_first_blocked_candidate_contract_enforced": (
            evidence.stop_on_first_blocked_candidate_contract_enforced
        ),
        "policy_snapshot_hash": evidence.policy_snapshot_hash,
        "implementation_evidence_hash": evidence.implementation_evidence_hash,
        "unresolved_blockers": evidence.unresolved_blockers,
        "schema_version": evidence.schema_version,
    }
    values.update(overrides)
    return RuntimeOrchestrationEvidence(**values)


def test_complete_runtime_orchestration_is_review_ready():
    decision = evaluate_pr142_runtime_orchestration(complete_evidence())

    assert decision.review_ready is True
    assert decision.state == "structured-runtime-review-ready"
    assert decision.paper_runtime_claim_allowed is False
    assert decision.live_claim_allowed is False
    assert decision.blockers == ()
    assert decision.metrics["stage_count"] == len(STAGES)
    assert len(decision.evidence_hash) == 64


def test_missing_stage_budget_blocks_deadline_claim():
    evidence = complete_evidence(
        stage_budgets=tuple(
            StageBudget(
                stage_name=name,
                timeout_ms=2_000,
                cancellation_budget_ms=500,
                max_attempts=1,
                max_external_calls=3,
                lease_refresh_ms=1_000,
                terminal_reason=f"{name}_deadline",
            )
            for name in STAGES
            if name != "simulation"
        )
    )

    decision = evaluate_pr142_runtime_orchestration(evidence)

    assert "MISSING_STAGE_BUDGET:simulation" in decision.blockers


def test_one_shot_run_until_stopped_blocks_continuous_runtime():
    decision = evaluate_pr142_runtime_orchestration(
        complete_evidence(continuous_run_until_stopped=False)
    )

    assert "RUN_UNTIL_STOPPED_IS_NOT_CONTINUOUS" in decision.blockers


def test_critical_task_death_must_change_readiness():
    components = list(complete_evidence().component_contracts)
    components[0] = ComponentContract(
        component_name="discovery_loop",
        criticality=ComponentCriticality.SUPPORTING,
        owned_by_supervisor=True,
        failure_changes_readiness=False,
        exception_history_limit=32,
        restart_limit=1,
        cancellation_propagates=True,
    )
    evidence = complete_evidence(component_contracts=tuple(components))

    decision = evaluate_pr142_runtime_orchestration(evidence)

    assert "REQUIRED_COMPONENT_NOT_CRITICAL:discovery_loop" in decision.blockers


def test_expired_queue_items_must_release_tracker_pending():
    queue_tracker = QueueTrackerEvidence(
        queue_capacity=1_000,
        pending_ttl_ms=60_000,
        terminal_ttl_ms=3_600_000,
        terminal_retention_max=50_000,
        expired_items_release_pending=False,
        persistent_dedup_enabled=True,
        drop_reason_durable=True,
        backpressure_metrics=True,
    )

    decision = evaluate_pr142_runtime_orchestration(
        complete_evidence(queue_tracker=queue_tracker)
    )

    assert "EXPIRED_QUEUE_ITEM_DOES_NOT_RELEASE_TRACKER_PENDING" in decision.blockers


def test_database_actor_must_reject_second_writer_process():
    database_actor = DatabaseActorEvidence(
        dedicated_writer_actor=True,
        bounded_command_queue=True,
        command_queue_capacity=1_000,
        no_blocking_db_in_event_loop=True,
        explicit_reader_connections=True,
        process_lock_or_leader_lease=True,
        rejects_second_writer_process=False,
        topology_in_readiness=True,
        evidence_hash=HASH_A,
    )

    decision = evaluate_pr142_runtime_orchestration(
        complete_evidence(database_actor=database_actor)
    )

    assert (
        "DATABASE_ACTOR_REQUIREMENT_MISSING:rejects_second_writer_process"
        in decision.blockers
    )


def test_shutdown_requires_no_orphan_task_proof_and_cancelled_error_propagation():
    shutdown = ShutdownProtocolEvidence(
        implemented_steps=SHUTDOWN[:-1],
        drain_timeout_ms=30_000,
        checkpoint_hash=HASH_B,
        cancellation_preserves_ambiguous_state=True,
        no_orphan_tasks_proven=False,
        cancelled_error_propagates=False,
    )

    decision = evaluate_pr142_runtime_orchestration(
        complete_evidence(shutdown_protocol=shutdown)
    )

    assert "MISSING_SHUTDOWN_STEP:readiness_false_before_exit" in decision.blockers
    assert "NO_ORPHAN_TASKS_NOT_PROVEN" in decision.blockers
    assert "CANCELLED_ERROR_NOT_PROPAGATED" in decision.blockers


def test_fault_injection_must_cover_stage_hangs_queue_full_and_db_locked():
    faults = FaultInjectionEvidence(
        covered_faults=(
            "child_task_crash",
            "cancellation_during_db_commit",
            "cancellation_during_provider_request",
        ),
        no_task_leak=True,
        no_queue_leak=True,
        no_file_descriptor_leak=True,
        readiness_changes_on_critical_task_death=True,
        evidence_hash=HASH_C,
    )

    decision = evaluate_pr142_runtime_orchestration(
        complete_evidence(fault_injection=faults)
    )

    assert "MISSING_FAULT_INJECTION:stage_hang" in decision.blockers
    assert "MISSING_FAULT_INJECTION:queue_full" in decision.blockers
    assert "MISSING_FAULT_INJECTION:db_busy_locked" in decision.blockers


def test_dead_stop_on_first_blocked_candidate_config_blocks_review():
    decision = evaluate_pr142_runtime_orchestration(
        complete_evidence(stop_on_first_blocked_candidate_contract_enforced=False)
    )

    assert "STOP_ON_FIRST_BLOCKED_CANDIDATE_CONTRACT_NOT_ENFORCED" in decision.blockers


def test_malformed_hashes_and_duplicates_are_rejected():
    with pytest.raises(PR142RuntimeError, match="policy_snapshot_hash"):
        complete_evidence(policy_snapshot_hash="not-a-hash")

    with pytest.raises(PR142RuntimeError, match="stages"):
        complete_evidence(
            stage_budgets=(
                complete_evidence().stage_budgets[0],
                complete_evidence().stage_budgets[0],
            )
        )


def test_assert_helper_raises_typed_blocked_error():
    with pytest.raises(PR142RuntimeError, match="PR142_BLOCKED"):
        assert_pr142_runtime_orchestration_review_ready(
            complete_evidence(unresolved_blockers=("paper runner not wired",))
        )
