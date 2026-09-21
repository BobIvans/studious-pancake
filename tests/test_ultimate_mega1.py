from __future__ import annotations

import importlib

import pytest

from src.mega8_08.core import Mega808Error
from src.mega8_08.manifest import (
    ALL_FUNCTIONS as RESIDUAL_FUNCTIONS,
    CHILDREN as RESIDUAL_CHILDREN,
    FUNCTION_COUNT as RESIDUAL_COUNT,
    NF_IDS as RESIDUAL_NF_IDS,
)
from src.mega8_08.pr289 import normalize_intent_constraints, price_solver_fill
from src.mega8_08.pr292 import build_sui_atomic_route
from src.mega8_08.pr299 import approve_shadow_promotion, submit_strategy_proposal
from src.release_gate.ultimate_mega1_closure import (
    CLOSURE_PACKAGES,
    NF_TO_CLOSURE,
    assert_static_closure_partition,
)
from src.ultimate_mega1.core import UltimateMegaError
from src.ultimate_mega1.manifest import (
    ALL_FUNCTIONS,
    CHILDREN,
    FUNCTION_COUNT,
    NF_IDS,
)
from src.ultimate_mega1.pr303 import (
    replay_witness_without_network,
    seed_replay_witness_from_message,
)
from src.ultimate_mega1.pr305 import (
    encode_prefix_balance_and_lifetimes,
    solve_financing_order_variant,
)
from src.ultimate_mega1.pr306 import reject_cosmetic_price_anomaly
from src.ultimate_mega1.pr308 import propagate_queue_position_bounds
from src.ultimate_mega1.pr310 import plan_claim_acquisition_and_settlement
from src.ultimate_mega1.pr312 import construct_balanced_v4_plan
from src.ultimate_mega1.pr317 import verify_disjoint_complete_partition
from src.ultimate_mega1.pr321 import validate_prefunded_crossvenue_plan
from src.ultimate_mega1.pr322 import read_l2_sequencer_health_witness
from src.ultimate_mega1.pr324 import draw_independent_sentinel_cells
from src.ultimate_mega1.pr326 import update_anytime_evidence_state


def test_exact_owner_ranges_and_every_symbol_imports() -> None:
    assert tuple(RESIDUAL_CHILDREN) == tuple(range(287, 303))
    assert RESIDUAL_COUNT == 64
    assert RESIDUAL_NF_IDS == tuple(range(833, 897))
    assert len(RESIDUAL_FUNCTIONS) == len(set(RESIDUAL_FUNCTIONS)) == 64
    for child, rows in RESIDUAL_CHILDREN.items():
        module = importlib.import_module(f"src.mega8_08.pr{child}")
        for _nf, name in rows:
            assert callable(getattr(module, name))

    assert tuple(CHILDREN) == tuple(range(303, 327))
    assert FUNCTION_COUNT == 120
    assert NF_IDS == tuple(range(897, 1017))
    assert len(ALL_FUNCTIONS) == len(set(ALL_FUNCTIONS)) == 120
    for child, rows in CHILDREN.items():
        module = importlib.import_module(f"src.ultimate_mega1.pr{child}")
        for _nf, name in rows:
            assert callable(getattr(module, name))


def test_closure_partition_is_exactly_1016_once() -> None:
    assert_static_closure_partition()
    assert tuple(CLOSURE_PACKAGES) == tuple(range(327, 353))
    assert len(NF_TO_CLOSURE) == 1016
    assert tuple(sorted(NF_TO_CLOSURE)) == tuple(range(1, 1017))


def test_replay_witness_is_incomplete_when_account_missing_and_network_is_forbidden() -> None:
    seed = seed_replay_witness_from_message(
        {"account_metas": ("a", "b")},
        {"slot": 42, "bank_context": "bank:42", "accounts": {"a": {"lamports": 1}}},
    )
    assert seed.status == "INCOMPLETE"
    assert seed.payload["missing_dependencies"] == ("b",)
    with pytest.raises(UltimateMegaError, match="HIDDEN_NETWORK_ACCESS"):
        replay_witness_without_network(
            {"closure_complete": True, "missing_dependencies": ()},
            observed_result={"ok": True},
            expected_result={"ok": True},
            network_accessed=True,
        )


def test_financing_prefix_and_cycle_fail_closed() -> None:
    with pytest.raises(UltimateMegaError, match="FEE_BOOTSTRAP_MISSING"):
        encode_prefix_balance_and_lifetimes(
            {"native": 1},
            (),
            upfront_fee=2,
        )
    unsat = solve_financing_order_variant(2, ((0, 1), (1, 0)))
    assert unsat.status == "BLOCKED"
    assert unsat.payload["solver_status"] == "UNSAT"


def test_token_ui_change_is_not_profit() -> None:
    report = reject_cosmetic_price_anomaly(
        raw_value_before=100,
        raw_value_after=100,
        ui_value_before=100,
        ui_value_after=200,
    )
    assert report.payload["classification"] == "COSMETIC"
    assert report.payload["profitable_candidate"] is False


def test_l2_queue_does_not_assume_unknown_cancel_is_ahead() -> None:
    result = propagate_queue_position_bounds(
        initial_quantity_ahead=10,
        events=({"kind": "cancel_unknown", "quantity": 3},),
        l3_exact=False,
    )
    assert result.payload["optimistic_quantity_ahead"] == 10
    assert result.payload["pessimistic_quantity_ahead"] == 13


def test_temporal_claim_rejects_flash_debt() -> None:
    with pytest.raises(UltimateMegaError, match="FLASH_DEBT_WOULD_PERSIST"):
        plan_claim_acquisition_and_settlement(
            {"claim": "x"},
            transferable=True,
            capital_lock=1,
            outstanding_flash_debt=1,
        )


def test_v4_open_delta_and_outcome_overlap_fail_closed() -> None:
    with pytest.raises(UltimateMegaError, match="OPEN_CURRENCY_OBLIGATION"):
        construct_balanced_v4_plan({"USDC": -5}, settlement_steps={"USDC": 4})
    with pytest.raises(UltimateMegaError, match="OVERLAPPING_PARTITION"):
        verify_disjoint_complete_partition(outcome_count=3, bitsets=(0b011, 0b010))


def test_crossvenue_requires_prefunding_and_sequencer_health() -> None:
    with pytest.raises(UltimateMegaError, match="UNFUNDED_DESTINATION"):
        validate_prefunded_crossvenue_plan(
            source_inventory=10,
            destination_inventory=0,
            source_required=5,
            destination_required=1,
            withdrawal_enabled=True,
        )
    with pytest.raises(UltimateMegaError, match="SEQUENCER_DOWN"):
        read_l2_sequencer_health_witness(
            status=1,
            status_started_at=10,
            feed_updated_at=20,
            now=21,
            max_feed_age=10,
        )


def test_sentinel_draw_is_deterministic_and_independent_of_ranker() -> None:
    frame = {"available": ("a", "b", "c", "d")}
    first = draw_independent_sentinel_cells(
        frame, seed_commitment="seed", sample_size=2
    )
    second = draw_independent_sentinel_cells(
        frame, seed_commitment="seed", sample_size=2
    )
    assert first.payload["selected"] == second.payload["selected"]
    assert first.payload["ranker_used"] is False


def test_sequential_evidence_is_idempotent_and_bounded() -> None:
    initial = {"event_ids": (), "count": 0, "sum": 0}
    updated = update_anytime_evidence_state(
        initial,
        event_id="e1",
        value=1,
        lower_bound=0,
        upper_bound=1,
    )
    with pytest.raises(UltimateMegaError, match="DUPLICATE_SAMPLE"):
        update_anytime_evidence_state(
            updated.payload,
            event_id="e1",
            value=1,
            lower_bound=0,
            upper_bound=1,
        )
    with pytest.raises(UltimateMegaError, match="ASSUMPTION_BROKEN"):
        update_anytime_evidence_state(
            initial,
            event_id="e2",
            value=2,
            lower_bound=0,
            upper_bound=1,
        )


def test_solver_and_shadow_governance_never_grant_live_authority() -> None:
    constraints = normalize_intent_constraints(
        expiry=100,
        now=10,
        min_output=90,
        allowed_recipients=("user",),
        consent_present=True,
    )
    priced = price_solver_fill(
        offered_output=100,
        user_min_output=constraints.payload["min_output"],
        solver_fee=5,
        gas_or_execution_fee=1,
    )
    assert priced.payload["user_net_output"] == 95

    route = build_sui_atomic_route(
        objects=(("pool", 1), ("coin", 2)),
        operations=("borrow", "swap", "repay"),
        repayment_present=True,
    )
    assert route.payload["unsigned"] is True

    proposal = submit_strategy_proposal(
        strategy_id="s",
        evidence_hashes=("e",),
        max_loss=1,
        requested_stage="SHADOW",
    )
    promotion = approve_shadow_promotion(
        strategy_id="s",
        review_passed=True,
        scope_hash=proposal.contract,
        expiry=100,
        now=1,
    )
    assert promotion.payload["stage"] == "SHADOW"
    assert promotion.payload["live_enabled"] is False
    with pytest.raises(Mega808Error, match="LIVE_PROMOTION_NOT_AUTHORIZED"):
        submit_strategy_proposal(
            strategy_id="s",
            evidence_hashes=("e",),
            max_loss=1,
            requested_stage="LIVE",
        )
