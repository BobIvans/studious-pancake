"""MEGA8-06 shared deterministic offline contracts.

This package consumes captured observations and immutable evidence only.  It has
no network, signer, submission, wallet, or capital-mutation capability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Iterable, Mapping, Sequence


class Mega806Error(ValueError):
    """Fail-closed MEGA8-06 contract violation."""


class Disposition(StrEnum):
    IMPLEMENTED_OFFLINE = "implemented-offline"
    RESEARCH_ONLY = "research-only"
    BLOCKED = "blocked"
    REJECTED = "rejected"


def stable_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Mega806Error(f"{field} is required")
    return value


def require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Mega806Error(f"{field} must be integer")
    return value


def require_nonnegative_int(value: object, field: str) -> int:
    value = require_int(value, field)
    if value < 0:
        raise Mega806Error(f"{field} must be non-negative")
    return value


def require_positive_int(value: object, field: str) -> int:
    value = require_nonnegative_int(value, field)
    if value == 0:
        raise Mega806Error(f"{field} must be positive")
    return value


def require_ppm(value: object, field: str) -> int:
    value = require_nonnegative_int(value, field)
    if value > 1_000_000:
        raise Mega806Error(f"{field} exceeds 1e6 ppm")
    return value


def mean_int(values: Sequence[int]) -> int:
    if not values:
        raise Mega806Error("values are required")
    checked = [require_int(v, "value") for v in values]
    return sum(checked) // len(checked)


def quantile(values: Sequence[int], ppm: int) -> int:
    if not values:
        raise Mega806Error("values are required")
    ppm = require_ppm(ppm, "ppm")
    checked = sorted(require_int(v, "value") for v in values)
    index = (len(checked) - 1) * ppm // 1_000_000
    return checked[index]


def cvar_upper(values: Sequence[int], tail_ppm: int) -> int:
    if not values:
        raise Mega806Error("values are required")
    tail_ppm = require_ppm(tail_ppm, "tail_ppm")
    if tail_ppm == 0:
        raise Mega806Error("tail_ppm must be positive")
    checked = sorted(require_nonnegative_int(v, "loss") for v in values)
    cutoff = quantile(checked, 1_000_000 - tail_ppm)
    tail = [v for v in checked if v >= cutoff]
    return mean_int(tail)


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    generation: str
    state_sha256: str
    observed_at: int
    expires_at: int
    verified: bool = True

    def __post_init__(self) -> None:
        require_text(self.generation, "generation")
        if (
            not isinstance(self.state_sha256, str)
            or len(self.state_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.state_sha256)
        ):
            raise Mega806Error("state_sha256 must be lowercase sha256")
        require_nonnegative_int(self.observed_at, "observed_at")
        require_positive_int(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise Mega806Error("expires_at must be after observed_at")
        if not isinstance(self.verified, bool):
            raise Mega806Error("verified must be bool")

    def assert_usable(self, *, now: int) -> None:
        require_nonnegative_int(now, "now")
        if not self.verified:
            raise Mega806Error("UNVERIFIED_EVIDENCE")
        if now >= self.expires_at:
            raise Mega806Error("STALE_EVIDENCE")

    @property
    def identity(self) -> str:
        return stable_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class ResearchResult:
    operation: str
    evidence_id: str
    payload_sha256: str
    disposition: Disposition
    reason: str
    live_enabled: bool = False
    signing_enabled: bool = False
    submission_enabled: bool = False
    automatic_capital_increase: bool = False

    def __post_init__(self) -> None:
        require_text(self.operation, "operation")
        require_text(self.evidence_id, "evidence_id")
        require_text(self.payload_sha256, "payload_sha256")
        require_text(self.reason, "reason")
        if (
            self.live_enabled
            or self.signing_enabled
            or self.submission_enabled
            or self.automatic_capital_increase
        ):
            raise Mega806Error("MEGA8-06 cannot grant effect authority")


def offline_result(
    operation: str,
    evidence: EvidenceBinding,
    payload: object,
    *,
    now: int,
    disposition: Disposition = Disposition.IMPLEMENTED_OFFLINE,
    reason: str = "OFFLINE_CONTRACT_SATISFIED",
) -> ResearchResult:
    evidence.assert_usable(now=now)
    return ResearchResult(
        operation=operation,
        evidence_id=evidence.identity,
        payload_sha256=stable_hash(payload),
        disposition=disposition,
        reason=reason,
    )


def normalize_weighted_rows(
    rows: Iterable[tuple[str, int]], *, field: str = "weight"
) -> tuple[tuple[str, int], ...]:
    materialized: list[tuple[str, int]] = []
    for name, weight in rows:
        materialized.append(
            (require_text(name, "name"), require_nonnegative_int(weight, field))
        )
    return tuple(sorted(materialized))


def require_same_generation(rows: Sequence[Mapping[str, object]]) -> str:
    if not rows:
        raise Mega806Error("rows are required")
    generations = {require_text(row.get("generation"), "generation") for row in rows}
    if len(generations) != 1:
        raise Mega806Error("GENERATION_MISMATCH")
    return next(iter(generations))


def bounded_ratio_ppm(numerator: int, denominator: int) -> int:
    numerator = require_nonnegative_int(numerator, "numerator")
    denominator = require_positive_int(denominator, "denominator")
    return min(1_000_000, numerator * 1_000_000 // denominator)
