from dataclasses import replace

import pytest

from src.assets.resolution.evidence import EvidenceStore
from src.assets.resolution.resolver import canonical_identifier
from src.economics.flash_capital_graph.graph import (
    FlashCapitalEdge,
    FlashCapitalGraph,
    Project0CapitalProvider,
    navi_sdk_snapshot,
)
from tests.test_dynamic_asset_resolution import evidence
from tests.test_dynamic_relations import asset


def capital(**changes):
    a = asset()
    return replace(
        FlashCapitalEdge(
            "solana",
            "project0",
            a.asset_id,
            a.canonical_identifier,
            "bank-a",
            1000,
            1,
            1000,
            1,
            "LOCAL_ATOMIC_CANDIDATE",
            (),
            evidence("lender", 10),
            ("proof",),
        ),
        **changes,
    )


def test_observed_capacity_fee_and_pr118_economics(tmp_path):
    graph = FlashCapitalGraph("campaign", EvidenceStore(tmp_path))
    edge = capital()
    graph.observe(edge, now=101)
    assert graph.size_grid(edge, lower=10, upper=2000, max_points=3) == (10, 505, 1000)
    ledger = graph.paper_ledger(
        edge,
        asset=asset(),
        principal=501,
        guaranteed_output=505,
        costs=(),
        resources=frozenset(),
        now=101,
    )
    assert ledger.required_repayment_amount == 503
    assert ledger.conservative_net_amount() == 2
    with pytest.raises(ValueError):
        edge.fee(1001)


def test_changed_capacity_or_fee_invalidates_old_size(tmp_path):
    graph = FlashCapitalGraph("campaign", EvidenceStore(tmp_path))
    old = capital()
    graph.observe(old, now=101)
    new = capital(
        max_amount_live=100,
        fee_numerator=10,
        evidence=evidence("lender", 11, timestamp=102),
    )
    graph.observe(new, now=102)
    assert len(graph.history) == 2
    with pytest.raises(ValueError, match="changed"):
        graph.paper_ledger(
            old,
            asset=asset(),
            principal=501,
            guaranteed_output=505,
            costs=(),
            resources=frozenset(),
            now=102,
        )
    with pytest.raises(ValueError):
        graph.paper_ledger(
            new,
            asset=asset(),
            principal=501,
            guaranteed_output=505,
            costs=(),
            resources=frozenset(),
            now=102,
        )


def test_disagreement_and_stale_terms_fail_closed(tmp_path):
    graph = FlashCapitalGraph("campaign", EvidenceStore(tmp_path))
    edge = capital()
    graph.observe(edge, now=101)
    with pytest.raises(ValueError, match="disagreement"):
        graph.observe(capital(max_amount_live=999), now=101)
    with pytest.raises(ValueError):
        graph.paper_ledger(
            edge,
            asset=asset(),
            principal=10,
            guaranteed_output=20,
            costs=(),
            resources=frozenset(),
            now=101,
        )
    with pytest.raises(ValueError, match="stale"):
        graph.observe(edge, now=200)


def test_pool_local_capital_cannot_finance_unrelated_market(tmp_path):
    graph = FlashCapitalGraph("campaign", EvidenceStore(tmp_path))
    edge = capital(constraints=("pool-a",))
    graph.observe(edge, now=101)
    with pytest.raises(ValueError, match="constraints"):
        graph.paper_ledger(
            edge,
            asset=asset(),
            principal=10,
            guaranteed_output=20,
            costs=(),
            resources=frozenset(("pool-b",)),
            now=101,
        )


def test_dynamic_provider_never_assumes_registry_asset_is_borrowable():
    a = asset()
    row = {
        "canonical_identifier": a.canonical_identifier,
        "resource_id": "bank",
        "flash_enabled": True,
        "max_amount_atoms": 500,
        "fee_numerator": 1,
        "fee_denominator": 1000,
        "protocol_rounding_atoms": 0,
        "constraints": [],
    }
    payload = {
        "schema": "dynamic-universe.capital.v1",
        "provider": "project0",
        "assets": [row],
    }
    provider = Project0CapitalProvider(lambda: (payload, evidence("lender", 10)), (a,))
    assert provider.refresh(a.asset_id, 100).max_amount_live == 500
    row["flash_enabled"] = False
    assert provider.discover_assets() == ()
    with pytest.raises(ValueError):
        provider.refresh(a.asset_id, 100)
    payload["schema"] = "drift"
    assert provider.discover_assets() == ()
    assert "capital_schema_drift" in provider.negative_evidence


def test_navi_sdk_units_and_fee_are_exact():
    coin = canonical_identifier("sui", "0x2::sui::SUI")
    rows = [
        {
            "coinType": coin,
            "max": "12.000000001",
            "flashloanFee": "0.0009",
            "resource_id": "pool",
            "flash_enabled": True,
            "protocol_rounding_atoms": 0,
            "constraints": [],
        }
    ]
    row = navi_sdk_snapshot(rows, decimals_by_type={coin: 9})["assets"][0]
    assert row["max_amount_atoms"] == 12_000_000_001
    assert (row["fee_numerator"], row["fee_denominator"]) == (9, 10000)
    rows[0]["flashloanFee"] = 0.0009
    with pytest.raises(ValueError):
        navi_sdk_snapshot(rows, decimals_by_type={coin: 9})


def test_ton_is_never_local_atomic_capital():
    with pytest.raises(ValueError):
        capital(chain="ton")
