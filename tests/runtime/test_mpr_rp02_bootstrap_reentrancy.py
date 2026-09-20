from __future__ import annotations

import logging
import os
from pathlib import Path

from src import cli_entrypoint
from src.runtime.bootstrap import BootstrapContext
from src.runtime.process_hooks import LoggingHandlerOwner


def test_bootstrap_environment_and_paths_are_immutable(tmp_path: Path) -> None:
    source = {
        "FLASHLOAN_RELEASE_ID": "release-a",
        "FLASHLOAN_PAPER_SERVICE_DB": "state/paper.sqlite3",
        "TZ": "UTC",
    }
    context = BootstrapContext.capture(
        ("run", "--mode", "paper"),
        command="flashloan-bot.run",
        environ=source,
        cwd=tmp_path,
        invocation_id="invocation-a",
    )
    source["FLASHLOAN_RELEASE_ID"] = "release-b"
    source["FLASHLOAN_PAPER_SERVICE_DB"] = "other.sqlite3"

    assert context.environment["FLASHLOAN_RELEASE_ID"] == "release-a"
    assert context.resolve_path("state/paper.sqlite3") == (
        tmp_path / "state/paper.sqlite3"
    ).resolve()


def test_repeated_cli_translation_does_not_mutate_os_environ(monkeypatch) -> None:
    calls: list[list[str]] = []

    class FakeLegacy:
        @staticmethod
        def main(argv):
            calls.append(list(argv))
            return 0

    monkeypatch.setattr(cli_entrypoint, "legacy_cli", FakeLegacy())
    before = dict(os.environ)

    assert (
        cli_entrypoint.main(
            ["run", "--mode", "paper", "--db-path", "first.sqlite3", "--json"]
        )
        == 0
    )
    assert cli_entrypoint.main(["run", "--mode", "paper"]) == 0

    assert dict(os.environ) == before
    assert calls == [
        ["run", "--mode", "paper"],
        ["run", "--mode", "paper"],
    ]


def test_logging_owner_restores_exact_root_state() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    for handler in original_handlers:
        root.removeHandler(handler)
    try:
        with LoggingHandlerOwner(level=logging.INFO):
            assert len(root.handlers) == 1
            assert root.level == logging.INFO
        assert root.handlers == []
        assert root.level == original_level
    finally:
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
