"""Canonical immutable opportunity domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4
import time


@dataclass(frozen=True, slots=True, init=False)
class Opportunity:
    """A strategy-neutral opportunity detected before execution approval."""

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
    opportunity_id: str = field(default_factory=lambda: uuid4().hex)

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
        expected_gross_profit: int | float,
        expires_at: float,
        metadata: Mapping[str, Any] | None = None,
        opportunity_id: str | None = None,
    ) -> None:
        if expires_at <= detected_at:
            raise ValueError("opportunity expiration must be after detection timestamp")
        if proposed_amount_base_units <= 0:
            raise ValueError("proposed_amount_base_units must be positive")

        object.__setattr__(self, "strategy_name", strategy_name)
        object.__setattr__(self, "opportunity_type", opportunity_type)
        object.__setattr__(self, "detected_at", detected_at)
        object.__setattr__(self, "detection_slot", detection_slot)
        object.__setattr__(self, "input_mint", input_mint)
        object.__setattr__(self, "output_mint", output_mint)
        object.__setattr__(
            self,
            "proposed_amount_base_units",
            proposed_amount_base_units,
        )
        object.__setattr__(
            self,
            "expected_gross_profit",
            _coerce_base_units(expected_gross_profit, "expected_gross_profit"),
        )
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "metadata", MappingProxyType(dict(metadata or {})))
        object.__setattr__(self, "opportunity_id", opportunity_id or uuid4().hex)

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
        expected_gross_profit: int | float,
        ttl_seconds: float,
        metadata: Mapping[str, Any] | None = None,
        detected_at: float | None = None,
    ) -> "Opportunity":
        now = time.time() if detected_at is None else detected_at
        return cls(
            strategy_name=strategy_name,
            opportunity_type=opportunity_type,
            detected_at=now,
            detection_slot=detection_slot,
            input_mint=input_mint,
            output_mint=output_mint,
            proposed_amount_base_units=proposed_amount_base_units,
            expected_gross_profit=expected_gross_profit,
            expires_at=now + ttl_seconds,
            metadata=metadata or {},
        )


def _coerce_base_units(value: int | float, field_name: str) -> int:
    """Return integer base units while tolerating legacy integral fixtures."""

    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be integer base units")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    raise TypeError(f"{field_name} must be integer base units")
