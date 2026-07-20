"""PR-042 dependency-aware health, readiness, status and metrics surfaces.

The module is deliberately standard-library only so the production container can
serve local health endpoints without installing the optional service extra.  It
does not call RPC, providers, signers, simulators or senders.  It only exposes
the already-declared runtime state and dependency gates in a redacted,
machine-readable format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping
from urllib import error, request

from .redaction import sanitize

HEALTH_SCHEMA = "pr042.health.v1"
READINESS_SCHEMA = "pr042.readiness.v1"
STATUS_SCHEMA = "pr042.status.v1"
METRICS_SCHEMA = "pr042.metrics.v1"
DEFAULT_HEALTH_HOST = "127.0.0.1"
DEFAULT_HEALTH_PORT = 8080
DEFAULT_HTTP_TIMEOUT_SECONDS = 2.0
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 20.0


class DependencyState(StrEnum):
    """Stable PR-042 dependency state taxonomy."""

    OK = "ok"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    """One redaction-safe dependency/readiness row."""

    name: str
    kind: str
    state: DependencyState
    critical: bool
    reason: str
    updated_at_unix_ns: int
    latency_ms: int | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "kind": self.kind,
            "state": self.state.value,
            "critical": self.critical,
            "reason": self.reason,
            "updated_at_unix_ns": self.updated_at_unix_ns,
            "latency_ms": self.latency_ms,
            "labels": dict(self.labels),
        }
        return sanitize(payload)


@dataclass(frozen=True, slots=True)
class RuntimeHttpConfig:
    """Local-only HTTP surface configuration for the fail-closed container."""

    host: str = DEFAULT_HEALTH_HOST
    port: int = DEFAULT_HEALTH_PORT

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _now_ns() -> int:
    return time.time_ns()


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )


def _coerce_state(value: object) -> DependencyState:
    if isinstance(value, DependencyState):
        return value
    try:
        return DependencyState(str(value))
    except ValueError:
        return DependencyState.UNKNOWN


def dependency_from_mapping(
    item: Mapping[str, Any], *, now_ns: int | None = None
) -> DependencyStatus:
    """Load a dependency row from persisted runtime state."""

    return DependencyStatus(
        name=str(item.get("name") or "unknown"),
        kind=str(item.get("kind") or "runtime"),
        state=_coerce_state(item.get("state") or DependencyState.UNKNOWN.value),
        critical=bool(item.get("critical", True)),
        reason=str(item.get("reason") or ""),
        updated_at_unix_ns=int(item.get("updated_at_unix_ns") or now_ns or _now_ns()),
        latency_ms=(
            int(item["latency_ms"])
            if item.get("latency_ms") is not None
            else None
        ),
        labels={
            str(key): str(value) for key, value in dict(item.get("labels") or {}).items()
        },
    )


def dependencies_from_state(
    state: Mapping[str, Any], *, now_ns: int | None = None
) -> tuple[DependencyStatus, ...]:
    """Derive dependency readiness rows from the safe-idle runtime state."""

    now = now_ns or _now_ns()
    configured = state.get("dependencies")
    if isinstance(configured, list):
        return tuple(
            dependency_from_mapping(item, now_ns=now)
            for item in configured
            if isinstance(item, Mapping)
        )

    diagnostic = str(state.get("diagnostic") or "UNKNOWN")
    mode = str(state.get("mode") or "unknown")
    product_state = str(state.get("product_state") or "unknown")
    runtime_state = (
        DependencyState.OK
        if diagnostic in {"SAFE_IDLE_NO_EXECUTION", "READY_FOR_DECLARED_MODE"}
        else DependencyState.UNKNOWN
    )
    pipeline_state = (
        DependencyState.DISABLED if mode == "disabled" else DependencyState.UNKNOWN
    )
    return (
        DependencyStatus(
            name="runtime_contract",
            kind="runtime",
            state=runtime_state,
            critical=True,
            reason=f"diagnostic={diagnostic}; product_state={product_state}",
            updated_at_unix_ns=now,
        ),
        DependencyStatus(
            name="execution_pipeline",
            kind="runtime",
            state=pipeline_state,
            critical=True,
            reason=(
                "safe idle: no detector, RPC, simulation, signer or sender task "
                "is active"
            ),
            updated_at_unix_ns=now,
        ),
    )


def heartbeat_dependency(
    state: Mapping[str, Any],
    *,
    now_ns: int | None = None,
    max_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> DependencyStatus:
    """Classify the process heartbeat as a dependency row."""

    now = now_ns or _now_ns()
    try:
        heartbeat_ns = int(state["heartbeat_unix_ns"])
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        return DependencyStatus(
            name="process_heartbeat",
            kind="runtime",
            state=DependencyState.UNAVAILABLE,
            critical=True,
            reason="state payload has invalid pid or heartbeat",
            updated_at_unix_ns=now,
        )

    age_seconds = (now - heartbeat_ns) / 1_000_000_000
    if pid <= 0:
        state_value = DependencyState.UNAVAILABLE
        reason = "runtime pid is invalid"
    elif age_seconds < -1.0:
        state_value = DependencyState.UNAVAILABLE
        reason = "heartbeat timestamp is in the future"
    elif age_seconds > max_age_seconds:
        state_value = DependencyState.UNAVAILABLE
        reason = f"heartbeat stale: {age_seconds:.3f}s"
    else:
        state_value = DependencyState.OK
        reason = "safe-idle heartbeat is current"
    return DependencyStatus(
        name="process_heartbeat",
        kind="runtime",
        state=state_value,
        critical=True,
        reason=reason,
        updated_at_unix_ns=now,
        latency_ms=max(0, int(age_seconds * 1000)),
        labels={"pid": str(pid)},
    )


def _critical_blockers(
    dependencies: tuple[DependencyStatus, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{item.name}:{item.state.value}:{item.reason}"
        for item in dependencies
        if item.critical and item.state is not DependencyState.OK
    )


def build_health_payload(
    state: Mapping[str, Any],
    *,
    now_ns: int | None = None,
    max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> dict[str, Any]:
    """Build `/health`: process liveness, not market readiness."""

    now = now_ns or _now_ns()
    heartbeat = heartbeat_dependency(
        state,
        now_ns=now,
        max_age_seconds=max_heartbeat_age_seconds,
    )
    ok = heartbeat.state is DependencyState.OK
    payload = {
        "schema_version": HEALTH_SCHEMA,
        "ok": ok,
        "status": "healthy" if ok else "unhealthy",
        "generated_at_unix_ns": now,
        "runtime": {
            "pid": state.get("pid"),
            "mode": state.get("mode"),
            "diagnostic": state.get("diagnostic"),
            "product_state": state.get("product_state"),
            "capability_sha256": state.get("capability_sha256"),
        },
        "dependencies": [heartbeat.to_dict()],
    }
    return sanitize(payload)


def build_readiness_payload(
    state: Mapping[str, Any],
    *,
    now_ns: int | None = None,
    max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> dict[str, Any]:
    """Build `/ready`: dependency-aware readiness and blocking reasons."""

    now = now_ns or _now_ns()
    dependencies = (
        heartbeat_dependency(
            state,
            now_ns=now,
            max_age_seconds=max_heartbeat_age_seconds,
        ),
        *dependencies_from_state(state, now_ns=now),
    )
    blockers = _critical_blockers(dependencies)
    ok = not blockers
    payload = {
        "schema_version": READINESS_SCHEMA,
        "ok": ok,
        "status": "ready" if ok else "not_ready",
        "generated_at_unix_ns": now,
        "reasons": list(blockers),
        "dependencies": [item.to_dict() for item in dependencies],
    }
    return sanitize(payload)


def build_status_payload(
    state: Mapping[str, Any],
    *,
    now_ns: int | None = None,
    max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> dict[str, Any]:
    """Build redacted `/status` for operators and diagnostics."""

    now = now_ns or _now_ns()
    health = build_health_payload(
        state,
        now_ns=now,
        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
    )
    readiness = build_readiness_payload(
        state,
        now_ns=now,
        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
    )
    payload = {
        "schema_version": STATUS_SCHEMA,
        "generated_at_unix_ns": now,
        "health": health,
        "readiness": readiness,
        "runtime": {
            "schema_version": state.get("schema_version"),
            "started_at_unix_ns": state.get("started_at_unix_ns"),
            "heartbeat_unix_ns": state.get("heartbeat_unix_ns"),
            "mode": state.get("mode"),
            "diagnostic": state.get("diagnostic"),
            "product_state": state.get("product_state"),
            "capability_sha256": state.get("capability_sha256"),
        },
        "safety": {
            "live_enabled": False,
            "submitted": False,
            "signing_enabled": False,
            "material_redaction": "enabled",
        },
    }
    return sanitize(payload)


def build_metrics_text(
    state: Mapping[str, Any],
    *,
    now_ns: int | None = None,
    max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> str:
    """Render a small Prometheus-compatible text payload."""

    now = now_ns or _now_ns()
    health = build_health_payload(
        state,
        now_ns=now,
        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
    )
    readiness = build_readiness_payload(
        state,
        now_ns=now,
        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
    )
    lines = [
        "# HELP flashloan_health_status 1 when local process health is OK.",
        "# TYPE flashloan_health_status gauge",
        f"flashloan_health_status {1 if health['ok'] else 0}",
        "# HELP flashloan_readiness_status 1 when all critical dependencies are ready.",
        "# TYPE flashloan_readiness_status gauge",
        f"flashloan_readiness_status {1 if readiness['ok'] else 0}",
        "# HELP flashloan_dependency_status Dependency state gauge by dependency.",
        "# TYPE flashloan_dependency_status gauge",
    ]
    for item in readiness["dependencies"]:
        value = 1 if item["state"] == DependencyState.OK.value else 0
        name = str(item["name"]).replace("\\", "\\\\").replace('"', '\\"')
        kind = str(item["kind"]).replace("\\", "\\\\").replace('"', '\\"')
        state_name = str(item["state"]).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            "flashloan_dependency_status{"
            f'dependency="{name}",kind="{kind}",state="{state_name}"'
            f"}} {value}"
        )
    return "\n".join(lines) + "\n"


class FileStateProvider:
    """Read a JSON runtime state file for every HTTP request."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def __call__(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))


def _send_json(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    payload: Mapping[str, Any],
) -> None:
    body = _json_dumps(payload).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_text(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    payload: str,
) -> None:
    body = payload.encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _handler_factory(
    state_provider: Callable[[], Mapping[str, Any]],
    *,
    max_heartbeat_age_seconds: float,
) -> type[BaseHTTPRequestHandler]:
    class RuntimeStatusHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            try:
                state = state_provider()
            except Exception as exc:
                payload = {
                    "schema_version": HEALTH_SCHEMA,
                    "ok": False,
                    "status": "unhealthy",
                    "reason": sanitize(exc),
                }
                _send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, payload)
                return

            if self.path == "/health":
                payload = build_health_payload(
                    state,
                    max_heartbeat_age_seconds=max_heartbeat_age_seconds,
                )
                status = HTTPStatus.OK if payload["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
                _send_json(self, status, payload)
                return
            if self.path == "/ready":
                payload = build_readiness_payload(
                    state,
                    max_heartbeat_age_seconds=max_heartbeat_age_seconds,
                )
                status = HTTPStatus.OK if payload["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
                _send_json(self, status, payload)
                return
            if self.path == "/status":
                payload = build_status_payload(
                    state,
                    max_heartbeat_age_seconds=max_heartbeat_age_seconds,
                )
                _send_json(self, HTTPStatus.OK, payload)
                return
            if self.path == "/metrics":
                _send_text(
                    self,
                    HTTPStatus.OK,
                    build_metrics_text(
                        state,
                        max_heartbeat_age_seconds=max_heartbeat_age_seconds,
                    ),
                )
                return
            _send_json(
                self,
                HTTPStatus.NOT_FOUND,
                {
                    "schema_version": STATUS_SCHEMA,
                    "ok": False,
                    "reason": "unknown endpoint",
                },
            )

    return RuntimeStatusHandler


class RuntimeStatusHttpServer:
    """Threaded local HTTP server for PR-042 health endpoints."""

    def __init__(
        self,
        state_provider: Callable[[], Mapping[str, Any]],
        *,
        host: str = DEFAULT_HEALTH_HOST,
        port: int = DEFAULT_HEALTH_PORT,
        max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
    ) -> None:
        handler = _handler_factory(
            state_provider,
            max_heartbeat_age_seconds=max_heartbeat_age_seconds,
        )
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="flashloan-pr042-health-http",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def host(self) -> str:
        return str(self._server.server_address[0])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "RuntimeStatusHttpServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def check_http_health(
    url: str,
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Small stdlib HTTP probe used by the Docker healthcheck."""

    try:
        with request.urlopen(url, timeout=timeout) as response:  # nosec B310
            raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
    except error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = str(exc)
        return False, f"http health probe failed: {exc.code} {detail}"
    except Exception as exc:
        return False, f"http health probe failed: {exc}"
    if payload.get("ok") is True:
        return True, "healthy: /health endpoint returned ok"
    return False, f"unhealthy: {payload.get('status') or payload.get('reason')}"
