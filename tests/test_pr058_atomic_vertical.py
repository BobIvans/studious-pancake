from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.config.chain_registry import TOKEN_PROGRAM_ADDRESS
from src.execution.economic_reconciliation import (
    AccountLifecycle,
    AssetKey,
    MarginfiRepaymentObservation,
    ReconciliationStatus,
    TokenObservation,
    TokenState,
)
from src.execution.exact_simulation import ExactSimulationFinalizer, ExactSimulationPolicy
from src.execution.models import BlockhashContext, ComputeBudgetPolicy
from src.paper_shadow.atomic_vertical import (
    AtomicPlannerSimulationReconciliationVertical,
    AtomicVerticalCandidate,
    AtomicVerticalError,
    AtomicVerticalRejectionCode,
)
from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerPolicy,
    AtomicPlannerRequest,
    CapitalReservationEvidence,
)
from src.providers.jupiter.router import (
    JupiterInstructionBundle,
    JupiterRawInstruction,
    RawAccountMeta,
)

NOW = 1_750_000_000.0


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes([seed]) * 32)


PAYER = _pk(1)
BANK_MINT = str(_pk(2))
BRIDGE_MINT = str(_pk(3))
DESTINATION = _pk(4)
REPAYMENT_SOURCE = _pk(5)
MARGIN_ACCOUNT = _pk(6)
BANK = _pk(7)
VAULT = _pk(8)
ORACLE = _pk(9)
MARGINFI_PROGRAM = _pk(10)
SETUP_PROGRAM = _pk(11)
SWAP_PROGRAM = _pk(12)
OTHER_PROGRAM = _pk(13)
CLEANUP_PROGRAM = _pk(14)
TOKEN_ASSET = AssetKey(BANK_MINT, TOKEN_PROGRAM_ADDRESS, 6)


@dataclass(frozen=True)
class _Bank:
    address: str = str(BANK)
    mint: str = BANK_MINT
    liquidity_vault: str = str(VAULT)
    oracle_keys: tuple[str, ...] = (str(ORACLE),)
    available_liquidity: int = 1_000_000


@dataclass(frozen=True)
class _MarginAccount:
    address: str = str(MARGIN_ACCOUNT)
    authority: str = str(PAYER)


@dataclass(frozen=True)
class _Snapshot:
    slot: int = 900
    bank: _Bank = _Bank()
    margin_account: _MarginAccount = _MarginAccount()
    state_fingerprint: str = "b" * 64


@dataclass(frozen=True)
class _Prepared:
    borrow_instruction: Instruction
    repay_instruction: Instruction
    required_repayment: int
    min_context_slot: int
    pin_hash: str
    state_fingerprint: str


@dataclass(frozen=True)
class _Finalized:
    instructions: tuple[Instruction, ...]
    start_index: int
    end_index: int
    required_repayment: int
    sequence_fingerprint: str


class _VerifiedMarginfiProvider:
    execution_conformance_verified = True

    def prepare(
        self,
        *,
        snapshot: _Snapshot,
        amount: int,
        destination_token_account: str,
        repayment_source_token_account: str,
        min_final_balance: int,
        safety_surplus: int = 0,
    ) -> _Prepared:
        assert min_final_balance >= amount + safety_surplus
        borrow = Instruction(
            MARGINFI_PROGRAM,
            b"borrow" + amount.to_bytes(8, "little"),
            [
                AccountMeta(PAYER, True, False),
                AccountMeta(Pubkey.from_string(destination_token_account), False, True),
            ],
        )
        repay = Instruction(
            MARGINFI_PROGRAM,
            b"repay" + amount.to_bytes(8, "little"),
            [
                AccountMeta(PAYER, True, False),
                AccountMeta(
                    Pubkey.from_string(repayment_source_token_account),
                    False,
                    True,
                ),
            ],
        )
        return _Prepared(
            borrow_instruction=borrow,
            repay_instruction=repay,
            required_repayment=amount,
            min_context_slot=snapshot.slot,
            pin_hash="a" * 64,
            state_fingerprint=snapshot.state_fingerprint,
        )

    def finalize(
        self,
        prepared: _Prepared,
        immutable_sequence,
    ) -> _Finalized:
        sequence = tuple(immutable_sequence)
        borrow_index = sequence.index(prepared.borrow_instruction)
        start = Instruction(
            MARGINFI_PROGRAM,
            b"start" + (len(sequence) + 1).to_bytes(8, "little"),
            [AccountMeta(PAYER, True, False)],
        )
        end = Instruction(
            MARGINFI_PROGRAM,
            b"end",
            [AccountMeta(PAYER, True, False)],
        )
        final = (
            *sequence[:borrow_index],
            start,
            *sequence[borrow_index:],
            end,
        )
        return _Finalized(
            instructions=final,
            start_index=borrow_index,
            end_index=len(final) - 1,
            required_repayment=prepared.required_repayment,
            sequence_fingerprint=hashlib.sha256(b"verified-sequence").hexdigest(),
        )


class _FakeRpc:
    def __init__(self) -> None:
        self._units = [100_000, 102_000]

    async def call(self, method: str, params: list[Any]) -> object:
        if method == "getBlockHeight":
            return {"result": 100}
        if method == "simulateTransaction":
            config = params[1]
            addresses = tuple(config["accounts"]["addresses"])
            units = self._units.pop(0)
            return {
                "result": {
                    "context": {"slot": 950},
                    "value": {
                        "err": None,
                        "unitsConsumed": units,
                        "loadedAccountsDataSize": 2_048,
                        "logs": ("Program log: exact simulation",),
                        "accounts": [_rpc_account(address) for address in addresses],
                        "replacementBlockhash": None,
                    },
                }
            }
        if method == "getFeeForMessage":
            return {"result": {"context": {"slot": 950}, "value": 5_000}}
        raise AssertionError(f"unexpected RPC method: {method}")


def _raw(program: Pubkey, name: str) -> JupiterRawInstruction:
    return JupiterRawInstruction(
        program_id=str(program),
        accounts=(
            RawAccountMeta(
                pubkey=str(PAYER),
                is_signer=True,
                is_writable=False,
            ),
        ),
        data_b64=base64.b64encode(name.encode()).decode(),
        name=name,
    )


def _bundle(
    *,
    input_mint: str,
    output_mint: str,
    in_amount: int,
    out_amount: int,
    threshold: int,
    setup_name: str,
    other_name: str,
    swap_name: str,
    cleanup_name: str,
) -> JupiterInstructionBundle:
    return JupiterInstructionBundle(
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=in_amount,
        out_amount=out_amount,
        other_amount_threshold=threshold,
        swap_mode="ExactIn",
        slippage_bps=50,
        route_plan=({"label": swap_name},),
        compute_unit_price_instructions=(),
        setup_instructions=(_raw(SETUP_PROGRAM, setup_name),),
        swap_instruction=_raw(SWAP_PROGRAM, swap_name),
        cleanup_instruction=_raw(CLEANUP_PROGRAM, cleanup_name),
        other_instructions=(_raw(OTHER_PROGRAM, other_name),),
        tip_instruction=None,
        addresses_by_lookup_table_address={},
        blockhash_with_metadata={
            "blockhash": str(_pk(30)),
            "lastValidBlockHeight": 1_000,
        },
        received_at=NOW,
    )


def _policy() -> AtomicPlannerPolicy:
    return AtomicPlannerPolicy(
        allowed_program_ids=(
            str(MARGINFI_PROGRAM),
            str(SETUP_PROGRAM),
            str(SWAP_PROGRAM),
            str(OTHER_PROGRAM),
            str(CLEANUP_PROGRAM),
        ),
        max_build_age_seconds=2.0,
        compute_budget_policy=ComputeBudgetPolicy(),
    )


def _request() -> AtomicPlannerRequest:
    return AtomicPlannerRequest(
        opportunity_id="candidate-058",
        payer=PAYER,
        marginfi_snapshot=_Snapshot(),
        borrow_amount=1_000,
        destination_token_account=DESTINATION,
        repayment_source_token_account=REPAYMENT_SOURCE,
        leg_a=_bundle(
            input_mint=BANK_MINT,
            output_mint=BRIDGE_MINT,
            in_amount=1_000,
            out_amount=1_120,
            threshold=1_100,
            setup_name="setup-a",
            other_name="other-a",
            swap_name="swap-a",
            cleanup_name="cleanup-a",
        ),
        leg_b=_bundle(
            input_mint=BRIDGE_MINT,
            output_mint=BANK_MINT,
            in_amount=1_090,
            out_amount=1_040,
            threshold=1_020,
            setup_name="setup-b",
            other_name="other-b",
            swap_name="swap-b",
            cleanup_name="cleanup-b",
        ),
        capital=CapitalReservationEvidence(
            reservation_id="reservation-058",
            approved=True,
            approved_borrow_amount=1_000,
            policy_profile="paper",
            decision_hash="c" * 64,
        ),
        jupiter_contract_pin="d" * 64,
        discovery_slot=901,
        oracle_slot=899,
        safety_surplus=10,
    )


def _blockhash() -> BlockhashContext:
    return BlockhashContext(
        blockhash=Hash.from_bytes(bytes([31]) * 32),
        last_valid_block_height=1_000,
        source_slot=950,
        fetched_at=NOW,
        commitment="confirmed",
    )


def _rpc_account(address: str) -> dict[str, object]:
    return {
        "address": address,
        "data": ("", "base64"),
        "executable": False,
        "lamports": 1,
        "owner": "11111111111111111111111111111111",
        "rentEpoch": 0,
    }


def _account_hash(account: object) -> str:
    payload = json.dumps(
        account,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _expected_return_hashes(plan) -> tuple[str, ...]:
    monitored = tuple(
        dict.fromkeys(
            (
                str(plan.payer),
                *(str(address) for address in plan.monitored_accounts),
            )
        )
    )
    return tuple(_account_hash(_rpc_account(address)) for address in monitored)


def _token_observations(slot: int = 950) -> tuple[TokenObservation, ...]:
    return (
        TokenObservation(
            address=str(REPAYMENT_SOURCE),
            authority=str(PAYER),
            asset=TOKEN_ASSET,
            pre=TokenState(
                address=str(REPAYMENT_SOURCE),
                program_owner=TOKEN_PROGRAM_ADDRESS,
                authority=str(PAYER),
                asset=TOKEN_ASSET,
                amount=1_000_000,
                account_lamports=2_039_280,
                slot=slot,
            ),
            post=TokenState(
                address=str(REPAYMENT_SOURCE),
                program_owner=TOKEN_PROGRAM_ADDRESS,
                authority=str(PAYER),
                asset=TOKEN_ASSET,
                amount=1_000_020,
                account_lamports=2_039_280,
                slot=slot,
            ),
            lifecycle=AccountLifecycle.STABLE,
        ),
    )


def _marginfi_observation(slot: int = 950) -> MarginfiRepaymentObservation:
    return MarginfiRepaymentObservation(
        program_id=str(MARGINFI_PROGRAM),
        margin_account=str(MARGIN_ACCOUNT),
        bank=str(BANK),
        liquidity_vault=str(VAULT),
        asset=TOKEN_ASSET,
        slot=slot,
        margin_owner_before=str(MARGINFI_PROGRAM),
        margin_owner_after=str(MARGINFI_PROGRAM),
        bank_owner_before=str(MARGINFI_PROGRAM),
        bank_owner_after=str(MARGINFI_PROGRAM),
        flags_before=0,
        flags_after=0,
        liability_before=0,
        liability_after=0,
        borrowed=1_000,
        required_repayment=1_000,
        vault_before=100_000,
        vault_after=100_000,
    )


def _vertical() -> AtomicPlannerSimulationReconciliationVertical:
    return AtomicPlannerSimulationReconciliationVertical(
        AtomicMarginfiJupiterPlanner(
            _VerifiedMarginfiProvider(),
            _policy(),
            clock=lambda: NOW,
        ),
        ExactSimulationFinalizer(
            _FakeRpc(),
            policy=ExactSimulationPolicy(rpc_timeout_seconds=1.0),
        ),
    )


def _candidate(
    *,
    request: AtomicPlannerRequest | None = None,
    marginfi_observation: MarginfiRepaymentObservation | None = None,
    decoded_account_hashes: tuple[str, ...] | None = None,
) -> AtomicVerticalCandidate:
    actual_request = request or _request()
    planner_result = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    ).plan(actual_request)
    return AtomicVerticalCandidate(
        request=actual_request,
        blockhash=_blockhash(),
        settlement_asset=TOKEN_ASSET,
        token_observations=_token_observations(),
        marginfi_observation=(
            _marginfi_observation()
            if marginfi_observation is None
            else marginfi_observation
        ),
        decoded_account_hashes=(
            _expected_return_hashes(planner_result.transaction_plan)
            if decoded_account_hashes is None
            else decoded_account_hashes
        ),
        required_accounts=(str(REPAYMENT_SOURCE),),
    )


@pytest.mark.asyncio
async def test_pr058_runs_recorded_vertical_without_sender() -> None:
    result = await _vertical().run(_candidate())

    assert result.reconciliation.status is ReconciliationStatus.PROVEN_PROFIT
    assert result.reconciliation.settlement_net == 20
    assert result.trace.message_hash == result.finalized.compiled.message_hash
    assert result.trace.planner_digest == result.planner_result.provenance.digest
    assert (
        result.trace.sequence_fingerprint
        == result.planner_result.provenance.sequence_fingerprint
    )
    assert (
        result.trace.final_compute_unit_limit
        == result.finalized.report.final_compute_unit_limit
    )
    assert result.trace.final_fee_lamports == 5_000
    assert result.trace.reconciliation_status == ReconciliationStatus.PROVEN_PROFIT.value
    assert result.trace.required_accounts == (str(REPAYMENT_SOURCE),)


@pytest.mark.asyncio
async def test_pr058_rejects_decoded_account_hash_drift_before_reconciliation() -> None:
    candidate = _candidate(decoded_account_hashes=("0" * 64,))

    with pytest.raises(AtomicVerticalError) as caught:
        await _vertical().run(candidate)

    assert caught.value.code is AtomicVerticalRejectionCode.ACCOUNT_EVIDENCE_MISMATCH


@pytest.mark.asyncio
async def test_pr058_rejects_unproven_marginfi_repayment_state() -> None:
    candidate = replace(_candidate(), marginfi_observation=None)

    with pytest.raises(AtomicVerticalError) as caught:
        await _vertical().run(candidate)

    assert caught.value.code is AtomicVerticalRejectionCode.RECONCILIATION_INCOMPLETE
    assert caught.value.details["reason"] == "marginfi_evidence_missing"
