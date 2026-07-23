"""Backward-compatible wrapper for the installed ``flashloan-bot`` command."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
import sys
from typing import cast

from src.cli import (  # re-exported for legacy import compatibility
    EXIT_CONFIGURATION_ERROR,
    EXIT_MODE_UNAVAILABLE,
    EXIT_NO_EXECUTABLE_STRATEGIES,
    EXIT_PAPER_SHADOW_BLOCKED,
    EXIT_PAPER_SHADOW_DEGRADED,
    EXIT_PAPER_SHADOW_FAILED,
    LauncherConfig,
    install_signal_handlers,
    load_configuration,
)

CANONICAL_MAIN_TARGET = "src.cli_pr189:main"
LEGACY_MAIN_TARGET = "src.cli:main"
LEGACY_PR023_COMMANDS = frozenset({"status", "capabilities"})


def _load_target(target_path: str) -> Callable[[Sequence[str] | None], int]:
    module_name, attr_name = target_path.split(":", 1)
    target = getattr(import_module(module_name), attr_name)
    return cast(Callable[[Sequence[str] | None], int], target)


def _load_canonical_main() -> Callable[[Sequence[str] | None], int]:
    return _load_target(CANONICAL_MAIN_TARGET)


def _load_legacy_main() -> Callable[[Sequence[str] | None], int]:
    return _load_target(LEGACY_MAIN_TARGET)


def _first_command(args: Sequence[str]) -> str | None:
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--config-file":
            index += 2
            continue
        if item.startswith("--config-file="):
            index += 1
            continue
        return item
    return None


def _requires_legacy_pr023_surface(args: Sequence[str]) -> bool:
    command = _first_command(args)
    # ``arb_bot.py`` remains the PR-023 compatibility wrapper.  The installed
    # ``flashloan-bot`` entrypoint stays dependency-light through src.cli_pr189,
    # while legacy tests and operators that import/call arb_bot keep the exact
    # runtime-truth surface: no default executable strategies and the original
    # status/capabilities JSON contract.
    return command is None or command in LEGACY_PR023_COMMANDS


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if _requires_legacy_pr023_surface(args):
        return _load_legacy_main()(args)
    return _load_canonical_main()(args)


if __name__ == "__main__":
    raise SystemExit(main())
