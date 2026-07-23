"""MPR-10 lifecycle-consistent queueing, bounded shutdown and observability gate.

The module is offline, deterministic and sender-free. It validates evidence that
queue expiry, consumer expiry, shutdown, tracker retention, metrics aggregation
and timing configuration fail closed before MPR-10 can be considered satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import math
import re
from typing import Any, Mapping, Sequence

MPR10_SCHEMA_VERSION = "mpr10.lifecycle-queue-observability.v1"

_REQUIRED_HASHES = (
    "queue_lifecycle_model_hash",
    "lifecycle_authority_contract_hash",
    "shutdown_policy_hash",
    "tracker_retention_policy_hash",
    "observability_window_policy_hash",
    "numeric_config_policy_hash",
    "stress_suite_hash",
)
_REQUIRED_NUMERIC_REJECTS = {
    "nan",
    "positive_infinity",
    "negative_infinity",
    "excessive_delay",
    "negative_delay",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR10EvidenceError(ValueError):
    """Raised when MPR-10 evidence has the wrong shape."""


class Severity(StrEnum):
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class MPR10Diagnostic:
    code: str
    severity: Severity
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class MPR10Report:
    schema_version: str
    ready: bool
    diagnostics: tuple[MPR10Diagnostic, ...]
    artifact_hashes: dict[str, str]
    live_capability_allowed: bool = False
    signer_capability_allowed: bool = False
    sender_capability_allowed: bool = False

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "reason_codes": list(self.reason_codes),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "artifact_hashes": dict(sorted(self.artifact_hashes.items())),
            "live_capability_allowed": self.live_capability_allowed,
            "signer_capability_allowed": self.signer_capability_allowed,
            "sender_capability_allowed": self.sender_capability_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"


def live_capability_allowed() -> bool:
    return False


def signer_capability_allowed() -> bool:
    return False


def sender_capability_allowed() -> bool:
    return False


def evaluate_mpr10_lifecycle_gate(evidence: Mapping[str, Any]) -> MPR10Report:
    """Evaluate the MPR-10 offline acceptance evidence."""

    if not isinstance(evidence, Mapping):
        raise MPR10EvidenceError("evidence must be a mapping")
    schema = _non_empty(evidence.get("schema_version"), "schema_version")
    if schema != MPR10_SCHEMA_VERSION:
        raise MPR10EvidenceError(f"schema_version must be {MPR10_SCHEMA_VERSION!r}")

    artifact_hashes = _validate_hashes(_mapping(evidence.get("artifact_hashes"), "artifact_hashes"))
    diagnostics: list[MPR10Diagnostic] = []
    diagnostics.extend(_capabilities(_mapping(evidence.get("runtime_capabilities"), "runtime_capabilities")))
    diagnostics.extend(_queue(_mapping(evidence.get("queue_lifecycle"), "queue_lifecycle")))
    diagnostics.extend(_shutdown(_mapping(evidence.get("shutdown"), "shutdown")))
    diagnostics.extend(_bounded(_mapping(evidence.get("bounded_state"), "bounded_state")))
    diagnostics.extend(_numeric(_mapping(evidence.get("numeric_timing"), "numeric_timing")))

    return MPR10Report(
        schema_version=MPR10_SCHEMA_VERSION,
        ready=not diagnostics,
        diagnostics=tuple(diagnostics),
        artifact_hashes=artifact_hashes,
    )


def _capabilities(raw: Mapping[str, Any]) -> tuple[MPR10Diagnostic, ...]:
    diagnostics: list[MPR10Diagnostic] = []
    for name in ("live", "signer", "sender"):
        if _bool(raw.get(name), f"runtime_capabilities.{name}"):
            diagnostics.append(
                _diag(
                    f"{name.upper()}_CAPABILITY_NOT_ALLOWED",
                    f"MPR-10 must not enable {name} capability",
                    f"runtime_capabilities.{name}",
                )
            )
    return tuple(diagnostics)


def _queue(raw: Mapping[str, Any]) -> tuple[MPR10Diagnostic, ...]:
    required = (
        ("single_lifecycle_authority", "QUEUE_NOT_SINGLE_AUTHORITY", "queue needs one lifecycle authority"),
        ("expiry_records_terminal_outcome", "EXPIRY_DOES_NOT_TERMINALIZE", "expiry must record terminal outcome"),
        ("expiry_releases_pending_identity", "EXPIRY_LEAVES_PENDING", "expiry must release or terminalize PENDING identity"),
        ("public_expire_lock_protected", "EXPIRE_NOT_LOCK_PROTECTED", "public expiry must serialize with put/get"),
        ("consumer_expiry_claims_or_terminalizes", "CONSUMER_EXPIRY_NOT_LIFECYCLE_BOUND", "consumer expiry must bind lifecycle"),
        ("sink_result_matches_lifecycle_state", "SINK_LIFECYCLE_MISMATCH", "sink result must match lifecycle"),
        ("readmission_policy_explicit", "READMISSION_POLICY_MISSING", "readmission policy must be explicit"),
        ("concurrent_stress_preserves_heap_ids_lifecycle", "QUEUE_STRESS_INVARIANT_MISSING", "stress must preserve heap/id/lifecycle"),
        ("crash_replay_preserves_terminal_expiry", "EXPIRY_CRASH_REPLAY_MISSING", "restart must preserve expiry terminal state"),
    )
    return _require_flags(raw, "queue_lifecycle", required)


def _shutdown(raw: Mapping[str, Any]) -> tuple[MPR10Diagnostic, ...]:
    diagnostics: list[MPR10Diagnostic] = []
    grace_ms = _int(raw.get("declared_grace_ms"), "shutdown.declared_grace_ms")
    if grace_ms <= 0:
        diagnostics.append(_diag("SHUTDOWN_GRACE_INVALID", "shutdown grace must be positive", "shutdown.declared_grace_ms"))
    if grace_ms > 600_000:
        diagnostics.append(_diag("SHUTDOWN_GRACE_UNBOUNDED", "shutdown grace must be bounded", "shutdown.declared_grace_ms"))
    required = (
        ("admission_stops_before_drain", "ADMISSION_NOT_STOPPED_BEFORE_DRAIN", "admission must stop before drain"),
        ("no_unbounded_second_drain", "UNBOUNDED_SECOND_DRAIN", "shutdown must not do unbounded second drain"),
        ("hung_handler_finishes_within_grace", "HUNG_HANDLER_BLOCKS_SHUTDOWN", "hung handler must finish within grace"),
        ("remaining_work_marked_resumable_or_aborted", "REMAINING_WORK_NOT_RESUMABLE", "remaining work must be resumable or aborted"),
        ("cancellation_safe_terminalization", "CANCELLATION_NOT_TERMINALIZED", "cancellation must terminalize lifecycle"),
        ("structured_concurrency_used", "STRUCTURED_CONCURRENCY_MISSING", "workers need structured ownership"),
    )
    diagnostics.extend(_require_flags(raw, "shutdown", required))
    return tuple(diagnostics)


def _bounded(raw: Mapping[str, Any]) -> tuple[MPR10Diagnostic, ...]:
    diagnostics: list[MPR10Diagnostic] = []
    if _int(raw.get("terminal_tracker_max_entries"), "bounded_state.terminal_tracker_max_entries") <= 0:
        diagnostics.append(_diag("TERMINAL_TRACKER_CAP_INVALID", "tracker cap must be positive", "bounded_state.terminal_tracker_max_entries"))
    if _int(raw.get("terminal_tracker_retention_ms"), "bounded_state.terminal_tracker_retention_ms") <= 0:
        diagnostics.append(_diag("TERMINAL_TRACKER_RETENTION_INVALID", "tracker retention must be positive", "bounded_state.terminal_tracker_retention_ms"))
    if _int(raw.get("metrics_query_row_limit"), "bounded_state.metrics_query_row_limit") <= 0:
        diagnostics.append(_diag("METRICS_QUERY_ROW_LIMIT_INVALID", "metrics row limit must be positive", "bounded_state.metrics_query_row_limit"))
    deadline = _int(raw.get("metrics_query_deadline_ms"), "bounded_state.metrics_query_deadline_ms")
    if deadline <= 0 or deadline > 60_000:
        diagnostics.append(_diag("METRICS_QUERY_DEADLINE_INVALID", "metrics deadline must be bounded", "bounded_state.metrics_query_deadline_ms"))
    required = (
        ("terminal_tracker_bounded", "TERMINAL_TRACKER_UNBOUNDED", "terminal tracker must be bounded"),
        ("durable_dedupe_handoff", "DURABLE_DEDUPE_HANDOFF_MISSING", "dedupe must hand off to durable identity"),
        ("eviction_metrics_exported", "TRACKER_EVICTION_METRICS_MISSING", "eviction metrics required"),
        ("multi_day_memory_bound_verified", "MULTI_DAY_MEMORY_BOUND_MISSING", "multi-day memory bound required"),
        ("observability_query_windowed", "OBSERVABILITY_QUERY_UNBOUNDED", "metrics must be window bounded"),
        ("streaming_quantiles_or_sql_histograms", "OBSERVABILITY_SORTS_FULL_HISTORY", "metrics must not sort full history"),
        ("truncation_metadata_exported", "OBSERVABILITY_TRUNCATION_METADATA_MISSING", "truncation metadata required"),
    )
    diagnostics.extend(_require_flags(raw, "bounded_state", required))
    return tuple(diagnostics)


def _numeric(raw: Mapping[str, Any]) -> tuple[MPR10Diagnostic, ...]:
    diagnostics: list[MPR10Diagnostic] = []
    max_delay = _number(raw.get("max_delay_seconds"), "numeric_timing.max_delay_seconds")
    if not math.isfinite(max_delay) or max_delay <= 0 or max_delay > 86_400:
        diagnostics.append(_diag("NUMERIC_MAX_DELAY_INVALID", "max delay must be finite and bounded", "numeric_timing.max_delay_seconds"))
    rejected = {
        _non_empty(item, f"numeric_timing.rejected_values[{idx}]")
        for idx, item in enumerate(_list(raw.get("rejected_values"), "numeric_timing.rejected_values"))
    }
    if not _REQUIRED_NUMERIC_REJECTS.issubset(rejected):
        diagnostics.append(_diag("NUMERIC_REJECTION_COVERAGE_MISSING", "NaN/infinity/invalid delay rejects required", "numeric_timing.rejected_values"))
    required = (
        ("all_duration_inputs_finite", "DURATION_FINITE_CHECK_MISSING", "all durations must be finite"),
        ("upper_bounds_enforced", "DURATION_UPPER_BOUND_MISSING", "duration upper bounds required"),
        ("config_errors_typed_before_start", "CONFIG_ERRORS_NOT_TYPED", "invalid timing must fail before start"),
    )
    diagnostics.extend(_require_flags(raw, "numeric_timing", required))
    return tuple(diagnostics)


def _require_flags(raw: Mapping[str, Any], prefix: str, flags: Sequence[tuple[str, str, str]]) -> tuple[MPR10Diagnostic, ...]:
    diagnostics: list[MPR10Diagnostic] = []
    for key, code, message in flags:
        if not _bool(raw.get(key), f"{prefix}.{key}"):
            diagnostics.append(_diag(code, message, f"{prefix}.{key}"))
    return tuple(diagnostics)


def _validate_hashes(raw: Mapping[str, Any]) -> dict[str, str]:
    unknown = sorted(set(raw) - set(_REQUIRED_HASHES))
    if unknown:
        raise MPR10EvidenceError("unknown artifact_hashes keys: " + ", ".join(unknown))
    return {key: _sha256(raw.get(key), f"artifact_hashes.{key}") for key in _REQUIRED_HASHES}


def _diag(code: str, message: str, path: str) -> MPR10Diagnostic:
    return MPR10Diagnostic(code=code, severity=Severity.ERROR, message=message, path=path)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MPR10EvidenceError(f"{path} must be a mapping")
    return value


def _list(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MPR10EvidenceError(f"{path} must be a list")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise MPR10EvidenceError(f"{path} must be boolean")
    return value


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MPR10EvidenceError(f"{path} must be integer")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MPR10EvidenceError(f"{path} must be numeric")
    return float(value)


def _non_empty(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MPR10EvidenceError(f"{path} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, path: str) -> str:
    text = _non_empty(value, path)
    if not _SHA256_RE.fullmatch(text):
        raise MPR10EvidenceError(f"{path} must be a lowercase sha256 digest")
    if text == "0" * 64 or text == "f" * 64:
        raise MPR10EvidenceError(f"{path} must not be a placeholder digest")
    return text
