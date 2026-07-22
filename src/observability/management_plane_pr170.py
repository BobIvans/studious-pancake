"PR-170 authenticated management-plane policy and signed state snapshots."

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any, Mapping

PR170_SCHEMA = "pr170.management-plane.v1"
PR170_STATE_SCHEMA = "pr170.signed-runtime-state.v1"
PR170_LIVENESS_SCHEMA = "pr170.liveness.v1"
DEFAULT_MAX_STATE_BYTES = 64 * 1024


class ManagementSurface(StrEnum):
    LIVENESS = "liveness"
    READINESS = "readiness"
    METRICS = "metrics"
    OPERATOR_STATUS = "operator_status"
    ADMIN_MUTATION = "admin_mutation"


class ManagementDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class ManagementReason(StrEnum):
    LOOPBACK_LIVENESS = "loopback_liveness"
    AUTHENTICATED_OPERATOR = "authenticated_operator"
    AUTHENTICATED_METRICS = "authenticated_metrics"
    AUTHENTICATED_PROXY = "authenticated_proxy"
    EXTERNAL_BIND_REQUIRES_AUTHENTICATED_PROXY = (
        "external_bind_requires_authenticated_proxy"
    )
    TOKEN_REQUIRED = "token_required"
    TOKEN_INVALID = "token_invalid"
    ADMIN_MUTATION_DISABLED = "admin_mutation_disabled"


class SnapshotErrorCode(StrEnum):
    STATE_FILE_MISSING = "state_file_missing"
    STATE_PATH_IS_SYMLINK = "state_path_is_symlink"
    STATE_PATH_NOT_REGULAR = "state_path_not_regular"
    STATE_FILE_MODE_TOO_OPEN = "state_file_mode_too_open"
    STATE_FILE_TOO_LARGE = "state_file_too_large"
    STATE_JSON_INVALID = "state_json_invalid"
    STATE_SCHEMA_INVALID = "state_schema_invalid"
    STATE_MAC_INVALID = "state_mac_invalid"
    STATE_GENERATION_STALE = "state_generation_stale"
    STATE_POLICY_MISMATCH = "state_policy_mismatch"


@dataclass(frozen=True, slots=True)
class ManagementPlanePolicy:
    """Fail-closed policy for PR-170 management-plane exposure."""

    bind_host: str = "127.0.0.1"
    bearer_token_sha256: str | None = None
    authenticated_proxy: bool = False
    metrics_requires_auth: bool = True
    operator_requires_auth: bool = True
    admin_mutation_enabled: bool = False
    max_connections: int = 16
    request_timeout_seconds: float = 2.0
    max_response_bytes: int = 32 * 1024
    release_id: str = "development"
    runtime_generation: int = 0
    policy_bundle_hash: str = "0" * 64

    def __post_init__(self) -> None:
        if self.max_connections <= 0:
            raise ValueError("max_connections must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if self.runtime_generation < 0:
            raise ValueError("runtime_generation must be non-negative")
        _require_sha256("policy_bundle_hash", self.policy_bundle_hash)
        if self.bearer_token_sha256 is not None:
            _require_sha256("bearer_token_sha256", self.bearer_token_sha256)


@dataclass(frozen=True, slots=True)
class ManagementAccessDecision:
    decision: ManagementDecision
    reason: ManagementReason
    surface: ManagementSurface
    external_bind: bool

    @property
    def allowed(self) -> bool:
        return self.decision is ManagementDecision.ALLOW


@dataclass(frozen=True, slots=True)
class RuntimeTruth:
    """Minimal generation-fenced truth used by PR-170 status snapshots."""

    process_boot_id: str
    release_id: str
    runtime_generation: int
    policy_bundle_hash: str
    heartbeat_sequence: int
    active_task_generation: int
    live_enabled: bool = False
    trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.process_boot_id:
            raise ValueError("process_boot_id is required")
        if not self.release_id:
            raise ValueError("release_id is required")
        _require_sha256("policy_bundle_hash", self.policy_bundle_hash)
        for name in (
            "runtime_generation",
            "heartbeat_sequence",
            "active_task_generation",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    def to_payload(self) -> dict[str, Any]:
        return {
            "process_boot_id": self.process_boot_id,
            "release_id": self.release_id,
            "runtime_generation": self.runtime_generation,
            "policy_bundle_hash": self.policy_bundle_hash,
            "heartbeat_sequence": self.heartbeat_sequence,
            "active_task_generation": self.active_task_generation,
            "live_enabled": self.live_enabled,
            "trading_enabled": self.trading_enabled,
        }


@dataclass(frozen=True, slots=True)
class SignedRuntimeSnapshot:
    schema_version: str
    payload: Mapping[str, Any]
    mac_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "payload": dict(self.payload),
            "mac_sha256": self.mac_sha256,
        }


@dataclass(frozen=True, slots=True)
class SnapshotValidation:
    ok: bool
    reason: SnapshotErrorCode | None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PublicLiveness:
    ok: bool
    generated_at_unix_ns: int
    schema_version: str = PR170_LIVENESS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "status": "ok" if self.ok else "unhealthy",
            "generated_at_unix_ns": self.generated_at_unix_ns,
        }


@dataclass(frozen=True, slots=True)
class ManagementIngressLimits:
    max_connections: int
    request_timeout_seconds: float
    max_response_bytes: int
    cache_control: str = "no-store"
    security_headers: Mapping[str, str] = field(
        default_factory=lambda: {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
    )


def build_ingress_limits(policy: ManagementPlanePolicy) -> ManagementIngressLimits:
    return ManagementIngressLimits(
        max_connections=policy.max_connections,
        request_timeout_seconds=policy.request_timeout_seconds,
        max_response_bytes=policy.max_response_bytes,
    )


def build_public_liveness_payload(*, ok: bool, now_ns: int) -> dict[str, Any]:
    """Return a topology-minimal public liveness response."""

    return PublicLiveness(ok=ok, generated_at_unix_ns=now_ns).to_dict()


def authorize_surface(
    policy: ManagementPlanePolicy,
    surface: ManagementSurface,
    *,
    bearer_token: str | None = None,
) -> ManagementAccessDecision:
    external = is_external_bind(policy.bind_host)
    if external and not policy.authenticated_proxy:
        return ManagementAccessDecision(
            ManagementDecision.DENY,
            ManagementReason.EXTERNAL_BIND_REQUIRES_AUTHENTICATED_PROXY,
            surface,
            external,
        )
    if (
        surface is ManagementSurface.ADMIN_MUTATION
        and not policy.admin_mutation_enabled
    ):
        return ManagementAccessDecision(
            ManagementDecision.DENY,
            ManagementReason.ADMIN_MUTATION_DISABLED,
            surface,
            external,
        )
    if surface is ManagementSurface.LIVENESS and not external:
        return ManagementAccessDecision(
            ManagementDecision.ALLOW,
            ManagementReason.LOOPBACK_LIVENESS,
            surface,
            external,
        )
    requires_token = (
        surface in {ManagementSurface.OPERATOR_STATUS, ManagementSurface.READINESS}
        and policy.operator_requires_auth
    ) or (surface is ManagementSurface.METRICS and policy.metrics_requires_auth)
    if requires_token or external:
        if policy.bearer_token_sha256 is None or not bearer_token:
            return ManagementAccessDecision(
                ManagementDecision.DENY,
                ManagementReason.TOKEN_REQUIRED,
                surface,
                external,
            )
        digest = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()
        if not secrets.compare_digest(digest, policy.bearer_token_sha256):
            return ManagementAccessDecision(
                ManagementDecision.DENY,
                ManagementReason.TOKEN_INVALID,
                surface,
                external,
            )
        reason = (
            ManagementReason.AUTHENTICATED_METRICS
            if surface is ManagementSurface.METRICS
            else ManagementReason.AUTHENTICATED_OPERATOR
        )
        if external and policy.authenticated_proxy:
            reason = ManagementReason.AUTHENTICATED_PROXY
        return ManagementAccessDecision(
            ManagementDecision.ALLOW,
            reason,
            surface,
            external,
        )
    return ManagementAccessDecision(
        ManagementDecision.ALLOW,
        ManagementReason.LOOPBACK_LIVENESS,
        surface,
        external,
    )


def make_signed_snapshot(
    payload: Mapping[str, Any], signing_key: bytes
) -> SignedRuntimeSnapshot:
    body = _canonical_json_bytes(payload)
    return SignedRuntimeSnapshot(
        schema_version=PR170_STATE_SCHEMA,
        payload=dict(payload),
        mac_sha256=hmac.new(signing_key, body, hashlib.sha256).hexdigest(),
    )


def write_signed_state_snapshot(
    path: str | os.PathLike[str],
    truth: RuntimeTruth,
    signing_key: bytes,
    *,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Atomically write owner-only, MACed runtime state with fsync."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = truth.to_payload()
    payload.update(dict(extra or {}))
    snapshot = make_signed_snapshot(payload, signing_key).to_json()
    encoded = _canonical_json_bytes(snapshot)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        try:
            os.chmod(target, 0o600)
        except PermissionError:
            pass
        _fsync_directory(target.parent)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def read_signed_state_snapshot(
    path: str | os.PathLike[str],
    signing_key: bytes,
    *,
    minimum_generation: int,
    expected_policy_bundle_hash: str,
    max_bytes: int = DEFAULT_MAX_STATE_BYTES,
) -> SnapshotValidation:
    target = Path(path)
    if target.is_symlink():
        return SnapshotValidation(False, SnapshotErrorCode.STATE_PATH_IS_SYMLINK)
    try:
        stat_result = target.stat()
    except FileNotFoundError:
        return SnapshotValidation(False, SnapshotErrorCode.STATE_FILE_MISSING)
    if not target.is_file():
        return SnapshotValidation(False, SnapshotErrorCode.STATE_PATH_NOT_REGULAR)
    if stat_result.st_mode & 0o077:
        return SnapshotValidation(False, SnapshotErrorCode.STATE_FILE_MODE_TOO_OPEN)
    if stat_result.st_size > max_bytes:
        return SnapshotValidation(False, SnapshotErrorCode.STATE_FILE_TOO_LARGE)
    try:
        raw = target.read_bytes()
        wrapper = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return SnapshotValidation(False, SnapshotErrorCode.STATE_JSON_INVALID)
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("schema_version") != PR170_STATE_SCHEMA
    ):
        return SnapshotValidation(False, SnapshotErrorCode.STATE_SCHEMA_INVALID)
    payload = wrapper.get("payload")
    supplied_mac = wrapper.get("mac_sha256")
    if not isinstance(payload, dict) or not isinstance(supplied_mac, str):
        return SnapshotValidation(False, SnapshotErrorCode.STATE_SCHEMA_INVALID)
    expected_mac = make_signed_snapshot(payload, signing_key).mac_sha256
    if not secrets.compare_digest(supplied_mac, expected_mac):
        return SnapshotValidation(False, SnapshotErrorCode.STATE_MAC_INVALID)
    if int(payload.get("runtime_generation", -1)) < minimum_generation:
        return SnapshotValidation(False, SnapshotErrorCode.STATE_GENERATION_STALE)
    if payload.get("policy_bundle_hash") != expected_policy_bundle_hash:
        return SnapshotValidation(False, SnapshotErrorCode.STATE_POLICY_MISMATCH)
    return SnapshotValidation(True, None, payload)


def is_external_bind(host: str) -> bool:
    normalized = host.strip().strip("[]")
    if normalized in {"", "*"}:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return normalized not in {"localhost"}
    return not address.is_loopback


def _require_sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256 digest")


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DEFAULT_MAX_STATE_BYTES",
    "ManagementAccessDecision",
    "ManagementDecision",
    "ManagementIngressLimits",
    "ManagementPlanePolicy",
    "ManagementReason",
    "ManagementSurface",
    "PR170_LIVENESS_SCHEMA",
    "PR170_SCHEMA",
    "PR170_STATE_SCHEMA",
    "PublicLiveness",
    "RuntimeTruth",
    "SignedRuntimeSnapshot",
    "SnapshotErrorCode",
    "SnapshotValidation",
    "authorize_surface",
    "build_ingress_limits",
    "build_public_liveness_payload",
    "is_external_bind",
    "make_signed_snapshot",
    "read_signed_state_snapshot",
    "write_signed_state_snapshot",
]
