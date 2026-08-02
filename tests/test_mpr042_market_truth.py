from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.market import (
    CompletenessPolicy,
    CompletenessState,
    CorrectionKind,
    DerivedCacheKey,
    DurableCursorStore,
    FanoutMatrix,
    GenerationBoundCache,
    MarketObservationV2,
    ObservationBatch,
    ObservationError,
    ObservationGeneration,
    ObservationWatermark,
    SnapshotSet,
    SourceCursor,
    WatermarkedObservationBuffer,
)
from src.strategy.detectors import CircularArbitrageDetector, DetectorPair

pytestmark = pytest.mark.unit


def _observation(
    *,
    source: str = "jupiter",
    offset: int = 1,
    slot: int = 100,
    epoch: int = 0,
    input_mint: str = "A",
    output_mint: str = "B",
    expected: int = 120,
    guaranteed: int = 110,
    input_amount: int = 100,
    generation: ObservationGeneration | None = None,
    correction_kind: CorrectionKind = CorrectionKind.ORIGINAL,
    supersedes_id: str | None = None,
) -> MarketObservationV2:
    return MarketObservationV2(
        provider=source,
        input_mint=input_mint,
        output_mint=output_mint,
        input_amount=input_amount,
        expected_output=expected,
        guaranteed_output=guaranteed,
        slot=slot,
        root_slot=slot - 1,
        observed_at=1_700_000_000.0,
        expires_at=1_700_000_100.0,
        source=f"https://{source}.invalid/quote",
        confidence="provider-normalized",
        commitment="confirmed",
        request_fingerprint=f"request-{source}-{offset}",
        response_hash=f"response-{source}-{offset}",
        generation=generation or ObservationGeneration(code_generation="mpr042"),
        cursor=SourceCursor(source, "quotes", offset, slot, epoch),
        correction_kind=correction_kind,
        supersedes_id=supersedes_id,
    )


def test_detector_uses_guaranteed_not_optimistic_output() -> None:
    pair = DetectorPair(
        pair_id="a-b-loop",
        base_mint="A",
        intermediate_mint="B",
        probe_amount_base_units=100,
        min_gross_profit_base_units=1,
        max_snapshot_age_seconds=10,
        cooldown_seconds=0,
        max_slot_skew=0,
    )
    detector = CircularArbitrageDetector((pair,))
    batch = SnapshotSet(
        (
            _observation(expected=120, guaranteed=110),
            _observation(
                source="okx",
                input_mint="B",
                output_mint="A",
                input_amount=110,
                expected=105,
                guaranteed=99,
            ),
        )
    )

    assert detector.detect(batch, now=1_700_000_001.0) == ()
    assert detector.last_rejections[pair.pair_id].reason_code == (
        "below_min_gross_profit"
    )


def test_detector_rejects_non_admissible_batch_before_route_search() -> None:
    observation = _observation()
    watermark = ObservationWatermark((observation.cursor,), 100, 100, 0)
    policy = CompletenessPolicy(
        policy_id="two-source",
        required_sources=("jupiter", "okx"),
    )
    batch = ObservationBatch(
        (observation,),
        watermark=watermark,
        policy=policy,
    )
    detector = CircularArbitrageDetector(
        (
            DetectorPair(
                pair_id="a-b-loop",
                base_mint="A",
                intermediate_mint="B",
                probe_amount_base_units=100,
            ),
        )
    )

    assert batch.completeness is CompletenessState.BLOCKED
    assert detector.detect(batch, now=1_700_000_001.0) == ()
    rejection = detector.last_rejections["a-b-loop"]
    assert rejection.reason_code == "observation_batch_incomplete"
    assert rejection.details["batch_id"] == batch.batch_id


def test_reconnect_blocks_until_every_required_source_is_backfilled(
    tmp_path: Path,
) -> None:
    store = DurableCursorStore(tmp_path / "cursors.json")
    buffer = WatermarkedObservationBuffer(
        fanout=FanoutMatrix({"circular": ("jupiter", "okx")}),
        cursor_store=store,
    )
    epoch = buffer.begin_reconnect()
    buffer.ingest(_observation(source="jupiter", epoch=epoch))
    buffer.mark_backfill_complete("jupiter")

    blocked = buffer.publish("circular", max_slot_skew=0)
    assert blocked.completeness is CompletenessState.BLOCKED
    assert "backfill_pending:okx" in blocked.degraded_reasons

    buffer.ingest(_observation(source="okx", epoch=epoch, slot=100))
    buffer.mark_backfill_complete("okx")
    complete = buffer.publish("circular", max_slot_skew=0, minimum_observations=2)

    assert complete.completeness is CompletenessState.COMPLETE
    assert complete.watermark.reconnect_epoch == epoch
    assert DurableCursorStore(tmp_path / "cursors.json").load()


def test_restart_requires_explicit_backfill_even_with_durable_cursors(
    tmp_path: Path,
) -> None:
    store = DurableCursorStore(tmp_path / "cursors.json")
    fanout = FanoutMatrix({"circular": ("jupiter", "okx")})
    original = WatermarkedObservationBuffer(fanout=fanout, cursor_store=store)
    original.ingest(_observation(source="jupiter"))
    original.ingest(_observation(source="okx"))
    original.mark_backfill_complete("jupiter")
    original.mark_backfill_complete("okx")
    assert original.publish("circular", minimum_observations=2).admissible

    restarted = WatermarkedObservationBuffer(fanout=fanout, cursor_store=store)
    blocked = restarted.publish("circular", minimum_observations=2)

    assert blocked.completeness is CompletenessState.BLOCKED
    assert "backfill_pending:jupiter" in blocked.degraded_reasons
    assert "backfill_pending:okx" in blocked.degraded_reasons


def test_duplicate_is_dropped_and_reordered_cursor_fails_closed() -> None:
    buffer = WatermarkedObservationBuffer(
        fanout=FanoutMatrix({"circular": ("jupiter",)})
    )
    first = _observation(offset=2)
    assert buffer.ingest(first) is True
    assert buffer.ingest(first) is False

    with pytest.raises(ObservationError, match="moved backwards"):
        buffer.ingest(_observation(offset=1, slot=99))


def test_correction_replaces_superseded_observation() -> None:
    buffer = WatermarkedObservationBuffer(
        fanout=FanoutMatrix({"circular": ("jupiter",)})
    )
    original = _observation(offset=1)
    buffer.ingest(original)
    corrected = _observation(
        offset=2,
        expected=125,
        guaranteed=115,
        correction_kind=CorrectionKind.CORRECTION,
        supersedes_id=original.observation_id,
    )
    buffer.ingest(corrected)
    buffer.mark_backfill_complete("jupiter")

    assert buffer.publish("circular").active_observations() == (corrected,)


def test_cache_rejects_generation_and_provenance_drift() -> None:
    cache = GenerationBoundCache(max_entries=2, max_bytes=512)
    key = DerivedCacheKey("route", "A-B", "gen-1", "proof-1", "jupiter")
    cache.put_json(key, {"value": 1}, ttl_seconds=10)

    assert cache.get_json(key) == {"value": 1}
    assert (
        cache.get_json(DerivedCacheKey("route", "A-B", "gen-2", "proof-1", "jupiter"))
        is None
    )
    assert (
        cache.get_json(DerivedCacheKey("route", "A-B", "gen-1", "proof-2", "jupiter"))
        is None
    )
    assert cache.invalidate_generation("gen-1") == (key.identity,)


@pytest.mark.asyncio
async def test_cache_singleflight_is_cancellation_safe() -> None:
    cache = GenerationBoundCache()
    key = DerivedCacheKey("route", "A-B", "gen", "proof", "jupiter")
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"ok": True}

    first, second = await asyncio.gather(
        cache.get_or_compute(key, factory, ttl_seconds=10),
        cache.get_or_compute(key, factory, ttl_seconds=10),
    )

    assert first == second == {"ok": True}
    assert calls == 1
