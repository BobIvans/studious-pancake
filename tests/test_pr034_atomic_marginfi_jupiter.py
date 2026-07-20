from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace

import pytest
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.execution.models import ComputeBudgetPolicy
from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerError,
    AtomicPlannerPolicy,
    AtomicPlannerRejectionCode,
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
ALT = _pk(15)
ALT_MEMBER = _pk(16)


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
        snapshot,
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
                AccountMeta(
                    Pubkey.from_string(destination_token_account),
                    False,
                    True,
                ),
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


class _UnverifiedMarginfiProvider(_VerifiedMarginfiProvider):
    execution_conformance_verified = False


def _raw(
    program: Pubkey,
    name: str,
    *,
    signer: Pubkey = PAYER,
) -> JupiterRawInstruction:
    return JupiterRawInstruction(
        program_id=str(program),
        accounts=(
            RawAccountMeta(
                pubkey=str(signer),
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
    received_at: float = NOW,
    alt_values: tuple[str, ...] = (str(ALT_MEMBER),),
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
        addresses_by_lookup_table_address={str(ALT): alt_values},
        blockhash_with_metadata={
            "blockhash": str(_pk(30)),
            "lastValidBlockHeight": 1_000,
        },
        received_at=received_at,
    )


def _policy(*, allowed_program_ids: tuple[str, ...] | None = None):
    return AtomicPlannerPolicy(
        allowed_program_ids=allowed_program_ids
        or (
            str(MARGINFI_PROGRAM),
            str(SETUP_PROGRAM),
            str(SWAP_PROGRAM),
            str(OTHER_PROGRAM),
            str(CLEANUP_PROGRAM),
        ),
        max_build_age_seconds=2.0,
        compute_budget_policy=ComputeBudgetPolicy(),
    )


def _request(
    *,
    leg_a: JupiterInstructionBundle | None = None,
    leg_b: JupiterInstructionBundle | None = None,
) -> AtomicPlannerRequest:
    first = leg_a or _bundle(
        input_mint=BANK_MINT,
        output_mint=BRIDGE_MINT,
        in_amount=1_000,
        out_amount=1_120,
        threshold=1_100,
        setup_name="setup-a",
        other_name="other-a",
        swap_name="swap-a",
        cleanup_name="cleanup-a",
    )
    second = leg_b or _bundle(
        input_mint=BRIDGE_MINT,
        output_mint=BANK_MINT,
        in_amount=1_090,
        out_amount=1_040,
        threshold=1_020,
        setup_name="setup-b",
        other_name="other-b",
        swap_name="swap-b",
        cleanup_name="cleanup-b",
    )
    return AtomicPlannerRequest(
        opportunity_id="candidate-034",
        payer=PAYER,
        marginfi_snapshot=_Snapshot(),
        borrow_amount=1_000,
        destination_token_account=DESTINATION,
        repayment_source_token_account=REPAYMENT_SOURCE,
        leg_a=first,
        leg_b=second,
        capital=CapitalReservationEvidence(
            reservation_id="reservation-034",
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


def test_builds_exact_atomic_sequence_and_provenance() -> None:
    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )

    result = planner.plan(_request())
    plan = result.transaction_plan
    roles = tuple(value.role for value in plan.instructions)

    assert roles == (
        "jupiter_setup",
        "jupiter_setup",
        "marginfi_start",
        "marginfi_borrow",
        "jupiter_other",
        "jupiter_swap",
        "jupiter_other",
        "jupiter_swap",
        "marginfi_repay",
        "jupiter_cleanup",
        "jupiter_cleanup",
        "marginfi_end",
    )
    assert result.pre_flash_setup_count == 2
    assert result.flash_start_index == 2
    assert result.flash_end_index == len(plan.instructions) - 1
    assert result.cleanup_count == 2
    assert result.required_repayment == 1_000
    assert result.guaranteed_final_out == 1_020
    assert plan.required_signers == (PAYER,)
    assert plan.lookup_table_addresses == (ALT,)
    assert plan.required_lookup_addresses == (ALT_MEMBER,)
    assert plan.tip_policy.lamports == 0
    assert plan.min_context_slot == 901
    assert result.provenance.input_mint == BANK_MINT
    assert result.provenance.bridge_mint == BRIDGE_MINT
    assert len(result.provenance.digest) == 64


def test_rejects_unverified_marginfi_provider() -> None:
    planner = AtomicMarginfiJupiterPlanner(
        _UnverifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        planner.plan(_request())
    assert (
        caught.value.code
        is AtomicPlannerRejectionCode.MARGINFI_CONFORMANCE_REQUIRED
    )


def test_rejects_leg_b_input_above_leg_a_guarantee() -> None:
    bad_second = replace(_request().leg_b, in_amount=1_101)
    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        planner.plan(_request(leg_b=bad_second))
    assert caught.value.code is AtomicPlannerRejectionCode.GUARANTEED_INPUT_GAP


def test_rejects_second_leg_that_cannot_repay() -> None:
    bad_second = replace(
        _request().leg_b,
        out_amount=1_000,
        other_amount_threshold=1_000,
    )
    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        planner.plan(_request(leg_b=bad_second))
    assert caught.value.code is AtomicPlannerRejectionCode.REPAYMENT_NOT_COVERED


@pytest.mark.parametrize("field", ["compute", "tip"])
def test_rejects_provider_owned_compute_or_tip(field: str) -> None:
    first = _request().leg_a
    if field == "compute":
        first = replace(
            first,
            compute_unit_price_instructions=(
                _raw(_pk(17), "provider-compute"),
            ),
        )
        expected = AtomicPlannerRejectionCode.PROVIDER_COMPUTE_BUDGET_FORBIDDEN
    else:
        first = replace(
            first,
            tip_instruction=_raw(_pk(18), "provider-tip"),
        )
        expected = AtomicPlannerRejectionCode.PROVIDER_TIP_FORBIDDEN

    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        planner.plan(_request(leg_a=first))
    assert caught.value.code is expected


def test_rejects_stale_build_and_unknown_program() -> None:
    stale = replace(_request().leg_a, received_at=NOW - 3)
    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        planner.plan(_request(leg_a=stale))
    assert caught.value.code is AtomicPlannerRejectionCode.STALE_BUILD

    restricted = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(
            allowed_program_ids=(
                str(MARGINFI_PROGRAM),
                str(SETUP_PROGRAM),
                str(SWAP_PROGRAM),
                str(CLEANUP_PROGRAM),
            )
        ),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        restricted.plan(_request())
    assert caught.value.code is AtomicPlannerRejectionCode.UNSUPPORTED_PROGRAM


def test_rejects_conflicting_alt_provenance() -> None:
    second = replace(
        _request().leg_b,
        addresses_by_lookup_table_address={
            str(ALT): (str(_pk(19)),),
        },
    )
    planner = AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )
    with pytest.raises(AtomicPlannerError) as caught:
        planner.plan(_request(leg_b=second))
    assert caught.value.code is AtomicPlannerRejectionCode.ALT_PROVENANCE_MISMATCH
