"""PR-192 runtime-memory confidentiality and crash-artifact controls.

The module is intentionally standard-library only so the production launcher can
apply it before configuration, credentials, provider clients or signing material
are constructed.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Protocol

try:  # pragma: no cover - unavailable only on non-POSIX platforms
    import resource as _resource
except ImportError:  # pragma: no cover - Windows fallback
    _resource = None

PR_GET_DUMPABLE = 3
PR_SET_DUMPABLE = 4
RUNTIME_MEMORY_SCHEMA = "pr192.runtime-memory.v1"
CRASH_ARTIFACT_SCHEMA = "pr192.crash-artifact.v1"
SUPPORT_BUNDLE_SCHEMA = "pr192.support-bundle.v1"

_SAFE_CODE_RE = re.compile(r"\A[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_SUPPORT_FIELDS = frozenset(
    {
        "component",
        "operation",
        "reason_code",
        "correlation_id",
        "release_hash",
        "policy_hash",
        "config_generation",
        "timestamp_unix_ns",
    }
)


class RuntimeMemoryHardeningError(RuntimeError):
    """Raised when a required memory-confidentiality control cannot be proved."""


class CrashArtifactError(ValueError):
    """Raised when diagnostic output is not strictly allowlisted."""


class ProcessMemoryBackend(Protocol):
    """Injectable operating-system boundary used by tests and the launcher."""

    platform: str

    def set_core_limit_zero(self) -> None: ...

    def get_core_limit(self) -> tuple[int, int]: ...

    def set_dumpable(self, value: int) -> None: ...

    def get_dumpable(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class RuntimeMemoryPolicy:
    require_core_limit_zero: bool = True
    require_non_dumpable: bool = True
    require_no_active_tracer: bool = True
    require_linux: bool = False

    @classmethod
    def production_default(cls) -> "RuntimeMemoryPolicy":
        return cls(require_linux=True)


@dataclass(frozen=True, slots=True)
class RuntimeMemoryStatus:
    schema_version: str
    platform: str
    core_soft_limit: int | None
    core_hard_limit: int | None
    dumpable: int | None
    tracer_pid: int | None
    verified: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "platform": self.platform,
            "core_soft_limit": self.core_soft_limit,
            "core_hard_limit": self.core_hard_limit,
            "dumpable": self.dumpable,
            "tracer_pid": self.tracer_pid,
            "verified": self.verified,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class SafeCrashArtifact:
    schema_version: str
    component: str
    operation: str
    reason_code: str
    exception_type: str
    correlation_id: str | None = None
    timestamp_unix_ns: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "component": self.component,
            "operation": self.operation,
            "reason_code": self.reason_code,
            "exception_type": self.exception_type,
        }
        if self.correlation_id is not None:
            payload["correlation_id"] = self.correlation_id
        if self.timestamp_unix_ns is not None:
            payload["timestamp_unix_ns"] = self.timestamp_unix_ns
        return payload


class SystemProcessMemoryBackend:
    """Linux/POSIX implementation of core-limit and dumpability controls."""

    def __init__(self, *, platform: str = sys.platform) -> None:
        self.platform = platform
        self._libc: Any | None = None
        if platform.startswith("linux"):
            self._libc = ctypes.CDLL(None, use_errno=True)

    def set_core_limit_zero(self) -> None:
        if _resource is None:
            raise OSError(errno.ENOTSUP, "resource limits unavailable")
        _resource.setrlimit(_resource.RLIMIT_CORE, (0, 0))

    def get_core_limit(self) -> tuple[int, int]:
        if _resource is None:
            raise OSError(errno.ENOTSUP, "resource limits unavailable")
        soft, hard = _resource.getrlimit(_resource.RLIMIT_CORE)
        return int(soft), int(hard)

    def set_dumpable(self, value: int) -> None:
        if self._libc is None:
            raise OSError(errno.ENOTSUP, "prctl unavailable")
        self._prctl(PR_SET_DUMPABLE, value)

    def get_dumpable(self) -> int | None:
        if self._libc is None:
            return None
        return self._prctl(PR_GET_DUMPABLE, 0)

    def _prctl(self, option: int, argument: int) -> int:
        assert self._libc is not None
        ctypes.set_errno(0)
        result = int(self._libc.prctl(option, argument, 0, 0, 0))
        if result < 0:
            error_number = ctypes.get_errno() or errno.EPERM
            raise OSError(error_number, "prctl operation failed")
        return result


def _read_tracer_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    for line in text.splitlines():
        if line.startswith("TracerPid:"):
            _, value = line.split(":", 1)
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def harden_process_memory(
    *,
    policy: RuntimeMemoryPolicy | None = None,
    backend: ProcessMemoryBackend | None = None,
    proc_status_path: Path = Path("/proc/self/status"),
    fail_closed: bool = True,
) -> RuntimeMemoryStatus:
    """Apply and verify process-level memory confidentiality controls.

    Error details are represented only by stable reason codes. Operating-system
    exception messages are deliberately excluded because they may contain paths,
    process details or other sensitive runtime context.
    """

    active_policy = policy or RuntimeMemoryPolicy.production_default()
    active_backend = backend or SystemProcessMemoryBackend()
    reasons: list[str] = []

    if active_policy.require_linux and not active_backend.platform.startswith("linux"):
        reasons.append("MEMORY_HARDENING_LINUX_REQUIRED")

    if active_policy.require_core_limit_zero:
        try:
            active_backend.set_core_limit_zero()
        except (OSError, ValueError):
            reasons.append("CORE_LIMIT_SET_FAILED")

    if active_policy.require_non_dumpable:
        try:
            active_backend.set_dumpable(0)
        except (OSError, ValueError):
            reasons.append("DUMPABLE_DISABLE_FAILED")

    core_soft: int | None = None
    core_hard: int | None = None
    try:
        core_soft, core_hard = active_backend.get_core_limit()
    except (OSError, ValueError):
        reasons.append("CORE_LIMIT_VERIFY_FAILED")

    dumpable: int | None = None
    try:
        dumpable = active_backend.get_dumpable()
    except (OSError, ValueError):
        reasons.append("DUMPABLE_VERIFY_FAILED")

    tracer_pid = (
        _read_tracer_pid(proc_status_path)
        if active_backend.platform.startswith("linux")
        else None
    )

    if active_policy.require_core_limit_zero and (core_soft, core_hard) != (0, 0):
        reasons.append("CORE_LIMIT_NOT_ZERO")
    if active_policy.require_non_dumpable and dumpable != 0:
        reasons.append("PROCESS_STILL_DUMPABLE")
    if active_policy.require_no_active_tracer:
        if active_backend.platform.startswith("linux") and tracer_pid is None:
            reasons.append("TRACER_STATE_UNVERIFIED")
        elif tracer_pid not in (None, 0):
            reasons.append("ACTIVE_TRACER_DETECTED")

    status = RuntimeMemoryStatus(
        schema_version=RUNTIME_MEMORY_SCHEMA,
        platform=active_backend.platform,
        core_soft_limit=core_soft,
        core_hard_limit=core_hard,
        dumpable=dumpable,
        tracer_pid=tracer_pid,
        verified=not reasons,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
    if fail_closed and not status.verified:
        joined = ",".join(status.reason_codes)
        raise RuntimeMemoryHardeningError(f"runtime memory hardening failed: {joined}")
    return status


def build_safe_crash_artifact(
    exception: BaseException,
    *,
    component: str,
    operation: str,
    reason_code: str,
    correlation_id: str | None = None,
    timestamp_unix_ns: int | None = None,
) -> SafeCrashArtifact:
    """Create a metadata-only crash artifact without message, args or traceback."""

    return SafeCrashArtifact(
        schema_version=CRASH_ARTIFACT_SCHEMA,
        component=_safe_code(component, "component"),
        operation=_safe_code(operation, "operation"),
        reason_code=_safe_code(reason_code, "reason_code"),
        exception_type=_safe_code(type(exception).__name__, "exception_type"),
        correlation_id=(
            _safe_code(correlation_id, "correlation_id")
            if correlation_id is not None
            else None
        ),
        timestamp_unix_ns=_safe_non_negative_int(
            timestamp_unix_ns, "timestamp_unix_ns", allow_none=True
        ),
    )


def build_allowlisted_support_bundle(metadata: Mapping[str, object]) -> dict[str, object]:
    """Build a support bundle from a fixed metadata allowlist.

    Environment variables, headers, request/response bodies, configuration trees,
    transaction bytes, signatures, wallet topology, tracebacks and locals have no
    representable field in this schema and are rejected as unknown input.
    """

    unknown = set(metadata) - _SUPPORT_FIELDS
    if unknown:
        raise CrashArtifactError(
            "support bundle contains non-allowlisted fields: "
            + ",".join(sorted(unknown))
        )

    payload: dict[str, object] = {"schema_version": SUPPORT_BUNDLE_SCHEMA}
    for key in ("component", "operation", "reason_code", "correlation_id"):
        value = metadata.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise CrashArtifactError(f"{key} must be a string")
            payload[key] = _safe_code(value, key)
    for key in ("release_hash", "policy_hash"):
        value = metadata.get(key)
        if value is not None:
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise CrashArtifactError(f"{key} must be a lowercase SHA-256 digest")
            payload[key] = value
    for key in ("config_generation", "timestamp_unix_ns"):
        value = metadata.get(key)
        if value is not None:
            payload[key] = _safe_non_negative_int(value, key)
    return payload


def _safe_code(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_CODE_RE.fullmatch(value):
        raise CrashArtifactError(f"{field} contains unsafe diagnostic text")
    return value


def _safe_non_negative_int(
    value: object, field: str, *, allow_none: bool = False
) -> int | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CrashArtifactError(f"{field} must be a non-negative integer")
    return value


__all__ = [
    "CRASH_ARTIFACT_SCHEMA",
    "CrashArtifactError",
    "ProcessMemoryBackend",
    "RUNTIME_MEMORY_SCHEMA",
    "RuntimeMemoryHardeningError",
    "RuntimeMemoryPolicy",
    "RuntimeMemoryStatus",
    "SUPPORT_BUNDLE_SCHEMA",
    "SafeCrashArtifact",
    "SystemProcessMemoryBackend",
    "build_allowlisted_support_bundle",
    "build_safe_crash_artifact",
    "harden_process_memory",
]
