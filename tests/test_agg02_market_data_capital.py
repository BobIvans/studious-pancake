from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.agg02 import (
    AffectedRouteIndex,
    Agg02Error,
    AssetIdentity,
    BudgetDimension,
    CapacityPoint,
    CapacitySurface,
    EvidenceLineageDAG,
    EvidenceNode,
    ExecutableGraph,
    FeeComponent,
    FeeSurface,
    OperationEdge,
    ProgramTokenObservation,
    RawEventEnvelope,
    RouteDefinition,
    SourceAccess,
    SourceBudgetAuthority,
    SourceRegistryEntry,
    StateRecord,
    UniverseCandidate,
    admit_program_token_interaction,
    build_state_frame,
    build_subscription_plan,
    classify_retry,
    evaluate_source_slo,
    observe_budget_envelope,
    route_resource_footprint,
    routes_conflict,
    schedule_market_universe,
)
from src.agg02.storage import DurableRawJournal
from src.data_plane.bounded_provider_plane_pr197 import SQLiteQuotaAuthority
from src.economics.durable_reservations import WalletBalanceSnapshot

pytestmark = pytest.mark.unit

HASH_A = "a" * 64
HASH_B = "b" * 64


def _source() -> SourceRegistryEntry:
    return SourceRegistryEntry(
        source_id="helius",
        role="rpc",
        metering_unit="request",
        credential_scope="market-read",
        storage_allowed=True,
        access=SourceAccess.ACTIVE,
        entitlement_expires_at_ms=100_000,
        correlation_group="provider-a",
    )


def _event(
    payload: bytes,
    *,
    event_id: str,
    offset: int,
    gap_before: bool = False,
) -> RawEventEnvelope:
    return RawEventEnvelope(
        event_id=event_id,
        source_id="helius",
        chain_id="solana-mainnet",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        received_at_ms=10_000 + offset,
        available_at_ms=10_001 + offset,
        decoder_version="v1",
        cursor_source="helius",
        cursor_partition="accounts",
        cursor_offset=offset,
        reconnect_epoch=0,
        slot=1_000 + offset,
        commitment="confirmed",
        gap_before=gap_before,
    )


def test_shared_source_budget_is_cross_instance_and_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "quota.sqlite3"
    first_db = SQLiteQuotaAuthority(path)
    second_db = SQLiteQuotaAuthority(path)
    first = SourceBudgetAuthority(first_db)
    second = SourceBudgetAuthority(second_db)
    dimensions = (
        BudgetDimension("requests", limit=2, span_ms=60_000),
        BudgetDimension("bytes", limit=20, span_ms=60_000, units=10),
    )

    first.reserve(
        source=_source(),
        key_fingerprint=HASH_A,
        now_ms=1_000,
        dimensions=dimensions,
    )
    second.reserve(
        source=_source(),
        key_fingerprint=HASH_A,
        now_ms=1_001,
        dimensions=dimensions,
    )
    with pytest.raises(Agg02Error) as denied:
        first.reserve(
            source=_source(),
            key_fingerprint=HASH_A,
            now_ms=1_002,
            dimensions=dimensions,
        )
    assert denied.value.reason_code == "AGG02_SOURCE_BUDGET_DENIED"
    assert str(denied.value) == "PR197_QUOTA_EXHAUSTED"

    first_db.close()
    second_db.close()


def test_expired_entitlement_blocks_before_quota_write(tmp_path: Path) -> None:
    db = SQLiteQuotaAuthority(tmp_path / "quota.sqlite3")
    authority = SourceBudgetAuthority(db)
    expired = SourceRegistryEntry(
        source_id="trial",
        role="stream",
        metering_unit="byte",
        credential_scope="read",
        storage_allowed=True,
        access=SourceAccess.ACTIVE,
        entitlement_expires_at_ms=100,
    )
    with pytest.raises(Agg02Error, match="AGG02_SOURCE_ENTITLEMENT_EXPIRED"):
        authority.reserve(
            source=expired,
            key_fingerprint=HASH_A,
            now_ms=100,
            dimensions=(BudgetDimension("bytes", 10, 60_000),),
        )
    db.close()


def test_retry_subscription_and_slo_semantics_are_bounded() -> None:
    assert classify_retry(
        status_code=403,
        retry_after_ms=None,
        attempt=0,
        max_attempts=3,
        now_ms=10,
        deadline_ms=1_000,
    ).retry is False
    rate = classify_retry(
        status_code=429,
        retry_after_ms=50,
        attempt=0,
        max_attempts=3,
        now_ms=10,
        deadline_ms=1_000,
    )
    assert rate.retry is True
    assert rate.delay_ms == 50

    plan = build_subscription_plan(
        source_id="helius",
        requirements={
            "circular": ("pool-a", "oracle-a"),
            "stable": ("pool-a",),
        },
    )
    assert plan.accounts == ("oracle-a", "pool-a")
    assert plan.consumers_by_account["pool-a"] == ("circular", "stable")

    verdict = evaluate_source_slo(
        freshness_ms=None,
        gap_count=0,
        unknown_share_bps=0,
        max_freshness_ms=1_000,
        max_gaps=0,
        max_unknown_share_bps=100,
    )
    assert verdict.qualified is False
    assert verdict.reason == "freshness_unknown"


def test_raw_journal_binds_payload_and_cursor_atomically(tmp_path: Path) -> None:
    path = tmp_path / "raw.sqlite3"
    with DurableRawJournal(path) as journal:
        first_payload = b'{"slot":1}'
        first = _event(first_payload, event_id="event-1", offset=1)
        receipt = journal.append(first, first_payload)
        assert receipt.inserted is True
        assert journal.append(first, first_payload).inserted is False
        assert journal.cursor("helius", "accounts").offset == 1

        with pytest.raises(Agg02Error, match="AGG02_RAW_PAYLOAD_HASH_MISMATCH"):
            journal.append(
                _event(b'{"slot":2}', event_id="event-2", offset=2),
                b"tampered",
            )
        assert journal.cursor("helius", "accounts").offset == 1

        with pytest.raises(Agg02Error, match="AGG02_UNDECLARED_CURSOR_GAP"):
            journal.append(
                _event(b'{"slot":3}', event_id="event-3", offset=3),
                b'{"slot":3}',
            )
        assert journal.cursor("helius", "accounts").offset == 1

        third = _event(
            b'{"slot":3}',
            event_id="event-3",
            offset=3,
            gap_before=True,
        )
        journal.record_gap(
            source="helius",
            partition="accounts",
            reconnect_epoch=0,
            from_offset=2,
            to_offset=2,
            reason="provider_gap",
        )
        journal.append(third, b'{"slot":3}')
        assert journal.open_gaps()
        journal.close_gap(
            source="helius",
            partition="accounts",
            reconnect_epoch=0,
            from_offset=2,
        )
        assert journal.open_gaps() == ()

    with DurableRawJournal(path) as restarted:
        assert restarted.replay_event_ids() == ("event-1", "event-3")
        assert restarted.cursor("helius", "accounts").offset == 3


def test_state_frame_is_point_in_time_and_gap_fail_closed() -> None:
    old = StateRecord.from_mapping(
        dependency_id="pool-a",
        generation="g1",
        available_at_ms=100,
        payload={"reserve": "10"},
        slot=10,
    )
    future = StateRecord.from_mapping(
        dependency_id="pool-a",
        generation="g2",
        available_at_ms=300,
        payload={"reserve": "20"},
        slot=20,
    )
    frame = build_state_frame(
        (old, future),
        required_dependencies=("pool-a",),
        decision_time_ms=200,
    )
    assert frame.records == (old,)

    broken = StateRecord.from_mapping(
        dependency_id="pool-a",
        generation="g3",
        available_at_ms=150,
        payload={"reserve": "15"},
        slot=15,
        gap_affected=True,
    )
    with pytest.raises(Agg02Error, match="AGG02_GAP_AFFECTED_STATE_IN_FRAME"):
        build_state_frame(
            (broken,),
            required_dependencies=("pool-a",),
            decision_time_ms=200,
        )


def _graph() -> tuple[ExecutableGraph, RouteDefinition, RouteDefinition]:
    asset_a = AssetIdentity("solana", "mint-a", "spl", 6)
    asset_b = AssetIdentity("solana", "mint-b", "spl", 6)
    assets = {asset_a.asset_id: asset_a, asset_b.asset_id: asset_b}
    edge_a = OperationEdge(
        edge_id="edge-a",
        kind="swap",
        input_asset_ids=(asset_a.asset_id,),
        output_asset_ids=(asset_b.asset_id,),
        dependency_ids=("pool-a", "fee-a"),
        write_resources=("pool-a",),
        economic_resources=("reserve-a",),
    )
    edge_b = OperationEdge(
        edge_id="edge-b",
        kind="swap",
        input_asset_ids=(asset_b.asset_id,),
        output_asset_ids=(asset_a.asset_id,),
        dependency_ids=("pool-b",),
        write_resources=("pool-b",),
        economic_resources=("reserve-a",),
    )
    graph = ExecutableGraph(
        assets=assets,
        edges={"edge-a": edge_a, "edge-b": edge_b},
        generation="g1",
    )
    return (
        graph,
        RouteDefinition("route-a", ("edge-a",)),
        RouteDefinition("route-b", ("edge-b",)),
    )


def test_market_graph_tracks_affected_routes_and_shared_resources() -> None:
    graph, route_a, route_b = _graph()
    index = AffectedRouteIndex(graph, (route_a, route_b))
    assert index.affected_by(("fee-a",)) == ("route-a",)
    assert routes_conflict(
        route_resource_footprint(graph, route_a),
        route_resource_footprint(graph, route_b),
    )


def test_capacity_fee_and_lineage_contracts_fail_closed() -> None:
    surface = CapacitySurface(
        edge_id="edge-a",
        state_frame_hash=HASH_A,
        points=(
            CapacityPoint(1, 1, True),
            CapacityPoint(2, None, False),
        ),
    )
    assert surface.points[1].feasible is False

    with pytest.raises(Agg02Error, match="AGG02_UNKNOWN_FEE_BLOCKS_ADMISSION"):
        FeeSurface(
            edge_id="edge-a",
            components=(FeeComponent("network", "SOL", None, False, "g1"),),
        )

    root = EvidenceNode("raw", "raw", HASH_A)
    frame = EvidenceNode("frame", "frame", HASH_B, ("raw",))
    dag = EvidenceLineageDAG((root, frame))
    assert dag.ancestors("frame") == ("raw",)


def test_read_only_capital_budget_uses_exact_lamports_and_reservations() -> None:
    unknown = observe_budget_envelope(
        snapshot=None,
        active_reserved_lamports=0,
        native_fee_floor_lamports=5_000,
        peak_rent_lamports=10_000,
        now_ns=100,
        max_snapshot_age_ns=10,
    )
    assert unknown.effect_allowed is False
    assert unknown.reason == "unknown_balance"

    snapshot = WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=100_000,
        context_slot=123,
        captured_at_ns=100,
        cluster_genesis="mainnet-beta",
    )
    envelope = observe_budget_envelope(
        snapshot=snapshot,
        active_reserved_lamports=40_000,
        native_fee_floor_lamports=5_000,
        peak_rent_lamports=50_000,
        now_ns=105,
        max_snapshot_age_ns=10,
        expected_genesis="mainnet-beta",
    )
    assert envelope.free_native_lamports == 60_000
    assert envelope.effect_allowed is True


def test_program_token_admission_and_market_scheduler_are_conservative() -> None:
    observation = ProgramTokenObservation(
        program_id="program-a",
        program_hash=HASH_A,
        mint_id="mint-a",
        mint_owner_program="spl-token",
        extensions=("transfer-fee",),
        destinations=("vault-a",),
    )
    denied = admit_program_token_interaction(
        observation,
        allowed_program_hashes={"program-a": HASH_A},
        allowed_token_programs=("spl-token",),
        allowed_extensions=(),
        allowed_destinations=("vault-a",),
    )
    assert denied.accepted is False
    assert denied.reason == "unknown_token_extension"

    selected = schedule_market_universe(
        (
            UniverseCandidate("a", 10, 5, 100, True),
            UniverseCandidate("b", 8, 2, 100, True),
            UniverseCandidate("untrusted", 100, 1, 100, False),
        ),
        max_source_cost_units=5,
    )
    assert selected == ("b",)
