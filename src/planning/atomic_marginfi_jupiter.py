"""Fail-closed PR-034 atomic MarginFi + Jupiter two-leg planner.

The planner is intentionally sender-free.  It accepts only two canonical Jupiter
instruction bundles, a verified MarginFi provider port, and capital reservation
evidence.  The output is one typed ``TransactionPlan`` for the canonical v0
compiler.  No signing, simulation result, permit, or submission is created here.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.execution.models import (
    COMPUTE_BUDGET_PROGRAM_ID,
    ComputeBudgetPolicy,
    PlannedInstruction,
    TipPolicy,
    TransactionPlan,
)
from src.providers.jupiter.router import (
    JupiterInstructionBundle,
    JupiterRawInstruction,
)


PLANNER_VERSION = "pr034.atomic-marginfi-jupiter.v1"


class AtomicPlannerRejectionCode(str, Enum):
    INVALID_REQUEST = "PR034_INVALID_REQUEST"
    CAPITAL_NOT_RESERVED = "PR034_CAPITAL_NOT_RESERVED"
    MARGINFI_CONFORMANCE_REQUIRED = "PR034_MARGINFI_CONFORMANCE_REQUIRED"
    JUPITER_CONTRACT_PIN_REQUIRED = "PR034_JUPITER_CONTRACT_PIN_REQUIRED"
    STALE_BUILD = "PR034_STALE_BUILD"
    ROUTE_CHAIN_MISMATCH = "PR034_ROUTE_CHAIN_MISMATCH"
    GUARANTEED_INPUT_GAP = "PR034_GUARANTEED_INPUT_GAP"
    REPAYMENT_NOT_COVERED = "PR034_REPAYMENT_NOT_COVERED"
    PROVIDER_COMPUTE_BUDGET_FORBIDDEN = (
        "PR034_PROVIDER_COMPUTE_BUDGET_FORBIDDEN"
    )
    PROVIDER_TIP_FORBIDDEN = "PR034_PROVIDER_TIP_FORBIDDEN"
    UNSUPPORTED_PROGRAM = "PR034_UNSUPPORTED_PROGRAM"
    UNEXPECTED_SIGNER = "PR034_UNEXPECTED_SIGNER"
    ALT_PROVENANCE_MISMATCH = "PR034_ALT_PROVENANCE_MISMATCH"
    MARGINFI_PROVIDER_REJECTED = "PR034_MARGINFI_PROVIDER_REJECTED"
    SEQUENCE_INVARIANT = "PR034_SEQUENCE_INVARIANT"
    INSTRUCTION_LIMIT = "PR034_INSTRUCTION_LIMIT"


class AtomicPlannerError(ValueError):
    """Typed, fail-closed planner rejection."""

    def __init__(
        self,
        code: AtomicPlannerRejectionCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.details = dict(details or {})


class PreparedFlashLoanLike(Protocol):
    borrow_instruction: Instruction
    repay_instruction: Instruction
    required_repayment: int
    min_context_slot: int
    pin_hash: str
    state_fingerprint: str


class FinalizedFlashLoanLike(Protocol):
    instructions: tuple[Instruction, ...]
    start_index: int
    end_index: int
    required_repayment: int
    sequence_fingerprint: str


class VerifiedMarginfiProviderPort(Protocol):
    """PR-028 must expose this explicit conformance admission bit."""

    execution_conformance_verified: bool

    def prepare(
        self,
        *,
        snapshot: Any,
        amount: int,
        destination_token_account: str,
        repayment_source_token_account: str,
        min_final_balance: int,
        safety_surplus: int = 0,
    ) -> PreparedFlashLoanLike: ...

    def finalize(
        self,
        prepared: PreparedFlashLoanLike,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedFlashLoanLike: ...


@dataclass(frozen=True, slots=True)
class CapitalReservationEvidence:
    """Transport-neutral evidence supplied by PR-032's capital boundary."""

    reservation_id: str
    approved: bool
    approved_borrow_amount: int
    policy_profile: str
    decision_hash: str

    def validate(self, expected_borrow_amount: int) -> None:
        if not self.approved:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.CAPITAL_NOT_RESERVED,
                "capital decision did not approve this candidate",
            )
        if self.approved_borrow_amount != expected_borrow_amount:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.CAPITAL_NOT_RESERVED,
                "reserved borrow amount differs from planner request",
            )
        if (
            not self.reservation_id.strip()
            or not self.policy_profile.strip()
            or not _is_sha256(self.decision_hash)
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.CAPITAL_NOT_RESERVED,
                "capital reservation evidence is incomplete",
            )


@dataclass(frozen=True, slots=True)
class AtomicPlannerPolicy:
    """Immutable safety envelope owned by configuration/policy, not providers."""

    allowed_program_ids: tuple[str, ...]
    max_build_age_seconds: float = 2.0
    max_future_clock_skew_seconds: float = 1.0
    max_total_instructions: int = 32
    compute_budget_policy: ComputeBudgetPolicy = ComputeBudgetPolicy()

    def __post_init__(self) -> None:
        if not self.allowed_program_ids:
            raise ValueError("allowed_program_ids must not be empty")
        for value in self.allowed_program_ids:
            try:
                Pubkey.from_string(value)
            except Exception as exc:
                raise ValueError(f"invalid allowed program id: {value!r}") from exc
        if self.max_build_age_seconds <= 0:
            raise ValueError("max_build_age_seconds must be positive")
        if self.max_future_clock_skew_seconds < 0:
            raise ValueError("max_future_clock_skew_seconds must be non-negative")
        if self.max_total_instructions < 6:
            raise ValueError("max_total_instructions is too small for an atomic route")


@dataclass(frozen=True, slots=True)
class AtomicPlannerRequest:
    opportunity_id: str
    payer: Pubkey
    marginfi_snapshot: Any
    borrow_amount: int
    destination_token_account: Pubkey
    repayment_source_token_account: Pubkey
    leg_a: JupiterInstructionBundle
    leg_b: JupiterInstructionBundle
    capital: CapitalReservationEvidence
    jupiter_contract_pin: str
    discovery_slot: int
    oracle_slot: int | None = None
    safety_surplus: int = 0
    monitored_accounts: tuple[Pubkey, ...] = ()


@dataclass(frozen=True, slots=True)
class AtomicPlannerProvenance:
    planner_version: str
    opportunity_id: str
    provider: str
    jupiter_contract_pin: str
    marginfi_pin_hash: str
    marginfi_state_fingerprint: str
    leg_a_fingerprint: str
    leg_b_fingerprint: str
    sequence_fingerprint: str
    capital_reservation_id: str
    capital_decision_hash: str
    input_mint: str
    bridge_mint: str
    output_mint: str
    borrow_amount: int
    guaranteed_final_out: int
    required_repayment: int
    lookup_table_addresses: tuple[str, ...]
    min_context_slot: int

    @property
    def digest(self) -> str:
        payload = {
            "planner_version": self.planner_version,
            "opportunity_id": self.opportunity_id,
            "provider": self.provider,
            "jupiter_contract_pin": self.jupiter_contract_pin,
            "marginfi_pin_hash": self.marginfi_pin_hash,
            "marginfi_state_fingerprint": self.marginfi_state_fingerprint,
            "leg_a_fingerprint": self.leg_a_fingerprint,
            "leg_b_fingerprint": self.leg_b_fingerprint,
            "sequence_fingerprint": self.sequence_fingerprint,
            "capital_reservation_id": self.capital_reservation_id,
            "capital_decision_hash": self.capital_decision_hash,
            "input_mint": self.input_mint,
            "bridge_mint": self.bridge_mint,
            "output_mint": self.output_mint,
            "borrow_amount": self.borrow_amount,
            "guaranteed_final_out": self.guaranteed_final_out,
            "required_repayment": self.required_repayment,
            "lookup_table_addresses": self.lookup_table_addresses,
            "min_context_slot": self.min_context_slot,
        }
        return _sha256_json(payload)


@dataclass(frozen=True, slots=True)
class AtomicPlannerResult:
    transaction_plan: TransactionPlan
    provenance: AtomicPlannerProvenance
    required_repayment: int
    guaranteed_final_out: int
    pre_flash_setup_count: int
    flash_start_index: int
    flash_end_index: int
    cleanup_count: int


class AtomicMarginfiJupiterPlanner:
    """Build one MarginFi borrow -> Jupiter A -> Jupiter B -> repay plan."""

    def __init__(
        self,
        marginfi_provider: VerifiedMarginfiProviderPort,
        policy: AtomicPlannerPolicy,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._marginfi = marginfi_provider
        self._policy = policy
        self._clock = clock
        self._allowed_program_ids = frozenset(policy.allowed_program_ids)

    def plan(self, request: AtomicPlannerRequest) -> AtomicPlannerResult:
        self._validate_request(request)
        request.capital.validate(request.borrow_amount)
        self._require_contract_admission(request)
        self._validate_build_freshness(request.leg_a)
        self._validate_build_freshness(request.leg_b)
        bank_mint = self._validate_route_chain(request)
        self._validate_provider_owned_instructions(request.leg_a)
        self._validate_provider_owned_instructions(request.leg_b)

        try:
            prepared = self._marginfi.prepare(
                snapshot=request.marginfi_snapshot,
                amount=request.borrow_amount,
                destination_token_account=str(request.destination_token_account),
                repayment_source_token_account=str(
                    request.repayment_source_token_account
                ),
                min_final_balance=request.leg_b.other_amount_threshold,
                safety_surplus=request.safety_surplus,
            )
        except Exception as exc:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.MARGINFI_PROVIDER_REJECTED,
                "MarginFi prepare rejected the candidate",
                details={"exception_type": type(exc).__name__},
            ) from exc

        required_repayment = _positive_int(
            getattr(prepared, "required_repayment", None),
            "prepared.required_repayment",
        )
        if request.leg_b.other_amount_threshold < (
            required_repayment + request.safety_surplus
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.REPAYMENT_NOT_COVERED,
                "second-leg guaranteed output cannot cover repayment and surplus",
                details={
                    "guaranteed_final_out": request.leg_b.other_amount_threshold,
                    "required_repayment": required_repayment,
                    "safety_surplus": request.safety_surplus,
                },
            )

        leg_a_setup = _solders_many(request.leg_a.setup_instructions)
        leg_b_setup = _solders_many(request.leg_b.setup_instructions)
        pre_flash_setup = (*leg_a_setup, *leg_b_setup)

        leg_a_other = _solders_many(request.leg_a.other_instructions)
        leg_b_other = _solders_many(request.leg_b.other_instructions)
        leg_a_swap = request.leg_a.swap_instruction.to_solders_instruction()
        leg_b_swap = request.leg_b.swap_instruction.to_solders_instruction()

        cleanup: tuple[Instruction, ...] = tuple(
            ix.to_solders_instruction()
            for ix in (
                request.leg_a.cleanup_instruction,
                request.leg_b.cleanup_instruction,
            )
            if ix is not None
        )

        immutable_sequence = (
            *pre_flash_setup,
            prepared.borrow_instruction,
            *leg_a_other,
            leg_a_swap,
            *leg_b_other,
            leg_b_swap,
            prepared.repay_instruction,
            *cleanup,
        )

        try:
            finalized = self._marginfi.finalize(prepared, immutable_sequence)
        except Exception as exc:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.MARGINFI_PROVIDER_REJECTED,
                "MarginFi finalize rejected the immutable sequence",
                details={"exception_type": type(exc).__name__},
            ) from exc

        final_instructions = tuple(finalized.instructions)
        self._validate_exact_sequence(
            finalized=finalized,
            prepared=prepared,
            pre_flash_setup=pre_flash_setup,
            leg_a_other=leg_a_other,
            leg_a_swap=leg_a_swap,
            leg_b_other=leg_b_other,
            leg_b_swap=leg_b_swap,
            cleanup=cleanup,
        )
        self._validate_final_instructions(final_instructions, request.payer)

        if len(final_instructions) > self._policy.max_total_instructions:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INSTRUCTION_LIMIT,
                "atomic plan exceeds configured instruction ceiling",
                details={
                    "actual": len(final_instructions),
                    "limit": self._policy.max_total_instructions,
                },
            )

        lookup_tables, required_lookup_addresses = self._merge_alt_provenance(
            request.leg_a.addresses_by_lookup_table_address,
            request.leg_b.addresses_by_lookup_table_address,
        )
        monitored_accounts = self._monitored_accounts(request)
        planned_instructions = self._planned_instructions(
            finalized=finalized,
            prepared=prepared,
            pre_flash_setup=pre_flash_setup,
            leg_a_other=leg_a_other,
            leg_a_swap=leg_a_swap,
            leg_b_other=leg_b_other,
            leg_b_swap=leg_b_swap,
            cleanup=cleanup,
        )

        snapshot_slot = _positive_int(
            getattr(request.marginfi_snapshot, "slot", None),
            "marginfi_snapshot.slot",
        )
        prepared_min_context_slot = _positive_int(
            getattr(prepared, "min_context_slot", None),
            "prepared.min_context_slot",
        )
        market_state_slot = max(snapshot_slot, prepared_min_context_slot)
        oracle_slot = request.oracle_slot
        if oracle_slot is not None and oracle_slot <= 0:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "oracle_slot must be positive when supplied",
            )

        transaction_plan = TransactionPlan(
            opportunity_id=request.opportunity_id,
            payer=request.payer,
            instructions=planned_instructions,
            compute_budget_policy=self._policy.compute_budget_policy,
            tip_policy=TipPolicy(),
            required_signers=(request.payer,),
            lookup_table_addresses=lookup_tables,
            required_lookup_addresses=required_lookup_addresses,
            quote_slot=request.discovery_slot,
            market_state_slot=market_state_slot,
            oracle_slot=oracle_slot,
            monitored_accounts=monitored_accounts,
        )

        marginfi_pin_hash = str(getattr(prepared, "pin_hash", ""))
        marginfi_state_fingerprint = str(
            getattr(prepared, "state_fingerprint", "")
        )
        if not _is_sha256(marginfi_pin_hash) or not _is_sha256(
            marginfi_state_fingerprint
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.MARGINFI_CONFORMANCE_REQUIRED,
                "MarginFi prepared plan lacks pinned SHA-256 provenance",
            )

        sequence_fingerprint = str(
            getattr(finalized, "sequence_fingerprint", "")
        )
        if not _is_sha256(sequence_fingerprint):
            sequence_fingerprint = _instruction_sequence_fingerprint(
                final_instructions
            )

        provenance = AtomicPlannerProvenance(
            planner_version=PLANNER_VERSION,
            opportunity_id=request.opportunity_id,
            provider="jupiter",
            jupiter_contract_pin=request.jupiter_contract_pin,
            marginfi_pin_hash=marginfi_pin_hash,
            marginfi_state_fingerprint=marginfi_state_fingerprint,
            leg_a_fingerprint=_bundle_fingerprint(request.leg_a),
            leg_b_fingerprint=_bundle_fingerprint(request.leg_b),
            sequence_fingerprint=sequence_fingerprint,
            capital_reservation_id=request.capital.reservation_id,
            capital_decision_hash=request.capital.decision_hash,
            input_mint=bank_mint,
            bridge_mint=request.leg_a.output_mint,
            output_mint=request.leg_b.output_mint,
            borrow_amount=request.borrow_amount,
            guaranteed_final_out=request.leg_b.other_amount_threshold,
            required_repayment=required_repayment,
            lookup_table_addresses=tuple(str(value) for value in lookup_tables),
            min_context_slot=transaction_plan.min_context_slot,
        )
        return AtomicPlannerResult(
            transaction_plan=transaction_plan,
            provenance=provenance,
            required_repayment=required_repayment,
            guaranteed_final_out=request.leg_b.other_amount_threshold,
            pre_flash_setup_count=len(pre_flash_setup),
            flash_start_index=int(finalized.start_index),
            flash_end_index=int(finalized.end_index),
            cleanup_count=len(cleanup),
        )

    def _validate_request(self, request: AtomicPlannerRequest) -> None:
        if not request.opportunity_id.strip():
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "opportunity_id is required",
            )
        if not isinstance(request.payer, Pubkey):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "payer must be a Pubkey",
            )
        if not isinstance(request.destination_token_account, Pubkey) or not isinstance(
            request.repayment_source_token_account, Pubkey
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "token accounts must be Pubkey values",
            )
        if request.borrow_amount <= 0 or request.safety_surplus < 0:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "borrow amount must be positive and surplus non-negative",
            )
        if request.discovery_slot <= 0:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "discovery_slot must be positive",
            )

    def _require_contract_admission(self, request: AtomicPlannerRequest) -> None:
        if getattr(self._marginfi, "execution_conformance_verified", False) is not True:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.MARGINFI_CONFORMANCE_REQUIRED,
                "MarginFi provider has not passed PR-028 conformance",
            )
        if not _is_sha256(request.jupiter_contract_pin):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.JUPITER_CONTRACT_PIN_REQUIRED,
                "Jupiter contract pin must be a reviewed SHA-256",
            )

    def _validate_build_freshness(self, bundle: JupiterInstructionBundle) -> None:
        age = self._clock() - bundle.received_at
        if (
            age > self._policy.max_build_age_seconds
            or age < -self._policy.max_future_clock_skew_seconds
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.STALE_BUILD,
                "Jupiter build is stale or has invalid future time",
                details={"age_seconds": age},
            )

    def _validate_route_chain(self, request: AtomicPlannerRequest) -> str:
        try:
            bank = request.marginfi_snapshot.bank
            bank_mint = str(bank.mint)
            available_liquidity = int(bank.available_liquidity)
            authority = str(request.marginfi_snapshot.margin_account.authority)
        except Exception as exc:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "MarginFi snapshot is missing required bank/account fields",
            ) from exc

        if authority != str(request.payer):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.UNEXPECTED_SIGNER,
                "first vertical requires payer to equal MarginFi authority",
            )
        if available_liquidity < request.borrow_amount:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "snapshot liquidity cannot satisfy requested borrow",
            )

        a = request.leg_a
        b = request.leg_b
        if a.swap_mode != "ExactIn" or b.swap_mode != "ExactIn":
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.ROUTE_CHAIN_MISMATCH,
                "both Jupiter legs must be ExactIn",
            )
        if (
            a.input_mint != bank_mint
            or a.in_amount != request.borrow_amount
            or a.output_mint != b.input_mint
            or b.output_mint != bank_mint
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.ROUTE_CHAIN_MISMATCH,
                "legs do not form bank-mint -> bridge -> bank-mint cycle",
            )
        for label, bundle in (("leg_a", a), ("leg_b", b)):
            if (
                bundle.in_amount <= 0
                or bundle.out_amount <= 0
                or bundle.other_amount_threshold <= 0
                or bundle.other_amount_threshold > bundle.out_amount
            ):
                raise AtomicPlannerError(
                    AtomicPlannerRejectionCode.ROUTE_CHAIN_MISMATCH,
                    f"{label} amounts are not conservative ExactIn values",
                )
        if b.in_amount > a.other_amount_threshold:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.GUARANTEED_INPUT_GAP,
                "leg B input exceeds leg A guaranteed minimum output",
                details={
                    "leg_b_input": b.in_amount,
                    "leg_a_guaranteed_out": a.other_amount_threshold,
                },
            )
        if b.other_amount_threshold < request.borrow_amount + request.safety_surplus:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.REPAYMENT_NOT_COVERED,
                "second-leg guarantee is below principal plus safety surplus",
                details={
                    "guaranteed_final_out": b.other_amount_threshold,
                    "minimum_required": request.borrow_amount
                    + request.safety_surplus,
                },
            )
        return bank_mint

    def _validate_provider_owned_instructions(
        self, bundle: JupiterInstructionBundle
    ) -> None:
        if bundle.compute_unit_price_instructions:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.PROVIDER_COMPUTE_BUDGET_FORBIDDEN,
                "compute budget is compiler-owned",
            )
        if bundle.tip_instruction is not None:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.PROVIDER_TIP_FORBIDDEN,
                "tip policy is compiler/sender-owned",
            )

    def _validate_exact_sequence(
        self,
        *,
        finalized: FinalizedFlashLoanLike,
        prepared: PreparedFlashLoanLike,
        pre_flash_setup: tuple[Instruction, ...],
        leg_a_other: tuple[Instruction, ...],
        leg_a_swap: Instruction,
        leg_b_other: tuple[Instruction, ...],
        leg_b_swap: Instruction,
        cleanup: tuple[Instruction, ...],
    ) -> None:
        final = tuple(finalized.instructions)
        start_index = int(finalized.start_index)
        end_index = int(finalized.end_index)
        if (
            start_index != len(pre_flash_setup)
            or end_index != len(final) - 1
            or start_index < 0
            or start_index + 1 >= len(final)
        ):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.SEQUENCE_INVARIANT,
                "MarginFi start/end indices do not match atomic bracket",
            )
        start_instruction = final[start_index]
        end_instruction = final[end_index]
        expected = (
            *pre_flash_setup,
            start_instruction,
            prepared.borrow_instruction,
            *leg_a_other,
            leg_a_swap,
            *leg_b_other,
            leg_b_swap,
            prepared.repay_instruction,
            *cleanup,
            end_instruction,
        )
        if final != expected:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.SEQUENCE_INVARIANT,
                "finalized instruction order differs from immutable PR-034 order",
            )
        if int(finalized.required_repayment) != int(prepared.required_repayment):
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.SEQUENCE_INVARIANT,
                "finalized repayment differs from prepared repayment",
            )

    def _validate_final_instructions(
        self, instructions: tuple[Instruction, ...], payer: Pubkey
    ) -> None:
        for instruction in instructions:
            program_id = str(instruction.program_id)
            if instruction.program_id == COMPUTE_BUDGET_PROGRAM_ID:
                raise AtomicPlannerError(
                    AtomicPlannerRejectionCode.PROVIDER_COMPUTE_BUDGET_FORBIDDEN,
                    "provider sequence contains ComputeBudget instruction",
                )
            if program_id not in self._allowed_program_ids:
                raise AtomicPlannerError(
                    AtomicPlannerRejectionCode.UNSUPPORTED_PROGRAM,
                    "instruction program is outside the configured allowlist",
                    details={"program_id": program_id},
                )
            for account in instruction.accounts:
                if account.is_signer and account.pubkey != payer:
                    raise AtomicPlannerError(
                        AtomicPlannerRejectionCode.UNEXPECTED_SIGNER,
                        "atomic plan requires an undeclared signer",
                        details={"signer": str(account.pubkey)},
                    )

    def _merge_alt_provenance(
        self,
        first: Mapping[str, tuple[str, ...]],
        second: Mapping[str, tuple[str, ...]],
    ) -> tuple[tuple[Pubkey, ...], tuple[Pubkey, ...]]:
        merged: dict[str, tuple[str, ...]] = {}
        for source in (first, second):
            for address, values in source.items():
                normalized = tuple(values)
                if address in merged and merged[address] != normalized:
                    raise AtomicPlannerError(
                        AtomicPlannerRejectionCode.ALT_PROVENANCE_MISMATCH,
                        "same ALT has conflicting address provenance",
                        details={"lookup_table": address},
                    )
                merged[address] = normalized
        try:
            lookup_tables = tuple(Pubkey.from_string(value) for value in merged)
            required = _dedupe_pubkeys(
                Pubkey.from_string(value)
                for values in merged.values()
                for value in values
            )
        except Exception as exc:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.ALT_PROVENANCE_MISMATCH,
                "Jupiter ALT provenance contains an invalid pubkey",
            ) from exc
        return lookup_tables, required

    def _monitored_accounts(
        self, request: AtomicPlannerRequest
    ) -> tuple[Pubkey, ...]:
        try:
            snapshot_values = (
                request.marginfi_snapshot.margin_account.address,
                request.marginfi_snapshot.bank.address,
                request.marginfi_snapshot.bank.liquidity_vault,
                *request.marginfi_snapshot.bank.oracle_keys,
            )
            snapshot_pubkeys = tuple(
                Pubkey.from_string(str(value)) for value in snapshot_values
            )
        except Exception as exc:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.INVALID_REQUEST,
                "snapshot monitored-account provenance is invalid",
            ) from exc
        return _dedupe_pubkeys(
            (
                *request.monitored_accounts,
                *snapshot_pubkeys,
                request.destination_token_account,
                request.repayment_source_token_account,
            )
        )

    def _planned_instructions(
        self,
        *,
        finalized: FinalizedFlashLoanLike,
        prepared: PreparedFlashLoanLike,
        pre_flash_setup: tuple[Instruction, ...],
        leg_a_other: tuple[Instruction, ...],
        leg_a_swap: Instruction,
        leg_b_other: tuple[Instruction, ...],
        leg_b_swap: Instruction,
        cleanup: tuple[Instruction, ...],
    ) -> tuple[PlannedInstruction, ...]:
        final = tuple(finalized.instructions)
        start_index = int(finalized.start_index)
        end_index = int(finalized.end_index)
        specs: list[tuple[Instruction, str, str]] = []
        specs.extend(
            (instruction, "jupiter_setup", f"setup_{index}")
            for index, instruction in enumerate(pre_flash_setup)
        )
        specs.append((final[start_index], "marginfi_start", "marginfi_start_flashloan"))
        specs.append(
            (
                prepared.borrow_instruction,
                "marginfi_borrow",
                "marginfi_flash_borrow",
            )
        )
        specs.extend(
            (instruction, "jupiter_other", f"leg_a_other_{index}")
            for index, instruction in enumerate(leg_a_other)
        )
        specs.append((leg_a_swap, "jupiter_swap", "jupiter_leg_a"))
        specs.extend(
            (instruction, "jupiter_other", f"leg_b_other_{index}")
            for index, instruction in enumerate(leg_b_other)
        )
        specs.append((leg_b_swap, "jupiter_swap", "jupiter_leg_b"))
        specs.append(
            (
                prepared.repay_instruction,
                "marginfi_repay",
                "marginfi_flash_repay",
            )
        )
        specs.extend(
            (instruction, "jupiter_cleanup", f"cleanup_{index}")
            for index, instruction in enumerate(cleanup)
        )
        specs.append((final[end_index], "marginfi_end", "marginfi_end_flashloan"))
        if tuple(instruction for instruction, _, _ in specs) != final:
            raise AtomicPlannerError(
                AtomicPlannerRejectionCode.SEQUENCE_INVARIANT,
                "planned instruction metadata does not match final sequence",
            )
        return tuple(
            PlannedInstruction(instruction=instruction, role=role, name=name)
            for instruction, role, name in specs
        )


def _solders_many(
    values: Sequence[JupiterRawInstruction],
) -> tuple[Instruction, ...]:
    return tuple(value.to_solders_instruction() for value in values)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AtomicPlannerError(
            AtomicPlannerRejectionCode.INVALID_REQUEST,
            f"{label} must be a positive integer",
        )
    return value


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _dedupe_pubkeys(values: Sequence[Pubkey] | Any) -> tuple[Pubkey, ...]:
    result: list[Pubkey] = []
    seen: set[Pubkey] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _raw_instruction_record(value: JupiterRawInstruction | None) -> object:
    if value is None:
        return None
    return {
        "program_id": value.program_id,
        "accounts": [
            {
                "pubkey": account.pubkey,
                "is_signer": account.is_signer,
                "is_writable": account.is_writable,
            }
            for account in value.accounts
        ],
        "data_b64": value.data_b64,
        "name": value.name,
    }


def _bundle_fingerprint(bundle: JupiterInstructionBundle) -> str:
    payload = {
        "input_mint": bundle.input_mint,
        "output_mint": bundle.output_mint,
        "in_amount": bundle.in_amount,
        "out_amount": bundle.out_amount,
        "other_amount_threshold": bundle.other_amount_threshold,
        "swap_mode": bundle.swap_mode,
        "slippage_bps": bundle.slippage_bps,
        "route_plan": bundle.route_plan,
        "setup": [
            _raw_instruction_record(value) for value in bundle.setup_instructions
        ],
        "other": [
            _raw_instruction_record(value) for value in bundle.other_instructions
        ],
        "swap": _raw_instruction_record(bundle.swap_instruction),
        "cleanup": _raw_instruction_record(bundle.cleanup_instruction),
        "alt": dict(bundle.addresses_by_lookup_table_address),
        "blockhash": dict(bundle.blockhash_with_metadata),
    }
    return _sha256_json(payload)


def _instruction_sequence_fingerprint(
    instructions: Sequence[Instruction],
) -> str:
    digest = hashlib.sha256()
    for instruction in instructions:
        digest.update(bytes(instruction.program_id))
        digest.update(len(instruction.data).to_bytes(4, "little"))
        digest.update(instruction.data)
        for account in instruction.accounts:
            digest.update(bytes(account.pubkey))
            digest.update(bytes((int(account.is_signer), int(account.is_writable))))
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
