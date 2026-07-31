"""Quarantined source alias for the installed ``flashloan-bot`` command.

This file intentionally owns no dispatch policy.  It exists for source-checkout
compatibility only and every invocation delegates to the canonical composition
root used by the installed console script.
"""

from __future__ import annotations

from src.cli import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_MODE_UNAVAILABLE,
    EXIT_NO_EXECUTABLE_STRATEGIES,
    EXIT_PAPER_SHADOW_BLOCKED,
    EXIT_PAPER_SHADOW_DEGRADED,
    EXIT_PAPER_SHADOW_FAILED,
    LauncherConfig,
    install_signal_handlers,
    load_configuration,
)  # re-exported for legacy import compatibility

CANONICAL_MAIN_TARGET = "src.cli_pr189:main"


def main(argv=None) -> int:
    from src.cli_pr189 import main as canonical_main

    return canonical_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
