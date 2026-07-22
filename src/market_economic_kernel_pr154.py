"""PR-154 market, MarginFi state and exact economic decision gate.

Side-effect-free contract only: no provider/RPC/Jupiter/MarginFi/sender calls.
It checks recorded evidence before a later integration may emit an exact
market/economic candidate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re

PR154_SCHEMA_VERSION = "pr154.market-economic-kernel.v1"
PR154_RESULT_SCHEMA_VERSION = "pr154.market-economic-kernel-result.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class Decision(StrEnum):
    EXACT_CANDIDATE = "EXACT_CANDIDATE"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"


class Blocker(StrEnum):
    BAD_HASH = "BAD_HASH"
    ROUTE_AMOUNT_MISMATCH = "ROUTE_AMOUNT_MISMATCH"
    ROUTE_STALE = "ROUTE_STALE"
    ROUTE_UNATTESTED_PROGRAM = "ROUTE_UNATTESTED_PROGRAM"
    RANDOM_OR_MISSING_OPPORTUNITY_ID = "RANDOM_OR_MISSING_OPPORTUNITY_ID"
    MISSING_PERSISTENT_DEDUP = "MISSING_PERSISTENT_DEDUP"
    FINAL_BUILD_QUOTA_NOT_RESERVED = "FINAL_BUILD_QUOTA_NOT_RESERVED"
    RATE_LIMITER_NOT_SHARED = "RATE_LIMITER_NOT_SHARED"
    MARGINFI_INCOMPLETE = "MARGINFI_INCOMPLETE"
    MARGINFI_MIXED_SLOT = "MARGINFI_MIXED_SLOT"
    MARGINFI_NOT_REVIEWED = "MARGINFI_NOT_REVIEWED"
    ASSET_UNATTESTED = "ASSET_UNATTESTED"
    LST_OPTIONAL_NOT_DISABLED = "LST_OPTIONAL_NOT_DISABLED"
    MONOTONIC_SIZING_ASSUMED = "MONOTONIC_SIZING_ASSUMED"
    COST_LEDGER_INCOMPLETE = "COST_LEDGER_INCOMPLETE"
    WALLET_SOL_UNRESERVED = "WALLET_SOL_UNRESERVED"
    ATA_WSOL_LIFECYCLE_INCOMPLETE = "ATA_WSOL_LIFECYCLE_INCOMPLETE"
    PROFIT_BELOW_THRESHOLD = "PROFIT_BELOW_THRESHOLD"


@dataclass(frozen=True, slots=True)
class RouteLeg:
    input_amount_atoms: int
    output_amount_atoms: int
    request_sha256: str
    response_sha256: str
    route_program_ids: tuple[str, ...]
    expires_at_slot: int


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    first_leg: RouteLeg
    second_leg: RouteLeg
    final_rebuild_request_sha256: str
    final_rebuild_response_sha256: str
    exact_amount_coupled: bool


@dataclass(frozen=True, slots=True)
class OpportunityEvidence:
    logical_id: str
    identity_sha256: str
    persistent_dedup: bool
    persisted_cooldown: bool


@dataclass(frozen=True, slots=True)
class QuotaEvidence:
    call_budget_sha256: str
    final_build_quota_reserved: bool
    shared_limiter: bool
    retry_after_propagated: bool
    exact_request_cache: bool


@dataclass(frozen=True, slots=True)
class MarginFiEvidence:
    canonical_idl_sha256: str
    account_vectors_sha256: str
    instruction_vectors_sha256: str
    rpc_evidence_sha256: str
    group_bank_vault_oracle_sha256: str
    coherent_slot: int
    root_slot: int
    mixed_slot_detected: bool
    flashloan_metas_verified: bool
    token2022_paths_verified: bool
    human_reviewed: bool
    shadow_execution_capable: bool


@dataclass(frozen=True, slots=True)
class AssetEvidence:
    mint: str
    owner_sha256: str
    extensions_sha256: str
    authority_policy_sha256: str
    rent_model_sha256: str
    transfer_fee_policy_sha256: str
    lst_disabled_or_reviewed: bool
    attested: bool


@dataclass(frozen=True, slots=True)
class SizingEvidence:
    strategy: str
    sampled_amounts: tuple[int, ...]
    selected_amount_atoms: int
    non_monotonic_checked: bool


@dataclass(frozen=True, slots=True)
class CostLedger:
    principal_atoms: int
    flash_fee_atoms: int
    required_repayment_atoms: int
    swap_fees_atoms: int
    transfer_fees_atoms: int
    network_fee_atoms: int
    tip_atoms: int
    rent_locked_atoms: int
    rent_lost_atoms: int
    slippage_atoms: int
    uncertainty_atoms: int
    wallet_sol_reserved_atoms: int

    @property
    def total_cost_atoms(self) -> int:
        return (
            self.required_repayment_atoms
            + self.swap_fees_atoms
            + self.transfer_fees_atoms
            + self.network_fee_atoms
            + self.tip_atoms
            + self.rent_lost_atoms
            + self.slippage_atoms
            + self.uncertainty_atoms
        )


@dataclass(frozen=True, slots=True)
class AtaWsolEvidence:
    explicit_payer: bool
    explicit_taker: bool
    deterministic_atas: bool
    wrap_unwrap_declared: bool
    rent_reserved: bool
    cleanup_destination_declared: bool
    own_sol_debit_reserved: bool


@dataclass(frozen=True, slots=True)
class KernelEvidence:
    route: RouteEvidence
    opportunity: OpportunityEvidence
    quota: QuotaEvidence
    marginfi: MarginFiEvidence
    assets: tuple[AssetEvidence, ...]
    sizing: SizingEvidence
    ledger: CostLedger
    ata_wsol: AtaWsolEvidence
    attested_program_ids: frozenset[str]
    now_slot: int
    min_profit_atoms: int


@dataclass(frozen=True, slots=True)
class KernelDecision:
    schema_version: str
    decision: Decision
    candidate_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    conservative_net_atoms: int
    evidence_hash: str
    sender_submission_allowed: bool = False
    live_claim_allowed: bool = False


class MarketKernelError(ValueError):
    """Raised when PR-154 evidence cannot produce an exact candidate."""


def evaluate_pr154_market_kernel(evidence: KernelEvidence) -> KernelDecision:
    blockers: list[str] = []
    _check_route(evidence, blockers)
    _check_opportunity(evidence.opportunity, blockers)
    _check_quota(evidence.quota, blockers)
    _check_marginfi(evidence.marginfi, blockers)
    _check_assets(evidence.assets, blockers)
    _check_sizing(evidence.sizing, evidence.route.first_leg.input_amount_atoms, blockers)
    _check_ledger(evidence.ledger, blockers)
    _check_ata_wsol(evidence.ata_wsol, blockers)

    conservative_net = evidence.route.second_leg.output_amount_atoms - evidence.ledger.total_cost_atoms
    if conservative_net < evidence.min_profit_atoms:
        blockers.append(Blocker.PROFIT_BELOW_THRESHOLD.value)

    unique = tuple(dict.fromkeys(blockers))
    decision = (
        Decision.EXACT_CANDIDATE
        if not unique
        else Decision.NO_TRADE
        if unique == (Blocker.PROFIT_BELOW_THRESHOLD.value,)
        else Decision.BLOCKED
    )
    return KernelDecision(
        schema_version=PR154_RESULT_SCHEMA_VERSION,
        decision=decision,
        candidate_allowed=decision is Decision.EXACT_CANDIDATE,
        blockers=unique,
        warnings=("PR154_REVIEW_ONLY_RUNTIME_UNCHANGED",),
        conservative_net_atoms=conservative_net,
        evidence_hash=_hash_evidence(evidence),
    )


def assert_pr154_exact_candidate(evidence: KernelEvidence) -> KernelDecision:
    decision = evaluate_pr154_market_kernel(evidence)
    if decision.decision is not Decision.EXACT_CANDIDATE:
        raise MarketKernelError("PR154_BLOCKED:" + ",".join(decision.blockers))
    return decision


def _check_route(evidence: KernelEvidence, blockers: list[str]) -> None:
    route = evidence.route
    for leg in (route.first_leg, route.second_leg):
        if not _sha(leg.request_sha256) or not _sha(leg.response_sha256):
            blockers.append(Blocker.BAD_HASH.value)
        if evidence.now_slot >= leg.expires_at_slot:
            blockers.append(Blocker.ROUTE_STALE.value)
        unknown = sorted(set(leg.route_program_ids) - set(evidence.attested_program_ids))
        if unknown:
            blockers.append(Blocker.ROUTE_UNATTESTED_PROGRAM.value + ":" + ",".join(unknown))
    if route.second_leg.input_amount_atoms != route.first_leg.output_amount_atoms:
        blockers.append(Blocker.ROUTE_AMOUNT_MISMATCH.value)
    if not route.exact_amount_coupled:
        blockers.append(Blocker.ROUTE_AMOUNT_MISMATCH.value)
    if not _sha(route.final_rebuild_request_sha256) or not _sha(route.final_rebuild_response_sha256):
        blockers.append(Blocker.BAD_HASH.value)


def _check_opportunity(item: OpportunityEvidence, blockers: list[str]) -> None:
    lowered = item.logical_id.lower()
    if not item.logical_id or "uuid" in lowered or "random" in lowered or not _sha(item.identity_sha256):
        blockers.append(Blocker.RANDOM_OR_MISSING_OPPORTUNITY_ID.value)
    if not item.persistent_dedup or not item.persisted_cooldown:
        blockers.append(Blocker.MISSING_PERSISTENT_DEDUP.value)


def _check_quota(item: QuotaEvidence, blockers: list[str]) -> None:
    if not _sha(item.call_budget_sha256):
        blockers.append(Blocker.BAD_HASH.value)
    if not item.final_build_quota_reserved:
        blockers.append(Blocker.FINAL_BUILD_QUOTA_NOT_RESERVED.value)
    if not item.shared_limiter or not item.retry_after_propagated or not item.exact_request_cache:
        blockers.append(Blocker.RATE_LIMITER_NOT_SHARED.value)


def _check_marginfi(item: MarginFiEvidence, blockers: list[str]) -> None:
    required = (
        item.canonical_idl_sha256,
        item.account_vectors_sha256,
        item.instruction_vectors_sha256,
        item.rpc_evidence_sha256,
        item.group_bank_vault_oracle_sha256,
    )
    if any(not _sha(value) for value in required):
        blockers.append(Blocker.MARGINFI_INCOMPLETE.value)
    if item.mixed_slot_detected or item.coherent_slot <= 0 or item.root_slot <= 0:
        blockers.append(Blocker.MARGINFI_MIXED_SLOT.value)
    if not item.flashloan_metas_verified or not item.token2022_paths_verified:
        blockers.append(Blocker.MARGINFI_INCOMPLETE.value)
    if not item.human_reviewed or not item.shadow_execution_capable:
        blockers.append(Blocker.MARGINFI_NOT_REVIEWED.value)


def _check_assets(items: tuple[AssetEvidence, ...], blockers: list[str]) -> None:
    for item in items:
        required = (
            item.owner_sha256,
            item.extensions_sha256,
            item.authority_policy_sha256,
            item.rent_model_sha256,
            item.transfer_fee_policy_sha256,
        )
        if not item.attested or any(not _sha(value) for value in required):
            blockers.append(Blocker.ASSET_UNATTESTED.value + ":" + item.mint)
        if not item.lst_disabled_or_reviewed:
            blockers.append(Blocker.LST_OPTIONAL_NOT_DISABLED.value + ":" + item.mint)


def _check_sizing(item: SizingEvidence, expected_amount: int, blockers: list[str]) -> None:
    if item.selected_amount_atoms != expected_amount:
        blockers.append(Blocker.ROUTE_AMOUNT_MISMATCH.value)
    if item.strategy == "binary_monotonic" or not item.non_monotonic_checked:
        blockers.append(Blocker.MONOTONIC_SIZING_ASSUMED.value)


def _check_ledger(item: CostLedger, blockers: list[str]) -> None:
    values = [getattr(item, name) for name in item.__dataclass_fields__]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        blockers.append(Blocker.COST_LEDGER_INCOMPLETE.value)
    if item.required_repayment_atoms != item.principal_atoms + item.flash_fee_atoms:
        blockers.append(Blocker.COST_LEDGER_INCOMPLETE.value)
    required_sol = item.network_fee_atoms + item.tip_atoms + item.rent_locked_atoms + item.rent_lost_atoms
    if item.wallet_sol_reserved_atoms < required_sol:
        blockers.append(Blocker.WALLET_SOL_UNRESERVED.value)


def _check_ata_wsol(item: AtaWsolEvidence, blockers: list[str]) -> None:
    if not all(
        (
            item.explicit_payer,
            item.explicit_taker,
            item.deterministic_atas,
            item.wrap_unwrap_declared,
            item.rent_reserved,
            item.cleanup_destination_declared,
            item.own_sol_debit_reserved,
        )
    ):
        blockers.append(Blocker.ATA_WSOL_LIFECYCLE_INCOMPLETE.value)


def _sha(value: str) -> bool:
    return bool(_SHA_RE.fullmatch(value))


def _canonical(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return [_canonical(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {k: _canonical(getattr(value, k)) for k in sorted(value.__dataclass_fields__)}
    return value


def _hash_evidence(evidence: KernelEvidence) -> str:
    payload = {
        "domain": "flashloan-bot/pr154-market-economic-kernel",
        "schema_version": PR154_SCHEMA_VERSION,
        "payload": _canonical(evidence),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
