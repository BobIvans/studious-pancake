"""Active O1 authenticated management plane.

This module replaces the active ``http.server`` listener with a bounded aiohttp
service that consumes PR-170 signed, generation-fenced runtime truth.  Canonical
PR-174 readiness is the only source that may make ``/ready`` return success.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import errno
from http import HTTPStatus
import hashlib
import secrets
import json
from pathlib import Path
import time
from typing import Any

from aiohttp import web

from src.canonical_readiness import PR174_SCHEMA_VERSION
from src.observability.health import (
    DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
    build_health_payload,
)
from src.observability.management_plane_pr170 import (
    ManagementPlanePolicy,
    ManagementSurface,
    SnapshotErrorCode,
    SnapshotValidation,
    authorize_surface,
    build_ingress_limits,
    build_public_liveness_payload,
    read_signed_state_snapshot,
)
from src.observability.redaction import sanitize

O1_READINESS_SCHEMA = "o1.canonical-readiness-http.v1"
O1_STATUS_SCHEMA = "o1.management-status.v1"
O1_METRICS_SCHEMA = "o1.management-metrics.v1"


@dataclass(frozen=True, slots=True)
class SignedRuntimeStateProvider:
    path: Path
    signing_key: bytes
    minimum_generation: int
    expected_policy_bundle_hash: str

    def __call__(self) -> SnapshotValidation:
        return read_signed_state_snapshot(
            self.path,
            self.signing_key,
            minimum_generation=self.minimum_generation,
            expected_policy_bundle_hash=self.expected_policy_bundle_hash,
        )


@dataclass(frozen=True, slots=True)
class CanonicalReadinessValidation:
    ok: bool
    reason: str
    payload: Mapping[str, Any] | None


def validate_canonical_readiness_payload(value: object) -> CanonicalReadinessValidation:
    if not isinstance(value, Mapping):
        return CanonicalReadinessValidation(False, "CANONICAL_READINESS_MISSING", None)
    payload = dict(value)
    supplied_hash = payload.pop("state_hash", None)
    if payload.get("schema_version") != PR174_SCHEMA_VERSION:
        return CanonicalReadinessValidation(
            False, "CANONICAL_READINESS_SCHEMA_INVALID", None
        )
    if not isinstance(supplied_hash, str) or len(supplied_hash) != 64:
        return CanonicalReadinessValidation(
            False, "CANONICAL_READINESS_HASH_MISSING", None
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected_hash = hashlib.sha256(encoded).hexdigest()
    if not secrets.compare_digest(supplied_hash, expected_hash):
        return CanonicalReadinessValidation(
            False, "CANONICAL_READINESS_HASH_INVALID", None
        )
    bool_fields = ("paper_ready", "live_ready", "production_ready")
    if any(not isinstance(payload.get(name), bool) for name in bool_fields):
        return CanonicalReadinessValidation(
            False, "CANONICAL_READINESS_BOOLEAN_INVALID", None
        )
    payload["state_hash"] = supplied_hash
    return CanonicalReadinessValidation(True, "CANONICAL_READINESS_VERIFIED", payload)


def _bearer_token(request: web.Request) -> str | None:
    value = request.headers.get("Authorization")
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if separator != " " or scheme != "Bearer" or not token or " " in token:
        return None
    return token


class ActiveManagementHttpServer:
    """Bounded authenticated management service for the active container runtime."""

    def __init__(
        self,
        state_provider: Callable[[], SnapshotValidation],
        *,
        policy: ManagementPlanePolicy,
        max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.state_provider = state_provider
        self.policy = policy
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds
        self.clock_ns = clock_ns
        self.limits = build_ingress_limits(policy)
        self._connections = asyncio.Semaphore(policy.max_connections)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._host = policy.bind_host
        self._port = 0

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        host = (
            f"[{self.host}]"
            if ":" in self.host and not self.host.startswith("[")
            else self.host
        )
        return f"http://{host}:{self.port}"

    async def start(self, *, port: int) -> "ActiveManagementHttpServer":
        application = web.Application(client_max_size=1024)
        application.router.add_get("/health", self._health)
        application.router.add_get("/ready", self._ready)
        application.router.add_get("/status", self._status)
        application.router.add_get("/metrics", self._metrics)
        self._runner = web.AppRunner(
            application,
            access_log=None,
            keepalive_timeout=self.policy.request_timeout_seconds,
            shutdown_timeout=self.policy.request_timeout_seconds,
        )
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            host=self.policy.bind_host,
            port=port,
        )
        try:
            await self._site.start()
        except OSError as exc:
            await self.stop()
            if exc.errno == errno.EADDRINUSE:
                raise OSError(exc.errno, "Address already in use") from exc
            raise
        server = getattr(self._site, "_server", None)
        sockets = tuple(server.sockets or ()) if server is not None else ()
        if not sockets:
            await self.stop()
            raise RuntimeError("management server did not expose a listening socket")
        address = sockets[0].getsockname()
        self._host = str(address[0])
        self._port = int(address[1])
        return self

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        self._site = None
        if runner is not None:
            await runner.cleanup()

    async def _bounded(
        self,
        handler: Callable[[web.Request], Any],
        request: web.Request,
    ) -> web.Response:
        async with self._connections:
            try:
                async with asyncio.timeout(self.policy.request_timeout_seconds):
                    response = await handler(request)
            except TimeoutError:
                response = self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "reason": "MANAGEMENT_REQUEST_TIMEOUT"},
                )
            return response

    async def _health(self, request: web.Request) -> web.Response:
        return await self._bounded(self._health_impl, request)

    async def _health_impl(self, request: web.Request) -> web.Response:
        denied = self._authorize(request, ManagementSurface.LIVENESS)
        if denied is not None:
            return denied
        payload = build_public_liveness_payload(ok=True, now_ns=self.clock_ns())
        return self._json(HTTPStatus.OK, payload)

    async def _ready(self, request: web.Request) -> web.Response:
        return await self._bounded(self._ready_impl, request)

    async def _ready_impl(self, request: web.Request) -> web.Response:
        denied = self._authorize(request, ManagementSurface.READINESS)
        if denied is not None:
            return denied
        validation = self.state_provider()
        if not validation.ok or validation.payload is None:
            return self._snapshot_failure(validation.reason)
        state = dict(validation.payload)
        health = build_health_payload(
            state,
            now_ns=self.clock_ns(),
            max_heartbeat_age_seconds=self.max_heartbeat_age_seconds,
        )
        canonical = validate_canonical_readiness_payload(
            state.get("canonical_readiness")
        )
        canonical_payload = canonical.payload or {}
        ready = (
            bool(health.get("ok"))
            and canonical.ok
            and canonical_payload.get("paper_ready") is True
        )
        reasons: list[str] = []
        if not health.get("ok"):
            reasons.append("SIGNED_RUNTIME_HEARTBEAT_UNHEALTHY")
        if not canonical.ok:
            reasons.append(canonical.reason)
        elif not ready:
            requirement_blockers = canonical_payload.get("requirement_blockers", {})
            global_blockers = canonical_payload.get("global_blockers", [])
            reasons.extend(str(item) for item in global_blockers)
            if isinstance(requirement_blockers, Mapping):
                for domain, blockers in requirement_blockers.items():
                    if isinstance(blockers, list):
                        reasons.extend(f"{domain}:{item}" for item in blockers)
        payload = {
            "schema_version": O1_READINESS_SCHEMA,
            "ok": ready,
            "status": "ready" if ready else "not_ready",
            "generated_at_unix_ns": self.clock_ns(),
            "canonical_readiness": canonical.payload,
            "reasons": list(dict.fromkeys(reasons)),
        }
        status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
        return self._json(status, payload)

    async def _status(self, request: web.Request) -> web.Response:
        return await self._bounded(self._status_impl, request)

    async def _status_impl(self, request: web.Request) -> web.Response:
        denied = self._authorize(request, ManagementSurface.OPERATOR_STATUS)
        if denied is not None:
            return denied
        validation = self.state_provider()
        if not validation.ok or validation.payload is None:
            return self._snapshot_failure(validation.reason)
        state = dict(validation.payload)
        canonical = validate_canonical_readiness_payload(
            state.get("canonical_readiness")
        )
        payload = sanitize(
            {
                "schema_version": O1_STATUS_SCHEMA,
                "generated_at_unix_ns": self.clock_ns(),
                "runtime": {
                    "release_id": state.get("release_id"),
                    "runtime_generation": state.get("runtime_generation"),
                    "policy_bundle_hash": state.get("policy_bundle_hash"),
                    "heartbeat_sequence": state.get("heartbeat_sequence"),
                    "active_task_generation": state.get("active_task_generation"),
                    "mode": state.get("mode"),
                    "diagnostic": state.get("diagnostic"),
                    "live_enabled": state.get("live_enabled"),
                    "trading_enabled": state.get("trading_enabled"),
                },
                "canonical_readiness": canonical.payload,
                "canonical_readiness_validation": canonical.reason,
            }
        )
        return self._json(HTTPStatus.OK, payload)

    async def _metrics(self, request: web.Request) -> web.Response:
        return await self._bounded(self._metrics_impl, request)

    async def _metrics_impl(self, request: web.Request) -> web.Response:
        denied = self._authorize(request, ManagementSurface.METRICS)
        if denied is not None:
            return denied
        validation = self.state_provider()
        snapshot_ok = validation.ok and validation.payload is not None
        snapshot_payload = validation.payload or {}
        canonical = validate_canonical_readiness_payload(
            snapshot_payload.get("canonical_readiness") if snapshot_ok else None
        )
        paper_ready = bool(canonical.payload and canonical.payload.get("paper_ready"))
        text = "\n".join(
            (
                f"# {O1_METRICS_SCHEMA}",
                "# TYPE flashloan_signed_runtime_state_valid gauge",
                f"flashloan_signed_runtime_state_valid {1 if snapshot_ok else 0}",
                "# TYPE flashloan_canonical_paper_readiness gauge",
                f"flashloan_canonical_paper_readiness {1 if paper_ready else 0}",
                "",
            )
        )
        return self._text(HTTPStatus.OK, text)

    def _authorize(
        self, request: web.Request, surface: ManagementSurface
    ) -> web.Response | None:
        decision = authorize_surface(
            self.policy,
            surface,
            bearer_token=_bearer_token(request),
        )
        if decision.allowed:
            return None
        return self._json(
            HTTPStatus.UNAUTHORIZED,
            {
                "ok": False,
                "reason": decision.reason.value,
                "surface": surface.value,
            },
            extra_headers={"WWW-Authenticate": "Bearer"},
        )

    def _snapshot_failure(self, reason: SnapshotErrorCode | None) -> web.Response:
        return self._json(
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "schema_version": O1_READINESS_SCHEMA,
                "ok": False,
                "status": "not_ready",
                "reason": (
                    reason.value if reason is not None else "signed_state_invalid"
                ),
            },
        )

    def _json(
        self,
        status: HTTPStatus,
        payload: Mapping[str, Any],
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> web.Response:
        body = json.dumps(
            sanitize(dict(payload)),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        if len(body) > self.policy.max_response_bytes:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = b'{"ok":false,"reason":"MANAGEMENT_RESPONSE_TOO_LARGE"}'
        headers = {
            "Cache-Control": self.limits.cache_control,
            **dict(self.limits.security_headers),
            **dict(extra_headers or {}),
        }
        return web.Response(
            status=status.value,
            body=body,
            content_type="application/json",
            charset="utf-8",
            headers=headers,
        )

    def _text(self, status: HTTPStatus, payload: str) -> web.Response:
        body = payload.encode("utf-8")
        if len(body) > self.policy.max_response_bytes:
            return self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "reason": "MANAGEMENT_RESPONSE_TOO_LARGE"},
            )
        return web.Response(
            status=status.value,
            body=body,
            content_type="text/plain",
            charset="utf-8",
            headers={
                "Cache-Control": self.limits.cache_control,
                **dict(self.limits.security_headers),
            },
        )


__all__ = [
    "ActiveManagementHttpServer",
    "CanonicalReadinessValidation",
    "O1_METRICS_SCHEMA",
    "O1_READINESS_SCHEMA",
    "O1_STATUS_SCHEMA",
    "SignedRuntimeStateProvider",
    "validate_canonical_readiness_payload",
]
