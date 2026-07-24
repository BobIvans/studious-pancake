"""Backward-compatible wrapper for the installed ``flashloan-bot`` command."""
from __future__ import annotations

from importlib import import_module
import sys

from src.cli import EXIT_CONFIGURATION_ERROR, EXIT_MODE_UNAVAILABLE, EXIT_NO_EXECUTABLE_STRATEGIES, EXIT_PAPER_SHADOW_BLOCKED, EXIT_PAPER_SHADOW_DEGRADED, EXIT_PAPER_SHADOW_FAILED, LauncherConfig, install_signal_handlers, load_configuration  # re-exported for legacy import compatibility

CANONICAL_MAIN_TARGET = "src.cli_pr189:main"
LEGACY_MAIN_TARGET = "src.cli:main"
LEGACY_PR023_COMMANDS = frozenset({"status", "capabilities"})


def _load_target(target_path):
    module_name, attr_name = target_path.split(":", 1)
    return getattr(import_module(module_name), attr_name)


def _first_command(args):
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--config-file":
            index += 2
        elif item.startswith("--config-file="):
            index += 1
        else:
            return item
    return None


def main(argv=None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    command = _first_command(args)
    target = LEGACY_MAIN_TARGET if command is None or command in LEGACY_PR023_COMMANDS else CANONICAL_MAIN_TARGET
    return _load_target(target)(args)


if __name__ == "__main__":
    raise SystemExit(main())
