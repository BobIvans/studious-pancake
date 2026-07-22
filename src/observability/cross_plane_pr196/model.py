"""PR-196 immutable evidence and verified-projection models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

PR196_SCHEMA = "pr196.cross-plane-terminal-truth.v1"
PR196_DATABASE_PRODUCT = "pr196.verified-terminal-projection"
PR196_METRICS_SCHEMA = "pr196.verified-terminal-metrics.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_PLACEHOLDERS = frozenset({"", "unknown", "placeholder", "none", "null", "n/a"})


class TerminalTruthState(StrEnum):
    NON_TERMINAL = "non-terminal"
    TERMINAL_SUCCESS = "terminal-success"
    TERMINAL_FAILURE = "terminal-failure"
    AMBIGUOUS = "ambiguous"
    CONFLICTED = "conflicted"
    CORRECTED = "corrected"


class CanonicalOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class ReservationTerminalState(StrEnum):
    CONSUMED = "consumed"
    RELEASED = "released"


class TruthPlane(StrEnum):
    LIFECYCLE = "lifecycle"
    SETTLEMENT = "settlement"
    LEDGER = "ledger"


class CrossPlaneTruthError(RuntimeError):
    """Invalid product ownership, projection state, or truth-plane evidence."""


@dataclass(frozen=True, slots=True)
class PlaneWatermark:
    plane: TruthPlane
    database_epoch: str
    sequence_no: int
    observed_at_ns: int

    def __post_init__(self) -> None:
        require_id(self.database_epoch, "database_epoch")
        if self.sequence_no < 0 or self.observed_at_ns < 0:
            raise ValueError("watermark sequence/time must be non-negative")


@dataclass(frozen=True, slots=True)
class LifecycleTerminalEvidence:
    attempt_id: str
    attempt_generation: int
    logical_opportunity_id: str
    plan_hash: str
    lifecycle_event_id: str
    lifecycle_event_hash: str
    reservation_state: ReservationTerminalState
    outcome: CanonicalOutcome
    terminal_reason: str
    watermark: PlaneWatermark

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "logical_opportunity_id",
            "lifecycle_event_id",
            "terminal_reason",
        ):
            require_id(str(getattr(self, name)), name)
        require_sha(self.plan_hash, "plan_hash")
        require_sha(self.lifecycle_event_hash, "lifecycle_event_hash")
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        if self.watermark.plane is not TruthPlane.LIFECYCLE:
            raise ValueError("lifecycle evidence requires lifecycle watermark")
        expected = (
            ReservationTerminalState.CONSUMED
            if self.outcome is CanonicalOutcome.SUCCESS
            else ReservationTerminalState.RELEASED
        )
        if self.reservation_state is not expected:
            raise ValueError("lifecycle outcome and reservation state disagree")


@dataclass(frozen=True, slots=True)
class FinalizedSettlementEvidence:
    attempt_id: str
    attempt_generation: int
    message_hash: str
    finalized_signature: str
    finalized_slot: int
    settlement_evidence_digest: str
    asset_mint: str
    amount_base_units: int
    outcome: CanonicalOutcome
    watermark: PlaneWatermark

    def __post_init__(self) -> None:
        require_id(self.attempt_id, "attempt_id")
        require_id(self.finalized_signature, "finalized_signature")
        require_id(self.asset_mint, "asset_mint")
        require_sha(self.message_hash, "message_hash")
        require_sha(self.settlement_evidence_digest, "settlement_evidence_digest")
        if self.attempt_generation < 0 or self.finalized_slot <= 0:
            raise ValueError("invalid settlement generation/slot")
        require_int(self.amount_base_units, "amount_base_units")
        if self.watermark.plane is not TruthPlane.SETTLEMENT:
            raise ValueError("settlement evidence requires settlement watermark")


@dataclass(frozen=True, slots=True)
class LedgerPostingEvidence:
    attempt_id: str
    attempt_generation: int
    posting_id: str
    posting_hash: str
    settlement_evidence_digest: str
    asset_mint: str
    amount_base_units: int
    outcome: CanonicalOutcome
    watermark: PlaneWatermark

    def __post_init__(self) -> None:
        require_id(self.attempt_id, "attempt_id")
        require_id(self.posting_id, "posting_id")
        require_id(self.asset_mint, "asset_mint")
        require_sha(self.posting_hash, "posting_hash")
        require_sha(self.settlement_evidence_digest, "settlement_evidence_digest")
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        require_int(self.amount_base_units, "amount_base_units")
        if self.watermark.plane is not TruthPlane.LEDGER:
            raise ValueError("ledger evidence requires ledger watermark")


@dataclass(frozen=True, slots=True)
class ReleasePolicyEvidence:
    release_id: str
    release_hash: str
    policy_bundle_hash: str
    approved: bool = True

    def __post_init__(self) -> None:
        require_id(self.release_id, "release_id")
        require_sha(self.release_hash, "release_hash")
        require_sha(self.policy_bundle_hash, "policy_bundle_hash")
        if not self.approved:
            raise ValueError("PR196_RELEASE_POLICY_NOT_APPROVED")


@dataclass(frozen=True, slots=True)
class AuthoritativeTruthBundle:
    lifecycle: LifecycleTerminalEvidence
    settlement: FinalizedSettlementEvidence | None
    ledger: LedgerPostingEvidence | None
    release_policy: ReleasePolicyEvidence


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    attempt_id: str
    attempt_generation: int
    state: TerminalTruthState
    outcome: CanonicalOutcome | None
    reason_codes: tuple[str, ...]
    projection_hash: str
    reconciled_sequence: int
    release_ready: bool
    replayed: bool = False

    @property
    def authoritative(self) -> bool:
        return self.state in {
            TerminalTruthState.TERMINAL_SUCCESS,
            TerminalTruthState.TERMINAL_FAILURE,
            TerminalTruthState.CORRECTED,
        }

    @property
    def counts_as_success(self) -> bool:
        return self.authoritative and self.outcome is CanonicalOutcome.SUCCESS


@dataclass(frozen=True, slots=True)
class VerifiedTerminalProjection:
    attempt_id: str
    attempt_generation: int
    logical_opportunity_id: str
    state: TerminalTruthState
    outcome: CanonicalOutcome | None
    plan_hash: str
    message_hash: str | None
    lifecycle_event_id: str | None
    settlement_evidence_digest: str | None
    ledger_posting_id: str | None
    release_hash: str | None
    policy_bundle_hash: str | None
    asset_mint: str | None
    amount_base_units: int | None
    finalized_signature: str | None
    finalized_slot: int | None
    source_event_id: str
    source_sequence_no: int
    reason_codes: tuple[str, ...]
    projection_hash: str
    release_ready: bool


def conflicted_projection(
    existing: VerifiedTerminalProjection,
    incoming: VerifiedTerminalProjection,
) -> VerifiedTerminalProjection:
    reasons = tuple(
        sorted(
            set(
                existing.reason_codes
                + incoming.reason_codes
                + ("PR196_CONFLICTING_TERMINAL_EVIDENCE",)
            )
        )
    )
    digest = hash_json(
        {
            "existing": existing.projection_hash,
            "incoming": incoming.projection_hash,
            "state": TerminalTruthState.CONFLICTED.value,
            "reasons": reasons,
        }
    )
    return VerifiedTerminalProjection(
        attempt_id=incoming.attempt_id,
        attempt_generation=incoming.attempt_generation,
        logical_opportunity_id=incoming.logical_opportunity_id,
        state=TerminalTruthState.CONFLICTED,
        outcome=None,
        plan_hash=incoming.plan_hash,
        message_hash=incoming.message_hash,
        lifecycle_event_id=incoming.lifecycle_event_id,
        settlement_evidence_digest=incoming.settlement_evidence_digest,
        ledger_posting_id=incoming.ledger_posting_id,
        release_hash=incoming.release_hash,
        policy_bundle_hash=incoming.policy_bundle_hash,
        asset_mint=incoming.asset_mint,
        amount_base_units=incoming.amount_base_units,
        finalized_signature=incoming.finalized_signature,
        finalized_slot=incoming.finalized_slot,
        source_event_id=incoming.source_event_id,
        source_sequence_no=incoming.source_sequence_no,
        reason_codes=reasons,
        projection_hash=digest,
        release_ready=False,
    )


def projection_json(projection: VerifiedTerminalProjection) -> str:
    payload = asdict(projection)
    payload["state"] = projection.state.value
    payload["outcome"] = projection.outcome.value if projection.outcome else None
    payload["reason_codes"] = list(projection.reason_codes)
    return canonical_json(payload)


def projection_from_json(encoded: str) -> VerifiedTerminalProjection:
    payload = json.loads(encoded)
    return VerifiedTerminalProjection(
        **{
            **payload,
            "state": TerminalTruthState(str(payload["state"])),
            "outcome": (
                CanonicalOutcome(str(payload["outcome"]))
                if payload.get("outcome")
                else None
            ),
            "reason_codes": tuple(payload.get("reason_codes", ())),
        }
    )


def placeholder(value: object) -> bool:
    return str(value or "").strip().lower() in _PLACEHOLDERS


def valid_sha(value: object) -> bool:
    text = str(value or "")
    return bool(_SHA256.fullmatch(text)) and not (
        len(set(text)) == 1 and text[0] in {"0", "f"}
    )


def require_sha(value: str, field: str) -> None:
    if not valid_sha(value):
        raise ValueError(f"{field} must be a non-placeholder lowercase sha256")


def require_id(value: str, field: str) -> None:
    if placeholder(value) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a non-placeholder stable identity")


def require_int(value: object, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def hash_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
