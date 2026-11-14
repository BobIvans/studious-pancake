"""R-14-K: Kamino unsigned financing plans wired into the atomic planner.

The Kamino plans built by ``src.lending.unsigned_builders.kamino_builder``
(pinned ``@kamino-finance/klend-sdk`` ABI) are wired into the existing PR-034
atomic planner as metadata/unsigned instruction REFERENCES only:

- positives: reference insertion into the existing plan structure, exact byte
  preservation (no re-encoding), borrow-index retargeting at FINAL ordering
  via ``retarget_borrow_index``, separated build/capacity status fields, and
  R-13 ``BuildHandoff`` reachability (winner-only, parity checks);
- fail-closed negatives: capacity claims attached to the reference or either
  plan (``R03_BUILD_CAPACITY_ADMIXTURE``), foreign builder bytes, wrong chain,
  foreign/missing source pin, fake build status, stale or backwards repay
  index after retargeting.

Zero network: every input is offline synthetic; nothing is signed, sent, or
composed into an executable transaction, and no account is created.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace

import pytest
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.execution.models import ComputeBudgetPolicy
from src.execution.quote_build_kernel import (
    MAX_AGE_NS,
    BuildHandoff,
    NormalizedProviderQuote,
    ProviderCorrelation,
    QuoteDirection,
    QuoteFreshness,
    QuoteRaceRequest,
    QuoteRaceResult,
)
from src.lending.unsigned_builders.contract import (
    BuildStatus,
    BuilderSourcePin,
    CapacityStatus,
    ConformanceErrorCode,
    ConformanceViolation,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
)
from src.lending.unsigned_builders.kamino_builder import (
    KAMINO_BUILDER_PROVIDER,
    KAMINO_BUILDER_SOURCE_PIN,
    KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX,
    KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX,
    KAMINO_KLEND_PROGRAM_ID,
    KaminoFlashAccounts,
    build_kamino_flash_borrow_plan,
    build_kamino_flash_repay_plan,
    retarget_borrow_index,
)
from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerError,
    AtomicPlannerPolicy,
    AtomicPlannerRejectionCode,
    AtomicPlannerRequest,
    CapitalReservationEvidence,
    KaminoFinancingPlanReference,
)
from src.providers.jupiter.router import (
    JupiterInstructionBundle,
    JupiterRawInstruction,
    RawAccountMeta,
)

pytestmark = pytest.mark.unit


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

#: Pinned Kamino flash-borrow data layout: discriminator(8) + u64 LE (16 bytes).
_KAMINO_BORROW_DATA_SIZE = 16
#: Pinned Kamino flash-repay data layout: the u8 borrowInstructionIndex sits
#: at offset 16 of the 17-byte payload.
_KAMINO_REPAY_EMBEDDED_BORROW_INDEX_OFFSET = 16

KAMINO_PRINCIPAL = 1_000_000
KAMINO_FLASH_LOAN_FEE_SF = 500_000
KAMINO_STATE_FINGERPRINT = "e" * 64


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
        addresses_by_lookup_table_address={str(ALT): (str(ALT_MEMBER),)},
        blockhash_with_metadata={
            "blockhash": str(_pk(30)),
            "lastValidBlockHeight": 1_000,
        },
        received_at=received_at,
    )


def _policy() -> AtomicPlannerPolicy:
    return AtomicPlannerPolicy(
        allowed_program_ids=(
            str(MARGINFI_PROGRAM),
            str(SETUP_PROGRAM),
            str(SWAP_PROGRAM),
            str(OTHER_PROGRAM),
            str(CLEANUP_PROGRAM),
            KAMINO_KLEND_PROGRAM_ID,
        ),
        max_build_age_seconds=2.0,
        compute_budget_policy=ComputeBudgetPolicy(),
    )


def _request(
    *,
    leg_a: JupiterInstructionBundle | None = None,
    leg_b: JupiterInstructionBundle | None = None,
    kamino: KaminoFinancingPlanReference | None = None,
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
        opportunity_id="candidate-r14-kamino",
        payer=PAYER,
        marginfi_snapshot=_Snapshot(),
        borrow_amount=1_000,
        destination_token_account=DESTINATION,
        repayment_source_token_account=REPAYMENT_SOURCE,
        leg_a=first,
        leg_b=second,
        capital=CapitalReservationEvidence(
            reservation_id="reservation-r14",
            approved=True,
            approved_borrow_amount=1_000,
            policy_profile="paper",
            decision_hash="c" * 64,
        ),
        jupiter_contract_pin="d" * 64,
        discovery_slot=901,
        oracle_slot=899,
        safety_surplus=10,
        kamino_financing=kamino,
    )


# ---------------------------------------------------------------------------
# Kamino unsigned plan fixtures (real pinned builder, offline)
# ---------------------------------------------------------------------------


def _kamino_accounts() -> KaminoFlashAccounts:
    return KaminoFlashAccounts(
        user_transfer_authority=str(PAYER),
        lending_market_authority=str(_pk(40)),
        lending_market=str(_pk(41)),
        reserve=str(_pk(42)),
        reserve_liquidity_mint=str(_pk(43)),
        reserve_liquidity_vault=str(_pk(44)),
        user_liquidity_account=str(_pk(45)),
        reserve_liquidity_fee_receiver=str(_pk(46)),
        instructions_sysvar=str(_pk(47)),
        token_program=str(_pk(48)),
    )


def _kamino_plans(
    *, borrow_instruction_index: int
) -> tuple[UnsignedBorrowPlan, UnsignedRepayPlan]:
    accounts = _kamino_accounts()
    borrow_plan = build_kamino_flash_borrow_plan(
        principal_base_units=KAMINO_PRINCIPAL,
        flash_loan_fee_sf=KAMINO_FLASH_LOAN_FEE_SF,
        state_fingerprint=KAMINO_STATE_FINGERPRINT,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    repay_plan = build_kamino_flash_repay_plan(
        borrow_plan=borrow_plan,
        flash_loan_fee_sf=KAMINO_FLASH_LOAN_FEE_SF,
        state_fingerprint=KAMINO_STATE_FINGERPRINT,
        destination_token_account_confirmed=True,
        accounts=accounts,
        borrow_instruction_index=borrow_instruction_index,
    )
    return borrow_plan, repay_plan


def _kamino_reference(
    *,
    borrow_instruction_index: int,
    original_borrow_index: int = 0,
) -> KaminoFinancingPlanReference:
    """Build the reference the way the offline caller would: the repay plan is
    rebuilt against the FINAL planner ordering index (retargeted from the
    provisional ``original_borrow_index``) before handing it to the planner."""
    borrow_plan, repay_plan = _kamino_plans(
        borrow_instruction_index=borrow_instruction_index
    )
    return KaminoFinancingPlanReference(
        borrow_plan=borrow_plan,
        repay_plan=repay_plan,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        capacity_status=CapacityStatus.NOT_EVALUATED,
        original_borrow_index=original_borrow_index,
    )


#: Final ordering with the fixture route (2 Jupiter setups before the Kamino
#: borrow; the MarginFi finalize appends its end template after the repay).
_KAMINO_BORROW_FINAL_INDEX = 2
_KAMINO_REPAY_FINAL_INDEX = 12


def _planner() -> AtomicMarginfiJupiterPlanner:
    return AtomicMarginfiJupiterPlanner(
        _VerifiedMarginfiProvider(),
        _policy(),
        clock=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# Positives
# ---------------------------------------------------------------------------


def test_kamino_reference_wired_as_byte_exact_instruction_references() -> None:
    # Standalone provisional build: borrow at index 0. The planner composes 2
    # Jupiter setup instructions before the borrow, so the caller retargets
    # 0 -> 2 via retarget_borrow_index and rebuilds the repay plan against the
    # final index before handing the reference to the planner.
    assert retarget_borrow_index(0, 2) == 2
    reference = _kamino_reference(
        borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX,
        original_borrow_index=0,
    )

    result = _planner().plan(_request(kamino=reference))
    plan = result.transaction_plan
    roles = tuple(value.role for value in plan.instructions)

    assert roles == (
        "jupiter_setup",
        "jupiter_setup",
        "financing_kamino_borrow",
        "marginfi_start",
        "marginfi_borrow",
        "jupiter_other",
        "jupiter_swap",
        "jupiter_other",
        "jupiter_swap",
        "marginfi_repay",
        "jupiter_cleanup",
        "jupiter_cleanup",
        "financing_kamino_repay",
        "marginfi_end",
    )
    borrow_ref = plan.instructions[_KAMINO_BORROW_FINAL_INDEX]
    repay_ref = plan.instructions[_KAMINO_REPAY_FINAL_INDEX]
    assert borrow_ref.name == "kamino_flash_borrow"
    assert repay_ref.name == "kamino_flash_repay"
    assert borrow_ref.instruction.program_id == Pubkey.from_string(
        KAMINO_KLEND_PROGRAM_ID
    )
    assert repay_ref.instruction.program_id == Pubkey.from_string(
        KAMINO_KLEND_PROGRAM_ID
    )
    # Exact byte preservation: the carried data IS the builder bytes.
    assert reference.borrow_plan.bookend is not None
    assert reference.repay_plan.bookend is not None
    borrow_data = bytes(borrow_ref.instruction.data)
    repay_data = bytes(repay_ref.instruction.data)
    assert borrow_data == bytes.fromhex(reference.borrow_plan.bookend.data_hex)
    assert repay_data == bytes.fromhex(reference.repay_plan.bookend.data_hex)
    assert len(borrow_data) == _KAMINO_BORROW_DATA_SIZE
    assert borrow_data[:8].hex() == KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX
    assert borrow_data[8:] == KAMINO_PRINCIPAL.to_bytes(8, "little")
    assert repay_data[:8].hex() == KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX
    assert repay_data[8:16] == KAMINO_PRINCIPAL.to_bytes(8, "little")
    assert (
        repay_data[_KAMINO_REPAY_EMBEDDED_BORROW_INDEX_OFFSET]
        == _KAMINO_BORROW_FINAL_INDEX
    )
    # Ordered account metas preserved role-for-role, flag-for-flag.
    for ref, bookend in (
        (borrow_ref, reference.borrow_plan.bookend),
        (repay_ref, reference.repay_plan.bookend),
    ):
        assert tuple(
            (str(meta.pubkey), meta.is_signer, meta.is_writable)
            for meta in ref.instruction.accounts
        ) == tuple(
            (meta.pubkey, meta.is_signer, meta.is_writable)
            for meta in bookend.account_metas
        )
    # Final-ordering resolution evidence.
    assert result.kamino_financing is reference
    assert result.kamino_borrow_final_index == _KAMINO_BORROW_FINAL_INDEX
    assert result.kamino_repay_final_index == _KAMINO_REPAY_FINAL_INDEX
    fingerprint = result.provenance.kamino_financing_fingerprint
    assert fingerprint is not None and len(fingerprint) == 64
    # Build and capacity status are separate typed fields (build != capacity).
    assert reference.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert reference.capacity_status is CapacityStatus.NOT_EVALUATED
    assert reference.borrow_plan.capacity_status is CapacityStatus.NOT_EVALUATED
    assert reference.repay_plan.capacity_status is CapacityStatus.NOT_EVALUATED


def test_kamino_reference_reachable_via_build_handoff() -> None:
    """The planner result's Kamino plans satisfy R-13 BuildHandoff parity."""
    reference = _kamino_reference(
        borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX,
        original_borrow_index=0,
    )
    result = _planner().plan(_request(kamino=reference))

    winner = NormalizedProviderQuote(
        provider_id="jupiter",
        provider_generation="gen-r14k-fixture",
        chain="solana",
        direction=QuoteDirection.EXACT_IN,
        input_representation_id="solana-wsol-6dec",
        output_representation_id="solana-usdc-6dec",
        input_amount_raw=1_000_000,
        output_amount_raw=990_000,
        input_amount_normalized=1_000_000,
        output_amount_normalized=990_000,
        correlation=ProviderCorrelation(correlation_group="jupiter-metis-router"),
        freshness=QuoteFreshness(
            received_at_ns=1_800_000_000_000_000_000,
            provider_generated_at_ns=1_800_000_000_000_000_000,
        ),
        raw_response_hash=hashlib.sha256(b"jupiter").hexdigest(),
        request_fingerprint="req-jupiter",
    )
    loser = replace(
        winner,
        provider_id="0x",
        output_amount_raw=989_000,
        raw_response_hash=hashlib.sha256(b"0x").hexdigest(),
    )
    race = QuoteRaceResult.build(
        request=QuoteRaceRequest(
            chain="solana",
            input_representation_id="solana-wsol-6dec",
            output_representation_id="solana-usdc-6dec",
            direction=QuoteDirection.EXACT_IN,
            amount_raw=1_000_000,
            taker=None,
            max_age_ns=MAX_AGE_NS,
            max_slot_gap=32,
        ),
        quotes=[winner, loser],
        now_ns=1_800_000_000_000_000_000,
    )
    assert result.kamino_financing is not None
    handoff = BuildHandoff(
        race_result=race,
        won_quote=race.require_winner(),
        builder_provider=KAMINO_BUILDER_PROVIDER,
        builder_build_status=result.kamino_financing.build_status,
        plan=result.kamino_financing.borrow_plan,
    )
    assert handoff.plan is result.kamino_financing.borrow_plan
    assert handoff.builder_provider == KAMINO_BUILDER_PROVIDER
    assert handoff.builder_build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert len(handoff.handoff_fingerprint) == 64

    # Winner-only: handing off a losing quote is refused.
    from src.execution.quote_build_kernel import BuildHandoffError, KernelErrorCode

    with pytest.raises(BuildHandoffError) as caught:
        BuildHandoff(
            race_result=race,
            won_quote=race.entries[1].quote,
            builder_provider=KAMINO_BUILDER_PROVIDER,
            builder_build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            plan=result.kamino_financing.borrow_plan,
        )
    assert caught.value.code is KernelErrorCode.HANDOFF_NOT_WINNER


# ---------------------------------------------------------------------------
# Fail-closed negatives
# ---------------------------------------------------------------------------


def _expect_kamino_rejection(reference_factory) -> AtomicPlannerError:
    with pytest.raises(AtomicPlannerError) as caught:
        reference_factory()
    assert caught.value.code is AtomicPlannerRejectionCode.KAMINO_FINANCING_REJECTED
    return caught.value


def test_rejects_capacity_claims_attached_to_reference_or_plans() -> None:
    # Capacity claim on the reference itself.
    def claim_on_reference() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        KaminoFinancingPlanReference(
            borrow_plan=borrow_plan,
            repay_plan=repay_plan,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.PENDING_R02_CAPACITY_GATE,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(claim_on_reference)
    assert error.details["r03_code"] == (
        ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE.value
    )

    # Capacity claim smuggled onto either underlying plan.
    for field in ("borrow_plan", "repay_plan"):

        def claim_on_plan(field: str = field) -> None:
            borrow_plan, repay_plan = _kamino_plans(
                borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
            )
            claimed = replace(
                borrow_plan if field == "borrow_plan" else repay_plan,
                capacity_status=CapacityStatus.CAPACITY_UNQUALIFIED,
            )
            KaminoFinancingPlanReference(
                borrow_plan=(claimed if field == "borrow_plan" else borrow_plan),
                repay_plan=(repay_plan if field == "borrow_plan" else claimed),
                build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
                capacity_status=CapacityStatus.NOT_EVALUATED,
                original_borrow_index=0,
            )

        error = _expect_kamino_rejection(claim_on_plan)
        assert error.details["r03_code"] == (
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE.value
        )


def _foreign_pin(*, provider: str = "kamino") -> BuilderSourcePin:
    return BuilderSourcePin(
        provider=provider,
        chain="solana",
        repository="https://example.com/foreign-fork",
        commit="a" * 40,
        version="0.0.0",
        license_label="MIT",
        source_paths=("src/foreign/flash.ts",),
        blob_sha1s=("c" * 40,),
        verified_offline=True,
    )


def test_rejects_foreign_builder_bytes() -> None:
    # Foreign program: borrow bookend rebuilt under a different program id.
    def foreign_program() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        assert borrow_plan.bookend is not None
        foreign = replace(
            borrow_plan.bookend,
            program_id=str(_pk(60)),
        )
        KaminoFinancingPlanReference(
            borrow_plan=replace(borrow_plan, bookend=foreign),
            repay_plan=repay_plan,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(foreign_program)
    assert error.details["r03_code"] == (ConformanceErrorCode.PROGRAM_ID_MISMATCH.value)

    # Foreign discriminator under the pinned program id: the bytes were not
    # produced by the pinned Kamino flash builder.
    def foreign_discriminator() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        assert borrow_plan.bookend is not None
        disc = "00" * 8
        foreign = replace(
            borrow_plan.bookend,
            discriminator_hex=disc,
            data_hex=disc + KAMINO_PRINCIPAL.to_bytes(8, "little").hex(),
        )
        KaminoFinancingPlanReference(
            borrow_plan=replace(borrow_plan, bookend=foreign),
            repay_plan=repay_plan,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(foreign_discriminator)
    assert error.details["r03_code"] == (
        ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE.value
    )

    # Repay plan no longer bound to the exact borrow bookend bytes.
    def repay_unbound_from_borrow() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        assert repay_plan.borrow_bookend is not None
        foreign_borrow_bookend = replace(
            repay_plan.borrow_bookend,
            program_id=str(_pk(61)),
        )
        KaminoFinancingPlanReference(
            borrow_plan=borrow_plan,
            repay_plan=replace(repay_plan, borrow_bookend=foreign_borrow_bookend),
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(repay_unbound_from_borrow)
    assert error.details["r03_code"] == (ConformanceErrorCode.PROGRAM_ID_MISMATCH.value)


def test_rejects_wrong_chain() -> None:
    def wrong_chain() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        KaminoFinancingPlanReference(
            borrow_plan=replace(borrow_plan, chain="sui"),
            repay_plan=repay_plan,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(wrong_chain)
    assert error.details["reason"] == "chain_mismatch"
    assert error.details["expected"] == "solana"


def test_rejects_foreign_or_missing_source_pin() -> None:
    # A verified pin that is NOT the pinned KAMINO_BUILDER_SOURCE_PIN.
    def foreign_commit() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        KaminoFinancingPlanReference(
            borrow_plan=replace(borrow_plan, source_pin=_foreign_pin()),
            repay_plan=repay_plan,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(foreign_commit)
    assert error.details["r03_code"] == (
        ConformanceErrorCode.SOURCE_PIN_UNVERIFIED.value
    )
    assert error.details["reason"] == "source_pin_missing_or_foreign"

    # A foreign provider's pin under a foreign provider identity.
    def foreign_provider() -> None:
        borrow_plan, repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        KaminoFinancingPlanReference(
            borrow_plan=replace(
                borrow_plan,
                provider="jupiter-lend",
                source_pin=_foreign_pin(provider="jupiter-lend"),
            ),
            repay_plan=repay_plan,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(foreign_provider)
    assert error.details["reason"] == "provider_mismatch"


def test_rejects_fake_build_status() -> None:
    def declared_built_but_blocked() -> None:
        borrow_plan, _repay_plan = _kamino_plans(
            borrow_instruction_index=_KAMINO_BORROW_FINAL_INDEX
        )
        blocked_repay = UnsignedRepayPlan(
            provider=KAMINO_BUILDER_PROVIDER,
            chain="solana",
            source_pin=KAMINO_BUILDER_SOURCE_PIN,
            asset_id=borrow_plan.asset_id,
            bookend=None,
            borrow_bookend=None,
            required_repayment_base_units=(borrow_plan.required_repayment_base_units),
            borrow_index_u8_required=True,
            state_fingerprint=KAMINO_STATE_FINGERPRINT,
            blockers=(
                ConformanceViolation(
                    code=ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED,
                    message="no account binding supplied",
                    provider=KAMINO_BUILDER_PROVIDER,
                ),
            ),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
        KaminoFinancingPlanReference(
            borrow_plan=borrow_plan,
            repay_plan=blocked_repay,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            capacity_status=CapacityStatus.NOT_EVALUATED,
            original_borrow_index=0,
        )

    error = _expect_kamino_rejection(declared_built_but_blocked)
    assert error.details["r03_code"] == (
        ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE.value
    )
    assert error.details["reason"] == "declared_build_status_mismatch"


def test_planner_rejects_stale_repay_index_at_final_ordering() -> None:
    # A reference whose repay bytes still embed the provisional standalone
    # index (borrow at 0) passes reference construction — the planner's final
    # ordering is not yet known — but must be rejected fail-closed at planning
    # time against the finalized sequence. The planner never re-encodes.
    reference = _kamino_reference(borrow_instruction_index=0, original_borrow_index=0)
    with pytest.raises(AtomicPlannerError) as caught:
        _planner().plan(_request(kamino=reference))
    assert caught.value.code is AtomicPlannerRejectionCode.KAMINO_FINANCING_REJECTED
    assert caught.value.details["reason"] == "repay_index_mismatch_after_retarget"
    assert caught.value.details["embedded_index"] == 0
    assert caught.value.details["final_borrow_index"] == (_KAMINO_BORROW_FINAL_INDEX)


def test_planner_rejects_backwards_borrow_index_retarget() -> None:
    # Declared build-time borrow index above the final ordering position: the
    # retarget shift would be negative, so retarget_borrow_index fails closed.
    reference = _kamino_reference(borrow_instruction_index=5, original_borrow_index=5)
    with pytest.raises(AtomicPlannerError) as caught:
        _planner().plan(_request(kamino=reference))
    assert caught.value.code is AtomicPlannerRejectionCode.KAMINO_FINANCING_REJECTED
    assert caught.value.details["reason"] == "borrow_index_retarget_failed"
    assert caught.value.details["r03_code"] == (
        ConformanceErrorCode.INVALID_INPUT.value
    )


def test_reference_rejects_backwards_embedded_index() -> None:
    # Embedded repay u8 below the declared build-time index cannot retarget.
    def backwards() -> None:
        _kamino_reference(borrow_instruction_index=1, original_borrow_index=3)

    error = _expect_kamino_rejection(backwards)
    assert error.details["reason"] == "borrow_index_retarget_backwards"


def test_planner_without_kamino_inputs_is_unchanged() -> None:
    """No Kamino reference: the planner's behavior is exactly the PR-034 one."""
    result = _planner().plan(_request())
    roles = tuple(value.role for value in result.transaction_plan.instructions)
    assert "financing_kamino_borrow" not in roles
    assert "financing_kamino_repay" not in roles
    assert result.kamino_financing is None
    assert result.kamino_borrow_final_index is None
    assert result.kamino_repay_final_index is None
    assert result.provenance.kamino_financing_fingerprint is None
