from dataclasses import replace
import pytest
from src.market.streams import RawStreamEvent, RecoverableStreamJournal
from src.market.observations import ObservationError


def event(cursor=1, **kw):
    return replace(
        RawStreamEvent(
            "s",
            "p",
            1,
            cursor,
            cursor * 10,
            cursor * 10 - 1,
            "market",
            "v1",
            '{"bid":10,"ask":20}',
            "b",
            "a",
        ),
        **kw,
    )


def test_crash_restart_dedup_correction_and_point_in_time(tmp_path):
    path = tmp_path / "raw.db"
    journal = RecoverableStreamJournal(path)
    first = event()
    assert journal.append(first)
    assert not journal.append(first)
    with pytest.raises(ObservationError, match="different payload"):
        journal.append(replace(first, payload_json='{"bid":99}'))
    journal.append(event(2, kind="delta", payload_json='{"bid":11,"ask":null}'))
    journal.close()
    journal = RecoverableStreamJournal(path)
    assert journal.reconstruct(source="s", partition="p", available_at_ns=10) == {
        "bid": 10,
        "ask": 20,
    }
    assert journal.reconstruct(source="s", partition="p", available_at_ns=20) == {
        "bid": 11
    }
    journal.append(
        event(3, kind="retraction", supersedes_hash=first.identity, payload_json="{}")
    )
    with pytest.raises(ObservationError, match="repaired snapshot"):
        journal.reconstruct(source="s", partition="p", available_at_ns=30)
    assert journal.reconstruct(source="s", partition="p", available_at_ns=20) == {
        "bid": 11
    }
    journal.append(event(4, payload_json='{"bid":12}'))
    assert journal.reconstruct(source="s", partition="p", available_at_ns=40) == {
        "bid": 12
    }
    journal.close()


def test_gaps_forks_reconnect_and_failed_write_do_not_advance_cursor(tmp_path):
    journal = RecoverableStreamJournal(tmp_path / "raw.db")
    journal.append(event())
    for bad in (
        event(3, kind="delta"),
        event(2, kind="delta", block_hash="fork", parent_hash="other"),
        event(2, kind="delta", generation=2),
    ):
        with pytest.raises(ObservationError, match="snapshot repair"):
            journal.append(bad)
    assert len(journal.events(available_at_ns=100)) == 1
    assert journal.append(event(2, kind="delta", payload_json='{"bid":11}'))
    assert journal.append(
        event(
            5,
            generation=2,
            block_hash="fork",
            parent_hash="other",
            payload_json='{"bid":99}',
        )
    )
    assert journal.reconstruct(source="s", partition="p", available_at_ns=50) == {
        "bid": 99
    }
    journal.close()


def test_storage_budget_blocks_new_events_but_allows_exact_dedup(tmp_path):
    journal = RecoverableStreamJournal(tmp_path / "bounded.db", max_events=1)
    assert journal.append(event())
    assert not journal.append(event())
    with pytest.raises(ObservationError, match="storage budget"):
        journal.append(event(2, kind="delta"))
    assert len(journal.events(available_at_ns=100)) == 1
    journal.close()
