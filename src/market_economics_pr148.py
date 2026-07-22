"""PR-148 market, MarginFi state and exact economic decision kernel.

Side-effect-free PR-148 primitive: no provider/RPC call, no compile, no
simulation, no signing, and no sending.  It consumes explicit evidence and
returns EXACT_CANDIDATE, NO_TRADE, or BLOCKED.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class EconomicDecision(StrEnum):
    EXACT_CANDIDATE = "EXACT_CANDIDATE"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"


class EconomicReason(StrEnum):
    READY = "ready"
    NON_POSITIVE_VALUE = "non_positive_value"
    BELOW_MIN_PROFIT = "below_min_profit"
    PLACEHOLDER_HASH = "placeholder_hash"
    EXACT_AMOUNT_MISMATCH = "exact_amount_mismatch"
    LINEAR_PROJECTION_FORBIDDEN = "linear_projection_forbidden"
    EMPTY_ROUTE_PROGRAMS = "empty_route_programs"
    QUOTE_EXPIRED = "quote_expired"
    MIXED_SLOT_STATE = "mixed_slot_state"
    MARGINFI_UNREVIEWED = "marginfi_unreviewed"
    MARGINFI_PAUSED = "marginfi_paused"
    MARGINFI_FLASHLOAN_UNVERIFIED = "marginfi_flashloan_unverified"
    ASSET_UNATTESTED = "asset_unattested"
    TOKEN_2022_UNSUPPORTED = "token_2022_unsupported"
    LST_UNAPPROVED = "lst_unapproved"
    FLASH_FEE_MISMATCH = "flash_fee_mismatch"
    FLASH_FEE_DOUBLE_COUNTED = "flash_fee_double_counted"
    WALLET_SOL_UNRESERVED = "wallet_sol_unreserved"
    ATA_RENT_UNRESERVED = "ata_rent_unreserved"
    DUPLICATE_OR_COOLDOWN = "duplicate_or_cooldown"


TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


@dataclass(frozen=True, slots=True)
class RouteQuoteEvidence:
    provider: str
    leg_id: str
    input_mint: str
    output_mint: str
    exact_input_atoms: int
    quoted_output_atoms: int
    request_hash: str
    response_hash: str
    route_program_ids: tuple[str, ...]
    slot: int
    expires_at_slot: int
    provider_native_expiry_hash: str
    derived_from_linear_projection: bool = False

    def __post_init__(self) -> None:
        for name in ("provider", "leg_id", "input_mint", "output_mint"):
            _require_nonempty(name, getattr(self, name))
        for name in ("exact_input_atoms", "quoted_output_atoms", "slot", "expires_at_slot"):
            _require_non_negative_int(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class MarginFiStateEvidence:
    context_slot: int
    root_slot: int
    group_hash: str
    bank_hashes: tuple[str, ...]
    oracle_hashes: tuple[str, ...]
    vault_hashes: tuple[str, ...]
    canonical_idl_hash: str
    account_vectors_hash: str
    instruction_vectors_hash: str
    rpc_evidence_hash: str
    flashloan_fee_bps: int
    flashloan_metas_verified: bool
    token_2022_paths_verified: bool
    human_reviewed: bool
    shadow_execution_capable: bool
    paused: bool = False

    def __post_init__(self) -> None:
        for name in ("context_slot", "root_slot", "flashloan_fee_bps"):
            _require_non_negative_int(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class AssetPolicy:
    mint: str
    token_program_id: str
    owner_verified: bool
    mint_authority_hash: str
    extension_policy_hash: str
    account_size: int
    rent_exempt_lamports: int
    transfer_fee_bps: int = 0
    transfer_hook_enabled: bool = False
    transfer_hook_policy_approved: bool = False
    is_lst: bool = False
    lst_policy_approved: bool = False

    def __post_init__(self) -> None:
        for name in ("mint", "token_program_id"):
            _require_nonempty(name, getattr(self, name))
        for name in ("account_size", "rent_exempt_lamports", "transfer_fee_bps"):
            _require_non_negative_int(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class WalletLifecyclePolicy:
    payer: str
    taker: str
    expected_ata_creations: int
    rent_reserved_lamports: int
    own_sol_debit_lamports: int
    reserved_wallet_sol_lamports: int
    wsol_wrap_lamports: int = 0
    cleanup_refund_lamports: int = 0
    jupiter_lifecycle_flags_hash: str = "unset"

    def __post_init__(self) -> None:
        _require_nonempty("payer", self.payer)
        _require_nonempty("taker", self.taker)
        for name in (
            "expected_ata_creations",
            "rent_reserved_lamports",
            "own_sol_debit_lamports",
            "reserved_wallet_sol_lamports",
            "wsol_wrap_lamports",
            "cleanup_refund_lamports",
        ):
            _require_non_negative_int(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class ExactCostLedger:
    principal_atoms: int
    flash_fee_atoms: int
    required_repayment_atoms: int
    gross_output_atoms: int
    swap_fees_atoms: int = 0
    transfer_fees_atoms: int = 0
    slippage_atoms: int = 0
    uncertainty_atoms: int = 0
    network_fee_lamports: int = 0
    priority_fee_lamports: int = 0
    tip_lamports: int = 0
    rent_locked_lamports: int = 0
    rent_refunded_lamports: int = 0
    flash_fee_entries: int = 1

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _require_non_negative_int(name, getattr(self, name))

    @property
    def conservative_profit_atoms(self) -> int:
        return (
            self.gross_output_atoms
            - self.required_repayment_atoms
            - self.swap_fees_atoms
            - self.transfer_fees_atoms
            - self.slippage_atoms
            - self.uncertainty_atoms
        )

    @property
    def landing_cost_lamports(self) -> int:
        return (
            self.network_fee_lamports
            + self.priority_fee_lamports
            + self.tip_lamports
            + max(0, self.rent_locked_lamports - self.rent_refunded_lamports)
        )


@dataclass(frozen=True, slots=True)
class ExactMarketKernelInput:
    strategy_id: str
    policy_version: str
    pair: str
    first_leg: RouteQuoteEvidence
    second_leg: RouteQuoteEvidence
    marginfi: MarginFiStateEvidence
    input_asset: AssetPolicy
    intermediate_asset: AssetPolicy
    output_asset: AssetPolicy
    lifecycle: WalletLifecyclePolicy
    ledger: ExactCostLedger
    current_slot: int
    evidence_generation: int
    min_profit_atoms: int = 1
    max_quote_slot_skew: int = 32
    seen_or_cooldown_logical_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("strategy_id", "policy_version", "pair"):
            _require_nonempty(name, getattr(self, name))
        for name in ("current_slot", "evidence_generation", "min_profit_atoms", "max_quote_slot_skew"):
            _require_non_negative_int(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class EconomicFailure:
    reason: EconomicReason
    detail: str


@dataclass(frozen=True, slots=True)
class ExactCandidate:
    logical_opportunity_id: str
    route_hash: str
    policy_version: str
    principal_atoms: int
    conservative_profit_atoms: int
    landing_cost_lamports: int
    first_leg_hash: str
    second_leg_hash: str
    marginfi_state_hash: str


@dataclass(frozen=True, slots=True)
class EconomicDecisionReport:
    decision: EconomicDecision
    reason: EconomicReason
    failures: tuple[EconomicFailure, ...]
    logical_opportunity_id: str
    report_hash: str
    candidate: ExactCandidate | None = None

    @property
    def exact_candidate(self) -> bool:
        return self.decision is EconomicDecision.EXACT_CANDIDATE

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "reason": self.reason.value,
            "logical_opportunity_id": self.logical_opportunity_id,
            "report_hash": self.report_hash,
            "candidate": None if self.candidate is None else _canonical_data(self.candidate),
            "failures": [
                {"reason": failure.reason.value, "detail": failure.detail}
                for failure in self.failures
            ],
        }


def evaluate_exact_market_candidate(kernel_input: ExactMarketKernelInput) -> EconomicDecisionReport:
    logical_id = logical_opportunity_id(kernel_input)
    failures: list[EconomicFailure] = []
    failures.extend(_validate_hashes(kernel_input))
    failures.extend(_validate_exact_quote_chain(kernel_input))
    failures.extend(_validate_slots(kernel_input))
    failures.extend(_validate_marginfi(kernel_input.marginfi))
    for asset in (kernel_input.input_asset, kernel_input.intermediate_asset, kernel_input.output_asset):
        failure = _validate_asset(asset)
        if failure is not None:
            failures.append(failure)
    failures.extend(_validate_lifecycle(kernel_input))
    failures.extend(_validate_ledger(kernel_input))
    if logical_id in set(kernel_input.seen_or_cooldown_logical_ids):
        failures.append(
            EconomicFailure(
                EconomicReason.DUPLICATE_OR_COOLDOWN,
                "logical opportunity is already seen or in cooldown",
            )
        )
    if failures:
        return _report(EconomicDecision.BLOCKED, failures[0].reason, tuple(failures), logical_id, kernel_input, None)

    profit = kernel_input.ledger.conservative_profit_atoms
    if profit <= 0:
        failure = EconomicFailure(EconomicReason.NON_POSITIVE_VALUE, "conservative integer result is not positive")
        return _report(EconomicDecision.NO_TRADE, failure.reason, (failure,), logical_id, kernel_input, None)
    if profit < kernel_input.min_profit_atoms:
        failure = EconomicFailure(
            EconomicReason.BELOW_MIN_PROFIT,
            "conservative integer result is below configured minimum",
        )
        return _report(EconomicDecision.NO_TRADE, failure.reason, (failure,), logical_id, kernel_input, None)

    first_hash = evidence_hash("flashloan-bot/market-route-leg", kernel_input.first_leg)
    second_hash = evidence_hash("flashloan-bot/market-route-leg", kernel_input.second_leg)
    marginfi_hash = evidence_hash("flashloan-bot/marginfi-state", kernel_input.marginfi)
    candidate = ExactCandidate(
        logical_opportunity_id=logical_id,
        route_hash=evidence_hash(
            "flashloan-bot/exact-route",
            {
                "first_leg": first_hash,
                "second_leg": second_hash,
                "programs": sorted(set(kernel_input.first_leg.route_program_ids) | set(kernel_input.second_leg.route_program_ids)),
            },
        ),
        policy_version=kernel_input.policy_version,
        principal_atoms=kernel_input.ledger.principal_atoms,
        conservative_profit_atoms=profit,
        landing_cost_lamports=kernel_input.ledger.landing_cost_lamports,
        first_leg_hash=first_hash,
        second_leg_hash=second_hash,
        marginfi_state_hash=marginfi_hash,
    )
    return _report(EconomicDecision.EXACT_CANDIDATE, EconomicReason.READY, (), logical_id, kernel_input, candidate)


def logical_opportunity_id(kernel_input: ExactMarketKernelInput) -> str:
    payload = {
        "strategy_id": kernel_input.strategy_id,
        "policy_version": kernel_input.policy_version,
        "pair": kernel_input.pair,
        "first_leg": {
            "provider": kernel_input.first_leg.provider,
            "exact_input_atoms": kernel_input.first_leg.exact_input_atoms,
            "quoted_output_atoms": kernel_input.first_leg.quoted_output_atoms,
            "request_hash": kernel_input.first_leg.request_hash,
            "response_hash": kernel_input.first_leg.response_hash,
            "slot": kernel_input.first_leg.slot,
        },
        "second_leg": {
            "provider": kernel_input.second_leg.provider,
            "exact_input_atoms": kernel_input.second_leg.exact_input_atoms,
            "quoted_output_atoms": kernel_input.second_leg.quoted_output_atoms,
            "request_hash": kernel_input.second_leg.request_hash,
            "response_hash": kernel_input.second_leg.response_hash,
            "slot": kernel_input.second_leg.slot,
        },
        "marginfi_root_slot": kernel_input.marginfi.root_slot,
        "evidence_generation": kernel_input.evidence_generation,
    }
    return evidence_hash("flashloan-bot/logical-opportunity", payload)


def evidence_hash(domain: str, payload: object) -> str:
    envelope = {
        "domain": domain,
        "schema_version": "pr148.exact-economic-kernel.v1",
        "payload": _canonical_data(payload),
    }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_hashes(kernel_input: ExactMarketKernelInput) -> tuple[EconomicFailure, ...]:
    failures: list[EconomicFailure] = []
    values = [
        ("first.request_hash", kernel_input.first_leg.request_hash),
        ("first.response_hash", kernel_input.first_leg.response_hash),
        ("first.provider_native_expiry_hash", kernel_input.first_leg.provider_native_expiry_hash),
        ("second.request_hash", kernel_input.second_leg.request_hash),
        ("second.response_hash", kernel_input.second_leg.response_hash),
        ("second.provider_native_expiry_hash", kernel_input.second_leg.provider_native_expiry_hash),
        ("marginfi.group_hash", kernel_input.marginfi.group_hash),
        ("marginfi.canonical_idl_hash", kernel_input.marginfi.canonical_idl_hash),
        ("marginfi.account_vectors_hash", kernel_input.marginfi.account_vectors_hash),
        ("marginfi.instruction_vectors_hash", kernel_input.marginfi.instruction_vectors_hash),
        ("marginfi.rpc_evidence_hash", kernel_input.marginfi.rpc_evidence_hash),
        ("input_asset.mint_authority_hash", kernel_input.input_asset.mint_authority_hash),
        ("intermediate_asset.mint_authority_hash", kernel_input.intermediate_asset.mint_authority_hash),
        ("output_asset.mint_authority_hash", kernel_input.output_asset.mint_authority_hash),
        ("lifecycle.jupiter_lifecycle_flags_hash", kernel_input.lifecycle.jupiter_lifecycle_flags_hash),
    ]
    values.extend((f"marginfi.bank_hashes[{idx}]", value) for idx, value in enumerate(kernel_input.marginfi.bank_hashes))
    values.extend((f"marginfi.oracle_hashes[{idx}]", value) for idx, value in enumerate(kernel_input.marginfi.oracle_hashes))
    values.extend((f"marginfi.vault_hashes[{idx}]", value) for idx, value in enumerate(kernel_input.marginfi.vault_hashes))
    for name, value in values:
        if _looks_placeholder_hash(value):
            failures.append(EconomicFailure(EconomicReason.PLACEHOLDER_HASH, f"{name} is missing or placeholder-shaped"))
    return tuple(failures)


def _validate_exact_quote_chain(kernel_input: ExactMarketKernelInput) -> tuple[EconomicFailure, ...]:
    failures: list[EconomicFailure] = []
    first = kernel_input.first_leg
    second = kernel_input.second_leg
    if first.derived_from_linear_projection or second.derived_from_linear_projection:
        failures.append(EconomicFailure(EconomicReason.LINEAR_PROJECTION_FORBIDDEN, "quotes must be provider-native exact amount evidence"))
    if not first.route_program_ids or not second.route_program_ids:
        failures.append(EconomicFailure(EconomicReason.EMPTY_ROUTE_PROGRAMS, "route program identities are required"))
    if first.output_mint != second.input_mint:
        failures.append(EconomicFailure(EconomicReason.EXACT_AMOUNT_MISMATCH, "first-leg output mint must equal second-leg input mint"))
    if first.quoted_output_atoms != second.exact_input_atoms:
        failures.append(EconomicFailure(EconomicReason.EXACT_AMOUNT_MISMATCH, "second leg must be quoted for exact first-leg output atoms"))
    if second.quoted_output_atoms != kernel_input.ledger.gross_output_atoms:
        failures.append(EconomicFailure(EconomicReason.EXACT_AMOUNT_MISMATCH, "ledger gross output must equal exact second-leg output atoms"))
    if first.exact_input_atoms != kernel_input.ledger.principal_atoms:
        failures.append(EconomicFailure(EconomicReason.EXACT_AMOUNT_MISMATCH, "ledger principal must equal exact first-leg input atoms"))
    return tuple(failures)


def _validate_slots(kernel_input: ExactMarketKernelInput) -> tuple[EconomicFailure, ...]:
    failures: list[EconomicFailure] = []
    for leg in (kernel_input.first_leg, kernel_input.second_leg):
        if kernel_input.current_slot > leg.expires_at_slot:
            failures.append(EconomicFailure(EconomicReason.QUOTE_EXPIRED, f"{leg.leg_id} quote expired"))
    if kernel_input.marginfi.root_slot > kernel_input.marginfi.context_slot:
        failures.append(EconomicFailure(EconomicReason.MIXED_SLOT_STATE, "MarginFi root slot cannot exceed context slot"))
    slots = (kernel_input.first_leg.slot, kernel_input.second_leg.slot, kernel_input.marginfi.context_slot)
    if max(slots) - min(slots) > kernel_input.max_quote_slot_skew:
        failures.append(EconomicFailure(EconomicReason.MIXED_SLOT_STATE, "route and MarginFi evidence exceed allowed slot skew"))
    if kernel_input.first_leg.slot < kernel_input.marginfi.root_slot or kernel_input.second_leg.slot < kernel_input.marginfi.root_slot:
        failures.append(EconomicFailure(EconomicReason.MIXED_SLOT_STATE, "quote evidence is older than rooted MarginFi state"))
    return tuple(failures)


def _validate_marginfi(marginfi: MarginFiStateEvidence) -> tuple[EconomicFailure, ...]:
    failures: list[EconomicFailure] = []
    if marginfi.paused:
        failures.append(EconomicFailure(EconomicReason.MARGINFI_PAUSED, "MarginFi state is paused"))
    if not marginfi.human_reviewed:
        failures.append(EconomicFailure(EconomicReason.MARGINFI_UNREVIEWED, "MarginFi evidence is not human reviewed"))
    if not marginfi.shadow_execution_capable:
        failures.append(EconomicFailure(EconomicReason.MARGINFI_FLASHLOAN_UNVERIFIED, "MarginFi evidence is not shadow execution capable"))
    if not marginfi.flashloan_metas_verified:
        failures.append(EconomicFailure(EconomicReason.MARGINFI_FLASHLOAN_UNVERIFIED, "flashloan instruction metas are not verified"))
    if not marginfi.token_2022_paths_verified:
        failures.append(EconomicFailure(EconomicReason.MARGINFI_FLASHLOAN_UNVERIFIED, "Token-2022 MarginFi paths are not verified"))
    return tuple(failures)


def _validate_asset(asset: AssetPolicy) -> EconomicFailure | None:
    if not asset.owner_verified or _looks_placeholder_hash(asset.mint_authority_hash):
        return EconomicFailure(EconomicReason.ASSET_UNATTESTED, f"{asset.mint} owner/authority evidence missing")
    if asset.token_program_id == TOKEN_2022_PROGRAM_ID and asset.transfer_hook_enabled and not asset.transfer_hook_policy_approved:
        return EconomicFailure(EconomicReason.TOKEN_2022_UNSUPPORTED, f"{asset.mint} Token-2022 transfer hook is not approved")
    if asset.is_lst and not asset.lst_policy_approved:
        return EconomicFailure(EconomicReason.LST_UNAPPROVED, f"{asset.mint} LST policy is not approved")
    return None


def _validate_lifecycle(kernel_input: ExactMarketKernelInput) -> tuple[EconomicFailure, ...]:
    lifecycle = kernel_input.lifecycle
    assets = (kernel_input.input_asset, kernel_input.intermediate_asset, kernel_input.output_asset)
    required_rent = lifecycle.expected_ata_creations * max(asset.rent_exempt_lamports for asset in assets)
    failures: list[EconomicFailure] = []
    if lifecycle.rent_reserved_lamports < required_rent:
        failures.append(EconomicFailure(EconomicReason.ATA_RENT_UNRESERVED, "ATA creation rent is not fully reserved"))
    required_own_sol = lifecycle.own_sol_debit_lamports + kernel_input.ledger.landing_cost_lamports
    if lifecycle.reserved_wallet_sol_lamports < required_own_sol:
        failures.append(EconomicFailure(EconomicReason.WALLET_SOL_UNRESERVED, "own-wallet SOL debit/landing cost is not fully reserved"))
    return tuple(failures)


def _validate_ledger(kernel_input: ExactMarketKernelInput) -> tuple[EconomicFailure, ...]:
    ledger = kernel_input.ledger
    expected_flash_fee = (ledger.principal_atoms * kernel_input.marginfi.flashloan_fee_bps + 9_999) // 10_000
    failures: list[EconomicFailure] = []
    if ledger.flash_fee_atoms != expected_flash_fee:
        failures.append(EconomicFailure(EconomicReason.FLASH_FEE_MISMATCH, "flash fee does not match MarginFi fee bps"))
    if ledger.required_repayment_atoms != ledger.principal_atoms + ledger.flash_fee_atoms:
        failures.append(EconomicFailure(EconomicReason.FLASH_FEE_MISMATCH, "repayment must be principal plus exactly one flash fee"))
    if ledger.flash_fee_entries != 1:
        failures.append(EconomicFailure(EconomicReason.FLASH_FEE_DOUBLE_COUNTED, "flash fee must appear exactly once"))
    return tuple(failures)


def _report(
    decision: EconomicDecision,
    reason: EconomicReason,
    failures: tuple[EconomicFailure, ...],
    logical_id: str,
    kernel_input: ExactMarketKernelInput,
    candidate: ExactCandidate | None,
) -> EconomicDecisionReport:
    payload = {
        "decision": decision.value,
        "reason": reason.value,
        "logical_id": logical_id,
        "candidate": None if candidate is None else _canonical_data(candidate),
        "failures": [_canonical_data(failure) for failure in failures],
        "input_hash": evidence_hash("flashloan-bot/exact-market-kernel-input", kernel_input),
    }
    return EconomicDecisionReport(
        decision=decision,
        reason=reason,
        failures=failures,
        logical_opportunity_id=logical_id,
        report_hash=evidence_hash("flashloan-bot/exact-market-decision", payload),
        candidate=candidate,
    )


def _canonical_data(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {field_name: _canonical_data(getattr(value, field_name)) for field_name in sorted(value.__dataclass_fields__)}  # type: ignore[attr-defined]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical_data(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_canonical_data(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str | int):
        return value
    if isinstance(value, float):
        raise TypeError("binary floats are not allowed in PR-148 economic evidence")
    return value


def _looks_placeholder_hash(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"", "0", "placeholder", "todo", "pending", "null", "none", "unset"}:
        return True
    if len(normalized) < 16:
        return True
    return len(set(normalized)) == 1


def _require_nonempty(name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{name} must be non-empty")


def _require_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer base-unit value")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


__all__ = [
    "AssetPolicy",
    "EconomicDecision",
    "EconomicDecisionReport",
    "EconomicFailure",
    "EconomicReason",
    "ExactCandidate",
    "ExactCostLedger",
    "ExactMarketKernelInput",
    "MarginFiStateEvidence",
    "RouteQuoteEvidence",
    "SPL_TOKEN_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "WalletLifecyclePolicy",
    "evaluate_exact_market_candidate",
    "evidence_hash",
    "logical_opportunity_id",
]
