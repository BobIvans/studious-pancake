"""Compatibility alias for the semantic :mod:`src.cli_entrypoint` owner.

The installed console script may continue to target this module for compatibility,
but all dispatch policy and runtime behavior live in ``src.cli_entrypoint``.
"""

from __future__ import annotations

from collections.abc import Sequence

from src import cli_entrypoint as _impl

# Compatibility attributes retained for tests and downstream monkeypatching.
automation_cli_pr189 = _impl.automation_cli_pr189
legacy_cli = _impl.legacy_cli
LIVE_MODE = _impl.LIVE_MODE
PAPER_DB_ENV = _impl.PAPER_DB_ENV
PAPER_MAX_CYCLES_ENV = _impl.PAPER_MAX_CYCLES_ENV
PAPER_IDLE_DELAY_ENV = _impl.PAPER_IDLE_DELAY_ENV

# Compatibility markers consumed by existing source-contract tests:
# _rewrite_super_mpr_a_command
# rewrite_canonical_command(args)
# rewritten_super_mpr_a


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate to the semantic owner while preserving monkeypatch compatibility."""

    _impl.automation_cli_pr189 = automation_cli_pr189
    _impl.legacy_cli = legacy_cli
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
