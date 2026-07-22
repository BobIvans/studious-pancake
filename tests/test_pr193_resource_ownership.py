from __future__ import annotations

import gc
from pathlib import Path

import pytest

import src.execution.live_control_resources_pr193 as live_resources_module
from src.execution.journal import SQLiteAttemptJournal
from src.execution.live_control_resources_pr193 import (
    ClosableLiveControlStore,
    LiveControlResources,
)
from src.resource_ownership_pr193 import (
    ResourceGraph,
    ResourceOwnership,
    ResourceOwnershipError,
)


class SyncResource:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self.closed = closed

    def close(self) -> None:
        self.closed.append(self.name)


class AsyncResource:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self.closed = closed

    async def aclose(self) -> None:
        self.closed.append(self.name)


def test_graph_closes_owned_resources_in_reverse_order() -> None:
    closed: list[str] = []
    graph = ResourceGraph(generation=7)
    graph.register(SyncResource("first", closed), resource_id="first", kind="test")
    graph.register(SyncResource("second", closed), resource_id="second", kind="test")

    graph.close()
    graph.close()

    assert closed == ["second", "first"]
    assert all(item["state"] == "closed" for item in graph.health())


def test_borrowed_resource_is_never_closed() -> None:
    closed: list[str] = []
    graph = ResourceGraph()
    graph.register(
        SyncResource("borrowed", closed),
        resource_id="borrowed",
        kind="test",
        ownership=ResourceOwnership.BORROWED,
    )

    graph.close()

    assert closed == []


def test_same_object_cannot_have_two_owned_registrations() -> None:
    graph = ResourceGraph()
    resource = SyncResource("one", [])
    graph.register(resource, resource_id="one", kind="test")

    with pytest.raises(ResourceOwnershipError):
        graph.register(resource, resource_id="two", kind="test")


@pytest.mark.asyncio
async def test_async_graph_closes_mixed_resources_in_reverse_order() -> None:
    closed: list[str] = []
    graph = ResourceGraph()
    graph.register(SyncResource("sync", closed), resource_id="sync", kind="test")
    graph.register(AsyncResource("async", closed), resource_id="async", kind="test")

    await graph.aclose()

    assert closed == ["async", "sync"]


def test_live_control_resources_close_both_sqlite_owners(tmp_path: Path) -> None:
    resources = LiveControlResources.open(tmp_path / "state.sqlite", generation=3)
    resources.store.latch("test")

    resources.close()
    resources.close()

    assert resources.closed is True
    assert resources.store.closed is True
    assert resources.journal.closed is True


def test_borrowed_live_control_store_is_not_closed(tmp_path: Path) -> None:
    store = ClosableLiveControlStore(tmp_path / "borrowed.sqlite")
    journal_resources = LiveControlResources.open(tmp_path / "owned.sqlite")
    resources = LiveControlResources.compose(
        store=store,
        journal=journal_resources.journal,
        store_ownership=ResourceOwnership.BORROWED,
        journal_ownership=ResourceOwnership.BORROWED,
    )

    resources.close()

    assert store.closed is False
    assert journal_resources.journal.closed is False
    store.close()
    journal_resources.close()


def test_failed_start_closes_already_opened_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[SQLiteAttemptJournal] = []

    class TrackingJournal(SQLiteAttemptJournal):
        def __init__(self, path: str | Path) -> None:
            super().__init__(path)
            opened.append(self)

    class FailingStore:
        def __init__(self, path: str | Path) -> None:
            raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(live_resources_module, "SQLiteAttemptJournal", TrackingJournal)
    monkeypatch.setattr(live_resources_module, "ClosableLiveControlStore", FailingStore)

    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        LiveControlResources.open(tmp_path / "failed-start.sqlite")

    assert len(opened) == 1
    assert opened[0].closed is True


def _fd_count() -> int | None:
    proc_fd = Path("/proc/self/fd")
    if not proc_fd.exists():
        return None
    return len(tuple(proc_fd.iterdir()))


def test_repeated_live_control_open_close_has_no_fd_growth(tmp_path: Path) -> None:
    before = _fd_count()
    if before is None:
        pytest.skip("/proc/self/fd is unavailable")

    for index in range(40):
        with LiveControlResources.open(tmp_path / f"state-{index}.sqlite"):
            pass
    gc.collect()

    after = _fd_count()
    assert after is not None
    assert after - before <= 3
