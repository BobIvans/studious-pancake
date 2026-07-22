"""PR-201 trusted authorization challenges and durable replay protection.

This standard-library-only module never imports a wallet, signs, submits, or calls
RPC. It provides the one-time boundary an isolated signer/operator backend must use.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from src.signer_authorization_pr141 import (
    SignerAuthorizationRequest,
    TransactionAuthorization,
    authorize_transaction,
    is_sha256_hex,
)

SCHEMA_VERSION = "pr201.authorization-replay.v1"
PRODUCT_ID = "flashloan-bot.authorization-replay"
_MIN_NONCE_BYTES = 32
_MAX_RESULT_BYTES = 128 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class AuthorizationDomain(StrEnum):
    SIGNER_TRANSACTION = "signer_transaction"
    OPERATOR_APPROVAL = "operator_approval"
    RECOVERY_ACTION = "recovery_action"
    RELEASE_ACTIVATION = "release_activation"
    SUBMISSION_PERMIT = "submission_permit"
    TREASURY_TRANSFER = "treasury_transfer"


class ChallengeState(StrEnum):
    ISSUED = "issued"
    RESERVED = "reserved"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONFLICTED = "conflicted"


class ReplayFailure(StrEnum):
    BAD_CHALLENGE = "bad_challenge"
    BAD_AUTHORITY = "bad_authority"
    BAD_BINDING = "bad_binding"
    BAD_NONCE = "bad_nonce"
    NONCE_REUSED = "nonce_reused"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"
    CONFLICTED = "conflicted"
    RESULT_INVALID = "result_invalid"
    EXECUTION_UNKNOWN = "execution_unknown"
    STORE_ERROR = "store_error"


class ReplayProtectionError(RuntimeError):
    """Stable fail-closed error without secret-bearing backend text."""

    def __init__(self, failure: ReplayFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class AuthorizationChallenge:
    schema_version: str
    challenge_id: str
    issuer_id: str
    issuer_key_id: str
    domain: AuthorizationDomain
    purpose: str
    release_id: str
    policy_bundle_hash: str
    attempt_id: str
    attempt_generation: int
    operation_hash: str
    environment: str
    cluster: str
    nonce_b64: str
    nonce_digest: str
    issued_at_ns: int
    expires_at_ns: int
    authority_tag: str

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "challenge_id": self.challenge_id,
            "issuer_id": self.issuer_id,
            "issuer_key_id": self.issuer_key_id,
            "domain": self.domain.value,
            "purpose": self.purpose,
            "release_id": self.release_id,
            "policy_bundle_hash": self.policy_bundle_hash,
            "attempt_id": self.attempt_id,
            "attempt_generation": self.attempt_generation,
            "operation_hash": self.operation_hash,
            "environment": self.environment,
            "cluster": self.cluster,
            "nonce_b64": self.nonce_b64,
            "nonce_digest": self.nonce_digest,
            "issued_at_ns": self.issued_at_ns,
            "expires_at_ns": self.expires_at_ns,
        }

    @property
    def envelope_hash(self) -> str:
        return _hash_json(
            {
                "domain": "flashloan-bot/pr201/challenge-envelope",
                "payload": self.unsigned_payload(),
                "authority_tag": self.authority_tag,
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    result_kind: str
    payload_json: str
    result_sha256: str

    @classmethod
    def from_payload(
        cls, result_kind: str, payload: Mapping[str, object]
    ) -> AuthorizationResult:
        _identifier("result_kind", result_kind)
        payload_json = _json(dict(payload))
        if len(payload_json.encode()) > _MAX_RESULT_BYTES:
            raise ReplayProtectionError(
                ReplayFailure.RESULT_INVALID, "authorization result is too large"
            )
        digest = _hash_json(
            {
                "domain": "flashloan-bot/pr201/authorization-result",
                "result_kind": result_kind,
                "payload": json.loads(payload_json),
            }
        )
        return cls(result_kind, payload_json, digest)

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ReplayProtectionError(
                ReplayFailure.RESULT_INVALID, "stored result is not a JSON object"
            )
        return value

    def validate(self) -> None:
        expected = self.from_payload(self.result_kind, self.payload())
        if not hmac.compare_digest(expected.result_sha256, self.result_sha256):
            raise ReplayProtectionError(
                ReplayFailure.RESULT_INVALID, "stored result digest mismatch"
            )


@dataclass(frozen=True, slots=True)
class AuthorizationExecution:
    challenge_id: str
    operation_id: str
    result: AuthorizationResult
    replayed: bool


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    challenge_id: str
    state: ChallengeState
    nonce_digest: str
    domain: AuthorizationDomain
    operation_hash: str
    reserved_operation_id: str | None
    request_hash: str | None
    result: AuthorizationResult | None


@dataclass(frozen=True, slots=True)
class _Reservation:
    acquired: bool
    operation_id: str
    result: AuthorizationResult | None = None


class SQLiteAuthorizationReplayLedger:
    """Durable single-use ledger with bounded SQLite lock waiting."""

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
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS authorization_replay_meta(
                      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                      product_id TEXT NOT NULL,
                      schema_version TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS authorization_nonce_ledger(
                      challenge_id TEXT PRIMARY KEY,
                      nonce_digest TEXT NOT NULL UNIQUE,
                      envelope_hash TEXT NOT NULL UNIQUE,
                      issuer_id TEXT NOT NULL,
                      issuer_key_id TEXT NOT NULL,
                      domain TEXT NOT NULL,
                      purpose TEXT NOT NULL,
                      release_id TEXT NOT NULL,
                      policy_bundle_hash TEXT NOT NULL,
                      attempt_id TEXT NOT NULL,
                      attempt_generation INTEGER NOT NULL,
                      operation_hash TEXT NOT NULL,
                      environment TEXT NOT NULL,
                      cluster TEXT NOT NULL,
                      issued_at_ns INTEGER NOT NULL,
                      expires_at_ns INTEGER NOT NULL,
                      state TEXT NOT NULL,
                      authority_tag TEXT NOT NULL,
                      reserved_operation_id TEXT,
                      request_hash TEXT,
                      result_kind TEXT,
                      result_payload_json TEXT,
                      result_sha256 TEXT,
                      updated_at_ns INTEGER NOT NULL,
                      consumed_at_ns INTEGER,
                      conflict_reason TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_pr201_state_expiry
                    ON authorization_nonce_ledger(state, expires_at_ns);
                    """
                )
                connection.execute(
                    """INSERT INTO authorization_replay_meta VALUES(1, ?, ?)
                    ON CONFLICT(singleton) DO NOTHING""",
                    (PRODUCT_ID, SCHEMA_VERSION),
                )
                row = connection.execute(
                    "SELECT product_id, schema_version FROM authorization_replay_meta"
                ).fetchone()
                if row is None or tuple(row) != (PRODUCT_ID, SCHEMA_VERSION):
                    raise ReplayProtectionError(
                        ReplayFailure.STORE_ERROR,
                        "authorization replay database identity mismatch",
                    )
        except ReplayProtectionError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("database initialization failed", exc)

    def record_issued(self, challenge: AuthorizationChallenge, *, now_ns: int) -> None:
        values = (
            challenge.challenge_id,
            challenge.nonce_digest,
            challenge.envelope_hash,
            challenge.issuer_id,
            challenge.issuer_key_id,
            challenge.domain.value,
            challenge.purpose,
            challenge.release_id,
            challenge.policy_bundle_hash,
            challenge.attempt_id,
            challenge.attempt_generation,
            challenge.operation_hash,
            challenge.environment,
            challenge.cluster,
            challenge.issued_at_ns,
            challenge.expires_at_ns,
            ChallengeState.ISSUED.value,
            challenge.authority_tag,
            now_ns,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO authorization_nonce_ledger(
                      challenge_id, nonce_digest, envelope_hash, issuer_id,
                      issuer_key_id, domain, purpose, release_id,
                      policy_bundle_hash, attempt_id, attempt_generation,
                      operation_hash, environment, cluster, issued_at_ns,
                      expires_at_ns, state, authority_tag, updated_at_ns
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise ReplayProtectionError(
                ReplayFailure.NONCE_REUSED,
                "challenge or nonce already exists in replay ledger",
            ) from exc
        except sqlite3.Error as exc:
            raise self._store_error("failed to persist challenge", exc)

    def reserve(
        self,
        challenge: AuthorizationChallenge,
        *,
        operation_id: str,
        request_hash: str,
        now_ns: int,
    ) -> _Reservation:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = self._row(connection, challenge.challenge_id)
                self._match(row, challenge)
                state = ChallengeState(row["state"])
                if state is ChallengeState.ISSUED and now_ns >= row["expires_at_ns"]:
                    connection.execute(
                        "UPDATE authorization_nonce_ledger "
                        "SET state=?, updated_at_ns=? "
                        "WHERE challenge_id=? AND state=?",
                        (
                            ChallengeState.EXPIRED.value,
                            now_ns,
                            challenge.challenge_id,
                            ChallengeState.ISSUED.value,
                        ),
                    )
                    connection.execute("COMMIT")
                    raise ReplayProtectionError(
                        ReplayFailure.EXPIRED, "authorization challenge expired"
                    )
                if state is ChallengeState.CONSUMED:
                    if self._same_request(row, operation_id, request_hash):
                        result = self._result(row)
                        connection.execute("COMMIT")
                        return _Reservation(False, operation_id, result)
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        ReplayFailure.REPLAYED, "challenge already consumed"
                    )
                if state is ChallengeState.RESERVED:
                    connection.execute("ROLLBACK")
                    failure = (
                        ReplayFailure.IN_PROGRESS
                        if self._same_request(row, operation_id, request_hash)
                        else ReplayFailure.CONFLICTED
                    )
                    raise ReplayProtectionError(
                        failure, "challenge is already reserved; reconcile first"
                    )
                failure_by_state = {
                    ChallengeState.EXPIRED: ReplayFailure.EXPIRED,
                    ChallengeState.REVOKED: ReplayFailure.REVOKED,
                    ChallengeState.CONFLICTED: ReplayFailure.CONFLICTED,
                }
                if state in failure_by_state:
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        failure_by_state[state], f"challenge state is {state.value}"
                    )
                updated = connection.execute(
                    """UPDATE authorization_nonce_ledger
                    SET state=?, reserved_operation_id=?, request_hash=?,
                        updated_at_ns=?
                    WHERE challenge_id=? AND state=?""",
                    (
                        ChallengeState.RESERVED.value,
                        operation_id,
                        request_hash,
                        now_ns,
                        challenge.challenge_id,
                        ChallengeState.ISSUED.value,
                    ),
                ).rowcount
                if updated != 1:
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        ReplayFailure.CONFLICTED, "reservation compare-and-swap failed"
                    )
                connection.execute("COMMIT")
                return _Reservation(True, operation_id)
        except ReplayProtectionError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("failed to reserve challenge", exc)

    def finalize(
        self,
        challenge: AuthorizationChallenge,
        *,
        operation_id: str,
        request_hash: str,
        result: AuthorizationResult,
        now_ns: int,
    ) -> AuthorizationExecution:
        result.validate()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = self._row(connection, challenge.challenge_id)
                self._match(row, challenge)
                state = ChallengeState(row["state"])
                if state is ChallengeState.CONSUMED:
                    stored = self._result(row)
                    if (
                        self._same_request(row, operation_id, request_hash)
                        and stored.result_sha256 == result.result_sha256
                    ):
                        connection.execute("COMMIT")
                        return AuthorizationExecution(
                            challenge.challenge_id, operation_id, stored, True
                        )
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        ReplayFailure.REPLAYED,
                        "result conflicts with consumed challenge",
                    )
                if state is not ChallengeState.RESERVED or not self._same_request(
                    row, operation_id, request_hash
                ):
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        ReplayFailure.CONFLICTED,
                        "finalization does not match durable reservation",
                    )
                updated = connection.execute(
                    """UPDATE authorization_nonce_ledger
                    SET state=?, result_kind=?, result_payload_json=?, result_sha256=?,
                        consumed_at_ns=?, updated_at_ns=?
                    WHERE challenge_id=? AND state=? AND reserved_operation_id=?
                      AND request_hash=?""",
                    (
                        ChallengeState.CONSUMED.value,
                        result.result_kind,
                        result.payload_json,
                        result.result_sha256,
                        now_ns,
                        now_ns,
                        challenge.challenge_id,
                        ChallengeState.RESERVED.value,
                        operation_id,
                        request_hash,
                    ),
                ).rowcount
                if updated != 1:
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        ReplayFailure.CONFLICTED, "finalization compare-and-swap failed"
                    )
                connection.execute("COMMIT")
                return AuthorizationExecution(
                    challenge.challenge_id, operation_id, result, False
                )
        except ReplayProtectionError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("failed to finalize challenge", exc)

    def revoke(self, challenge_id: str, *, now_ns: int, reason: str) -> None:
        _identifier("challenge_id", challenge_id)
        safe_reason = reason.strip()[:128]
        if not safe_reason:
            raise ValueError("revocation reason is required")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = self._row(connection, challenge_id)
                state = ChallengeState(row["state"])
                if state is ChallengeState.CONSUMED:
                    connection.execute("ROLLBACK")
                    raise ReplayProtectionError(
                        ReplayFailure.REPLAYED, "consumed challenge cannot be revoked"
                    )
                target = (
                    ChallengeState.CONFLICTED
                    if state is ChallengeState.RESERVED
                    else ChallengeState.REVOKED
                )
                connection.execute(
                    "UPDATE authorization_nonce_ledger "
                    "SET state=?, conflict_reason=?, updated_at_ns=? "
                    "WHERE challenge_id=?",
                    (target.value, safe_reason, now_ns, challenge_id),
                )
                connection.execute("COMMIT")
        except ReplayProtectionError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("failed to revoke challenge", exc)

    def get(self, challenge_id: str) -> LedgerRecord | None:
        _identifier("challenge_id", challenge_id)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM authorization_nonce_ledger WHERE challenge_id=?",
                    (challenge_id,),
                ).fetchone()
            if row is None:
                return None
            result = self._result(row) if row["result_sha256"] is not None else None
            return LedgerRecord(
                challenge_id=row["challenge_id"],
                state=ChallengeState(row["state"]),
                nonce_digest=row["nonce_digest"],
                domain=AuthorizationDomain(row["domain"]),
                operation_hash=row["operation_hash"],
                reserved_operation_id=row["reserved_operation_id"],
                request_hash=row["request_hash"],
                result=result,
            )
        except sqlite3.Error as exc:
            raise self._store_error("failed to read challenge", exc)

    @staticmethod
    def _row(connection: sqlite3.Connection, challenge_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM authorization_nonce_ledger WHERE challenge_id=?",
            (challenge_id,),
        ).fetchone()
        if row is None:
            raise ReplayProtectionError(
                ReplayFailure.BAD_CHALLENGE, "challenge is absent from replay ledger"
            )
        return row

    @staticmethod
    def _match(row: sqlite3.Row, challenge: AuthorizationChallenge) -> None:
        expected = {
            "nonce_digest": challenge.nonce_digest,
            "envelope_hash": challenge.envelope_hash,
            "issuer_id": challenge.issuer_id,
            "issuer_key_id": challenge.issuer_key_id,
            "domain": challenge.domain.value,
            "operation_hash": challenge.operation_hash,
            "authority_tag": challenge.authority_tag,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise ReplayProtectionError(
                ReplayFailure.BAD_BINDING,
                "challenge does not match durable issuer record",
            )

    @staticmethod
    def _same_request(row: sqlite3.Row, operation_id: str, request_hash: str) -> bool:
        return (
            row["reserved_operation_id"] == operation_id
            and row["request_hash"] == request_hash
        )

    @staticmethod
    def _result(row: sqlite3.Row) -> AuthorizationResult:
        fields = (row["result_kind"], row["result_payload_json"], row["result_sha256"])
        if any(value is None for value in fields):
            raise ReplayProtectionError(
                ReplayFailure.STORE_ERROR, "consumed challenge has no durable result"
            )
        result = AuthorizationResult(*fields)
        result.validate()
        return result

    @staticmethod
    def _store_error(message: str, exc: sqlite3.Error) -> ReplayProtectionError:
        return ReplayProtectionError(ReplayFailure.STORE_ERROR, message)


class AuthorizationReplayService:
    """Trusted CSPRNG issuer and one-time execution coordinator."""

    def __init__(
        self,
        ledger: SQLiteAuthorizationReplayLedger,
        *,
        issuer_id: str,
        issuer_key_id: str,
        mac_key: bytes,
        environment: str,
        cluster: str,
        clock_ns: Callable[[], int] = time.time_ns,
        nonce_factory: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        for name, value in (
            ("issuer_id", issuer_id),
            ("issuer_key_id", issuer_key_id),
            ("environment", environment),
            ("cluster", cluster),
        ):
            _identifier(name, value)
        if len(mac_key) < 32:
            raise ValueError("mac_key must contain at least 256 bits")
        self.ledger = ledger
        self.issuer_id = issuer_id
        self.issuer_key_id = issuer_key_id
        self._mac_key = bytes(mac_key)
        self.environment = environment
        self.cluster = cluster
        self._clock_ns = clock_ns
        self._nonce_factory = nonce_factory

    def issue(
        self,
        *,
        domain: AuthorizationDomain,
        purpose: str,
        release_id: str,
        policy_bundle_hash: str,
        attempt_id: str,
        attempt_generation: int,
        operation_hash: str,
        ttl_ns: int,
    ) -> AuthorizationChallenge:
        for name, value in (
            ("purpose", purpose),
            ("release_id", release_id),
            ("attempt_id", attempt_id),
        ):
            _identifier(name, value)
        if attempt_generation < 0:
            raise ValueError("attempt_generation cannot be negative")
        if not is_sha256_hex(policy_bundle_hash) or not is_sha256_hex(operation_hash):
            raise ValueError("policy and operation hashes must be lowercase sha256")
        if not 0 < ttl_ns <= 15 * 60 * 1_000_000_000:
            raise ValueError("ttl_ns must be positive and no longer than 15 minutes")
        issued_at_ns = self._clock_ns()
        nonce = self._nonce_factory(_MIN_NONCE_BYTES)
        _validate_nonce(nonce)
        nonce_b64 = base64.urlsafe_b64encode(nonce).rstrip(b"=").decode()
        unsigned = AuthorizationChallenge(
            schema_version=SCHEMA_VERSION,
            challenge_id=f"authz_{uuid.uuid4().hex}",
            issuer_id=self.issuer_id,
            issuer_key_id=self.issuer_key_id,
            domain=domain,
            purpose=purpose,
            release_id=release_id,
            policy_bundle_hash=policy_bundle_hash,
            attempt_id=attempt_id,
            attempt_generation=attempt_generation,
            operation_hash=operation_hash,
            environment=self.environment,
            cluster=self.cluster,
            nonce_b64=nonce_b64,
            nonce_digest=hashlib.sha256(nonce).hexdigest(),
            issued_at_ns=issued_at_ns,
            expires_at_ns=issued_at_ns + ttl_ns,
            authority_tag="",
        )
        payload = unsigned.unsigned_payload()
        payload["domain"] = domain
        payload["authority_tag"] = self._tag(unsigned.unsigned_payload())
        challenge = AuthorizationChallenge(**payload)  # type: ignore[arg-type]
        self.ledger.record_issued(challenge, now_ns=issued_at_ns)
        return challenge

    def verify(
        self, challenge: AuthorizationChallenge, *, now_ns: int | None = None
    ) -> None:
        if challenge.schema_version != SCHEMA_VERSION:
            raise ReplayProtectionError(
                ReplayFailure.BAD_CHALLENGE, "unsupported challenge schema"
            )
        if (
            challenge.issuer_id != self.issuer_id
            or challenge.issuer_key_id != self.issuer_key_id
        ):
            raise ReplayProtectionError(
                ReplayFailure.BAD_AUTHORITY, "challenge issuer/key is not active"
            )
        if (
            challenge.environment != self.environment
            or challenge.cluster != self.cluster
        ):
            raise ReplayProtectionError(
                ReplayFailure.BAD_BINDING, "challenge environment/cluster mismatch"
            )
        nonce = _decode_nonce(challenge.nonce_b64)
        _validate_nonce(nonce)
        if not hmac.compare_digest(
            hashlib.sha256(nonce).hexdigest(), challenge.nonce_digest
        ):
            raise ReplayProtectionError(
                ReplayFailure.BAD_NONCE, "challenge nonce digest mismatch"
            )
        if not hmac.compare_digest(
            self._tag(challenge.unsigned_payload()), challenge.authority_tag
        ):
            raise ReplayProtectionError(
                ReplayFailure.BAD_AUTHORITY, "challenge authority tag is invalid"
            )
        current = self._clock_ns() if now_ns is None else now_ns
        if challenge.expires_at_ns <= challenge.issued_at_ns:
            raise ReplayProtectionError(
                ReplayFailure.BAD_CHALLENGE, "challenge expiry is invalid"
            )
        if current >= challenge.expires_at_ns:
            raise ReplayProtectionError(
                ReplayFailure.EXPIRED, "authorization challenge expired"
            )

    def execute_once(
        self,
        challenge: AuthorizationChallenge,
        *,
        request_hash: str,
        executor: Callable[[str], AuthorizationResult],
        now_ns: int | None = None,
    ) -> AuthorizationExecution:
        if not is_sha256_hex(request_hash):
            raise ReplayProtectionError(
                ReplayFailure.BAD_BINDING, "request hash must be lowercase sha256"
            )
        current = self._clock_ns() if now_ns is None else now_ns
        self.verify(challenge, now_ns=current)
        operation_id = _operation_id(challenge, request_hash)
        reservation = self.ledger.reserve(
            challenge,
            operation_id=operation_id,
            request_hash=request_hash,
            now_ns=current,
        )
        if not reservation.acquired:
            if reservation.result is None:
                raise ReplayProtectionError(
                    ReplayFailure.STORE_ERROR, "consumed challenge has no result"
                )
            return AuthorizationExecution(
                challenge.challenge_id, operation_id, reservation.result, True
            )
        try:
            result = executor(operation_id)
            if not isinstance(result, AuthorizationResult):
                raise ReplayProtectionError(
                    ReplayFailure.RESULT_INVALID, "executor returned invalid result"
                )
            result.validate()
        except ReplayProtectionError:
            raise
        except Exception as exc:
            raise ReplayProtectionError(
                ReplayFailure.EXECUTION_UNKNOWN,
                "backend outcome is unknown; reconcile reserved operation",
            ) from exc
        return self.ledger.finalize(
            challenge,
            operation_id=operation_id,
            request_hash=request_hash,
            result=result,
            now_ns=self._clock_ns(),
        )

    def recover_result(
        self,
        challenge: AuthorizationChallenge,
        *,
        request_hash: str,
        result: AuthorizationResult,
        now_ns: int | None = None,
    ) -> AuthorizationExecution:
        current = self._clock_ns() if now_ns is None else now_ns
        self.verify(challenge, now_ns=current)
        return self.ledger.finalize(
            challenge,
            operation_id=_operation_id(challenge, request_hash),
            request_hash=request_hash,
            result=result,
            now_ns=current,
        )

    def _tag(self, payload: Mapping[str, object]) -> str:
        message = _json(
            {
                "domain": "flashloan-bot/pr201/challenge-authority",
                "payload": dict(payload),
            }
        ).encode()
        return hmac.new(self._mac_key, message, hashlib.sha256).hexdigest()


def authorize_pr141_once(
    service: AuthorizationReplayService,
    challenge: AuthorizationChallenge,
    request: SignerAuthorizationRequest,
) -> TransactionAuthorization:
    """Bind the PR-141 structural authorization to trusted PR-201 freshness."""

    checks = (
        (
            challenge.domain is AuthorizationDomain.SIGNER_TRANSACTION,
            "challenge domain does not authorize signer transaction",
        ),
        (
            request.authorization_id == challenge.challenge_id,
            "authorization ID mismatch",
        ),
        (request.attempt_id == challenge.attempt_id, "attempt ID mismatch"),
        (
            request.attempt_generation == challenge.attempt_generation,
            "attempt generation mismatch",
        ),
        (
            request.policy_bundle_hash == challenge.policy_bundle_hash,
            "PolicyBundle mismatch",
        ),
        (
            request.decoded_message.message_sha256 == challenge.operation_hash,
            "exact message hash mismatch",
        ),
        (request.nonce_digest == challenge.nonce_digest, "trusted nonce mismatch"),
    )
    for ok, message in checks:
        if not ok:
            failure = (
                ReplayFailure.BAD_NONCE
                if "nonce" in message
                else ReplayFailure.BAD_BINDING
            )
            raise ReplayProtectionError(failure, message)

    def executor(_: str) -> AuthorizationResult:
        authorization = authorize_transaction(request)
        return AuthorizationResult.from_payload(
            "pr141.transaction-authorization.v1", asdict(authorization)
        )

    execution = service.execute_once(
        challenge, request_hash=_pr141_request_hash(request), executor=executor
    )
    payload = execution.result.payload()
    payload["required_signers"] = tuple(_string_list(payload, "required_signers"))
    payload["program_ids"] = tuple(_string_list(payload, "program_ids"))
    return TransactionAuthorization(**payload)  # type: ignore[arg-type]


def _pr141_request_hash(request: SignerAuthorizationRequest) -> str:
    decoded = request.decoded_message
    return _hash_json(
        {
            "domain": "flashloan-bot/pr201/pr141-request",
            "authorization_id": request.authorization_id,
            "attempt_id": request.attempt_id,
            "attempt_generation": request.attempt_generation,
            "logical_opportunity_id": request.logical_opportunity_id,
            "decoded_message": {
                "message_sha256": decoded.message_sha256,
                "version": decoded.version,
                "payer": decoded.payer,
                "required_signers": list(decoded.required_signers),
                "program_ids": list(decoded.program_ids),
                "message_byte_count": decoded.message_byte_count,
                "required_signature_count": decoded.required_signature_count,
                "address_lookup_table_count": decoded.address_lookup_table_count,
            },
            "expected_payer": request.expected_payer,
            "expected_required_signers": list(request.expected_required_signers),
            "allowed_program_ids": sorted(request.allowed_program_ids),
            "plan_hash": request.plan_hash,
            "policy_bundle_hash": request.policy_bundle_hash,
            "exact_simulation_hash": request.exact_simulation_hash,
            "cpi_call_graph_hash": request.cpi_call_graph_hash,
            "fee_compute_budget_hash": request.fee_compute_budget_hash,
            "blockhash_alt_fork_hash": request.blockhash_alt_fork_hash,
            "nonce_digest": request.nonce_digest,
            "issued_at_ns": request.issued_at_ns,
            "expires_at_ns": request.expires_at_ns,
            "alt_evidence_hash": request.alt_evidence_hash,
        }
    )


def _operation_id(challenge: AuthorizationChallenge, request_hash: str) -> str:
    return _hash_json(
        {
            "domain": "flashloan-bot/pr201/idempotent-operation",
            "challenge_id": challenge.challenge_id,
            "authorization_domain": challenge.domain.value,
            "operation_hash": challenge.operation_hash,
            "request_hash": request_hash,
        }
    )


def _validate_nonce(nonce: bytes) -> None:
    if len(nonce) < _MIN_NONCE_BYTES or len(set(nonce)) == 1:
        raise ReplayProtectionError(
            ReplayFailure.BAD_NONCE, "nonce is short or an obvious placeholder"
        )
    for width in (2, 4, 8, 16):
        if len(nonce) % width == 0 and nonce == nonce[:width] * (len(nonce) // width):
            raise ReplayProtectionError(
                ReplayFailure.BAD_NONCE, "nonce is a repeated placeholder pattern"
            )


def _decode_nonce(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (TypeError, ValueError) as exc:
        raise ReplayProtectionError(
            ReplayFailure.BAD_NONCE, "nonce encoding is invalid"
        ) from exc


def _identifier(name: str, value: str) -> None:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a bounded structured identifier")


def _string_list(payload: Mapping[str, object], name: str) -> list[str]:
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ReplayProtectionError(
            ReplayFailure.RESULT_INVALID, "stored signer tuple field is invalid"
        )
    return value


def _json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(payload: object) -> str:
    return hashlib.sha256(_json(payload).encode()).hexdigest()
