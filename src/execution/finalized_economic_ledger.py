"""MPR-2610 finalized economic truth consumer.

This module is deliberately sender-free and persistence-free.  It consumes an
already-finalized attempt identity plus decoded, atomic-unit economic movements
and produces one deterministic economic classification.  Durable lifecycle and
capital ownership remain with the existing runtime authority; callers persist
this result through that owner rather than creating a second ledger database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any, Iterable

MPR2610_SCHEMA_VERSION = "mpr2610.finalized-economic-ledger.v1"
SOL_ASSET_ID = "native:SOL:lamports"


class FinalizedEconomicLedgerError(ValueError):
    """Raised when finalized economic input is malformed or contradictory."""


class PostingKind(str, Enum):
    STRATEGY_ASSET_DELTA = "strategy_asset_delta"
    NETWORK_FEE = "network_fee"
    JITO_TIP = "jito_tip"
    RENT_LOCK = "rent_lock"
    RENT_REFUND = "rent_refund"
    PROTOCOL_FEE = "protocol_fee"
    TOKEN_TRANSFER_FEE = "token_transfer_fee"
    FLASHLOAN_PRINCIPAL = "flashloan_principal"
    FLASHLOAN_REPAYMENT = "flashloan_repayment"
    FAILED_ATTEMPT_COST = "failed_attempt_cost"
    FUNDING = "funding"
    WITHDRAWAL_SWEEP = "withdrawal_sweep"
    ADJUSTMENT_CORRECTION = "adjustment_correction"


class FinalizedEconomicOutcome(str, Enum):
    UNKNOWN_QUARANTINED = "unknown_quarantined"
    FINALIZED_FAILURE_COSTED = "finalized_failure_costed"
    FINALIZED_PENDING_ECONOMICS = "finalized_pending_economics"
    FINALIZED_REALIZED_LOSS = "finalized_realized_loss"
    FINALIZED_REALIZED_BREAK_EVEN = "finalized_realized_break_even"
    FINALIZED_REALIZED_PROFIT = "finalized_realized_profit"
    FINALIZED_REALIZED_PARTIAL = "finalized_realized_partial"


@dataclass(frozen=True, slots=True)
class AttemptEconomicLineage:
    attempt_id: str
    attempt_generation: int
    message_hash: str
    signed_transaction_digest: str
    primary_signature: str
    finalized_slot: int
    release_hash: str
    config_hash: str
    policy_hash: str
    cluster_genesis_hash: str
    raw_evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_generation": self.attempt_generation,
            "message_hash": self.message_hash,
            "signed_transaction_digest": self.signed_transaction_digest,
            "primary_signature": self.primary_signature,
            "finalized_slot": self.finalized_slot,
            "release_hash": self.release_hash,
            "config_hash": self.config_hash,
            "policy_hash": self.policy_hash,
            "cluster_genesis_hash": self.cluster_genesis_hash,
            "raw_evidence_hash": self.raw_evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class EconomicPosting:
    posting_id: str
    asset_id: str
    base_units: int
    kind: PostingKind
    account_scope: str
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "posting_id": self.posting_id,
            "asset_id": self.asset_id,
            "base_units": self.base_units,
            "kind": self.kind.value,
            "account_scope": self.account_scope,
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class FinalizedEconomicInput:
    lineage: AttemptEconomicLineage
    confirmation_status: str
    meta_err: object | None
    marginfi_repayment_proven: bool
    economics_complete: bool
    postings: tuple[EconomicPosting, ...]
    payer_pre_lamports: int | None = None
    payer_post_lamports: int | None = None
    meta_fee_lamports: int | None = None


@dataclass(frozen=True, slots=True)
class FinalizedEconomicLedger:
    schema_version: str
    lineage: AttemptEconomicLineage
    outcome: FinalizedEconomicOutcome
    economically_successful: bool
    per_asset_delta: tuple[tuple[str, int], ...]
    blockers: tuple[str, ...]
    ledger_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lineage": self.lineage.to_dict(),
            "outcome": self.outcome.value,
            "economically_successful": self.economically_successful,
            "per_asset_delta": [
                {"asset_id": asset_id, "base_units": amount}
                for asset_id, amount in self.per_asset_delta
            ],
            "blockers": list(self.blockers),
            "ledger_hash": self.ledger_hash,
        }


def classify_finalized_economics(
    value: FinalizedEconomicInput,
) -> FinalizedEconomicLedger:
    """Recompute terminal economics from immutable atomic-unit postings.

    Cross-asset base units are never added.  Therefore a positive-profit claim
    is permitted only when the complete material result is representable in one
    asset.  A future accepted valuation projection may value multiple assets,
    but it must remain derived from these raw postings.
    """

    _validate_input(value)
    blockers: list[str] = []

    if value.confirmation_status.strip().lower() != "finalized":
        blockers.append("FINALIZED_EVIDENCE_REQUIRED")

    if not value.marginfi_repayment_proven and value.meta_err is None:
        blockers.append("MARGINFI_REPAYMENT_NOT_PROVEN")

    if value.payer_pre_lamports is not None:
        observed_native_delta = value.payer_post_lamports - value.payer_pre_lamports  # type: ignore[operator]
        posted_native_delta = sum(
            posting.base_units
            for posting in value.postings
            if posting.asset_id == SOL_ASSET_ID
            and posting.kind not in {PostingKind.FUNDING, PostingKind.WITHDRAWAL_SWEEP}
        )
        if observed_native_delta != posted_native_delta:
            blockers.append("PAYER_NATIVE_CONSERVATION_MISMATCH")

    if value.meta_fee_lamports is not None:
        network_fee = -sum(
            posting.base_units
            for posting in value.postings
            if posting.asset_id == SOL_ASSET_ID
            and posting.kind == PostingKind.NETWORK_FEE
        )
        if network_fee != value.meta_fee_lamports:
            blockers.append("META_FEE_DECOMPOSITION_MISMATCH")

    deltas = _strategy_deltas(value.postings)

    if blockers:
        return _result(
            value,
            outcome=FinalizedEconomicOutcome.UNKNOWN_QUARANTINED,
            successful=False,
            deltas=deltas,
            blockers=blockers,
        )

    if value.meta_err is not None:
        return _result(
            value,
            outcome=FinalizedEconomicOutcome.FINALIZED_FAILURE_COSTED,
            successful=False,
            deltas=deltas,
            blockers=("FINALIZED_TRANSACTION_META_ERR",),
        )

    if not value.economics_complete:
        return _result(
            value,
            outcome=FinalizedEconomicOutcome.FINALIZED_PENDING_ECONOMICS,
            successful=False,
            deltas=deltas,
            blockers=("FINALIZED_ECONOMICS_INCOMPLETE",),
        )

    nonzero = tuple((asset, amount) for asset, amount in deltas if amount != 0)
    if len(nonzero) > 1:
        return _result(
            value,
            outcome=FinalizedEconomicOutcome.FINALIZED_REALIZED_PARTIAL,
            successful=False,
            deltas=deltas,
            blockers=("CROSS_ASSET_VALUATION_REQUIRED",),
        )

    total = nonzero[0][1] if nonzero else 0
    if total > 0:
        outcome = FinalizedEconomicOutcome.FINALIZED_REALIZED_PROFIT
        successful = True
        final_blockers: tuple[str, ...] = ()
    elif total < 0:
        outcome = FinalizedEconomicOutcome.FINALIZED_REALIZED_LOSS
        successful = False
        final_blockers = ("FINALIZED_REALIZED_NET_NEGATIVE",)
    else:
        outcome = FinalizedEconomicOutcome.FINALIZED_REALIZED_BREAK_EVEN
        successful = False
        final_blockers = ("FINALIZED_REALIZED_NET_ZERO",)

    return _result(
        value,
        outcome=outcome,
        successful=successful,
        deltas=deltas,
        blockers=final_blockers,
    )


def _strategy_deltas(postings: Iterable[EconomicPosting]) -> tuple[tuple[str, int], ...]:
    by_asset: dict[str, int] = {}
    excluded = {PostingKind.FUNDING, PostingKind.WITHDRAWAL_SWEEP}
    for posting in postings:
        if posting.kind in excluded:
            continue
        by_asset[posting.asset_id] = by_asset.get(posting.asset_id, 0) + posting.base_units
    return tuple(sorted(by_asset.items()))


def _result(
    value: FinalizedEconomicInput,
    *,
    outcome: FinalizedEconomicOutcome,
    successful: bool,
    deltas: tuple[tuple[str, int], ...],
    blockers: Iterable[str],
) -> FinalizedEconomicLedger:
    blocker_tuple = tuple(blockers)
    canonical_postings = sorted(value.postings, key=lambda posting: posting.posting_id)
    body = {
        "schema_version": MPR2610_SCHEMA_VERSION,
        "lineage": value.lineage.to_dict(),
        "outcome": outcome.value,
        "economically_successful": successful,
        "per_asset_delta": list(deltas),
        "blockers": list(blocker_tuple),
        "postings": [posting.to_dict() for posting in canonical_postings],
    }
    return FinalizedEconomicLedger(
        schema_version=MPR2610_SCHEMA_VERSION,
        lineage=value.lineage,
        outcome=outcome,
        economically_successful=successful,
        per_asset_delta=deltas,
        blockers=blocker_tuple,
        ledger_hash=_hash_json(body),
    )


def _validate_input(value: FinalizedEconomicInput) -> None:
    lineage = value.lineage
    _nonempty(lineage.attempt_id, "attempt_id")
    _positive_int(lineage.attempt_generation, "attempt_generation")
    _nonempty(lineage.primary_signature, "primary_signature")
    _nonnegative_int(lineage.finalized_slot, "finalized_slot")
    for name in (
        "message_hash",
        "signed_transaction_digest",
        "release_hash",
        "config_hash",
        "policy_hash",
        "cluster_genesis_hash",
        "raw_evidence_hash",
    ):
        _sha256(getattr(lineage, name), name)

    seen: set[str] = set()
    for posting in value.postings:
        _nonempty(posting.posting_id, "posting_id")
        _nonempty(posting.asset_id, "asset_id")
        _nonempty(posting.account_scope, "account_scope")
        _sha256(posting.evidence_hash, "posting.evidence_hash")
        _strict_int(posting.base_units, "posting.base_units")
        if posting.posting_id in seen:
            raise FinalizedEconomicLedgerError("duplicate posting_id")
        seen.add(posting.posting_id)

    paired = value.payer_pre_lamports is not None or value.payer_post_lamports is not None
    if paired:
        if value.payer_pre_lamports is None or value.payer_post_lamports is None:
            raise FinalizedEconomicLedgerError("payer pre/post balances must be paired")
        _nonnegative_int(value.payer_pre_lamports, "payer_pre_lamports")
        _nonnegative_int(value.payer_post_lamports, "payer_post_lamports")
    if value.meta_fee_lamports is not None:
        _nonnegative_int(value.meta_fee_lamports, "meta_fee_lamports")


def _strict_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FinalizedEconomicLedgerError(f"{label} must be an integer")


def _nonnegative_int(value: object, label: str) -> None:
    _strict_int(value, label)
    if value < 0:  # type: ignore[operator]
        raise FinalizedEconomicLedgerError(f"{label} must be non-negative")


def _positive_int(value: object, label: str) -> None:
    _strict_int(value, label)
    if value <= 0:  # type: ignore[operator]
        raise FinalizedEconomicLedgerError(f"{label} must be positive")


def _nonempty(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise FinalizedEconomicLedgerError(f"{label} is required")


def _sha256(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise FinalizedEconomicLedgerError(f"{label} must be sha256 hex")
    try:
        int(value, 16)
    except ValueError as exc:
        raise FinalizedEconomicLedgerError(f"{label} must be sha256 hex") from exc


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MPR2610_SCHEMA_VERSION",
    "SOL_ASSET_ID",
    "AttemptEconomicLineage",
    "EconomicPosting",
    "FinalizedEconomicInput",
    "FinalizedEconomicLedger",
    "FinalizedEconomicLedgerError",
    "FinalizedEconomicOutcome",
    "PostingKind",
    "classify_finalized_economics",
]
