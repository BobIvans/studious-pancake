"""PR-192 hardened console entrypoint.

This wrapper applies process-memory controls before importing the canonical CLI,
which in turn loads configuration, resolves credentials, constructs clients and
starts the runtime. ``src.cli`` remains the single command implementation.
"""

from __future__ import annotations

from importlib import import_module
import json
import os
import sys
from types import ModuleType
from typing import Mapping, Sequence

from src.security.runtime_memory import (
    RuntimeMemoryHardeningError,
    RuntimeMemoryPolicy,
    RuntimeMemoryStatus,
    harden_process_memory,
)

EXIT_MEMORY_HARDENING_ERROR = 8
_REQUIRED_ENV = "FLASHLOAN_MEMORY_HARDENING_REQUIRED"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _requests_live(args: Sequence[str]) -> bool:
    return any(
        argument == "--mode"
        and index + 1 < len(args)
        and args[index + 1] == "live"
        for index, argument in enumerate(args)
    )


def _strict_required(args: Sequence[str], *, environ: Mapping[str, str]) -> bool:
    if _truthy(environ.get(_REQUIRED_ENV)):
        return True
    if args and args[0] == "container":
        return True
    return bool(args and args[0] == "run" and _requests_live(args))


def _policy_for(
    args: Sequence[str], *, environ: Mapping[str, str]
) -> RuntimeMemoryPolicy:
    if _strict_required(args, environ=environ):
        return RuntimeMemoryPolicy.production_default()
    linux = sys.platform.startswith("linux")
    return RuntimeMemoryPolicy(
        require_core_limit_zero=True,
        require_non_dumpable=linux,
        require_no_active_tracer=linux,
        require_linux=False,
    )


def _emit_verified(status: RuntimeMemoryStatus) -> None:
    payload = status.to_dict()
    payload.update(
        {
            "event": "runtime_memory_hardening_verified",
            "live_enabled": False,
            "secret_material_in_event": False,
        }
    )
    print(json.dumps(payload, sort_keys=True), flush=True)


def _load_canonical_cli() -> ModuleType:
    return import_module("src.cli")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else list(sys.argv[1:])
    environ = os.environ
    strict = _strict_required(args, environ=environ)
    try:
        status = harden_process_memory(policy=_policy_for(args, environ=environ))
    except RuntimeMemoryHardeningError as exc:
        print(f"MEMORY_HARDENING_ERROR: {exc}", file=sys.stderr)
        return EXIT_MEMORY_HARDENING_ERROR
    if strict:
        _emit_verified(status)
    canonical_cli = _load_canonical_cli()
    return int(canonical_cli.main(args))


if __name__ == "__main__":
    raise SystemExit(main())
