"""Backward-compatible wrapper for the installed ``flashloan-bot`` command."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module
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


def _load_canonical_main() -> Callable[[Sequence[str] | None], int]:
    module_name, attr_name = CANONICAL_MAIN_TARGET.split(":", 1)
    target = getattr(import_module(module_name), attr_name)
    return cast(Callable[[Sequence[str] | None], int], target)


def main(argv: Sequence[str] | None = None) -> int:
    return _load_canonical_main()(argv)


if __name__ == "__main__":
    raise SystemExit(main())
