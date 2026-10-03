from dataclasses import replace
import pytest
from src.mechanism_discovery.intent_graph import ClearingIntent, clear_intents
from src.lending.financing import FinancingEvidence, FinancingContractError
from src.lending.shadow_capacity import ShadowFundingCapacity, debt_is_closed


def test_clearing_conserves_assets_per_user_limits_cancels_and_expiry():
    left = ClearingIntent("a", "A", "B", 10, 20, 10, 100)
    right = ClearingIntent("b", "B", "A", 20, 10, 10, 100)
    result = clear_intents((right, left), now_ns=20, lot_sizes=(("A", 10), ("B", 20)))
    assert result.matched_intent_count == 2
    assert result.fills[0].left_sell_atoms == 10
    assert result.fills[0].right_sell_atoms == 20
    assert dict(result.remaining_sell_atoms) == {"a": 0, "b": 0}
    assert not result.execution_right
    for invalid in (
        replace(left, minimum_buy_atoms=21),
        replace(left, canceled_at_ns=20),
        replace(left, expires_at_ns=20),
        replace(left, domain="other"),
        replace(left, access_id="private"),
    ):
        assert not clear_intents(
            (invalid, right), now_ns=20, lot_sizes=(("A", 10), ("B", 20))
        ).fills


def test_funding_is_revision_bound_and_repayment_is_per_asset():
    proof = FinancingEvidence("lender", "program", 1, "a" * 64, "decoder", 1)
    terms = ShadowFundingCapacity(
        proof, "chain", "USDC/rev1", 1000, 1, 1000, 1, 10, 100, True, True
    )
    assert (
        terms.repayment(999, now_ns=20, domain="chain", asset_identity="USDC/rev1")
        == 1001
    )
    for changes in (
        {"asset_identity": "USDC/rev2"},
        {"domain": "other"},
        {"now_ns": 100},
    ):
        args = {
            "now_ns": 20,
            "domain": "chain",
            "asset_identity": "USDC/rev1",
            **changes,
        }
        with pytest.raises(FinancingContractError):
            terms.repayment(999, **args)
    assert not debt_is_closed(
        outputs_by_asset={"SOL": 10**9},
        repayments_by_asset={"USDC/rev1": 1},
        native_wallet_atoms=10,
        native_cost_atoms=1,
    )
    assert not debt_is_closed(
        outputs_by_asset={"USDC/rev1": 1001},
        repayments_by_asset={"USDC/rev1": 1001},
        native_wallet_atoms=0,
        native_cost_atoms=1,
    )
    assert debt_is_closed(
        outputs_by_asset={"USDC/rev1": 1001},
        repayments_by_asset={"USDC/rev1": 1001},
        native_wallet_atoms=1,
        native_cost_atoms=1,
    )
