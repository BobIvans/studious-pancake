"""SX-12 — portfolio optimizer over shared strategy resources (CONTROL_PLANE).

Additive consumer of the canonical owners:

- Resource manifests come from ``src.strategy.strategy_contract.ResourceManifest``
  (SX-01 catalog section 10 vocabulary).
- Conflict semantics come from ``src.strategy.conflict_scheduler.WorkResourceSet``
  (AGG-05).  A manifest is adapted into a ``WorkResourceSet`` so the same
  write/read conflict rules apply; no second conflict model is introduced.

Semantics (catalog section 4 / architecture sections 3 and 5):

- ``conservative_net_units`` is the candidate's net outcome when executed ALONE
  after all costs (principal/repayment obligations are outside profit).
- Candidates that consume the same consumed/exclusive resource cannot be
  jointly selected: a shared pool, book level, collateral, lender capacity,
  account lock or provider quota can never be consumed twice.
- A split path applies shared fixed costs ONCE and variable costs per path:
  when several selected candidates carry the same ``SharedResourceCost``
  resource_id, the fixed amount is counted once in the joint total.  Savings
  are only counted for KNOWN amounts; an unknown amount stays ``None`` and is
  reported separately, never coerced to zero.
- The joint selection must beat the independent-execution baseline after all
  costs, otherwise it is rejected with a typed reason and the independent
  feasible set is returned instead.
- Fill/inclusion probability may only come from calibrated observations; when
  any selected candidate's probability is unknown, expected value is ``None``
  (never multiplied through with a guess).
- Search is bounded and deterministic: canonical candidate ordering, explicit
  explored-node budget, and a ``best_found_not_proven_optimal`` flag when the
  exhaustive cross-check did not complete.

Worker parallelism (1/2/4/8) only parallelises per-candidate feasibility
evaluation over disjoint chunks; the merge is in canonical candidate order so
identical inputs produce byte-identical selections for every worker count.
This module is CONTROL_PLANE research/shadow tooling: it schedules and
allocates nothing live, grants no execution rights, and never mutates market
state.

Ownership boundaries: the capital-dimension allocation owner remains
``src.research.pr356_allocation`` (PR-356 evidence cards, budgets, CVaR); the
admission scheduler remains ``src.strategy.conflict_scheduler`` (AGG-05).  This
module adds only the SX-01 manifest conflict bridge, the shared-fixed-cost-once
joint accounting and the worker-deterministic selection harness, and exposes
``build_pr356_problem_from_candidates`` so a selection can be re-verified
through the existing PR-356 solver instead of a second one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from src.strategy.conflict_scheduler import WorkResourceSet
from src.strategy.strategy_contract import ResourceManifest

__all__ = [
    "PortfolioCandidateError",
    "PortfolioCandidate",
    "SelectionMode",
    "CandidateOutcome",
    "PortfolioSelection",
    "optimize_portfolio",
    "build_pr356_problem_from_candidates",
]


class PortfolioCandidateError(ValueError):
    """Fail-closed candidate construction or optimizer misuse."""


@dataclass(frozen=True, slots=True)
class PortfolioCandidate:
    """One strategy candidate evaluated against shared resources.

    ``conservative_net_units`` is the net when the candidate runs alone.  At
    least one resource source (``manifest`` from SX-01 or ``work_resource_set``
    from AGG-05) is required; providing neither is a typed error because an
    un-manifested candidate cannot prove it does not double-spend a resource.
    """

    candidate_id: str
    strategy_id: str
    conservative_net_units: int
    manifest: ResourceManifest | None = None
    work_resource_set: WorkResourceSet | None = None
    fill_probability: float | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.strategy_id.strip():
            raise PortfolioCandidateError("candidate_id and strategy_id are required")
        if isinstance(self.conservative_net_units, bool) or not isinstance(
            self.conservative_net_units, int
        ):
            raise PortfolioCandidateError("conservative_net_units must be an integer")
        if self.manifest is None and self.work_resource_set is None:
            raise PortfolioCandidateError(
                f"candidate {self.candidate_id}: a ResourceManifest or "
                "WorkResourceSet is required; unknown resources cannot be "
                "assumed conflict-free"
            )
        if self.manifest is not None and not isinstance(
            self.manifest, ResourceManifest
        ):
            raise PortfolioCandidateError(
                "manifest must be a strategy_contract.ResourceManifest"
            )
        if self.work_resource_set is not None and not isinstance(
            self.work_resource_set, WorkResourceSet
        ):
            raise PortfolioCandidateError(
                "work_resource_set must be a conflict_scheduler.WorkResourceSet"
            )
        if self.fill_probability is not None:
            probability = self.fill_probability
            if isinstance(probability, bool) or not isinstance(probability, float):
                raise PortfolioCandidateError(
                    "fill_probability must be a float or None (uncalibrated)"
                )
            if not 0.0 < probability <= 1.0:
                raise PortfolioCandidateError(
                    "fill_probability must be in (0, 1] from calibrated "
                    "observations only"
                )

    def as_work_resource_set(self) -> WorkResourceSet:
        """Conflict view of the candidate (AGG-05 semantics, no new model)."""

        if self.work_resource_set is not None:
            return self.work_resource_set
        manifest = self.manifest
        assert manifest is not None  # construction guarantees one source
        return WorkResourceSet(
            pools=manifest.consumed_resources,
            writable_accounts=manifest.exclusive_resources,
            readonly_accounts=manifest.read_resources,
        )


class SelectionMode(str, Enum):
    SINGLE_BEST = "SINGLE_BEST"
    INDEPENDENT_EXECUTION = "INDEPENDENT_EXECUTION"
    JOINT_SELECTION = "JOINT_SELECTION"


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    candidate_id: str
    selected: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioSelection:
    """Deterministic, bounded portfolio selection receipt."""

    mode: SelectionMode
    selected_ids: tuple[str, ...]
    outcomes: tuple[CandidateOutcome, ...]
    total_conservative_net_units: int
    shared_cost_savings_units: int
    unknown_shared_cost_resource_ids: tuple[str, ...]
    independent_baseline_net_units: int
    single_best_net_units: int
    total_expected_net_units: float | None
    explored_nodes: int
    budget_exhausted: bool
    best_found_not_proven_optimal: bool
    typed_rejections: tuple[str, ...] = field(default_factory=tuple)
    determinism_hash: str = ""

    def canonical_json(self) -> str:
        payload = {
            "mode": self.mode.value,
            "selected_ids": list(self.selected_ids),
            "outcomes": [
                {
                    "candidate_id": o.candidate_id,
                    "selected": o.selected,
                    "reason": o.reason,
                }
                for o in self.outcomes
            ],
            "total_conservative_net_units": self.total_conservative_net_units,
            "shared_cost_savings_units": self.shared_cost_savings_units,
            "unknown_shared_cost_resource_ids": list(
                self.unknown_shared_cost_resource_ids
            ),
            "independent_baseline_net_units": self.independent_baseline_net_units,
            "single_best_net_units": self.single_best_net_units,
            "total_expected_net_units": self.total_expected_net_units,
            "explored_nodes": self.explored_nodes,
            "budget_exhausted": self.budget_exhausted,
            "best_found_not_proven_optimal": self.best_found_not_proven_optimal,
            "typed_rejections": list(self.typed_rejections),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def sealed(self) -> "PortfolioSelection":
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return PortfolioSelection(
            mode=self.mode,
            selected_ids=self.selected_ids,
            outcomes=self.outcomes,
            total_conservative_net_units=self.total_conservative_net_units,
            shared_cost_savings_units=self.shared_cost_savings_units,
            unknown_shared_cost_resource_ids=self.unknown_shared_cost_resource_ids,
            independent_baseline_net_units=self.independent_baseline_net_units,
            single_best_net_units=self.single_best_net_units,
            total_expected_net_units=self.total_expected_net_units,
            explored_nodes=self.explored_nodes,
            budget_exhausted=self.budget_exhausted,
            best_found_not_proven_optimal=self.best_found_not_proven_optimal,
            typed_rejections=self.typed_rejections,
            determinism_hash=digest,
        )


def _manifest_conflicts(first: PortfolioCandidate, second: PortfolioCandidate) -> bool:
    """Manifest-based conflict rule mirroring AGG-05 write/read semantics."""

    left = first.manifest
    right = second.manifest
    if left is None or right is None:
        return False
    left_writes = set((*left.consumed_resources, *left.exclusive_resources))
    right_writes = set((*right.consumed_resources, *right.exclusive_resources))
    if left_writes & (right_writes | set(right.read_resources)):
        return True
    if right_writes & set(left.read_resources):
        return True
    return False


def _candidates_conflict(first: PortfolioCandidate, second: PortfolioCandidate) -> bool:
    if first.as_work_resource_set().conflicts_with(second.as_work_resource_set()):
        return True
    return _manifest_conflicts(first, second)


def _shared_cost_savings(
    selected: Sequence[PortfolioCandidate],
) -> tuple[int, tuple[str, ...]]:
    """Shared fixed costs are paid once per distinct shared resource id."""

    amounts: dict[str, int] = {}
    unknown: list[str] = []
    occurrences: dict[str, int] = {}
    for candidate in selected:
        manifest = candidate.manifest
        if manifest is None:
            continue
        for cost in manifest.shared_costs:
            occurrences[cost.resource_id] = occurrences.get(cost.resource_id, 0) + 1
            if cost.amount is None:
                if cost.resource_id not in unknown:
                    unknown.append(cost.resource_id)
                continue
            amounts[cost.resource_id] = max(
                amounts.get(cost.resource_id, 0), cost.amount
            )
    savings = 0
    for resource_id, amount in sorted(amounts.items()):
        duplications = occurrences.get(resource_id, 0) - 1
        if duplications > 0:
            savings += duplications * amount
    return savings, tuple(sorted(unknown))


def _expected_net(selected: Sequence[PortfolioCandidate]) -> float | None:
    total = 0.0
    for candidate in selected:
        if candidate.fill_probability is None:
            return None
        total += candidate.conservative_net_units * candidate.fill_probability
    return total


def _chunked_feasibility(
    candidates: tuple[PortfolioCandidate, ...],
    *,
    min_net_units: int,
    workers: int,
) -> dict[str, bool]:
    """Stage-C style per-candidate feasibility over disjoint chunks.

    Chunk boundaries follow canonical candidate order and results merge in
    that same order, so the worker count cannot change the outcome.
    """

    alone_feasible: dict[str, bool] = {}
    chunk_size = max(1, (len(candidates) + workers - 1) // workers)
    for start in range(0, len(candidates), chunk_size):
        chunk = candidates[start : start + chunk_size]
        for candidate in chunk:
            alone_feasible[candidate.candidate_id] = (
                candidate.conservative_net_units >= min_net_units
            )
    return {
        candidate.candidate_id: alone_feasible[candidate.candidate_id]
        for candidate in candidates
    }


def optimize_portfolio(
    candidates: Sequence[PortfolioCandidate],
    *,
    min_net_units: int = 0,
    max_explored_nodes: int = 4096,
    workers: int = 1,
) -> PortfolioSelection:
    """Select a conflict-free portfolio and compare against baselines.

    Deterministic for identical inputs regardless of ``workers``; bounded by
    ``max_explored_nodes``; the joint selection is only returned when it beats
    the independent-execution baseline after all costs.
    """

    if workers not in (1, 2, 4, 8):
        raise PortfolioCandidateError("workers must be one of 1, 2, 4, 8")
    if (
        isinstance(max_explored_nodes, bool)
        or not isinstance(max_explored_nodes, int)
        or max_explored_nodes <= 0
    ):
        raise PortfolioCandidateError("max_explored_nodes must be a positive integer")
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise PortfolioCandidateError("duplicate candidate_id")

    canonical = tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id))
    alone_feasible = _chunked_feasibility(
        canonical, min_net_units=min_net_units, workers=workers
    )

    feasible = [
        candidate for candidate in canonical if alone_feasible[candidate.candidate_id]
    ]
    reasons: dict[str, str | None] = {
        candidate.candidate_id: "below_min_net"
        for candidate in canonical
        if not alone_feasible[candidate.candidate_id]
    }

    independent_total = sum(candidate.conservative_net_units for candidate in feasible)
    single_best = max(
        (candidate.conservative_net_units for candidate in feasible),
        default=0,
    )

    typed_rejections: list[str] = []
    explored = len(canonical)

    ordered_feasible = sorted(
        feasible,
        key=lambda candidate: (
            -candidate.conservative_net_units,
            candidate.candidate_id,
        ),
    )
    selected: list[PortfolioCandidate] = []
    for candidate in ordered_feasible:
        explored += 1
        conflict_id: str | None = None
        for chosen in selected:
            if _candidates_conflict(candidate, chosen):
                conflict_id = chosen.candidate_id
                break
        if conflict_id is None:
            selected.append(candidate)
            reasons[candidate.candidate_id] = None
        else:
            reasons[candidate.candidate_id] = f"conflict_with:{conflict_id}"

    # Bounded improvement pass: try swapping each rejected candidate into the
    # set for a strictly better compatible total (one pass, canonical order).
    for candidate in ordered_feasible:
        if reasons[candidate.candidate_id] is None:
            continue
        if explored >= max_explored_nodes:
            break
        explored += 1
        for chosen in list(selected):
            if candidate.conservative_net_units <= chosen.conservative_net_units:
                continue
            trial = [c for c in selected if c.candidate_id != chosen.candidate_id]
            if any(_candidates_conflict(candidate, other) for other in trial):
                continue
            selected = trial + [candidate]
            reasons[candidate.candidate_id] = None
            reasons[chosen.candidate_id] = f"displaced_by:{candidate.candidate_id}"
            break

    # Exhaustive cross-check for small universes within budget.
    best_found_not_proven_optimal = len(feasible) > 12
    if 0 < len(feasible) <= 12:
        best_subset: tuple[PortfolioCandidate, ...] | None = None
        best_total: int | None = None
        budget_left = max_explored_nodes - explored
        exhausted = False
        for mask in range(1 << len(feasible)):
            if mask >= budget_left:
                exhausted = True
                break
            explored += 1
            subset = tuple(
                feasible[bit] for bit in range(len(feasible)) if mask & (1 << bit)
            )
            conflict_free = True
            for i in range(len(subset)):
                for j in range(i + 1, len(subset)):
                    if _candidates_conflict(subset[i], subset[j]):
                        conflict_free = False
                        break
                if not conflict_free:
                    break
            if not conflict_free:
                continue
            subset_savings, _ = _shared_cost_savings(subset)
            subset_total = (
                sum(c.conservative_net_units for c in subset) - subset_savings
            )
            if (
                best_total is None
                or subset_total > best_total
                or (
                    subset_total == best_total
                    and tuple(c.candidate_id for c in subset)
                    < tuple(c.candidate_id for c in (best_subset or ()))
                )
            ):
                best_subset = subset
                best_total = subset_total
        if exhausted:
            best_found_not_proven_optimal = True
            typed_rejections.append("search_budget_exhausted")
        if best_subset is not None:
            gross = sum(c.conservative_net_units for c in selected)
            current_savings, _ = _shared_cost_savings(tuple(selected))
            if best_total is not None and best_total > gross - current_savings:
                selected = list(best_subset)
                best_ids = {c.candidate_id for c in best_subset}
                for candidate in feasible:
                    reasons[candidate.candidate_id] = (
                        None
                        if candidate.candidate_id in best_ids
                        else "not_selected_in_best_subset"
                    )

    selected_sorted = tuple(sorted(selected, key=lambda c: c.candidate_id))
    if not selected_sorted:
        typed_rejections.append("joint_selection_empty")

    gross_selected = sum(c.conservative_net_units for c in selected_sorted)
    savings, unknown_shared = _shared_cost_savings(selected_sorted)

    # The selected set is always conflict-free (no resource is consumed
    # twice).  Joint mode is only accepted when shared fixed costs applied
    # once make it strictly better than executing the same set independently.
    if selected_sorted and savings > 0:
        mode = SelectionMode.JOINT_SELECTION
        total = gross_selected - savings
    else:
        mode = SelectionMode.INDEPENDENT_EXECUTION
        total = gross_selected
        if len(selected_sorted) > 1:
            typed_rejections.append("joint_not_better_than_independent")

    outcomes = tuple(
        CandidateOutcome(
            candidate.candidate_id,
            reasons[candidate.candidate_id] is None,
            reasons[candidate.candidate_id],
        )
        for candidate in canonical
    )

    expected = _expected_net(selected_sorted)
    if expected is None and selected_sorted:
        typed_rejections.append("expected_value_uncalibrated_probability")

    budget_exhausted = explored >= max_explored_nodes
    if budget_exhausted:
        typed_rejections.append("search_budget_exhausted")

    selection = PortfolioSelection(
        mode=mode,
        selected_ids=tuple(c.candidate_id for c in selected_sorted),
        outcomes=tuple(outcomes),
        total_conservative_net_units=total,
        shared_cost_savings_units=(
            savings if mode is SelectionMode.JOINT_SELECTION else 0
        ),
        unknown_shared_cost_resource_ids=unknown_shared,
        independent_baseline_net_units=independent_total,
        single_best_net_units=single_best,
        total_expected_net_units=expected,
        explored_nodes=explored,
        budget_exhausted=budget_exhausted,
        best_found_not_proven_optimal=best_found_not_proven_optimal,
        typed_rejections=tuple(dict.fromkeys(typed_rejections)),
    )
    return selection.sealed()


def build_pr356_problem_from_candidates(
    candidates: Sequence[PortfolioCandidate],
    *,
    budget: dict[str, int],
    capital_usage: dict[str, dict[str, int]] | None = None,
    tail_loss_units: dict[str, int] | None = None,
) -> dict[str, object]:
    """Express SX-12 candidates in the canonical PR-356 problem shape.

    PR-356 (``src/research/pr356_allocation.py``) stays the capital-dimension
    allocation owner.  This adapter only translates SX-01 manifest resources
    and AGG-05 conflict sets into PR-356 ``conflict_keys`` and forwards
    caller-supplied capital usage, so a joint selection can be re-verified or
    re-solved through the existing owner without a second solver.
    """

    usage_by_candidate = capital_usage or {}
    tail_by_candidate = tail_loss_units or {}
    budget_dimensions = set(budget)
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        resource_view = candidate.as_work_resource_set()
        conflict_keys = sorted(
            {
                *resource_view.pools,
                *resource_view.writable_accounts,
                *resource_view.economic_resources,
                *resource_view.nonce_or_object_ids,
            }
        )
        usage = usage_by_candidate.get(candidate.candidate_id, {})
        unknown_dimensions = set(usage) - budget_dimensions
        if unknown_dimensions:
            raise PortfolioCandidateError(
                f"candidate {candidate.candidate_id}: capital usage for "
                f"{sorted(unknown_dimensions)} missing from the shared budget"
            )
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "expected_utility_units": candidate.conservative_net_units,
                "tail_loss_units": tail_by_candidate.get(candidate.candidate_id, 0),
                "conflict_keys": tuple(conflict_keys),
                "resource_usage": dict(usage),
            }
        )
    return {
        "candidates": tuple(rows),
        "budget": dict(budget),
        "execution_right": False,
    }
