"""Typed contracts for roadmap PR-046 limited-live canary control."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "pr046.limited-live-canary.v1"
REPORT_SCHEMA_VERSION = "pr046.canary-report.v1"
OPERATOR_ACKNOWLEDGEMENT = "ENABLE LIMITED LIVE CANARY; NO AI AUTHORITY"


class CanaryControlError(ValueError):
    pass


class CanaryMode(StrEnum):
    SHADOW = "shadow"
    LIMITED_LIVE = "limited_live"


class ActorKind(StrEnum):
    HUMAN = "human"
    AUTOMATION = "automation"
    AI = "ai"


class ReconciliationStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    INDETERMINATE = "indeterminate"


class LatchCode(StrEnum):
    MANUAL_KILL_SWITCH = "manual_kill_switch"
    LOW_BALANCE = "low_balance"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    CONSECUTIVE_FAILURE_LIMIT = "consecutive_failure_limit"
    STALE_DATA = "stale_data"
    RECONCILIATION_AMBIGUITY = "reconciliation_ambiguity"
    RPC_DIVERGENCE = "rpc_divergence"


class AdmissionReason(StrEnum):
    POLICY_DISABLED = "policy_disabled"
    SHADOW_MODE = "shadow_mode"
    HUMAN_REVIEW_MISSING = "human_review_missing"
    OPERATOR_ACK_MISSING = "operator_ack_missing"
    CANARY_NOT_ARMED = "canary_not_armed"
    ARM_EXPIRED = "arm_expired"
    ACTIVE_LATCH = "active_latch"
    OUTSTANDING_SUBMISSION = "outstanding_submission"
    PAIR_NOT_ALLOWLISTED = "pair_not_allowlisted"
    PROGRAM_NOT_ALLOWLISTED = "program_not_allowlisted"
    PROVIDER_NOT_ALLOWLISTED = "provider_not_allowlisted"
    PRINCIPAL_CAP_EXCEEDED = "principal_cap_exceeded"
    WALLET_SPEND_CAP_EXCEEDED = "wallet_spend_cap_exceeded"
    WALLET_RESERVE_BREACH = "wallet_reserve_breach"
    DATA_STALE = "data_stale"
    RPC_DIVERGENCE = "rpc_divergence"
    INVALID_IDENTITY = "invalid_identity"


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CanaryControlError(f"{name} must be an integer >= {minimum}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanaryControlError(f"{name} must be a non-empty string")
    return value.strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    actor_id: str
    kind: ActorKind = ActorKind.HUMAN

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _text(self.actor_id, "actor_id"))

    @property
    def is_human(self) -> bool:
        return self.kind is ActorKind.HUMAN


@dataclass(frozen=True, slots=True)
class CanaryPolicy:
    schema_version: str = SCHEMA_VERSION
    enabled: bool = False
    mode: CanaryMode = CanaryMode.SHADOW
    allowlisted_pairs: tuple[str, ...] = ()
    allowlisted_program_ids: tuple[str, ...] = ()
    allowlisted_providers: tuple[str, ...] = ()
    max_principal_base_units: int = 0
    deployment_principal_ceiling_base_units: int = 0
    max_wallet_spend_lamports: int = 0
    deployment_wallet_spend_ceiling_lamports: int = 0
    minimum_wallet_reserve_lamports: int = 0
    maximum_daily_loss_lamports: int = 0
    maximum_consecutive_failures: int = 0
    maximum_data_age_ms: int = 0
    maximum_rpc_slot_divergence: int = 0
    max_outstanding_submissions: int = 1
    operator_confirmation_ttl_ms: int = 0
    ai_authority: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.ai_authority:
            raise CanaryControlError("unsupported schema or AI authority")
        numeric = (
            "max_principal_base_units",
            "deployment_principal_ceiling_base_units",
            "max_wallet_spend_lamports",
            "deployment_wallet_spend_ceiling_lamports",
            "minimum_wallet_reserve_lamports",
            "maximum_daily_loss_lamports",
            "maximum_consecutive_failures",
            "maximum_data_age_ms",
            "maximum_rpc_slot_divergence",
            "operator_confirmation_ttl_ms",
        )
        for name in numeric:
            _integer(getattr(self, name), name)
        if self.max_outstanding_submissions != 1:
            raise CanaryControlError("exactly one outstanding submission is required")
        for name in (
            "allowlisted_pairs",
            "allowlisted_program_ids",
            "allowlisted_providers",
        ):
            values = tuple(_text(item, name) for item in getattr(self, name))
            if len(values) != len(set(values)):
                raise CanaryControlError(f"{name} contains duplicates")
            object.__setattr__(self, name, values)
        if self.enabled:
            if self.mode is not CanaryMode.LIMITED_LIVE:
                raise CanaryControlError("enabled policy must use limited_live")
            if not all(
                (
                    self.allowlisted_pairs,
                    self.allowlisted_program_ids,
                    self.allowlisted_providers,
                )
            ):
                raise CanaryControlError("enabled policy requires explicit allowlists")
            positive = numeric[:-1] + ("operator_confirmation_ttl_ms",)
            if any(getattr(self, name) <= 0 for name in positive):
                raise CanaryControlError("enabled policy requires positive limits")
            if (
                self.max_principal_base_units
                > self.deployment_principal_ceiling_base_units
            ):
                raise CanaryControlError("principal cap exceeds deployment ceiling")
            if (
                self.max_wallet_spend_lamports
                > self.deployment_wallet_spend_ceiling_lamports
            ):
                raise CanaryControlError("wallet spend cap exceeds deployment ceiling")

    @property
    def policy_hash(self) -> str:
        return sha256_json(self)


@dataclass(frozen=True, slots=True)
class ReviewedShadowEvidence:
    evidence_hash: str
    schema_version: str
    corpus_id: str
    reviewer_id: str
    review_reference: str
    reviewed_at_ms: int


@dataclass(frozen=True, slots=True)
class OperatorAcknowledgement:
    acknowledgement_id: str
    operator_id: str
    policy_hash: str
    evidence_hash: str
    acknowledged_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class ArmingReceipt:
    arming_id: str
    operator_id: str
    policy_hash: str
    evidence_hash: str
    armed_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class CanaryCandidate:
    attempt_id: str
    pair: str
    provider: str
    program_ids: tuple[str, ...]
    principal_base_units: int
    wallet_spend_lamports: int
    plan_hash: str
    message_hash: str
    observed_at_ms: int

    def __post_init__(self) -> None:
        for name in ("attempt_id", "pair", "provider", "plan_hash", "message_hash"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        programs = tuple(_text(item, "program_ids") for item in self.program_ids)
        if not programs or len(programs) != len(set(programs)):
            raise CanaryControlError("program_ids must be non-empty and unique")
        object.__setattr__(self, "program_ids", programs)
        _integer(self.principal_base_units, "principal_base_units", 1)
        _integer(self.wallet_spend_lamports, "wallet_spend_lamports")
        _integer(self.observed_at_ms, "observed_at_ms")
        if len(self.plan_hash) != 64 or len(self.message_hash) != 64:
            raise CanaryControlError("plan and message hashes must be SHA-256")

    @property
    def candidate_hash(self) -> str:
        return sha256_json(self)


@dataclass(frozen=True, slots=True)
class RuntimeSafetySnapshot:
    now_ms: int
    wallet_balance_lamports: int
    daily_realized_pnl_lamports: int
    consecutive_failures: int
    data_observed_at_ms: int
    reconciliation_ambiguous: bool
    rpc_primary_slot: int
    rpc_secondary_slot: int


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    decision_id: str
    allowed: bool
    reasons: tuple[AdmissionReason, ...]
    attempt_id: str
    candidate_hash: str
    policy_hash: str
    evidence_hash: str | None
    evaluated_at_ms: int


@dataclass(frozen=True, slots=True)
class OutstandingSubmission:
    attempt_id: str
    message_hash: str
    candidate_hash: str
    reserved_at_ms: int


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    attempt_id: str
    message_hash: str
    reconciliation_hash: str
    status: ReconciliationStatus
    realized_pnl_lamports: int
    observed_at_ms: int


@dataclass(frozen=True, slots=True)
class CanaryEvent:
    sequence: int
    kind: str
    observed_at_ms: int
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def event_hash(self) -> str:
        return sha256_json(self)


@dataclass(frozen=True, slots=True)
class CanaryReport:
    schema_version: str
    policy_hash: str
    evidence_hash: str | None
    mode: CanaryMode
    armed: bool
    armed_until_ms: int | None
    outstanding_attempt_id: str | None
    active_latches: tuple[LatchCode, ...]
    daily_realized_pnl_lamports: int
    consecutive_failures: int
    event_count: int
    event_digest: str
    ai_authority: bool = False

    @property
    def report_hash(self) -> str:
        return sha256_json(self)

    def to_dict(self) -> dict[str, Any]:
        payload = _jsonable(self)
        payload["report_hash"] = self.report_hash
        return payload
