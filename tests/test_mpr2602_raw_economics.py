"""Raw account fixtures -> actual finalizer -> adapter/reconciler/qualification.

This isolates coherent simulation/economic boundaries; no atomic planner is
called, so these tests are not a full flashloan execution qualification.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.execution.exact_simulation import (
    ExactSimulationFinalizer,
    ExactSimulationError,
)
from src.execution.models import (
    BlockhashContext,
    ComputeBudgetPolicy,
    PlannedInstruction,
    TransactionPlan,
)
from src.execution.economic_reconciliation import (
    AssetKey,
    EconomicReconciler,
    NATIVE_SOL_ASSET,
)
from src.execution.economic_reconciliation.exact_adapter import (
    evidence_from_raw_simulation,
)
from src.execution.economic_reconciliation.mega_pr02_proof import (
    ConservativeAssetQuote,
    ConservativeValuationSnapshot,
    MarginfiRegistrySnapshot,
    QualificationReason,
    QualificationStatus,
    RawStateEconomicProofAuthority,
)
from src.execution.state_evidence_pr115 import PR115DecodePolicy, SPL_TOKEN_PROGRAM_ID
from tests.test_mpr2602_marginfi_raw_decoder import (
    ADDRESSES,
    BANK,
    MARGIN,
    MINT,
    PAYER,
    PROGRAM,
    VAULT,
    _key,
    _raw,
    vectors,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]
SETTLEMENT = str(Pubkey.from_bytes(bytes([19]) * 32))
ASSET = AssetKey(MINT, SPL_TOKEN_PROGRAM_ID, 6)


async def finalized_fixture(token_profit=20_000):
    pre, post, context = vectors()
    account = bytearray(165)
    _key(account, 0, MINT)
    _key(account, 32, PAYER)
    account[64:72] = (100).to_bytes(8, "little")
    account[108] = 1
    pre.append(_raw(account, SPL_TOKEN_PROGRAM_ID))
    account[64:72] = (100 + token_profit).to_bytes(8, "little")
    post.append(_raw(account, SPL_TOKEN_PROGRAM_ID))
    addresses = (*ADDRESSES, SETTLEMENT)

    class Rpc:
        calls = 0

        async def call(self, method, params):
            if method == "getBlockHeight":
                return 50
            if method == "isBlockhashValid":
                return {"context": {"slot": 22}, "value": True}
            if method == "getFeeForMessage":
                return {"context": {"slot": 22}, "value": 5000}
            assert method == "simulateTransaction"
            assert params[1]["accounts"]["addresses"] == list(addresses)
            assert params[1]["sigVerify"] is False
            self.calls += 1
            return {
                "context": {"slot": 22},
                "value": {
                    "err": None,
                    "logs": [],
                    "unitsConsumed": 100_000,
                    "accounts": post,
                    "loadedAccountsDataSize": 5570,
                },
            }

    payer = Pubkey.from_string(PAYER)
    plan = TransactionPlan(
        opportunity_id="economic-state-vector",
        payer=payer,
        instructions=(
            PlannedInstruction(
                Instruction(Pubkey.default(), b"offline", []),
                role="application",
                name="state-vector",
            ),
        ),
        compute_budget_policy=ComputeBudgetPolicy(micro_lamports_per_cu=7),
        required_signers=(payer,),
        quote_slot=22,
        market_state_slot=22,
        oracle_slot=22,
        monitored_accounts=tuple(
            Pubkey.from_string(address) for address in addresses[1:]
        ),
    )
    blockhash = BlockhashContext(
        Hash.from_bytes(bytes(range(32))), 100, 22, 0.0, "confirmed"
    )
    rpc = Rpc()
    finalized = await ExactSimulationFinalizer(rpc).finalize(plan, blockhash)
    assert rpc.calls == 2
    return finalized, tuple(pre), PR115DecodePolicy(marginfi=context)


def adapt(finalized, pre, policy, **changes):
    args = dict(
        pre_state_accounts=pre,
        pre_state_slot=22,
        policy=policy,
        settlement_asset=ASSET,
        assets=(ASSET,),
        payer=PAYER,
        principal=1000,
    )
    args.update(changes)
    return evidence_from_raw_simulation(finalized, **args)


def valuation(*, include_native=True, slot=22):
    quotes = [ConservativeAssetQuote(ASSET, 1, "c" * 64, slot)]
    if include_native:
        quotes.append(ConservativeAssetQuote(NATIVE_SOL_ASSET, 1, "d" * 64, slot))
    return ConservativeValuationSnapshot("offline-test-unit", tuple(quotes), slot, 2, 0)


def qualify(evidence, report, raw, values):
    registry = MarginfiRegistrySnapshot.build(
        program_id=PROGRAM,
        banks={BANK},
        liquidity_vaults={VAULT},
        margin_accounts={MARGIN},
    )
    return RawStateEconomicProofAuthority().qualify(
        evidence=evidence,
        report=report,
        raw_state=raw,
        registry=registry,
        valuation=values,
    )


async def test_decoded_wallet_profit_excludes_lender_vault_and_qualifies():
    finalized, pre, policy = await finalized_fixture()
    evidence, raw, digest = adapt(finalized, pre, policy)
    observations = {item.address: item for item in evidence.tokens}
    assert observations[SETTLEMENT].include_in_wallet_delta
    assert not observations[VAULT].include_in_wallet_delta
    report = EconomicReconciler().reconcile(evidence)
    assert report.complete, report.diagnostic
    assert report.settlement_net == 20_000
    result = qualify(evidence, report, raw, valuation())
    assert result.qualified, result.diagnostic
    assert result.quote_net == 15_000
    assert len(digest) == 64
    assert report.message_hash == finalized.compiled.message_hash


async def test_included_raw_network_fee_and_priority_are_not_charged_twice():
    finalized, pre, policy = await finalized_fixture()
    evidence, raw, _ = adapt(finalized, pre, policy)
    assert evidence.fees.base_network_fee_lamports == 4999
    assert evidence.fees.priority_fee_lamports == 1
    report = EconomicReconciler().reconcile(evidence)
    assert report.complete, report.diagnostic
    native = next(item for item in report.breakdowns if item.asset == NATIVE_SOL_ASSET)
    assert native.net == -5000
    assert native.network_fee + native.priority_fee == 5000
    assert qualify(evidence, report, raw, valuation()).quote_net == 15_000


async def test_positive_token_delta_with_negative_total_value_is_rejected():
    finalized, pre, policy = await finalized_fixture(token_profit=100)
    evidence, raw, _ = adapt(finalized, pre, policy)
    report = EconomicReconciler().reconcile(evidence)
    assert report.complete, report.diagnostic
    assert report.settlement_net == 100
    result = qualify(evidence, report, raw, valuation())
    assert not result.qualified
    assert result.status is QualificationStatus.PROVEN_LOSS
    assert result.reason is QualificationReason.NEGATIVE_CROSS_ASSET_NET
    assert result.quote_net == -4900


@pytest.mark.parametrize(
    "values, reason",
    [
        (valuation(include_native=False), QualificationReason.VALUATION_MISSING),
        (valuation(slot=1), QualificationReason.VALUATION_STALE),
    ],
)
async def test_absent_native_valuation_or_stale_quotes_cannot_qualify(values, reason):
    finalized, pre, policy = await finalized_fixture()
    evidence, raw, _ = adapt(finalized, pre, policy)
    report = EconomicReconciler().reconcile(evidence)
    assert report.complete, report.diagnostic
    result = qualify(evidence, report, raw, values)
    assert not result.qualified
    assert result.reason is reason


async def test_adapter_rejects_unproven_pre_post_slot_pair():
    finalized, pre, policy = await finalized_fixture()
    with pytest.raises(ValueError, match="INDETERMINATE_STATE_PAIR"):
        adapt(finalized, pre, policy, pre_state_slot=21)


async def test_adapter_rejects_planner_principal_or_asset_drift():
    finalized, pre, policy = await finalized_fixture()
    with pytest.raises(ValueError, match="principal"):
        adapt(finalized, pre, policy, principal=2000)
    with pytest.raises(ValueError, match="settlement asset"):
        adapt(finalized, pre, policy, settlement_asset=replace(ASSET, decimals=9))


async def test_adapter_rejects_changed_compiled_bytes_with_copied_hash_label():
    finalized, pre, policy = await finalized_fixture()
    message = finalized.compiled.serialized_message
    changed = bytes([message[0] ^ 1]) + message[1:]
    forged = replace(
        finalized, compiled=replace(finalized.compiled, serialized_message=changed)
    )
    with pytest.raises((ValueError, ExactSimulationError)):
        adapt(forged, pre, policy)
