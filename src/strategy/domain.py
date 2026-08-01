"""Canonical, deeply immutable, content-addressed opportunity contract."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Mapping

from src.runtime.trusted_time import SystemTrustedTime, TrustedTime

_MAX_ATOMS = 2**63 - 1


def _freeze(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("metadata floats must be finite")
        return value
    if type(value) is dict:
        return MappingProxyType(
            {
                str(k): _freeze(v)
                for k, v in sorted(value.items(), key=lambda x: str(x[0]))
            }
        )
    if type(value) in (list, tuple):
        return tuple(_freeze(v) for v in value)
    raise TypeError(f"unsupported mutable metadata type: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _atoms(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be integer base units")
    if value < (1 if positive else -_MAX_ATOMS) or value > _MAX_ATOMS:
        raise ValueError(f"{name} outside supported atomic range")
    return value


def _timestamp(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True, slots=True, init=False)
class Opportunity:
    strategy_name: str
    opportunity_type: str
    detected_at: float
    detection_slot: int
    input_mint: str
    output_mint: str
    proposed_amount_base_units: int
    expected_gross_profit: int
    expires_at: float
    metadata: Mapping[str, Any] = field(default_factory=dict)
    opportunity_id: str = ""

    def __init__(
        self,
        *,
        strategy_name: str,
        opportunity_type: str,
        detected_at: float,
        detection_slot: int,
        input_mint: str,
        output_mint: str,
        proposed_amount_base_units: int,
        expected_gross_profit: int,
        expires_at: float,
        metadata: Mapping[str, Any] | None = None,
        opportunity_id: str | None = None,
    ) -> None:
        detected, expires = _timestamp(detected_at, "detected_at"), _timestamp(
            expires_at, "expires_at"
        )
        if expires <= detected:
            raise ValueError("opportunity expiration must be after detection timestamp")
        if (
            isinstance(detection_slot, bool)
            or not isinstance(detection_slot, int)
            or detection_slot < 0
        ):
            raise ValueError("detection_slot must be a non-negative integer")
        amount = _atoms(
            proposed_amount_base_units, "proposed_amount_base_units", positive=True
        )
        profit = _atoms(expected_gross_profit, "expected_gross_profit")
        if (
            not strategy_name.strip()
            or not opportunity_type.strip()
            or not input_mint.strip()
            or not output_mint.strip()
        ):
            raise ValueError("opportunity identities are required")
        frozen = _freeze(dict(metadata or {}))
        payload = {
            "schema_version": 2,
            "strategy": strategy_name,
            "type": opportunity_type,
            "slot": detection_slot,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "amount": amount,
            "gross_profit": profit,
            "detected_at": detected,
            "expires_at": expires,
            "metadata": _plain(frozen),
        }
        digest = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        object.__setattr__(self, "strategy_name", strategy_name)
        object.__setattr__(self, "opportunity_type", opportunity_type)
        object.__setattr__(self, "detected_at", detected)
        object.__setattr__(self, "detection_slot", detection_slot)
        object.__setattr__(self, "input_mint", input_mint)
        object.__setattr__(self, "output_mint", output_mint)
        object.__setattr__(self, "proposed_amount_base_units", amount)
        object.__setattr__(self, "expected_gross_profit", profit)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "metadata", frozen)
        object.__setattr__(self, "opportunity_id", opportunity_id or digest)

    @classmethod
    def create(
        cls,
        *,
        strategy_name: str,
        opportunity_type: str,
        detection_slot: int,
        input_mint: str,
        output_mint: str,
        proposed_amount_base_units: int,
        expected_gross_profit: int,
        ttl_seconds: int | float | None = None,
        ttl_ms: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        detected_at: float | None = None,
        clock: TrustedTime | None = None,
    ) -> "Opportunity":
        if (ttl_seconds is None) == (ttl_ms is None):
            raise ValueError("exactly one of ttl_seconds or ttl_ms is required")
        if ttl_ms is not None:
            if (
                isinstance(ttl_ms, bool)
                or not isinstance(ttl_ms, int)
                or not 0 < ttl_ms <= 86_400_000
            ):
                raise ValueError("ttl_ms must be an integer in 1..86400000")
            ttl = ttl_ms / 1000
        else:
            if (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(ttl_seconds)
                or not 0 < ttl_seconds <= 86_400
            ):
                raise ValueError("ttl_seconds must be finite and in (0, 86400]")
            ttl = float(ttl_seconds)
        now = (
            (clock or SystemTrustedTime()).snapshot().utc.timestamp()
            if detected_at is None
            else detected_at
        )
        return cls(
            strategy_name=strategy_name,
            opportunity_type=opportunity_type,
            detected_at=now,
            detection_slot=detection_slot,
            input_mint=input_mint,
            output_mint=output_mint,
            proposed_amount_base_units=proposed_amount_base_units,
            expected_gross_profit=expected_gross_profit,
            expires_at=float(now) + ttl,
            metadata=metadata,
        )
