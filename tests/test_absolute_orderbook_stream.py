import pytest
from src.providers.orderbook.models import L2Level, Side, OrderbookDepth
from src.providers.orderbook.stream_state import AbsoluteLevelBook, BookResyncRequired


def test_absolute_level_updates_replace_remove_and_gap_blocks_frames():
    book = AbsoluteLevelBook()
    book.install_snapshot(
        generation="session1",
        sequence=10,
        depth=OrderbookDepth((L2Level(Side.BID, 10, 7),), ()),
    )
    updated = book.update(
        generation="session1", sequence=11, absolute_levels=(L2Level(Side.BID, 10, 3),)
    )
    assert updated.depth.bids[0].base_lots == 3
    removed = book.update(
        generation="session1", sequence=12, absolute_levels=(L2Level(Side.BID, 10, 0),)
    )
    assert not removed.depth.bids
    with pytest.raises(BookResyncRequired):
        book.update(
            generation="session1",
            sequence=14,
            absolute_levels=(L2Level(Side.BID, 10, 5),),
        )
    with pytest.raises(BookResyncRequired):
        book.frame()
    restored = book.install_snapshot(
        generation="session2",
        sequence=20,
        depth=OrderbookDepth((L2Level(Side.BID, 10, 2),), ()),
    )
    fresh = AbsoluteLevelBook().install_snapshot(
        generation="session2", sequence=20, depth=restored.depth
    )
    assert fresh.evidence_hash == restored.evidence_hash
    with pytest.raises(BookResyncRequired):
        book.update(generation="old", sequence=21, absolute_levels=())
