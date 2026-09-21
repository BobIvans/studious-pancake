"""PR-174 / CAPITAL-03: multi-lender shared-capacity planner."""
from __future__ import annotations
from typing import Mapping, Sequence
from .core import CapacityQuote, Mega802Error, allocate_capacity_core


def enumerate_lender_variants(
    quotes: Sequence[CapacityQuote],
) -> tuple[CapacityQuote, ...]:
    return tuple(
        sorted(quotes, key=lambda item: (item.asset_id, item.fee, item.source_id))
    )


def model_shared_lender_liquidity(
    quotes: Sequence[CapacityQuote], shared_caps: Mapping[str, int]
) -> tuple[CapacityQuote, ...]:
    result: list[CapacityQuote] = []
    consumed: dict[str, int] = {}
    for quote in enumerate_lender_variants(quotes):
        group = quote.asset_id
        cap = shared_caps.get(group, quote.capacity)
        remaining = max(0, cap - consumed.get(group, 0))
        bounded = min(quote.capacity, remaining)
        consumed[group] = consumed.get(group, 0) + bounded
        result.append(
            CapacityQuote(
                quote.source_id, quote.asset_id, bounded, quote.fee,
                quote.generation, quote.atomic,
            )
        )
    return tuple(result)


def allocate_borrow_across_lenders(
    quotes: Sequence[CapacityQuote], *, amount: int
) -> tuple[tuple[str, int], ...]:
    return allocate_capacity_core(quotes, amount=amount)


def select_atomic_financing_variant(
    quotes: Sequence[CapacityQuote], *, amount: int, max_total_fee: int
) -> tuple[tuple[str, int], ...]:
    atomic = [quote for quote in quotes if quote.atomic]
    if not atomic:
        raise Mega802Error("NO_ATOMIC_FINANCING")
    return allocate_capacity_core(
        atomic, amount=amount, max_total_fee=max_total_fee
    )
