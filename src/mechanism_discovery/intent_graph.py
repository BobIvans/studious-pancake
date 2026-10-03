"""RND-04 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

attest_intent_resolver = make_research_function("attest_intent_resolver", "RND-04")
resolve_order_requirements = make_research_function(
    "resolve_order_requirements", "RND-04"
)
compile_intent_dependency_graph = make_research_function(
    "compile_intent_dependency_graph", "RND-04"
)
normalize_intent_deadlines_and_finality = make_research_function(
    "normalize_intent_deadlines_and_finality", "RND-04"
)
compare_solver_quotes_same_intent = make_research_function(
    "compare_solver_quotes_same_intent", "RND-04"
)
estimate_solver_inventory_shadow_cost = make_research_function(
    "estimate_solver_inventory_shadow_cost", "RND-04"
)
detect_intent_settlement_basis = make_research_function(
    "detect_intent_settlement_basis", "RND-04"
)
qualify_intent_dialect = make_research_function("qualify_intent_dialect", "RND-04")

__all__ = [
    "attest_intent_resolver",
    "resolve_order_requirements",
    "compile_intent_dependency_graph",
    "normalize_intent_deadlines_and_finality",
    "compare_solver_quotes_same_intent",
    "estimate_solver_inventory_shadow_cost",
    "detect_intent_settlement_basis",
    "qualify_intent_dialect",
]


from dataclasses import dataclass
from typing import Any
from src.mechanism_discovery.evidence_native_core import (
    require_int,
    require_text,
    EvidenceNativeError,
)
from src.research.pr356_allocation import solve_opportunity_portfolio


@dataclass(frozen=True, slots=True)
class ClearingIntent:
    intent_id: str
    sell_asset: str
    buy_asset: str
    max_sell_atoms: int
    minimum_buy_atoms: int
    available_at_ns: int
    expires_at_ns: int
    canceled_at_ns: int | None = None
    domain: str = "offline"
    access_id: str = "public"

    def __post_init__(self):
        for field in ("intent_id", "sell_asset", "buy_asset", "domain", "access_id"):
            require_text(getattr(self, field), field)
        for field in ("max_sell_atoms", "minimum_buy_atoms"):
            require_int(getattr(self, field), field, minimum=1)
        require_int(self.available_at_ns, "available_at_ns", minimum=0)
        require_int(self.expires_at_ns, "expires_at_ns", minimum=1)
        if self.canceled_at_ns is not None:
            require_int(
                self.canceled_at_ns, "canceled_at_ns", minimum=self.available_at_ns
            )
        if (
            self.sell_asset == self.buy_asset
            or self.expires_at_ns <= self.available_at_ns
        ):
            raise EvidenceNativeError("CLEARING_INTENT_INVALID")


@dataclass(frozen=True, slots=True)
class ClearingFill:
    left_intent_id: str
    right_intent_id: str
    left_sell_atoms: int
    right_sell_atoms: int


@dataclass(frozen=True, slots=True)
class ClearingResult:
    fills: tuple[ClearingFill, ...]
    remaining_sell_atoms: tuple[tuple[str, int], ...]
    matched_intent_count: int
    finite_candidate_count: int
    execution_right: bool = False


def clear_intents(
    intents: tuple[ClearingIntent, ...],
    *,
    now_ns: int,
    lot_sizes: tuple[tuple[str, int], ...],
    max_candidates: int = 18,
) -> ClearingResult:
    """Finite opposing-order netting via the existing PR356 exact allocator.

    Enumerates registered integer lots, verifies each user's proportional limit,
    and conserves each asset within each match. This is not a general continuous
    clearing optimum, DEX route solver, or authority to settle user orders.
    """
    require_int(now_ns, "now_ns", minimum=0)
    require_int(max_candidates, "max_candidates", minimum=1)
    if max_candidates > 18 or len(intents) > 10:
        raise EvidenceNativeError("CLEARING_BOUND_EXCEEDED")
    if len({row.intent_id for row in intents}) != len(intents):
        raise EvidenceNativeError("CLEARING_DUPLICATE_INTENT")
    if len(dict(lot_sizes)) != len(lot_sizes):
        raise EvidenceNativeError("CLEARING_DUPLICATE_LOT")
    lots = {
        require_text(asset, "asset"): require_int(size, "lot", minimum=1)
        for asset, size in lot_sizes
    }
    if any(row.max_sell_atoms // lots.get(row.sell_asset, 1) > 4096 for row in intents):
        raise EvidenceNativeError("CLEARING_LOT_ENUMERATION_BOUND_EXCEEDED")
    active = sorted(
        (
            r
            for r in intents
            if r.available_at_ns <= now_ns < r.expires_at_ns
            and (r.canceled_at_ns is None or now_ns < r.canceled_at_ns)
        ),
        key=lambda r: r.intent_id,
    )
    candidates: list[dict[str, Any]] = []
    fills = {}
    for i, left in enumerate(active):
        for right in active[i + 1 :]:
            if (left.sell_asset, left.buy_asset, left.domain, left.access_id) != (
                right.buy_asset,
                right.sell_asset,
                right.domain,
                right.access_id,
            ):
                continue
            if left.sell_asset not in lots or right.sell_asset not in lots:
                raise EvidenceNativeError("CLEARING_LOT_MISSING")
            for lq in range(
                lots[left.sell_asset], left.max_sell_atoms + 1, lots[left.sell_asset]
            ):
                lower = (
                    left.minimum_buy_atoms * lq + left.max_sell_atoms - 1
                ) // left.max_sell_atoms
                upper = min(
                    right.max_sell_atoms,
                    right.max_sell_atoms * lq // right.minimum_buy_atoms,
                )
                rq = (
                    (lower + lots[right.sell_asset] - 1) // lots[right.sell_asset]
                ) * lots[right.sell_asset]
                if rq > upper:
                    continue
                if len(candidates) >= max_candidates:
                    raise EvidenceNativeError(
                        "CLEARING_FINITE_CANDIDATE_BOUND_EXCEEDED"
                    )
                cid = f"{left.intent_id}/{right.intent_id}/{lq}/{rq}"
                fills[cid] = ClearingFill(left.intent_id, right.intent_id, lq, rq)
                candidates.append(
                    {
                        "candidate_id": cid,
                        "expected_utility_units": 2,
                        "tail_loss_units": 0,
                        "resource_usage": {left.intent_id: lq, right.intent_id: rq},
                        "conflict_keys": (
                            "intent:" + left.intent_id,
                            "intent:" + right.intent_id,
                        ),
                    }
                )
    proposal = solve_opportunity_portfolio(
        {
            "candidates": candidates,
            "budget": {r.intent_id: r.max_sell_atoms for r in active},
            "max_tail_loss_units": 0,
        }
    )
    chosen = tuple(fills[cid] for cid in proposal.candidate_ids)
    remaining = {r.intent_id: r.max_sell_atoms for r in intents}
    for fill in chosen:
        remaining[fill.left_intent_id] -= fill.left_sell_atoms
        remaining[fill.right_intent_id] -= fill.right_sell_atoms
    return ClearingResult(
        chosen, tuple(sorted(remaining.items())), len(chosen) * 2, len(candidates)
    )
