from __future__ import annotations

import pytest

from src.mega8_02.core import (
    CapacityQuote,
    EvidenceBinding,
    Mega802Error,
    ResourceEnvelope,
    RouteVariant,
)
from src.mega8_02.pr163 import (
    define_financial_primitive_type,
    resolve_wrapper_underlying_chain,
    validate_asset_units_and_rights,
)
from src.mega8_02.pr164 import (
    compile_operation_hyperedge,
    simulate_hyperedge_state_transition,
)
from src.mega8_02.pr165 import (
    deduplicate_route_variants,
    preserve_distinct_resource_profiles,
)
from src.mega8_02.pr166 import (
    identify_affected_routes,
    maintain_scc_cycle_cache,
    update_incremental_graph_index,
)
from src.mega8_02.pr167 import (
    apply_route_leg_to_state,
    emit_state_transition_proof,
    rollback_failed_route_branch,
    trace_shared_resource_mutations,
)
from src.mega8_02.pr168 import calibrate_resource_predictor
from src.mega8_02.pr169 import (
    estimate_writable_lock_contention,
    gate_high_contention_candidate,
)
from src.mega8_02.pr170 import (
    FeeObservation,
    estimate_inclusion_cost_curve,
    select_economic_fee_bid,
)
from src.mega8_02.pr171 import (
    build_pareto_frontier,
    score_route_objectives,
    select_policy_constrained_route,
)
from src.mega8_02.pr172 import (
    MixedRoute,
    solve_continuous_flow_allocation,
    verify_solver_optimality_gap,
)
from src.mega8_02.pr173 import optimize_worst_case_net, reject_fragile_opportunity
from src.mega8_02.pr174 import (
    allocate_borrow_across_lenders,
    select_atomic_financing_variant,
)
from src.mega8_02.pr175 import (
    bind_variant_resources,
    generate_transaction_variants,
    prune_dominated_variants,
)
from src.mega8_02.pr176 import build_solver_certificate, verify_certificate_replay


def evidence(*, verified: bool = True, expires: int = 100) -> EvidenceBinding:
    return EvidenceBinding("g1", "a" * 64, "v1", 1, expires, verified=verified)


def test_evidence_boundary_is_verified_fresh_and_never_live() -> None:
    evidence().assert_usable(now=2)
    with pytest.raises(Mega802Error, match="stale"):
        evidence(expires=2).assert_usable(now=2)
    with pytest.raises(Mega802Error, match="unverified"):
        evidence(verified=False).assert_usable(now=2)
    with pytest.raises(Mega802Error, match="live authority"):
        EvidenceBinding("g", "a" * 64, "v1", 1, 2, live_enabled=True)


def test_rights_hyperedge_and_wrapper_chain_fail_closed() -> None:
    wrapper = define_financial_primitive_type(
        kind="wrapper",
        asset_id="w",
        unit="atomic",
        rights=("redeem",),
        underlying=("u",),
    )
    underlying = define_financial_primitive_type(
        kind="asset", asset_id="u", unit="atomic", rights=("hold",)
    )
    assert resolve_wrapper_underlying_chain({"w": wrapper, "u": underlying}, "w") == (
        "w",
        "u",
    )
    assert validate_asset_units_and_rights(
        wrapper, expected_unit="atomic", required_rights=("redeem",)
    )
    with pytest.raises(Mega802Error, match="MISSING_RIGHTS"):
        validate_asset_units_and_rights(
            wrapper, expected_unit="atomic", required_rights=("borrow",)
        )
    edge = compile_operation_hyperedge(
        edge_id="mint",
        inputs={"A": 5},
        outputs={"B": 4},
        writable_resources=("pool",),
    )
    assert simulate_hyperedge_state_transition({"A": 10}, edge) == {"A": 5, "B": 4}
    with pytest.raises(Mega802Error, match="insufficient"):
        simulate_hyperedge_state_transition({"A": 4}, edge)


def test_route_canonicalization_preserves_resource_profiles() -> None:
    a = RouteVariant("a", ("x", "y"), 100, 110, "g", ("pool-a",), ())
    b = RouteVariant("b", ("x", "y"), 100, 110, "g", ("pool-b",), ())
    duplicate = RouteVariant("z", ("x", "y"), 100, 110, "g", ("pool-a",), ())
    rows = deduplicate_route_variants((a, b, duplicate))
    assert len(rows) == 2
    profiles = preserve_distinct_resource_profiles((a, b, duplicate))
    assert len(profiles[a.economic_identity]) == 2


def test_incremental_index_state_trace_and_rollback_are_deterministic() -> None:
    index = update_incremental_graph_index(
        generation="g1",
        routes={"r1": ("pool-a", "oracle"), "r2": ("pool-b",)},
    )
    assert identify_affected_routes(index, ("pool-a",)) == ("r1",)
    assert maintain_scc_cycle_cache({"A": ("B",), "B": ("A",), "C": ()}) == (
        ("A", "B"),
        ("C",),
    )
    before = {"reserve": 100}
    legs = (("l1", {"reserve": -10}), ("l2", {"reserve": 4}))
    after = before
    for leg_id, deltas in legs:
        after = apply_route_leg_to_state(after, leg_id=leg_id, deltas=deltas)
    mutations = trace_shared_resource_mutations(legs)
    assert after == {"reserve": 94}
    assert rollback_failed_route_branch(after, mutations) == before
    proof = emit_state_transition_proof(before, after, mutations)
    assert proof == emit_state_transition_proof(before, after, mutations)


def test_resource_contention_fee_and_solver_layers() -> None:
    envelope = calibrate_resource_predictor(
        (100, 110, 120), (5, 6, 7), (200, 220, 240)
    )
    assert envelope.compute_units >= 120
    contention = estimate_writable_lock_contention(
        ("pool",), (("pool", "x"), ("other",), ("pool",))
    )
    assert contention == 666_666
    with pytest.raises(Mega802Error, match="HIGH_CONTENTION"):
        gate_high_contention_candidate(contention, max_ppm=500_000)

    curve = estimate_inclusion_cost_curve(
        (
            FeeObservation(1, False),
            FeeObservation(2, True),
            FeeObservation(3, True),
        )
    )
    assert select_economic_fee_bid(
        curve, target_inclusion_ppm=600_000, hard_cap=3
    ) == 3

    good = score_route_objectives(
        candidate_id="good",
        conservative_net=10,
        duration_us=5,
        resource_cost=2,
        uncertainty=1,
        contention_ppm=1,
    )
    worse = score_route_objectives(
        candidate_id="worse",
        conservative_net=9,
        duration_us=6,
        resource_cost=2,
        uncertainty=1,
        contention_ppm=1,
    )
    frontier = build_pareto_frontier((good, worse))
    assert frontier == (good,)
    assert select_policy_constrained_route(
        frontier, max_duration_us=10, max_uncertainty=2, max_contention_ppm=10
    ) == good


def test_mixed_robust_lender_variant_and_certificate_replay() -> None:
    routes = (MixedRoute("r1", 5, 60), MixedRoute("r2", 3, 50))
    assert solve_continuous_flow_allocation(routes, amount=100) == (
        ("r1", 60),
        ("r2", 40),
    )
    assert verify_solver_optimality_gap(100, 105, max_gap=5) == 5
    worst = optimize_worst_case_net(
        gross_out_low=120, input_amount=100, fixed_cost=5
    )
    assert worst == 15
    assert reject_fragile_opportunity(worst)
    with pytest.raises(Mega802Error, match="FRAGILE"):
        reject_fragile_opportunity(0)

    quotes = (
        CapacityQuote("cheap", "USDC", 60, 1, "g"),
        CapacityQuote("deep", "USDC", 60, 2, "g"),
    )
    assert allocate_borrow_across_lenders(quotes, amount=100) == (
        ("cheap", 60),
        ("deep", 40),
    )
    assert select_atomic_financing_variant(
        quotes, amount=100, max_total_fee=3
    ) == (("cheap", 60), ("deep", 40))

    raws = generate_transaction_variants(
        route_ids=("r1",), lender_ids=("l1",), format_ids=("v0",),
        send_paths=("rpc", "jito"),
    )
    small = ResourceEnvelope(100, 5, 200)
    big = ResourceEnvelope(200, 5, 300)
    variants = (
        bind_variant_resources(raws[0], message_sha256="a" * 64,
                               envelope=small, expected_net=10),
        bind_variant_resources(raws[1], message_sha256="b" * 64,
                               envelope=big, expected_net=9),
    )
    assert len(prune_dominated_variants(variants)) == 1

    cert = build_solver_certificate(
        selected_id="r1",
        constraints={"max_hops": 5},
        objectives={"net": 10},
        rejected={"r2": "dominated"},
    )
    assert verify_certificate_replay(
        cert,
        selected_id="r1",
        constraints={"max_hops": 5},
        objectives={"net": 10},
        rejected={"r2": "dominated"},
    )
