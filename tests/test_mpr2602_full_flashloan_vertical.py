"""Regression for the real-provider admission blocker, not a full-path PASS.

The fixture capital receipt is only an inert input to the pre-simulation
admission test. No reservation, live conformance or human approval is asserted.
"""

from __future__ import annotations

from dataclasses import replace
import base64
import copy
import hashlib
import json

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.execution.economic_reconciliation import AssetKey
from src.execution.exact_simulation import ExactSimulationFinalizer
from src.execution.models import BlockhashContext
from src.execution.models import ComputeBudgetPolicy
from src.execution.state_evidence_pr115 import (
    PR115DecodePolicy,
    PR115ReadonlyAccountBinding,
)
from src.execution.economic_reconciliation import NATIVE_SOL_ASSET
from src.execution.economic_reconciliation.mega_pr02_proof import (
    ConservativeAssetQuote,
    ConservativeValuationSnapshot,
    MarginfiRegistrySnapshot,
    QualificationStatus,
)
from src.providers.marginfi import MarginfiAccountReader, RpcAccount
from src.providers.marginfi.provider import MarginfiSourceVectorEvidence
from src.providers.jupiter.router import (
    JupiterInstructionBundle,
    JupiterRawInstruction,
    RawAccountMeta,
)
from src.planning.atomic_marginfi_jupiter import (
    AtomicPlannerPolicy,
    AtomicPlannerRequest,
    CapitalReservationEvidence,
)
from tests.test_mpr2602_marginfi_raw_decoder import vectors, mutate_data
from tests.test_mpr2602_marginfi_raw_decoder import (
    ADDRESSES as RAW_ADDRESSES,
    PAYER as RAW_PAYER,
    BANK as RAW_BANK,
    MARGIN as RAW_MARGIN,
    GROUP as RAW_GROUP,
    VAULT as RAW_VAULT,
    ORACLE as RAW_ORACLE,
    PROGRAM as RAW_PROGRAM,
    _key,
    _raw,
)
from src.paper_shadow.atomic_vertical import (
    AtomicPlannerSimulationReconciliationVertical,
    AtomicVerticalCandidate,
    AtomicVerticalError,
)
from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerError,
    AtomicPlannerRejectionCode,
)
from src.providers.marginfi import MarginfiFlashLoanProvider, load_marginfi_contract_pin
from tests.providers.test_marginfi_provider import (
    AUTHORITY,
    DESTINATION,
    REPAYMENT,
    TOKEN,
    USDC,
    _snapshot,
)
from tests.test_pr034_atomic_marginfi_jupiter import NOW, _policy, _request

pytestmark = pytest.mark.unit


def actual_provider_request():
    pin = load_marginfi_contract_pin()
    provider = MarginfiFlashLoanProvider(pin)
    snapshot = _snapshot(pin)
    source = _request()
    request = replace(
        source,
        marginfi_snapshot=snapshot,
        payer=Pubkey.from_string(AUTHORITY),
        destination_token_account=Pubkey.from_string(DESTINATION),
        repayment_source_token_account=Pubkey.from_string(REPAYMENT),
        leg_a=replace(source.leg_a, input_mint=USDC),
        leg_b=replace(
            source.leg_b, output_mint=USDC, out_amount=1300, other_amount_threshold=1250
        ),
    )
    return provider, request


def test_actual_source_decoded_provider_can_prepare_and_finalize_local_bracket():
    provider, request = actual_provider_request()
    prepared = provider.prepare(
        snapshot=request.marginfi_snapshot,
        amount=1000,
        destination_token_account=DESTINATION,
        repayment_source_token_account=REPAYMENT,
        min_final_balance=1250,
    )
    bracket = provider.finalize(
        prepared, (prepared.borrow_instruction, prepared.repay_instruction)
    )
    assert prepared.origination_fee == 125
    assert bracket.required_repayment == 1125
    assert len(bracket.instructions) == 4
    assert bracket.instructions[0].data[:8] == provider.pin.ix_discriminator(
        "lending_account_start_flashloan"
    )
    assert int.from_bytes(bracket.instructions[0].data[8:], "little") == 3
    assert getattr(provider, "execution_conformance_verified", False) is False


@pytest.mark.asyncio
async def test_actual_provider_cannot_be_promoted_to_full_vertical_with_fixture_bool():
    provider, request = actual_provider_request()

    class NoSimulationRpc:
        calls = 0

        async def call(self, method, params):
            self.calls += 1
            raise AssertionError("unqualified provider must not reach simulation")

    rpc = NoSimulationRpc()
    planner = AtomicMarginfiJupiterPlanner(provider, _policy(), clock=lambda: NOW)
    vertical = AtomicPlannerSimulationReconciliationVertical(
        planner, ExactSimulationFinalizer(rpc)
    )
    candidate = AtomicVerticalCandidate(
        request=request,
        blockhash=BlockhashContext(
            Hash.from_bytes(bytes(range(32))), 1000, 901, NOW, "confirmed"
        ),
        settlement_asset=AssetKey(USDC, TOKEN, 6),
    )
    with pytest.raises(AtomicPlannerError) as error:
        await vertical.run(candidate)
    assert error.value.code is AtomicPlannerRejectionCode.MARGINFI_CONFORMANCE_REQUIRED
    assert rpc.calls == 0


JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
WSOL = "So11111111111111111111111111111111111111112"
WALLET_TOKEN = str(Pubkey.from_bytes(bytes([19]) * 32))
BRIDGE_TOKEN = str(Pubkey.from_bytes(bytes([20]) * 32))
ORACLE_OWNER = str(Pubkey.from_bytes(bytes([21]) * 32))


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _source_instructions():
    """Independent source-derived account metas and discriminators, no provider call."""

    def meta(key, signer=False, writable=False):
        return AccountMeta(Pubkey.from_string(key), signer, writable)

    program = Pubkey.from_string(RAW_PROGRAM)
    vault_authority = Pubkey.find_program_address(
        [b"liquidity_vault_auth", bytes(Pubkey.from_string(RAW_BANK))], program
    )[0]
    start = Instruction(
        program,
        bytes.fromhex("0e8321dc51bab46b") + (5).to_bytes(8, "little"),
        [
            meta(RAW_MARGIN, writable=True),
            meta(RAW_PAYER, signer=True),
            meta("Sysvar1nstructions1111111111111111111111111"),
        ],
    )
    borrow = Instruction(
        program,
        bytes.fromhex("047e74353005d41f") + (1000).to_bytes(8, "little"),
        [
            meta(RAW_GROUP),
            meta(RAW_MARGIN, writable=True),
            meta(RAW_PAYER, signer=True),
            meta(RAW_BANK, writable=True),
            meta(WALLET_TOKEN, writable=True),
            meta(str(vault_authority)),
            meta(RAW_VAULT, writable=True),
            meta(TOKEN),
            meta(RAW_BANK),
            meta(RAW_ORACLE),
        ],
    )
    repay = Instruction(
        program,
        bytes.fromhex("4fd1acb1de33ad97") + (1125).to_bytes(8, "little") + b"\x01\x01",
        [
            meta(RAW_GROUP),
            meta(RAW_MARGIN, writable=True),
            meta(RAW_PAYER, signer=True),
            meta(RAW_BANK, writable=True),
            meta(WALLET_TOKEN, writable=True),
            meta(RAW_VAULT, writable=True),
            meta(TOKEN),
        ],
    )
    end = Instruction(
        program,
        bytes.fromhex("697cc96a9902089c"),
        [
            meta(RAW_MARGIN, writable=True),
            meta(RAW_PAYER, signer=True),
            meta(RAW_BANK),
            meta(RAW_ORACLE),
        ],
    )
    return start, borrow, repay, end


def offline_vertical_fixture(*, token_profit=20_000):
    """Actual account reader/provider; only build/RPC boundary data are synthetic."""
    pre, post, context = vectors()
    for states in (pre, post):
        mutate_data(states, 2, 8, bytes(Pubkey.from_string(USDC)))
        mutate_data(states, 4, 0, bytes(Pubkey.from_string(USDC)))
    pre_map, post_map = dict(zip(RAW_ADDRESSES, pre)), dict(zip(RAW_ADDRESSES, post))
    oracle = _raw(b"source-fixture-oracle-payload", ORACLE_OWNER)
    pre_map[RAW_ORACLE], post_map[RAW_ORACLE] = oracle, copy.deepcopy(oracle)
    for address, mint, initial, final in (
        (WALLET_TOKEN, USDC, 100, 100 + token_profit),
        (BRIDGE_TOKEN, WSOL, 0, 0),
    ):
        data = bytearray(165)
        _key(data, 0, mint)
        _key(data, 32, RAW_PAYER)
        data[108] = 1
        if mint == WSOL:
            data[109:113] = (1).to_bytes(4, "little")
            data[113:121] = (2_039_280).to_bytes(8, "little")
        data[64:72] = initial.to_bytes(8, "little")
        pre_map[address] = _raw(data, TOKEN)
        data[64:72] = final.to_bytes(8, "little")
        post_map[address] = _raw(data, TOKEN)
    pin = load_marginfi_contract_pin()

    class ReadonlyFixture:
        def get_multiple_accounts(self, addresses, *, min_context_slot=None):
            result = []
            for address in addresses:
                if address == pin.program_id:
                    result.append(
                        RpcAccount(
                            address, pin.raw["program_owner"], b"", executable=True
                        )
                    )
                else:
                    raw = pre_map[address]
                    result.append(
                        RpcAccount(
                            address,
                            raw["owner"],
                            base64.b64decode(raw["data"][0]),
                            raw["lamports"],
                        )
                    )
            return 22, tuple(result)

    snapshot = MarginfiAccountReader(pin, ReadonlyFixture(), clock=lambda: 1000).read(
        group=RAW_GROUP,
        margin_account=RAW_MARGIN,
        authority=RAW_PAYER,
        bank=RAW_BANK,
        symbol="USDC",
        amount=1000,
    )
    provider = MarginfiFlashLoanProvider(pin)
    expected = _source_instructions()
    source_vectors = MarginfiSourceVectorEvidence(
        pin.source_commit,
        _digest(pin.raw),
        snapshot.state_fingerprint,
        1000,
        WALLET_TOKEN,
        WALLET_TOKEN,
        tuple(hashlib.sha256(bytes(ix)).hexdigest() for ix in expected),
    )

    def bundle(input_mint, output_mint, amount, output, name):
        swap = JupiterRawInstruction(
            JUPITER,
            (
                RawAccountMeta(RAW_PAYER, True, False),
                RawAccountMeta(WALLET_TOKEN, False, True),
                RawAccountMeta(BRIDGE_TOKEN, False, True),
            ),
            base64.b64encode(name.encode()).decode(),
            name,
        )
        return JupiterInstructionBundle(
            input_mint,
            output_mint,
            amount,
            output,
            output,
            "ExactIn",
            0,
            ({"label": "offline-build-fixture"},),
            (),
            (),
            swap,
            None,
            (),
            None,
            {},
            {},
            1000.0,
        )

    request = AtomicPlannerRequest(
        opportunity_id="mpr2602-source-vertical",
        payer=Pubkey.from_string(RAW_PAYER),
        marginfi_snapshot=snapshot,
        borrow_amount=1000,
        destination_token_account=Pubkey.from_string(WALLET_TOKEN),
        repayment_source_token_account=Pubkey.from_string(WALLET_TOKEN),
        leg_a=bundle(USDC, WSOL, 1000, 1900, "route-a"),
        leg_b=bundle(WSOL, USDC, 1900, 21125, "route-b"),
        capital=CapitalReservationEvidence(
            "offline-fixture-capital",
            True,
            1000,
            "source-vector-paper",
            _digest({"scope": "offline-input-only"}),
        ),
        jupiter_contract_pin=_digest({"build": "isolated-source-fixture"}),
        discovery_slot=22,
        oracle_slot=22,
        monitored_accounts=tuple(
            Pubkey.from_string(address) for address in (RAW_GROUP, BRIDGE_TOKEN)
        ),
        marginfi_source_vectors=source_vectors,
    )
    planner = AtomicMarginfiJupiterPlanner(
        provider,
        AtomicPlannerPolicy(
            (RAW_PROGRAM, JUPITER),
            compute_budget_policy=ComputeBudgetPolicy(micro_lamports_per_cu=7),
        ),
        clock=lambda: 1000.0,
    )
    plan = planner.plan(request)
    monitored = (
        RAW_PAYER,
        *(str(key) for key in plan.transaction_plan.monitored_accounts),
    )

    class SimulationRpc:
        calls = 0

        async def call(self, method, params):
            if method == "getBlockHeight":
                return 50
            if method == "isBlockhashValid":
                return {"context": {"slot": 22}, "value": True}
            if method == "getFeeForMessage":
                return {"context": {"slot": 22}, "value": 5000}
            assert method == "simulateTransaction"
            assert params[1]["accounts"]["addresses"] == list(monitored)
            self.calls += 1
            return {
                "context": {"slot": 22},
                "value": {
                    "err": None,
                    "logs": [],
                    "unitsConsumed": 100000,
                    "loadedAccountsDataSize": 6000,
                    "accounts": [post_map[address] for address in monitored],
                },
            }

    asset = AssetKey(USDC, TOKEN, 6)
    bridge_asset = AssetKey(WSOL, TOKEN, 9)
    valuation = ConservativeValuationSnapshot(
        "offline-test-unit",
        (
            ConservativeAssetQuote(asset, 1, "c" * 64, 22),
            ConservativeAssetQuote(NATIVE_SOL_ASSET, 1, "d" * 64, 22),
            ConservativeAssetQuote(bridge_asset, 1, "e" * 64, 22),
        ),
        22,
        2,
        0,
    )
    candidate = AtomicVerticalCandidate(
        request=request,
        blockhash=BlockhashContext(
            Hash.from_bytes(bytes(range(32))), 100, 22, 1000.0, "confirmed"
        ),
        settlement_asset=asset,
        pre_state_accounts=tuple(pre_map[address] for address in monitored),
        pre_state_slot=22,
        decode_policy=PR115DecodePolicy(
            marginfi=context,
            readonly_accounts=(
                PR115ReadonlyAccountBinding(RAW_ORACLE, ORACLE_OWNER, _digest(oracle)),
            ),
        ),
        approved_assets=(asset, bridge_asset),
        valuation=valuation,
        marginfi_registry=MarginfiRegistrySnapshot.build(
            program_id=RAW_PROGRAM,
            banks={RAW_BANK},
            liquidity_vaults={RAW_VAULT},
            margin_accounts={RAW_MARGIN},
        ),
    )
    rpc = SimulationRpc()
    return (
        AtomicPlannerSimulationReconciliationVertical(
            planner, ExactSimulationFinalizer(rpc)
        ),
        candidate,
        rpc,
    )


@pytest.mark.asyncio
async def test_actual_source_vector_planner_provider_raw_economic_vertical():
    vertical, candidate, rpc = offline_vertical_fixture()
    result = await vertical.run(candidate)
    assert rpc.calls == 2
    assert (
        result.planner_result.provenance.marginfi_conformance_scope
        == "SOURCE_VECTOR_OFFLINE"
    )
    assert result.qualification.qualified
    assert result.qualification.quote_net == 15000
    assert result.reconciliation.settlement_net == 20000
    assert result.raw_evidence_hash
    instructions = result.finalized.compiled.message.instructions
    assert instructions[2].data[:8] == bytes.fromhex("0e8321dc51bab46b")
    assert int.from_bytes(instructions[2].data[8:], "little") == 7
    assert instructions[7].data == bytes.fromhex("697cc96a9902089c")
    assert result.evidence_origin == "decoder_owned_offline"
    assert (
        getattr(vertical.planner._marginfi, "execution_conformance_verified", False)
        is False
    )


@pytest.mark.asyncio
async def test_actual_source_vector_vertical_rejects_negative_total_value():
    vertical, candidate, _ = offline_vertical_fixture(token_profit=100)
    result = await vertical.run(candidate)
    assert not result.qualification.qualified
    assert result.qualification.status is QualificationStatus.PROVEN_LOSS
    assert result.qualification.quote_net == -4900


@pytest.mark.asyncio
async def test_source_vector_drift_cannot_reuse_offline_admission():
    vertical, candidate, rpc = offline_vertical_fixture()
    evidence = replace(
        candidate.request.marginfi_source_vectors, instruction_hashes=("0" * 64,) * 4
    )
    with pytest.raises(AtomicPlannerError, match="offline source vector comparison"):
        await vertical.run(
            replace(
                candidate,
                request=replace(candidate.request, marginfi_source_vectors=evidence),
            )
        )
    assert rpc.calls == 0


@pytest.mark.asyncio
async def test_readonly_oracle_cannot_change_between_captured_and_final_state():
    vertical, candidate, _ = offline_vertical_fixture()
    changed = copy.deepcopy(candidate.pre_state_accounts)
    for account in changed:
        if account["owner"] == ORACLE_OWNER:
            account["data"][0] = base64.b64encode(b"other observation").decode()
    with pytest.raises(AtomicVerticalError):
        await vertical.run(replace(candidate, pre_state_accounts=changed))


@pytest.mark.asyncio
async def test_source_vector_snapshot_identity_cannot_be_relabelled():
    vertical, candidate, rpc = offline_vertical_fixture()
    evidence = replace(
        candidate.request.marginfi_source_vectors, snapshot_fingerprint="f" * 64
    )
    with pytest.raises(AtomicPlannerError):
        await vertical.run(
            replace(
                candidate,
                request=replace(candidate.request, marginfi_source_vectors=evidence),
            )
        )
    assert rpc.calls == 0


@pytest.mark.asyncio
async def test_legacy_caller_hashes_cannot_override_raw_vertical_economics():
    vertical, candidate, _ = offline_vertical_fixture()
    with pytest.raises(AtomicVerticalError):
        await vertical.run(replace(candidate, decoded_account_hashes=("f" * 64,)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        dict(bank=RAW_GROUP),
        dict(authority=RAW_GROUP),
        dict(principal=2000),
        dict(source_commit="0" * 40),
    ],
)
async def test_raw_policy_cannot_diverge_from_actual_planner_snapshot(change):
    vertical, candidate, rpc = offline_vertical_fixture()
    policy = replace(
        candidate.decode_policy,
        marginfi=replace(candidate.decode_policy.marginfi, **change),
    )
    with pytest.raises(ValueError, match="raw decoder and planner"):
        await vertical.run(replace(candidate, decode_policy=policy))
    assert rpc.calls == 0
