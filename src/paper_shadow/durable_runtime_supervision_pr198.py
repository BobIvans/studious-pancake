"""PR-198 durable sender-free runtime supervision gate.

This module is deliberately offline and sender-free.  It does not import a
sender, signer, RPC transport, Jito client, wallet material, or a live permit.
It validates evidence that the installed paper/shadow runtime has one real
composition surface, supervised strategy tasks, a durable queue/result sink and
a bounded shutdown/drain boundary before PR-199 can rely on PR-198 evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR198_RUNTIME_SUPERVISION_SCHEMA = "pr198.durable-runtime-supervision.v1"
PR198_RUNTIME_SUPERVISION_RESULT_SCHEMA = (
    "pr198.durable-runtime-supervision-result.v1"
)
MAX_SHUTDOWN_DEADLINE_MS = 60_000
_ALLOWED_STRATEGY_STATES = frozenset(
    {
        "running",
        "stopped-cleanly",
        "failed",
        "restart-exhausted",
    }
)
_ALLOWED_TERMINAL_QUEUE_ACTIONS = frozenset(
    {
        "terminal-outcome-written",
        "durable-requeue-written",
        "durable-abandon-written",
    }
)
_FORBIDDEN_ACTIVE_SURFACE = (
    "sender-module-present",
    "signer-module-present",
    "jito-submit-endpoint-present",
    "rpc-send-endpoint-present",
    "live-permit-present",
    "live-capability-enabled",
    "trading-wallet-present",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class DurableRuntimeSupervisionError(ValueError):
    """Raised when PR-198 runtime supervision evidence is malformed."""


class RuntimeSupervisionState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_SENDER_FREE_SHADOW = "ready-for-sender-free-shadow"


@dataclass(frozen=True, slots=True)
class RuntimeDependencyEvidence:
    """Evidence that paper/shadow is a real installed vertical, not placeholders."""

    production_factory_singleton: bool
    installed_command_singleton: bool
    real_dependency_graph: bool
    placeholder_dependencies_present: bool
    memory_only_authorities_present: bool
    dependency_graph_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "production_factory_singleton",
            "installed_command_singleton",
            "real_dependency_graph",
            "placeholder_dependencies_present",
            "memory_only_authorities_present",
        ):
            _require_bool(getattr(self, field_name), f"dependencies.{field_name}")
        object.__setattr__(
            self,
            "dependency_graph_hash",
            _require_sha256(
                self.dependency_graph_hash,
                "dependencies.dependency_graph_hash",
            ),
        )


@dataclass(frozen=True, slots=True)
class StrategyTaskEvidence:
    """One strategy task supervision record from the sender-free runtime."""

    strategy_name: str
    required: bool
    supervised: bool
    state: str
    readiness_false_on_failure: bool
    restart_attempts: int
    restart_limit: int
    terminal_reason_code: str
    exception_redacted: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "strategy_name",
            _require_text(self.strategy_name, "strategy.strategy_name"),
        )
        for field_name in (
            "required",
            "supervised",
            "readiness_false_on_failure",
            "exception_redacted",
        ):
            _require_bool(getattr(self, field_name), f"strategy.{field_name}")
        state = _require_text(self.state, "strategy.state")
        if state not in _ALLOWED_STRATEGY_STATES:
            raise DurableRuntimeSupervisionError(
                f"strategy.state is unsupported: {state}"
            )
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "restart_attempts",
            _require_non_negative_int(
                self.restart_attempts,
                "strategy.restart_attempts",
            ),
        )
        object.__setattr__(
            self,
            "restart_limit",
            _require_non_negative_int(self.restart_limit, "strategy.restart_limit"),
        )
        object.__setattr__(
            self,
            "terminal_reason_code",
            str(self.terminal_reason_code).strip(),
        )


@dataclass(frozen=True, slots=True)
class QueueLifecycleEvidence:
    """Durable queue, tracker and terminal outcome evidence for PR-198."""

    durable_queue: bool
    admission_closed_before_drain: bool
    single_consumer_owner: bool
    expiry_releases_pending_lifecycle: bool
    tracker_state_durable: bool
    result_sink_durable: bool
    duplicate_processing_observed: bool
    max_queue_depth: int
    pending_items_at_shutdown: int
    terminal_outcomes_written: int
    abandoned_or_requeued_items: int

    def __post_init__(self) -> None:
        for field_name in (
            "durable_queue",
            "admission_closed_before_drain",
            "single_consumer_owner",
            "expiry_releases_pending_lifecycle",
            "tracker_state_durable",
            "result_sink_durable",
            "duplicate_processing_observed",
        ):
            _require_bool(getattr(self, field_name), f"queue.{field_name}")
        for field_name in (
            "max_queue_depth",
            "pending_items_at_shutdown",
            "terminal_outcomes_written",
            "abandoned_or_requeued_items",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(
                    getattr(self, field_name),
                    f"queue.{field_name}",
                ),
            )


@dataclass(frozen=True, slots=True)
class ShutdownDrainEvidence:
    """Evidence that shutdown has one owner and a bounded terminal action."""

    structured_concurrency: bool
    deadline_ms: int
    fallback_deadline_ms: int
    cancellation_acknowledged: bool
    owned_tasks_before_shutdown: int
    owned_tasks_after_shutdown: int
    double_consumer_race_prevented: bool
    forced_shutdown_latch_written: bool
    terminal_queue_action: str

    def __post_init__(self) -> None:
        for field_name in (
            "structured_concurrency",
            "cancellation_acknowledged",
            "double_consumer_race_prevented",
            "forced_shutdown_latch_written",
        ):
            _require_bool(getattr(self, field_name), f"shutdown.{field_name}")
        for field_name in (
            "deadline_ms",
            "fallback_deadline_ms",
            "owned_tasks_before_shutdown",
            "owned_tasks_after_shutdown",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(
                    getattr(self, field_name),
                    f"shutdown.{field_name}",
                ),
            )
        terminal_action = _require_text(
            self.terminal_queue_action,
            "shutdown.terminal_queue_action",
        )
        if terminal_action not in _ALLOWED_TERMINAL_QUEUE_ACTIONS:
            raise DurableRuntimeSupervisionError(
                f"unsupported terminal queue action: {terminal_action}"
            )
        object.__setattr__(self, "terminal_queue_action", terminal_action)


@dataclass(frozen=True, slots=True)
class RuntimeSupervisionEvidenceBundle:
    """Complete offline evidence bundle for the PR-198 runtime-supervision slice."""

    source_commit: str
    dependencies: RuntimeDependencyEvidence
    strategies: tuple[StrategyTaskEvidence, ...]
    queue: QueueLifecycleEvidence
    shutdown: ShutdownDrainEvidence
    active_surface: tuple[str, ...]
    evidence_artifacts: Mapping[str, str]
    assembled_at: datetime
    assembled_by: str
    schema_version: str = PR198_RUNTIME_SUPERVISION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR198_RUNTIME_SUPERVISION_SCHEMA:
            raise DurableRuntimeSupervisionError(
                "unsupported PR-198 supervision schema"
            )
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        object.__setattr__(self, "strategies", tuple(self.strategies))
        object.__setattr__(
            self,
            "active_surface",
            _tuple_of_text(self.active_surface, "active_surface"),
        )
        if not self.evidence_artifacts:
            raise DurableRuntimeSupervisionError("evidence artifacts are required")
        for key, value in self.evidence_artifacts.items():
            _require_text(str(key), "evidence_artifacts.key")
            _require_sha256(value, f"evidence_artifacts.{key}")
        _require_aware(self.assembled_at, "assembled_at")
        object.__setattr__(
            self,
            "assembled_by",
            _require_text(self.assembled_by, "assembled_by"),
        )


@dataclass(frozen=True, slots=True)
class RuntimeSupervisionReadiness:
    state: RuntimeSupervisionState
    ready_for_sender_free_shadow: bool
    live_execution_allowed: bool
    sender_import_allowed: bool
    signing_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    checks_evaluated: int
    schema_version: str = PR198_RUNTIME_SUPERVISION_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_runtime_supervision_evidence(
    bundle: RuntimeSupervisionEvidenceBundle,
) -> RuntimeSupervisionReadiness:
    """Evaluate PR-198 durable runtime-supervision evidence fail-closed."""

    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, code: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(code)

    _evaluate_dependencies(bundle.dependencies, check)
    _evaluate_strategies(bundle.strategies, check, warnings)
    _evaluate_queue(bundle.queue, check)
    _evaluate_shutdown(bundle.shutdown, check)
    _evaluate_active_surface(bundle.active_surface, check)
    _evaluate_artifacts(bundle.evidence_artifacts, check)

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    if ready:
        warnings.append("PR198_SENDER_FREE_ONLY_LIVE_SIGNING_AND_SEND_REMAIN_DENIED")

    return RuntimeSupervisionReadiness(
        state=(
            RuntimeSupervisionState.READY_FOR_SENDER_FREE_SHADOW
            if ready
            else RuntimeSupervisionState.BLOCKED
        ),
        ready_for_sender_free_shadow=ready,
        live_execution_allowed=False,
        sender_import_allowed=False,
        signing_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_hash=_sha256_payload(bundle),
        checks_evaluated=checks,
    )


def _evaluate_dependencies(
    dependencies: RuntimeDependencyEvidence,
    check: Callable[[bool, str], None],
) -> None:
    check(
        dependencies.production_factory_singleton,
        "PRODUCTION_FACTORY_NOT_SINGLETON",
    )
    check(
        dependencies.installed_command_singleton,
        "INSTALLED_COMMAND_NOT_SINGLETON",
    )
    check(dependencies.real_dependency_graph, "REAL_DEPENDENCY_GRAPH_MISSING")
    check(
        not dependencies.placeholder_dependencies_present,
        "PLACEHOLDER_DEPENDENCIES_PRESENT",
    )
    check(
        not dependencies.memory_only_authorities_present,
        "MEMORY_ONLY_AUTHORITIES_PRESENT",
    )


def _evaluate_strategies(
    strategies: tuple[StrategyTaskEvidence, ...],
    check: Callable[[bool, str], None],
    warnings: list[str],
) -> None:
    check(bool(strategies), "NO_STRATEGY_TASK_EVIDENCE")
    seen_names = {strategy.strategy_name for strategy in strategies}
    check(len(seen_names) == len(strategies), "DUPLICATE_STRATEGY_EVIDENCE")
    for strategy in strategies:
        name = strategy.strategy_name
        check(strategy.supervised, f"STRATEGY_NOT_SUPERVISED:{name}")
        check(strategy.restart_limit > 0, f"STRATEGY_RESTART_LIMIT_NOT_SET:{name}")
        check(
            strategy.restart_attempts <= strategy.restart_limit,
            f"STRATEGY_RESTART_LIMIT_EXCEEDED:{name}",
        )
        if strategy.required:
            check(
                strategy.state in {"running", "stopped-cleanly"},
                f"REQUIRED_STRATEGY_NOT_HEALTHY:{name}",
            )
        if strategy.state in {"failed", "restart-exhausted"}:
            check(
                strategy.readiness_false_on_failure,
                f"STRATEGY_FAILURE_NOT_READINESS_FALSE:{name}",
            )
            check(
                bool(strategy.terminal_reason_code),
                f"STRATEGY_FAILURE_REASON_MISSING:{name}",
            )
            check(
                strategy.exception_redacted,
                f"STRATEGY_FAILURE_EXCEPTION_NOT_REDACTED:{name}",
            )
        if not strategy.required and strategy.state in {"failed", "restart-exhausted"}:
            warnings.append(f"OPTIONAL_STRATEGY_TERMINAL:{name}")


def _evaluate_queue(
    queue: QueueLifecycleEvidence,
    check: Callable[[bool, str], None],
) -> None:
    check(queue.durable_queue, "QUEUE_NOT_DURABLE")
    check(
        queue.admission_closed_before_drain,
        "ADMISSION_NOT_CLOSED_BEFORE_DRAIN",
    )
    check(queue.single_consumer_owner, "SHUTDOWN_DRAIN_HAS_DOUBLE_CONSUMER_RISK")
    check(
        queue.expiry_releases_pending_lifecycle,
        "EXPIRY_DOES_NOT_RELEASE_PENDING_LIFECYCLE",
    )
    check(queue.tracker_state_durable, "TRACKER_STATE_NOT_DURABLE")
    check(queue.result_sink_durable, "RESULT_SINK_NOT_DURABLE")
    check(not queue.duplicate_processing_observed, "DUPLICATE_PROCESSING_OBSERVED")
    check(queue.max_queue_depth > 0, "QUEUE_MAX_DEPTH_NOT_SET")
    terminalized = queue.terminal_outcomes_written + queue.abandoned_or_requeued_items
    check(
        terminalized >= queue.pending_items_at_shutdown,
        "SHUTDOWN_PENDING_ITEMS_NOT_TERMINALIZED",
    )


def _evaluate_shutdown(
    shutdown: ShutdownDrainEvidence,
    check: Callable[[bool, str], None],
) -> None:
    check(shutdown.structured_concurrency, "STRUCTURED_CONCURRENCY_MISSING")
    check(shutdown.deadline_ms > 0, "SHUTDOWN_DEADLINE_NOT_SET")
    check(
        shutdown.deadline_ms <= MAX_SHUTDOWN_DEADLINE_MS,
        "SHUTDOWN_DEADLINE_TOO_LARGE",
    )
    check(shutdown.fallback_deadline_ms > 0, "SHUTDOWN_FALLBACK_DEADLINE_NOT_SET")
    check(
        shutdown.fallback_deadline_ms <= shutdown.deadline_ms,
        "SHUTDOWN_FALLBACK_NOT_BOUNDED_BY_DEADLINE",
    )
    check(shutdown.cancellation_acknowledged, "CANCELLATION_NOT_ACKNOWLEDGED")
    check(
        shutdown.owned_tasks_after_shutdown == 0,
        "OWNED_TASKS_LEFT_RUNNING_AFTER_SHUTDOWN",
    )
    check(
        shutdown.owned_tasks_after_shutdown <= shutdown.owned_tasks_before_shutdown,
        "OWNED_TASK_COUNT_INCREASED_DURING_SHUTDOWN",
    )
    check(
        shutdown.double_consumer_race_prevented,
        "DOUBLE_CONSUMER_RACE_NOT_PREVENTED",
    )
    check(shutdown.forced_shutdown_latch_written, "FORCED_SHUTDOWN_LATCH_MISSING")
    check(
        shutdown.terminal_queue_action in _ALLOWED_TERMINAL_QUEUE_ACTIONS,
        "TERMINAL_QUEUE_ACTION_NOT_DURABLE",
    )


def _evaluate_active_surface(
    active_surface: tuple[str, ...],
    check: Callable[[bool, str], None],
) -> None:
    present = set(active_surface)
    for capability in _FORBIDDEN_ACTIVE_SURFACE:
        check(capability not in present, f"FORBIDDEN_ACTIVE_SURFACE:{capability}")


def _evaluate_artifacts(
    artifacts: Mapping[str, str],
    check: Callable[[bool, str], None],
) -> None:
    for required_key in (
        "runtime_trace_sha256",
        "shutdown_trace_sha256",
        "queue_lifecycle_sha256",
    ):
        check(required_key in artifacts, f"SUPERVISION_ARTIFACT_MISSING:{required_key}")


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DurableRuntimeSupervisionError(f"{field} must be a non-empty string")
    return value.strip()


def _require_bool(value: bool, field: str) -> None:
    if not isinstance(value, bool):
        raise DurableRuntimeSupervisionError(f"{field} must be bool")


def _require_non_negative_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DurableRuntimeSupervisionError(f"{field} must be a non-negative integer")
    return value


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise DurableRuntimeSupervisionError(
            f"{field} must be a non-placeholder sha256"
        )
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise DurableRuntimeSupervisionError(
            f"{field} must be a non-placeholder git sha"
        )
    return lowered


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DurableRuntimeSupervisionError(f"{field} must be timezone-aware")


def _tuple_of_text(value: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise DurableRuntimeSupervisionError(f"{field} must be a sequence of strings")
    normalized = tuple(_require_text(item, field) for item in value)
    if len(normalized) != len(set(normalized)):
        raise DurableRuntimeSupervisionError(f"{field} must not contain duplicates")
    return normalized


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "MAX_SHUTDOWN_DEADLINE_MS",
    "PR198_RUNTIME_SUPERVISION_RESULT_SCHEMA",
    "PR198_RUNTIME_SUPERVISION_SCHEMA",
    "DurableRuntimeSupervisionError",
    "QueueLifecycleEvidence",
    "RuntimeDependencyEvidence",
    "RuntimeSupervisionEvidenceBundle",
    "RuntimeSupervisionReadiness",
    "RuntimeSupervisionState",
    "ShutdownDrainEvidence",
    "StrategyTaskEvidence",
    "evaluate_runtime_supervision_evidence",
]
