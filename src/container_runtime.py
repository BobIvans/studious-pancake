"""O1 authenticated container management and signed runtime truth.

The container remains fail-closed and starts no detector, RPC client, signer,
simulator or sender.  The active management listener now consumes a MACed,
generation-fenced runtime snapshot and exposes PR-174 canonical readiness as the
only readiness authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import tempfile
import time
from typing import Any, Sequence

from src.canonical_readiness import (
    BlockingMode,
    EvidenceState,
    ImplementationState,
    RequirementRecord,
    evaluate_canonical_readiness,
)
from src.observability.active_management import (
    ActiveManagementHttpServer,
    SignedRuntimeStateProvider,
)
from src.observability.health import (
    DEFAULT_HEALTH_HOST,
    DEFAULT_HEALTH_PORT,
    DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
    DependencyState,
    check_http_health,
)
from src.observability.management_plane_pr170 import (
    ManagementPlanePolicy,
    PR170_STATE_SCHEMA,
    RuntimeTruth,
    read_signed_state_snapshot,
    write_signed_state_snapshot,
)

DEFAULT_STATE_FILE = "/tmp/flashloan-bot-runtime.json"
STATE_SCHEMA = "o1.container-runtime.v1"
MAX_HEARTBEAT_AGE_SECONDS = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS
HEARTBEAT_INTERVAL_SECONDS = 5.0


def _state_path(value: str | os.PathLike[str] | None = None) -> Path:
    configured = value or os.environ.get("FLASHLOAN_RUNTIME_STATE_PATH")
    return Path(configured or DEFAULT_STATE_FILE)


def _capability_digest(matrix: Any) -> str:
    raw = json.dumps(matrix.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_owner_only_secret(
    path_value: str | None, *, text: bool
) -> bytes | str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("management secret path must be a regular file")
    stat_result = path.stat()
    if stat_result.st_mode & 0o077:
        raise ValueError("management secret file must be owner-only")
    if stat_result.st_nlink != 1:
        raise ValueError("management secret file must not be hardlinked")
    raw = path.read_bytes()
    if not raw or len(raw) > 4096:
        raise ValueError("management secret file has invalid size")
    if text:
        value = raw.decode("utf-8").strip()
        if not value:
            raise ValueError("management bearer token is empty")
        return value
    return raw


def _require_sha256(value: str, field: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase sha256")
    return value


def _unlink_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _companion_state_key_path(state_path: Path) -> Path:
    return state_path.with_name(f".{state_path.name}.key")


def _write_owner_only_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            signal.signal(sig, lambda *_: stop_event.set())


def _dependency(
    *,
    name: str,
    kind: str,
    state: DependencyState,
    critical: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "state": state.value,
        "critical": critical,
        "reason": reason,
        "updated_at_unix_ns": time.time_ns(),
        "labels": {},
    }


def _safe_idle_readiness(*, release_id: str) -> dict[str, Any]:
    requirement = RequirementRecord(
        domain_id="runtime.paper",
        title="Canonical sender-free paper runtime",
        owner_module="src.paper_shadow.composition",
        blocking_mode=BlockingMode.P0_BLOCKS_PAPER_AND_LIVE,
        implementation_state=ImplementationState.INTEGRATED_DISABLED,
        evidence_state=EvidenceState.MISSING,
        evidence_producer="src.paper_shadow.runner",
        evidence_verifier="src.canonical_readiness",
        architecture=None,
        package=None,
        blockers=("O1_SAFE_IDLE_EXECUTION_DISABLED",),
    )
    return evaluate_canonical_readiness(
        (requirement,),
        evaluated_release=release_id,
    ).to_dict()


def _signed_runtime_payload(
    *,
    base: dict[str, Any],
    process_boot_id: str,
    release_id: str,
    runtime_generation: int,
    policy_bundle_hash: str,
    heartbeat_sequence: int,
) -> tuple[RuntimeTruth, dict[str, Any]]:
    truth = RuntimeTruth(
        process_boot_id=process_boot_id,
        release_id=release_id,
        runtime_generation=runtime_generation,
        policy_bundle_hash=policy_bundle_hash,
        heartbeat_sequence=heartbeat_sequence,
        active_task_generation=0,
        live_enabled=False,
        trading_enabled=False,
    )
    extra = {
        **base,
        "heartbeat_unix_ns": time.time_ns(),
        "canonical_readiness": _safe_idle_readiness(release_id=release_id),
    }
    return truth, extra


async def run_safe_idle(
    matrix: Any,
    app: Any,
    *,
    state_file: str | None = None,
    health_host: str | None = None,
    health_port: int | None = None,
) -> int:
    """Validate the runtime contract, expose authenticated management, then idle."""

    app.validate()
    errors = tuple(app.capability_errors())
    if errors:
        for error in errors:
            print(f"CONFIGURATION_ERROR: {error}", file=sys.stderr)
        return 2

    path = _state_path(state_file)
    host = health_host or os.environ.get("FLASHLOAN_HEALTH_HOST") or DEFAULT_HEALTH_HOST
    port = int(
        health_port
        if health_port is not None
        else os.environ.get("FLASHLOAN_HEALTH_PORT") or DEFAULT_HEALTH_PORT
    )
    capability_digest = _capability_digest(matrix)
    policy_bundle_hash = _require_sha256(
        os.environ.get("FLASHLOAN_POLICY_BUNDLE_HASH") or capability_digest,
        "FLASHLOAN_POLICY_BUNDLE_HASH",
    )
    release_id = os.environ.get("FLASHLOAN_RELEASE_ID") or (
        f"development-{capability_digest[:12]}"
    )
    runtime_generation = int(os.environ.get("FLASHLOAN_RUNTIME_GENERATION") or "1")
    if runtime_generation < 1:
        raise ValueError("FLASHLOAN_RUNTIME_GENERATION must be positive")

    configured_state_key = _read_owner_only_secret(
        os.environ.get("FLASHLOAN_MANAGEMENT_STATE_KEY_FILE"),
        text=False,
    )
    companion_key_path: Path | None = None
    if isinstance(configured_state_key, bytes):
        signing_key = configured_state_key
    else:
        signing_key = secrets.token_bytes(32)
        companion_key_path = _companion_state_key_path(path)
        _unlink_state(companion_key_path)
        _write_owner_only_bytes(companion_key_path, signing_key)
    configured_token = _read_owner_only_secret(
        os.environ.get("FLASHLOAN_MANAGEMENT_BEARER_TOKEN_FILE"),
        text=True,
    )
    bearer_token = configured_token if isinstance(configured_token, str) else None
    token_digest = (
        hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()
        if bearer_token is not None
        else None
    )
    authenticated_proxy = (
        os.environ.get("FLASHLOAN_MANAGEMENT_AUTHENTICATED_PROXY", "false").lower()
        == "true"
    )
    policy = ManagementPlanePolicy(
        bind_host=host,
        bearer_token_sha256=token_digest,
        authenticated_proxy=authenticated_proxy,
        release_id=release_id,
        runtime_generation=runtime_generation,
        policy_bundle_hash=policy_bundle_hash,
    )

    stop_event = asyncio.Event()
    _install_stop_handlers(stop_event)
    process_boot_id = secrets.token_hex(16)
    base = {
        "schema_version": STATE_SCHEMA,
        "pid": os.getpid(),
        "started_at_unix_ns": time.time_ns(),
        "mode": "disabled",
        "diagnostic": "SAFE_IDLE_NO_EXECUTION",
        "product_state": matrix.product_state,
        "capability_sha256": capability_digest,
        "dependencies": [
            _dependency(
                name="runtime_contract",
                kind="runtime",
                state=DependencyState.OK,
                critical=True,
                reason="capability contract valid",
            ),
            _dependency(
                name="execution_pipeline",
                kind="runtime",
                state=DependencyState.DISABLED,
                critical=True,
                reason=(
                    "safe idle: detector, route planner, final simulation, "
                    "signing and submission are not active"
                ),
            ),
            _dependency(
                name="rpc",
                kind="provider",
                state=DependencyState.DISABLED,
                critical=True,
                reason="no RPC dependency is opened by the container supervisor",
            ),
        ],
    }

    _unlink_state(path)
    state_provider = SignedRuntimeStateProvider(
        path=path,
        signing_key=signing_key,
        minimum_generation=runtime_generation,
        expected_policy_bundle_hash=policy_bundle_hash,
    )
    server = ActiveManagementHttpServer(
        state_provider,
        policy=policy,
        max_heartbeat_age_seconds=MAX_HEARTBEAT_AGE_SECONDS,
    )
    heartbeat_sequence = 0
    try:
        await server.start(port=port)
        truth, extra = _signed_runtime_payload(
            base=base,
            process_boot_id=process_boot_id,
            release_id=release_id,
            runtime_generation=runtime_generation,
            policy_bundle_hash=policy_bundle_hash,
            heartbeat_sequence=heartbeat_sequence,
        )
        write_signed_state_snapshot(path, truth, signing_key, extra=extra)
        print(
            json.dumps(
                {
                    "event": "container_safe_idle_started",
                    "health_url": f"{server.base_url}/health",
                    "ready_url": f"{server.base_url}/ready",
                    "status_url": f"{server.base_url}/status",
                    "mode": "disabled",
                    "live_enabled": False,
                    "submitted": False,
                    "management_auth_configured": bearer_token is not None,
                    "runtime_generation": runtime_generation,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        while not stop_event.is_set():
            heartbeat_sequence += 1
            truth, extra = _signed_runtime_payload(
                base=base,
                process_boot_id=process_boot_id,
                release_id=release_id,
                runtime_generation=runtime_generation,
                policy_bundle_hash=policy_bundle_hash,
                heartbeat_sequence=heartbeat_sequence,
            )
            write_signed_state_snapshot(path, truth, signing_key, extra=extra)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                continue
    finally:
        await server.stop()
        _unlink_state(path)
        if companion_key_path is not None:
            _unlink_state(companion_key_path)
    return 0


def check_process_health(
    state_file: str | os.PathLike[str] | None = None,
    *,
    now_ns: int | None = None,
    max_age_seconds: float = MAX_HEARTBEAT_AGE_SECONDS,
) -> tuple[bool, str]:
    path = _state_path(state_file)
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, f"state file missing: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"state file unreadable: {exc}"

    if wrapper.get("schema_version") == PR170_STATE_SCHEMA:
        configured_key_path = os.environ.get("FLASHLOAN_MANAGEMENT_STATE_KEY_FILE")
        if configured_key_path is None:
            companion = _companion_state_key_path(path)
            configured_key_path = str(companion) if companion.is_file() else None
        key = _read_owner_only_secret(configured_key_path, text=False)
        if not isinstance(key, bytes):
            return (
                False,
                "signed state requires the configured management key or HTTP probe",
            )
        payload = wrapper.get("payload")
        if not isinstance(payload, dict):
            return False, "signed state payload is invalid"
        try:
            minimum_generation = int(payload.get("runtime_generation", -1))
            policy_hash = str(payload.get("policy_bundle_hash", ""))
        except (TypeError, ValueError):
            return False, "signed state generation or policy is invalid"
        validation = read_signed_state_snapshot(
            path,
            key,
            minimum_generation=minimum_generation,
            expected_policy_bundle_hash=policy_hash,
        )
        if not validation.ok or validation.payload is None:
            reason = (
                validation.reason.value if validation.reason is not None else "invalid"
            )
            return False, f"signed state validation failed: {reason}"
        payload = dict(validation.payload)
    else:
        payload = wrapper

    if payload.get("schema_version") not in {
        STATE_SCHEMA,
        "pr042.container-runtime.v1",
        "pr025.container-runtime.v1",
    }:
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
    return True, "healthy: signed safe-idle process heartbeat is current"


def healthcheck_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flashloan-bot-healthcheck",
        description="O1 local HTTP health probe with signed-state fallback.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("FLASHLOAN_HEALTH_URL"),
        help="HTTP health URL, normally http://127.0.0.1:8080/health",
    )
    parser.add_argument("--state-file", default=None)
    parser.add_argument(
        "--max-age-seconds", type=float, default=MAX_HEARTBEAT_AGE_SECONDS
    )
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.url:
        healthy, detail = check_http_health(args.url, timeout=args.timeout)
    else:
        healthy, detail = check_process_health(
            args.state_file, max_age_seconds=args.max_age_seconds
        )
    print(detail)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(healthcheck_main())
