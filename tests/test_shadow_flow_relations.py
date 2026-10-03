from dataclasses import replace
import pytest
from src.market_data_evolution.flow_observatory import FlowMeasurement, aggregate_flows
from src.mechanism_discovery.claims import EconomicRelation, qualify_cashflow_identity
from src.mechanism_discovery.evidence_native_core import EvidenceNativeError


def measurement():
    return FlowMeasurement(
        "e1",
        "trade1",
        "s1",
        "chain",
        "volume",
        "v1",
        "USD-micros",
        "flow",
        "underlying",
        10,
        20,
        21,
        100,
        1,
        5,
    )


def view(rows, now=21, kind="flow"):
    return aggregate_flows(
        rows,
        available_at_ns=now,
        metric_id="volume",
        definition_revision="v1",
        unit="USD-micros",
        domain="chain",
        kind=kind,
        window_start_ns=10,
        window_end_ns=20,
        aggregation_level="underlying",
    )


def test_dedup_units_aggregation_corrections_and_unknown():
    row = measurement()
    duplicate_event = replace(row, evidence_id="e2", source_id="s2")
    routed = replace(row, evidence_id="e3", aggregation_level="aggregator")
    assert view((row, duplicate_event, routed)).value_atoms == 100
    correction = replace(
        row, evidence_id="e4", supersedes_id="e1", value_atoms=110, available_at_ns=30
    )
    assert view((row, correction)).value_atoms == 100
    assert view((row, correction), 30).value_atoms == 110
    assert view((row, replace(duplicate_event, value_atoms=101))).value_atoms is None
    assert view(()).value_atoms is None
    assert view((replace(row, unit="SOL-atoms"),)).value_atoms is None
    assert (
        view(
            (
                replace(row, kind="stock"),
                replace(duplicate_event, kind="stock", event_id="stock2"),
            ),
            kind="stock",
        ).value_atoms
        is None
    )


def test_vector_conversion_hyperedge_and_access_atomicity():
    relation = EconomicRelation(
        "split",
        "v1",
        "chain",
        (("SY", 1),),
        (("PT", 1), ("YT", 1)),
        10,
        10,
        0,
        100,
        ("redeemer",),
        ("raw-proof",),
    )
    assert relation.apply(
        {"SY": 3}, lots=2, now_ns=20, domain="chain", access=frozenset({"redeemer"})
    ) == {"SY": 1, "PT": 2, "YT": 2}
    for invalid in (
        replace(relation, family="empirical-correlation"),
        replace(relation, settlement_delay_ns=1),
    ):
        with pytest.raises(EvidenceNativeError):
            invalid.apply(
                {"SY": 3},
                lots=2,
                now_ns=20,
                domain="chain",
                access=frozenset({"redeemer"}),
            )
    with pytest.raises(EvidenceNativeError, match="ACCESS"):
        relation.apply({"SY": 3}, lots=2, now_ns=20, domain="chain", access=frozenset())
    with pytest.raises(EvidenceNativeError, match="BALANCE"):
        relation.apply(
            {"SY": 1}, lots=2, now_ns=20, domain="chain", access=frozenset({"redeemer"})
        )
