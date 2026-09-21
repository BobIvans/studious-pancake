"""Shared fail-closed primitives for MEGA8-03.

This module is an offline contract/evidence layer.  It contains no RPC client,
private-key loader, signer, sender, capital mutation, or release promotion path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from src.research.common import (
    OFFLINE_RESEARCH_BOUNDARY,
    require_id,
    require_nonnegative,
    require_positive,
    require_sha256,
    require_text,
    unique_nonempty,
)

PPM = 1_000_000
MEGA8_03_SCHEMA = "mega8-03.offline.v1"


class Mega803Error(ValueError):
    """Malformed, unsupported, stale, or unsafe MEGA8-03 input."""


class OfflineStatus(StrEnum):
    QUALIFIED_OFFLINE = "QUALIFIED_OFFLINE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """Immutable identity/evidence boundary required by every child."""

    evidence_id: str
    evidence_sha256: str
    state_generation: str
    deployment_generation: str
    policy_generation: str
    observed_at_ns: int
    available_at_ns: int
    deployment_verified: bool = True
    semantics_verified: bool = True
    signer_allowed: bool = False
    submission_allowed: bool = False
    live_enabled: bool = False

    def __post_init__(self) -> None:
        require_id(self.evidence_id, "evidence_id")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        for field in (
            "state_generation",
            "deployment_generation",
            "policy_generation",
        ):
            require_id(getattr(self, field), field)
        require_nonnegative(self.observed_at_ns, "observed_at_ns")
        require_nonnegative(self.available_at_ns, "available_at_ns")
        if self.available_at_ns < self.observed_at_ns:
            raise Mega803Error("available_at_ns cannot predate observed_at_ns")
        for field in (
            "deployment_verified",
            "semantics_verified",
            "signer_allowed",
            "submission_allowed",
            "live_enabled",
        ):
            if not isinstance(getattr(self, field), bool):
                raise Mega803Error(f"{field} must be bool")
        if self.signer_allowed or self.submission_allowed or self.live_enabled:
            raise Mega803Error(
                "MEGA8-03 cannot grant signing/submission/live authority"
            )

    @property
    def blockers(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.deployment_verified:
            reasons.append("DEPLOYMENT_UNVERIFIED")
        if not self.semantics_verified:
            reasons.append("UNSUPPORTED_SEMANTICS")
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class OfflineDecision:
    child_id: str
    status: OfflineStatus
    evidence_sha256: str
    reason_codes: tuple[str, ...]
    payload: Mapping[str, Any]
    execution_authority: bool = False
    signing_allowed: bool = False
    submission_allowed: bool = False
    live_enabled: bool = False
    automatic_capital_increase_allowed: bool = False

    def __post_init__(self) -> None:
        require_id(self.child_id, "child_id")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        unique_nonempty(self.reason_codes, "reason_code")
        if (
            self.execution_authority
            or self.signing_allowed
            or self.submission_allowed
            or self.live_enabled
            or self.automatic_capital_increase_allowed
        ):
            raise Mega803Error(
                "offline decision cannot grant execution/capital authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AdvisoryModel:
    model_id: str
    model_kind: str
    parameters: Mapping[str, Any]
    evidence_sha256: str
    calibrated: bool
    holdout_verified: bool
    execution_authority: bool = False

    def __post_init__(self) -> None:
        require_id(self.model_id, "model_id")
        require_id(self.model_kind, "model_kind")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        if self.execution_authority:
            raise Mega803Error("research model cannot own execution authority")


def stable_hash(domain: str, value: Any) -> str:
    require_text(domain, "domain")
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode()
    return hashlib.sha256(domain.encode() + b"\n" + raw).hexdigest()


def decision(
    child_id: str,
    *,
    envelope: EvidenceEnvelope,
    payload: Mapping[str, Any],
    reasons: Iterable[str] = (),
    research_only: bool = False,
) -> OfflineDecision:
    reasons_tuple = tuple(dict.fromkeys((*envelope.blockers, *tuple(reasons))))
    status = (
        OfflineStatus.BLOCKED
        if envelope.blockers
        else (
            OfflineStatus.REJECTED
            if reasons_tuple
            else (
                OfflineStatus.RESEARCH_ONLY
                if research_only
                else OfflineStatus.QUALIFIED_OFFLINE
            )
        )
    )
    evidence = stable_hash(
        f"mega8-03/{child_id}/v1",
        {
            "envelope": asdict(envelope),
            "payload": dict(payload),
            "reasons": reasons_tuple,
            "research_only": research_only,
        },
    )
    return OfflineDecision(
        child_id=child_id,
        status=status,
        evidence_sha256=evidence,
        reason_codes=reasons_tuple,
        payload=dict(payload),
    )


def advisory_model(
    model_id: str,
    model_kind: str,
    parameters: Mapping[str, Any],
    *,
    calibrated: bool,
    holdout_verified: bool,
) -> AdvisoryModel:
    evidence = stable_hash(
        f"mega8-03/model/{model_kind}/v1",
        {
            "model_id": model_id,
            "parameters": dict(parameters),
            "calibrated": calibrated,
            "holdout_verified": holdout_verified,
        },
    )
    return AdvisoryModel(
        model_id=model_id,
        model_kind=model_kind,
        parameters=dict(parameters),
        evidence_sha256=evidence,
        calibrated=calibrated,
        holdout_verified=holdout_verified,
    )


def integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Mega803Error(f"{field} must be integer")
    if minimum is not None and value < minimum:
        raise Mega803Error(f"{field} must be >= {minimum}")
    return value


def ppm(value: Any, field: str) -> int:
    value = integer(value, field, minimum=0)
    if value > PPM:
        raise Mega803Error(f"{field} must be <= {PPM}")
    return value


def ratio_ppm(numerator: int, denominator: int) -> int:
    integer(numerator, "numerator")
    require_positive(denominator, "denominator")
    return numerator * PPM // denominator


def quantile_int(values: Sequence[int], quantile_ppm: int) -> int:
    if not values:
        raise Mega803Error("quantile requires observations")
    q = ppm(quantile_ppm, "quantile_ppm")
    ordered = sorted(integer(v, "value") for v in values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered) / PPM) - 1))
    return ordered[index]


def mean_int(values: Sequence[int]) -> int:
    if not values:
        raise Mega803Error("mean requires observations")
    checked = [integer(v, "value") for v in values]
    return sum(checked) // len(checked)


def bounded_probability_ppm(successes: int, total: int) -> int:
    require_nonnegative(successes, "successes")
    require_positive(total, "total")
    if successes > total:
        raise Mega803Error("successes cannot exceed total")
    return successes * PPM // total


def require_rows(rows: Sequence[Mapping[str, Any]], field: str = "rows") -> None:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise Mega803Error(f"{field} must be a non-empty sequence")
    for row in rows:
        if not isinstance(row, Mapping):
            raise Mega803Error(f"{field} must contain mappings")


def ensure_unique(values: Iterable[str], field: str) -> tuple[str, ...]:
    return unique_nonempty(tuple(values), field)


def require_offline_boundary() -> None:
    boundary = OFFLINE_RESEARCH_BOUNDARY
    if boundary.signing or boundary.submission or boundary.live_trading:
        raise Mega803Error("canonical research boundary unexpectedly permits effects")


__all__ = [
    "AdvisoryModel",
    "EvidenceEnvelope",
    "MEGA8_03_SCHEMA",
    "Mega803Error",
    "OfflineDecision",
    "OfflineStatus",
    "PPM",
    "advisory_model",
    "bounded_probability_ppm",
    "decision",
    "ensure_unique",
    "integer",
    "mean_int",
    "ppm",
    "quantile_int",
    "ratio_ppm",
    "require_offline_boundary",
    "require_rows",
    "stable_hash",
]
