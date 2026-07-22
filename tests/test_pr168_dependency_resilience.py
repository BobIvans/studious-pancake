from __future__ import annotations

import pytest
from dataclasses import replace

from src.dependency_resilience_pr168 import (
    BulkheadEvidence,
    CircuitBreakerEvidence,
    CircuitState,
    DependencyCatalogEntry,
    DependencyCriticality,
    DependencyResilienceBlocked,
    DependencyResilienceEvidence,
    FailureKind,
    FallbackEvidence,
    GracefulDegradationEvidence,
    OutageDrillEvidence,
    REQUIRED_BULKHEAD_PURPOSES,
    REQUIRED_OUTAGE_DRILLS,
    RetryDeadlineBudget,
    assert_pr168_dependency_resilience_ready,
    evaluate_pr168_dependency_resilience,
    stable_hash,
)

def h(name: str) -> str:
    return stable_hash({"fixture": name})

def catalog(*, dep: str = "jupiter", purpose: str = "discovery", criticality=DependencyCriticality.OPTIONAL):
    return DependencyCatalogEntry(
        dependency_id=dep,
        purpose=purpose,
        criticality=criticality,
        provider_identity_hash=h(dep + "provider"),
        endpoint_identity_hash=h(dep + "endpoint"),
        credential_ref_hash=h(dep + "cred"),
        quota_policy_hash=h(dep + "quota"),
        timeout_ms=1500,
        retry_policy_hash=h(dep + "retry"),
        circuit_policy_hash=h(dep + "circuit"),
        fallback_ids=("okx",) if dep == "jupiter" else (),
        consistency_contract_hash=h(dep + "consistency"),
        maximum_outage_ms=30_000,
        manual_override_policy_hash=h(dep + "manual"),
    )

def bulkheads():
    return tuple(
        BulkheadEvidence(
            purpose=p,
            max_concurrent_tasks=2,
            max_connections=2,
            max_memory_bytes=1_000_000,
            independent_pool=True,
            preserves_finalization_capacity=True,
            queue_bound=8,
            policy_hash=h("bulk" + p),
        )
        for p in REQUIRED_BULKHEAD_PURPOSES
    )

def budget(**kw):
    values = dict(
        operation_id="candidate-1",
        absolute_deadline_ns=2_000,
        issued_at_ns=1_000,
        max_total_attempts=3,
        max_cumulative_delay_ms=200,
        max_provider_switches=1,
        nested_components_share_budget=True,
        expires_before_candidate_ns=1_900,
        retry_after_expiry_allowed=False,
        policy_hash=h("budget"),
    )
    values.update(kw)
    return RetryDeadlineBudget(**values)

def circuit(**kw):
    values = dict(
        dependency_id="jupiter",
        purpose="discovery",
        state=CircuitState.CLOSED,
        rolling_window_ms=60_000,
        failure_rate_threshold_ppm=500_000,
        slow_call_threshold_ppm=500_000,
        minimum_sample_count=20,
        half_open_concurrency=1,
        exponential_open_duration=True,
        open_duration_cap_ms=300_000,
        persisted_state=True,
        persisted_last_cause=True,
        manual_force_open_supported=True,
        resets_only_on_policy_change=True,
        differentiates_failures=frozenset(FailureKind),
        fatal_failures_auto_recover_by_cooldown=False,
        policy_hash=h("circuit"),
    )
    values.update(kw)
    return CircuitBreakerEvidence(**values)

def fallback(**kw):
    caps = frozenset({"composable_instructions", "exact_amount_quote", "program_attested", "min_out", "slot_fresh"})
    values = dict(
        source_dependency_id="jupiter",
        fallback_dependency_id="okx",
        source_capabilities=caps,
        fallback_capabilities=caps,
        same_security_domain=True,
        same_economic_guarantees=True,
        same_atomicity_role=True,
        preserves_min_out=True,
        preserves_slot_freshness=True,
        preserves_program_attestation=True,
        equivalence_hash=h("fallback"),
    )
    values.update(kw)
    return FallbackEvidence(**values)

def degradations():
    scenarios = (
        "optional_provider_down",
        "required_finalizer_down",
        "one_rpc_down",
        "signer_down",
        "alerting_down",
        "object_store_down",
        "backup_down",
    )
    return tuple(
        GracefulDegradationEvidence(
            scenario=s,
            degraded_state_code=s.upper(),
            optional_loss_is_bounded=True,
            required_loss_blocks_trade=("required" in s or s in {"signer_down", "alerting_down", "backup_down"}),
            settlement_capacity_preserved=True,
            reconciliation_capacity_preserved=True,
            finalization_capacity_preserved=True,
            new_attempts_stopped_before_reconciliation=True,
            explicit_operator_alert=True,
            policy_hash=h("degrade" + s),
        )
        for s in scenarios
    )

def drills():
    return tuple(
        OutageDrillEvidence(
            drill_id=d,
            passed=True,
            report_hash=h("drill" + d),
            stable_memory=True,
            stable_fd=True,
            stable_queue=True,
            readiness_reflects_dependency_matrix=True,
            alerting_reflects_dependency_matrix=True,
        )
        for d in REQUIRED_OUTAGE_DRILLS
    )

def evidence(**kw):
    values = dict(
        catalog=(catalog(), catalog(dep="okx"), catalog(dep="rpc", purpose="rpc_account_reads", criticality=DependencyCriticality.REQUIRED)),
        bulkheads=bulkheads(),
        retry_budgets=(budget(),),
        circuits=(circuit(),),
        fallbacks=(fallback(),),
        degradations=degradations(),
        outage_drills=drills(),
        dependency_matrix_hash=h("matrix"),
        readiness_policy_hash=h("ready"),
        alerting_policy_hash=h("alert"),
    )
    values.update(kw)
    return DependencyResilienceEvidence(**values)

def blocked(ev):
    return evaluate_pr168_dependency_resilience(ev).blockers

def test_complete_evidence_is_review_ready():
    decision = assert_pr168_dependency_resilience_ready(evidence())
    assert decision.review_ready
    assert not decision.live_claim_allowed
    assert not decision.sender_submission_allowed

def test_missing_bulkhead_blocks():
    ev = evidence(bulkheads=bulkheads()[:-1])
    assert "MISSING_BULKHEAD:telemetry_backup" in blocked(ev)

def test_shared_retry_budget_required():
    ev = evidence(retry_budgets=(budget(nested_components_share_budget=False),))
    assert "NESTED_RETRIES_NOT_SHARED:candidate-1" in blocked(ev)

def test_retry_after_candidate_expiry_blocks():
    ev = evidence(retry_budgets=(budget(retry_after_expiry_allowed=True),))
    assert "RETRY_AFTER_EXPIRY_ALLOWED:candidate-1" in blocked(ev)

def test_circuit_state_must_persist():
    ev = evidence(circuits=(circuit(persisted_state=False),))
    assert "CIRCUIT_STATE_NOT_DURABLE:jupiter:discovery" in blocked(ev)

def test_fatal_failures_do_not_auto_recover():
    ev = evidence(circuits=(circuit(fatal_failures_auto_recover_by_cooldown=True),))
    assert "FATAL_FAILURE_AUTO_RECOVERS:jupiter:discovery" in blocked(ev)

def test_fallback_cannot_drop_composable_capability():
    ev = evidence(fallbacks=(fallback(fallback_capabilities=frozenset({"assembled_transaction", "exact_amount_quote", "program_attested", "min_out", "slot_fresh"})),))
    blockers = blocked(ev)
    assert any(b.startswith("FORBIDDEN_FALLBACK_CAPABILITY_DROP:composable_instructions") for b in blockers)

def test_fallback_must_preserve_program_attestation():
    ev = evidence(fallbacks=(fallback(preserves_program_attestation=False),))
    assert "FALLBACK_DROPS_PROGRAM_ATTESTATION:jupiter" in blocked(ev)

def test_required_dependency_loss_must_block_trade():
    bad = tuple(
        d if d.scenario != "required_finalizer_down" else replace(d, required_loss_blocks_trade=False)
        for d in degradations()
    )
    assert "REQUIRED_LOSS_DOES_NOT_BLOCK_TRADE:required_finalizer_down" in blocked(evidence(degradations=bad))

def test_settlement_capacity_preserved_under_brownout():
    bad = tuple(
        d if d.scenario != "optional_provider_down" else replace(d, settlement_capacity_preserved=False)
        for d in degradations()
    )
    assert "SETTLEMENT_RECONCILIATION_NOT_PRESERVED:optional_provider_down" in blocked(evidence(degradations=bad))

def test_all_outage_drills_required():
    ev = evidence(outage_drills=drills()[:-1])
    assert "MISSING_OUTAGE_DRILL:signer_alertmanager_object_store_unavailable" in blocked(ev)

def test_drill_resource_instability_blocks():
    bad = tuple(
        d if d.drill_id != "provider_hangs" else replace(d, stable_fd=False)
        for d in drills()
    )
    assert "OUTAGE_DRILL_RESOURCE_UNSTABLE:provider_hangs" in blocked(evidence(outage_drills=bad))

def test_bad_top_level_hash_blocks():
    assert "BAD_HASH:dependency_matrix_hash" in blocked(evidence(dependency_matrix_hash="not-a-hash"))

def test_assert_helper_raises_typed_exception():
    with pytest.raises(DependencyResilienceBlocked) as exc:
        assert_pr168_dependency_resilience_ready(evidence(unresolved_blockers=("wire runtime",)))
    assert "UNRESOLVED_BLOCKER:wire runtime" in exc.value.decision.blockers
