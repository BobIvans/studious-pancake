from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.mega_pr01_v4_multiprocess_runtime_gate import (
    SCHEMA_VERSION,
    AtomicReservationModel,
    BatchRuntimeEvidence,
    CapitalEvidence,
    EvidenceRef,
    MegaPR01V4Evidence,
    MegaPR01V4State,
    MultiProcessChaosEvidence,
    OwnershipEvidence,
    ProviderHandoffEvidence,
    evaluate_mega_pr01_v4_evidence,
    validate_cycle_deadline_lease_policy,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def ref(label: str) -> EvidenceRef:
    return EvidenceRef(label=label, sha256=digest(label), path=f"evidence/{label}.json")


def ownership() -> OwnershipEvidence:
    return OwnershipEvidence(
        synchronized_time_required_for_sensitive_writes=True,
        degraded_time_closes_readiness=True,
        owner_bound_fences_on_every_mutation=True,
        active_foreign_owner_rejected=True,
        takeover_allocates_new_fencing_token=True,
        terminal_states_irreversible=True,
        legal_state_transition_table_hash=digest("transition-table"),
        terminal_result_committed_atomically=True,
        failed_result_persistence_leaves_retryable_work=True,
        cycle_sequence_allocation_atomic=True,
        lease_ttl_exceeds_deadline_with_margin=True,
        ownership_renewal_supervised=True,
        recovery_fence_for_timeout_cancel_lease_loss=True,
    )


def provider_handoff() -> ProviderHandoffEvidence:
    return ProviderHandoffEvidence(
        inbox_claim_lease_ack_nack_dlq_state_machine=True,
        handoff_claim_lease_ack_nack_retry_state_machine=True,
        exact_claimed_handoff_set_acknowledged_with_cycle_terminal=True,
        poison_event_retry_budget_and_backoff=True,
        oldest_poison_event_cannot_block_queue=True,
        original_event_age_bounded_by_trusted_time=True,
        stale_events_routed_to_backfill_or_rejected=True,
        rpc_quorum_constructed_inside_transport=True,
        endpoint_identity_and_raw_response_bound_to_hash=True,
        duplicate_infrastructure_rejected=True,
        immutable_content_addressed_raw_evidence=True,
        raw_evidence_no_update_delete_enforced=True,
    )


def capital() -> CapitalEvidence:
    return CapitalEvidence(
        atomic_compare_and_reserve_transaction=True,
        aggregate_active_reservation_db_invariant=True,
        wallet_snapshot_bound_to_payer_genesis_slot_provider_time=True,
        wallet_snapshot_max_age_ms=5000,
        reservation_identity_collision_free=True,
        reservation_identity_includes_generation_and_candidate_hash=True,
        release_then_reattempt_collision_tested=True,
        reservation_saga_covers_exception_cancel_timeout=True,
        cleanup_failure_freezes_for_recovery=True,
        stranded_active_reservation_recovery_tested=True,
    )


def batch_runtime() -> BatchRuntimeEvidence:
    return BatchRuntimeEvidence(
        attempt_generation_minimum_one_everywhere=True,
        generation_zero_rejected_at_all_boundaries=True,
        per_item_deadlines=True,
        durable_partial_progress_checkpoints=True,
        slow_candidate_cannot_erase_completed_results=True,
        restart_resumes_only_unfinished_fenced_items=True,
        no_duplicate_cycle_multi_instance=True,
        no_foreign_fence_mutation_multi_process=True,
        no_over_reservation_two_coordinators=True,
        no_lost_terminal_result_under_sink_failure=True,
        bounded_queue_progress_under_poison_and_sqlite_busy=True,
    )


def chaos() -> MultiProcessChaosEvidence:
    return MultiProcessChaosEvidence(
        service_instances=2,
        capital_coordinators=2,
        injected_faults=("kill-9", "lease-expiry", "sqlite-busy", "provider-poison"),
        no_duplicate_cycle=True,
        no_foreign_fence_mutation=True,
        no_over_reservation=True,
        no_lost_terminal_result=True,
        bounded_queue_progress=True,
        evidence_artifact=ref("chaos"),
    )


def evidence() -> MegaPR01V4Evidence:
    return MegaPR01V4Evidence(
        schema_version=SCHEMA_VERSION,
        covered_findings=(
            "IMPL-42",
            "IMPL-43",
            "IMPL-44",
            "IMPL-45",
            "IMPL-46",
            "IMPL-47",
            "IMPL-48",
            "IMPL-49",
            "IMPL-50",
            "IMPL-51",
            "IMPL-52",
            "IMPL-53",
            "IMPL-54",
            "IMPL-55",
            "IMPL-56",
            "IMPL-57",
            "IMPL-60",
        ),
        ownership=ownership(),
        provider_handoff=provider_handoff(),
        capital=capital(),
        batch_runtime=batch_runtime(),
        chaos=chaos(),
        evidence_refs=(
            ref("ownership"),
            ref("provider_handoff"),
            ref("capital"),
            ref("batch_runtime"),
            ref("chaos"),
        ),
    )


def codes(report) -> set[str]:
    return {item.code for item in report.blockers}


def test_happy_path_allows_repair_review_only() -> None:
    report = evaluate_mega_pr01_v4_evidence(evidence())

    assert report.state is MegaPR01V4State.READY_FOR_MULTIPROCESS_REPAIR_REVIEW
    assert report.multiprocess_repair_review_allowed is True
    assert report.operational_paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert len(report.evidence_hash) == 64


def test_missing_v4_findings_fail_closed() -> None:
    item = replace(evidence(), covered_findings=("IMPL-42",))

    report = evaluate_mega_pr01_v4_evidence(item)

    assert report.state is MegaPR01V4State.BLOCKED
    assert "MEGA_PR01_V4_FINDINGS_INCOMPLETE" in codes(report)


def test_owner_fence_and_terminal_immutability_are_required() -> None:
    item = replace(
        evidence(),
        ownership=replace(
            ownership(),
            owner_bound_fences_on_every_mutation=False,
            terminal_states_irreversible=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_OWNERSHIP_GAP" in codes(report)


def test_sensitive_writes_require_synchronized_time() -> None:
    item = replace(
        evidence(),
        ownership=replace(
            ownership(),
            synchronized_time_required_for_sensitive_writes=False,
            degraded_time_closes_readiness=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_OWNERSHIP_GAP" in codes(report)


def test_lease_must_outlive_deadline_and_commit_margin() -> None:
    assert validate_cycle_deadline_lease_policy(
        now_ms=1000,
        deadline_ms=2000,
        lease_expires_ms=2600,
        commit_margin_ms=500,
    ) == (True, "READY")
    assert validate_cycle_deadline_lease_policy(
        now_ms=1000,
        deadline_ms=2000,
        lease_expires_ms=2500,
        commit_margin_ms=500,
    ) == (False, "LEASE_DOES_NOT_COVER_COMMIT_MARGIN")


def test_provider_handoff_requires_claim_ack_dlq_and_retry_budget() -> None:
    item = replace(
        evidence(),
        provider_handoff=replace(
            provider_handoff(),
            handoff_claim_lease_ack_nack_retry_state_machine=False,
            poison_event_retry_budget_and_backoff=False,
            oldest_poison_event_cannot_block_queue=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_PROVIDER_HANDOFF_GAP" in codes(report)


def test_rpc_quorum_and_raw_evidence_must_be_transport_proven() -> None:
    item = replace(
        evidence(),
        provider_handoff=replace(
            provider_handoff(),
            rpc_quorum_constructed_inside_transport=False,
            endpoint_identity_and_raw_response_bound_to_hash=False,
            immutable_content_addressed_raw_evidence=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_PROVIDER_HANDOFF_GAP" in codes(report)


def test_atomic_reservation_model_rejects_over_reservation() -> None:
    ledger = AtomicReservationModel(spendable_lamports=6_000_000)

    assert ledger.reserve(3_000_000) is True
    assert ledger.reserve(3_000_001) is False
    assert ledger.reserved_lamports == 3_000_000

    with pytest.raises(ValueError):
        ledger.reserve(0)


def test_capital_gate_rejects_non_atomic_or_unbound_snapshot() -> None:
    item = replace(
        evidence(),
        capital=replace(
            capital(),
            atomic_compare_and_reserve_transaction=False,
            aggregate_active_reservation_db_invariant=False,
            wallet_snapshot_bound_to_payer_genesis_slot_provider_time=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_CAPITAL_GAP" in codes(report)


def test_collision_free_reservation_identity_and_cleanup_saga_are_required() -> None:
    item = replace(
        evidence(),
        capital=replace(
            capital(),
            reservation_identity_collision_free=False,
            release_then_reattempt_collision_tested=False,
            reservation_saga_covers_exception_cancel_timeout=False,
            cleanup_failure_freezes_for_recovery=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_CAPITAL_GAP" in codes(report)


def test_batch_runtime_requires_positive_generation_and_partial_progress() -> None:
    item = replace(
        evidence(),
        batch_runtime=replace(
            batch_runtime(),
            attempt_generation_minimum_one_everywhere=False,
            generation_zero_rejected_at_all_boundaries=False,
            durable_partial_progress_checkpoints=False,
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_BATCH_RUNTIME_GAP" in codes(report)


def test_chaos_gate_requires_two_instances_and_declared_faults() -> None:
    item = replace(
        evidence(),
        chaos=replace(
            chaos(),
            service_instances=1,
            capital_coordinators=1,
            injected_faults=("kill-9",),
        ),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_CHAOS_SERVICE_INSTANCES" in codes(report)
    assert "MEGA_PR01_V4_CHAOS_CAPITAL_COORDINATORS" in codes(report)
    assert "MEGA_PR01_V4_CHAOS_FAULTS_INCOMPLETE" in codes(report)


def test_runtime_promotion_and_live_capabilities_are_forbidden() -> None:
    item = replace(
        evidence(),
        operational_paper_ready_requested=True,
        live_execution_requested=True,
        signer_requested=True,
        sender_requested=True,
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_OPERATIONAL_PAPER_PROMOTION_FORBIDDEN" in codes(report)
    assert "MEGA_PR01_V4_LIVE_FORBIDDEN" in codes(report)
    assert "MEGA_PR01_V4_SIGNER_FORBIDDEN" in codes(report)
    assert "MEGA_PR01_V4_SENDER_FORBIDDEN" in codes(report)
    assert report.operational_paper_ready_allowed is False


def test_invalid_evidence_references_fail_closed() -> None:
    item = replace(
        evidence(),
        evidence_refs=(EvidenceRef("ownership", "not-a-hash", "../bad.json"),),
    )

    report = evaluate_mega_pr01_v4_evidence(item)

    assert "MEGA_PR01_V4_EVIDENCE_REF_MISSING" in codes(report)
    assert "MEGA_PR01_V4_EVIDENCE_REF_INVALID" in codes(report)
