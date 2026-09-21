"""Shared deterministic primitives for missing MEGA8-08 PR-287..302 owners."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


class Mega808Error(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Mega808Error(f"{field.upper()}_INTEGER_REQUIRED")
    return value


def require_nonnegative(value: int, field: str) -> int:
    value = require_int(value, field)
    if value < 0:
        raise Mega808Error(f"{field.upper()}_NEGATIVE")
    return value


def require_positive(value: int, field: str) -> int:
    value = require_int(value, field)
    if value <= 0:
        raise Mega808Error(f"{field.upper()}_POSITIVE_REQUIRED")
    return value


def stable_hash(domain: str, value: Any) -> str:
    encoded = json.dumps(
        {"domain": domain, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Result:
    contract: str
    payload: Mapping[str, Any]
    status: str = "OK"
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"OK", "BLOCKED", "INCOMPLETE", "UNKNOWN", "DEFERRED"}:
            raise Mega808Error("INVALID_STATUS")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "blockers", tuple(dict.fromkeys(self.blockers)))


def result(
    contract: str,
    payload: Mapping[str, Any],
    *,
    status: str = "OK",
    blockers: tuple[str, ...] = (),
) -> Result:
    forbidden = ("private_key", "signer", "submission", "send", "live_enabled")
    for key in forbidden:
        if bool(payload.get(key)):
            raise Mega808Error("EFFECT_AUTHORITY_FORBIDDEN")
    if blockers and status == "OK":
        status = "BLOCKED"
    return Result(contract, payload, status, blockers)


__all__ = [
    "Mega808Error",
    "Result",
    "require_int",
    "require_nonnegative",
    "require_positive",
    "result",
    "stable_hash",
]
