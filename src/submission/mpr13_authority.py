"""MPR-13 cryptographic signer and rooted submission authority.

This additive boundary is live-disabled.  It derives signer policy identity from
canonical Solana message bytes, stores one-time permits and immutable intents in
SQLite, preserves complete bundle identity, and accepts only authenticated,
identity-bound status observations.  Transport ACK/inflight evidence is never
settlement proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Protocol
from uuid import UUID, uuid4

MPR13_SCHEMA_VERSION = "mpr13.submission-authority.v1"
MPR13_DECODER_VERSION = "solders.versioned-message.v1"
MPR13_COMPILE_TIME_LIVE_ENABLED = False
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,90}$")


class MPR13AuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IntentState(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    OBSERVED = "observed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    RECONCILED = "reconciled"
    AMBIGUOUS = "ambiguous"
    REVOKED = "revoked"


class ObservationKind(StrEnum):
    RPC_SIGNATURE = "rpc_signature"
    JITO_INFLIGHT = "jito_inflight"
    JITO_BUNDLE = "jito_bundle"
    ROOTED_TRANSACTION = "rooted_transaction"
    RECONCILIATION = "reconciliation"


class ObservationFinality(StrEnum):
    ADVISORY = "advisory"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    RECONCILED = "reconciled"


class TransportStage(StrEnum):
    CREATED = "created"
    DNS_RESOLVED = "dns_resolved"
    CONNECTED = "connected"
    TLS_VERIFIED = "tls_verified"
    HEADERS_SENT = "headers_sent"
    BODY_COMPLETE = "body_complete"
    RESPONSE_RECEIVED = "response_received"


_STAGE_ORDER = {stage: index for index, stage in enumerate(TransportStage)}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_json(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _require_hash(value: str, label: str) -> None:
    if not _HASH_RE.fullmatch(value):
        raise ValueError(f"{label} must be lowercase sha256 hex")


def _require_base58(value: str, label: str) -> None:
    if not _BASE58_RE.fullmatch(value):
        raise ValueError(f"{label} must be canonical base58 text")


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class AddressLookupSnapshot:
    table_pubkey: str
    addresses: tuple[str, ...]
    last_extended_slot: int
    deactivation_slot: int | None
    content_hash: str

    @classmethod
    def build(
        cls,
        *,
        table_pubkey: str,
        addresses: Sequence[str],
        last_extended_slot: int,
        deactivation_slot: int | None,
    ) -> "AddressLookupSnapshot":
        payload = {
            "table_pubkey": table_pubkey,
            "addresses": list(addresses),
            "last_extended_slot": last_extended_slot,
            "deactivation_slot": deactivation_slot,
        }
        return cls(
            table_pubkey,
            tuple(addresses),
            last_extended_slot,
            deactivation_slot,
            _hash_json(payload),
        )


@dataclass(frozen=True, slots=True)
class DecodedMessageIdentity:
    schema_version: str
    decoder_version: str
    message_sha256: str
    payer: str
    required_signers: tuple[str, ...]
    writable_accounts: tuple[str, ...]
    readonly_accounts: tuple[str, ...]
    program_ids: tuple[str, ...]
    recent_blockhash: str
    instruction_data_hashes: tuple[str, ...]
    lookup_snapshot_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != MPR13_SCHEMA_VERSION:
            raise ValueError("unsupported identity schema")
        _require_hash(self.message_sha256, "message_sha256")
        for value in (
            self.payer,
            self.recent_blockhash,
            *self.required_signers,
            *self.writable_accounts,
            *self.readonly_accounts,
            *self.program_ids,
        ):
            _require_base58(value, "message identity value")
        for value in (*self.instruction_data_hashes, *self.lookup_snapshot_hashes):
            _require_hash(value, "identity evidence hash")
        if not self.required_signers or self.required_signers[0] != self.payer:
            raise ValueError("payer must be first required signer")

    @property
    def identity_hash(self) -> str:
        return _hash_json(asdict(self))


class MessageDecoder(Protocol):
    decoder_version: str

    def decode(
        self,
        message_bytes: bytes,
        lookup_snapshots: Sequence[AddressLookupSnapshot] = (),
    ) -> DecodedMessageIdentity: ...


class SoldersVersionedMessageDecoder:
    decoder_version = MPR13_DECODER_VERSION

    def decode(
        self,
        message_bytes: bytes,
        lookup_snapshots: Sequence[AddressLookupSnapshot] = (),
    ) -> DecodedMessageIdentity:
        if not message_bytes:
            raise MPR13AuthorityError("MESSAGE_EMPTY", "message bytes are empty")
        try:
            from solders.message import from_bytes_versioned

            message = from_bytes_versioned(bytes(message_bytes))
        except Exception as exc:
            raise MPR13AuthorityError(
                "MESSAGE_DECODE_FAILED", "canonical VersionedMessage decode failed"
            ) from exc
        static = tuple(str(item) for item in message.account_keys)
        header = message.header
        required = int(header.num_required_signatures)
        ro_signed = int(header.num_readonly_signed_accounts)
        ro_unsigned = int(header.num_readonly_unsigned_accounts)
        if required <= 0 or required > len(static):
            raise MPR13AuthorityError("MESSAGE_INVALID", "invalid signer count")
        snapshots = {item.table_pubkey: item for item in lookup_snapshots}
        loaded_writable: list[str] = []
        loaded_readonly: list[str] = []
        used_snapshots: list[str] = []
        for lookup in tuple(getattr(message, "address_table_lookups", ())):
            snapshot = snapshots.get(str(lookup.account_key))
            if snapshot is None:
                raise MPR13AuthorityError(
                    "LOOKUP_SNAPSHOT_MISSING", "lookup table snapshot is required"
                )
            try:
                loaded_writable.extend(
                    snapshot.addresses[int(i)] for i in lookup.writable_indexes
                )
                loaded_readonly.extend(
                    snapshot.addresses[int(i)] for i in lookup.readonly_indexes
                )
            except (IndexError, TypeError, ValueError) as exc:
                raise MPR13AuthorityError(
                    "LOOKUP_INDEX_INVALID", "lookup index is out of bounds"
                ) from exc
            used_snapshots.append(snapshot.content_hash)
        all_keys = static + tuple(loaded_writable) + tuple(loaded_readonly)
        signed_write_end = required - ro_signed
        unsigned_write_end = len(static) - ro_unsigned
        writable = (
            static[:signed_write_end]
            + static[required:unsigned_write_end]
            + tuple(loaded_writable)
        )
        readonly = (
            static[signed_write_end:required]
            + static[unsigned_write_end:]
            + tuple(loaded_readonly)
        )
        programs: list[str] = []
        data_hashes: list[str] = []
        for instruction in message.instructions:
            program_index = int(instruction.program_id_index)
            if program_index >= len(all_keys):
                raise MPR13AuthorityError("MESSAGE_INVALID", "program index invalid")
            programs.append(all_keys[program_index])
            data_hashes.append(sha256(bytes(instruction.data)).hexdigest())
            if any(int(index) >= len(all_keys) for index in instruction.accounts):
                raise MPR13AuthorityError("MESSAGE_INVALID", "account index invalid")
        return DecodedMessageIdentity(
            MPR13_SCHEMA_VERSION,
            self.decoder_version,
            sha256(message_bytes).hexdigest(),
            static[0],
            static[:required],
            _ordered_unique(writable),
            _ordered_unique(readonly),
            _ordered_unique(programs),
            str(message.recent_blockhash),
            tuple(data_hashes),
            tuple(used_snapshots),
        )


@dataclass(frozen=True, slots=True)
class SignerReviewArtifact:
    review_id: UUID
    identity_hash: str
    message_sha256: str
    decoder_version: str
    cluster_genesis_hash: str
    policy_generation: int
    min_context_slot: int
    last_valid_block_height: int
    issued_at_ns: int
    expires_at_ns: int
    review_hash: str

    @classmethod
    def build(
        cls,
        *,
        identity: DecodedMessageIdentity,
        cluster_genesis_hash: str,
        policy_generation: int,
        min_context_slot: int,
        last_valid_block_height: int,
        issued_at_ns: int,
        expires_at_ns: int,
    ) -> "SignerReviewArtifact":
        review_id = uuid4()
        payload = {
            "review_id": str(review_id),
            "identity_hash": identity.identity_hash,
            "message_sha256": identity.message_sha256,
            "decoder_version": identity.decoder_version,
            "cluster_genesis_hash": cluster_genesis_hash,
            "policy_generation": policy_generation,
            "min_context_slot": min_context_slot,
            "last_valid_block_height": last_valid_block_height,
            "issued_at_ns": issued_at_ns,
            "expires_at_ns": expires_at_ns,
        }
        return cls(
            review_id=review_id,
            identity_hash=identity.identity_hash,
            message_sha256=identity.message_sha256,
            decoder_version=identity.decoder_version,
            cluster_genesis_hash=cluster_genesis_hash,
            policy_generation=policy_generation,
            min_context_slot=min_context_slot,
            last_valid_block_height=last_valid_block_height,
            issued_at_ns=issued_at_ns,
            expires_at_ns=expires_at_ns,
            review_hash=_hash_json(payload),
        )


@dataclass(frozen=True, slots=True)
class MPR13SignerPolicy:
    allowed_program_ids: frozenset[str]
    allowed_payers: frozenset[str]
    allowed_required_signers: frozenset[str]
    max_message_bytes: int = 1232
    max_permit_ttl_ns: int = 30_000_000_000
    block_height_safety_margin: int = 2

    @property
    def fingerprint(self) -> str:
        return _hash_json(
            {
                "programs": sorted(self.allowed_program_ids),
                "payers": sorted(self.allowed_payers),
                "signers": sorted(self.allowed_required_signers),
                "max_message_bytes": self.max_message_bytes,
                "max_permit_ttl_ns": self.max_permit_ttl_ns,
                "block_height_safety_margin": self.block_height_safety_margin,
            }
        )

    def evaluate(
        self,
        *,
        message_bytes: bytes,
        review: SignerReviewArtifact,
        decoder: MessageDecoder,
        lookup_snapshots: Sequence[AddressLookupSnapshot],
        now_ns: int,
    ) -> DecodedMessageIdentity:
        if len(message_bytes) > self.max_message_bytes:
            raise MPR13AuthorityError("MESSAGE_TOO_LARGE", "message exceeds limit")
        if not review.issued_at_ns <= now_ns < review.expires_at_ns:
            raise MPR13AuthorityError("REVIEW_EXPIRED", "review is not current")
        identity = decoder.decode(message_bytes, lookup_snapshots)
        if not hmac.compare_digest(identity.identity_hash, review.identity_hash):
            raise MPR13AuthorityError(
                "IDENTITY_MISMATCH", "decoded message differs from review artifact"
            )
        if identity.decoder_version != review.decoder_version:
            raise MPR13AuthorityError("DECODER_MISMATCH", "decoder version changed")
        if identity.payer not in self.allowed_payers:
            raise MPR13AuthorityError("PAYER_DENIED", "payer is not allowlisted")
        if set(identity.program_ids) - self.allowed_program_ids:
            raise MPR13AuthorityError("PROGRAM_DENIED", "program is not allowlisted")
        if set(identity.required_signers) - self.allowed_required_signers:
            raise MPR13AuthorityError("SIGNER_DENIED", "signer is not allowlisted")
        return identity


@dataclass(frozen=True, slots=True)
class SignedWireIdentity:
    payload_digest: str
    message_hashes: tuple[str, ...]
    transaction_digests: tuple[str, ...]
    signatures: tuple[str, ...]

    def __post_init__(self) -> None:
        count = len(self.message_hashes)
        if (
            not 1 <= count <= 5
            or count != len(self.transaction_digests)
            or count != len(self.signatures)
        ):
            raise ValueError(
                "wire identity must bind one to five complete transactions"
            )
        for value in (
            self.payload_digest,
            *self.message_hashes,
            *self.transaction_digests,
        ):
            _require_hash(value, "wire hash")
        for value in self.signatures:
            _require_base58(value, "signature")
        if len(set(self.signatures)) != count:
            raise ValueError("signatures must be unique")


@dataclass(frozen=True, slots=True)
class DurablePermit:
    permit_id: UUID
    attempt_id: str
    transport: str
    identity_hash: str
    message_hash: str
    policy_fingerprint: str
    policy_generation: int
    revocation_generation: int
    issued_at_ns: int
    expires_at_ns: int
    last_valid_block_height: int
    min_context_slot: int


@dataclass(frozen=True, slots=True)
class DurableIntent:
    intent_id: UUID
    permit_id: UUID
    attempt_id: str
    transport: str
    state: IntentState
    message_hash: str
    identity_hash: str
    wire: SignedWireIdentity
    bundle_id: str | None
    created_at_ns: int
    updated_at_ns: int
    last_valid_block_height: int


@dataclass(frozen=True, slots=True)
class TransportWriteEvidence:
    stage: TransportStage
    request_hash: str
    endpoint_identity_hash: str
    observed_at_ns: int

    @property
    def bytes_may_have_left_process(self) -> bool:
        return _STAGE_ORDER[self.stage] >= _STAGE_ORDER[TransportStage.BODY_COMPLETE]


@dataclass(frozen=True, slots=True)
class ProviderReceiptEnvelope:
    provider: str
    request_hash: str
    response_hash: str
    signatures: tuple[str, ...]
    bundle_id: str | None
    received_at_ns: int


@dataclass(frozen=True, slots=True)
class StatusObservationEnvelope:
    observation_id: UUID
    authority_id: str
    intent_id: UUID
    kind: ObservationKind
    finality: ObservationFinality
    provider: str
    message_hash: str
    signatures: tuple[str, ...]
    bundle_id: str | None
    cluster_genesis_hash: str
    request_hash: str
    response_hash: str
    slot: int | None
    root_slot: int | None
    collected_at_ns: int
    provider_status: str | None
    error_code: str | None
    mac: str

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("mac")
        value["observation_id"] = str(self.observation_id)
        value["intent_id"] = str(self.intent_id)
        value["kind"] = self.kind.value
        value["finality"] = self.finality.value
        value["signatures"] = list(self.signatures)
        return value


class StatusAuthority:
    def __init__(self, authority_id: str, key: bytes) -> None:
        if not authority_id or len(key) < 32:
            raise ValueError("status authority id and 32-byte key are required")
        self.authority_id = authority_id
        self._key = bytes(key)

    def issue(
        self,
        *,
        intent_id: UUID,
        kind: ObservationKind,
        finality: ObservationFinality,
        provider: str,
        message_hash: str,
        signatures: tuple[str, ...],
        bundle_id: str | None,
        cluster_genesis_hash: str,
        request_hash: str,
        response_hash: str,
        slot: int | None,
        root_slot: int | None,
        collected_at_ns: int,
        provider_status: str | None,
        error_code: str | None = None,
    ) -> StatusObservationEnvelope:
        envelope = StatusObservationEnvelope(
            observation_id=uuid4(),
            authority_id=self.authority_id,
            intent_id=intent_id,
            kind=kind,
            finality=finality,
            provider=provider,
            message_hash=message_hash,
            signatures=signatures,
            bundle_id=bundle_id,
            cluster_genesis_hash=cluster_genesis_hash,
            request_hash=request_hash,
            response_hash=response_hash,
            slot=slot,
            root_slot=root_slot,
            collected_at_ns=collected_at_ns,
            provider_status=provider_status,
            error_code=error_code,
            mac="",
        )
        mac = hmac.new(
            self._key, _canonical_json(envelope.payload()).encode(), sha256
        ).hexdigest()
        return replace(envelope, mac=mac)

    def verify(self, envelope: StatusObservationEnvelope) -> bool:
        if envelope.authority_id != self.authority_id:
            return False
        expected = hmac.new(
            self._key, _canonical_json(envelope.payload()).encode(), sha256
        ).hexdigest()
        return hmac.compare_digest(expected, envelope.mac)


@dataclass(frozen=True, slots=True)
class AbsenceProof:
    intent_id: UUID
    current_rooted_block_height: int
    archive_complete: bool
    independent_authority_ids: tuple[str, ...]
    all_absent: bool
    late_landing_freeze_until_ns: int
    collected_at_ns: int


class MPR13SubmissionAuthority:
    """SQLite-backed one-writer permit, intent and rooted status authority."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        signer_policy: MPR13SignerPolicy,
        cluster_genesis_hash: str,
        policy_generation: int,
        revocation_generation: int,
        decoder: MessageDecoder | None = None,
        clock_ns=time.time_ns,
    ) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self.signer_policy = signer_policy
        self.cluster_genesis_hash = cluster_genesis_hash
        self.policy_generation = policy_generation
        self.revocation_generation = revocation_generation
        self.decoder = decoder or SoldersVersionedMessageDecoder()
        self.clock_ns = clock_ns
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        os.chmod(self.path, 0o600)

    def _create_schema(self) -> None:
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS permits(
              permit_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
              transport TEXT NOT NULL, identity_hash TEXT NOT NULL,
              message_hash TEXT NOT NULL, policy_fingerprint TEXT NOT NULL,
              policy_generation INTEGER NOT NULL,
              revocation_generation INTEGER NOT NULL,
              issued_at_ns INTEGER NOT NULL, expires_at_ns INTEGER NOT NULL,
              last_valid_block_height INTEGER NOT NULL,
              min_context_slot INTEGER NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('issued','consumed','revoked'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_permit
              ON permits(attempt_id, identity_hash) WHERE state='issued';
            CREATE TABLE IF NOT EXISTS intents(
              intent_id TEXT PRIMARY KEY, permit_id TEXT NOT NULL UNIQUE,
              attempt_id TEXT NOT NULL UNIQUE, transport TEXT NOT NULL,
              state TEXT NOT NULL, message_hash TEXT NOT NULL,
              identity_hash TEXT NOT NULL, wire_json TEXT NOT NULL,
              bundle_id TEXT, request_hash TEXT,
              created_at_ns INTEGER NOT NULL, updated_at_ns INTEGER NOT NULL,
              last_valid_block_height INTEGER NOT NULL,
              FOREIGN KEY(permit_id) REFERENCES permits(permit_id)
            );
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL,
              kind TEXT NOT NULL, payload_json TEXT NOT NULL,
              previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE,
              created_at_ns INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations(
              observation_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
              envelope_json TEXT NOT NULL, envelope_hash TEXT NOT NULL UNIQUE
            );
            """)

    def issue_permit(
        self,
        *,
        attempt_id: str,
        transport: str,
        message_bytes: bytes,
        review: SignerReviewArtifact,
        requested_expires_at_ns: int,
        lookup_snapshots: Sequence[AddressLookupSnapshot] = (),
        now_ns: int | None = None,
    ) -> DurablePermit:
        now = int(self.clock_ns() if now_ns is None else now_ns)
        if (
            review.cluster_genesis_hash != self.cluster_genesis_hash
            or review.policy_generation != self.policy_generation
        ):
            raise MPR13AuthorityError(
                "REVIEW_SCOPE_MISMATCH", "review scope differs from authority"
            )
        if (
            requested_expires_at_ns <= now
            or requested_expires_at_ns - now > self.signer_policy.max_permit_ttl_ns
        ):
            raise MPR13AuthorityError("PERMIT_TTL_EXCEEDED", "permit TTL is invalid")
        identity = self.signer_policy.evaluate(
            message_bytes=message_bytes,
            review=review,
            decoder=self.decoder,
            lookup_snapshots=lookup_snapshots,
            now_ns=now,
        )
        permit = DurablePermit(
            uuid4(),
            attempt_id,
            transport,
            identity.identity_hash,
            identity.message_sha256,
            self.signer_policy.fingerprint,
            self.policy_generation,
            self.revocation_generation,
            now,
            requested_expires_at_ns,
            review.last_valid_block_height,
            review.min_context_slot,
        )
        try:
            self._connection.execute(
                "INSERT INTO permits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*_permit_values(permit), "issued"),
            )
        except sqlite3.IntegrityError as exc:
            raise MPR13AuthorityError(
                "PERMIT_CONFLICT", "active permit already exists"
            ) from exc
        return permit

    def commit_intent(
        self,
        *,
        permit_id: UUID,
        wire: SignedWireIdentity,
        current_rooted_block_height: int,
        now_ns: int | None = None,
    ) -> DurableIntent:
        now = int(self.clock_ns() if now_ns is None else now_ns)
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM permits WHERE permit_id=? AND state='issued'",
                (str(permit_id),),
            ).fetchone()
            if row is None:
                raise MPR13AuthorityError(
                    "PERMIT_NOT_ISSUED", "permit is absent or consumed"
                )
            permit = _permit_from_row(row)
            if now >= permit.expires_at_ns:
                raise MPR13AuthorityError("PERMIT_EXPIRED", "permit expired")
            if (
                permit.policy_generation != self.policy_generation
                or permit.revocation_generation != self.revocation_generation
            ):
                raise MPR13AuthorityError(
                    "PERMIT_REVOKED", "permit generation is stale"
                )
            if (
                current_rooted_block_height
                + self.signer_policy.block_height_safety_margin
                >= permit.last_valid_block_height
            ):
                raise MPR13AuthorityError(
                    "BLOCKHASH_EXPIRED", "rooted block height reached safety margin"
                )
            if wire.message_hashes[0] != permit.message_hash:
                raise MPR13AuthorityError(
                    "WIRE_IDENTITY_MISMATCH", "wire message differs from permit"
                )
            if permit.transport != "jito_bundle" and len(wire.signatures) != 1:
                raise MPR13AuthorityError(
                    "WIRE_CARDINALITY_INVALID",
                    "non-bundle intent must contain one transaction",
                )
            intent = DurableIntent(
                uuid4(),
                permit.permit_id,
                permit.attempt_id,
                permit.transport,
                IntentState.PREPARED,
                permit.message_hash,
                permit.identity_hash,
                wire,
                None,
                now,
                now,
                permit.last_valid_block_height,
            )
            self._connection.execute(
                "UPDATE permits SET state='consumed' WHERE permit_id=?",
                (str(permit_id),),
            )
            self._connection.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(intent.intent_id),
                    str(intent.permit_id),
                    intent.attempt_id,
                    intent.transport,
                    intent.state.value,
                    intent.message_hash,
                    intent.identity_hash,
                    _canonical_json(asdict(wire)),
                    None,
                    None,
                    now,
                    now,
                    intent.last_valid_block_height,
                ),
            )
            self._event(
                intent.intent_id, "INTENT_PREPARED", {"wire": asdict(wire)}, now
            )
        return intent

    def get_intent(self, intent_id: UUID) -> DurableIntent:
        row = self._connection.execute(
            "SELECT * FROM intents WHERE intent_id=?", (str(intent_id),)
        ).fetchone()
        if row is None:
            raise MPR13AuthorityError("INTENT_NOT_FOUND", "intent does not exist")
        wire_data = json.loads(row["wire_json"])
        if not isinstance(wire_data, dict):
            raise MPR13AuthorityError(
                "WIRE_IDENTITY_INVALID", "stored wire identity is not an object"
            )
        payload_digest = wire_data.get("payload_digest")
        if not isinstance(payload_digest, str):
            raise MPR13AuthorityError(
                "WIRE_IDENTITY_INVALID", "stored payload digest is invalid"
            )
        wire = SignedWireIdentity(
            payload_digest=payload_digest,
            message_hashes=_string_tuple(
                wire_data.get("message_hashes"), "message_hashes"
            ),
            transaction_digests=_string_tuple(
                wire_data.get("transaction_digests"), "transaction_digests"
            ),
            signatures=_string_tuple(wire_data.get("signatures"), "signatures"),
        )
        return DurableIntent(
            UUID(row["intent_id"]),
            UUID(row["permit_id"]),
            row["attempt_id"],
            row["transport"],
            IntentState(row["state"]),
            row["message_hash"],
            row["identity_hash"],
            wire,
            row["bundle_id"],
            row["created_at_ns"],
            row["updated_at_ns"],
            row["last_valid_block_height"],
        )

    def record_dispatch(
        self, intent_id: UUID, evidence: TransportWriteEvidence
    ) -> DurableIntent:
        intent = self.get_intent(intent_id)
        if intent.state not in {IntentState.PREPARED, IntentState.DISPATCHED}:
            raise MPR13AuthorityError("INTENT_STATE_INVALID", "intent cannot dispatch")
        self._connection.execute(
            "UPDATE intents SET state=?, request_hash=?, updated_at_ns=? "
            "WHERE intent_id=?",
            (
                IntentState.DISPATCHED.value,
                evidence.request_hash,
                evidence.observed_at_ns,
                str(intent_id),
            ),
        )
        self._event(
            intent_id,
            "TRANSPORT_STAGE",
            _enum_dict(asdict(evidence)),
            evidence.observed_at_ns,
        )
        return self.get_intent(intent_id)

    def record_ack(
        self, intent_id: UUID, receipt: ProviderReceiptEnvelope
    ) -> DurableIntent:
        intent = self.get_intent(intent_id)
        row = self._connection.execute(
            "SELECT request_hash FROM intents WHERE intent_id=?", (str(intent_id),)
        ).fetchone()
        if intent.state is not IntentState.DISPATCHED or not row["request_hash"]:
            raise MPR13AuthorityError(
                "ACK_WITHOUT_DISPATCH", "ACK requires dispatch evidence"
            )
        if (
            row["request_hash"] != receipt.request_hash
            or intent.wire.signatures != receipt.signatures
        ):
            raise MPR13AuthorityError(
                "ACK_IDENTITY_MISMATCH", "receipt identity differs from intent"
            )
        self._connection.execute(
            "UPDATE intents SET state=?, bundle_id=?, updated_at_ns=? "
            "WHERE intent_id=?",
            (
                IntentState.ACKNOWLEDGED.value,
                receipt.bundle_id,
                receipt.received_at_ns,
                str(intent_id),
            ),
        )
        self._event(
            intent_id,
            "PROVIDER_ACK",
            _enum_dict(asdict(receipt)),
            receipt.received_at_ns,
        )
        return self.get_intent(intent_id)

    def classify_transport_failure(
        self,
        intent_id: UUID,
        evidence: TransportWriteEvidence,
        *,
        reason: str,
    ) -> DurableIntent | None:
        if not evidence.bytes_may_have_left_process:
            self._event(
                intent_id,
                "PRE_SEND_FAILURE",
                {"reason": reason, **_enum_dict(asdict(evidence))},
                evidence.observed_at_ns,
            )
            return None
        self._connection.execute(
            "UPDATE intents SET state=?, request_hash=?, updated_at_ns=? "
            "WHERE intent_id=?",
            (
                IntentState.AMBIGUOUS.value,
                evidence.request_hash,
                evidence.observed_at_ns,
                str(intent_id),
            ),
        )
        self._event(
            intent_id,
            "AMBIGUOUS_TRANSPORT",
            {"reason": reason, **_enum_dict(asdict(evidence))},
            evidence.observed_at_ns,
        )
        return self.get_intent(intent_id)

    def record_observation(
        self,
        envelope: StatusObservationEnvelope,
        *,
        verifier: StatusAuthority,
    ) -> DurableIntent:
        if not verifier.verify(envelope):
            raise MPR13AuthorityError(
                "OBSERVATION_UNAUTHENTICATED", "status observation MAC is invalid"
            )
        intent = self.get_intent(envelope.intent_id)
        if (
            envelope.message_hash != intent.message_hash
            or envelope.signatures != intent.wire.signatures
            or envelope.bundle_id != intent.bundle_id
            or envelope.cluster_genesis_hash != self.cluster_genesis_hash
        ):
            raise MPR13AuthorityError(
                "OBSERVATION_IDENTITY_MISMATCH", "observation differs from intent"
            )
        if envelope.kind is ObservationKind.JITO_INFLIGHT:
            target = IntentState.OBSERVED
        elif envelope.finality is ObservationFinality.RECONCILED:
            if intent.state is not IntentState.FINALIZED:
                raise MPR13AuthorityError(
                    "RECONCILE_BEFORE_FINALITY",
                    "reconciliation requires finalized state",
                )
            target = IntentState.RECONCILED
        elif envelope.finality is ObservationFinality.FINALIZED:
            if (
                envelope.slot is None
                or envelope.root_slot is None
                or envelope.root_slot < envelope.slot
            ):
                raise MPR13AuthorityError(
                    "FINALITY_NOT_ROOTED", "finalized evidence is not rooted"
                )
            target = IntentState.FINALIZED
        elif envelope.finality is ObservationFinality.CONFIRMED:
            target = IntentState.CONFIRMED
        else:
            target = IntentState.OBSERVED
        envelope_json = _canonical_json(_tuple_dict(envelope.payload()))
        try:
            self._connection.execute(
                "INSERT INTO observations VALUES(?,?,?,?)",
                (
                    str(envelope.observation_id),
                    str(envelope.intent_id),
                    envelope_json,
                    sha256(envelope_json.encode()).hexdigest(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise MPR13AuthorityError(
                "OBSERVATION_REPLAY", "observation already recorded"
            ) from exc
        self._connection.execute(
            "UPDATE intents SET state=?, updated_at_ns=? WHERE intent_id=?",
            (target.value, envelope.collected_at_ns, str(envelope.intent_id)),
        )
        self._event(
            envelope.intent_id,
            f"STATUS_{target.value.upper()}",
            envelope.payload(),
            envelope.collected_at_ns,
        )
        return self.get_intent(envelope.intent_id)

    def authorize_rebuild(
        self, proof: AbsenceProof, *, now_ns: int | None = None
    ) -> str:
        now = int(self.clock_ns() if now_ns is None else now_ns)
        intent = self.get_intent(proof.intent_id)
        valid = (
            intent.state is IntentState.AMBIGUOUS
            and proof.archive_complete
            and proof.all_absent
            and len(set(proof.independent_authority_ids)) >= 2
            and proof.current_rooted_block_height > intent.last_valid_block_height
            and proof.collected_at_ns >= proof.late_landing_freeze_until_ns
            and now >= proof.late_landing_freeze_until_ns
        )
        if not valid:
            raise MPR13AuthorityError(
                "RESUBMISSION_FORBIDDEN", "absence lineage is incomplete"
            )
        proof_payload = _enum_dict(asdict(proof))
        intent_payload = _enum_dict(asdict(intent))
        lineage = _hash_json(
            {**proof_payload, "intent_hash": _hash_json(intent_payload)}
        )
        self._event(proof.intent_id, "REBUILD_AUTHORIZED", {"lineage": lineage}, now)
        return lineage

    def event_chain(self, intent_id: UUID) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT seq,kind,payload_json,previous_hash,event_hash,created_at_ns "
            "FROM events WHERE intent_id=? ORDER BY seq",
            (str(intent_id),),
        ).fetchall()
        return [
            {
                "seq": row["seq"],
                "kind": row["kind"],
                "payload": json.loads(row["payload_json"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
                "created_at_ns": row["created_at_ns"],
            }
            for row in rows
        ]

    def _event(
        self,
        intent_id: UUID,
        kind: str,
        payload: Mapping[str, object],
        created_at_ns: int,
    ) -> None:
        previous = self._connection.execute(
            "SELECT event_hash FROM events WHERE intent_id=? "
            "ORDER BY seq DESC LIMIT 1",
            (str(intent_id),),
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "0" * 64
        payload_json = _canonical_json(_tuple_dict(dict(payload)))
        event_hash = _hash_json(
            {
                "intent_id": str(intent_id),
                "kind": kind,
                "payload": json.loads(payload_json),
                "previous_hash": previous_hash,
                "created_at_ns": created_at_ns,
            }
        )
        self._connection.execute(
            "INSERT INTO events(intent_id,kind,payload_json,previous_hash,"
            "event_hash,created_at_ns) VALUES(?,?,?,?,?,?)",
            (
                str(intent_id),
                kind,
                payload_json,
                previous_hash,
                event_hash,
                created_at_ns,
            ),
        )

    class _Transaction:
        def __init__(self, owner: "MPR13SubmissionAuthority") -> None:
            self.owner = owner

        def __enter__(self) -> None:
            self.owner._lock.acquire()
            self.owner._connection.execute("BEGIN IMMEDIATE")

        def __exit__(self, exc_type, exc, tb) -> None:
            self.owner._connection.execute("ROLLBACK" if exc_type else "COMMIT")
            self.owner._lock.release()

    def _transaction(self) -> "MPR13SubmissionAuthority._Transaction":
        return self._Transaction(self)


def _permit_values(permit: DurablePermit) -> tuple[object, ...]:
    return (
        str(permit.permit_id),
        permit.attempt_id,
        permit.transport,
        permit.identity_hash,
        permit.message_hash,
        permit.policy_fingerprint,
        permit.policy_generation,
        permit.revocation_generation,
        permit.issued_at_ns,
        permit.expires_at_ns,
        permit.last_valid_block_height,
        permit.min_context_slot,
    )


def _permit_from_row(row: sqlite3.Row) -> DurablePermit:
    return DurablePermit(
        UUID(row["permit_id"]),
        row["attempt_id"],
        row["transport"],
        row["identity_hash"],
        row["message_hash"],
        row["policy_fingerprint"],
        row["policy_generation"],
        row["revocation_generation"],
        row["issued_at_ns"],
        row["expires_at_ns"],
        row["last_valid_block_height"],
        row["min_context_slot"],
    )


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MPR13AuthorityError(
            "WIRE_IDENTITY_INVALID", f"stored {label} must be an array"
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise MPR13AuthorityError(
                "WIRE_IDENTITY_INVALID", f"stored {label} contains non-text"
            )
        items.append(item)
    return tuple(items)


def _tuple_dict(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_tuple_dict(item) for item in value]
    if isinstance(value, list):
        return [_tuple_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _tuple_dict(item) for key, item in value.items()}
    return value


def _enum_dict(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _tuple_dict(item) for key, item in value.items()}


__all__ = [
    "AbsenceProof",
    "AddressLookupSnapshot",
    "DecodedMessageIdentity",
    "DurableIntent",
    "DurablePermit",
    "IntentState",
    "MPR13AuthorityError",
    "MPR13SignerPolicy",
    "MPR13SubmissionAuthority",
    "MPR13_COMPILE_TIME_LIVE_ENABLED",
    "MPR13_DECODER_VERSION",
    "MPR13_SCHEMA_VERSION",
    "ObservationFinality",
    "ObservationKind",
    "ProviderReceiptEnvelope",
    "SignedWireIdentity",
    "SignerReviewArtifact",
    "SoldersVersionedMessageDecoder",
    "StatusAuthority",
    "StatusObservationEnvelope",
    "TransportStage",
    "TransportWriteEvidence",
]
