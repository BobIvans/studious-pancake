"""PR-199 isolated signer, submission intent and finality scaffold.

This module is deliberately fail-closed.  It models the PR-199 live boundary
from the consolidated roadmap without implementing key loading, transaction
signing, Jito/RPC transport, or automatic live activation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Protocol

SCHEMA_VERSION = "roadmap-pr199.isolated-submission-boundary.v1"
PRODUCT_ID = "studious-pancake.pr199-isolated-submission-boundary"
COMPILE_TIME_LIVE_SUBMISSION_ENABLED = False
MAX_CANARY_PERMIT_TTL_BLOCKS = 150
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR199TransportKind(StrEnum):
    """Allowed transport identities, not implementations."""

    RPC = "rpc"
    JITO_SINGLE = "jito_single"


class PR199IntentState(StrEnum):
    """Durable intent states before final production transport exists."""

    PREPARED = "prepared"
    ACKNOWLEDGED = "acknowledged"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    FINALIZED = "finalized"
    REVOKED = "revoked"


class PR199Failure(StrEnum):
    PR198_EVIDENCE = "pr198_evidence"
    AUTHORIZATION_BINDING = "authorization_binding"
    POLICY_LIMIT = "policy_limit"
    CANARY_LIMIT = "canary_limit"
    REPLAY_CONFLICT = "replay_conflict"
    INTENT_STATE = "intent_state"
    COMPILE_DISABLED = "compile_disabled"
    ACK_NOT_FINALITY = "ack_not_finality"
    STORE_ERROR = "store_error"


class PR199BoundaryError(RuntimeError):
    """Raised when the PR-199 boundary refuses to advance."""

    def __init__(self, failure: PR199Failure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


class PR199Transport(Protocol):
    """Transport protocol kept unreachable while live submission is disabled."""

    def send(
        self, *, intent: "PR199IntentRecord", signed_payload: bytes
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class PR198AcceptanceEvidence:
    """Manual acceptance proof required before PR-199 can issue permits."""

    release_id: str
    evidence_sha256: str
    reviewer_id: str
    accepted: bool
    independently_reviewed: bool
    multi_day_shadow_soak: bool
    no_sender_modules: bool
    no_signing_keys: bool
    no_live_permit: bool

    def __post_init__(self) -> None:
        identifier(self.release_id, "release_id")
        identifier(self.reviewer_id, "reviewer_id")
        sha256(self.evidence_sha256, "evidence_sha256")

    @property
    def acceptance_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/pr198-acceptance",
                "release_id": self.release_id,
                "evidence_sha256": self.evidence_sha256,
                "reviewer_id": self.reviewer_id,
                "accepted": self.accepted,
                "independently_reviewed": self.independently_reviewed,
                "multi_day_shadow_soak": self.multi_day_shadow_soak,
                "no_sender_modules": self.no_sender_modules,
                "no_signing_keys": self.no_signing_keys,
                "no_live_permit": self.no_live_permit,
            }
        )

    def assert_accepted(self) -> None:
        if not all(
            (
                self.accepted,
                self.independently_reviewed,
                self.multi_day_shadow_soak,
                self.no_sender_modules,
                self.no_signing_keys,
                self.no_live_permit,
            )
        ):
            raise PR199BoundaryError(
                PR199Failure.PR198_EVIDENCE,
                "accepted PR-198 sender-free evidence is required before PR-199",
            )


@dataclass(frozen=True, slots=True)
class PR199CanaryLimits:
    """Hard live-canary bounds used by policy and durable intent admission."""

    max_outstanding_intents: int = 1
    max_principal_lamports: int = 1_000_000
    max_daily_debit_lamports: int = 1_000_000
    max_network_fee_lamports: int = 100_000
    max_priority_fee_lamports: int = 100_000
    max_jito_tip_lamports: int = 100_000
    max_message_bytes: int = 1232

    def __post_init__(self) -> None:
        values = (
            self.max_outstanding_intents,
            self.max_principal_lamports,
            self.max_daily_debit_lamports,
            self.max_network_fee_lamports,
            self.max_priority_fee_lamports,
            self.max_jito_tip_lamports,
            self.max_message_bytes,
        )
        if any(value <= 0 for value in values):
            raise ValueError("PR-199 canary limits must be positive")

    @property
    def limits_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/canary-limits",
                "max_outstanding_intents": self.max_outstanding_intents,
                "max_principal_lamports": self.max_principal_lamports,
                "max_daily_debit_lamports": self.max_daily_debit_lamports,
                "max_network_fee_lamports": self.max_network_fee_lamports,
                "max_priority_fee_lamports": self.max_priority_fee_lamports,
                "max_jito_tip_lamports": self.max_jito_tip_lamports,
                "max_message_bytes": self.max_message_bytes,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199AuthorizationRequest:
    """Semantic signer request; every field participates in the digest."""

    attempt_id: str
    generation: int
    plan_hash: str
    message_sha256: str
    wallet: str
    provider: str
    market: str
    reservation_id: str
    session_id: str
    nonce_digest: str
    config_generation_hash: str
    release_id: str
    policy_bundle_hash: str
    program_ids: tuple[str, ...]
    account_hashes: tuple[str, ...]
    amount_hashes: tuple[str, ...]
    principal_lamports: int
    expected_debit_lamports: int
    network_fee_lamports: int
    priority_fee_lamports: int
    jito_tip_lamports: int
    expires_at_block_height: int
    message_bytes_len: int
    transport: PR199TransportKind

    def __post_init__(self) -> None:
        for value, field in (
            (self.attempt_id, "attempt_id"),
            (self.wallet, "wallet"),
            (self.provider, "provider"),
            (self.market, "market"),
            (self.reservation_id, "reservation_id"),
            (self.session_id, "session_id"),
            (self.release_id, "release_id"),
        ):
            identifier(value, field)
        for value, field in (
            (self.plan_hash, "plan_hash"),
            (self.message_sha256, "message_sha256"),
            (self.nonce_digest, "nonce_digest"),
            (self.config_generation_hash, "config_generation_hash"),
            (self.policy_bundle_hash, "policy_bundle_hash"),
        ):
            sha256(value, field)
        for values, field in (
            (self.program_ids, "program_ids"),
            (self.account_hashes, "account_hashes"),
            (self.amount_hashes, "amount_hashes"),
        ):
            if not values or len(values) != len(set(values)):
                raise ValueError(f"{field} must be non-empty and unique")
            for value in values:
                sha256(value, field[:-1])
        numbers = (
            self.generation,
            self.principal_lamports,
            self.expected_debit_lamports,
            self.network_fee_lamports,
            self.priority_fee_lamports,
            self.jito_tip_lamports,
            self.expires_at_block_height,
            self.message_bytes_len,
        )
        if any(value < 0 for value in numbers) or self.generation < 1:
            raise ValueError("PR-199 authorization numbers must be non-negative")

    @property
    def authorization_digest(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/semantic-authorization",
                "attempt_id": self.attempt_id,
                "generation": self.generation,
                "plan_hash": self.plan_hash,
                "message_sha256": self.message_sha256,
                "wallet": self.wallet,
                "provider": self.provider,
                "market": self.market,
                "reservation_id": self.reservation_id,
                "session_id": self.session_id,
                "nonce_digest": self.nonce_digest,
                "config_generation_hash": self.config_generation_hash,
                "release_id": self.release_id,
                "policy_bundle_hash": self.policy_bundle_hash,
                "program_ids": list(self.program_ids),
                "account_hashes": list(self.account_hashes),
                "amount_hashes": list(self.amount_hashes),
                "principal_lamports": self.principal_lamports,
                "expected_debit_lamports": self.expected_debit_lamports,
                "network_fee_lamports": self.network_fee_lamports,
                "priority_fee_lamports": self.priority_fee_lamports,
                "jito_tip_lamports": self.jito_tip_lamports,
                "expires_at_block_height": self.expires_at_block_height,
                "message_bytes_len": self.message_bytes_len,
                "transport": self.transport.value,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199SubmissionPermit:
    permit_id: str
    authorization_digest: str
    attempt_id: str
    generation: int
    message_sha256: str
    wallet: str
    transport: PR199TransportKind
    reservation_id: str
    nonce_digest: str
    issued_at_block_height: int
    expires_at_block_height: int
    canary_limits_hash: str
    acceptance_hash: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.permit_id, "permit_id"),
            (self.attempt_id, "attempt_id"),
            (self.wallet, "wallet"),
            (self.reservation_id, "reservation_id"),
        ):
            identifier(value, field)
        for value, field in (
            (self.authorization_digest, "authorization_digest"),
            (self.message_sha256, "message_sha256"),
            (self.nonce_digest, "nonce_digest"),
            (self.canary_limits_hash, "canary_limits_hash"),
            (self.acceptance_hash, "acceptance_hash"),
        ):
            sha256(value, field)
        lifetime = self.expires_at_block_height - self.issued_at_block_height
        if self.generation < 1 or not 0 < lifetime <= MAX_CANARY_PERMIT_TTL_BLOCKS:
            raise ValueError("PR-199 permit lifetime must be positive and bounded")

    @property
    def permit_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/permit",
                "permit_id": self.permit_id,
                "authorization_digest": self.authorization_digest,
                "attempt_id": self.attempt_id,
                "generation": self.generation,
                "message_sha256": self.message_sha256,
                "wallet": self.wallet,
                "transport": self.transport.value,
                "reservation_id": self.reservation_id,
                "nonce_digest": self.nonce_digest,
                "issued_at_block_height": self.issued_at_block_height,
                "expires_at_block_height": self.expires_at_block_height,
                "canary_limits_hash": self.canary_limits_hash,
                "acceptance_hash": self.acceptance_hash,
            }
        )

    @property
    def idempotency_key(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/idempotency",
                "authorization_digest": self.authorization_digest,
                "attempt_id": self.attempt_id,
                "generation": self.generation,
                "message_sha256": self.message_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199IntentRecord:
    intent_id: str
    idempotency_key: str
    permit_hash: str
    authorization_digest: str
    message_sha256: str
    attempt_id: str
    generation: int
    transport: PR199TransportKind
    state: PR199IntentState
    signed_payload_sha256: str
    receipt_hash: str | None
    finality_evidence_hash: str | None
    created_at_ns: int
    updated_at_ns: int


class PR199AdmissionPolicy:
    """Fail-closed policy that can only create sender-ready metadata."""

    def __init__(
        self,
        *,
        pr198_evidence: PR198AcceptanceEvidence,
        canary_limits: PR199CanaryLimits | None = None,
    ) -> None:
        pr198_evidence.assert_accepted()
        self.pr198_evidence = pr198_evidence
        self.canary_limits = canary_limits or PR199CanaryLimits()

    def issue_permit(
        self,
        request: PR199AuthorizationRequest,
        *,
        permit_id: str,
        issued_at_block_height: int,
    ) -> PR199SubmissionPermit:
        self._validate_request(request, issued_at_block_height)
        return PR199SubmissionPermit(
            permit_id=permit_id,
            authorization_digest=request.authorization_digest,
            attempt_id=request.attempt_id,
            generation=request.generation,
            message_sha256=request.message_sha256,
            wallet=request.wallet,
            transport=request.transport,
            reservation_id=request.reservation_id,
            nonce_digest=request.nonce_digest,
            issued_at_block_height=issued_at_block_height,
            expires_at_block_height=request.expires_at_block_height,
            canary_limits_hash=self.canary_limits.limits_hash,
            acceptance_hash=self.pr198_evidence.acceptance_hash,
        )

    def _validate_request(
        self, request: PR199AuthorizationRequest, issued_at_block_height: int
    ) -> None:
        if request.expires_at_block_height <= issued_at_block_height:
            raise PR199BoundaryError(
                PR199Failure.AUTHORIZATION_BINDING,
                "authorization expires before permit issuance",
            )
        lifetime = request.expires_at_block_height - issued_at_block_height
        if lifetime > MAX_CANARY_PERMIT_TTL_BLOCKS:
            raise PR199BoundaryError(
                PR199Failure.POLICY_LIMIT,
                "permit block-height lifetime exceeds canary bound",
            )
        limits = self.canary_limits
        limit_checks = (
            request.principal_lamports <= limits.max_principal_lamports,
            request.expected_debit_lamports <= limits.max_daily_debit_lamports,
            request.network_fee_lamports <= limits.max_network_fee_lamports,
            request.priority_fee_lamports <= limits.max_priority_fee_lamports,
            request.jito_tip_lamports <= limits.max_jito_tip_lamports,
            request.message_bytes_len <= limits.max_message_bytes,
        )
        if not all(limit_checks):
            raise PR199BoundaryError(
                PR199Failure.POLICY_LIMIT,
                "authorization exceeds limited-canary bounds",
            )
        if request.transport is PR199TransportKind.JITO_SINGLE and request.jito_tip_lamports <= 0:
            raise PR199BoundaryError(
                PR199Failure.POLICY_LIMIT,
                "Jito transport requires a positive same-payload tip",
            )
        if request.transport is PR199TransportKind.RPC and request.jito_tip_lamports != 0:
            raise PR199BoundaryError(
                PR199Failure.POLICY_LIMIT,
                "RPC transport cannot carry a Jito tip",
            )


class PR199SubmissionIntentStore:
    """Small durable exactly-once intent ledger for PR-199 review tests."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 250) -> None:
        if not 0 <= busy_timeout_ms <= 5_000:
            raise ValueError("busy_timeout_ms must be between 0 and 5000")
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS pr199_meta(
                      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                      product_id TEXT NOT NULL,
                      schema_version TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS pr199_intent(
                      intent_id TEXT PRIMARY KEY,
                      idempotency_key TEXT NOT NULL UNIQUE,
                      permit_hash TEXT NOT NULL,
                      authorization_digest TEXT NOT NULL,
                      message_sha256 TEXT NOT NULL,
                      attempt_id TEXT NOT NULL,
                      generation INTEGER NOT NULL,
                      transport TEXT NOT NULL,
                      state TEXT NOT NULL,
                      signed_payload_sha256 TEXT NOT NULL,
                      receipt_hash TEXT,
                      finality_evidence_hash TEXT,
                      created_at_ns INTEGER NOT NULL,
                      updated_at_ns INTEGER NOT NULL
                    );
                    """
                )
                connection.execute(
                    """INSERT INTO pr199_meta VALUES(1, ?, ?)
                    ON CONFLICT(singleton) DO NOTHING""",
                    (PRODUCT_ID, SCHEMA_VERSION),
                )
                row = connection.execute(
                    "SELECT product_id, schema_version FROM pr199_meta"
                ).fetchone()
                if row is None or tuple(row) != (PRODUCT_ID, SCHEMA_VERSION):
                    raise PR199BoundaryError(
                        PR199Failure.STORE_ERROR, "database identity mismatch"
                    )
        except PR199BoundaryError:
            raise
        except sqlite3.Error as exc:
            raise PR199BoundaryError(
                PR199Failure.STORE_ERROR, "database initialization failed"
            ) from exc

    def prepare(
        self,
        permit: PR199SubmissionPermit,
        *,
        signed_payload_sha256: str,
        max_outstanding_intents: int,
        now_ns: int,
    ) -> PR199IntentRecord:
        sha256(signed_payload_sha256, "signed_payload_sha256")
        if max_outstanding_intents <= 0:
            raise ValueError("max_outstanding_intents must be positive")
        intent_id = f"pr199_intent_{permit.idempotency_key}"
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM pr199_intent WHERE idempotency_key=?",
                    (permit.idempotency_key,),
                ).fetchone()
                if row is not None:
                    record = self._record(row)
                    connection.execute("COMMIT")
                    if (
                        record.permit_hash == permit.permit_hash
                        and record.signed_payload_sha256 == signed_payload_sha256
                    ):
                        return record
                    raise PR199BoundaryError(
                        PR199Failure.REPLAY_CONFLICT,
                        "idempotency identity conflicts with signed payload",
                    )
                outstanding = connection.execute(
                    """SELECT COUNT(*) FROM pr199_intent
                    WHERE state IN (?, ?, ?)""",
                    (
                        PR199IntentState.PREPARED.value,
                        PR199IntentState.ACKNOWLEDGED.value,
                        PR199IntentState.SUBMISSION_UNCERTAIN.value,
                    ),
                ).fetchone()[0]
                if outstanding >= max_outstanding_intents:
                    connection.execute("ROLLBACK")
                    raise PR199BoundaryError(
                        PR199Failure.CANARY_LIMIT,
                        "limited canary allows no additional outstanding intent",
                    )
                connection.execute(
                    """INSERT INTO pr199_intent VALUES(
                    ?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)""",
                    (
                        intent_id,
                        permit.idempotency_key,
                        permit.permit_hash,
                        permit.authorization_digest,
                        permit.message_sha256,
                        permit.attempt_id,
                        permit.generation,
                        permit.transport.value,
                        PR199IntentState.PREPARED.value,
                        signed_payload_sha256,
                        now_ns,
                        now_ns,
                    ),
                )
                connection.execute("COMMIT")
                return PR199IntentRecord(
                    intent_id= intent_id,
                    idempotency_key=permit.idempotency_key,
                    permit_hash=permit.permit_hash,
                    authorization_digest=permit.authorization_digest,
                    message_sha256=permit.message_sha256,
                    attempt_id=permit.attempt_id,
                    generation=permit.generation,
                    transport=permit.transport,
                    state=PR199IntentState.PREPARED,
                    signed_payload_sha256=signed_payload_sha256,
                    receipt_hash=None,
                    finality_evidence_hash=None,
                    created_at_ns=now_ns,
                    updated_at_ns=now_ns,
                )
        except PR199BoundaryError:
            raise
        except sqlite3.Error as exc:
            raise PR199BoundaryError(
                PR199Failure.STORE_ERROR, "failed to persist PR-199 intent"
            ) from exc

    def transition(
        self,
        intent_id: str,
        *,
        expected: PR199IntentState,
        target: PR199IntentState,
        now_ns: int,
        receipt_hash: str | None = None,
        finality_evidence_hash: str | None = None,
    ) -> PR199IntentRecord:
        identifier(intent_id, "intent_id")
        if receipt_hash is not None:
            sha256(receipt_hash, "receipt_hash")
        if finality_evidence_hash is not None:
            sha256(finality_evidence_hash, "finality_evidence_hash")
        allowed = {
            (PR199IntentState.PREPARED, PR199IntentState.ACKNOWLEDGED),
            (PR199IntentState.PREPARED, PR199IntentState.SUBMISSION_UNCERTAIN),
            (PR199IntentState.PREPARED, PR199IntentState.REVOKED),
            (PR199IntentState.ACKNOWLEDGED, PR199IntentState.SUBMISSION_UNCERTAIN),
            (PR199IntentState.ACKNOWLEDGED, PR199IntentState.FINALIZED),
            (PR199IntentState.SUBMISSION_UNCERTAIN, PR199IntentState.FINALIZED),
        }
        if (expected, target) not in allowed:
            raise PR199BoundaryError(
                PR199Failure.INTENT_STATE, "unsupported PR-199 intent transition"
            )
        if target is PR199IntentState.FINALIZED and finality_evidence_hash is None:
            raise PR199BoundaryError(
                PR199Failure.ACK_NOT_FINALITY,
                "finality requires chain reconciliation evidence, not an ACK",
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    """UPDATE pr199_intent
                    SET state=?, receipt_hash=COALESCE(?, receipt_hash),
                        finality_evidence_hash=COALESCE(?, finality_evidence_hash),
                        updated_at_ns=?
                    WHERE intent_id=? AND state=?""",
                    (
                        target.value,
                        receipt_hash,
                        finality_evidence_hash,
                        now_ns,
                        intent_id,
                        expected.value,
                    ),
                ).rowcount
                if changed != 1:
                    connection.execute("ROLLBACK")
                    raise PR199BoundaryError(
                        PR199Failure.INTENT_STATE,
                        "intent compare-and-swap failed",
                    )
                row = connection.execute(
                    "SELECT * FROM pr199_intent WHERE intent_id=?", (intent_id,)
                ).fetchone()
                connection.execute("COMMIT")
                if row is None:
                    raise PR199BoundaryError(
                        PR199Failure.STORE_ERROR, "updated intent is missing"
                    )
                return self._record(row)
        except PR199BoundaryError:
            raise
        except sqlite3.Error as exc:
            raise PR199BoundaryError(
                PR199Failure.STORE_ERROR, "failed to transition PR-199 intent"
            ) from exc

    @staticmethod
    def _record(row: sqlite3.Row) -> PR199IntentRecord:
        return PR199IntentRecord(
            intent_id=row["intent_id"],
            idempotency_key=row["idempotency_key"],
            permit_hash=row["permit_hash"],
            authorization_digest=row["authorization_digest"],
            message_sha256=row["message_sha256"],
            attempt_id=row["attempt_id"],
            generation=row["generation"],
            transport=PR199TransportKind(row["transport"]),
            state=PR199IntentState(row["state"]),
            signed_payload_sha256=row["signed_payload_sha256"],
            receipt_hash=row["receipt_hash"],
            finality_evidence_hash=row["finality_evidence_hash"],
            created_at_ns=row["created_at_ns"],
            updated_at_ns=row["updated_at_ns"],
        )


class PR199SubmissionBoundary:
    """Coordinates policy and durable intent without live transport access."""

    def __init__(
        self,
        *,
        policy: PR199AdmissionPolicy,
        store: PR199SubmissionIntentStore,
        clock_ns=time.time_ns,
    ) -> None:
        self.policy = policy
        self.store = store
        self.clock_ns = clock_ns

    def prepare_intent(
        self,
        *,
        request: PR199AuthorizationRequest,
        permit_id: str,
        issued_at_block_height: int,
        signed_payload_sha256: str,
    ) -> PR199IntentRecord:
        permit = self.policy.issue_permit(
            request,
            permit_id=permit_id,
            issued_at_block_height=issued_at_block_height,
        )
        return self.store.prepare(
            permit,
            signed_payload_sha256=signed_payload_sha256,
            max_outstanding_intents=self.policy.canary_limits.max_outstanding_intents,
            now_ns=int(self.clock_ns()),
        )

    def dispatch_once(
        self,
        *,
        intent: PR199IntentRecord,
        signed_payload: bytes,
        transport: PR199Transport,
    ) -> Mapping[str, object]:
        del intent, signed_payload, transport
        if not COMPILE_TIME_LIVE_SUBMISSION_ENABLED:
            raise PR199BoundaryError(
                PR199Failure.COMPILE_DISABLED,
                "PR-199 live submission is compile-time disabled in this scaffold",
            )
        raise AssertionError("unreachable while PR-199 live submission is disabled")

    def acknowledge_transport(
        self, intent: PR199IntentRecord, *, receipt_hash: str
    ) -> PR199IntentRecord:
        return self.store.transition(
            intent.intent_id,
            expected=PR199IntentState.PREPARED,
            target=PR199IntentState.ACKNOWLEDGED,
            receipt_hash=receipt_hash,
            now_ns=int(self.clock_ns()),
        )

    def mark_uncertain(self, intent: PR199IntentRecord) -> PR199IntentRecord:
        return self.store.transition(
            intent.intent_id,
            expected=intent.state,
            target=PR199IntentState.SUBMISSION_UNCERTAIN,
            now_ns=int(self.clock_ns()),
        )

    def finalize_from_chain(
        self, intent: PR199IntentRecord, *, finality_evidence_hash: str
    ) -> PR199IntentRecord:
        return self.store.transition(
            intent.intent_id,
            expected=intent.state,
            target=PR199IntentState.FINALIZED,
            finality_evidence_hash=finality_evidence_hash,
            now_ns=int(self.clock_ns()),
        )



def pr199_status_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "roadmap_pr": "PR-199",
        "compile_time_live_submission_enabled": COMPILE_TIME_LIVE_SUBMISSION_ENABLED,
        "private_key_loader_present": False,
        "network_transport_implementation_present": False,
        "requires_accepted_pr198_evidence": True,
        "ack_is_finality": False,
        "automatic_scale_up_supported": False,
    }



def identifier(value: str, field: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded structured identifier")
    return value



def sha256(value: str, field: str) -> str:
    if not _SHA256_RE.fullmatch(value) or len(set(value)) == 1:
        raise ValueError(f"{field} must be a non-placeholder lowercase sha256")
    return value



def hash_json(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
