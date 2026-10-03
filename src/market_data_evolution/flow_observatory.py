"""Point-in-time, unit-safe stock/flow views over local immutable evidence."""

from __future__ import annotations
from dataclasses import dataclass
from .contracts import _int, _id


@dataclass(frozen=True, slots=True)
class FlowMeasurement:
    evidence_id: str
    event_id: str
    source_id: str
    domain: str
    metric_id: str
    definition_revision: str
    unit: str
    kind: str
    aggregation_level: str
    window_start_ns: int
    window_end_ns: int
    available_at_ns: int
    value_atoms: int | None
    covered_markets: int
    total_markets: int
    supersedes_id: str | None = None

    def __post_init__(self):
        for field in (
            "evidence_id",
            "event_id",
            "source_id",
            "domain",
            "metric_id",
            "definition_revision",
            "unit",
        ):
            _id(getattr(self, field), field)
        for field in (
            "window_start_ns",
            "window_end_ns",
            "available_at_ns",
            "covered_markets",
            "total_markets",
        ):
            _int(getattr(self, field), field, minimum=0)
        if (
            self.window_start_ns > self.window_end_ns
            or self.available_at_ns < self.window_end_ns
            or self.covered_markets > self.total_markets
        ):
            raise ValueError("invalid window or coverage")
        if self.value_atoms is not None:
            _int(self.value_atoms, "value_atoms", minimum=0)
        if self.kind not in ("stock", "flow") or self.aggregation_level not in (
            "underlying",
            "aggregator",
        ):
            raise ValueError("unsupported flow semantics")


@dataclass(frozen=True, slots=True)
class FlowView:
    value_atoms: int | None
    unit: str
    covered_markets: int
    total_markets: int
    source_lineage: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    aggregation_level: str


def aggregate_flows(
    rows: tuple[FlowMeasurement, ...],
    *,
    available_at_ns: int,
    metric_id: str,
    definition_revision: str,
    unit: str,
    domain: str,
    kind: str,
    window_start_ns: int,
    window_end_ns: int,
    aggregation_level: str,
) -> FlowView:
    """Deduplicate same economic event across suppliers; never sum stocks.

    Corrections only replace their exact evidence target once available. Source
    disagreement is UNKNOWN. Aggregator volume is a separate view, not additive
    to routed DEX volume. Coverage counts must agree and are not additive.
    """
    visible = [r for r in rows if r.available_at_ns <= available_at_ns]
    ids = [r.evidence_id for r in visible]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence identity")
    by_id = {r.evidence_id: r for r in visible}
    for row in visible:
        if row.supersedes_id is not None:
            target = by_id.get(row.supersedes_id)
            if (
                target is None
                or target.available_at_ns >= row.available_at_ns
                or (
                    target.event_id,
                    target.metric_id,
                    target.definition_revision,
                    target.unit,
                    target.domain,
                    target.kind,
                    target.aggregation_level,
                    target.window_start_ns,
                    target.window_end_ns,
                )
                != (
                    row.event_id,
                    row.metric_id,
                    row.definition_revision,
                    row.unit,
                    row.domain,
                    row.kind,
                    row.aggregation_level,
                    row.window_start_ns,
                    row.window_end_ns,
                )
            ):
                raise ValueError("correction lineage mismatch")
    removed = {r.supersedes_id for r in visible if r.supersedes_id is not None}
    if removed - set(ids):
        raise ValueError("missing correction target")
    selected = [
        r
        for r in visible
        if r.evidence_id not in removed
        and (
            r.metric_id,
            r.definition_revision,
            r.unit,
            r.domain,
            r.kind,
            r.window_start_ns,
            r.window_end_ns,
            r.aggregation_level,
        )
        == (
            metric_id,
            definition_revision,
            unit,
            domain,
            kind,
            window_start_ns,
            window_end_ns,
            aggregation_level,
        )
    ]
    by_event: dict[str, list[FlowMeasurement]] = {}
    for row in selected:
        by_event.setdefault(row.event_id, []).append(row)
    unknown = not selected
    values: list[int] = []
    for group in by_event.values():
        unique = {row.value_atoms for row in group}
        if len(unique) != 1 or None in unique:
            unknown = True
        else:
            value = group[0].value_atoms
            assert value is not None
            values.append(value)
    if kind == "stock" and len(by_event) != 1:
        unknown = True
    coverage = {(r.covered_markets, r.total_markets) for r in selected}
    if len(coverage) != 1:
        unknown = True
    covered, total = next(iter(coverage)) if len(coverage) == 1 else (0, 0)
    return FlowView(
        None if unknown else sum(values),
        unit,
        covered,
        total,
        tuple(sorted({r.source_id for r in selected})),
        tuple(sorted(r.evidence_id for r in selected)),
        aggregation_level,
    )
