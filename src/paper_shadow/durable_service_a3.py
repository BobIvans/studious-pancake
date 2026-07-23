"""Installed sender-free paper service backed by the roadmap PR-02 authority.

The former A3 cycle/outbox tables are retained only as compatibility projections.
The authoritative intent, terminal record, ownership lease, and outbox event are
committed by :class:`UnifiedLifecycleAuthority` in the PR-041/PR-182 database.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import time

from src.config.runtime import RuntimeConfig
from src.durability.unified_authority_pr02 import (
    AuthorityFence,
    UnifiedLifecycleAuthority,
)
from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeReport,
)

A3_SCHEMA = "roadmap-pr02.a3-compatibility-projection.v1"
A3_DEFAULT_DB_PATH = Path(".runtime/paper-service.sqlite3")
A3_DEFAULT_OWNER_ID = "installed-durable-paper-service"
A3_B3_EVIDENCE_MISSING = "blocked_a3_b3_provider_evidence_missing"
A3_RUNTIME_UNWIRED = "blocked_a3_exact_attempt_runtime_unwired"
A3_RUNTIME_TIMEOUT = "blocked_a3_global_cycle_deadline_exceeded"
A3_BATCH_SOURCE_FAILED = "blocked_a3_batch_source_failed"


class A3PaperServiceStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    RECONCILED_PAPER_SUCCESS = "RECONCILED_PAPER_SUCCESS"
    RECONCILED_PAPER_FAILURE = "RECONCILED_PAPER_FAILURE"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class A3ProviderEvidenceState:
    """B3 evidence admission state consumed by the installed A3 service."""

    provider_evidence_hash: str
    ready: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _is_sha256(self.provider_evidence_hash):
            raise ValueError("provider_evidence_hash must be lowercase sha256")
        if self.ready and self.blockers:
            raise ValueError("ready provider evidence cannot carry blockers")
        if not self.ready and not self.blockers:
            raise ValueError("blocked provider evidence needs a reason")
        object.__setattr__(self, "blockers", _dedupe(self.blockers))

    @classmethod
    def missing_b3(cls, config: RuntimeConfig) -> "A3ProviderEvidenceState":
        payload = {
            "schema": A3_SCHEMA,
            "configuration": _safe_config_fingerprint(config),
            "reason": A3_B3_EVIDENCE_MISSING,
        }
        return cls(
            provider_evidence_hash=_hash_json(payload),
            ready=False,
            blockers=(A3_B3_EVIDENCE_MISSING,),
        )

    def to_json(self) -> dict[str, object]:
        return {
            "provider_evidence_hash": self.provider_evidence_hash,
            "ready": self.ready,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class A3ExactAttemptBatch:
    """Exact-attempt work admitted into one durable service cycle."""

    evidence: A3ProviderEvidenceState
    items: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True, slots=True)
class InstalledPaperServiceConfig:
    db_path: Path = A3_DEFAULT_DB_PATH
    run_id: str = "installed-paper-service"
    source_surface: str = "installed-cli"
    owner_id: str = A3_DEFAULT_OWNER_ID
    cycle_deadline_seconds: float = 30.0
    lease_ttl_ns: int = 30_000_000_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        if not self.run_id.strip():
            raise ValueError("run_id is required")
        if not self.source_surface.strip() or not self.owner_id.strip():
            raise ValueError("source_surface and owner_id are required")
        if self.cycle_deadline_seconds <= 0:
            raise ValueError("cycle_deadline_seconds must be positive")
        if self.lease_ttl_ns <= 0:
            raise ValueError("lease_ttl_ns must be positive")


@dataclass(frozen=True, slots=True)
class InstalledDurablePaperServiceReport:
    cycle_id: str
    status: A3PaperServiceStatus
    terminal_reason: str
    db_path: str
    provider_evidence_hash: str
    report_hash: str
    ready_for_next_cycle: bool
    sequence: int
    sender_imported: bool = False
    submission_allowed: bool = False
    live_enabled: bool = False
    source_surface: str = "installed-cli"
    records: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    b3_blockers: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.live_enabled:
            raise ValueError("A3 service cannot enable live")
        if self.sender_imported or self.submission_allowed:
            if self.status is not A3PaperServiceStatus.INDETERMINATE:
                raise ValueError(
                    "unsafe sender/submission evidence must be indeterminate"
                )
        if not _is_sha256(self.provider_evidence_hash):
            raise ValueError("provider_evidence_hash must be lowercase sha256")
        if not _is_sha256(self.report_hash):
            raise ValueError("report_hash must be lowercase sha256")
        object.__setattr__(self, "records", _record_tuple(self.records))
        object.__setattr__(self, "b3_blockers", _dedupe(self.b3_blockers))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": A3_SCHEMA,
            "cycle_id": self.cycle_id,
            "sequence": self.sequence,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason,
            "db_path": self.db_path,
            "provider_evidence_hash": self.provider_evidence_hash,
            "report_hash": self.report_hash,
            "ready_for_next_cycle": self.ready_for_next_cycle,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
            "live_enabled": self.live_enabled,
            "source_surface": self.source_surface,
            "b3_blockers": list(self.b3_blockers),
            "records": [dict(item) for item in self.records],
        }


ExactAttemptBatchSource = Callable[[], A3ExactAttemptBatch]
A3RuntimeCycle = Callable[[str, Sequence[object]], Awaitable[ExactAttemptRuntimeReport]]


class InstalledDurablePaperService:
    """Installed paper service using the single PR-02 SQLite authority."""

    def __init__(
        self,
        config: RuntimeConfig,
        service_config: InstalledPaperServiceConfig | None = None,
        *,
        batch_source: ExactAttemptBatchSource | None = None,
        runtime_cycle: A3RuntimeCycle | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
        authority: UnifiedLifecycleAuthority | None = None,
    ) -> None:
        self.runtime_config = config
        self.config = service_config or InstalledPaperServiceConfig()
        self.batch_source = batch_source or self._default_blocked_batch
        self.runtime_cycle = runtime_cycle
        # Retained for constructor compatibility. Correctness-sensitive ownership
        # is read by the injected/default TimeAuthority inside PR-02.
        self.clock_ns = clock_ns
        identity = _config_identity(config)
        self.authority = authority or UnifiedLifecycleAuthority(
            self.config.db_path,
            release_digest=identity,
            policy_bundle_hash=identity,
            owner_id=self.config.owner_id,
            lease_ttl_ns=self.config.lease_ttl_ns,
            environment=_runtime_environment(config),
            cluster_genesis=_cluster_genesis(config),
        )
        self._owns_authority = authority is None

    def close(self) -> None:
        if self._owns_authority:
            self.authority.close()

    def __enter__(self) -> "InstalledDurablePaperService":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    async def run_once(self) -> InstalledDurablePaperServiceReport:
        sequence = self.authority.next_cycle_sequence(self.config.run_id)
        cycle_id = self._cycle_id(sequence)
        fence = self.authority.begin_cycle_intent(
            run_id=self.config.run_id,
            sequence=sequence,
            config_fingerprint=_safe_config_fingerprint(self.runtime_config),
            source_surface=self.config.source_surface,
        )
        try:
            batch = self.batch_source()
        except Exception as exc:
            report = self._indeterminate_report(
                cycle_id,
                sequence,
                A3ProviderEvidenceState(
                    provider_evidence_hash=_hash_json(
                        {"cycle_id": cycle_id, "source": "batch-source"}
                    ),
                    ready=False,
                    blockers=(A3_BATCH_SOURCE_FAILED,),
                ),
                f"{A3_BATCH_SOURCE_FAILED}_{type(exc).__name__}",
            )
            self._commit(fence, report)
            return report
        self.authority.bind_provider_evidence(
            fence,
            provider_evidence_hash=batch.evidence.provider_evidence_hash,
        )
        report = await self._report_for_batch(cycle_id, sequence, batch)
        self._commit(fence, report)
        return report

    def recovery_state(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self.authority.recovery_summary())

    def _commit(
        self,
        fence: AuthorityFence,
        report: InstalledDurablePaperServiceReport,
    ) -> None:
        self.authority.commit_cycle_terminal(
            fence,
            outcome=report.status.value,
            reason_code=report.terminal_reason,
            report_hash=report.report_hash,
            report_payload=report.to_dict(),
            provider_evidence_hash=report.provider_evidence_hash,
            ready_for_next_cycle=report.ready_for_next_cycle,
            source_surface=report.source_surface,
            sender_imported=report.sender_imported,
            submission_allowed=report.submission_allowed,
            live_enabled=report.live_enabled,
        )

    def _default_blocked_batch(self) -> A3ExactAttemptBatch:
        return A3ExactAttemptBatch(
            A3ProviderEvidenceState.missing_b3(self.runtime_config)
        )

    async def _report_for_batch(
        self,
        cycle_id: str,
        sequence: int,
        batch: A3ExactAttemptBatch,
    ) -> InstalledDurablePaperServiceReport:
        if batch.evidence.blockers:
            return self._blocked_report(
                cycle_id,
                sequence,
                batch.evidence,
                batch.evidence.blockers[0],
            )
        if self.runtime_cycle is None:
            return self._blocked_report(
                cycle_id,
                sequence,
                batch.evidence,
                A3_RUNTIME_UNWIRED,
            )
        return await self._run_a2_cycle(cycle_id, sequence, batch)

    async def _run_a2_cycle(
        self,
        cycle_id: str,
        sequence: int,
        batch: A3ExactAttemptBatch,
    ) -> InstalledDurablePaperServiceReport:
        assert self.runtime_cycle is not None
        try:
            operation = self.runtime_cycle(cycle_id, tuple(batch.items))
            a2_report = await asyncio.wait_for(
                operation,
                timeout=self.config.cycle_deadline_seconds,
            )
        except TimeoutError:
            return self._blocked_report(
                cycle_id,
                sequence,
                batch.evidence,
                A3_RUNTIME_TIMEOUT,
            )
        except Exception as exc:
            return self._indeterminate_report(
                cycle_id,
                sequence,
                batch.evidence,
                f"blocked_a3_runtime_cycle_failed_{type(exc).__name__}",
            )
        return InstalledDurablePaperServiceReport(
            cycle_id=cycle_id,
            status=_status_from_a2(a2_report.status),
            terminal_reason=a2_report.terminal_reason,
            db_path=str(self.config.db_path),
            provider_evidence_hash=batch.evidence.provider_evidence_hash,
            report_hash=a2_report.report_hash,
            ready_for_next_cycle=a2_report.ready_for_next_cycle,
            sequence=sequence,
            sender_imported=a2_report.sender_imported,
            submission_allowed=a2_report.submission_allowed,
            live_enabled=a2_report.live_enabled,
            source_surface=self.config.source_surface,
            records=tuple(record.to_json() for record in a2_report.records),
        )

    def _blocked_report(
        self,
        cycle_id: str,
        sequence: int,
        evidence: A3ProviderEvidenceState,
        reason: str,
    ) -> InstalledDurablePaperServiceReport:
        blockers = tuple(evidence.blockers or (reason,))
        payload = {
            "cycle_id": cycle_id,
            "reason": reason,
            "provider_evidence_hash": evidence.provider_evidence_hash,
            "blockers": list(blockers),
        }
        return InstalledDurablePaperServiceReport(
            cycle_id=cycle_id,
            status=A3PaperServiceStatus.BLOCKED,
            terminal_reason=reason,
            db_path=str(self.config.db_path),
            provider_evidence_hash=evidence.provider_evidence_hash,
            report_hash=_hash_json(payload),
            ready_for_next_cycle=False,
            sequence=sequence,
            source_surface=self.config.source_surface,
            b3_blockers=blockers,
        )

    def _indeterminate_report(
        self,
        cycle_id: str,
        sequence: int,
        evidence: A3ProviderEvidenceState,
        reason: str,
    ) -> InstalledDurablePaperServiceReport:
        payload = {"cycle_id": cycle_id, "reason": reason}
        return InstalledDurablePaperServiceReport(
            cycle_id=cycle_id,
            status=A3PaperServiceStatus.INDETERMINATE,
            terminal_reason=reason,
            db_path=str(self.config.db_path),
            provider_evidence_hash=evidence.provider_evidence_hash,
            report_hash=_hash_json(payload),
            ready_for_next_cycle=False,
            sequence=sequence,
            source_surface=self.config.source_surface,
        )

    def _cycle_id(self, sequence: int) -> str:
        return _hash_json(
            {
                "run_id": self.config.run_id,
                "sequence": sequence,
                "config_fingerprint": _safe_config_fingerprint(self.runtime_config),
                "source_surface": self.config.source_surface,
            }
        )


def build_installed_durable_paper_service(
    config: RuntimeConfig,
    *,
    db_path: Path | str | None = None,
    batch_source: ExactAttemptBatchSource | None = None,
    runtime_cycle: A3RuntimeCycle | None = None,
    clock_ns: Callable[[], int] = time.time_ns,
    authority: UnifiedLifecycleAuthority | None = None,
) -> InstalledDurablePaperService:
    service_config = InstalledPaperServiceConfig(
        db_path=Path(db_path) if db_path is not None else A3_DEFAULT_DB_PATH,
    )
    return InstalledDurablePaperService(
        config,
        service_config,
        batch_source=batch_source,
        runtime_cycle=runtime_cycle,
        clock_ns=clock_ns,
        authority=authority,
    )


def _status_from_a2(status: A2PaperOutcomeStatus) -> A3PaperServiceStatus:
    return A3PaperServiceStatus(status.value)


def _config_identity(config: RuntimeConfig) -> str:
    value = _safe_config_fingerprint(config)
    return value if _is_sha256(value) else hashlib.sha256(value.encode()).hexdigest()


def _safe_config_fingerprint(config: RuntimeConfig) -> str:
    fingerprint = getattr(config, "fingerprint", None)
    if callable(fingerprint):
        return str(fingerprint())
    return "unavailable"


def _runtime_environment(config: RuntimeConfig) -> str:
    runtime = getattr(config, "runtime", None)
    mode = getattr(runtime, "mode", "paper")
    value = getattr(mode, "value", mode)
    return str(value or "paper")


def _cluster_genesis(config: RuntimeConfig) -> str:
    cluster = getattr(config, "cluster", None)
    for name in ("genesis_hash", "genesis", "name"):
        value = getattr(cluster, name, None)
        if value:
            return str(value)
    return "mainnet-beta"


def _record_tuple(
    records: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(dict(item) for item in records)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


__all__ = [
    "A3_BATCH_SOURCE_FAILED",
    "A3_B3_EVIDENCE_MISSING",
    "A3_DEFAULT_DB_PATH",
    "A3_RUNTIME_TIMEOUT",
    "A3_RUNTIME_UNWIRED",
    "A3_SCHEMA",
    "A3ExactAttemptBatch",
    "A3PaperServiceStatus",
    "A3ProviderEvidenceState",
    "InstalledDurablePaperService",
    "InstalledDurablePaperServiceReport",
    "InstalledPaperServiceConfig",
    "build_installed_durable_paper_service",
]
