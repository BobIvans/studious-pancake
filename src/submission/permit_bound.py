"""Permit-bound RPC/Jito submission and transport reconciliation for PR-045.

The module is network-transport agnostic.  Callers inject an async HTTP port and
must obtain a one-time permit from a default-deny issuer before any request can
be emitted.  A transport acknowledgement is never treated as landing proof.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
import time
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import UUID, uuid4

from solders.message import to_bytes_versioned
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SYSTEM_TRANSFER_DISCRIMINATOR = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BASE58_SIGNATURE_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{64,90}$")
_JITO_HOST_RE = re.compile(r"^(?:[a-z0-9-]+\.)?mainnet\.block-engine\.jito\.wtf$")


class TransportKind(StrEnum):
    RPC = "rpc"
    JITO_SINGLE = "jito_single"
    JITO_BUNDLE = "jito_bundle"


class SubmissionState(StrEnum):
    ACCEPTED = "accepted"
    LANDED = "landed"
    FAILED = "failed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class ErrorDisposition(StrEnum):
    FATAL = "fatal"
    RETRYABLE_PRE_SEND = "retryable_pre_send"
    AMBIGUOUS = "ambiguous"


class SubmissionErrorCode(StrEnum):
    LIVE_GATE_CLOSED = "live_gate_closed"
    PERMIT_INVALID = "permit_invalid"
    PERMIT_EXPIRED = "permit_expired"
    IDENTITY_MISMATCH = "identity_mismatch"
    PAYLOAD_INVALID = "payload_invalid"
    AUTH_INVALID = "auth_invalid"
    TIP_POLICY_INVALID = "tip_policy_invalid"
    ENDPOINT_INVALID = "endpoint_invalid"
    TRANSPORT_ERROR = "transport_error"
    JSON_RPC_ERROR = "json_rpc_error"
    MALFORMED_RESPONSE = "malformed_response"
    STATUS_INDETERMINATE = "status_indeterminate"
    RESUBMIT_FORBIDDEN = "resubmit_forbidden"


SafeDetail = str | int | bool | None


class SubmissionError(RuntimeError):
    """Typed error with intentionally redaction-safe diagnostics."""

    def __init__(
        self,
        code: SubmissionErrorCode,
        disposition: ErrorDisposition,
        message: str,
        details: Mapping[str, SafeDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.disposition = disposition
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: object
    headers: Mapping[str, str] = field(default_factory=dict)


class AsyncJsonHttpTransport(Protocol):
    async def post_json(
        self,
        url: str,
        body: Mapping[str, object],
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class JitoUuidAuth:
    """Optional Jito UUID auth; the value is excluded from repr and diagnostics."""

    value: UUID = field(repr=False)

    @classmethod
    def parse(cls, value: str) -> "JitoUuidAuth":
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise SubmissionError(
                SubmissionErrorCode.AUTH_INVALID,
                ErrorDisposition.FATAL,
                "Jito authentication must be a UUID",
            ) from exc
        return cls(parsed)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.value.bytes).hexdigest()[:16]

    def headers(self) -> Mapping[str, str]:
        return {"x-jito-auth": str(self.value)}


@dataclass(frozen=True, slots=True)
class TipEvidence:
    bound_message_hashes: tuple[str, ...]
    tip_message_hash: str
    payer: str
    account: str
    lamports: int
    instruction_count: int
    account_is_static: bool

    def __post_init__(self) -> None:
        if not self.bound_message_hashes:
            raise ValueError("tip evidence must bind at least one message")
        for value in self.bound_message_hashes:
            _require_hash(value, "tip bound message hash")
        _require_hash(self.tip_message_hash, "tip message_hash")
        if self.tip_message_hash not in self.bound_message_hashes:
            raise ValueError("tip message must be inside the bound payload")
        if not self.payer or not self.account:
            raise ValueError("tip payer and account are required")
        if self.lamports <= 0 or self.instruction_count != 1:
            raise ValueError("exactly one positive tip is required")

    @property
    def message_hash(self) -> str:
        return self.tip_message_hash

    @property
    def evidence_hash(self) -> str:
        return _hash_json(
            {
                "bound_message_hashes": list(self.bound_message_hashes),
                "tip_message_hash": self.tip_message_hash,
                "payer": self.payer,
                "account": self.account,
                "lamports": self.lamports,
                "instruction_count": self.instruction_count,
                "account_is_static": self.account_is_static,
            }
        )


@dataclass(frozen=True, slots=True)
class SignedPayload:
    """Canonical signed wire payload with identities derived from the bytes."""

    transactions: tuple[bytes, ...]
    message_hashes: tuple[str, ...]
    signatures: tuple[str, ...]
    transaction_digests: tuple[str, ...]
    tip_evidence: TipEvidence | None = None

    @classmethod
    def from_wire_transactions(
        cls,
        transactions: Sequence[bytes],
        *,
        tip_evidence: TipEvidence | None = None,
    ) -> "SignedPayload":
        if not 1 <= len(transactions) <= 5:
            raise SubmissionError(
                SubmissionErrorCode.PAYLOAD_INVALID,
                ErrorDisposition.FATAL,
                "signed payload must contain one to five transactions",
            )
        wire: list[bytes] = []
        message_hashes: list[str] = []
        signatures: list[str] = []
        digests: list[str] = []
        for raw_value in transactions:
            raw = bytes(raw_value)
            if not raw:
                raise SubmissionError(
                    SubmissionErrorCode.PAYLOAD_INVALID,
                    ErrorDisposition.FATAL,
                    "signed transaction cannot be empty",
                )
            try:
                tx = VersionedTransaction.from_bytes(raw)
                tx.sanitize()
                verified = tx.verify_with_results()
            except Exception as exc:
                raise SubmissionError(
                    SubmissionErrorCode.PAYLOAD_INVALID,
                    ErrorDisposition.FATAL,
                    "signed transaction failed canonical parsing",
                ) from exc
            if not verified or not all(verified):
                raise SubmissionError(
                    SubmissionErrorCode.PAYLOAD_INVALID,
                    ErrorDisposition.FATAL,
                    "signed transaction contains an invalid signature",
                )
            if not tx.signatures:
                raise SubmissionError(
                    SubmissionErrorCode.PAYLOAD_INVALID,
                    ErrorDisposition.FATAL,
                    "signed transaction has no transaction signature",
                )
            message_bytes = bytes(to_bytes_versioned(tx.message))
            signature = str(tx.signatures[0])
            if not _valid_signature(signature):
                raise SubmissionError(
                    SubmissionErrorCode.PAYLOAD_INVALID,
                    ErrorDisposition.FATAL,
                    "transaction signature shape is invalid",
                )
            wire.append(raw)
            message_hashes.append(hashlib.sha256(message_bytes).hexdigest())
            signatures.append(signature)
            digests.append(hashlib.sha256(raw).hexdigest())
        if len(set(signatures)) != len(signatures):
            raise SubmissionError(
                SubmissionErrorCode.PAYLOAD_INVALID,
                ErrorDisposition.FATAL,
                "duplicate transaction signature in payload",
            )
        payload = cls(
            tuple(wire),
            tuple(message_hashes),
            tuple(signatures),
            tuple(digests),
            tip_evidence,
        )
        if tip_evidence and tip_evidence.bound_message_hashes != payload.message_hashes:
            raise SubmissionError(
                SubmissionErrorCode.TIP_POLICY_INVALID,
                ErrorDisposition.FATAL,
                "tip evidence is not bound to the complete signed payload",
            )
        return payload

    @property
    def primary_message_hash(self) -> str:
        return self.message_hashes[0]

    @property
    def payload_digest(self) -> str:
        framed = bytearray()
        for raw in self.transactions:
            framed.extend(len(raw).to_bytes(8, "big"))
            framed.extend(raw)
        return hashlib.sha256(framed).hexdigest()


@dataclass(frozen=True, slots=True)
class LiveSubmissionPolicy:
    """Two independent switches keep the transport completely default-deny."""

    compile_time_enabled: bool = False
    config_enabled: bool = False
    allowed_transports: tuple[TransportKind, ...] = ()
    commitment: str = "confirmed"
    skip_preflight: bool = False
    max_retries: int = 0
    timeout_seconds: float = 8.0
    require_jito_uuid_auth: bool = True
    jito_bundle_only: bool = True

    def __post_init__(self) -> None:
        if self.commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("unsupported commitment")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if len(set(self.allowed_transports)) != len(self.allowed_transports):
            raise ValueError("allowed_transports contains duplicates")

    @property
    def enabled(self) -> bool:
        return self.compile_time_enabled and self.config_enabled

    @property
    def fingerprint(self) -> str:
        return _hash_json(
            {
                "compile_time_enabled": self.compile_time_enabled,
                "config_enabled": self.config_enabled,
                "allowed_transports": [item.value for item in self.allowed_transports],
                "commitment": self.commitment,
                "skip_preflight": self.skip_preflight,
                "max_retries": self.max_retries,
                "timeout_seconds": self.timeout_seconds,
                "require_jito_uuid_auth": self.require_jito_uuid_auth,
                "jito_bundle_only": self.jito_bundle_only,
            }
        )


@dataclass(frozen=True, slots=True)
class PermitRequest:
    attempt_id: str
    transport: TransportKind
    message_hash: str
    exact_simulation_hash: str
    payload_digest: str
    message_hashes: tuple[str, ...]
    transaction_digests: tuple[str, ...]
    expected_signatures: tuple[str, ...]
    expires_at_ns: int
    last_valid_block_height: int
    min_context_slot: int
    tip_evidence_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionPermit:
    permit_id: UUID
    attempt_id: str
    transport: TransportKind
    message_hash: str
    payload_digest: str
    message_hashes: tuple[str, ...]
    transaction_digests: tuple[str, ...]
    expected_signatures: tuple[str, ...]
    issued_at_ns: int
    expires_at_ns: int
    last_valid_block_height: int
    min_context_slot: int
    policy_fingerprint: str
    tip_evidence_hash: str | None

    @property
    def idempotency_key(self) -> str:
        return f"permit:{self.permit_id}:{self.attempt_id}:{self.message_hash}"


class LivePermitIssuer:
    """Issues in-process one-time permits; no environment variable is consulted."""

    def __init__(
        self,
        policy: LiveSubmissionPolicy | None = None,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.policy = policy or LiveSubmissionPolicy()
        self.clock_ns = clock_ns
        self._issued: dict[UUID, SubmissionPermit] = {}
        self._consumed: set[UUID] = set()

    def issue(self, request: PermitRequest) -> SubmissionPermit:
        now = int(self.clock_ns())
        if not self.policy.enabled:
            raise SubmissionError(
                SubmissionErrorCode.LIVE_GATE_CLOSED,
                ErrorDisposition.FATAL,
                "live submission is disabled by compile-time/config policy",
            )
        if request.transport not in self.policy.allowed_transports:
            raise SubmissionError(
                SubmissionErrorCode.LIVE_GATE_CLOSED,
                ErrorDisposition.FATAL,
                "requested transport is not allowlisted",
            )
        self._validate_request(request, now)
        permit = SubmissionPermit(
            permit_id=uuid4(),
            attempt_id=request.attempt_id,
            transport=request.transport,
            message_hash=request.message_hash,
            payload_digest=request.payload_digest,
            message_hashes=request.message_hashes,
            transaction_digests=request.transaction_digests,
            expected_signatures=request.expected_signatures,
            issued_at_ns=now,
            expires_at_ns=request.expires_at_ns,
            last_valid_block_height=request.last_valid_block_height,
            min_context_slot=request.min_context_slot,
            policy_fingerprint=self.policy.fingerprint,
            tip_evidence_hash=request.tip_evidence_hash,
        )
        self._issued[permit.permit_id] = permit
        return permit

    def consume(self, permit: SubmissionPermit) -> None:
        now = int(self.clock_ns())
        issued = self._issued.get(permit.permit_id)
        if issued != permit or permit.policy_fingerprint != self.policy.fingerprint:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit was not issued by this active policy",
            )
        if permit.permit_id in self._consumed:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit has already been consumed",
            )
        if now >= permit.expires_at_ns:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_EXPIRED,
                ErrorDisposition.FATAL,
                "permit has expired",
            )
        self._consumed.add(permit.permit_id)

    @staticmethod
    def _validate_request(request: PermitRequest, now: int) -> None:
        if not request.attempt_id:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "attempt_id is required",
            )
        for label, value in (
            ("message_hash", request.message_hash),
            ("exact_simulation_hash", request.exact_simulation_hash),
            ("payload_digest", request.payload_digest),
        ):
            _require_hash(value, label)
        if request.message_hash != request.exact_simulation_hash:
            raise SubmissionError(
                SubmissionErrorCode.IDENTITY_MISMATCH,
                ErrorDisposition.FATAL,
                "permit hash does not match exact simulation",
            )
        count = len(request.message_hashes)
        if not 1 <= count <= 5:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit must bind one to five transactions",
            )
        if request.transport is not TransportKind.JITO_BUNDLE and count != 1:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "non-bundle transport must bind one transaction",
            )
        if not (
            count
            == len(request.transaction_digests)
            == len(request.expected_signatures)
        ):
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit identity tuple lengths differ",
            )
        if request.message_hashes[0] != request.message_hash:
            raise SubmissionError(
                SubmissionErrorCode.IDENTITY_MISMATCH,
                ErrorDisposition.FATAL,
                "primary permit hash is not the first payload hash",
            )
        for value in (*request.message_hashes, *request.transaction_digests):
            _require_hash(value, "permit transaction identity")
        if any(not _valid_signature(value) for value in request.expected_signatures):
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit contains an invalid transaction signature",
            )
        if len(set(request.expected_signatures)) != count:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit signatures must be unique",
            )
        if request.expires_at_ns <= now:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_EXPIRED,
                ErrorDisposition.FATAL,
                "permit expiry must be in the future",
            )
        if request.last_valid_block_height < 0 or request.min_context_slot < 0:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "block height and context slot must be non-negative",
            )
        if request.tip_evidence_hash is not None:
            _require_hash(request.tip_evidence_hash, "tip_evidence_hash")


def permit_request_from_payload(
    *,
    attempt_id: str,
    transport: TransportKind,
    exact_simulation_hash: str,
    payload: SignedPayload,
    expires_at_ns: int,
    last_valid_block_height: int,
    min_context_slot: int,
) -> PermitRequest:
    return PermitRequest(
        attempt_id=attempt_id,
        transport=transport,
        message_hash=payload.primary_message_hash,
        exact_simulation_hash=exact_simulation_hash,
        payload_digest=payload.payload_digest,
        message_hashes=payload.message_hashes,
        transaction_digests=payload.transaction_digests,
        expected_signatures=payload.signatures,
        expires_at_ns=expires_at_ns,
        last_valid_block_height=last_valid_block_height,
        min_context_slot=min_context_slot,
        tip_evidence_hash=(
            payload.tip_evidence.evidence_hash if payload.tip_evidence else None
        ),
    )


def validate_permit_payload(
    permit: SubmissionPermit,
    payload: SignedPayload,
    message_hash: str,
) -> None:
    _require_hash(message_hash, "submission message_hash")
    if (
        message_hash != permit.message_hash
        or message_hash != payload.primary_message_hash
    ):
        raise SubmissionError(
            SubmissionErrorCode.IDENTITY_MISMATCH,
            ErrorDisposition.FATAL,
            "permit, payload and submission message hashes differ",
        )
    comparisons = (
        (permit.payload_digest, payload.payload_digest, "payload digest"),
        (permit.message_hashes, payload.message_hashes, "message hashes"),
        (permit.transaction_digests, payload.transaction_digests, "wire digests"),
        (permit.expected_signatures, payload.signatures, "transaction signatures"),
    )
    for expected, actual, label in comparisons:
        if expected != actual:
            raise SubmissionError(
                SubmissionErrorCode.IDENTITY_MISMATCH,
                ErrorDisposition.FATAL,
                f"permit {label} do not match signed payload",
            )
    evidence_hash = payload.tip_evidence.evidence_hash if payload.tip_evidence else None
    if permit.tip_evidence_hash != evidence_hash:
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "permit tip evidence does not match signed payload",
        )


def inspect_exactly_one_system_tip(
    *,
    instructions: Sequence[object],
    message_hash: str,
    payer: object,
    approved_accounts: set[str],
    expected_account: object,
    expected_lamports: int,
    static_account_keys: set[str],
) -> TipEvidence:
    """Inspect one canonical transaction before signing/permit issuance."""

    return inspect_exactly_one_system_tip_across_transactions(
        instruction_sets=(instructions,),
        message_hashes=(message_hash,),
        payer=payer,
        approved_accounts=approved_accounts,
        expected_account=expected_account,
        expected_lamports=expected_lamports,
        static_account_keys_by_message=(static_account_keys,),
    )


def inspect_exactly_one_system_tip_across_transactions(
    *,
    instruction_sets: Sequence[Sequence[object]],
    message_hashes: tuple[str, ...],
    payer: object,
    approved_accounts: set[str],
    expected_account: object,
    expected_lamports: int,
    static_account_keys_by_message: Sequence[set[str]],
) -> TipEvidence:
    """Prove exactly one approved System transfer across a full Jito bundle."""

    if not instruction_sets or len(instruction_sets) != len(message_hashes):
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "tip inspection inputs do not match the payload",
        )
    if len(static_account_keys_by_message) != len(message_hashes):
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "static account evidence does not match the payload",
        )
    for value in message_hashes:
        _require_hash(value, "message_hash")
    if expected_lamports <= 0:
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "Jito tip must be positive",
        )
    payer_text = str(payer)
    expected_text = str(expected_account)
    if expected_text not in approved_accounts:
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "tip account is not in current getTipAccounts evidence",
        )
    matches: list[tuple[int, str, int]] = []
    for transaction_index, instructions in enumerate(instruction_sets):
        for instruction in instructions:
            if str(getattr(instruction, "program_id", "")) != SYSTEM_PROGRAM_ID:
                continue
            accounts = tuple(getattr(instruction, "accounts", ()))
            data = bytes(getattr(instruction, "data", b""))
            if len(accounts) < 2 or len(data) != 12:
                continue
            discriminator = int.from_bytes(data[:4], "little")
            if discriminator != SYSTEM_TRANSFER_DISCRIMINATOR:
                continue
            source = str(getattr(accounts[0], "pubkey", ""))
            destination = str(getattr(accounts[1], "pubkey", ""))
            lamports = int.from_bytes(data[4:], "little")
            if source == payer_text and destination in approved_accounts:
                matches.append((transaction_index, destination, lamports))
    exact = [item for item in matches if item[1:] == (expected_text, expected_lamports)]
    if len(matches) != 1 or len(exact) != 1:
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "compiled payload must contain exactly one approved Jito tip",
            {"matching_tip_count": len(matches)},
        )
    transaction_index = exact[0][0]
    if expected_text not in static_account_keys_by_message[transaction_index]:
        raise SubmissionError(
            SubmissionErrorCode.TIP_POLICY_INVALID,
            ErrorDisposition.FATAL,
            "Jito tip account must be a static message account",
        )
    return TipEvidence(
        bound_message_hashes=message_hashes,
        tip_message_hash=message_hashes[transaction_index],
        payer=payer_text,
        account=expected_text,
        lamports=expected_lamports,
        instruction_count=1,
        account_is_static=True,
    )


@dataclass(frozen=True, slots=True)
class SubmissionAck:
    state: SubmissionState
    transport: TransportKind
    request_id: str
    transaction_signatures: tuple[str, ...]
    bundle_id: str | None
    accepted_at_ns: int
    provider_code: int | None = None

    @property
    def landed(self) -> bool:
        return self.state is SubmissionState.LANDED


class Sender(Protocol):
    async def submit(
        self,
        permit: SubmissionPermit,
        signed_payload: SignedPayload,
        message_hash: str,
    ) -> SubmissionAck: ...


class _BaseSender:
    def __init__(
        self,
        http: AsyncJsonHttpTransport,
        issuer: LivePermitIssuer,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.http = http
        self.issuer = issuer
        self.clock_ns = clock_ns

    async def _post(
        self,
        url: str,
        body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> HttpResponse:
        try:
            return await asyncio.wait_for(
                self.http.post_json(
                    url,
                    body,
                    headers=headers,
                    timeout_seconds=self.issuer.policy.timeout_seconds,
                ),
                timeout=self.issuer.policy.timeout_seconds,
            )
        except SubmissionError:
            raise
        except TimeoutError as exc:
            raise SubmissionError(
                SubmissionErrorCode.TRANSPORT_ERROR,
                ErrorDisposition.AMBIGUOUS,
                "submission transport timed out after request dispatch",
            ) from exc
        except Exception as exc:
            raise SubmissionError(
                SubmissionErrorCode.TRANSPORT_ERROR,
                ErrorDisposition.AMBIGUOUS,
                "submission transport failed after request dispatch",
                {"exception_type": type(exc).__name__},
            ) from exc

    def _prepare(
        self,
        permit: SubmissionPermit,
        payload: SignedPayload,
        message_hash: str,
        expected: TransportKind,
    ) -> None:
        if permit.transport is not expected:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit transport does not match sender",
            )
        validate_permit_payload(permit, payload, message_hash)
        self.issuer.consume(permit)


class RpcSender(_BaseSender):
    def __init__(
        self,
        endpoint: str,
        http: AsyncJsonHttpTransport,
        issuer: LivePermitIssuer,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        super().__init__(http, issuer, clock_ns=clock_ns)
        self.endpoint = _validate_https_endpoint(endpoint)

    async def submit(
        self,
        permit: SubmissionPermit,
        signed_payload: SignedPayload,
        message_hash: str,
    ) -> SubmissionAck:
        self._prepare(permit, signed_payload, message_hash, TransportKind.RPC)
        if len(signed_payload.transactions) != 1:
            raise SubmissionError(
                SubmissionErrorCode.PAYLOAD_INVALID,
                ErrorDisposition.FATAL,
                "RPC sender accepts exactly one transaction",
            )
        request_id = str(uuid4())
        body: Mapping[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(signed_payload.transactions[0]).decode("ascii"),
                {
                    "encoding": "base64",
                    "skipPreflight": self.issuer.policy.skip_preflight,
                    "preflightCommitment": self.issuer.policy.commitment,
                    "maxRetries": self.issuer.policy.max_retries,
                    "minContextSlot": permit.min_context_slot,
                },
            ],
        }
        response = await self._post(
            self.endpoint,
            body,
            {"content-type": "application/json"},
        )
        result = _unwrap_json_rpc(response, request_id, after_send=True)
        if result != signed_payload.signatures[0]:
            raise SubmissionError(
                SubmissionErrorCode.IDENTITY_MISMATCH,
                ErrorDisposition.AMBIGUOUS,
                "RPC acknowledgement signature differs from signed payload",
            )
        return SubmissionAck(
            SubmissionState.ACCEPTED,
            TransportKind.RPC,
            request_id,
            signed_payload.signatures,
            None,
            int(self.clock_ns()),
        )


class JitoSender(_BaseSender):
    def __init__(
        self,
        base_url: str,
        http: AsyncJsonHttpTransport,
        issuer: LivePermitIssuer,
        *,
        auth: JitoUuidAuth | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        super().__init__(http, issuer, clock_ns=clock_ns)
        self.base_url = _validate_jito_base(base_url)
        self.auth = auth
        if issuer.policy.require_jito_uuid_auth and auth is None:
            raise SubmissionError(
                SubmissionErrorCode.AUTH_INVALID,
                ErrorDisposition.FATAL,
                "Jito UUID authentication is required by policy",
            )

    async def submit(
        self,
        permit: SubmissionPermit,
        signed_payload: SignedPayload,
        message_hash: str,
    ) -> SubmissionAck:
        if permit.transport is TransportKind.JITO_SINGLE:
            return await self._submit_single(permit, signed_payload, message_hash)
        if permit.transport is TransportKind.JITO_BUNDLE:
            return await self._submit_bundle(permit, signed_payload, message_hash)
        raise SubmissionError(
            SubmissionErrorCode.PERMIT_INVALID,
            ErrorDisposition.FATAL,
            "Jito sender received a non-Jito permit",
        )

    def _headers(self) -> Mapping[str, str]:
        headers = {"content-type": "application/json"}
        if self.auth:
            headers.update(self.auth.headers())
        return headers

    def _require_tip(self, permit: SubmissionPermit, payload: SignedPayload) -> None:
        if not permit.tip_evidence_hash or payload.tip_evidence is None:
            raise SubmissionError(
                SubmissionErrorCode.TIP_POLICY_INVALID,
                ErrorDisposition.FATAL,
                "Jito submission requires bound exactly-one-tip evidence",
            )
        if payload.tip_evidence.instruction_count != 1:
            raise SubmissionError(
                SubmissionErrorCode.TIP_POLICY_INVALID,
                ErrorDisposition.FATAL,
                "Jito submission must contain exactly one tip",
            )

    async def _submit_single(
        self,
        permit: SubmissionPermit,
        payload: SignedPayload,
        message_hash: str,
    ) -> SubmissionAck:
        self._prepare(permit, payload, message_hash, TransportKind.JITO_SINGLE)
        self._require_tip(permit, payload)
        if len(payload.transactions) != 1:
            raise SubmissionError(
                SubmissionErrorCode.PAYLOAD_INVALID,
                ErrorDisposition.FATAL,
                "Jito single sender accepts exactly one transaction",
            )
        request_id = str(uuid4())
        query = {"bundleOnly": "true"} if self.issuer.policy.jito_bundle_only else {}
        url = _with_path(self.base_url, "/api/v1/transactions", query)
        body: Mapping[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(payload.transactions[0]).decode("ascii"),
                {"encoding": "base64"},
            ],
        }
        response = await self._post(url, body, self._headers())
        result = _unwrap_json_rpc(response, request_id, after_send=True)
        if result != payload.signatures[0]:
            raise SubmissionError(
                SubmissionErrorCode.IDENTITY_MISMATCH,
                ErrorDisposition.AMBIGUOUS,
                "Jito acknowledgement signature differs from signed payload",
            )
        bundle_id = _header(response.headers, "x-bundle-id")
        if bundle_id is not None and not _valid_bundle_id(bundle_id):
            raise SubmissionError(
                SubmissionErrorCode.MALFORMED_RESPONSE,
                ErrorDisposition.AMBIGUOUS,
                "Jito x-bundle-id header is malformed",
            )
        return SubmissionAck(
            SubmissionState.ACCEPTED,
            TransportKind.JITO_SINGLE,
            request_id,
            payload.signatures,
            bundle_id,
            int(self.clock_ns()),
        )

    async def _submit_bundle(
        self,
        permit: SubmissionPermit,
        payload: SignedPayload,
        message_hash: str,
    ) -> SubmissionAck:
        self._prepare(permit, payload, message_hash, TransportKind.JITO_BUNDLE)
        self._require_tip(permit, payload)
        request_id = str(uuid4())
        url = _with_path(self.base_url, "/api/v1/bundles")
        encoded = [
            base64.b64encode(raw).decode("ascii") for raw in payload.transactions
        ]
        body: Mapping[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "sendBundle",
            "params": [encoded, {"encoding": "base64"}],
        }
        response = await self._post(url, body, self._headers())
        result = _unwrap_json_rpc(response, request_id, after_send=True)
        if not isinstance(result, str) or not _valid_bundle_id(result):
            raise SubmissionError(
                SubmissionErrorCode.MALFORMED_RESPONSE,
                ErrorDisposition.AMBIGUOUS,
                "Jito bundle acknowledgement lacks a valid bundle id",
            )
        return SubmissionAck(
            SubmissionState.ACCEPTED,
            TransportKind.JITO_BUNDLE,
            request_id,
            payload.signatures,
            result,
            int(self.clock_ns()),
        )


@dataclass(frozen=True, slots=True)
class TipAccountSnapshot:
    accounts: frozenset[str]
    response_hash: str
    observed_at_ns: int

    def __post_init__(self) -> None:
        if not self.accounts:
            raise ValueError("tip account snapshot cannot be empty")
        _require_hash(self.response_hash, "tip account response hash")


class SubmissionStatusClient:
    """Bounded official RPC/Jito status and tip-account polling client."""

    def __init__(
        self,
        http: AsyncJsonHttpTransport,
        *,
        rpc_endpoint: str,
        jito_base_url: str | None = None,
        jito_auth: JitoUuidAuth | None = None,
        timeout_seconds: float = 8.0,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.http = http
        self.rpc_endpoint = _validate_https_endpoint(rpc_endpoint)
        self.jito_base_url = (
            _validate_jito_base(jito_base_url) if jito_base_url is not None else None
        )
        self.jito_auth = jito_auth
        self.timeout_seconds = timeout_seconds
        self.clock_ns = clock_ns

    async def signature_statuses(
        self,
        ack: SubmissionAck,
        *,
        current_block_height: int,
        last_valid_block_height: int,
    ) -> SubmissionObservation:
        request_id = str(uuid4())
        body: Mapping[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "getSignatureStatuses",
            "params": [
                list(ack.transaction_signatures),
                {"searchTransactionHistory": True},
            ],
        }
        result = await self._call(
            self.rpc_endpoint,
            body,
            {"content-type": "application/json"},
            request_id,
        )
        return classify_signature_statuses(
            {"result": result},
            expected_signatures=ack.transaction_signatures,
            current_block_height=current_block_height,
            last_valid_block_height=last_valid_block_height,
            observed_at_ns=int(self.clock_ns()),
        )

    async def jito_inflight_status(
        self,
        ack: SubmissionAck,
    ) -> SubmissionObservation:
        bundle_id = self._require_bundle(ack)
        result = await self._jito_call(
            "/api/v1/getInflightBundleStatuses",
            "getInflightBundleStatuses",
            [[bundle_id]],
        )
        return classify_jito_inflight_status(
            {"result": result},
            bundle_id=bundle_id,
            observed_at_ns=int(self.clock_ns()),
        )

    async def jito_bundle_status(
        self,
        ack: SubmissionAck,
    ) -> SubmissionObservation:
        bundle_id = self._require_bundle(ack)
        result = await self._jito_call(
            "/api/v1/getBundleStatuses",
            "getBundleStatuses",
            [[bundle_id]],
        )
        return classify_jito_bundle_status(
            {"result": result},
            bundle_id=bundle_id,
            expected_signatures=ack.transaction_signatures,
            observed_at_ns=int(self.clock_ns()),
        )

    async def jito_tip_accounts(self) -> TipAccountSnapshot:
        result = await self._jito_call(
            "/api/v1/getTipAccounts",
            "getTipAccounts",
            [],
        )
        if not isinstance(result, list) or not result:
            raise _malformed("getTipAccounts result must be a non-empty array")
        accounts: set[str] = set()
        for value in result:
            if not isinstance(value, str):
                raise _malformed("getTipAccounts entries must be strings")
            try:
                Pubkey.from_string(value)
            except Exception as exc:
                raise _malformed("getTipAccounts returned an invalid pubkey") from exc
            accounts.add(value)
        if len(accounts) != len(result):
            raise _malformed("getTipAccounts returned duplicate accounts")
        return TipAccountSnapshot(
            frozenset(accounts),
            _hash_json(result),
            int(self.clock_ns()),
        )

    async def _jito_call(
        self,
        path: str,
        method: str,
        params: list[object],
    ) -> object:
        if self.jito_base_url is None:
            raise SubmissionError(
                SubmissionErrorCode.ENDPOINT_INVALID,
                ErrorDisposition.FATAL,
                "Jito status endpoint is not configured",
            )
        request_id = str(uuid4())
        body: Mapping[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        headers = {"content-type": "application/json"}
        if self.jito_auth:
            headers.update(self.jito_auth.headers())
        return await self._call(
            _with_path(self.jito_base_url, path),
            body,
            headers,
            request_id,
        )

    async def _call(
        self,
        url: str,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request_id: str,
    ) -> object:
        try:
            response = await asyncio.wait_for(
                self.http.post_json(
                    url,
                    body,
                    headers=headers,
                    timeout_seconds=self.timeout_seconds,
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise SubmissionError(
                SubmissionErrorCode.TRANSPORT_ERROR,
                ErrorDisposition.RETRYABLE_PRE_SEND,
                "status polling timed out",
            ) from exc
        except SubmissionError:
            raise
        except Exception as exc:
            raise SubmissionError(
                SubmissionErrorCode.TRANSPORT_ERROR,
                ErrorDisposition.RETRYABLE_PRE_SEND,
                "status polling transport failed",
                {"exception_type": type(exc).__name__},
            ) from exc
        return _unwrap_json_rpc(response, request_id, after_send=False)

    @staticmethod
    def _require_bundle(ack: SubmissionAck) -> str:
        if not ack.bundle_id or not _valid_bundle_id(ack.bundle_id):
            raise SubmissionError(
                SubmissionErrorCode.IDENTITY_MISMATCH,
                ErrorDisposition.FATAL,
                "a valid bundle id is required for Jito status polling",
            )
        return ack.bundle_id


@dataclass(frozen=True, slots=True)
class SubmissionObservation:
    state: SubmissionState
    source: str
    observed_at_ns: int
    slot: int | None = None
    confirmation_status: str | None = None
    provider_status: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResubmissionDecision:
    allowed: bool
    requires_new_permit: bool
    reason: str


def classify_signature_statuses(
    raw: object,
    *,
    expected_signatures: tuple[str, ...],
    current_block_height: int,
    last_valid_block_height: int,
    observed_at_ns: int | None = None,
) -> SubmissionObservation:
    if current_block_height < 0 or last_valid_block_height < 0:
        raise ValueError("block heights must be non-negative")
    result = _rpc_result_object(raw, "getSignatureStatuses")
    context = result.get("context")
    value = result.get("value")
    if not isinstance(context, Mapping) or not isinstance(value, list):
        raise _malformed("signature status result shape is invalid")
    slot_value = context.get("slot")
    slot = (
        slot_value
        if isinstance(slot_value, int)
        and not isinstance(slot_value, bool)
        and slot_value >= 0
        else None
    )
    if len(value) != len(expected_signatures):
        raise _malformed("signature status count differs from submitted payload")
    statuses: list[str] = []
    for item in value:
        if item is None:
            statuses.append("missing")
            continue
        if not isinstance(item, Mapping):
            raise _malformed("signature status item must be object or null")
        if item.get("err") is not None:
            statuses.append("failed")
            continue
        confirmation = item.get("confirmationStatus")
        if confirmation in {"confirmed", "finalized"}:
            statuses.append(str(confirmation))
        elif confirmation == "processed":
            statuses.append("processed")
        else:
            statuses.append("unknown")
    now = int(observed_at_ns if observed_at_ns is not None else time.time_ns())
    if statuses and all(item in {"confirmed", "finalized"} for item in statuses):
        confirmation = (
            "finalized"
            if all(item == "finalized" for item in statuses)
            else "confirmed"
        )
        return SubmissionObservation(
            SubmissionState.LANDED,
            "solana.getSignatureStatuses",
            now,
            slot,
            confirmation,
            reason="all transaction signatures landed",
        )
    if any(item == "failed" for item in statuses):
        return SubmissionObservation(
            SubmissionState.FAILED,
            "solana.getSignatureStatuses",
            now,
            slot,
            reason="at least one transaction signature has an on-chain error",
        )
    if current_block_height > last_valid_block_height and all(
        item == "missing" for item in statuses
    ):
        return SubmissionObservation(
            SubmissionState.EXPIRED,
            "solana.getSignatureStatuses",
            now,
            slot,
            reason="blockhash expired and no signature was observed",
        )
    if any(item == "processed" for item in statuses):
        return SubmissionObservation(
            SubmissionState.ACCEPTED,
            "solana.getSignatureStatuses",
            now,
            slot,
            "processed",
            reason="signature observed but not yet confirmed",
        )
    return SubmissionObservation(
        SubmissionState.UNKNOWN,
        "solana.getSignatureStatuses",
        now,
        slot,
        reason="signature state is missing or indeterminate",
    )


def classify_jito_inflight_status(
    raw: object,
    *,
    bundle_id: str,
    observed_at_ns: int | None = None,
) -> SubmissionObservation:
    if not _valid_bundle_id(bundle_id):
        raise ValueError("bundle_id must be sha256 hex")
    result = _rpc_result_object(raw, "getInflightBundleStatuses")
    value = result.get("value")
    context = result.get("context")
    if value is None:
        return SubmissionObservation(
            SubmissionState.UNKNOWN,
            "jito.getInflightBundleStatuses",
            int(observed_at_ns or time.time_ns()),
            reason="bundle not found in inflight window",
        )
    if not isinstance(value, list) or not isinstance(context, Mapping):
        raise _malformed("Jito inflight result shape is invalid")
    match = _find_bundle(value, bundle_id)
    now = int(observed_at_ns or time.time_ns())
    if match is None:
        return SubmissionObservation(
            SubmissionState.UNKNOWN,
            "jito.getInflightBundleStatuses",
            now,
            reason="requested bundle id missing from response",
        )
    status = match.get("status")
    landed_slot = match.get("landed_slot")
    slot = (
        landed_slot
        if isinstance(landed_slot, int)
        and not isinstance(landed_slot, bool)
        and landed_slot >= 0
        else None
    )
    if status == "Landed":
        return SubmissionObservation(
            SubmissionState.LANDED,
            "jito.getInflightBundleStatuses",
            now,
            slot,
            provider_status="Landed",
            reason="Jito reports the bundle landed",
        )
    if status == "Pending":
        return SubmissionObservation(
            SubmissionState.ACCEPTED,
            "jito.getInflightBundleStatuses",
            now,
            provider_status="Pending",
            reason="Jito bundle remains pending",
        )
    if status in {"Failed", "Invalid"}:
        return SubmissionObservation(
            SubmissionState.UNKNOWN,
            "jito.getInflightBundleStatuses",
            now,
            provider_status=str(status),
            reason="Jito status requires signature reconciliation before retry",
        )
    raise _malformed("unknown Jito inflight status")


def classify_jito_bundle_status(
    raw: object,
    *,
    bundle_id: str,
    expected_signatures: tuple[str, ...],
    observed_at_ns: int | None = None,
) -> SubmissionObservation:
    result = _rpc_result_object(raw, "getBundleStatuses")
    value = result.get("value")
    context = result.get("context")
    now = int(observed_at_ns or time.time_ns())
    if value is None:
        return SubmissionObservation(
            SubmissionState.UNKNOWN,
            "jito.getBundleStatuses",
            now,
            reason="bundle not found in durable status response",
        )
    if not isinstance(value, list) or not isinstance(context, Mapping):
        raise _malformed("Jito bundle status result shape is invalid")
    match = _find_bundle(value, bundle_id)
    if match is None:
        return SubmissionObservation(
            SubmissionState.UNKNOWN,
            "jito.getBundleStatuses",
            now,
            reason="requested bundle id missing from response",
        )
    transactions = match.get("transactions")
    if not isinstance(transactions, list) or tuple(transactions) != expected_signatures:
        raise SubmissionError(
            SubmissionErrorCode.IDENTITY_MISMATCH,
            ErrorDisposition.FATAL,
            "Jito status transaction signatures differ from permit",
        )
    status = match.get("confirmation_status", match.get("confirmationStatus"))
    slot_value = match.get("slot")
    slot = (
        slot_value
        if isinstance(slot_value, int)
        and not isinstance(slot_value, bool)
        and slot_value >= 0
        else None
    )
    error = match.get("err")
    if _jito_error_is_ok(error) and status in {"confirmed", "finalized"}:
        return SubmissionObservation(
            SubmissionState.LANDED,
            "jito.getBundleStatuses",
            now,
            slot,
            str(status),
            provider_status=str(status),
            reason="Jito durable bundle status is landed",
        )
    return SubmissionObservation(
        SubmissionState.UNKNOWN,
        "jito.getBundleStatuses",
        now,
        slot,
        provider_status=str(status) if status is not None else None,
        reason="bundle result is not confirmed landing proof",
    )


def resubmission_decision(observation: SubmissionObservation) -> ResubmissionDecision:
    if observation.state in {
        SubmissionState.ACCEPTED,
        SubmissionState.LANDED,
        SubmissionState.UNKNOWN,
    }:
        return ResubmissionDecision(
            False,
            False,
            "accepted, landed or ambiguous state must reconcile without resend",
        )
    if observation.state is SubmissionState.EXPIRED:
        return ResubmissionDecision(
            True,
            True,
            "proven expiry permits a full rebuild with a new permit",
        )
    return ResubmissionDecision(
        True,
        True,
        "proven failure permits a reviewed rebuild with a new permit",
    )


def _unwrap_json_rpc(
    response: HttpResponse,
    request_id: str,
    *,
    after_send: bool,
) -> object:
    disposition = (
        ErrorDisposition.AMBIGUOUS
        if after_send
        else ErrorDisposition.RETRYABLE_PRE_SEND
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise SubmissionError(
            SubmissionErrorCode.TRANSPORT_ERROR,
            disposition,
            "submission endpoint returned a retryable HTTP status",
            {"http_status": response.status_code},
        )
    if not 200 <= response.status_code < 300:
        raise SubmissionError(
            SubmissionErrorCode.TRANSPORT_ERROR,
            disposition,
            "submission endpoint returned a non-success HTTP status",
            {"http_status": response.status_code},
        )
    body = response.body
    if not isinstance(body, Mapping):
        raise _malformed("JSON-RPC response must be an object", disposition)
    if body.get("jsonrpc") != "2.0" or body.get("id") != request_id:
        raise _malformed("JSON-RPC version or id mismatch", disposition)
    error = body.get("error")
    if error is not None:
        code_value = error.get("code") if isinstance(error, Mapping) else None
        rpc_code = (
            code_value
            if isinstance(code_value, int) and not isinstance(code_value, bool)
            else None
        )
        raise SubmissionError(
            SubmissionErrorCode.JSON_RPC_ERROR,
            disposition,
            "submission endpoint returned a JSON-RPC error",
            {"rpc_code": rpc_code},
        )
    if "result" not in body:
        raise _malformed("JSON-RPC result is missing", disposition)
    return body["result"]


def _rpc_result_object(raw: object, method: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise _malformed(f"{method} response must be an object")
    if raw.get("error") is not None:
        error = raw.get("error")
        code_value = error.get("code") if isinstance(error, Mapping) else None
        rpc_code = (
            code_value
            if isinstance(code_value, int) and not isinstance(code_value, bool)
            else None
        )
        raise SubmissionError(
            SubmissionErrorCode.JSON_RPC_ERROR,
            ErrorDisposition.RETRYABLE_PRE_SEND,
            f"{method} returned a JSON-RPC error",
            {"rpc_code": rpc_code},
        )
    result = raw.get("result")
    if not isinstance(result, Mapping):
        raise _malformed(f"{method} result must be an object")
    return result


def _find_bundle(
    value: list[object],
    bundle_id: str,
) -> Mapping[str, object] | None:
    for item in value:
        if not isinstance(item, Mapping):
            raise _malformed("bundle status item must be an object")
        if item.get("bundle_id") == bundle_id:
            return item
    return None


def _jito_error_is_ok(error: object) -> bool:
    if error is None:
        return True
    if isinstance(error, Mapping):
        return error.get("Ok") is None and set(error) == {"Ok"}
    return False


def _validate_https_endpoint(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise SubmissionError(
            SubmissionErrorCode.ENDPOINT_INVALID,
            ErrorDisposition.FATAL,
            "submission endpoint must be a credential-free HTTPS URL",
        )
    return value.rstrip("/")


def _validate_jito_base(value: str) -> str:
    checked = _validate_https_endpoint(value)
    parsed = urlparse(checked)
    hostname = (parsed.hostname or "").lower()
    if not _JITO_HOST_RE.fullmatch(hostname):
        raise SubmissionError(
            SubmissionErrorCode.ENDPOINT_INVALID,
            ErrorDisposition.FATAL,
            "Jito endpoint host is not allowlisted",
        )
    if parsed.path not in {"", "/"} or parsed.query:
        raise SubmissionError(
            SubmissionErrorCode.ENDPOINT_INVALID,
            ErrorDisposition.FATAL,
            "Jito base URL must not contain a path or query",
        )
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _with_path(
    base: str,
    path: str,
    query: Mapping[str, str] | None = None,
) -> str:
    parsed = urlparse(base)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            "",
            urlencode(query or {}),
            "",
        )
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return None


def _valid_bundle_id(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def _valid_signature(value: str) -> bool:
    return bool(_BASE58_SIGNATURE_RE.fullmatch(value))


def _require_hash(value: str, label: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise SubmissionError(
            SubmissionErrorCode.IDENTITY_MISMATCH,
            ErrorDisposition.FATAL,
            f"{label} must be lowercase sha256 hex",
        )


def _hash_json(value: object) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _malformed(
    message: str,
    disposition: ErrorDisposition = ErrorDisposition.RETRYABLE_PRE_SEND,
) -> SubmissionError:
    return SubmissionError(
        SubmissionErrorCode.MALFORMED_RESPONSE,
        disposition,
        message,
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "AsyncJsonHttpTransport",
    "ErrorDisposition",
    "HttpResponse",
    "JitoSender",
    "JitoUuidAuth",
    "LivePermitIssuer",
    "LiveSubmissionPolicy",
    "PermitRequest",
    "ResubmissionDecision",
    "RpcSender",
    "Sender",
    "SignedPayload",
    "SubmissionAck",
    "SubmissionError",
    "SubmissionErrorCode",
    "SubmissionObservation",
    "SubmissionPermit",
    "SubmissionState",
    "SubmissionStatusClient",
    "TipAccountSnapshot",
    "TipEvidence",
    "TransportKind",
    "classify_jito_bundle_status",
    "classify_jito_inflight_status",
    "classify_signature_statuses",
    "inspect_exactly_one_system_tip",
    "inspect_exactly_one_system_tip_across_transactions",
    "permit_request_from_payload",
    "resubmission_decision",
    "validate_permit_payload",
]
