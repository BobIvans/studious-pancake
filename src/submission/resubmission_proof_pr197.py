"""PR-197 archive-complete transaction absence proof and safe resubmission.

The legacy submission status classifier is useful as an observation, but a null
status plus a caller-selected block height is not proof that a signed transaction
never landed.  This module introduces the fail-closed proof boundary required
before a full rebuild with a new permit may be authorized.

No function in this module signs or submits a transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

PR197_PROOF_SCHEMA = "pr197.archive-complete-resubmission-proof.v1"
PR197_AUTHORIZATION_SCHEMA = "pr197.one-time-resubmission-authorization.v1"
MAX_PROOF_TTL_NS = 5 * 60 * 1_000_000_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ResubmissionProofError(ValueError):
    """Raised when proof evidence is malformed, incomplete, or unsafe."""


class AbsenceProofState(StrEnum):
    VERIFIED_ABSENT = "verified_absent"
    LANDED = "landed"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


class SignatureEvidenceState(StrEnum):
    MISSING = "missing"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TransactionLookupState(StrEnum):
    MISSING = "missing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class JsonHttpResponse(Protocol):
    status_code: int
    body: object


class AsyncJsonHttpTransport(Protocol):
    async def post_json(
        self,
        url: str,
        body: Mapping[str, object],
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> JsonHttpResponse: ...


@dataclass(frozen=True, slots=True)
class RpcEvidenceSource:
    """One independently operated, archive-capable RPC evidence source."""

    provider_id: str
    correlation_group: str
    rpc_endpoint: str
    archive_capable: bool

    def __post_init__(self) -> None:
        _require_safe_id(self.provider_id, "provider_id")
        _require_safe_id(self.correlation_group, "correlation_group")
        parsed = urlparse(self.rpc_endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            raise ResubmissionProofError("RPC evidence endpoint must be public HTTPS")

    @property
    def endpoint_fingerprint(self) -> str:
        return hashlib.sha256(self.rpc_endpoint.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Sanitized evidence collected from one RPC source."""

    provider_id: str
    correlation_group: str
    endpoint_fingerprint: str
    archive_capable: bool
    complete: bool
    genesis_hash: str | None
    finalized_slot: int | None
    finalized_block_height: int | None
    blockhash_context_slot: int | None
    blockhash_valid: bool | None
    signature_states: tuple[SignatureEvidenceState, ...]
    transaction_states: tuple[TransactionLookupState, ...]
    response_hashes: tuple[str, ...]
    observed_at_ns: int
    failure_code: str | None = None

    def blockers(
        self,
        *,
        signature_count: int,
        last_valid_block_height: int,
        min_context_slot: int,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.complete:
            blockers.append("SOURCE_OBSERVATION_INCOMPLETE")
        if not self.archive_capable:
            blockers.append("SOURCE_NOT_ARCHIVE_CAPABLE")
        if self.genesis_hash is None:
            blockers.append("SOURCE_GENESIS_HASH_MISSING")
        if self.finalized_slot is None or self.finalized_slot < min_context_slot:
            blockers.append("SOURCE_FINALIZED_SLOT_TOO_OLD")
        if (
            self.finalized_block_height is None
            or self.finalized_block_height <= last_valid_block_height
        ):
            blockers.append("SOURCE_FINALIZED_HEIGHT_NOT_BEYOND_EXPIRY")
        if (
            self.blockhash_context_slot is None
            or self.blockhash_context_slot < min_context_slot
        ):
            blockers.append("SOURCE_BLOCKHASH_CONTEXT_TOO_OLD")
        if self.blockhash_valid is not False:
            blockers.append("SOURCE_BLOCKHASH_INVALIDITY_NOT_PROVEN")
        if len(self.signature_states) != signature_count:
            blockers.append("SOURCE_SIGNATURE_STATUS_COUNT_MISMATCH")
        if len(self.transaction_states) != signature_count:
            blockers.append("SOURCE_TRANSACTION_LOOKUP_COUNT_MISMATCH")
        if any(state is not SignatureEvidenceState.MISSING for state in self.signature_states):
            blockers.append("SOURCE_SIGNATURE_ABSENCE_NOT_PROVEN")
        if any(state is not TransactionLookupState.MISSING for state in self.transaction_states):
            blockers.append("SOURCE_TRANSACTION_ABSENCE_NOT_PROVEN")
        if not self.response_hashes or any(
            not _is_sha256(value) for value in self.response_hashes
        ):
            blockers.append("SOURCE_RESPONSE_HASHES_INVALID")
        if self.failure_code:
            blockers.append(f"SOURCE_FAILURE:{self.failure_code}")
        return tuple(blockers)

    @property
    def landed(self) -> bool:
        return any(
            state in {SignatureEvidenceState.CONFIRMED, SignatureEvidenceState.FINALIZED}
            for state in self.signature_states
        ) or TransactionLookupState.SUCCEEDED in self.transaction_states

    @property
    def failed(self) -> bool:
        return (
            SignatureEvidenceState.FAILED in self.signature_states
            or TransactionLookupState.FAILED in self.transaction_states
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "correlation_group": self.correlation_group,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "archive_capable": self.archive_capable,
            "complete": self.complete,
            "genesis_hash": self.genesis_hash,
            "finalized_slot": self.finalized_slot,
            "finalized_block_height": self.finalized_block_height,
            "blockhash_context_slot": self.blockhash_context_slot,
            "blockhash_valid": self.blockhash_valid,
            "signature_states": [item.value for item in self.signature_states],
            "transaction_states": [item.value for item in self.transaction_states],
            "response_hashes": list(self.response_hashes),
            "observed_at_ns": self.observed_at_ns,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True, slots=True)
class JitoReconciliationEvidence:
    """Supplementary Jito evidence; it can block, but never prove absence alone."""

    bundle_id: str
    expected_signatures: tuple[str, ...]
    inflight_status: str
    durable_status: str
    observed_at_ns: int

    def blockers(self, *, signatures: tuple[str, ...]) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.bundle_id.strip():
            blockers.append("JITO_BUNDLE_ID_MISSING")
        if self.expected_signatures != signatures:
            blockers.append("JITO_SIGNATURE_IDENTITY_MISMATCH")
        unsafe = {"pending", "accepted", "landed", "confirmed", "finalized", "unknown"}
        if self.inflight_status.lower() in unsafe:
            blockers.append("JITO_INFLIGHT_NOT_TERMINALLY_ABSENT")
        if self.durable_status.lower() in unsafe:
            blockers.append("JITO_DURABLE_NOT_TERMINALLY_ABSENT")
        return tuple(blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "expected_signatures": list(self.expected_signatures),
            "inflight_status": self.inflight_status,
            "durable_status": self.durable_status,
            "observed_at_ns": self.observed_at_ns,
        }


@dataclass(frozen=True, slots=True)
class ResubmissionProof:
    """Archive-complete, multi-source proof bound to one old signed message."""

    proof_id: str
    attempt_id: str
    attempt_generation: int
    old_message_hash: str
    old_signatures: tuple[str, ...]
    old_blockhash: str
    last_valid_block_height: int
    min_context_slot: int
    policy_bundle_hash: str
    theoretical_expiry_observed_at_ns: int
    grace_period_ns: int
    observation_started_at_ns: int
    observation_completed_at_ns: int
    issued_at_ns: int
    expires_at_ns: int
    sources: tuple[SourceObservation, ...]
    minimum_independent_sources: int = 2
    jito: JitoReconciliationEvidence | None = None
    schema: str = PR197_PROOF_SCHEMA

    def __post_init__(self) -> None:
        _require_safe_id(self.proof_id, "proof_id")
        _require_safe_id(self.attempt_id, "attempt_id")
        if self.attempt_generation < 1:
            raise ResubmissionProofError("attempt_generation must be positive")
        _require_sha256(self.old_message_hash, "old_message_hash")
        _require_sha256(self.policy_bundle_hash, "policy_bundle_hash")
        if not self.old_signatures or len(set(self.old_signatures)) != len(
            self.old_signatures
        ):
            raise ResubmissionProofError("old signatures must be non-empty and unique")
        if any(not value.strip() for value in self.old_signatures):
            raise ResubmissionProofError("old signatures cannot be blank")
        if not self.old_blockhash.strip():
            raise ResubmissionProofError("old_blockhash is required")
        if self.last_valid_block_height < 0 or self.min_context_slot < 0:
            raise ResubmissionProofError("block height and context slot must be non-negative")
        if self.minimum_independent_sources < 2:
            raise ResubmissionProofError("at least two independent sources are required")
        if self.grace_period_ns < 0:
            raise ResubmissionProofError("grace period cannot be negative")
        if not (
            0 < self.issued_at_ns <= self.expires_at_ns
            and self.expires_at_ns - self.issued_at_ns <= MAX_PROOF_TTL_NS
        ):
            raise ResubmissionProofError("proof expiry must be positive and short-lived")
        if self.observation_completed_at_ns < self.observation_started_at_ns:
            raise ResubmissionProofError("observation window is inverted")

    @property
    def state(self) -> AbsenceProofState:
        if any(source.landed for source in self.sources):
            return AbsenceProofState.LANDED
        if any(source.failed for source in self.sources):
            return AbsenceProofState.FAILED
        if self.blockers():
            return AbsenceProofState.AMBIGUOUS
        return AbsenceProofState.VERIFIED_ABSENT

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.schema != PR197_PROOF_SCHEMA:
            blockers.append("UNSUPPORTED_PROOF_SCHEMA")
        if len(self.sources) < self.minimum_independent_sources:
            blockers.append("INSUFFICIENT_RPC_SOURCES")
        provider_ids = {source.provider_id for source in self.sources}
        groups = {source.correlation_group for source in self.sources}
        if len(provider_ids) != len(self.sources):
            blockers.append("DUPLICATE_RPC_PROVIDER")
        if len(groups) < self.minimum_independent_sources:
            blockers.append("INSUFFICIENT_INDEPENDENT_CORRELATION_GROUPS")
        genesis_values = {
            source.genesis_hash for source in self.sources if source.genesis_hash is not None
        }
        if len(genesis_values) != 1:
            blockers.append("RPC_GENESIS_DISAGREEMENT")
        grace_deadline = self.theoretical_expiry_observed_at_ns + self.grace_period_ns
        if self.observation_started_at_ns < grace_deadline:
            blockers.append("OBSERVATION_GRACE_PERIOD_NOT_ELAPSED")
        if self.issued_at_ns < self.observation_completed_at_ns:
            blockers.append("PROOF_ISSUED_BEFORE_OBSERVATION_COMPLETED")
        for source in self.sources:
            blockers.extend(
                source.blockers(
                    signature_count=len(self.old_signatures),
                    last_valid_block_height=self.last_valid_block_height,
                    min_context_slot=self.min_context_slot,
                )
            )
        if self.jito is not None:
            blockers.extend(self.jito.blockers(signatures=self.old_signatures))
        return tuple(sorted(set(blockers)))

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "proof_id": self.proof_id,
            "attempt_id": self.attempt_id,
            "attempt_generation": self.attempt_generation,
            "old_message_hash": self.old_message_hash,
            "old_signatures": list(self.old_signatures),
            "old_blockhash": self.old_blockhash,
            "last_valid_block_height": self.last_valid_block_height,
            "min_context_slot": self.min_context_slot,
            "policy_bundle_hash": self.policy_bundle_hash,
            "theoretical_expiry_observed_at_ns": self.theoretical_expiry_observed_at_ns,
            "grace_period_ns": self.grace_period_ns,
            "observation_started_at_ns": self.observation_started_at_ns,
            "observation_completed_at_ns": self.observation_completed_at_ns,
            "issued_at_ns": self.issued_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "minimum_independent_sources": self.minimum_independent_sources,
            "sources": [source.to_dict() for source in self.sources],
            "jito": self.jito.to_dict() if self.jito is not None else None,
            "state": self.state.value,
            "blockers": list(self.blockers()),
        }

    @property
    def proof_hash(self) -> str:
        return _hash_json(self.identity_payload())


@dataclass(frozen=True, slots=True)
class SafeResubmissionDecision:
    allowed: bool
    requires_new_permit: bool
    requires_freeze: bool
    reason: str
    proof_hash: str | None


def resubmission_decision_from_proof(
    proof: ResubmissionProof | None,
    *,
    now_ns: int | None = None,
) -> SafeResubmissionDecision:
    """Authorize a rebuild only from a live, verified PR-197 absence proof."""

    if proof is None:
        return SafeResubmissionDecision(
            False,
            False,
            False,
            "archive-complete resubmission proof is required",
            None,
        )
    now = int(time.time_ns() if now_ns is None else now_ns)
    if proof.state is AbsenceProofState.LANDED:
        return SafeResubmissionDecision(
            False,
            False,
            True,
            "old transaction landed; freeze and reconcile before any new submission",
            proof.proof_hash,
        )
    if proof.state is AbsenceProofState.FAILED:
        return SafeResubmissionDecision(
            False,
            False,
            True,
            "old transaction executed with an on-chain failure; absence is not proven",
            proof.proof_hash,
        )
    if proof.state is not AbsenceProofState.VERIFIED_ABSENT:
        return SafeResubmissionDecision(
            False,
            False,
            False,
            "provider evidence is incomplete or ambiguous",
            proof.proof_hash,
        )
    if now < proof.issued_at_ns or now >= proof.expires_at_ns:
        return SafeResubmissionDecision(
            False,
            False,
            False,
            "resubmission proof is not currently valid",
            proof.proof_hash,
        )
    return SafeResubmissionDecision(
        True,
        True,
        False,
        "verified archive-complete absence permits one reviewed rebuild with a new permit",
        proof.proof_hash,
    )


class ArchiveCompleteResubmissionClient:
    """Collects runtime-owned rooted/archive evidence; callers cannot supply height."""

    def __init__(
        self,
        http: AsyncJsonHttpTransport,
        sources: Sequence[RpcEvidenceSource],
        *,
        minimum_independent_sources: int = 2,
        timeout_seconds: float = 8.0,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        values = tuple(sources)
        if len(values) < minimum_independent_sources or minimum_independent_sources < 2:
            raise ResubmissionProofError("at least two RPC evidence sources are required")
        if timeout_seconds <= 0:
            raise ResubmissionProofError("timeout_seconds must be positive")
        if len({item.provider_id for item in values}) != len(values):
            raise ResubmissionProofError("RPC provider IDs must be unique")
        self.http = http
        self.sources = values
        self.minimum_independent_sources = minimum_independent_sources
        self.timeout_seconds = timeout_seconds
        self.clock_ns = clock_ns

    async def collect_proof(
        self,
        *,
        attempt_id: str,
        attempt_generation: int,
        old_message_hash: str,
        old_signatures: Sequence[str],
        old_blockhash: str,
        last_valid_block_height: int,
        min_context_slot: int,
        policy_bundle_hash: str,
        theoretical_expiry_observed_at_ns: int,
        grace_period_ns: int,
        proof_ttl_ns: int = 60 * 1_000_000_000,
        jito: JitoReconciliationEvidence | None = None,
    ) -> ResubmissionProof:
        """Collect proof without accepting a caller-provided current block height."""

        if proof_ttl_ns <= 0 or proof_ttl_ns > MAX_PROOF_TTL_NS:
            raise ResubmissionProofError("proof_ttl_ns is outside the reviewed bound")
        signatures = tuple(old_signatures)
        started = int(self.clock_ns())
        observations = await asyncio.gather(
            *(
                self._observe_source_safe(
                    source,
                    signatures=signatures,
                    old_blockhash=old_blockhash,
                    min_context_slot=min_context_slot,
                )
                for source in self.sources
            )
        )
        completed = int(self.clock_ns())
        issued = max(completed, int(self.clock_ns()))
        return ResubmissionProof(
            proof_id=f"proof-{uuid4()}",
            attempt_id=attempt_id,
            attempt_generation=attempt_generation,
            old_message_hash=old_message_hash,
            old_signatures=signatures,
            old_blockhash=old_blockhash,
            last_valid_block_height=last_valid_block_height,
            min_context_slot=min_context_slot,
            policy_bundle_hash=policy_bundle_hash,
            theoretical_expiry_observed_at_ns=theoretical_expiry_observed_at_ns,
            grace_period_ns=grace_period_ns,
            observation_started_at_ns=started,
            observation_completed_at_ns=completed,
            issued_at_ns=issued,
            expires_at_ns=issued + proof_ttl_ns,
            sources=tuple(observations),
            minimum_independent_sources=self.minimum_independent_sources,
            jito=jito,
        )

    async def _observe_source_safe(
        self,
        source: RpcEvidenceSource,
        *,
        signatures: tuple[str, ...],
        old_blockhash: str,
        min_context_slot: int,
    ) -> SourceObservation:
        try:
            return await self._observe_source(
                source,
                signatures=signatures,
                old_blockhash=old_blockhash,
                min_context_slot=min_context_slot,
            )
        except Exception as exc:  # fail closed and retain only a stable category
            code = (
                str(exc)
                if isinstance(exc, ResubmissionProofError)
                else type(exc).__name__
            )
            return SourceObservation(
                provider_id=source.provider_id,
                correlation_group=source.correlation_group,
                endpoint_fingerprint=source.endpoint_fingerprint,
                archive_capable=source.archive_capable,
                complete=False,
                genesis_hash=None,
                finalized_slot=None,
                finalized_block_height=None,
                blockhash_context_slot=None,
                blockhash_valid=None,
                signature_states=(),
                transaction_states=(),
                response_hashes=(),
                observed_at_ns=int(self.clock_ns()),
                failure_code=_stable_failure_code(code),
            )

    async def _observe_source(
        self,
        source: RpcEvidenceSource,
        *,
        signatures: tuple[str, ...],
        old_blockhash: str,
        min_context_slot: int,
    ) -> SourceObservation:
        response_hashes: list[str] = []
        genesis, digest = await self._rpc_call(source, "getGenesisHash", [])
        response_hashes.append(digest)
        if not isinstance(genesis, str) or not genesis:
            raise ResubmissionProofError("genesis_hash_invalid")

        slot_raw, digest = await self._rpc_call(
            source, "getSlot", [{"commitment": "finalized"}]
        )
        response_hashes.append(digest)
        finalized_slot = _require_non_negative_int(slot_raw, "finalized_slot_invalid")

        height_raw, digest = await self._rpc_call(
            source,
            "getBlockHeight",
            [{"commitment": "finalized", "minContextSlot": min_context_slot}],
        )
        response_hashes.append(digest)
        finalized_height = _require_non_negative_int(
            height_raw, "finalized_block_height_invalid"
        )

        blockhash_raw, digest = await self._rpc_call(
            source,
            "isBlockhashValid",
            [
                old_blockhash,
                {"commitment": "finalized", "minContextSlot": min_context_slot},
            ],
        )
        response_hashes.append(digest)
        if not isinstance(blockhash_raw, Mapping):
            raise ResubmissionProofError("blockhash_validity_shape_invalid")
        context = blockhash_raw.get("context")
        if not isinstance(context, Mapping):
            raise ResubmissionProofError("blockhash_context_invalid")
        context_slot = _require_non_negative_int(
            context.get("slot"), "blockhash_context_slot_invalid"
        )
        blockhash_valid = blockhash_raw.get("value")
        if not isinstance(blockhash_valid, bool):
            raise ResubmissionProofError("blockhash_validity_value_invalid")

        statuses_raw, digest = await self._rpc_call(
            source,
            "getSignatureStatuses",
            [list(signatures), {"searchTransactionHistory": True}],
        )
        response_hashes.append(digest)
        signature_states = _parse_signature_states(statuses_raw, len(signatures))

        transaction_states: list[TransactionLookupState] = []
        for signature in signatures:
            transaction_raw, digest = await self._rpc_call(
                source,
                "getTransaction",
                [
                    signature,
                    {
                        "commitment": "finalized",
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            )
            response_hashes.append(digest)
            transaction_states.append(_parse_transaction_state(transaction_raw))

        return SourceObservation(
            provider_id=source.provider_id,
            correlation_group=source.correlation_group,
            endpoint_fingerprint=source.endpoint_fingerprint,
            archive_capable=source.archive_capable,
            complete=True,
            genesis_hash=genesis,
            finalized_slot=finalized_slot,
            finalized_block_height=finalized_height,
            blockhash_context_slot=context_slot,
            blockhash_valid=blockhash_valid,
            signature_states=signature_states,
            transaction_states=tuple(transaction_states),
            response_hashes=tuple(response_hashes),
            observed_at_ns=int(self.clock_ns()),
        )

    async def _rpc_call(
        self,
        source: RpcEvidenceSource,
        method: str,
        params: list[object],
    ) -> tuple[object, str]:
        request_id = str(uuid4())
        request: Mapping[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            response = await asyncio.wait_for(
                self.http.post_json(
                    source.rpc_endpoint,
                    request,
                    headers={"content-type": "application/json"},
                    timeout_seconds=self.timeout_seconds,
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ResubmissionProofError("rpc_timeout") from exc
        if not 200 <= response.status_code < 300:
            raise ResubmissionProofError("rpc_http_status")
        body = response.body
        if not isinstance(body, Mapping):
            raise ResubmissionProofError("rpc_response_shape")
        digest = _hash_json(body)
        if body.get("jsonrpc") != "2.0" or body.get("id") != request_id:
            raise ResubmissionProofError("rpc_response_identity")
        if body.get("error") is not None or "result" not in body:
            raise ResubmissionProofError("rpc_error_or_missing_result")
        return body["result"], digest


@dataclass(frozen=True, slots=True)
class ResendAuthorization:
    authorization_id: str
    proof_hash: str
    superseded_message_hash: str
    new_permit_request_hash: str
    created_at_ns: int
    schema: str = PR197_AUTHORIZATION_SCHEMA

    @property
    def authorization_hash(self) -> str:
        return _hash_json(
            {
                "schema": self.schema,
                "authorization_id": self.authorization_id,
                "proof_hash": self.proof_hash,
                "superseded_message_hash": self.superseded_message_hash,
                "new_permit_request_hash": self.new_permit_request_hash,
                "created_at_ns": self.created_at_ns,
            }
        )


class SQLiteResubmissionProofStore:
    """Durable one-time proof consumption and late-landing conflict latch."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pr197_resubmission_proofs (
                    proof_hash TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    attempt_generation INTEGER NOT NULL,
                    old_message_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    issued_at_ns INTEGER NOT NULL,
                    expires_at_ns INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0, 1)),
                    late_landing INTEGER NOT NULL DEFAULT 0 CHECK (late_landing IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS pr197_resend_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    proof_hash TEXT NOT NULL UNIQUE,
                    new_permit_request_hash TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    authorization_hash TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(proof_hash) REFERENCES pr197_resubmission_proofs(proof_hash)
                );
                CREATE TABLE IF NOT EXISTS pr197_late_landings (
                    proof_hash TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    observed_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(proof_hash, signature),
                    FOREIGN KEY(proof_hash) REFERENCES pr197_resubmission_proofs(proof_hash)
                );
                """
            )

    def record_proof(self, proof: ResubmissionProof) -> str:
        payload = _canonical_json(proof.identity_payload())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM pr197_resubmission_proofs WHERE proof_hash = ?",
                (proof.proof_hash,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload:
                    raise ResubmissionProofError("proof hash collision or mutation detected")
                return proof.proof_hash
            connection.execute(
                """
                INSERT INTO pr197_resubmission_proofs (
                    proof_hash, attempt_id, attempt_generation, old_message_hash,
                    state, issued_at_ns, expires_at_ns, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proof.proof_hash,
                    proof.attempt_id,
                    proof.attempt_generation,
                    proof.old_message_hash,
                    proof.state.value,
                    proof.issued_at_ns,
                    proof.expires_at_ns,
                    payload,
                ),
            )
        return proof.proof_hash

    def authorize_new_permit(
        self,
        *,
        proof_hash: str,
        new_permit_request_hash: str,
        now_ns: int | None = None,
    ) -> ResendAuthorization:
        _require_sha256(proof_hash, "proof_hash")
        _require_sha256(new_permit_request_hash, "new_permit_request_hash")
        now = int(time.time_ns() if now_ns is None else now_ns)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT old_message_hash, state, issued_at_ns, expires_at_ns,
                       consumed, late_landing
                FROM pr197_resubmission_proofs
                WHERE proof_hash = ?
                """,
                (proof_hash,),
            ).fetchone()
            if row is None:
                raise ResubmissionProofError("resubmission proof is not recorded")
            if row["state"] != AbsenceProofState.VERIFIED_ABSENT.value:
                raise ResubmissionProofError("only verified absence can authorize rebuild")
            if not row["issued_at_ns"] <= now < row["expires_at_ns"]:
                raise ResubmissionProofError("resubmission proof is expired or not yet valid")
            if row["consumed"]:
                raise ResubmissionProofError("resubmission proof was already consumed")
            if row["late_landing"]:
                raise ResubmissionProofError("late landing conflict freezes resubmission")
            authorization = ResendAuthorization(
                authorization_id=f"resend-{uuid4()}",
                proof_hash=proof_hash,
                superseded_message_hash=row["old_message_hash"],
                new_permit_request_hash=new_permit_request_hash,
                created_at_ns=now,
            )
            connection.execute(
                """
                INSERT INTO pr197_resend_authorizations (
                    authorization_id, proof_hash, new_permit_request_hash,
                    created_at_ns, authorization_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    authorization.authorization_id,
                    proof_hash,
                    new_permit_request_hash,
                    now,
                    authorization.authorization_hash,
                ),
            )
            updated = connection.execute(
                """
                UPDATE pr197_resubmission_proofs
                SET consumed = 1
                WHERE proof_hash = ? AND consumed = 0 AND late_landing = 0
                """,
                (proof_hash,),
            )
            if updated.rowcount != 1:
                raise ResubmissionProofError("proof consumption lost an atomic race")
        return authorization

    def record_late_landing(
        self,
        *,
        proof_hash: str,
        signature: str,
        observed_at_ns: int | None = None,
    ) -> None:
        _require_sha256(proof_hash, "proof_hash")
        if not signature.strip():
            raise ResubmissionProofError("late landing signature is required")
        observed = int(time.time_ns() if observed_at_ns is None else observed_at_ns)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            found = connection.execute(
                "SELECT 1 FROM pr197_resubmission_proofs WHERE proof_hash = ?",
                (proof_hash,),
            ).fetchone()
            if found is None:
                raise ResubmissionProofError("resubmission proof is not recorded")
            connection.execute(
                """
                INSERT OR IGNORE INTO pr197_late_landings (
                    proof_hash, signature, observed_at_ns
                ) VALUES (?, ?, ?)
                """,
                (proof_hash, signature, observed),
            )
            connection.execute(
                "UPDATE pr197_resubmission_proofs SET late_landing = 1 WHERE proof_hash = ?",
                (proof_hash,),
            )

    def freeze_required(self, proof_hash: str) -> bool:
        _require_sha256(proof_hash, "proof_hash")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT late_landing FROM pr197_resubmission_proofs WHERE proof_hash = ?",
                (proof_hash,),
            ).fetchone()
        if row is None:
            raise ResubmissionProofError("resubmission proof is not recorded")
        return bool(row["late_landing"])


def _parse_signature_states(
    result: object,
    expected_count: int,
) -> tuple[SignatureEvidenceState, ...]:
    if not isinstance(result, Mapping):
        raise ResubmissionProofError("signature_status_result_invalid")
    value = result.get("value")
    if not isinstance(value, list) or len(value) != expected_count:
        raise ResubmissionProofError("signature_status_count_invalid")
    states: list[SignatureEvidenceState] = []
    for item in value:
        if item is None:
            states.append(SignatureEvidenceState.MISSING)
            continue
        if not isinstance(item, Mapping):
            raise ResubmissionProofError("signature_status_item_invalid")
        if item.get("err") is not None:
            states.append(SignatureEvidenceState.FAILED)
            continue
        confirmation = item.get("confirmationStatus")
        if confirmation == "processed":
            states.append(SignatureEvidenceState.PROCESSED)
        elif confirmation == "confirmed":
            states.append(SignatureEvidenceState.CONFIRMED)
        elif confirmation == "finalized":
            states.append(SignatureEvidenceState.FINALIZED)
        else:
            states.append(SignatureEvidenceState.UNKNOWN)
    return tuple(states)


def _parse_transaction_state(result: object) -> TransactionLookupState:
    if result is None:
        return TransactionLookupState.MISSING
    if not isinstance(result, Mapping):
        return TransactionLookupState.UNKNOWN
    meta = result.get("meta")
    if not isinstance(meta, Mapping):
        return TransactionLookupState.UNKNOWN
    return (
        TransactionLookupState.SUCCEEDED
        if meta.get("err") is None
        else TransactionLookupState.FAILED
    )


def _require_non_negative_int(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ResubmissionProofError(code)
    return value


def _stable_failure_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return normalized[:64] or "unknown_failure"


def _require_safe_id(value: str, field: str) -> None:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ResubmissionProofError(f"{field} has an invalid shape")


def _require_sha256(value: str, field: str) -> None:
    if not _is_sha256(value):
        raise ResubmissionProofError(f"{field} must be lowercase SHA-256 hex")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResubmissionProofError("value is not canonical JSON") from exc


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "PR197_AUTHORIZATION_SCHEMA",
    "PR197_PROOF_SCHEMA",
    "AbsenceProofState",
    "ArchiveCompleteResubmissionClient",
    "AsyncJsonHttpTransport",
    "JitoReconciliationEvidence",
    "ResendAuthorization",
    "ResubmissionProof",
    "ResubmissionProofError",
    "RpcEvidenceSource",
    "SafeResubmissionDecision",
    "SignatureEvidenceState",
    "SourceObservation",
    "SQLiteResubmissionProofStore",
    "TransactionLookupState",
    "resubmission_decision_from_proof",
]
