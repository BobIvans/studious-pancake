from dataclasses import replace

import pytest

from src.research.product import DataEvidenceApi, DataEvidenceKind
from src.research.pr358_contracts import canonical_hash
from src.research.pr359_wave15_institution import (
    AgentProfile,
    EvidenceRef,
    InstitutionRuntime,
    Offer,
    RuleSnapshot,
    SemanticEvidenceResolver,
    ServiceTask,
    Wave15InstitutionError,
    allocate_service,
    build_evidence,
    enumerate_unilateral_deviations,
    execute_service,
    run_inst01_vertical,
    welfare,
)


def _rules(mechanism: str = "critical_price") -> RuleSnapshot:
    kwargs = {}
    if mechanism == "posted_price":
        kwargs = {"posted_price_units": 3, "invitation_order": ("A", "B", "C")}
    return RuleSnapshot(
        rule_id=f"rule-{mechanism}",
        generation=1,
        mechanism=mechanism,
        reserve_units=5,
        **kwargs,
    )


def _task(rules: RuleSnapshot, task_id: str = "task") -> ServiceTask:
    values = (2, 3, 5)
    return ServiceTask(
        task_id=task_id,
        service_id="svc",
        state_hash=canonical_hash({"task": task_id, "values": values}),
        rule_hash=rules.rule_hash,
        budget_units=5,
        deadline=10,
        input_values=values,
    )


def _profiles() -> tuple[AgentProfile, ...]:
    return tuple(AgentProfile(x, "svc") for x in ("A", "B", "C"))


def _offers(task: ServiceTask) -> tuple[Offer, ...]:
    return (
        Offer(task.task_id, "A", 2),
        Offer(task.task_id, "B", 4),
        Offer(task.task_id, "C", 5),
    )


def test_money_rejects_bool_float_and_negative() -> None:
    rules = _rules()
    task = _task(rules)
    for value in (True, 1.5, -1):
        with pytest.raises(Wave15InstitutionError):
            Offer(task.task_id, "A", value)  # type: ignore[arg-type]


def test_critical_price_is_second_bid_and_tie_is_deterministic() -> None:
    rules = _rules("critical_price")
    task = _task(rules)
    offers = (
        Offer(task.task_id, "C", 2),
        Offer(task.task_id, "A", 2),
        Offer(task.task_id, "B", 4),
    )
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=offers,
    )
    assert decision.winner_id == "A"
    assert decision.payment_units == 2
    reversed_decision = allocate_service(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=tuple(reversed(offers)),
    )
    assert reversed_decision == decision


def test_single_critical_bidder_is_paid_reserve() -> None:
    rules = _rules("critical_price")
    task = _task(rules)
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=(AgentProfile("A", "svc"),),
        offers=(Offer(task.task_id, "A", 2),),
    )
    assert decision.payment_units == 5


def test_first_price_pays_own_bid() -> None:
    rules = _rules("first_price")
    task = _task(rules)
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=_offers(task),
    )
    assert (decision.winner_id, decision.payment_units) == ("A", 2)


def test_posted_price_respects_precommitted_invitation_order_not_cheapest() -> None:
    rules = _rules("posted_price")
    task = _task(rules)
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=(
            Offer(task.task_id, "A", 3),
            Offer(task.task_id, "B", 1),
            Offer(task.task_id, "C", 2),
        ),
    )
    assert (decision.winner_id, decision.payment_units) == ("A", 3)


def test_fixed_eligibility_ignores_low_bid_from_ineligible_supplier() -> None:
    rules = _rules()
    task = _task(rules)
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=(
            AgentProfile("A", "svc", eligible=False),
            AgentProfile("B", "svc", eligible=True),
        ),
        offers=(Offer(task.task_id, "A", 0), Offer(task.task_id, "B", 3)),
    )
    assert decision.winner_id == "B"
    assert decision.payment_units == 5


def test_empty_and_over_reserve_are_no_trade() -> None:
    rules = _rules()
    task = _task(rules)
    empty = allocate_service(task=task, rules=rules, profiles=_profiles(), offers=())
    assert empty.winner_id is None
    over = allocate_service(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=(Offer(task.task_id, "A", 6),),
    )
    assert over.winner_id is None


def test_duplicate_offer_and_double_allocation_fail_closed() -> None:
    rules = _rules()
    task = _task(rules)
    with pytest.raises(Wave15InstitutionError):
        allocate_service(
            task=task,
            rules=rules,
            profiles=_profiles(),
            offers=(Offer(task.task_id, "A", 1), Offer(task.task_id, "A", 2)),
        )
    runtime = InstitutionRuntime()
    runtime.award_once(task=task, rules=rules, profiles=_profiles(), offers=_offers(task))
    with pytest.raises(Wave15InstitutionError, match="ALREADY_ALLOCATED"):
        runtime.award_once(
            task=task,
            rules=rules,
            profiles=_profiles(),
            offers=_offers(task),
        )


def _resolver_for(
    *,
    task: ServiceTask,
    supplier_id: str,
    completed_at: int = 9,
    result_override: int | None = None,
    evidence_kind: DataEvidenceKind = DataEvidenceKind.SIMULATED,
    claims_actual_pnl: bool = False,
    payload_mutator=None,
):
    body = execute_service(
        task=task,
        supplier_id=supplier_id,
        completed_at=completed_at,
        result_override=result_override,
    )
    artifact, payload, ref = build_evidence(
        task=task,
        supplier_id=supplier_id,
        body_json=body,
        artifact_id=f"artifact-{task.task_id}-{completed_at}-{result_override}",
        evidence_kind=evidence_kind,
        claims_actual_pnl=claims_actual_pnl,
    )
    if payload_mutator is not None:
        payload = payload_mutator(payload)
    return SemanticEvidenceResolver(
        api=DataEvidenceApi((artifact,)), payloads=(payload,)
    ), ref


def test_correct_semantic_result_is_accepted_but_never_real_pnl() -> None:
    rules = _rules()
    task = _task(rules)
    resolver, ref = _resolver_for(task=task, supplier_id="A")
    result = resolver.resolve(
        evidence_ref=ref,
        task=task,
        expected_supplier_id="A",
        lease_id="lease",
        access_scope="research",
    )
    assert result.status == "ACCEPTED_SYNTHETIC"
    assert result.actual_pnl_claimed is False
    assert result.external_economic_success is False


def test_wrong_but_well_hashed_result_is_semantically_rejected() -> None:
    rules = _rules()
    task = _task(rules)
    resolver, ref = _resolver_for(task=task, supplier_id="A", result_override=11)
    result = resolver.resolve(
        evidence_ref=ref,
        task=task,
        expected_supplier_id="A",
        lease_id="lease",
        access_scope="research",
    )
    assert result.reason == "SEMANTIC_VALIDATION_FAILED"


def test_binding_mismatch_is_not_success() -> None:
    rules = _rules()
    task = _task(rules)

    def mutate(payload):
        return replace(payload, state_hash="wrong-state")

    resolver, ref = _resolver_for(
        task=task, supplier_id="A", payload_mutator=mutate
    )
    result = resolver.resolve(
        evidence_ref=ref,
        task=task,
        expected_supplier_id="A",
        lease_id="lease",
        access_scope="research",
    )
    assert result.reason == "BINDING_MISMATCH"


def test_nonempty_fabricated_evidence_ref_is_not_success() -> None:
    rules = _rules()
    task = _task(rules)
    resolver, _ = _resolver_for(task=task, supplier_id="A")
    fake = EvidenceRef("fabricated", "v1", "0" * 64)
    with pytest.raises(Exception):
        resolver.resolve(
            evidence_ref=fake,
            task=task,
            expected_supplier_id="A",
            lease_id="lease",
            access_scope="research",
        )


def test_observed_unfinalized_economic_claim_is_rejected() -> None:
    rules = _rules()
    task = _task(rules)
    resolver, ref = _resolver_for(
        task=task,
        supplier_id="A",
        evidence_kind=DataEvidenceKind.OBSERVED,
        claims_actual_pnl=True,
    )
    result = resolver.resolve(
        evidence_ref=ref,
        task=task,
        expected_supplier_id="A",
        lease_id="lease",
        access_scope="research",
    )
    assert result.reason == "ECONOMIC_CLAIM_UNFINALIZED"
    assert result.external_economic_success is False


def test_late_delivery_is_separate_from_semantic_failure() -> None:
    rules = _rules()
    task = _task(rules)
    resolver, ref = _resolver_for(task=task, supplier_id="A", completed_at=11)
    result = resolver.resolve(
        evidence_ref=ref,
        task=task,
        expected_supplier_id="A",
        lease_id="lease",
        access_scope="research",
    )
    assert result.status == "LATE"
    assert result.reason == "LATE"


def test_unknown_holds_obligation_and_duplicate_terminal_close_is_prevented() -> None:
    rules = _rules()
    task = _task(rules, "unknown-task")
    runtime = InstitutionRuntime()
    decision = runtime.award_once(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=_offers(task),
    )
    assert decision.winner_id is not None
    runtime.accept(task_id=task.task_id, supplier_id=decision.winner_id)
    held = runtime.settle(
        task=task,
        resolver=None,
        evidence_ref=None,
        outcome="unknown",
    )
    assert held.status == "HELD_UNKNOWN"
    assert held.payable_units is None
    assert held.reservation_held_units == decision.payment_units

    resolver, ref = _resolver_for(task=task, supplier_id=decision.winner_id)
    closed = runtime.settle(
        task=task,
        resolver=resolver,
        evidence_ref=ref,
        outcome="delivered",
    )
    assert closed.status == "ACCEPTED_SYNTHETIC"
    with pytest.raises(Wave15InstitutionError, match="ALREADY_CLOSED"):
        runtime.settle(
            task=task,
            resolver=resolver,
            evidence_ref=ref,
            outcome="delivered",
            lease_id="second",
        )


def test_internal_payment_is_a_transfer_not_double_counted_welfare() -> None:
    rules = _rules("first_price")
    task = _task(rules)
    decision = allocate_service(
        task=task,
        rules=rules,
        profiles=_profiles(),
        offers=_offers(task),
    )
    accounting = welfare(
        decision,
        buyer_value_units=7,
        true_costs={"A": 1, "B": 3, "C": 5},
    )
    assert accounting["transfer_sum"] == 0
    assert accounting["social_welfare"] == 6


def test_finite_deviation_baselines_preserve_scope_and_counterexample() -> None:
    first = enumerate_unilateral_deviations("first_price")
    critical = enumerate_unilateral_deviations("critical_price")
    assert first["unilateral_checks"] == 2625
    assert critical["unilateral_checks"] == 2625
    assert first["max_tested_gain"] > 0
    assert first["first_counterexample"] is not None
    assert critical["max_tested_gain"] == 0
    assert critical["scope"] == "FINITE_DOMAIN_ONLY_NOT_GLOBAL_IC_CERTIFICATE"


def test_integrated_inst01_vertical_is_replayable_and_effect_free() -> None:
    first = run_inst01_vertical()
    second = run_inst01_vertical()
    assert first["integrated_receipt_hash"] == second["integrated_receipt_hash"]
    assert first["verdict"]["total_unilateral_checks"] == 5250
    assert first["accepted_receipt"]["status"] == "ACCEPTED_SYNTHETIC"
    assert (
        first["wrong_well_hashed_verification"]["reason"]
        == "SEMANTIC_VALIDATION_FAILED"
    )
    assert first["unknown_receipt"]["status"] == "HELD_UNKNOWN"
    assert all(value is False for value in first["effect_boundary"].values())
