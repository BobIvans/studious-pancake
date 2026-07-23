"""PR-07 release-bound, signed and resumable sender-free soak evidence.

This module does not manufacture a successful soak. It provides an append-only
checkpoint chain and an independent verifier that can declare a run ready for
review only after at least 72 hours of evidence from one pinned installed wheel,
hardened image, PolicyBundle and admitted provider-evidence identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Protocol, Sequence

from src.security.trust_anchors import (
    SignedEnvelope,
    TrustUsage,
    TrustVerificationResult,
    signable_payload_bytes,
)

PR07_SCHEMA_VERSION = "pr07.release-bound-soak.v1"
PR07_CHECKPOINT_SCHEMA = "pr07.soak-checkpoint.v1"
PR07_CHECKPOINT_DOMAIN = "studious-pancake.pr07.soak-checkpoint"
PR07_MIN_SOAK_SECONDS = 72 * 60 * 60
PR07_GENESIS_CHECKPOINT = "0" * 64
PR07_DB_PRODUCT = "studious-pancake.pr07.soak-evidence"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class SoakVerificationError(ValueError):
    """Stable fail-closed error for malformed or conflicting soak evidence."""


class SoakVerdict(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_REVIEW = "ready-for-review"


class FaultDrill(StrEnum):
    RESTART = "restart"
    PROCESS_KILL = "process-kill"
    CANCELLATION = "cancellation"
    PROVIDER_OUTAGE = "provider-outage"
    QUORUM_LOSS = "quorum-loss"
    RPC_DRIFT = "rpc-drift"
    STALE_ROOT = "stale-root"
    DATABASE_LOCK = "database-lock"
    DISK_PRESSURE = "disk-pressure"
    PARTIAL_WRITE = "partial-write"
    ALERT_ACKNOWLEDGEMENT = "alert-acknowledgement"
    BACKUP_RESTORE = "backup-restore"
    ROLLBACK = "rollback"


REQUIRED_FAULT_DRILLS = tuple(FaultDrill)


class CheckpointTrustRegistry(Protocol):
    generation: str

    def verify(
        self,
        envelope: SignedEnvelope,
        payload: bytes,
        *,
        usage: TrustUsage,
        evaluated_at: datetime,
        expected_domain: str,
        expected_environment: str,
    ) -> TrustVerificationResult: ...


@dataclass(frozen=True, slots=True)
class SoakRunIdentity:
    run_id: str
    source_commit: str
    release_digest: str
    wheel_sha256: str
    image_digest: str
    policy_bundle_sha256: str
    provider_evidence_sha256: str
    cluster_genesis: str
    environment: str
    started_at: datetime
    runtime_surface: str = "installed-wheel+hardened-image"

    def __post_init__(self) -> None:
        _require_safe_id("run_id", self.run_id)
        if (
            not _COMMIT_RE.fullmatch(self.source_commit)
            or self.source_commit == "0" * 40
        ):
            raise SoakVerificationError("PR07_SOURCE_COMMIT_INVALID")
        _require_release_digest("release_digest", self.release_digest)
        _require_sha256("wheel_sha256", self.wheel_sha256)
        _require_release_digest("image_digest", self.image_digest)
        _require_sha256("policy_bundle_sha256", self.policy_bundle_sha256)
        _require_sha256("provider_evidence_sha256", self.provider_evidence_sha256)
        _require_safe_id("cluster_genesis", self.cluster_genesis)
        _require_safe_id("environment", self.environment)
        _require_time("started_at", self.started_at)
        if self.runtime_surface != "installed-wheel+hardened-image":
            raise SoakVerificationError("PR07_RUNTIME_SURFACE_NOT_RELEASE_ARTIFACT")

    @property
    def identity_sha256(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "source_commit": self.source_commit,
            "release_digest": self.release_digest,
            "wheel_sha256": self.wheel_sha256,
            "image_digest": self.image_digest,
            "policy_bundle_sha256": self.policy_bundle_sha256,
            "provider_evidence_sha256": self.provider_evidence_sha256,
            "cluster_genesis": self.cluster_genesis,
            "environment": self.environment,
            "started_at": _format_time(self.started_at),
            "runtime_surface": self.runtime_surface,
        }


@dataclass(frozen=True, slots=True)
class SoakCheckpointPayload:
    run_identity_sha256: str
    sequence: int
    previous_checkpoint_sha256: str
    observed_at: datetime
    process_generation: int
    provider_events_admitted: int
    cycles_completed: int
    candidates_seen: int
    terminal_outcomes: tuple[tuple[str, int], ...]
    retries: int
    duplicates: int
    dead_letters: int
    reservation_leaks: int
    duplicate_capital_uses: int
    unreconciled_outcomes: int
    data_gaps: int
    queue_depth: int
    max_queue_depth: int
    rss_bytes: int
    fd_count: int
    task_count: int
    event_loop_lag_ms: int
    memory_stability_passed: bool
    descriptor_stability_passed: bool
    queue_stability_passed: bool
    resource_limits_passed: bool
    live_enabled: bool
    sender_reachable: bool
    signer_reachable: bool
    signatures_observed: int
    submissions_observed: int
    fixture_rows_observed: int
    drill_evidence: tuple[tuple[FaultDrill, str], ...]
    resource_evidence_sha256: str

    def __post_init__(self) -> None:
        _require_sha256("run_identity_sha256", self.run_identity_sha256)
        if self.sequence < 1:
            raise SoakVerificationError("PR07_CHECKPOINT_SEQUENCE_INVALID")
        if self.sequence == 1:
            if self.previous_checkpoint_sha256 != PR07_GENESIS_CHECKPOINT:
                raise SoakVerificationError("PR07_GENESIS_CHECKPOINT_INVALID")
        else:
            _require_sha256(
                "previous_checkpoint_sha256", self.previous_checkpoint_sha256
            )
        _require_time("observed_at", self.observed_at)
        if self.process_generation < 1:
            raise SoakVerificationError("PR07_PROCESS_GENERATION_INVALID")
        counters = (
            self.provider_events_admitted,
            self.cycles_completed,
            self.candidates_seen,
            self.retries,
            self.duplicates,
            self.dead_letters,
            self.reservation_leaks,
            self.duplicate_capital_uses,
            self.unreconciled_outcomes,
            self.data_gaps,
            self.queue_depth,
            self.max_queue_depth,
            self.rss_bytes,
            self.fd_count,
            self.task_count,
            self.event_loop_lag_ms,
            self.signatures_observed,
            self.submissions_observed,
            self.fixture_rows_observed,
        )
        if min(counters) < 0:
            raise SoakVerificationError("PR07_NEGATIVE_COUNTER")
        if self.queue_depth > self.max_queue_depth:
            raise SoakVerificationError("PR07_QUEUE_DEPTH_EXCEEDS_MAX")
        _normalize_terminal_outcomes(self.terminal_outcomes)
        _normalize_drill_evidence(self.drill_evidence)
        _require_sha256("resource_evidence_sha256", self.resource_evidence_sha256)

    @property
    def checkpoint_sha256(self) -> str:
        return hashlib.sha256(self.signable_bytes()).hexdigest()

    def signable_bytes(self) -> bytes:
        return signable_payload_bytes(self.to_dict())

    def terminal_outcome_map(self) -> dict[str, int]:
        return dict(self.terminal_outcomes)

    def drill_evidence_map(self) -> dict[FaultDrill, str]:
        return dict(self.drill_evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PR07_CHECKPOINT_SCHEMA,
            "run_identity_sha256": self.run_identity_sha256,
            "sequence": self.sequence,
            "previous_checkpoint_sha256": self.previous_checkpoint_sha256,
            "observed_at": _format_time(self.observed_at),
            "process_generation": self.process_generation,
            "provider_events_admitted": self.provider_events_admitted,
            "cycles_completed": self.cycles_completed,
            "candidates_seen": self.candidates_seen,
            "terminal_outcomes": dict(self.terminal_outcomes),
            "retries": self.retries,
            "duplicates": self.duplicates,
            "dead_letters": self.dead_letters,
            "reservation_leaks": self.reservation_leaks,
            "duplicate_capital_uses": self.duplicate_capital_uses,
            "unreconciled_outcomes": self.unreconciled_outcomes,
            "data_gaps": self.data_gaps,
            "queue_depth": self.queue_depth,
            "max_queue_depth": self.max_queue_depth,
            "rss_bytes": self.rss_bytes,
            "fd_count": self.fd_count,
            "task_count": self.task_count,
            "event_loop_lag_ms": self.event_loop_lag_ms,
            "memory_stability_passed": self.memory_stability_passed,
            "descriptor_stability_passed": self.descriptor_stability_passed,
            "queue_stability_passed": self.queue_stability_passed,
            "resource_limits_passed": self.resource_limits_passed,
            "live_enabled": self.live_enabled,
            "sender_reachable": self.sender_reachable,
            "signer_reachable": self.signer_reachable,
            "signatures_observed": self.signatures_observed,
            "submissions_observed": self.submissions_observed,
            "fixture_rows_observed": self.fixture_rows_observed,
            "drill_evidence": {
                drill.value: digest for drill, digest in self.drill_evidence
            },
            "resource_evidence_sha256": self.resource_evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class SignedSoakCheckpoint:
    payload: SoakCheckpointPayload
    envelope: SignedEnvelope

    def to_dict(self) -> dict[str, object]:
        return {
            "payload": self.payload.to_dict(),
            "checkpoint_sha256": self.payload.checkpoint_sha256,
            "envelope": _envelope_to_dict(self.envelope),
        }


@dataclass(frozen=True, slots=True)
class CheckpointAppendResult:
    run_id: str
    sequence: int
    checkpoint_sha256: str
    replayed: bool
    verification_key_id: str
    registry_generation: str


@dataclass(frozen=True, slots=True)
class SoakFinalReport:
    verdict: SoakVerdict
    blockers: tuple[str, ...]
    run_identity_sha256: str
    checkpoint_count: int
    final_checkpoint_sha256: str | None
    observed_duration_seconds: int
    provider_events_admitted: int
    cycles_completed: int
    candidates_seen: int
    terminal_outcomes: tuple[tuple[str, int], ...]
    report_sha256: str
    d2_soak_evidence: Mapping[str, object]
    schema_version: str = PR07_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
            "blockers": list(self.blockers),
            "run_identity_sha256": self.run_identity_sha256,
            "checkpoint_count": self.checkpoint_count,
            "final_checkpoint_sha256": self.final_checkpoint_sha256,
            "observed_duration_seconds": self.observed_duration_seconds,
            "provider_events_admitted": self.provider_events_admitted,
            "cycles_completed": self.cycles_completed,
            "candidates_seen": self.candidates_seen,
            "terminal_outcomes": dict(self.terminal_outcomes),
            "report_sha256": self.report_sha256,
            "d2_soak_evidence": dict(self.d2_soak_evidence),
            "live_enabled": False,
            "sender_reachable": False,
            "signer_reachable": False,
            "submission_allowed": False,
        }


class SQLiteSoakCheckpointStore:
    """Append-only evidence store; it is not a lifecycle or capital authority."""

    def __init__(
        self,
        path: Path | str,
        identity: SoakRunIdentity,
        registry: CheckpointTrustRegistry,
        *,
        busy_timeout_ms: int = 2_000,
    ) -> None:
        if busy_timeout_ms < 1:
            raise SoakVerificationError("PR07_BUSY_TIMEOUT_INVALID")
        self.path = Path(path)
        self.identity = identity
        self.registry = registry
        self.db = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=busy_timeout_ms / 1_000,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(_SCHEMA)
        if self.path != Path(":memory:") and self.path.exists():
            os.chmod(self.path, 0o600)
        self._bind_identity()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SQLiteSoakCheckpointStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def append(
        self,
        checkpoint: SignedSoakCheckpoint,
        *,
        evaluated_at: datetime,
    ) -> CheckpointAppendResult:
        verification = verify_signed_checkpoint(
            self.identity,
            checkpoint,
            self.registry,
            evaluated_at=evaluated_at,
        )
        if not verification.verified:
            raise SoakVerificationError(
                "PR07_CHECKPOINT_SIGNATURE_BLOCKED:" + ",".join(verification.blockers)
            )
        payload = checkpoint.payload
        payload_json = _canonical_json(payload.to_dict())
        envelope_json = _canonical_json(_envelope_to_dict(checkpoint.envelope))
        checkpoint_sha256 = payload.checkpoint_sha256
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT checkpoint_sha256 FROM pr07_checkpoint "
                "WHERE run_id=? AND sequence=?",
                (self.identity.run_id, payload.sequence),
            ).fetchone()
            if existing is not None:
                if existing["checkpoint_sha256"] != checkpoint_sha256:
                    raise SoakVerificationError("PR07_CHECKPOINT_IMMUTABILITY_CONFLICT")
                self.db.execute("COMMIT")
                return CheckpointAppendResult(
                    run_id=self.identity.run_id,
                    sequence=payload.sequence,
                    checkpoint_sha256=checkpoint_sha256,
                    replayed=True,
                    verification_key_id=checkpoint.envelope.key_id,
                    registry_generation=verification.registry_generation,
                )
            previous_row = self.db.execute(
                "SELECT sequence,checkpoint_sha256,payload_json FROM pr07_checkpoint "
                "WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                (self.identity.run_id,),
            ).fetchone()
            _validate_append_position(payload, previous_row)
            self.db.execute(
                "INSERT INTO pr07_checkpoint("
                "run_id,sequence,checkpoint_sha256,previous_checkpoint_sha256,"
                "observed_at,payload_json,envelope_json,verification_key_id,"
                "registry_generation) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    self.identity.run_id,
                    payload.sequence,
                    checkpoint_sha256,
                    payload.previous_checkpoint_sha256,
                    _format_time(payload.observed_at),
                    payload_json,
                    envelope_json,
                    checkpoint.envelope.key_id,
                    verification.registry_generation,
                ),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return CheckpointAppendResult(
            run_id=self.identity.run_id,
            sequence=payload.sequence,
            checkpoint_sha256=checkpoint_sha256,
            replayed=False,
            verification_key_id=checkpoint.envelope.key_id,
            registry_generation=verification.registry_generation,
        )

    def checkpoints(self) -> tuple[SignedSoakCheckpoint, ...]:
        rows = self.db.execute(
            "SELECT payload_json,envelope_json FROM pr07_checkpoint "
            "WHERE run_id=? ORDER BY sequence",
            (self.identity.run_id,),
        ).fetchall()
        return tuple(
            SignedSoakCheckpoint(
                payload=checkpoint_payload_from_mapping(
                    json.loads(row["payload_json"])
                ),
                envelope=signed_envelope_from_mapping(json.loads(row["envelope_json"])),
            )
            for row in rows
        )

    def evaluate(self, *, evaluated_at: datetime) -> SoakFinalReport:
        return evaluate_soak(
            self.identity,
            self.checkpoints(),
            self.registry,
            evaluated_at=evaluated_at,
        )

    def _bind_identity(self) -> None:
        identity_json = _canonical_json(self.identity.to_dict())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            product = self.db.execute(
                "SELECT product_id,schema_version FROM pr07_product_identity "
                "WHERE singleton=1"
            ).fetchone()
            if product is None:
                self.db.execute(
                    "INSERT INTO pr07_product_identity("
                    "singleton,product_id,schema_version) "
                    "VALUES(1,?,?)",
                    (PR07_DB_PRODUCT, PR07_SCHEMA_VERSION),
                )
            elif (
                product["product_id"] != PR07_DB_PRODUCT
                or product["schema_version"] != PR07_SCHEMA_VERSION
            ):
                raise SoakVerificationError("PR07_DATABASE_PRODUCT_MISMATCH")
            row = self.db.execute(
                "SELECT identity_sha256,identity_json FROM pr07_run WHERE run_id=?",
                (self.identity.run_id,),
            ).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO pr07_run("
                    "run_id,identity_sha256,identity_json) VALUES(?,?,?)",
                    (
                        self.identity.run_id,
                        self.identity.identity_sha256,
                        identity_json,
                    ),
                )
            elif (
                row["identity_sha256"] != self.identity.identity_sha256
                or row["identity_json"] != identity_json
            ):
                raise SoakVerificationError("PR07_RUN_IDENTITY_CONFLICT")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise


def verify_signed_checkpoint(
    identity: SoakRunIdentity,
    checkpoint: SignedSoakCheckpoint,
    registry: CheckpointTrustRegistry,
    *,
    evaluated_at: datetime,
) -> TrustVerificationResult:
    _require_time("evaluated_at", evaluated_at)
    if checkpoint.payload.run_identity_sha256 != identity.identity_sha256:
        raise SoakVerificationError("PR07_CHECKPOINT_RUN_IDENTITY_MISMATCH")
    if checkpoint.envelope.schema_version != PR07_CHECKPOINT_SCHEMA:
        raise SoakVerificationError("PR07_SIGNED_CHECKPOINT_SCHEMA_MISMATCH")
    return registry.verify(
        checkpoint.envelope,
        checkpoint.payload.signable_bytes(),
        usage=TrustUsage.EVIDENCE,
        evaluated_at=evaluated_at,
        expected_domain=PR07_CHECKPOINT_DOMAIN,
        expected_environment=identity.environment,
    )


def evaluate_soak(
    identity: SoakRunIdentity,
    checkpoints: Sequence[SignedSoakCheckpoint],
    registry: CheckpointTrustRegistry,
    *,
    evaluated_at: datetime,
    minimum_duration_seconds: int = PR07_MIN_SOAK_SECONDS,
) -> SoakFinalReport:
    _require_time("evaluated_at", evaluated_at)
    if minimum_duration_seconds < PR07_MIN_SOAK_SECONDS:
        raise SoakVerificationError("PR07_MINIMUM_DURATION_CANNOT_BE_WEAKENED")
    blockers: list[str] = []
    previous: SoakCheckpointPayload | None = None
    previous_sha = PR07_GENESIS_CHECKPOINT
    verified_checkpoints: list[SignedSoakCheckpoint] = []
    for expected_sequence, checkpoint in enumerate(checkpoints, start=1):
        payload = checkpoint.payload
        if payload.sequence != expected_sequence:
            blockers.append("PR07_CHECKPOINT_SEQUENCE_GAP")
        if payload.previous_checkpoint_sha256 != previous_sha:
            blockers.append("PR07_CHECKPOINT_CHAIN_DIVERGENCE")
        try:
            result = verify_signed_checkpoint(
                identity,
                checkpoint,
                registry,
                evaluated_at=evaluated_at,
            )
        except SoakVerificationError as exc:
            blockers.append(str(exc))
        else:
            blockers.extend(result.blockers)
            if result.verified:
                verified_checkpoints.append(checkpoint)
        if previous is not None:
            blockers.extend(_counter_regression_blockers(previous, payload))
        previous = payload
        previous_sha = payload.checkpoint_sha256

    if len(checkpoints) < 2:
        blockers.append("PR07_CHECKPOINT_COVERAGE_INSUFFICIENT")
    if len(verified_checkpoints) != len(checkpoints):
        blockers.append("PR07_CHECKPOINT_CHAIN_NOT_FULLY_VERIFIED")

    final = checkpoints[-1].payload if checkpoints else None
    observed_duration_seconds = (
        int((final.observed_at - identity.started_at).total_seconds())
        if final is not None
        else 0
    )
    if observed_duration_seconds < minimum_duration_seconds:
        blockers.append("PR07_SOAK_DURATION_BELOW_72_HOURS")
    if final is not None:
        blockers.extend(_final_checkpoint_blockers(final))
    unique_blockers = tuple(dict.fromkeys(blockers))
    verdict = SoakVerdict.BLOCKED if unique_blockers else SoakVerdict.READY_FOR_REVIEW
    terminal_outcomes = final.terminal_outcomes if final is not None else ()
    d2_soak = _d2_soak_mapping(identity, final, observed_duration_seconds)
    report_payload = {
        "schema_version": PR07_SCHEMA_VERSION,
        "verdict": verdict.value,
        "blockers": list(unique_blockers),
        "run_identity_sha256": identity.identity_sha256,
        "checkpoint_count": len(checkpoints),
        "final_checkpoint_sha256": previous_sha if checkpoints else None,
        "observed_duration_seconds": observed_duration_seconds,
        "provider_events_admitted": final.provider_events_admitted if final else 0,
        "cycles_completed": final.cycles_completed if final else 0,
        "candidates_seen": final.candidates_seen if final else 0,
        "terminal_outcomes": dict(terminal_outcomes),
        "d2_soak_evidence": d2_soak,
        "live_enabled": False,
        "sender_reachable": False,
        "signer_reachable": False,
    }
    return SoakFinalReport(
        verdict=verdict,
        blockers=unique_blockers,
        run_identity_sha256=identity.identity_sha256,
        checkpoint_count=len(checkpoints),
        final_checkpoint_sha256=previous_sha if checkpoints else None,
        observed_duration_seconds=observed_duration_seconds,
        provider_events_admitted=final.provider_events_admitted if final else 0,
        cycles_completed=final.cycles_completed if final else 0,
        candidates_seen=final.candidates_seen if final else 0,
        terminal_outcomes=terminal_outcomes,
        report_sha256=_hash_json(report_payload),
        d2_soak_evidence=d2_soak,
    )


def run_identity_from_mapping(data: Mapping[str, Any]) -> SoakRunIdentity:
    return SoakRunIdentity(
        run_id=str(data["run_id"]),
        source_commit=str(data["source_commit"]),
        release_digest=str(data["release_digest"]),
        wheel_sha256=str(data["wheel_sha256"]),
        image_digest=str(data["image_digest"]),
        policy_bundle_sha256=str(data["policy_bundle_sha256"]),
        provider_evidence_sha256=str(data["provider_evidence_sha256"]),
        cluster_genesis=str(data["cluster_genesis"]),
        environment=str(data["environment"]),
        started_at=_parse_time(data["started_at"]),
        runtime_surface=str(
            data.get("runtime_surface", "installed-wheel+hardened-image")
        ),
    )


def checkpoint_payload_from_mapping(
    data: Mapping[str, Any],
) -> SoakCheckpointPayload:
    if data.get("schema_version") not in {None, PR07_CHECKPOINT_SCHEMA}:
        raise SoakVerificationError("PR07_CHECKPOINT_SCHEMA_UNSUPPORTED")
    outcomes = tuple(
        sorted(
            (str(key), _strict_int(value))
            for key, value in _mapping(data["terminal_outcomes"]).items()
        )
    )
    drills = tuple(
        sorted(
            (
                (FaultDrill(str(key)), str(value))
                for key, value in _mapping(data["drill_evidence"]).items()
            ),
            key=lambda item: item[0].value,
        )
    )
    return SoakCheckpointPayload(
        run_identity_sha256=str(data["run_identity_sha256"]),
        sequence=_strict_int(data["sequence"]),
        previous_checkpoint_sha256=str(data["previous_checkpoint_sha256"]),
        observed_at=_parse_time(data["observed_at"]),
        process_generation=_strict_int(data["process_generation"]),
        provider_events_admitted=_strict_int(data["provider_events_admitted"]),
        cycles_completed=_strict_int(data["cycles_completed"]),
        candidates_seen=_strict_int(data["candidates_seen"]),
        terminal_outcomes=outcomes,
        retries=_strict_int(data["retries"]),
        duplicates=_strict_int(data["duplicates"]),
        dead_letters=_strict_int(data["dead_letters"]),
        reservation_leaks=_strict_int(data["reservation_leaks"]),
        duplicate_capital_uses=_strict_int(data["duplicate_capital_uses"]),
        unreconciled_outcomes=_strict_int(data["unreconciled_outcomes"]),
        data_gaps=_strict_int(data["data_gaps"]),
        queue_depth=_strict_int(data["queue_depth"]),
        max_queue_depth=_strict_int(data["max_queue_depth"]),
        rss_bytes=_strict_int(data["rss_bytes"]),
        fd_count=_strict_int(data["fd_count"]),
        task_count=_strict_int(data["task_count"]),
        event_loop_lag_ms=_strict_int(data["event_loop_lag_ms"]),
        memory_stability_passed=_strict_bool(data["memory_stability_passed"]),
        descriptor_stability_passed=_strict_bool(data["descriptor_stability_passed"]),
        queue_stability_passed=_strict_bool(data["queue_stability_passed"]),
        resource_limits_passed=_strict_bool(data["resource_limits_passed"]),
        live_enabled=_strict_bool(data["live_enabled"]),
        sender_reachable=_strict_bool(data["sender_reachable"]),
        signer_reachable=_strict_bool(data["signer_reachable"]),
        signatures_observed=_strict_int(data["signatures_observed"]),
        submissions_observed=_strict_int(data["submissions_observed"]),
        fixture_rows_observed=_strict_int(data["fixture_rows_observed"]),
        drill_evidence=drills,
        resource_evidence_sha256=str(data["resource_evidence_sha256"]),
    )


def signed_envelope_from_mapping(data: Mapping[str, Any]) -> SignedEnvelope:
    return SignedEnvelope(
        domain=str(data["domain"]),
        schema_version=str(data["schema_version"]),
        environment=str(data["environment"]),
        key_id=str(data["key_id"]),
        issued_at=_parse_time(data["issued_at"]),
        expires_at=_parse_time(data["expires_at"]),
        payload_sha256=str(data["payload_sha256"]),
        signature_base58=str(data["signature_base58"]),
    )


def signed_checkpoint_from_mapping(
    data: Mapping[str, Any],
) -> SignedSoakCheckpoint:
    return SignedSoakCheckpoint(
        payload=checkpoint_payload_from_mapping(_mapping(data["payload"])),
        envelope=signed_envelope_from_mapping(_mapping(data["envelope"])),
    )


def render_report_json(report: SoakFinalReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"


def _validate_append_position(
    payload: SoakCheckpointPayload,
    previous_row: sqlite3.Row | None,
) -> None:
    if previous_row is None:
        if payload.sequence != 1:
            raise SoakVerificationError("PR07_CHECKPOINT_SEQUENCE_GAP")
        return
    expected_sequence = int(previous_row["sequence"]) + 1
    if payload.sequence != expected_sequence:
        raise SoakVerificationError("PR07_CHECKPOINT_SEQUENCE_GAP")
    if payload.previous_checkpoint_sha256 != previous_row["checkpoint_sha256"]:
        raise SoakVerificationError("PR07_CHECKPOINT_CHAIN_DIVERGENCE")
    previous = checkpoint_payload_from_mapping(json.loads(previous_row["payload_json"]))
    blockers = _counter_regression_blockers(previous, payload)
    if blockers:
        raise SoakVerificationError(blockers[0])


def _counter_regression_blockers(
    previous: SoakCheckpointPayload,
    current: SoakCheckpointPayload,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if current.observed_at <= previous.observed_at:
        blockers.append("PR07_CHECKPOINT_TIME_NOT_MONOTONIC")
    if current.process_generation < previous.process_generation:
        blockers.append("PR07_PROCESS_GENERATION_REGRESSION")
    for field in (
        "provider_events_admitted",
        "cycles_completed",
        "candidates_seen",
        "retries",
        "duplicates",
        "dead_letters",
        "reservation_leaks",
        "duplicate_capital_uses",
        "unreconciled_outcomes",
        "data_gaps",
        "max_queue_depth",
        "signatures_observed",
        "submissions_observed",
        "fixture_rows_observed",
    ):
        if getattr(current, field) < getattr(previous, field):
            blockers.append(f"PR07_COUNTER_REGRESSION:{field}")
    previous_outcomes = previous.terminal_outcome_map()
    current_outcomes = current.terminal_outcome_map()
    for key, value in previous_outcomes.items():
        if current_outcomes.get(key, 0) < value:
            blockers.append(f"PR07_TERMINAL_COUNTER_REGRESSION:{key}")
    previous_drills = previous.drill_evidence_map()
    current_drills = current.drill_evidence_map()
    for drill, digest in previous_drills.items():
        if current_drills.get(drill) != digest:
            blockers.append(f"PR07_DRILL_EVIDENCE_REGRESSION:{drill.value}")
    return tuple(dict.fromkeys(blockers))


def _final_checkpoint_blockers(payload: SoakCheckpointPayload) -> tuple[str, ...]:
    blockers: list[str] = []
    if payload.provider_events_admitted <= 0:
        blockers.append("PR07_REAL_PROVIDER_EVIDENCE_NOT_ADMITTED")
    if payload.cycles_completed <= 0:
        blockers.append("PR07_PAPER_CYCLES_MISSING")
    if (
        not payload.terminal_outcomes
        or sum(dict(payload.terminal_outcomes).values()) <= 0
    ):
        blockers.append("PR07_TERMINAL_OUTCOMES_MISSING")
    if payload.reservation_leaks:
        blockers.append("PR07_RESERVATION_LEAKS")
    if payload.duplicate_capital_uses:
        blockers.append("PR07_DUPLICATE_CAPITAL_USAGE")
    if payload.unreconciled_outcomes:
        blockers.append("PR07_UNRECONCILED_OUTCOMES")
    if payload.data_gaps:
        blockers.append("PR07_DATA_GAPS")
    if payload.live_enabled:
        blockers.append("PR07_LIVE_ENABLED")
    if payload.sender_reachable:
        blockers.append("PR07_SENDER_REACHABLE")
    if payload.signer_reachable:
        blockers.append("PR07_SIGNER_REACHABLE")
    if payload.signatures_observed:
        blockers.append("PR07_SIGNATURES_OBSERVED")
    if payload.submissions_observed:
        blockers.append("PR07_SUBMISSIONS_OBSERVED")
    if payload.fixture_rows_observed:
        blockers.append("PR07_SYNTHETIC_OR_FIXTURE_ROWS_OBSERVED")
    if not payload.memory_stability_passed:
        blockers.append("PR07_MEMORY_STABILITY_NOT_PROVEN")
    if not payload.descriptor_stability_passed:
        blockers.append("PR07_DESCRIPTOR_STABILITY_NOT_PROVEN")
    if not payload.queue_stability_passed:
        blockers.append("PR07_QUEUE_STABILITY_NOT_PROVEN")
    if not payload.resource_limits_passed:
        blockers.append("PR07_RESOURCE_LIMITS_NOT_PROVEN")
    drill_map = payload.drill_evidence_map()
    for drill in REQUIRED_FAULT_DRILLS:
        if drill not in drill_map:
            blockers.append(f"PR07_DRILL_MISSING:{drill.value}")
    return tuple(blockers)


def _d2_soak_mapping(
    identity: SoakRunIdentity,
    final: SoakCheckpointPayload | None,
    observed_duration_seconds: int,
) -> dict[str, object]:
    if final is None:
        return {
            "release_digest": identity.release_digest,
            "policy_bundle_sha256": identity.policy_bundle_sha256,
            "started_at": _format_time(identity.started_at),
            "finished_at": _format_time(identity.started_at),
            "reviewed_duration_seconds": PR07_MIN_SOAK_SECONDS,
            "observed_duration_seconds": 0,
            "non_synthetic": False,
        }
    drills = final.drill_evidence_map()
    return {
        "release_digest": identity.release_digest,
        "policy_bundle_sha256": identity.policy_bundle_sha256,
        "started_at": _format_time(identity.started_at),
        "finished_at": _format_time(final.observed_at),
        "reviewed_duration_seconds": PR07_MIN_SOAK_SECONDS,
        "observed_duration_seconds": observed_duration_seconds,
        "non_synthetic": final.fixture_rows_observed == 0,
        "pinned_wheel": True,
        "pinned_image": True,
        "pinned_policy": True,
        "sender_imports_detected": final.sender_reachable,
        "signer_imports_detected": final.signer_reachable,
        "signatures_observed": final.signatures_observed,
        "submissions_observed": final.submissions_observed,
        "candidates_seen": final.candidates_seen,
        "terminal_outcomes": dict(final.terminal_outcomes),
        "unreconciled_terminal_gaps": final.unreconciled_outcomes,
        "reservation_leaks": final.reservation_leaks,
        "data_gaps": final.data_gaps,
        "restart_recovery_passed": FaultDrill.RESTART in drills,
        "cancellation_recovery_passed": FaultDrill.CANCELLATION in drills,
        "resource_limits_passed": (
            final.memory_stability_passed
            and final.descriptor_stability_passed
            and final.queue_stability_passed
            and final.resource_limits_passed
        ),
        "fixture_rows_excluded": final.fixture_rows_observed == 0,
        "checkpoint_chain_sha256": final.checkpoint_sha256,
        "provider_evidence_sha256": identity.provider_evidence_sha256,
        "resource_evidence_sha256": final.resource_evidence_sha256,
    }


def _normalize_terminal_outcomes(
    outcomes: tuple[tuple[str, int], ...],
) -> None:
    keys: set[str] = set()
    for key, value in outcomes:
        _require_safe_id("terminal_outcome", key)
        if key in keys:
            raise SoakVerificationError("PR07_DUPLICATE_TERMINAL_OUTCOME")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SoakVerificationError("PR07_TERMINAL_OUTCOME_COUNT_INVALID")
        keys.add(key)


def _normalize_drill_evidence(
    drills: tuple[tuple[FaultDrill, str], ...],
) -> None:
    keys: set[FaultDrill] = set()
    for drill, digest in drills:
        if drill in keys:
            raise SoakVerificationError("PR07_DUPLICATE_DRILL_EVIDENCE")
        _require_sha256(f"drill_evidence.{drill.value}", digest)
        keys.add(drill)


def _envelope_to_dict(envelope: SignedEnvelope) -> dict[str, object]:
    return {
        "domain": envelope.domain,
        "schema_version": envelope.schema_version,
        "environment": envelope.environment,
        "key_id": envelope.key_id,
        "issued_at": _format_time(envelope.issued_at),
        "expires_at": _format_time(envelope.expires_at),
        "payload_sha256": envelope.payload_sha256,
        "signature_base58": envelope.signature_base58,
    }


def _parse_time(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise SoakVerificationError("PR07_TIMESTAMP_INVALID") from exc
    _require_time("timestamp", parsed)
    return parsed


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _require_time(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SoakVerificationError(f"PR07_TIMEZONE_REQUIRED:{field}")


def _require_safe_id(field: str, value: str) -> None:
    if not _SAFE_ID_RE.fullmatch(value):
        raise SoakVerificationError(f"PR07_SAFE_ID_INVALID:{field}")


def _require_sha256(field: str, value: str) -> None:
    if not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise SoakVerificationError(f"PR07_SHA256_INVALID:{field}")


def _require_release_digest(field: str, value: str) -> None:
    digest = value.removeprefix("sha256:")
    _require_sha256(field, digest)


def _strict_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SoakVerificationError("PR07_INTEGER_REQUIRED")
    return value


def _strict_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise SoakVerificationError("PR07_BOOLEAN_REQUIRED")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SoakVerificationError("PR07_MAPPING_REQUIRED")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pr07_product_identity(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    product_id TEXT NOT NULL,
    schema_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pr07_run(
    run_id TEXT PRIMARY KEY,
    identity_sha256 TEXT NOT NULL UNIQUE,
    identity_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pr07_checkpoint(
    run_id TEXT NOT NULL REFERENCES pr07_run(run_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    checkpoint_sha256 TEXT NOT NULL UNIQUE,
    previous_checkpoint_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    verification_key_id TEXT NOT NULL,
    registry_generation TEXT NOT NULL,
    PRIMARY KEY(run_id, sequence)
);
"""


__all__ = [
    "CheckpointAppendResult",
    "CheckpointTrustRegistry",
    "FaultDrill",
    "PR07_CHECKPOINT_DOMAIN",
    "PR07_CHECKPOINT_SCHEMA",
    "PR07_GENESIS_CHECKPOINT",
    "PR07_MIN_SOAK_SECONDS",
    "PR07_SCHEMA_VERSION",
    "REQUIRED_FAULT_DRILLS",
    "SQLiteSoakCheckpointStore",
    "SignedSoakCheckpoint",
    "SoakCheckpointPayload",
    "SoakFinalReport",
    "SoakRunIdentity",
    "SoakVerdict",
    "SoakVerificationError",
    "checkpoint_payload_from_mapping",
    "evaluate_soak",
    "render_report_json",
    "run_identity_from_mapping",
    "signed_checkpoint_from_mapping",
    "signed_envelope_from_mapping",
    "verify_signed_checkpoint",
]
