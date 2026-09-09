"""Bounded integer-only optimizer for stable-peg candidates."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from .models import StablePegError, strict_int

@dataclass(frozen=True, slots=True)
class SizeResult:
    principal: int
    conservative_surplus: int
    iterations: int
    no_trade: bool


def bounded_best_size(*, max_principal: int, evaluate: Callable[[int], int], max_iterations: int = 64) -> SizeResult:
    """Bounded coarse-to-fine search; evaluate returns conservative surplus or negative loss."""
    strict_int(max_principal, field="max_principal", minimum=1)
    strict_int(max_iterations, field="max_iterations", minimum=1, maximum=4096)
    candidates: set[int] = {1, max_principal}
    p = 1
    while p < max_principal and len(candidates) < max_iterations // 2:
        candidates.add(p)
        p = min(max_principal, p * 2)
    ordered = sorted(candidates)
    best_p = 0
    best_surplus = 0
    iterations = 0
    for principal in ordered:
        if iterations >= max_iterations:
            break
        value = evaluate(principal)
        if type(value) is not int:
            raise StablePegError("evaluate must return non-bool integer")
        iterations += 1
        if value > best_surplus:
            best_p, best_surplus = principal, value
    if best_p and iterations < max_iterations:
        lo = max(1, best_p // 2)
        hi = min(max_principal, best_p * 2)
        remaining = max_iterations - iterations
        step = max(1, (hi - lo) // max(1, remaining))
        for principal in range(lo, hi + 1, step):
            if iterations >= max_iterations:
                break
            value = evaluate(principal)
            if type(value) is not int:
                raise StablePegError("evaluate must return non-bool integer")
            iterations += 1
            if value > best_surplus:
                best_p, best_surplus = principal, value
    return SizeResult(best_p, best_surplus, iterations, best_p == 0)
