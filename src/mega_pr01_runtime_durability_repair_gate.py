"""MEGA-PR-01 V3 runtime correctness and durability repair gate.

Side-effect-free acceptance contract for IMPL-25..IMPL-38.  It does not
start providers, open databases, sign, send, or enable live execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

SCHEMA_ID = "mega-pr-01.runtime-durability-repair.v3"
REQUIRED_FINDINGS: tuple[str, ...] = tuple(f"IMPL-{i}" for i in range(25, 39))
_PLACEHOLDERS = {"", "0" * 64, "f" * 64, "placeholder", "todo", "sha256"}


def _sha256(value: str) -> bool:
    value = value.lower()
    return len(value) == 64 and value not in _PLACEHOLDERS and all(c in "0123456789abcdef" for c in value)


def _digest(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    sha256: str
    size_bytes: int
    materialized: bool = True

    def blockers(self, prefix: str) -> list[str]:
        out: list[str] = []
        if not self.materialized:
            out.append(f"{prefix}_NOT_MATERIALIZED")
        if not self.path or self.path.startswith("/") or ".." in self.path.split("/"):
            out.append(f"{prefix}_UNSAFE_PATH")
        if not _sha256(self.sha256):
            out.append(f"{prefix}_INVALID_SHA256")
        if self.size_bytes <= 0:
            out.append(f"{prefix}_EMPTY")
        return out


@dataclass(frozen=True)
class QueueRuntimeEvidence:
    atomic_expiry_terminalizes_pending: bool
    expiry_releases_or_terminalizes_dedupe: bool
    same_id_readmission_tested: bool
    critical_task_supervision: bool
    task_death_closes_readiness: bool
    terminal_failure_reason_persisted: bool
    bounded_tracker_result_and_reports: bool
    absolute_shutdown_owner: bool
    remaining_work_persisted_after_timeout: bool

    def blockers(self) -> list[str]:
        checks = {
            "QUEUE_EXPIRY_NOT_ATOMIC": self.atomic_expiry_terminalizes_pending,
            "DEDUPE_NOT_RELEASED_OR_TERMINALIZED": self.expiry_releases_or_terminalizes_dedupe,
            "SAME_ID_READMISSION_TEST_MISSING": self.same_id_readmission_tested,
            "CRITICAL_TASK_SUPERVISION_MISSING": self.critical_task_supervision,
            "TASK_DEATH_DOES_NOT_CLOSE_READINESS": self.task_death_closes_readiness,
            "TERMINAL_FAILURE_REASON_NOT_PERSISTED": self.terminal_failure_reason_persisted,
            "RUNTIME_COLLECTIONS_UNBOUNDED": self.bounded_tracker_result_and_reports,
            "SHUTDOWN_HAS_NO_ABSOLUTE_OWNER": self.absolute_shutdown_owner,
            "REMAINING_WORK_NOT_PERSISTED_AFTER_TIMEOUT": self.remaining_work_persisted_after_timeout,
        }
        return [code for code, ok in checks.items() if not ok]


@dataclass(frozen=True)
class PersistenceEvidence:
    async_deadline_provider_intake: bool
    dedicated_bounded_sqlite_writer: bool
    writer_health_in_readiness: bool
    monotonic_deadlines_boot_bound: bool
    cross_boot_reconciles_with_utc_or_indeterminate: bool
    semantic_idempotency_command_hashes: bool
    conflicting_replay_rejected: bool
    migration_identity_and_checksum_verified: bool
    single_writer_with_independent_read_connections: bool
    reservation_leases_fencing_and_recovery: bool

    def blockers(self) -> list[str]:
        checks = {
            "PROVIDER_INTAKE_BLOCKS_ASYNCIO": self.async_deadline_provider_intake,
            "SQLITE_WRITER_NOT_DEDICATED_OR_BOUNDED": self.dedicated_bounded_sqlite_writer,
            "WRITER_HEALTH_NOT_IN_READINESS": self.writer_health_in_readiness,
            "MONOTONIC_DEADLINE_NOT_BOOT_BOUND": self.monotonic_deadlines_boot_bound,
            "CROSS_BOOT_EXPIRY_NOT_RECONCILED": self.cross_boot_reconciles_with_utc_or_indeterminate,
            "IDEMPOTENCY_COMMAND_HASH_MISSING": self.semantic_idempotency_command_hashes,
            "IDEMPOTENCY_CONFLICT_NOT_REJECTED": self.conflicting_replay_rejected,
            "MIGRATION_IDENTITY_CHECKSUM_MISSING": self.migration_identity_and_checksum_verified,
            "SQLITE_WRITER_OWNERSHIP_INCOMPLETE": self.single_writer_with_independent_read_connections,
            "RESERVATION_RECOVERY_INCOMPLETE": self.reservation_leases_fencing_and_recovery,
        }
        return [code for code, ok in checks.items() if not ok]


@dataclass(frozen=True)
class OutboxWebhookSecretEvidence:
    outbox_claim_renew_ack_nack_retry_dlq: bool
    outbox_boot_generation_fencing: bool
    outbox_attempt_history_and_crash_recovery: bool
    pending_row_not_delivery_evidence: bool
    webhook_chain_stable_identity: bool
    webhook_delivery_metadata_non_authoritative: bool
    webhook_claim_token_and_unexpired_ack_cas: bool
    webhook_max_attempt_poison_dlq: bool
    webhook_size_retention_index_time_bounds: bool
    endpoint_origin_separate_from_secret: bool
    credential_path_query_forbidden: bool
    config_doctor_logs_fingerprints_redact_secrets: bool
    provider_errors_sanitized: bool

    def blockers(self) -> list[str]:
        checks = {
            "OUTBOX_STATE_MACHINE_MISSING": self.outbox_claim_renew_ack_nack_retry_dlq,
            "OUTBOX_BOOT_GENERATION_FENCING_MISSING": self.outbox_boot_generation_fencing,
            "OUTBOX_HISTORY_OR_CRASH_RECOVERY_MISSING": self.outbox_attempt_history_and_crash_recovery,
            "OUTBOX_PENDING_ROW_COUNTS_AS_DELIVERED": self.pending_row_not_delivery_evidence,
            "WEBHOOK_IDENTITY_NOT_CHAIN_STABLE": self.webhook_chain_stable_identity,
            "WEBHOOK_DELIVERY_METADATA_AUTHORITATIVE": self.webhook_delivery_metadata_non_authoritative,
            "WEBHOOK_ACK_NACK_NOT_FENCED": self.webhook_claim_token_and_unexpired_ack_cas,
            "WEBHOOK_POISON_NOT_DLQ_AT_MAX_ATTEMPTS": self.webhook_max_attempt_poison_dlq,
            "WEBHOOK_BOUNDS_OR_INDEXES_MISSING": self.webhook_size_retention_index_time_bounds,
            "ENDPOINT_ORIGIN_NOT_SEPARATE_FROM_SECRET": self.endpoint_origin_separate_from_secret,
            "CREDENTIAL_PATH_QUERY_ALLOWED": self.credential_path_query_forbidden,
            "RPC_SECRET_REDACTION_INCOMPLETE": self.config_doctor_logs_fingerprints_redact_secrets,
            "PROVIDER_ERRORS_LEAK_SECRETS": self.provider_errors_sanitized,
        }
        return [code for code, ok in checks.items() if not ok]


@dataclass(frozen=True)
class PaperMergeGateEvidence:
    accelerated_soak_hours: int
    bounded_cardinality_proven: bool
    task_death_readiness_proven: bool
    kill9_recovery_proven: bool
    webhook_reorder_retry_proven: bool
    outbox_exactly_once_proven: bool
    no_secret_bytes_in_artifacts: bool

    def blockers(self) -> list[str]:
        out: list[str] = []
        if self.accelerated_soak_hours < 72:
            out.append("ACCELERATED_LONG_SOAK_TOO_SHORT")
        checks = {
            "BOUNDED_CARDINALITY_NOT_PROVEN": self.bounded_cardinality_proven,
            "TASK_DEATH_READINESS_NOT_PROVEN": self.task_death_readiness_proven,
            "KILL9_RECOVERY_NOT_PROVEN": self.kill9_recovery_proven,
            "WEBHOOK_REORDER_RETRY_NOT_PROVEN": self.webhook_reorder_retry_proven,
            "OUTBOX_EXACTLY_ONCE_NOT_PROVEN": self.outbox_exactly_once_proven,
            "SECRET_BYTES_IN_ARTIFACTS": self.no_secret_bytes_in_artifacts,
        }
        out.extend(code for code, ok in checks.items() if not ok)
        return out


@dataclass(frozen=True)
class MegaPr01RuntimeDurabilityEvidence:
    schema_id: str
    findings: frozenset[str]
    evidence_refs: tuple[EvidenceRef, ...]
    queue_runtime: QueueRuntimeEvidence
    persistence: PersistenceEvidence
    outbox_webhook_secret: OutboxWebhookSecretEvidence
    paper_merge_gate: PaperMergeGateEvidence
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_access_requested: bool = False


@dataclass(frozen=True)
class MegaPr01RuntimeDurabilityReport:
    schema_id: str
    accepted: bool
    blockers: tuple[str, ...]
    covered_findings: tuple[str, ...]
    evidence_digest: str
    sender_free_paper_merge_review_allowed: bool
    operational_paper_ready_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool


def evaluate_mega_pr01_runtime_durability(evidence: MegaPr01RuntimeDurabilityEvidence) -> MegaPr01RuntimeDurabilityReport:
    blockers: list[str] = []
    if evidence.schema_id != SCHEMA_ID:
        blockers.append("SCHEMA_ID_MISMATCH")
    missing = set(REQUIRED_FINDINGS) - set(evidence.findings)
    extra = set(evidence.findings) - set(REQUIRED_FINDINGS)
    if missing:
        blockers.append("MISSING_FINDINGS:" + ",".join(sorted(missing)))
    if extra:
        blockers.append("UNEXPECTED_FINDINGS:" + ",".join(sorted(extra)))
    if not evidence.evidence_refs:
        blockers.append("NO_MATERIALIZED_EVIDENCE_REFS")
    for i, ref in enumerate(evidence.evidence_refs):
        blockers.extend(ref.blockers(f"EVIDENCE_REF_{i}"))
    blockers.extend(evidence.queue_runtime.blockers())
    blockers.extend(evidence.persistence.blockers())
    blockers.extend(evidence.outbox_webhook_secret.blockers())
    blockers.extend(evidence.paper_merge_gate.blockers())
    if evidence.live_execution_requested:
        blockers.append("LIVE_EXECUTION_REQUESTED")
    if evidence.signer_requested:
        blockers.append("SIGNER_REQUESTED")
    if evidence.sender_requested:
        blockers.append("SENDER_REQUESTED")
    if evidence.private_key_access_requested:
        blockers.append("PRIVATE_KEY_ACCESS_REQUESTED")
    unique = tuple(sorted(set(blockers)))
    digest = _digest([evidence.schema_id, *sorted(evidence.findings), *(r.sha256 for r in evidence.evidence_refs), *unique])
    accepted = not unique
    return MegaPr01RuntimeDurabilityReport(
        schema_id=SCHEMA_ID,
        accepted=accepted,
        blockers=unique,
        covered_findings=REQUIRED_FINDINGS,
        evidence_digest=digest,
        sender_free_paper_merge_review_allowed=accepted,
        operational_paper_ready_allowed=False,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
    )
