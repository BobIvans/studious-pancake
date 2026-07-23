"""Roadmap PR-03 rooted provider verification and atomic A3 admission.

This module joins the existing bounded Helius delivery inbox to independently
rooted RPC evidence.  It produces authenticated evidence, commits one durable
handoff per canonical event, and exposes a typed A3 batch source.  It never
imports a signer, transaction sender, or live execution surface.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Protocol

PR03_EVIDENCE_SCHEMA = "roadmap-pr03.rooted-provider-evidence.v1"
PR03_HANDOFF_SCHEMA = "roadmap-pr03.atomic-provider-handoff.v1"
PR03_BATCH_SCHEMA = "roadmap-pr03.a3-rooted-batch.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


class ProviderVerificationError(RuntimeError):
    """Fail-closed provider verification or durable handoff error."""


class WorkerDecision(StrEnum):
    IDLE = "idle"
    ADMITTED = "admitted"
    RETRYABLE_BLOCKED = "retryable_blocked"
    PERMANENT_BLOCKED = "permanent_blocked"


@dataclass(frozen=True, slots=True)
class ProviderAdmissionBinding:
    provider: str
    decision: str
    evidence_hash: str
    endpoint_identity_hash: str
    expires_at_ns: int
    drift_detected: bool = False
    credential_failure: bool = False

    def __post_init__(self) -> None:
        _require_safe_id(self.provider, "provider")
        if self.decision not in {"admitted", "blocked"}:
            raise ValueError("decision must be admitted or blocked")
        _require_sha256(self.evidence_hash, "evidence_hash")
        _require_sha256(self.endpoint_identity_hash, "endpoint_identity_hash")
        if self.expires_at_ns <= 0:
            raise ValueError("expires_at_ns must be positive")


@dataclass(frozen=True, slots=True)
class RpcRootObservation:
    provider_id: str
    correlation_group: str
    endpoint_identity_hash: str
    genesis_hash: str
    rooted_slot: int
    transaction_signature: str
    transaction_slot: int
    transaction_found: bool
    response_hash: str
    observed_at_ns: int

    def __post_init__(self) -> None:
        _require_safe_id(self.provider_id, "provider_id")
        _require_safe_id(self.correlation_group, "correlation_group")
        _require_sha256(self.endpoint_identity_hash, "endpoint_identity_hash")
        _require_safe_id(self.genesis_hash, "genesis_hash")
        _require_safe_id(self.transaction_signature, "transaction_signature")
        _require_sha256(self.response_hash, "response_hash")
        if self.rooted_slot < 0 or self.transaction_slot < 0:
            raise ValueError("slots must be non-negative")
        if self.observed_at_ns <= 0:
            raise ValueError("observed_at_ns must be positive")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RootedRpcEvidence:
    observations: tuple[RpcRootObservation, ...]
    minimum_independent_sources: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        if self.minimum_independent_sources < 2:
            raise ValueError("minimum_independent_sources must be at least two")

    @property
    def evidence_hash(self) -> str:
        return _hash_json(
            {
                "minimum_independent_sources": self.minimum_independent_sources,
                "observations": [item.to_dict() for item in self.observations],
            }
        )


@dataclass(frozen=True, slots=True)
class HeliusInboxEvent:
    event_id: str
    delivery_id: str
    webhook_id: str
    signature: str
    slot: int
    payload_hash: str
    payload_json: str
    queued_at_ns: int

    def __post_init__(self) -> None:
        _require_sha256(self.event_id, "event_id")
        _require_sha256(self.delivery_id, "delivery_id")
        _require_safe_id(self.webhook_id, "webhook_id")
        _require_safe_id(self.signature, "signature")
        _require_sha256(self.payload_hash, "payload_hash")
        if self.slot < 0 or self.queued_at_ns <= 0:
            raise ValueError("event timing and slot must be positive")
        if _hash_text(self.payload_json) != self.payload_hash:
            raise ValueError("payload_json does not match payload_hash")


@dataclass(frozen=True, slots=True)
class VerifiedProviderEvent:
    event_id: str
    delivery_id: str
    webhook_id: str
    signature: str
    slot: int
    payload_hash: str
    raw_evidence_ref: str
    cluster_genesis: str
    rooted_slot: int
    release_id: str
    policy_bundle_hash: str
    provider_admission_hash: str
    provider_endpoint_identity_hash: str
    rpc_quorum_hash: str
    verifier_trust_anchor_id: str
    issued_at_ns: int
    expires_at_ns: int
    authentication_mac: str
    schema: str = PR03_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "delivery_id",
            "payload_hash",
            "policy_bundle_hash",
            "provider_admission_hash",
            "provider_endpoint_identity_hash",
            "rpc_quorum_hash",
            "authentication_mac",
        ):
            _require_sha256(str(getattr(self, name)), name)
        for name in (
            "webhook_id",
            "signature",
            "cluster_genesis",
            "release_id",
            "verifier_trust_anchor_id",
        ):
            _require_safe_id(str(getattr(self, name)), name)
        if self.slot < 0 or self.rooted_slot < self.slot:
            raise ValueError("rooted slot must cover event slot")
        if self.issued_at_ns <= 0 or self.expires_at_ns <= self.issued_at_ns:
            raise ValueError("invalid evidence validity window")
        if not self.raw_evidence_ref.startswith("sqlite://"):
            raise ValueError("raw_evidence_ref must be an immutable sqlite reference")

    def unsigned_dict(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("authentication_mac")
        return value

    @property
    def evidence_hash(self) -> str:
        return _hash_json(asdict(self))

    def to_json(self) -> str:
        return _canonical_json(asdict(self))


@dataclass(frozen=True, slots=True)
class VerifiedProviderWorkItem:
    event_id: str
    signature: str
    slot: int
    payload_hash: str
    evidence_hash: str
    raw_evidence_ref: str
    release_id: str
    policy_bundle_hash: str


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    decision: WorkerDecision
    event_id: str | None
    reason_code: str
    evidence_hash: str | None = None
    handoff_id: str | None = None
    live_enabled: bool = False
    signer_reachable: bool = False
    sender_reachable: bool = False


class RootedRpcEvidenceCollector(Protocol):
    def collect(self, *, signature: str, slot: int) -> RootedRpcEvidence: ...


class HmacSha256EvidenceAuthenticator:
    """Protected-worker authenticity boundary; secret bytes are never persisted."""

    def __init__(self, *, trust_anchor_id: str, secret: bytes) -> None:
        _require_safe_id(trust_anchor_id, "trust_anchor_id")
        if len(secret) < 32:
            raise ValueError("PR-03 evidence secret must contain at least 32 bytes")
        self.trust_anchor_id = trust_anchor_id
        self._secret = bytes(secret)

    def sign(self, payload: Mapping[str, object]) -> str:
        return hmac.new(
            self._secret,
            _canonical_json(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify(self, payload: Mapping[str, object], mac: str) -> bool:
        if not _is_sha256(mac):
            return False
        return hmac.compare_digest(self.sign(payload), mac)


class RootedProviderEvidenceVerifier:
    def __init__(
        self,
        *,
        expected_genesis: str,
        release_id: str,
        policy_bundle_hash: str,
        authenticator: HmacSha256EvidenceAuthenticator,
        max_rpc_evidence_age_ns: int = 30_000_000_000,
        evidence_ttl_ns: int = 30_000_000_000,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        _require_safe_id(expected_genesis, "expected_genesis")
        _require_safe_id(release_id, "release_id")
        _require_sha256(policy_bundle_hash, "policy_bundle_hash")
        if max_rpc_evidence_age_ns <= 0 or evidence_ttl_ns <= 0:
            raise ValueError("evidence age and ttl must be positive")
        self.expected_genesis = expected_genesis
        self.release_id = release_id
        self.policy_bundle_hash = policy_bundle_hash
        self.authenticator = authenticator
        self.max_rpc_evidence_age_ns = max_rpc_evidence_age_ns
        self.evidence_ttl_ns = evidence_ttl_ns
        self._now_ns = now_ns

    def verify(
        self,
        *,
        event: HeliusInboxEvent,
        admission: ProviderAdmissionBinding,
        quorum: RootedRpcEvidence,
    ) -> VerifiedProviderEvent:
        now_ns = self._now_ns()
        blockers = self._blockers(
            event=event,
            admission=admission,
            quorum=quorum,
            now_ns=now_ns,
        )
        if blockers:
            raise ProviderVerificationError(blockers[0])
        rooted_slot = min(item.rooted_slot for item in quorum.observations)
        unsigned = {
            "event_id": event.event_id,
            "delivery_id": event.delivery_id,
            "webhook_id": event.webhook_id,
            "signature": event.signature,
            "slot": event.slot,
            "payload_hash": event.payload_hash,
            "raw_evidence_ref": (
                "sqlite://helius_event_inbox/dedup_key/" + event.event_id
            ),
            "cluster_genesis": self.expected_genesis,
            "rooted_slot": rooted_slot,
            "release_id": self.release_id,
            "policy_bundle_hash": self.policy_bundle_hash,
            "provider_admission_hash": admission.evidence_hash,
            "provider_endpoint_identity_hash": admission.endpoint_identity_hash,
            "rpc_quorum_hash": quorum.evidence_hash,
            "verifier_trust_anchor_id": self.authenticator.trust_anchor_id,
            "issued_at_ns": now_ns,
            "expires_at_ns": now_ns + self.evidence_ttl_ns,
            "schema": PR03_EVIDENCE_SCHEMA,
        }
        mac = self.authenticator.sign(unsigned)
        return VerifiedProviderEvent(authentication_mac=mac, **unsigned)

    def _blockers(
        self,
        *,
        event: HeliusInboxEvent,
        admission: ProviderAdmissionBinding,
        quorum: RootedRpcEvidence,
        now_ns: int,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if admission.provider.lower() != "helius":
            blockers.append("PR03_PROVIDER_ADMISSION_NOT_HELIUS")
        if admission.decision != "admitted":
            blockers.append("PR03_PROVIDER_ADMISSION_BLOCKED")
        if admission.expires_at_ns <= now_ns:
            blockers.append("PR03_PROVIDER_ADMISSION_EXPIRED")
        if admission.drift_detected:
            blockers.append("PR03_PROVIDER_DRIFT_DETECTED")
        if admission.credential_failure:
            blockers.append("PR03_PROVIDER_CREDENTIAL_FAILURE")
        if len(quorum.observations) < quorum.minimum_independent_sources:
            blockers.append("PR03_RPC_QUORUM_INSUFFICIENT")
        groups = {item.correlation_group for item in quorum.observations}
        if len(groups) < quorum.minimum_independent_sources:
            blockers.append("PR03_RPC_CORRELATION_GROUPS_INSUFFICIENT")
        endpoint_ids = {item.endpoint_identity_hash for item in quorum.observations}
        if len(endpoint_ids) < quorum.minimum_independent_sources:
            blockers.append("PR03_RPC_ENDPOINT_DIVERSITY_INSUFFICIENT")
        for observation in quorum.observations:
            if observation.genesis_hash != self.expected_genesis:
                blockers.append("PR03_RPC_GENESIS_MISMATCH")
            if observation.rooted_slot < event.slot:
                blockers.append("PR03_RPC_ROOT_BEHIND_EVENT")
            if not observation.transaction_found:
                blockers.append("PR03_RPC_TRANSACTION_NOT_FOUND")
            if observation.transaction_signature != event.signature:
                blockers.append("PR03_RPC_SIGNATURE_MISMATCH")
            if observation.transaction_slot != event.slot:
                blockers.append("PR03_RPC_TRANSACTION_SLOT_MISMATCH")
            age = now_ns - observation.observed_at_ns
            if age < 0 or age > self.max_rpc_evidence_age_ns:
                blockers.append("PR03_RPC_EVIDENCE_STALE")
        return tuple(dict.fromkeys(blockers))


class RootedProviderIngestionStore:
    """Extends the existing Helius SQLite inbox without creating lifecycle truth."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=1.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            required = {
                str(row[0])
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if (
                "helius_event_inbox" not in required
                or "helius_delivery" not in required
            ):
                raise ProviderVerificationError("PR03_HELIUS_DELIVERY_SCHEMA_MISSING")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS pr03_verified_provider_evidence(
                    event_id TEXT PRIMARY KEY,
                    delivery_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    policy_bundle_hash TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL UNIQUE,
                    evidence_json TEXT NOT NULL,
                    authentication_mac TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pr03_provider_handoff(
                    handoff_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE
                      REFERENCES pr03_verified_provider_evidence(event_id),
                    release_id TEXT NOT NULL,
                    policy_bundle_hash TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pr03_provider_handoff_audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    reason_code TEXT NOT NULL,
                    detail_hash TEXT,
                    created_at_ns INTEGER NOT NULL
                );
                """
            )

    def next_queued_event(self) -> HeliusInboxEvent | None:
        self.initialize()
        with self._connect() as con:
            row = con.execute(
                "SELECT i.dedup_key,i.delivery_id,d.webhook_id,i.signature,i.slot,"
                "i.payload_hash,i.payload_json,i.queued_at_ns "
                "FROM helius_event_inbox AS i "
                "JOIN helius_delivery AS d ON d.delivery_id=i.delivery_id "
                "WHERE i.state='queued' AND i.payload_json IS NOT NULL "
                "ORDER BY i.id LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        if row["slot"] is None:
            raise ProviderVerificationError("PR03_EVENT_SLOT_MISSING")
        return HeliusInboxEvent(
            event_id=str(row["dedup_key"]),
            delivery_id=str(row["delivery_id"]),
            webhook_id=str(row["webhook_id"]),
            signature=str(row["signature"]),
            slot=int(row["slot"]),
            payload_hash=str(row["payload_hash"]),
            payload_json=str(row["payload_json"]),
            queued_at_ns=int(row["queued_at_ns"]),
        )

    def unresolved_gap_blocks(self, event: HeliusInboxEvent) -> bool:
        self.initialize()
        with self._connect() as con:
            row = con.execute(
                "SELECT gap_from_slot,gap_to_slot FROM helius_gap_state "
                "WHERE webhook_id=?",
                (event.webhook_id,),
            ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            return False
        return event.slot >= int(row[0])

    def record_retryable(self, event_id: str | None, reason_code: str) -> None:
        self.initialize()
        now_ns = time.time_ns()
        with self._connect() as con:
            con.execute(
                "INSERT INTO pr03_provider_handoff_audit"
                "(event_id,reason_code,detail_hash,created_at_ns) VALUES(?,?,?,?)",
                (event_id, reason_code, _hash_text(reason_code), now_ns),
            )

    def commit_verified(
        self,
        *,
        event: HeliusInboxEvent,
        evidence: VerifiedProviderEvent,
    ) -> str:
        self.initialize()
        if (
            evidence.event_id != event.event_id
            or evidence.payload_hash != event.payload_hash
        ):
            raise ProviderVerificationError("PR03_EVIDENCE_EVENT_IDENTITY_MISMATCH")
        handoff_id = _hash_json(
            {
                "schema": PR03_HANDOFF_SCHEMA,
                "event_id": evidence.event_id,
                "release_id": evidence.release_id,
                "policy_bundle_hash": evidence.policy_bundle_hash,
                "evidence_hash": evidence.evidence_hash,
            }
        )
        now_ns = time.time_ns()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT release_id,policy_bundle_hash,evidence_hash FROM "
                "pr03_provider_handoff WHERE event_id=?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                actual = (str(existing[0]), str(existing[1]), str(existing[2]))
                expected = (
                    evidence.release_id,
                    evidence.policy_bundle_hash,
                    evidence.evidence_hash,
                )
                if actual != expected:
                    raise ProviderVerificationError(
                        "PR03_DUPLICATE_HANDOFF_IDENTITY_CONFLICT"
                    )
                return handoff_id
            con.execute(
                "INSERT INTO pr03_verified_provider_evidence"
                "(event_id,delivery_id,release_id,policy_bundle_hash,evidence_hash,"
                "evidence_json,authentication_mac,created_at_ns) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.delivery_id,
                    evidence.release_id,
                    evidence.policy_bundle_hash,
                    evidence.evidence_hash,
                    evidence.to_json(),
                    evidence.authentication_mac,
                    now_ns,
                ),
            )
            con.execute(
                "INSERT INTO pr03_provider_handoff"
                "(handoff_id,event_id,release_id,policy_bundle_hash,evidence_hash,"
                "payload_hash,status,created_at_ns) VALUES(?,?,?,?,?,?,'pending',?)",
                (
                    handoff_id,
                    event.event_id,
                    evidence.release_id,
                    evidence.policy_bundle_hash,
                    evidence.evidence_hash,
                    event.payload_hash,
                    now_ns,
                ),
            )
            updated = con.execute(
                "UPDATE helius_event_inbox SET state='verified',processed_at_ns=? "
                "WHERE dedup_key=? AND state='queued'",
                (now_ns, event.event_id),
            ).rowcount
            if updated != 1:
                raise ProviderVerificationError("PR03_HELIUS_EVENT_STATE_CHANGED")
        return handoff_id

    def pending_work_items(
        self,
        *,
        authenticator: HmacSha256EvidenceAuthenticator,
        limit: int = 100,
    ) -> tuple[VerifiedProviderWorkItem, ...]:
        self.initialize()
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as con:
            rows = con.execute(
                "SELECT h.event_id,h.release_id,h.policy_bundle_hash,h.evidence_hash,"
                "h.payload_hash,e.evidence_json FROM pr03_provider_handoff AS h "
                "JOIN pr03_verified_provider_evidence AS e ON e.event_id=h.event_id "
                "WHERE h.status='pending' "
                "ORDER BY h.created_at_ns,h.handoff_id LIMIT ?",
                (limit,),
            ).fetchall()
        items: list[VerifiedProviderWorkItem] = []
        for row in rows:
            try:
                payload = json.loads(str(row["evidence_json"]))
            except json.JSONDecodeError as exc:
                raise ProviderVerificationError(
                    "PR03_STORED_EVIDENCE_JSON_INVALID"
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderVerificationError("PR03_STORED_EVIDENCE_JSON_INVALID")
            mac = str(payload.pop("authentication_mac", ""))
            if not authenticator.verify(payload, mac):
                raise ProviderVerificationError(
                    "PR03_STORED_EVIDENCE_AUTHENTICATION_FAILED"
                )
            rebuilt = dict(payload)
            rebuilt["authentication_mac"] = mac
            if _hash_json(rebuilt) != str(row["evidence_hash"]):
                raise ProviderVerificationError("PR03_STORED_EVIDENCE_HASH_MISMATCH")
            items.append(
                VerifiedProviderWorkItem(
                    event_id=str(row["event_id"]),
                    signature=str(payload["signature"]),
                    slot=int(payload["slot"]),
                    payload_hash=str(row["payload_hash"]),
                    evidence_hash=str(row["evidence_hash"]),
                    raw_evidence_ref=str(payload["raw_evidence_ref"]),
                    release_id=str(row["release_id"]),
                    policy_bundle_hash=str(row["policy_bundle_hash"]),
                )
            )
        return tuple(items)


class RootedProviderIngestionWorker:
    def __init__(
        self,
        *,
        store: RootedProviderIngestionStore,
        verifier: RootedProviderEvidenceVerifier,
        collector: RootedRpcEvidenceCollector,
    ) -> None:
        self.store = store
        self.verifier = verifier
        self.collector = collector

    def run_once(self, admission: ProviderAdmissionBinding) -> WorkerOutcome:
        event: HeliusInboxEvent | None = None
        try:
            event = self.store.next_queued_event()
            if event is None:
                return WorkerOutcome(WorkerDecision.IDLE, None, "PR03_INBOX_EMPTY")
            if self.store.unresolved_gap_blocks(event):
                raise ProviderVerificationError("PR03_ROOTED_GAP_RECOVERY_REQUIRED")
            quorum = self.collector.collect(signature=event.signature, slot=event.slot)
            evidence = self.verifier.verify(
                event=event,
                admission=admission,
                quorum=quorum,
            )
            handoff_id = self.store.commit_verified(event=event, evidence=evidence)
            return WorkerOutcome(
                WorkerDecision.ADMITTED,
                event.event_id,
                "PR03_EVENT_ROOTED_AND_ADMITTED",
                evidence.evidence_hash,
                handoff_id,
            )
        except ProviderVerificationError as exc:
            reason = str(exc) or "PR03_PROVIDER_VERIFICATION_FAILED"
            self.store.record_retryable(event.event_id if event else None, reason)
            return WorkerOutcome(
                WorkerDecision.RETRYABLE_BLOCKED,
                event.event_id if event else None,
                reason,
            )

    def run_bounded(
        self,
        admission: ProviderAdmissionBinding,
        *,
        max_events: int,
    ) -> tuple[WorkerOutcome, ...]:
        if max_events <= 0 or max_events > 1000:
            raise ValueError("max_events must be between 1 and 1000")
        outcomes: list[WorkerOutcome] = []
        for _ in range(max_events):
            outcome = self.run_once(admission)
            outcomes.append(outcome)
            if outcome.decision is not WorkerDecision.ADMITTED:
                break
        return tuple(outcomes)


class A3RootedProviderBatchSource:
    """Concrete A3 source backed only by authenticated durable handoffs."""

    def __init__(
        self,
        *,
        store: RootedProviderIngestionStore,
        authenticator: HmacSha256EvidenceAuthenticator,
        limit: int = 100,
    ) -> None:
        self.store = store
        self.authenticator = authenticator
        self.limit = limit

    def __call__(self):
        from src.paper_shadow.durable_service_a3 import (
            A3ExactAttemptBatch,
            A3ProviderEvidenceState,
        )

        try:
            items = self.store.pending_work_items(
                authenticator=self.authenticator,
                limit=self.limit,
            )
        except ProviderVerificationError as exc:
            reason = str(exc) or "PR03_STORED_EVIDENCE_INVALID"
            evidence_hash = _hash_json(
                {"schema": PR03_BATCH_SCHEMA, "blocker": reason}
            )
            return A3ExactAttemptBatch(
                A3ProviderEvidenceState(evidence_hash, False, (reason,))
            )
        if not items:
            reason = "PR03_ROOTED_PROVIDER_HANDOFF_EMPTY"
            evidence_hash = _hash_json(
                {"schema": PR03_BATCH_SCHEMA, "blocker": reason}
            )
            return A3ExactAttemptBatch(
                A3ProviderEvidenceState(evidence_hash, False, (reason,))
            )
        identities = {
            (item.release_id, item.policy_bundle_hash) for item in items
        }
        if len(identities) != 1:
            reason = "PR03_BATCH_RELEASE_OR_POLICY_MIXED"
            evidence_hash = _hash_json(
                {"schema": PR03_BATCH_SCHEMA, "blocker": reason}
            )
            return A3ExactAttemptBatch(
                A3ProviderEvidenceState(evidence_hash, False, (reason,))
            )
        evidence_hash = _hash_json(
            {
                "schema": PR03_BATCH_SCHEMA,
                "release_id": items[0].release_id,
                "policy_bundle_hash": items[0].policy_bundle_hash,
                "event_evidence_hashes": [item.evidence_hash for item in items],
            }
        )
        return A3ExactAttemptBatch(
            A3ProviderEvidenceState(evidence_hash, True),
            tuple(items),
        )


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


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def _require_sha256(value: str, name: str) -> None:
    if not _is_sha256(value):
        raise ValueError(f"{name} must be lowercase sha256")


def _require_safe_id(value: str, name: str) -> None:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")


__all__ = [
    "A3RootedProviderBatchSource",
    "HeliusInboxEvent",
    "HmacSha256EvidenceAuthenticator",
    "PR03_BATCH_SCHEMA",
    "PR03_EVIDENCE_SCHEMA",
    "PR03_HANDOFF_SCHEMA",
    "ProviderAdmissionBinding",
    "ProviderVerificationError",
    "RootedProviderEvidenceVerifier",
    "RootedProviderIngestionStore",
    "RootedProviderIngestionWorker",
    "RootedRpcEvidence",
    "RootedRpcEvidenceCollector",
    "RpcRootObservation",
    "VerifiedProviderEvent",
    "VerifiedProviderWorkItem",
    "WorkerDecision",
    "WorkerOutcome",
]
