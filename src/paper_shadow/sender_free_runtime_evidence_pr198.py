"""PR-198 sender-free runtime evidence gate.

This module is deliberately offline and sender-free. It validates already
materialized runtime, replay, shadow, soak, chaos and acceptance evidence before
the project may be considered ready to request PR-199 signer/submission work.
It never imports a sender, signs, submits, opens live mode or mutates runtime
state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR198_SCHEMA_VERSION = "pr198.sender-free-runtime-evidence.v1"
PR198_RESULT_SCHEMA_VERSION = "pr198.sender-free-runtime-evidence-result.v1"
PR197_EVIDENCE_NAME = "pr197.accepted-atomic-execution-economic-kernel"
MIN_REAL_SOAK_DURATION = timedelta(days=2)
REQUIRED_COMPOSITION_STAGES = (
    "ingest-inbox",
    "normalization",
    "candidate",
    "rooted-state",
    "plan",
    "compile",
    "exact-simulate",
    "durable-outcome",
)
REQUIRED_FAULT_SCENARIOS = (
    "rpc-disagreement",
    "provider-429-timeout",
    "webhook-duplicate-gap",
    "sqlite-busy-crash",
    "clock-jump",
    "provider-drift",
    "blockhash-expiry",
    "shutdown-mid-attempt",
)
REQUIRED_HASH_KEYS = (
    "commit_sha",
    "image_digest_sha256",
    "lock_sha256",
    "config_generation_sha256",
    "protocol_snapshot_sha256",
    "replay_corpus_sha256",
    "shadow_outcome_schema_sha256",
    "redaction_policy_sha256",
)
REQUIRED_SLO_KEYS = (
    "ingest_lag_ms",
    "quote_build_age_ms",
    "plan_latency_ms",
    "simulation_latency_ms",
    "db_contention_ms",
    "memory_growth_bytes",
    "fd_growth_count",
    "task_growth_count",
)
_FORBIDDEN_RUNTIME_CAPABILITIES = (
    "signing-key-present",
    "sender-module-present",
    "jito-submit-endpoint-present",
    "live-permit-present",
    "live-capability-enabled",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SenderFreeRuntimeEvidenceError(ValueError):
    """Raised when PR-198 runtime evidence is malformed."""


class SenderFreeRuntimeState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_PR199_REVIEW = "ready-for-pr199-review"


@dataclass(frozen=True, slots=True)
class AcceptedPrerequisiteEvidence:
    name: str
    sha256: str
    source_commit: str
    accepted: bool
    reviewed_by: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "prerequisite.name"))
        object.__setattr__(
            self,
            "sha256",
            _require_sha256(self.sha256, "prerequisite.sha256"),
        )
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "prerequisite.source_commit"),
        )
        _require_bool(self.accepted, "prerequisite.accepted")
        object.__setattr__(
            self,
            "reviewed_by",
            _require_text(self.reviewed_by, "prerequisite.reviewed_by"),
        )
        _require_aware(self.reviewed_at, "prerequisite.reviewed_at")


@dataclass(frozen=True, slots=True)
class CompositionStageEvidence:
    stage: str
    evidence_hash: str
    deterministic: bool
    durable: bool
    terminal_outcome_written: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _require_text(self.stage, "stage"))
        object.__setattr__(
            self,
            "evidence_hash",
            _require_sha256(self.evidence_hash, "stage.evidence_hash"),
        )
        _require_bool(self.deterministic, "stage.deterministic")
        _require_bool(self.durable, "stage.durable")
        _require_bool(self.terminal_outcome_written, "stage.terminal_outcome_written")


@dataclass(frozen=True, slots=True)
class DurableRuntimeEvidence:
    queue_fenced_by_pr195: bool
    outbox_fenced_by_pr195: bool
    bounded_concurrency: bool
    backpressure_enabled: bool
    graceful_shutdown_verified: bool
    restart_generations_tested: int
    duplicate_attempt_generations: int
    missing_terminal_outcomes: int
    max_open_work_items: int

    def __post_init__(self) -> None:
        for field_name in (
            "queue_fenced_by_pr195",
            "outbox_fenced_by_pr195",
            "bounded_concurrency",
            "backpressure_enabled",
            "graceful_shutdown_verified",
        ):
            _require_bool(getattr(self, field_name), field_name)
        for field_name in (
            "restart_generations_tested",
            "duplicate_attempt_generations",
            "missing_terminal_outcomes",
            "max_open_work_items",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    raw_input_corpus_sha256: str
    protocol_snapshot_sha256: str
    replay_output_sha256: str
    deterministic_replay: bool
    ambient_network_disabled: bool
    runtime_db_secrets_required: bool
    replayed_attempts: int
    mismatched_replays: int

    def __post_init__(self) -> None:
        for field_name in (
            "raw_input_corpus_sha256",
            "protocol_snapshot_sha256",
            "replay_output_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        for field_name in (
            "deterministic_replay",
            "ambient_network_disabled",
            "runtime_db_secrets_required",
        ):
            _require_bool(getattr(self, field_name), field_name)
        for field_name in ("replayed_attempts", "mismatched_replays"):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class ShadowOutcomeEvidence:
    would_submit_identity_hash: str
    rejection_reason: str
    costs_lamports: int
    expected_profit_lamports: int
    source_slot: int
    min_context_slot: int
    freshness_ms: int
    evidence_hash: str
    redacted: bool
    immutable: bool

    def __post_init__(self) -> None:
        for field_name in ("would_submit_identity_hash", "evidence_hash"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "rejection_reason",
            _require_text(self.rejection_reason, "shadow.rejection_reason"),
        )
        for field_name in (
            "costs_lamports",
            "expected_profit_lamports",
            "source_slot",
            "min_context_slot",
            "freshness_ms",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(getattr(self, field_name), field_name),
            )
        _require_bool(self.redacted, "shadow.redacted")
        _require_bool(self.immutable, "shadow.immutable")


@dataclass(frozen=True, slots=True)
class RealSoakEvidence:
    started_at: datetime
    ended_at: datetime
    non_synthetic_mainnet: bool
    read_only: bool
    trading_wallet_used: bool
    attempts_observed: int
    terminal_sender_free_outcomes: int
    evidence_bundle_sha256: str
    human_acceptance_reviewer: str
    human_accepted_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.started_at, "soak.started_at")
        _require_aware(self.ended_at, "soak.ended_at")
        if self.ended_at <= self.started_at:
            raise SenderFreeRuntimeEvidenceError("soak must end after it starts")
        for field_name in ("non_synthetic_mainnet", "read_only", "trading_wallet_used"):
            _require_bool(getattr(self, field_name), f"soak.{field_name}")
        for field_name in ("attempts_observed", "terminal_sender_free_outcomes"):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "evidence_bundle_sha256",
            _require_sha256(self.evidence_bundle_sha256, "soak.evidence_bundle_sha256"),
        )
        object.__setattr__(
            self,
            "human_acceptance_reviewer",
            _require_text(
                self.human_acceptance_reviewer,
                "soak.human_acceptance_reviewer",
            ),
        )
        _require_aware(self.human_accepted_at, "soak.human_accepted_at")


@dataclass(frozen=True, slots=True)
class FaultInjectionEvidence:
    scenario: str
    injected: bool
    terminal_outcome_preserved: bool
    duplicate_generation_created: bool
    evidence_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario",
            _require_text(self.scenario, "fault.scenario"),
        )
        for field_name in (
            "injected",
            "terminal_outcome_preserved",
            "duplicate_generation_created",
        ):
            _require_bool(getattr(self, field_name), f"fault.{field_name}")
        object.__setattr__(
            self,
            "evidence_hash",
            _require_sha256(self.evidence_hash, "fault.evidence_hash"),
        )


@dataclass(frozen=True, slots=True)
class RuntimeMetricsEvidence:
    observed: Mapping[str, int]
    thresholds: Mapping[str, int]
    unexplained_task_growth: bool
    unexplained_fd_growth: bool
    unexplained_db_growth: bool

    def __post_init__(self) -> None:
        if not self.observed or not self.thresholds:
            raise SenderFreeRuntimeEvidenceError(
                "metrics observed/thresholds are required"
            )
        for mapping_name, values in (
            ("observed", self.observed),
            ("thresholds", self.thresholds),
        ):
            for key, value in values.items():
                _require_text(str(key), f"metrics.{mapping_name}.key")
                _require_non_negative_int(value, f"metrics.{mapping_name}.{key}")
        for field_name in (
            "unexplained_task_growth",
            "unexplained_fd_growth",
            "unexplained_db_growth",
        ):
            _require_bool(getattr(self, field_name), f"metrics.{field_name}")


@dataclass(frozen=True, slots=True)
class EvidenceBundleIdentity:
    artifact_hashes: Mapping[str, str]
    signed: bool
    redacted: bool
    immutable: bool
    independent_verifier: str
    verifier_needs_runtime_db_secrets: bool
    acceptance_signature_sha256: str

    def __post_init__(self) -> None:
        if not self.artifact_hashes:
            raise SenderFreeRuntimeEvidenceError("artifact hashes are required")
        for key, value in self.artifact_hashes.items():
            _require_text(str(key), "artifact_hash.key")
            _require_sha256(value, f"artifact_hash.{key}")
        for field_name in (
            "signed",
            "redacted",
            "immutable",
            "verifier_needs_runtime_db_secrets",
        ):
            _require_bool(getattr(self, field_name), f"bundle.{field_name}")
        object.__setattr__(
            self,
            "independent_verifier",
            _require_text(self.independent_verifier, "bundle.independent_verifier"),
        )
        object.__setattr__(
            self,
            "acceptance_signature_sha256",
            _require_sha256(
                self.acceptance_signature_sha256,
                "bundle.acceptance_signature_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class SenderFreeRuntimeEvidenceBundle:
    source_commit: str
    prerequisite: AcceptedPrerequisiteEvidence
    composition_stages: tuple[CompositionStageEvidence, ...]
    durable_runtime: DurableRuntimeEvidence
    replay: ReplayEvidence
    shadow_outcomes: tuple[ShadowOutcomeEvidence, ...]
    real_soak: RealSoakEvidence
    fault_injections: tuple[FaultInjectionEvidence, ...]
    metrics: RuntimeMetricsEvidence
    evidence_bundle: EvidenceBundleIdentity
    runtime_capabilities_present: tuple[str, ...]
    assembled_at: datetime
    assembled_by: str
    schema_version: str = PR198_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR198_SCHEMA_VERSION:
            raise SenderFreeRuntimeEvidenceError("unsupported PR-198 schema")
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        for field_name in (
            "composition_stages",
            "shadow_outcomes",
            "fault_injections",
            "runtime_capabilities_present",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "runtime_capabilities_present",
            _tuple_of_text(
                self.runtime_capabilities_present,
                "runtime_capabilities_present",
            ),
        )
        _require_aware(self.assembled_at, "assembled_at")
        object.__setattr__(
            self, "assembled_by", _require_text(self.assembled_by, "assembled_by")
        )


@dataclass(frozen=True, slots=True)
class SenderFreeRuntimeReadiness:
    state: SenderFreeRuntimeState
    ready_for_pr199_review: bool
    live_execution_allowed: bool
    sender_import_allowed: bool
    signing_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    checks_evaluated: int
    schema_version: str = PR198_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_sender_free_runtime_evidence(
    bundle: SenderFreeRuntimeEvidenceBundle,
) -> SenderFreeRuntimeReadiness:
    """Evaluate PR-198 evidence without enabling any sender or live capability."""

    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, code: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(code)

    _evaluate_prerequisite(bundle, check)
    _evaluate_composition(bundle.composition_stages, check)
    _evaluate_durable_runtime(bundle.durable_runtime, check)
    _evaluate_replay(bundle.replay, check)
    _evaluate_shadow_outcomes(bundle.shadow_outcomes, check)
    _evaluate_real_soak(bundle.real_soak, check)
    _evaluate_faults(bundle.fault_injections, check)
    _evaluate_metrics(bundle.metrics, check)
    _evaluate_evidence_bundle(bundle.evidence_bundle, check)
    _evaluate_sender_free_surface(bundle.runtime_capabilities_present, check)

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    if ready:
        warnings.append("PR198_REVIEW_ONLY_SENDER_AND_LIVE_REMAIN_DENIED")
    return SenderFreeRuntimeReadiness(
        state=(
            SenderFreeRuntimeState.READY_FOR_PR199_REVIEW
            if ready
            else SenderFreeRuntimeState.BLOCKED
        ),
        ready_for_pr199_review=ready,
        live_execution_allowed=False,
        sender_import_allowed=False,
        signing_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_hash=_sha256_payload(bundle),
        checks_evaluated=checks,
    )


def _evaluate_prerequisite(
    bundle: SenderFreeRuntimeEvidenceBundle,
    check: Callable[[bool, str], None],
) -> None:
    prerequisite = bundle.prerequisite
    check(prerequisite.name == PR197_EVIDENCE_NAME, "PR197_WRONG_EVIDENCE_NAME")
    check(prerequisite.accepted, "PR197_EVIDENCE_NOT_ACCEPTED")
    check(bool(prerequisite.reviewed_by.strip()), "PR197_REVIEWER_MISSING")
    check(
        prerequisite.source_commit == bundle.source_commit,
        "PR197_SOURCE_COMMIT_MISMATCH",
    )
    check(
        prerequisite.reviewed_at <= bundle.assembled_at, "PR197_REVIEW_AFTER_ASSEMBLY"
    )


def _evaluate_composition(
    stages: tuple[CompositionStageEvidence, ...],
    check: Callable[[bool, str], None],
) -> None:
    observed_order = tuple(stage.stage for stage in stages)
    check(
        observed_order == REQUIRED_COMPOSITION_STAGES, "COMPOSITION_ROOT_ORDER_INVALID"
    )
    for stage in stages:
        check(stage.deterministic, f"STAGE_NOT_DETERMINISTIC:{stage.stage}")
        check(stage.durable, f"STAGE_NOT_DURABLE:{stage.stage}")
        if stage.stage == "durable-outcome":
            check(
                stage.terminal_outcome_written,
                "DURABLE_OUTCOME_STAGE_MISSING_TERMINAL_WRITE",
            )


def _evaluate_durable_runtime(
    runtime: DurableRuntimeEvidence,
    check: Callable[[bool, str], None],
) -> None:
    check(runtime.queue_fenced_by_pr195, "QUEUE_NOT_FENCED_BY_PR195")
    check(runtime.outbox_fenced_by_pr195, "OUTBOX_NOT_FENCED_BY_PR195")
    check(runtime.bounded_concurrency, "CONCURRENCY_NOT_BOUNDED")
    check(runtime.backpressure_enabled, "BACKPRESSURE_NOT_ENABLED")
    check(runtime.graceful_shutdown_verified, "GRACEFUL_SHUTDOWN_NOT_VERIFIED")
    check(runtime.restart_generations_tested > 0, "RESTART_INJECTION_NOT_TESTED")
    check(runtime.duplicate_attempt_generations == 0, "DUPLICATE_ATTEMPT_GENERATION")
    check(runtime.missing_terminal_outcomes == 0, "MISSING_TERMINAL_OUTCOME")
    check(runtime.max_open_work_items > 0, "MAX_OPEN_WORK_ITEMS_NOT_SET")


def _evaluate_replay(
    replay: ReplayEvidence,
    check: Callable[[bool, str], None],
) -> None:
    check(replay.deterministic_replay, "REPLAY_NOT_DETERMINISTIC")
    check(replay.ambient_network_disabled, "REPLAY_CAN_USE_AMBIENT_NETWORK")
    check(not replay.runtime_db_secrets_required, "REPLAY_REQUIRES_RUNTIME_DB_SECRETS")
    check(replay.replayed_attempts > 0, "REPLAY_CORPUS_EMPTY")
    check(replay.mismatched_replays == 0, "REPLAY_MISMATCH_DETECTED")


def _evaluate_shadow_outcomes(
    outcomes: tuple[ShadowOutcomeEvidence, ...],
    check: Callable[[bool, str], None],
) -> None:
    check(bool(outcomes), "SHADOW_OUTCOME_CORPUS_EMPTY")
    identities = {outcome.would_submit_identity_hash for outcome in outcomes}
    check(len(identities) == len(outcomes), "DUPLICATE_WOULD_SUBMIT_IDENTITY")
    for outcome in outcomes:
        check(outcome.immutable, "SHADOW_OUTCOME_NOT_IMMUTABLE")
        check(outcome.redacted, "SHADOW_OUTCOME_NOT_REDACTED")
        check(
            outcome.min_context_slot <= outcome.source_slot, "SHADOW_SLOT_ORDER_INVALID"
        )


def _evaluate_real_soak(
    soak: RealSoakEvidence,
    check: Callable[[bool, str], None],
) -> None:
    check(
        soak.ended_at - soak.started_at >= MIN_REAL_SOAK_DURATION, "REAL_SOAK_TOO_SHORT"
    )
    check(soak.non_synthetic_mainnet, "REAL_SOAK_NOT_MAINNET")
    check(soak.read_only, "REAL_SOAK_NOT_READ_ONLY")
    check(not soak.trading_wallet_used, "REAL_SOAK_USED_TRADING_WALLET")
    check(soak.attempts_observed > 0, "REAL_SOAK_ATTEMPTS_EMPTY")
    check(
        soak.terminal_sender_free_outcomes == soak.attempts_observed,
        "REAL_SOAK_MISSING_TERMINAL_OUTCOMES",
    )
    check(soak.human_accepted_at >= soak.ended_at, "SOAK_ACCEPTED_BEFORE_END")


def _evaluate_faults(
    faults: tuple[FaultInjectionEvidence, ...],
    check: Callable[[bool, str], None],
) -> None:
    fault_by_name = {fault.scenario: fault for fault in faults}
    check(len(fault_by_name) == len(faults), "DUPLICATE_FAULT_SCENARIO")
    for scenario in REQUIRED_FAULT_SCENARIOS:
        fault = fault_by_name.get(scenario)
        check(fault is not None, f"FAULT_SCENARIO_MISSING:{scenario}")
        if fault is None:
            continue
        check(fault.injected, f"FAULT_NOT_INJECTED:{scenario}")
        check(
            fault.terminal_outcome_preserved,
            f"FAULT_TERMINAL_OUTCOME_NOT_PRESERVED:{scenario}",
        )
        check(
            not fault.duplicate_generation_created,
            f"FAULT_CREATED_DUPLICATE_GENERATION:{scenario}",
        )


def _evaluate_metrics(
    metrics: RuntimeMetricsEvidence,
    check: Callable[[bool, str], None],
) -> None:
    for key in REQUIRED_SLO_KEYS:
        check(key in metrics.observed, f"SLO_OBSERVED_MISSING:{key}")
        check(key in metrics.thresholds, f"SLO_THRESHOLD_MISSING:{key}")
        observed = metrics.observed.get(key)
        threshold = metrics.thresholds.get(key)
        if observed is not None and threshold is not None:
            check(observed <= threshold, f"SLO_THRESHOLD_EXCEEDED:{key}")
    check(not metrics.unexplained_task_growth, "UNEXPLAINED_TASK_GROWTH")
    check(not metrics.unexplained_fd_growth, "UNEXPLAINED_FD_GROWTH")
    check(not metrics.unexplained_db_growth, "UNEXPLAINED_DB_GROWTH")


def _evaluate_evidence_bundle(
    bundle: EvidenceBundleIdentity,
    check: Callable[[bool, str], None],
) -> None:
    for key in REQUIRED_HASH_KEYS:
        check(key in bundle.artifact_hashes, f"EVIDENCE_HASH_MISSING:{key}")
    check(bundle.signed, "EVIDENCE_BUNDLE_NOT_SIGNED")
    check(bundle.redacted, "EVIDENCE_BUNDLE_NOT_REDACTED")
    check(bundle.immutable, "EVIDENCE_BUNDLE_NOT_IMMUTABLE")
    check(
        bool(bundle.independent_verifier.strip()),
        "INDEPENDENT_VERIFIER_MISSING",
    )
    check(
        not bundle.verifier_needs_runtime_db_secrets,
        "INDEPENDENT_VERIFIER_NEEDS_RUNTIME_DB_SECRETS",
    )


def _evaluate_sender_free_surface(
    capabilities: tuple[str, ...],
    check: Callable[[bool, str], None],
) -> None:
    present = set(capabilities)
    for capability in _FORBIDDEN_RUNTIME_CAPABILITIES:
        check(capability not in present, f"FORBIDDEN_RUNTIME_CAPABILITY:{capability}")


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SenderFreeRuntimeEvidenceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_bool(value: bool, field: str) -> None:
    if not isinstance(value, bool):
        raise SenderFreeRuntimeEvidenceError(f"{field} must be bool")


def _require_non_negative_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SenderFreeRuntimeEvidenceError(f"{field} must be a non-negative integer")
    return value


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise SenderFreeRuntimeEvidenceError(
            f"{field} must be a non-placeholder sha256"
        )
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise SenderFreeRuntimeEvidenceError(
            f"{field} must be a non-placeholder git sha"
        )
    return lowered


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SenderFreeRuntimeEvidenceError(f"{field} must be timezone-aware")


def _tuple_of_text(value: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise SenderFreeRuntimeEvidenceError(f"{field} must be a sequence of strings")
    normalized = tuple(_require_text(item, field) for item in value)
    if len(normalized) != len(set(normalized)):
        raise SenderFreeRuntimeEvidenceError(f"{field} must not contain duplicates")
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
    "AcceptedPrerequisiteEvidence",
    "CompositionStageEvidence",
    "DurableRuntimeEvidence",
    "EvidenceBundleIdentity",
    "FaultInjectionEvidence",
    "MIN_REAL_SOAK_DURATION",
    "PR197_EVIDENCE_NAME",
    "PR198_RESULT_SCHEMA_VERSION",
    "PR198_SCHEMA_VERSION",
    "REQUIRED_COMPOSITION_STAGES",
    "REQUIRED_FAULT_SCENARIOS",
    "REQUIRED_HASH_KEYS",
    "REQUIRED_SLO_KEYS",
    "RealSoakEvidence",
    "ReplayEvidence",
    "RuntimeMetricsEvidence",
    "SenderFreeRuntimeEvidenceBundle",
    "SenderFreeRuntimeEvidenceError",
    "SenderFreeRuntimeReadiness",
    "SenderFreeRuntimeState",
    "ShadowOutcomeEvidence",
    "evaluate_sender_free_runtime_evidence",
]
