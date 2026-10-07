"""Thin adapters to qualification owners plus measured resource attribution."""

from dataclasses import asdict
from src.production_qualification import (
    build_agg04_funnel,
    compare_agg04_baselines,
    summarize_agg04_delay_stress,
    build_agg04_dashboard,
)


def build_strategy_funnel(**kwargs):
    return asdict(build_agg04_funnel(**kwargs))


def compare_strategy_baselines(rows):
    return asdict(compare_agg04_baselines(tuple(rows)))


def build_delay_stress(samples):
    return asdict(summarize_agg04_delay_stress(tuple(samples)))


def build_dashboard(**kwargs):
    return build_agg04_dashboard(**kwargs)


def build_resource_cost_report(rows: list[dict]) -> dict:
    fields = (
        "cpu_ms",
        "memory_peak_bytes",
        "disk_written_bytes",
        "quota_units",
        "laya_calls",
    )
    return {
        field: {
            "observed": sum(type(r.get(field)) is int for r in rows),
            "unknown": sum(type(r.get(field)) is not int for r in rows),
            "total": (
                sum(r[field] for r in rows if type(r.get(field)) is int)
                if any(type(r.get(field)) is int for r in rows)
                else None
            ),
        }
        for field in fields
    }
