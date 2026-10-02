from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest

from src.durability import DurableLifecycleStore
from src.economics.capital import CapitalPolicy, NativeCostBreakdown
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.market.observations import ObservationGeneration
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.exact_cpmm_capacity import (
    CapacityEconomics,
    CpmmEvaluationError,
    CpmmEvaluationRejection,
    ExactCpmmEdgeEvaluation,
    ExactCpmmRoutePlan,
    PINNED_CPMM_MODEL_REVISION,
    QualifiedCpmmState,
    QualifiedRaydiumCpmmAdapter,
    RAYDIUM_CPMM_PROGRAM_ID,
    SolanaAssetIdentity,
    evaluate_exact_cpmm_route,
    evaluate_sampled_cpmm_capacity,
)

pytestmark = pytest.mark.unit

NOW = 1_000.0
GENESIS = "solana-mainnet-genesis-fixture"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
GENERATION = ObservationGeneration(
    genesis_hash=GENESIS,
    provider_generation="fixture-provider-v1",
    asset_generation="fixture-assets-v1",
    policy_generation="shadow-only-v1",
    code_generation="exact-cpmm-capacity-v1",
)


def _asset(mint: str, **changes: object) -> SolanaAssetIdentity:
    values: dict[str, object] = {
        "domain": "solana-mainnet",
        "genesis_hash": GENESIS,
        "mint": mint,
        "token_program": TOKEN_PROGRAM,
        "token_revision": "spl-token-v1",
        "decimals": 9,
    }
    values.update(changes)
    return SolanaAssetIdentity(**values)  # type: ignore[arg-type]


A, B, C, D = (_asset(mint) for mint in ("WSOL", "TOKEN-B", "TOKEN-C", "TOKEN-D"))


def _pool(
    index: int,
    asset_a: SolanaAssetIdentity,
    asset_b: SolanaAssetIdentity,
    reserves: tuple[int, int],
    **changes: object,
) -> QualifiedCpmmState:
    values: dict[str, object] = {
        "venue": VenueIdentity(RAYDIUM_CPMM_PROGRAM_ID, f"pool-{index}"),
        "asset_a": asset_a,
        "asset_b": asset_b,
        "reserve_a": reserves[0],
        "reserve_b": reserves[1],
        "fee_bps": 25,
        "slot": 100,
        "observed_at": NOW - 1,
        "expires_at": NOW + 1,
        "generation": GENERATION,
    }
    values.update(changes)
    return QualifiedCpmmState(**values)  # type: ignore[arg-type]


def _three_hop_plan() -> ExactCpmmRoutePlan:
    # The finite grid 10/20/30 has gross results 6/9/8. With a 7-lamport
    # network fee, only 20 and 30 pass and PR118 must select 20 (net 2).
    return ExactCpmmRoutePlan(
        A,
        (
            _pool(1, A, B, (333, 9_170)),
            _pool(2, B, C, (2_350, 6_118)),
            _pool(3, C, A, (8_573, 266)),
        ),
    )


def _policy() -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=0,
        minimum_net_profit_lamports=1,
        maximum_priority_fee_lamports=10_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=10_000,
        contingency_lamports=0,
        maximum_flash_loan_lamports=1_000_000,
    )


def _coordinator(tmp_path: Path) -> DurableCapitalCoordinator:
    return DurableCapitalCoordinator(
        store=DurableLifecycleStore(tmp_path / "capital.db"), policy=_policy()
    )


def _wallet() -> WalletBalanceSnapshot:
    return WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=10_000_000,
        context_slot=100,
        captured_at_ns=time.time_ns(),
        cluster_genesis=GENESIS,
    )


def test_asset_identity_keeps_domain_genesis_and_revision() -> None:
    same_symbol_other_chain = replace(A, domain="evm-mainnet")
    same_address_other_genesis = replace(A, genesis_hash="other-genesis")
    assert (
        len(
            {
                A.identity,
                same_symbol_other_chain.identity,
                same_address_other_genesis.identity,
            }
        )
        == 3
    )


def test_pinned_cpmm_vector_is_integer_exact_and_updates_state() -> None:
    state = _pool(1, A, B, (1_000_000, 2_000_000))
    result = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=A, requested_input=10_000
    )

    # Independent integer vector: floor(2_000_000*10_000*9_975 /
    # (1_000_000*10_000 + 10_000*9_975)).
    assert result.conservative_output == 19_752
    assert result.requested_input == result.consumed_input == 10_000
    assert result.residual_input == 0
    assert result.state_after.reserve_a == 1_010_000
    assert result.state_after.reserve_b == 1_980_248
    assert result.to_observation().exact_output_for(10_000) == 19_752


def test_new_amount_gets_fresh_nonlinear_evaluation_and_identity() -> None:
    adapter = QualifiedRaydiumCpmmAdapter()
    state = _pool(1, A, B, (1_000, 2_000))
    ten = adapter.evaluate(state, input_asset=A, requested_input=10)
    hundred = adapter.evaluate(state, input_asset=A, requested_input=100)

    assert hundred.conservative_output != ten.conservative_output * 10
    assert hundred.evaluation_id != ten.evaluation_id
    with pytest.raises(ValueError, match="exact request evidence"):
        ten.to_observation().exact_output_for(100)


@pytest.mark.parametrize("amount", [True, 10.0, 0, -1])
def test_non_integer_or_non_positive_amounts_fail_closed(amount: object) -> None:
    with pytest.raises(CpmmEvaluationError) as error:
        QualifiedRaydiumCpmmAdapter().evaluate(
            _pool(1, A, B, (1_000, 2_000)),
            input_asset=A,
            requested_input=amount,  # type: ignore[arg-type]
        )
    assert error.value.reason is CpmmEvaluationRejection.INVALID_AMOUNT


def test_residual_contract_cannot_lose_unconsumed_input() -> None:
    state = _pool(1, A, B, (1_000, 2_000))
    after = replace(state, reserve_a=1_100, reserve_b=1_900)
    partial = ExactCpmmEdgeEvaluation(
        requested_input=101,
        consumed_input=100,
        residual_input=1,
        expected_output=100,
        conservative_output=100,
        embedded_fee_input=0,
        input_asset=A,
        output_asset=B,
        state_before=state,
        state_after=after,
    )
    assert partial.requested_input == partial.consumed_input + partial.residual_input
    with pytest.raises(ValueError, match="consumed plus residual"):
        replace(partial, residual_input=0)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"model_revision": "unknown"},
            CpmmEvaluationRejection.UNSUPPORTED_MODEL_REVISION,
        ),
        (
            {"decoder_revision": "unknown"},
            CpmmEvaluationRejection.UNSUPPORTED_DECODER_REVISION,
        ),
        (
            {"venue": VenueIdentity("other-program", "pool")},
            CpmmEvaluationRejection.WRONG_PROGRAM,
        ),
    ],
)
def test_unqualified_program_model_or_decoder_is_rejected(
    changes: dict[str, object], reason: CpmmEvaluationRejection
) -> None:
    state = replace(_pool(1, A, B, (1_000, 2_000)), **changes)
    with pytest.raises(CpmmEvaluationError) as error:
        QualifiedRaydiumCpmmAdapter().evaluate(state, input_asset=A, requested_input=10)
    assert error.value.reason is reason


def test_token_revision_and_route_generation_fail_closed() -> None:
    fee_token = replace(A, token_revision="token-2022-transfer-fee-v1")
    state = _pool(1, fee_token, B, (1_000, 2_000))
    with pytest.raises(CpmmEvaluationError) as error:
        QualifiedRaydiumCpmmAdapter().evaluate(
            state, input_asset=fee_token, requested_input=10
        )
    assert error.value.reason is CpmmEvaluationRejection.UNSUPPORTED_TOKEN_REVISION

    changed_generation = ObservationGeneration(
        genesis_hash=GENESIS, code_generation="other-code"
    )
    pools = list(_three_hop_plan().pools)
    pools[-1] = replace(pools[-1], generation=changed_generation)
    with pytest.raises(ValueError, match="mix state generations"):
        ExactCpmmRoutePlan(A, tuple(pools))


def test_three_and_four_hop_routes_reuse_pr559_exact_coupling() -> None:
    three = evaluate_exact_cpmm_route(_three_hop_plan(), input_amount=20, now=NOW)
    assert three.graph_route.amounts_base_units == (20, 494, 1_059, 29)
    assert three.conservative_output == 29

    four_plan = ExactCpmmRoutePlan(
        A,
        (
            _pool(1, A, B, (1_000, 2_000)),
            _pool(2, B, C, (1_000, 2_000)),
            _pool(3, C, D, (1_000, 2_000)),
            _pool(4, D, A, (1_000, 2_000)),
        ),
    )
    four = evaluate_exact_cpmm_route(four_plan, input_amount=10, now=NOW)
    assert len(four.legs) == 4
    assert four.graph_route.amounts_base_units[0] == 10
    assert four.graph_route.amounts_base_units[-1] > 10


def test_stale_state_and_repeated_venue_are_rejected() -> None:
    with pytest.raises(CpmmEvaluationError) as error:
        evaluate_exact_cpmm_route(_three_hop_plan(), input_amount=20, now=NOW + 2)
    assert error.value.reason is CpmmEvaluationRejection.NO_EXACT_GRAPH_CANDIDATE

    pools = list(_three_hop_plan().pools)
    pools[-1] = replace(pools[-1], venue=pools[0].venue)
    with pytest.raises(ValueError, match="repeat a venue"):
        ExactCpmmRoutePlan(A, tuple(pools))


def test_sampled_capacity_selects_best_verified_non_monotonic_point(
    tmp_path: Path,
) -> None:
    report = evaluate_sampled_cpmm_capacity(
        _three_hop_plan(),
        amounts=(30, 10, 20),
        economics=CapacityEconomics(
            settlement_asset_id="WSOL",
            flash_fee_bps=0,
            protocol_rounding_atoms=0,
            native_costs=NativeCostBreakdown(base_network_fee_lamports=7),
        ),
        coordinator=_coordinator(tmp_path),
        wallet_snapshot=_wallet(),
        now=NOW,
    )

    assert tuple(point.amount for point in report.points) == (10, 20, 30)
    assert tuple(point.conservative_net_atoms for point in report.points) == (-1, 2, 1)
    assert tuple(point.allowed for point in report.points) == (False, True, True)
    assert report.selected_amount == 20
    assert report.budget_status == "evaluated-all-points"
    assert len({point.evaluation_id for point in report.points}) == 3
    assert all(len(point.ordered_leg_evaluation_ids) == 3 for point in report.points)
    assert all(point.ledger.route_provenance_hash for point in report.points)


def test_capacity_budget_exhaustion_is_explicit(tmp_path: Path) -> None:
    report = evaluate_sampled_cpmm_capacity(
        _three_hop_plan(),
        amounts=(10, 20, 30),
        economics=CapacityEconomics(
            settlement_asset_id="WSOL",
            flash_fee_bps=0,
            protocol_rounding_atoms=0,
            native_costs=NativeCostBreakdown(base_network_fee_lamports=0),
        ),
        coordinator=_coordinator(tmp_path),
        wallet_snapshot=_wallet(),
        now=NOW,
        max_evaluations=2,
    )
    assert tuple(point.amount for point in report.points) == (10, 20)
    assert report.budget_status == "request-budget-exhausted"


def test_model_revision_changes_evidence_identity_before_admission() -> None:
    state = _pool(1, A, B, (1_000, 2_000))
    base = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=A, requested_input=10
    )
    assert state.model_revision == PINNED_CPMM_MODEL_REVISION
    assert (
        base.evaluation_id
        != replace(
            base,
            state_before=replace(state, model_revision="future-unqualified"),
        ).evaluation_id
    )
