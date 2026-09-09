"""MPR-2608 isolated signer and submission effect boundary.

This module is deliberately DEFAULT OFF.  It provides the narrow, restart-safe
control plane needed to qualify an isolated signer without loading production
secrets or performing network submission in the ordinary runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import hmac
import json
from pathlib import Path
import re
import socket
import sqlite3
import struct
import time
from typing import Callable, Protocol

MPR2608_SCHEMA = "studious-pancake.mpr2608.v1"
MPR2608_COMPILE_ENABLED = False
MAX_FRAME_BYTES = 64 * 1024
MAX_ID_LEN = 128
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR2608Error(RuntimeError):
    pass


class OutcomeState(StrEnum):
    NOT_ISSUED = "not_issued"
    ISSUED_UNKNOWN = "issued_unknown"
    ACKNOWLEDGED = "acknowledged"
    FINALIZED_FAILURE = "finalized_failure"
    FINALIZED_PENDING_ECONOMICS = "finalized_pending_economics"
    FINALIZED_SETTLED = "finalized_settled"
    QUARANTINED = "quarantined"


TERMINAL_STATES = {
    OutcomeState.FINALIZED_FAILURE,
    OutcomeState.FINALIZED_PENDING_ECONOMICS,
    OutcomeState.FINALIZED_SETTLED,
    OutcomeState.QUARANTINED,
}


@dataclass(frozen=True, slots=True)
class ApprovedIntent:
    permit_id: str
    intent_id: str
    attempt_id: str
    reservation_id: str
    release_id: str
    config_hash: str
    policy_hash: str
    genesis_hash: str
    signer_service_id: str
    signer_generation: int
    payer: str
    message_sha256: str
    simulation_sha256: str
    transport: str
    expires_at_ns: int

    def __post_init__(self) -> None:
        for value, field in (
            (self.permit_id, "permit_id"),
            (self.intent_id, "intent_id"),
            (self.attempt_id, "attempt_id"),
            (self.reservation_id, "reservation_id"),
            (self.release_id, "release_id"),
            (self.signer_service_id, "signer_service_id"),
            (self.payer, "payer"),
            (self.transport, "transport"),
        ):
            _identifier(value, field)
        for value, field in (
            (self.config_hash, "config_hash"),
            (self.policy_hash, "policy_hash"),
            (self.genesis_hash, "genesis_hash"),
            (self.message_sha256, "message_sha256"),
            (self.simulation_sha256, "simulation_sha256"),
        ):
            _sha256(value, field)
        if self.signer_generation < 1:
            raise ValueError("signer_generation must be positive")
        if self.expires_at_ns <= 0:
            raise ValueError("expires_at_ns must be positive")

    @property
    def semantic_hash(self) -> str:
        return _hash_json(
            {
                "schema": MPR2608_SCHEMA,
                "permit_id": self.permit_id,
                "intent_id": self.intent_id,
                "attempt_id": self.attempt_id,
                "reservation_id": self.reservation_id,
                "release_id": self.release_id,
                "config_hash": self.config_hash,
                "policy_hash": self.policy_hash,
                "genesis_hash": self.genesis_hash,
                "signer_service_id": self.signer_service_id,
                "signer_generation": self.signer_generation,
                "payer": self.payer,
                "message_sha256": self.message_sha256,
                "simulation_sha256": self.simulation_sha256,
                "transport": self.transport,
                "expires_at_ns": self.expires_at_ns,
            }
        )


@dataclass(frozen=True, slots=True)
class SignRequest:
    intent: ApprovedIntent
    request_id: str
    request_nonce: str
    unsigned_message: bytes

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.request_nonce, "request_nonce")
        if not self.unsigned_message:
            raise ValueError("unsigned_message must be non-empty")
        if len(self.unsigned_message) > 1232:
            raise ValueError("unsigned_message exceeds Solana packet bound")
        digest = hashlib.sha256(self.unsigned_message).hexdigest()
        if not hmac.compare_digest(digest, self.intent.message_sha256):
            raise ValueError("unsigned_message does not match approved message hash")


@dataclass(frozen=True, slots=True)
class SignReceipt:
    request_id: str
    intent_id: str
    message_sha256: str
    signed_wire_sha256: str
    signature: str
    signed_wire: bytes
    signer_service_id: str
    signer_generation: int


class ApprovedMessageValidator(Protocol):
    def __call__(self, *, unsigned_message: bytes, intent: ApprovedIntent) -> None: ...


class SigningBackend(Protocol):
    """Runs only inside the isolated signer process."""

    def sign_approved_transaction(self, unsigned_message: bytes) -> tuple[str, bytes]: ...


class MPR2608Store:
    """Canonical local cutover store for one-shot permit + durable intent semantics.

    This helper is intentionally small and transaction-oriented.  A production
    integration must map it onto the accepted lifecycle/capital owner instead of
    treating this database as a second economic ledger.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mpr2608_permits(
                    permit_id TEXT PRIMARY KEY,
                    semantic_hash TEXT NOT NULL,
                    consumed_intent_id TEXT,
                    consumed_at_ns INTEGER
                );
                CREATE TABLE IF NOT EXISTS mpr2608_intents(
                    intent_id TEXT PRIMARY KEY,
                    permit_id TEXT NOT NULL UNIQUE,
                    semantic_hash TEXT NOT NULL,
                    message_sha256 TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    state TEXT NOT NULL,
                    signed_wire_sha256 TEXT,
                    primary_signature TEXT,
                    ack_hash TEXT,
                    finality_hash TEXT,
                    capital_hold INTEGER NOT NULL CHECK(capital_hold IN (0,1)),
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    FOREIGN KEY(permit_id) REFERENCES mpr2608_permits(permit_id)
                );
                """
            )

    def seed_permit(self, permit_id: str, semantic_hash: str) -> None:
        _identifier(permit_id, "permit_id")
        _sha256(semantic_hash, "semantic_hash")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO mpr2608_permits(permit_id, semantic_hash) VALUES(?, ?)",
                (permit_id, semantic_hash),
            )
            row = conn.execute(
                "SELECT semantic_hash FROM mpr2608_permits WHERE permit_id=?", (permit_id,)
            ).fetchone()
            if row is None or row["semantic_hash"] != semantic_hash:
                raise MPR2608Error("permit semantic conflict")

    def consume_permit_and_create_intent(self, intent: ApprovedIntent, *, now_ns: int) -> None:
        if now_ns >= intent.expires_at_ns:
            raise MPR2608Error("permit expired before atomic cutover")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                permit = conn.execute(
                    "SELECT semantic_hash, consumed_intent_id FROM mpr2608_permits WHERE permit_id=?",
                    (intent.permit_id,),
                ).fetchone()
                if permit is None:
                    raise MPR2608Error("unknown permit")
                if permit["semantic_hash"] != intent.semantic_hash:
                    raise MPR2608Error("permit semantic conflict")
                if permit["consumed_intent_id"] is not None:
                    if permit["consumed_intent_id"] == intent.intent_id:
                        existing = conn.execute(
                            "SELECT semantic_hash FROM mpr2608_intents WHERE intent_id=?",
                            (intent.intent_id,),
                        ).fetchone()
                        if existing and existing["semantic_hash"] == intent.semantic_hash:
                            conn.execute("COMMIT")
                            return
                    raise MPR2608Error("permit already consumed")
                existing = conn.execute(
                    "SELECT semantic_hash FROM mpr2608_intents WHERE intent_id=?", (intent.intent_id,)
                ).fetchone()
                if existing is not None:
                    raise MPR2608Error("intent id conflict")
                conn.execute(
                    """
                    INSERT INTO mpr2608_intents(
                        intent_id, permit_id, semantic_hash, message_sha256, transport,
                        state, capital_hold, created_at_ns, updated_at_ns
                    ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        intent.intent_id,
                        intent.permit_id,
                        intent.semantic_hash,
                        intent.message_sha256,
                        intent.transport,
                        OutcomeState.NOT_ISSUED.value,
                        now_ns,
                        now_ns,
                    ),
                )
                conn.execute(
                    "UPDATE mpr2608_permits SET consumed_intent_id=?, consumed_at_ns=? WHERE permit_id=?",
                    (intent.intent_id, now_ns, intent.permit_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def mark_dispatching(
        self,
        *,
        intent_id: str,
        signed_wire_sha256: str,
        primary_signature: str,
        now_ns: int,
    ) -> None:
        _sha256(signed_wire_sha256, "signed_wire_sha256")
        _identifier(primary_signature, "primary_signature")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, signed_wire_sha256, primary_signature FROM mpr2608_intents WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise MPR2608Error("unknown intent")
            if row["state"] != OutcomeState.NOT_ISSUED.value:
                if (
                    row["state"] == OutcomeState.ISSUED_UNKNOWN.value
                    and row["signed_wire_sha256"] == signed_wire_sha256
                    and row["primary_signature"] == primary_signature
                ):
                    conn.execute("COMMIT")
                    return
                conn.execute("ROLLBACK")
                raise MPR2608Error("dispatch marker conflict")
            conn.execute(
                """
                UPDATE mpr2608_intents
                SET state=?, signed_wire_sha256=?, primary_signature=?, updated_at_ns=?
                WHERE intent_id=?
                """,
                (
                    OutcomeState.ISSUED_UNKNOWN.value,
                    signed_wire_sha256,
                    primary_signature,
                    now_ns,
                    intent_id,
                ),
            )
            conn.execute("COMMIT")

    def record_ack(self, *, intent_id: str, ack_payload: dict[str, object], now_ns: int) -> None:
        ack_hash = _hash_json(ack_payload)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, ack_hash FROM mpr2608_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise MPR2608Error("unknown intent")
            if row["state"] in {s.value for s in TERMINAL_STATES}:
                if row["ack_hash"] in (None, ack_hash):
                    conn.execute("COMMIT")
                    return
                conn.execute("ROLLBACK")
                raise MPR2608Error("conflicting late ACK")
            if row["state"] not in {
                OutcomeState.ISSUED_UNKNOWN.value,
                OutcomeState.ACKNOWLEDGED.value,
            }:
                conn.execute("ROLLBACK")
                raise MPR2608Error("ACK before dispatch marker")
            if row["ack_hash"] not in (None, ack_hash):
                conn.execute("ROLLBACK")
                raise MPR2608Error("conflicting ACK")
            conn.execute(
                "UPDATE mpr2608_intents SET state=?, ack_hash=?, updated_at_ns=? WHERE intent_id=?",
                (OutcomeState.ACKNOWLEDGED.value, ack_hash, now_ns, intent_id),
            )
            conn.execute("COMMIT")

    def record_finality(
        self,
        *,
        intent_id: str,
        finalized: bool,
        err: bool | None,
        evidence: dict[str, object],
        economics_settled: bool,
        now_ns: int,
    ) -> OutcomeState:
        if not finalized:
            raise MPR2608Error("processed/confirmed is not terminal finality")
        evidence_hash = _hash_json(evidence)
        if err is True:
            target = OutcomeState.FINALIZED_FAILURE
        elif err is False and economics_settled:
            target = OutcomeState.FINALIZED_SETTLED
        elif err is False:
            target = OutcomeState.FINALIZED_PENDING_ECONOMICS
        else:
            target = OutcomeState.QUARANTINED
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, finality_hash FROM mpr2608_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise MPR2608Error("unknown intent")
            current = OutcomeState(row["state"])
            if current in TERMINAL_STATES:
                if current is target and row["finality_hash"] == evidence_hash:
                    conn.execute("COMMIT")
                    return current
                conn.execute("ROLLBACK")
                raise MPR2608Error("terminal finality conflict")
            if current not in {OutcomeState.ISSUED_UNKNOWN, OutcomeState.ACKNOWLEDGED}:
                conn.execute("ROLLBACK")
                raise MPR2608Error("finality before dispatch marker")
            release_capital = target in {
                OutcomeState.FINALIZED_FAILURE,
                OutcomeState.FINALIZED_SETTLED,
            }
            conn.execute(
                """
                UPDATE mpr2608_intents
                SET state=?, finality_hash=?, capital_hold=?, updated_at_ns=?
                WHERE intent_id=?
                """,
                (target.value, evidence_hash, 0 if release_capital else 1, now_ns, intent_id),
            )
            conn.execute("COMMIT")
            return target

    def get_intent(self, intent_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mpr2608_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if row is None:
                raise MPR2608Error("unknown intent")
            return dict(row)


class IsolatedSignerServer:
    """Strict single-method local IPC server.

    Production deployment supplies a validator and secret-bearing backend from
    inside the signer process.  The caller receives only the signature and signed
    wire; no key material or generic sign(bytes) method exists.
    """

    def __init__(
        self,
        *,
        socket_path: str | Path,
        service_id: str,
        generation: int,
        validator: ApprovedMessageValidator,
        backend: SigningBackend,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        _identifier(service_id, "service_id")
        if generation < 1:
            raise ValueError("generation must be positive")
        self.socket_path = str(socket_path)
        self.service_id = service_id
        self.generation = generation
        self.validator = validator
        self.backend = backend
        self.now_ns = now_ns

    def handle_payload(self, raw: bytes) -> bytes:
        obj = _strict_json_loads(raw)
        if set(obj) != {"method", "request_id", "request_nonce", "intent", "unsigned_message_hex"}:
            raise MPR2608Error("unknown or missing IPC fields")
        if obj["method"] != "sign_approved_solana_transaction":
            raise MPR2608Error("unsupported IPC method")
        intent = ApprovedIntent(**obj["intent"])
        if intent.signer_service_id != self.service_id or intent.signer_generation != self.generation:
            raise MPR2608Error("wrong signer service identity or generation")
        if self.now_ns() >= intent.expires_at_ns:
            raise MPR2608Error("authorization expired")
        try:
            unsigned_message = bytes.fromhex(obj["unsigned_message_hex"])
        except (TypeError, ValueError) as exc:
            raise MPR2608Error("invalid unsigned message encoding") from exc
        request = SignRequest(
            intent=intent,
            request_id=obj["request_id"],
            request_nonce=obj["request_nonce"],
            unsigned_message=unsigned_message,
        )
        self.validator(unsigned_message=request.unsigned_message, intent=intent)
        signature, signed_wire = self.backend.sign_approved_transaction(request.unsigned_message)
        _identifier(signature, "signature")
        if not signed_wire:
            raise MPR2608Error("signer backend returned empty signed wire")
        receipt = {
            "schema": MPR2608_SCHEMA,
            "request_id": request.request_id,
            "intent_id": intent.intent_id,
            "message_sha256": intent.message_sha256,
            "signed_wire_sha256": hashlib.sha256(signed_wire).hexdigest(),
            "signature": signature,
            "signed_wire_hex": signed_wire.hex(),
            "signer_service_id": self.service_id,
            "signer_generation": self.generation,
        }
        return _canonical_json(receipt)

    def serve_once(self, *, timeout_seconds: float = 5.0) -> None:
        path = Path(self.socket_path)
        if path.exists():
            path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(self.socket_path)
            path.chmod(0o600)
            server.listen(1)
            server.settimeout(timeout_seconds)
            conn, _ = server.accept()
            with conn:
                conn.settimeout(timeout_seconds)
                raw = _recv_frame(conn)
                response = self.handle_payload(raw)
                _send_frame(conn, response)
        finally:
            server.close()
            if path.exists():
                path.unlink()


def build_sign_request_frame(request: SignRequest) -> bytes:
    body = {
        "method": "sign_approved_solana_transaction",
        "request_id": request.request_id,
        "request_nonce": request.request_nonce,
        "intent": {
            "permit_id": request.intent.permit_id,
            "intent_id": request.intent.intent_id,
            "attempt_id": request.intent.attempt_id,
            "reservation_id": request.intent.reservation_id,
            "release_id": request.intent.release_id,
            "config_hash": request.intent.config_hash,
            "policy_hash": request.intent.policy_hash,
            "genesis_hash": request.intent.genesis_hash,
            "signer_service_id": request.intent.signer_service_id,
            "signer_generation": request.intent.signer_generation,
            "payer": request.intent.payer,
            "message_sha256": request.intent.message_sha256,
            "simulation_sha256": request.intent.simulation_sha256,
            "transport": request.intent.transport,
            "expires_at_ns": request.intent.expires_at_ns,
        },
        "unsigned_message_hex": request.unsigned_message.hex(),
    }
    return _canonical_json(body)


def parse_sign_receipt(raw: bytes) -> SignReceipt:
    obj = _strict_json_loads(raw)
    expected = {
        "schema",
        "request_id",
        "intent_id",
        "message_sha256",
        "signed_wire_sha256",
        "signature",
        "signed_wire_hex",
        "signer_service_id",
        "signer_generation",
    }
    if set(obj) != expected or obj["schema"] != MPR2608_SCHEMA:
        raise MPR2608Error("invalid sign receipt schema")
    try:
        signed_wire = bytes.fromhex(obj["signed_wire_hex"])
    except (TypeError, ValueError) as exc:
        raise MPR2608Error("invalid signed wire encoding") from exc
    digest = hashlib.sha256(signed_wire).hexdigest()
    if not hmac.compare_digest(digest, obj["signed_wire_sha256"]):
        raise MPR2608Error("signed wire digest mismatch")
    return SignReceipt(
        request_id=obj["request_id"],
        intent_id=obj["intent_id"],
        message_sha256=obj["message_sha256"],
        signed_wire_sha256=obj["signed_wire_sha256"],
        signature=obj["signature"],
        signed_wire=signed_wire,
        signer_service_id=obj["signer_service_id"],
        signer_generation=obj["signer_generation"],
    )


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise MPR2608Error("unexpected IPC EOF")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(sock: socket.socket) -> bytes:
    header = _recv_exact(sock, 4)
    (length,) = struct.unpack("!I", header)
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise MPR2608Error("invalid IPC frame size")
    return _recv_exact(sock, length)


def _send_frame(sock: socket.socket, payload: bytes) -> None:
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise MPR2608Error("invalid IPC response size")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _strict_json_loads(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise MPR2608Error("invalid JSON frame size")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in pairs:
            if key in out:
                raise MPR2608Error("duplicate JSON key")
            out[key] = value
        return out

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MPR2608Error("malformed IPC JSON") from exc
    if not isinstance(value, dict):
        raise MPR2608Error("IPC payload must be an object")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) > MAX_ID_LEN or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")


def _sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
