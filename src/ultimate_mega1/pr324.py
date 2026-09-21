"""PR-324 / NF-1002..1006: independent sentinel sampling for observable misses."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def define_sentinel_sampling_frame(
    cells: Sequence[str],
    *,
    as_of: int,
    unavailable: Sequence[str] = (),
) -> ContractResult:
    if not cells:
        raise UltimateMegaError("FRAME_INCOMPLETE")
    as_of = require_nonnegative(as_of, "as_of")
    ordered = tuple(dict.fromkeys(str(x) for x in cells))
    excluded = tuple(sorted(set(str(x) for x in unavailable)))
    available = tuple(cell for cell in ordered if cell not in set(excluded))
    if not available:
        raise UltimateMegaError("FRAME_INCOMPLETE")
    return record(
        "define_sentinel_sampling_frame",
        {"as_of": as_of, "universe": ordered, "available": available, "unavailable": excluded},
    )


def draw_independent_sentinel_cells(
    frame: Mapping[str, Any],
    *,
    seed_commitment: str,
    sample_size: int,
) -> ContractResult:
    available = tuple(str(x) for x in frame.get("available", ()))
    size = require_positive(sample_size, "sample_size")
    if size > len(available):
        raise UltimateMegaError("PROTECTED_QUOTA_VIOLATION")
    ranked = sorted(
        available,
        key=lambda cell: hashlib.sha256(
            f"{seed_commitment}|{cell}".encode("utf-8")
        ).digest(),
    )
    selected = tuple(ranked[:size])
    return record(
        "draw_independent_sentinel_cells",
        {
            "selected": selected,
            "population": len(available),
            "sample_size": size,
            "inclusion_probability_fraction": (size, len(available)),
            "ranker_used": False,
        },
    )


def run_reference_search_on_sentinel(
    selected: Sequence[str],
    labels: Mapping[str, bool | None],
) -> ContractResult:
    rows = []
    inconclusive = 0
    for cell in selected:
        label = labels.get(cell)
        if label is None:
            inconclusive += 1
            rows.append((cell, "UNKNOWN"))
        else:
            rows.append((cell, "OPPORTUNITY" if label else "NO_OPPORTUNITY"))
    return record(
        "run_reference_search_on_sentinel",
        {"labels": tuple(rows), "inconclusive": inconclusive},
        status="INCOMPLETE" if inconclusive else "OK",
        blockers=("SEARCH_INCONCLUSIVE",) if inconclusive else (),
    )


def estimate_observable_miss_rate(
    *,
    labels: Mapping[str, bool | None],
    detector_selected: Mapping[str, bool],
    inclusion_probability_num: int,
    inclusion_probability_den: int,
) -> ContractResult:
    num = require_positive(inclusion_probability_num, "inclusion_probability_num")
    den = require_positive(inclusion_probability_den, "inclusion_probability_den")
    if num > den:
        raise UltimateMegaError("PROBABILITY_UNKNOWN")
    opportunities = misses = observed = 0
    for cell, label in labels.items():
        if label is None:
            continue
        observed += 1
        if label:
            opportunities += 1
            if not detector_selected.get(cell, False):
                misses += 1
    if observed == 0:
        raise UltimateMegaError("UNSUPPORTED_POPULATION_CLAIM")
    return record(
        "estimate_observable_miss_rate",
        {
            "observed_labels": observed,
            "observable_opportunities": opportunities,
            "misses": misses,
            "miss_rate_fraction": (misses, opportunities) if opportunities else (0, 1),
            "inclusion_probability_fraction": (num, den),
            "claim_scope": "DECLARED_SENTINEL_UNIVERSE",
        },
    )


def allocate_detector_improvement_from_misses(
    miss_causes: Mapping[str, int],
    *,
    minimum_evidence: int = 1,
) -> ContractResult:
    minimum = require_positive(minimum_evidence, "minimum_evidence")
    qualified = tuple(
        sorted(
            (cause, require_nonnegative(count, f"cause_{cause}"))
            for cause, count in miss_causes.items()
            if count >= minimum
        )
    )
    if not qualified:
        raise UltimateMegaError("INSUFFICIENT_SENTINEL_EVIDENCE")
    return record(
        "allocate_detector_improvement_from_misses",
        {"prioritized_causes": qualified, "source_quota_changed": False},
    )
