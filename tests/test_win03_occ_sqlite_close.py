"""WIN-03: OCCDurableLibrary must close every sqlite connection it opens.

Defect WINDOWS_SQLITE_TEMP_CLEANUP_PERMISSION: the sqlite3 connection
context manager commits/rolls back but never closes, so on Windows the OS
file handle survives until GC and TemporaryDirectory.cleanup() raises
PermissionError (WinError 32).  All connection sites now close explicitly
via contextlib.closing; these tests hold no fallback and no retry logic.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

import pytest

from src.occ_durable_library import OCCDurableLibrary, SourceVersion

pytestmark = pytest.mark.unit


def _exercise(
    library: OCCDurableLibrary,
) -> tuple[
    Mapping[str, Any], SourceVersion, SourceVersion, tuple[Mapping[str, Any], ...]
]:
    first = library.sync(
        namespace="local",
        source_id="fixture",
        content="payload",
        allowed_namespaces={"local"},
    )
    version = library.get_version(
        namespace="local",
        source_id="fixture",
        version_sha256=str(first["version_sha256"]),
        allowed_namespaces={"local"},
    )
    head = library.latest(
        namespace="local",
        source_id="fixture",
        allowed_namespaces={"local"},
    )
    history = library.history(
        namespace="local",
        source_id="fixture",
        allowed_namespaces={"local"},
    )
    return first, version, head, history


def test_temporary_directory_cleanup_after_full_use_releases_handles() -> None:
    for _ in range(3):
        td = tempfile.TemporaryDirectory()
        library = OCCDurableLibrary(Path(td.name) / "content.sqlite3")
        first, version, head, history = _exercise(library)
        assert first["duplicate"] is False
        assert version.version_sha256 == head.version_sha256
        assert len(history) == 1
        # Library object stays referenced; cleanup must not raise WinError 32.
        td.cleanup()


def test_read_methods_release_handles_immediately() -> None:
    base = Path(tempfile.mkdtemp())
    second_library = OCCDurableLibrary(base / "second.sqlite3")
    second_library.sync(
        namespace="local",
        source_id="other",
        content="payload",
        allowed_namespaces={"local"},
    )
    _exercise(second_library)
    # No gc.collect(): the file must be deletable as soon as the reads return.
    (base / "second.sqlite3").unlink()


def test_sync_history_round_trip_preserved() -> None:
    base = Path(tempfile.mkdtemp())
    library = OCCDurableLibrary(base / "content.sqlite3")
    first = library.sync(
        namespace="local",
        source_id="fixture",
        content="round-trip",
        allowed_namespaces={"local"},
    )
    second = library.sync(
        namespace="local",
        source_id="fixture",
        content="round-trip-2",
        allowed_namespaces={"local"},
    )
    history = library.history(
        namespace="local",
        source_id="fixture",
        allowed_namespaces={"local"},
    )
    assert first["event_seq"] == 1 and first["duplicate"] is False
    assert second["event_seq"] == 2
    assert [entry["outcome"] for entry in history] == ["CREATED", "UPDATED"]
    assert [entry["event_seq"] for entry in history] == [1, 2]
    (base / "content.sqlite3").unlink()
