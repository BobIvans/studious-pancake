"""Deprecated setup wrapper for the installed external-resource authority.

Legacy direct webhook mutation is intentionally removed.  The only supported
path is the sealed desired-state plan/apply/status/reconcile command.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from src.external_resources.cli import main as external_resources_main

_SUPPORTED = frozenset({"plan", "apply", "status", "reconcile"})


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] not in _SUPPORTED:
        print(
            "UNSUPPORTED_SOURCE_MUTATOR: use flashloan-external-resources "
            "plan/apply/status/reconcile with a sealed desired-state manifest.",
            file=sys.stderr,
        )
        return 2
    return external_resources_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
