"""Shared fail-closed primitives for ULTIMATE-MEGA1 PR-303..326.

This module is intentionally sender-free.  It provides exact integer helpers,
stable evidence hashing and immutable contract records; it does not open network
connections, load keys, sign, submit, mutate capital or grant live authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


class UltimateMegaError(ValueError):
    """Typed fail-closed contract violation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UltimateMegaError(f"{field.upper()}_REQUIRED")
    return value.strip()


def require_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UltimateMegaError(f"{field.upper()}_INTEGER_REQUIRED")
    return value


def require_nonnegative(value: int, field: str) -> int:
    value = require_int(value, field)
    if value < 0:
        raise UltimateMegaError(f"{field.upper()}_NEGATIVE")
    return value


def require_positive(value: int, field: str) -> int:
    value = require_int(value, field)
    if value <= 0:
        raise UltimateMegaError(f"{field.upper()}_POSITIVE_REQUIRED")
    return value


def require_ppm(value: int, field: str) -> int:
    value = require_nonnegative(value, field)
    if value > 1_000_000:
        raise UltimateMegaError(f"{field.upper()}_PPM_OUT_OF_RANGE")
    return value


def ceil_div(numerator: int, denominator: int) -> int:
    numerator = require_nonnegative(numerator, "numerator")
    denominator = require_positive(denominator, "denominator")
    return (numerator + denominator - 1) // denominator


def ppm_fee_ceil(amount: int, fee_ppm: int) -> int:
    amount = require_nonnegative(amount, "amount")
    fee_ppm = require_ppm(fee_ppm, "fee_ppm")
    return ceil_div(amount * fee_ppm, 1_000_000)


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonicalize(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_canonicalize(item) for item in sorted(value, key=repr)]
    if isinstance(value, float):
        if not isfinite(value):
            raise UltimateMegaError("NON_FINITE_VALUE")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise UltimateMegaError("UNSUPPORTED_EVIDENCE_VALUE")


def stable_hash(domain: str, value: Any) -> str:
    require_id(domain, "domain")
    encoded = json.dumps(
        {"domain": domain, "value": _canonicalize(value)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_FORBIDDEN_EFFECT_KEYS = {
    "private_key",
    "secret_key",
    "signer",
    "signing",
    "send",
    "submit",
    "submission",
    "live",
    "live_enabled",
    "mainnet_send",
    "paid_overage",
    "automatic_promotion",
    "automatic_capital_increase",
}


def reject_effect_authority(payload: Mapping[str, Any]) -> None:
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_EFFECT_KEYS and bool(value):
            raise UltimateMegaError("EFFECT_AUTHORITY_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class ContractResult:
    contract: str
    status: str
    payload: Mapping[str, Any]
    evidence_hash: str
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.contract, "contract")
        if self.status not in {"OK", "BLOCKED", "UNKNOWN", "INCOMPLETE"}:
            raise UltimateMegaError("INVALID_CONTRACT_STATUS")
        object.__setattr__(
            self, "payload", MappingProxyType(dict(_canonicalize(self.payload)))
        )
        object.__setattr__(self, "blockers", tuple(dict.fromkeys(self.blockers)))


def record(
    contract: str,
    payload: Mapping[str, Any],
    *,
    status: str = "OK",
    blockers: Sequence[str] = (),
) -> ContractResult:
    reject_effect_authority(payload)
    normalized = _canonicalize(payload)
    blocker_tuple = tuple(dict.fromkeys(str(x) for x in blockers if str(x)))
    if blocker_tuple and status == "OK":
        status = "BLOCKED"
    return ContractResult(
        contract=require_id(contract, "contract"),
        status=status,
        payload=normalized,
        blockers=blocker_tuple,
        evidence_hash=stable_hash(
            f"ultimate-mega1:{contract}",
            {"status": status, "payload": normalized, "blockers": blocker_tuple},
        ),
    )


def require_keys(mapping: Mapping[str, Any], keys: Iterable[str], code: str) -> None:
    missing = [key for key in keys if key not in mapping or mapping[key] is None]
    if missing:
        raise UltimateMegaError(code)


def require_same_identity(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    fields: Sequence[str],
    *,
    code: str,
) -> None:
    for field in fields:
        if left.get(field) != right.get(field):
            raise UltimateMegaError(code)


def require_unique(values: Sequence[str], code: str) -> tuple[str, ...]:
    normalized = tuple(require_id(value, "value") for value in values)
    if len(set(normalized)) != len(normalized):
        raise UltimateMegaError(code)
    return normalized


def exact_weighted_fraction(
    weighted_success: Sequence[tuple[int, int]],
) -> tuple[int, int]:
    numerator = 0
    denominator = 0
    for weight, success in weighted_success:
        weight = require_positive(weight, "weight")
        if success not in {0, 1}:
            raise UltimateMegaError("BINARY_LABEL_REQUIRED")
        numerator += weight * success
        denominator += weight
    if denominator == 0:
        raise UltimateMegaError("EMPTY_WEIGHTED_SAMPLE")
    return numerator, denominator


__all__ = [
    "ContractResult",
    "UltimateMegaError",
    "ceil_div",
    "exact_weighted_fraction",
    "ppm_fee_ceil",
    "record",
    "reject_effect_authority",
    "require_id",
    "require_int",
    "require_keys",
    "require_nonnegative",
    "require_positive",
    "require_ppm",
    "require_same_identity",
    "require_unique",
    "stable_hash",
]
