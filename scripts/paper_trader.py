#!/usr/bin/env python3
"""PR-038 thin wrapper for the supported paper/shadow runner.

The historical Jupiter quote-loop was quarantined by PR-023 because it was not a
canonical execution kernel.  Keeping this script as a tiny wrapper preserves the
operator entrypoint without allowing legacy paper accounting, fake fills or
independent route polling to bypass ``flashloan-bot``.
"""

from __future__ import annotations

from src.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["paper-shadow"]))
