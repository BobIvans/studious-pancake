"""Backward-compatible wrapper for the installed ``flashloan-bot`` command."""
from __future__ import annotations

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
from src.cli_pr189 import main

if __name__ == "__main__":
    raise SystemExit(main())
