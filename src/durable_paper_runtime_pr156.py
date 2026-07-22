"""PR-156 structured durable paper runtime evidence gate.

This module is deliberately side-effect free. It does not start a runtime, open
SQLite, call providers/RPC/webhooks, sign, or submit. It defines the fail-closed
contract that the later structured paper runtime must satisfy before it can
claim sender-free paper readiness or real operational soak evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class PR156State(StrEnum):
    BLOCKED = "blocked"
    REVIEW_READY = "review-ready"


class PR156RuntimeError(ValueError):
    """Typed, redacted PR-156 evaluation error."""


REQUIRED_STAGES: tuple[str, ...] = (
    "runtime_truth",
    "discovery",
    "economic_kernel",
    "transaction_proof",
    "durable_lifecycle",
    "paper_outcome",
    "observability_export",
)

REQUIRED_DURABLE_TABLES: tuple[str, ...] = (
    "candidate",
    "attempt",
    "reservation",
    "plan",
    "simulation",
    "reconciliation",
    "outcome",
    "outbox",
)

REQUIRED_FAULTS: tuple[str, ...] = (
    "hanging_provider",
    "stage_timeout",
    "critical_task_crash",
    "db_lock",
    "db_corruption",
    "cancellation",
    "disk_full",
    "webhook_duplicate",
    "webhook_gap",
    "rpc_disagreement",
    "restart_each_stage",
)


@dataclass(frozen=True, slots=True)
class PR156StageBudget:
    stage_id: str
    deadline_ms: int
    max_attempts: int
    p95_latency_ms: int | None = None
    re_raises_cancelled_error: bool = True
    terminal_reason_code: str = "typed"

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.stage_id not in REQUIRED_STAGES:
            blockers.append(f"UNKNOWN_STAGE:{self.stage_id}")
        if self.deadline_ms <= 0:
            blockers.append(f"STAGE_DEADLINE_MISSING:{self.stage_id}")
        if self.max_attempts <= 0:
            blockers.append(f"STAGE_ATTEMPTS_MISSING:{self.stage_id}")
        if self.p95_latency_ms is not None and self.p95_latency_ms > self.deadline_ms:
            blockers.append(f"STAGE_P95_EXCEEDS_DEADLINE:{self.stage_id}")
        if not self.re_raises_cancelled_error:
            blockers.append(f"STAGE_SWALLOWS_CANCELLED_ERROR:{self.stage_id}")
        if not self.terminal_reason_code:
            blockers.append(f"STAGE_TERMINAL_REASON_MISSING:{self.stage_id}")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR156RuntimeTruthBinding:
    base_main_sha: str
    runtime_truth_hash: str
    policy_bundle_hash: str
    provider_admission_hash: str
    market_kernel_hash: str
    transaction_proof_hash: str
    generation: int = 1

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not _COMMIT_RE.fullmatch(self.base_main_sha):
            blockers.append("BASE_MAIN_SHA_INVALID")
        for name, value in (
            ("runtime_truth_hash", self.runtime_truth_hash),
            ("policy_bundle_hash", self.policy_bundle_hash),
            ("provider_admission_hash", self.provider_admission_hash),
            ("market_kernel_hash", self.market_kernel_hash),
            ("transaction_proof_hash", self.transaction_proof_hash),
        ):
            if not is_sha256_hex(value):
                blockers.append(f"HASH_INVALID:{name}")
        if self.generation <= 0:
            blockers.append("RUNTIME_TRUTH_GENERATION_INVALID")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR156DurableStoreEvidence:
    sqlite_authoritative: bool
    jsonl_authoritative: bool
    writer_actor: bool
    process_fencing: bool
    atomic_transition_outbox: bool
    tables: tuple[str, ...]
    backup_restore_hash: str

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.sqlite_authoritative:
            blockers.append("SQLITE_NOT_AUTHORITATIVE")
        if self.jsonl_authoritative:
            blockers.append("JSONL_STILL_AUTHORITATIVE")
        if not self.writer_actor:
            blockers.append("DEDICATED_WRITER_ACTOR_MISSING")
        if not self.process_fencing:
            blockers.append("PROCESS_FENCING_MISSING")
        if not self.atomic_transition_outbox:
            blockers.append("ATOMIC_LIFECYCLE_OUTBOX_MISSING")
        missing = [table for table in REQUIRED_DURABLE_TABLES if table not in set(self.tables)]
        for table in missing:
            blockers.append(f"DURABLE_TABLE_MISSING:{table}")
        if not is_sha256_hex(self.backup_restore_hash):
            blockers.append("BACKUP_RESTORE_HASH_INVALID")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR156ConcurrencyEvidence:
    runtime_supervisor: bool
    repeated_cycles: bool
    taskgroup_used: bool
    bounded_queues_tasks_cache: bool
    critical_failure_marks_not_ready: bool
    graceful_sigterm: bool
    no_orphan_tasks: bool
    stage_budgets: tuple[PR156StageBudget, ...]

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.runtime_supervisor:
            blockers.append("RUNTIME_SUPERVISOR_MISSING")
        if not self.repeated_cycles:
            blockers.append("RUNNER_NOT_CONTINUOUS")
        if not self.taskgroup_used:
            blockers.append("STRUCTURED_CONCURRENCY_MISSING")
        if not self.bounded_queues_tasks_cache:
            blockers.append("RESOURCE_BOUNDS_MISSING")
        if not self.critical_failure_marks_not_ready:
            blockers.append("CRITICAL_FAILURE_READINESS_GAP")
        if not self.graceful_sigterm:
            blockers.append("SIGTERM_PROTOCOL_MISSING")
        if not self.no_orphan_tasks:
            blockers.append("ORPHAN_TASK_RISK")
        observed = {budget.stage_id for budget in self.stage_budgets}
        for stage in REQUIRED_STAGES:
            if stage not in observed:
                blockers.append(f"STAGE_BUDGET_MISSING:{stage}")
        for budget in self.stage_budgets:
            blockers.extend(budget.blockers())
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR156TransportEvidence:
    response_size_limits: bool
    decompression_limits: bool
    redirect_denied: bool
    approved_host_egress: bool
    typed_retry_taxonomy: bool
    no_raw_secret_exceptions: bool

    def blockers(self) -> tuple[str, ...]:
        return tuple(
            code
            for code, ok in (
                ("RESPONSE_SIZE_LIMIT_MISSING", self.response_size_limits),
                ("DECOMPRESSION_LIMIT_MISSING", self.decompression_limits),
                ("REDIRECT_POLICY_MISSING", self.redirect_denied),
                ("EGRESS_ALLOWLIST_MISSING", self.approved_host_egress),
                ("TYPED_RETRY_TAXONOMY_MISSING", self.typed_retry_taxonomy),
                ("RAW_SECRET_EXCEPTION_RISK", self.no_raw_secret_exceptions),
            )
            if not ok
        )


@dataclass(frozen=True, slots=True)
class PR156WebhookEvidence:
    auth_header_verified: bool
    immediate_200_then_enqueue: bool
    durable_enqueue: bool
    persistent_dedup: bool
    duplicate_retry_handling: bool
    gap_backfill: bool

    def blockers(self) -> tuple[str, ...]:
        return tuple(
            code
            for code, ok in (
                ("WEBHOOK_AUTH_HEADER_NOT_VERIFIED", self.auth_header_verified),
                ("WEBHOOK_FAST_ACK_MISSING", self.immediate_200_then_enqueue),
                ("WEBHOOK_DURABLE_ENQUEUE_MISSING", self.durable_enqueue),
                ("WEBHOOK_DEDUP_NOT_PERSISTENT", self.persistent_dedup),
                ("WEBHOOK_DUPLICATE_RETRY_MISSING", self.duplicate_retry_handling),
                ("WEBHOOK_GAP_BACKFILL_MISSING", self.gap_backfill),
            )
            if not ok
        )


@dataclass(frozen=True, slots=True)
class PR156MultiRpcEvidence:
    independent_provider_groups: bool
    genesis_version_capability_checked: bool
    rooted_finality_consistency: bool
    url_aliases_not_counted_as_quorum: bool

    def blockers(self) -> tuple[str, ...]:
        return tuple(
            code
            for code, ok in (
                ("RPC_INDEPENDENCE_GROUPS_MISSING", self.independent_provider_groups),
                ("RPC_GENESIS_CAPABILITY_MISSING", self.genesis_version_capability_checked),
                ("RPC_FINALITY_CONSISTENCY_MISSING", self.rooted_finality_consistency),
                ("RPC_ALIAS_QUORUM_RISK", self.url_aliases_not_counted_as_quorum),
            )
            if not ok
        )


@dataclass(frozen=True, slots=True)
class PR156ObservabilityEvidence:
    safe_migrations: bool
    monotonic_projections: bool
    full_event_envelopes: bool
    deterministic_replay_hash: str
    metrics_complete: bool
    backup_restore_drill: bool

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for code, ok in (
            ("OBSERVABILITY_MIGRATIONS_UNSAFE", self.safe_migrations),
            ("OBSERVABILITY_PROJECTIONS_NOT_MONOTONIC", self.monotonic_projections),
            ("EVENT_ENVELOPES_INCOMPLETE", self.full_event_envelopes),
            ("METRICS_INCOMPLETE", self.metrics_complete),
            ("OBSERVABILITY_BACKUP_RESTORE_MISSING", self.backup_restore_drill),
        ):
            if not ok:
                blockers.append(code)
        if not is_sha256_hex(self.deterministic_replay_hash):
            blockers.append("REPLAY_HASH_INVALID")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR156ShadowHarnessEvidence:
    executable_sender_free_command: bool
    immutable_artifacts_hash: str
    no_placeholder_hashes: bool
    operator_review: bool
    soak_seconds: int
    sender_free: bool
    private_key_absent: bool
    fault_injection: tuple[str, ...]

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.executable_sender_free_command:
            blockers.append("SHADOW_COMMAND_MISSING")
        if not is_sha256_hex(self.immutable_artifacts_hash):
            blockers.append("SOAK_ARTIFACT_HASH_INVALID")
        if not self.no_placeholder_hashes:
            blockers.append("PLACEHOLDER_SOAK_HASHES_PRESENT")
        if not self.operator_review:
            blockers.append("OPERATOR_REVIEW_MISSING")
        if self.soak_seconds < 0:
            blockers.append("SOAK_DURATION_INVALID")
        if not self.sender_free:
            blockers.append("SENDER_PRESENT_IN_SOAK")
        if not self.private_key_absent:
            blockers.append("PRIVATE_KEY_PRESENT_IN_SOAK")
        observed = set(self.fault_injection)
        for fault in REQUIRED_FAULTS:
            if fault not in observed:
                blockers.append(f"FAULT_INJECTION_MISSING:{fault}")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR156Manifest:
    repo_full_name: str
    branch: str
    runtime_truth: PR156RuntimeTruthBinding
    durable_store: PR156DurableStoreEvidence
    concurrency: PR156ConcurrencyEvidence
    transport: PR156TransportEvidence
    webhook: PR156WebhookEvidence
    multi_rpc: PR156MultiRpcEvidence
    observability: PR156ObservabilityEvidence
    shadow_harness: PR156ShadowHarnessEvidence
    profitable_fixture_claim: bool = False
    healthy_idle_claim: bool = False
    live_claim: bool = False
    sender_enabled: bool = False


@dataclass(frozen=True, slots=True)
class PR156Decision:
    state: PR156State
    review_ready: bool
    paper_runtime_claim_allowed: bool
    healthy_idle_claim_allowed: bool
    live_claim_allowed: bool
    sender_submission_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    proof_hash: str
    metrics: Mapping[str, int | bool]


def evaluate_pr156(manifest: PR156Manifest) -> PR156Decision:
    blockers: list[str] = []
    warnings = ("PR156_REVIEW_ONLY_NO_ACTIVE_RUNTIME_WIRING",)

    if manifest.repo_full_name != "BobIvans/studious-pancake":
        blockers.append("REPO_MISMATCH")
    if not manifest.branch.startswith("pr-156-"):
        blockers.append("BRANCH_NAME_NOT_PR156")
    if manifest.live_claim:
        blockers.append("LIVE_CLAIM_FORBIDDEN_IN_PR156")
    if manifest.sender_enabled:
        blockers.append("SENDER_ENABLED_FORBIDDEN_IN_PR156")

    for part in (
        manifest.runtime_truth,
        manifest.durable_store,
        manifest.concurrency,
        manifest.transport,
        manifest.webhook,
        manifest.multi_rpc,
        manifest.observability,
        manifest.shadow_harness,
    ):
        blockers.extend(part.blockers())

    review_ready = not blockers
    proof_hash = sha256_json(
        {
            "domain": "flashloan-bot/pr156-durable-paper-runtime",
            "schema_version": "pr156.durable-paper-runtime.v1",
            "repo": manifest.repo_full_name,
            "branch": manifest.branch,
            "runtime_truth": manifest.runtime_truth.runtime_truth_hash,
            "policy": manifest.runtime_truth.policy_bundle_hash,
            "market": manifest.runtime_truth.market_kernel_hash,
            "transaction": manifest.runtime_truth.transaction_proof_hash,
            "backup": manifest.durable_store.backup_restore_hash,
            "replay": manifest.observability.deterministic_replay_hash,
            "soak": manifest.shadow_harness.immutable_artifacts_hash,
            "stage_ids": sorted(b.stage_id for b in manifest.concurrency.stage_budgets),
            "faults": sorted(manifest.shadow_harness.fault_injection),
        }
    )
    return PR156Decision(
        state=PR156State.REVIEW_READY if review_ready else PR156State.BLOCKED,
        review_ready=review_ready,
        paper_runtime_claim_allowed=review_ready and manifest.profitable_fixture_claim,
        healthy_idle_claim_allowed=review_ready and manifest.healthy_idle_claim,
        live_claim_allowed=False,
        sender_submission_allowed=False,
        blockers=tuple(blockers),
        warnings=warnings,
        proof_hash=proof_hash,
        metrics={
            "stage_budget_count": len(manifest.concurrency.stage_budgets),
            "fault_count": len(manifest.shadow_harness.fault_injection),
            "durable_table_count": len(manifest.durable_store.tables),
            "sender_free": manifest.shadow_harness.sender_free,
        },
    )


def assert_pr156_review_ready(manifest: PR156Manifest) -> PR156Decision:
    decision = evaluate_pr156(manifest)
    if not decision.review_ready:
        raise PR156RuntimeError("PR156_BLOCKED:" + ",".join(decision.blockers))
    return decision


def sha256_json(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_sha256_hex(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def make_stage_budgets(deadline_ms: int = 1_000) -> tuple[PR156StageBudget, ...]:
    return tuple(
        PR156StageBudget(stage_id=stage, deadline_ms=deadline_ms, max_attempts=1)
        for stage in REQUIRED_STAGES
    )
