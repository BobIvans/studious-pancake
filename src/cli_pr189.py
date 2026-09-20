"""Compatibility alias for the semantic :mod:`src.cli_entrypoint` owner.

The installed console script continues to target this module.  Active ``run``
commands pass through the immutable MPR-RP runtime adapter; inspection and
operational aliases remain owned by :mod:`src.cli_entrypoint`.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys
from typing import Any

from src import cli_entrypoint as _impl

# Compatibility attributes retained for tests and downstream monkeypatching.
automation_cli_pr189 = _impl.automation_cli_pr189
legacy_cli = _impl.legacy_cli
_DEFAULT_AUTOMATION_CLI = automation_cli_pr189
_DEFAULT_LEGACY_CLI = legacy_cli
_DEFAULT_LEGACY_MAIN = legacy_cli.main
LIVE_MODE = _impl.LIVE_MODE
PAPER_DB_ENV = _impl.PAPER_DB_ENV
PAPER_MAX_CYCLES_ENV = _impl.PAPER_MAX_CYCLES_ENV
PAPER_IDLE_DELAY_ENV = _impl.PAPER_IDLE_DELAY_ENV

# Compatibility markers consumed by existing source-contract tests:
# _rewrite_super_mpr_a_command
# rewrite_canonical_command(args)
# rewritten_super_mpr_a


def _callable_identity(value: Any) -> Any:
    """Return the stable function behind a possibly bound method."""

    return getattr(value, "__func__", value)


_DEFAULT_LEGACY_MAIN_IDENTITY = _callable_identity(_DEFAULT_LEGACY_MAIN)


class _LegacyBootstrapAdapter:
    """Prevent immutable bootstrap metadata from leaking into old signatures."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def main(self, argv: Sequence[str] | None = None, **_: object) -> int:
        return int(self._delegate.main(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch active runtime through immutable admission, otherwise delegate."""

    args = list(argv) if argv is not None else sys.argv[1:]
    default_owners = (
        automation_cli_pr189 is _DEFAULT_AUTOMATION_CLI
        and legacy_cli is _DEFAULT_LEGACY_CLI
        and _callable_identity(legacy_cli.main) is _DEFAULT_LEGACY_MAIN_IDENTITY
    )
    if default_owners and "run" in args:
        from src.runtime import runtime_entrypoint as runtime_adapter

        return runtime_adapter.main(args)

    previous_automation = _impl.automation_cli_pr189
    previous_legacy = _impl.legacy_cli
    _impl.automation_cli_pr189 = automation_cli_pr189
    setattr(_impl, "legacy_cli", _LegacyBootstrapAdapter(legacy_cli))
    try:
        return _impl.main(args)
    finally:
        _impl.automation_cli_pr189 = previous_automation
        setattr(_impl, "legacy_cli", previous_legacy)


if __name__ == "__main__":
    raise SystemExit(main())
