"""Temporary PR-025 container liveness supervisor.

This module deliberately provides process liveness only. Dependency readiness,
market readiness and HTTP health endpoints belong to PR-042. The supervisor
starts no detector, RPC client, signer, simulator or sender.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Sequence

DEFAULT_STATE_FILE = "/tmp/flashloan-bot-runtime.json"
STATE_SCHEMA = "pr025.container-runtime.v1"
MAX_HEARTBEAT_AGE_SECONDS = 20.0
HEARTBEAT_INTERVAL_SECONDS = 5.0


def _state_path(value: str | os.PathLike[str] | None = None) -> Path:
    configured = value or os.environ.get("FLASHLOAN_RUNTIME_STATE_PATH")
    return Path(configured or DEFAULT_STATE_FILE)


def _capability_digest(matrix: Any) -> str:
    raw = json.dumps(matrix.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            signal.signal(sig, lambda *_: stop_event.set())


async def run_safe_idle(matrix: Any, app: Any, *, state_file: str | None = None) -> int:
    """Validate the declared runtime contract, then remain safely idle.

    No application strategy tasks are started. The heartbeat exists only so the
    Docker healthcheck can verify that the declared PID is alive until PR-042
    replaces it with dependency-aware health/readiness endpoints.
    """
    app.validate()
    errors = tuple(app.capability_errors())
    if errors:
        for error in errors:
            print(f"CONFIGURATION_ERROR: {error}", file=sys.stderr)
        return 2

    path = _state_path(state_file)
    stop_event = asyncio.Event()
    _install_stop_handlers(stop_event)
    base = {
        "schema_version": STATE_SCHEMA,
        "pid": os.getpid(),
        "started_at_unix_ns": time.time_ns(),
        "mode": "disabled",
        "diagnostic": "SAFE_IDLE_NO_EXECUTION",
        "product_state": matrix.product_state,
        "capability_sha256": _capability_digest(matrix),
    }
    print(
        "CONTAINER_SAFE_IDLE: capability contract valid; no detector, RPC, "
        "simulation, signing, or submission task was started.",
        flush=True,
    )
    try:
        while not stop_event.is_set():
            payload = dict(base)
            payload["heartbeat_unix_ns"] = time.time_ns()
            _write_state(path, payload)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                continue
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return 0


def check_process_health(
    state_file: str | os.PathLike[str] | None = None,
    *,
    now_ns: int | None = None,
    max_age_seconds: float = MAX_HEARTBEAT_AGE_SECONDS,
) -> tuple[bool, str]:
    path = _state_path(state_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, f"state file missing: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"state file unreadable: {exc}"

    if payload.get("schema_version") != STATE_SCHEMA:
        return False, "unexpected state schema"
    if payload.get("mode") != "disabled":
        return False, "container supervisor is not fail-closed disabled mode"
    try:
        pid = int(payload["pid"])
        heartbeat_ns = int(payload["heartbeat_unix_ns"])
    except (KeyError, TypeError, ValueError):
        return False, "state file has invalid pid or heartbeat"
    if pid <= 0:
        return False, "invalid runtime pid"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, f"runtime pid is not alive: {pid}"
    except PermissionError:
        pass
    age_seconds = ((now_ns or time.time_ns()) - heartbeat_ns) / 1_000_000_000
    if age_seconds < -1.0:
        return False, "heartbeat is unexpectedly in the future"
    if age_seconds > max_age_seconds:
        return False, f"heartbeat stale: {age_seconds:.3f}s"
    return True, "healthy: safe-idle process heartbeat is current"


def healthcheck_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flashloan-bot-healthcheck",
        description="Temporary PR-025 process-liveness probe; not readiness.",
    )
    parser.add_argument("--state-file", default=None)
    parser.add_argument(
        "--max-age-seconds", type=float, default=MAX_HEARTBEAT_AGE_SECONDS
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    healthy, detail = check_process_health(
        args.state_file, max_age_seconds=args.max_age_seconds
    )
    print(detail)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(healthcheck_main())
