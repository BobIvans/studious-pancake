"""PR-201 / ACTIVE-01 — active learning for expensive offline labels."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import PPM, integer, mean_int, require_rows


def select_uncertain_samples(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "samples")
    count = integer(limit, "limit", minimum=1)
    ranked = sorted(
        (
            dict(row)
            for row in rows
            if str(row.get("sample_id", "")).strip()
        ),
        key=lambda row: (
            abs(integer(row.get("probability_ppm"), "probability_ppm", minimum=0) - PPM // 2),
            str(row["sample_id"]),
        ),
    )
    return tuple(ranked[:count])


def request_targeted_labels(
    samples: Sequence[Mapping[str, Any]],
    *,
    quota_units: int,
    cost_per_label: int,
) -> tuple[dict[str, Any], ...]:
    quota = integer(quota_units, "quota_units", minimum=0)
    cost = integer(cost_per_label, "cost_per_label", minimum=1)
    maximum = quota // cost
    return tuple(
        {
            "sample_id": str(row["sample_id"]),
            "request_kind": "offline-label",
            "cost_units": cost,
            "execution_authority": False,
        }
        for row in samples[:maximum]
    )


def update_active_learning_pool(
    pool: Mapping[str, str | None],
    labels: Mapping[str, str],
) -> dict[str, str | None]:
    updated = dict(pool)
    for sample_id, label in labels.items():
        if sample_id not in updated:
            raise ValueError("label refers to unknown sample")
        updated[sample_id] = str(label)
    return updated


def measure_label_efficiency(
    uncertainty_before_ppm: Sequence[int],
    uncertainty_after_ppm: Sequence[int],
    *,
    acquired_labels: int,
) -> dict[str, int]:
    if not uncertainty_before_ppm or len(uncertainty_before_ppm) != len(uncertainty_after_ppm):
        raise ValueError("uncertainty arrays must align")
    labels = integer(acquired_labels, "acquired_labels", minimum=1)
    before = mean_int([integer(v, "uncertainty_before_ppm", minimum=0) for v in uncertainty_before_ppm])
    after = mean_int([integer(v, "uncertainty_after_ppm", minimum=0) for v in uncertainty_after_ppm])
    return {
        "uncertainty_reduction_ppm": before - after,
        "reduction_per_label_ppm": (before - after) // labels,
    }


__all__ = [
    "measure_label_efficiency",
    "request_targeted_labels",
    "select_uncertain_samples",
    "update_active_learning_pool",
]
