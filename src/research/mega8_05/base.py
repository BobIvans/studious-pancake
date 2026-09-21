"""Shared fail-closed primitives for MEGA8-05 research modules.

This package is deliberately signer-free and side-effect free.  It consumes
already captured metadata/data and emits deterministic research artifacts.  It
does not perform network access, install discovered code, sign, submit, fund,
or mutate remote state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import sqrt
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from src.research.common import hash_json, require_id, require_text


class Disposition(StrEnum):
    PASS = "pass"
    REJECT = "reject"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResearchArtifact:
    kind: str
    identity: str
    payload: Mapping[str, Any]
    disposition: Disposition
    reason: str
    signer_allowed: bool = False
    submission_allowed: bool = False
    live_allowed: bool = False

    def __post_init__(self) -> None:
        require_id(self.kind, "kind")
        require_id(self.identity, "identity")
        require_text(self.reason, "reason")
        if self.signer_allowed or self.submission_allowed or self.live_allowed:
            raise ValueError(
                "MEGA8-05 research artifacts cannot grant execution authority"
            )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _deep_freeze(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_deep_freeze(item) for item in value), key=repr))
    return value


def artifact(
    kind: str,
    payload: Mapping[str, Any],
    *,
    disposition: Disposition = Disposition.PASS,
    reason: str = "offline-research",
) -> ResearchArtifact:
    identity = hash_json(f"mega8-05/{kind}/v1", payload)
    return ResearchArtifact(
        kind=kind,
        identity=identity,
        payload=_deep_freeze(payload),
        disposition=disposition,
        reason=reason,
    )


def nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be finite")
    return result


def probability(value: Any, field: str) -> float:
    result = finite_number(value, field)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be in [0, 1]")
    return result


def require_same_length(*series: Sequence[Any]) -> int:
    if not series:
        raise ValueError("at least one series is required")
    length = len(series[0])
    if length == 0 or any(len(values) != length for values in series):
        raise ValueError("series must be non-empty and have equal length")
    return length


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    return sum(values) / len(values)


def variance(values: Sequence[float], *, sample: bool = True) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    if sample and len(values) < 2:
        return 0.0
    center = mean(values)
    denom = len(values) - 1 if sample else len(values)
    return sum((value - center) ** 2 for value in values) / denom


def covariance(left: Sequence[float], right: Sequence[float]) -> float:
    length = require_same_length(left, right)
    if length < 2:
        return 0.0
    left_mean = mean(left)
    right_mean = mean(right)
    return sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)
    ) / (length - 1)


def correlation(left: Sequence[float], right: Sequence[float]) -> float:
    require_same_length(left, right)
    left_var = variance(left)
    right_var = variance(right)
    if left_var <= 0.0 or right_var <= 0.0:
        return 0.0
    return covariance(left, right) / sqrt(left_var * right_var)


def unique_text(values: Iterable[str], field: str) -> tuple[str, ...]:
    normalized = tuple(nonempty_text(value, field) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} contains duplicates")
    return normalized


def frozen_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(value)}


__all__ = [
    "Disposition",
    "ResearchArtifact",
    "artifact",
    "correlation",
    "covariance",
    "finite_number",
    "frozen_mapping",
    "mean",
    "nonempty_text",
    "probability",
    "require_same_length",
    "unique_text",
    "variance",
]
