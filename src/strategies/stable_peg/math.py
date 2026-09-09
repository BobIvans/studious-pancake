"""Integer-only CLMM/DLMM helpers used by the MPR-2622 qualification vertical."""
from __future__ import annotations
from dataclasses import dataclass
from .models import StablePegError, strict_int

FEE_DENOMINATOR = 1_000_000


def ceil_div(n: int, d: int) -> int:
    strict_int(n, field="n")
    strict_int(d, field="d", minimum=1)
    return (n + d - 1) // d


def fee_against_strategy(amount: int, fee_numerator: int, fee_denominator: int = FEE_DENOMINATOR) -> int:
    strict_int(amount, field="amount")
    strict_int(fee_numerator, field="fee_numerator")
    strict_int(fee_denominator, field="fee_denominator", minimum=1)
    return ceil_div(amount * fee_numerator, fee_denominator)

@dataclass(frozen=True, slots=True)
class LiquidityBand:
    capacity_in: int
    numerator: int
    denominator: int
    digest: str

    def __post_init__(self) -> None:
        strict_int(self.capacity_in, field="capacity_in", minimum=1)
        strict_int(self.numerator, field="numerator", minimum=1)
        strict_int(self.denominator, field="denominator", minimum=1)
        if not self.digest:
            raise StablePegError("band digest required")


def traverse_bands_exact(amount_in: int, bands: tuple[LiquidityBand, ...], *, fee_numerator: int = 0, fee_denominator: int = FEE_DENOMINATOR) -> tuple[int, int, tuple[str, ...]]:
    """Conservative exact-input traversal over already-decoded CLMM ticks/DLMM bins."""
    strict_int(amount_in, field="amount_in", minimum=1)
    if not bands:
        raise StablePegError("no liquidity bands")
    fee = fee_against_strategy(amount_in, fee_numerator, fee_denominator)
    remaining = amount_in - fee
    if remaining <= 0:
        return 0, fee, ()
    output = 0
    used: list[str] = []
    for band in bands:
        if remaining <= 0:
            break
        take = min(remaining, band.capacity_in)
        output += (take * band.numerator) // band.denominator
        remaining -= take
        used.append(band.digest)
    if remaining:
        raise StablePegError("insufficient decoded tick/bin coverage")
    return output, fee, tuple(used)
