"""PR-285 / TERM-01: maturity-aware term-structure research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .core import Mega807Error, require_nonnegative, require_positive, stable_hash


@dataclass(frozen=True, slots=True)
class FixedRateInstrument:
    instrument_id: str
    asset_id: str
    maturity: int
    principal: int
    redemption: int
    available_at: int


def build_term_structure_curve(
    instruments: Sequence[FixedRateInstrument], *, cutoff: int
) -> tuple[tuple[int, int], ...]:
    rows = [item for item in instruments if item.available_at <= cutoff]
    if not rows:
        raise Mega807Error("TERM_CURVE_EMPTY")
    curve: list[tuple[int, int]] = []
    for item in sorted(rows, key=lambda row: row.maturity):
        require_positive(item.principal, "principal")
        require_positive(item.redemption, "redemption")
        rate_ppm = (item.redemption - item.principal) * 1_000_000 // item.principal
        curve.append((item.maturity, rate_ppm))
    return tuple(curve)


def normalize_fixed_rate_instruments(
    instruments: Sequence[FixedRateInstrument],
) -> tuple[FixedRateInstrument, ...]:
    seen: set[str] = set()
    rows: list[FixedRateInstrument] = []
    for item in sorted(
        instruments, key=lambda row: (row.asset_id, row.maturity, row.instrument_id)
    ):
        if item.instrument_id in seen:
            raise Mega807Error("DUPLICATE_FIXED_RATE_INSTRUMENT")
        seen.add(item.instrument_id)
        rows.append(item)
    return tuple(rows)


def detect_term_basis(left: FixedRateInstrument, right: FixedRateInstrument) -> int:
    if left.asset_id != right.asset_id or left.maturity != right.maturity:
        raise Mega807Error("TERM_BASIS_REQUIRES_MATCHED_ASSET_AND_MATURITY")
    left_rate = (left.redemption - left.principal) * 1_000_000 // left.principal
    right_rate = (right.redemption - right.principal) * 1_000_000 // right.principal
    return left_rate - right_rate


def qualify_term_structure_trade(
    *, basis_ppm: int, minimum_basis_ppm: int, atomic: bool
) -> dict[str, int | bool | str]:
    magnitude = abs(basis_ppm)
    if magnitude < require_nonnegative(minimum_basis_ppm, "minimum_basis_ppm"):
        raise Mega807Error("TERM_BASIS_BELOW_THRESHOLD")
    return {
        "basis_ppm": basis_ppm,
        "atomic": atomic,
        "verdict": "PARITY_RESEARCH" if atomic else "CARRY_RESEARCH",
        "live_authority": False,
        "qualification_sha256": stable_hash(
            "mega8-07-term-qualification",
            {"basis_ppm": basis_ppm, "atomic": atomic},
        ),
    }
