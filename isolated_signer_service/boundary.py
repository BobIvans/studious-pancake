"""MPR-CLOSE-05 isolated signer service boundary.

The trading runtime is allowed to send only an exact message hash, redacted
policy/config identities and expiring authorization metadata.  This module
models the separate signer service that validates the envelope, writes a durable
redacted audit event before signing, denies nonce replay and signs only the exact
message bytes whose hash was approved.

No private key bytes are accepted by any public API in this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
import time
from typing import Protocol

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MIN_SIGNATURE_BYTES = 32


class SignerBoundaryFailure(StrEnum):
    BAD_HASH = "bad_hash"
    BAD_IDENTITY = "bad_identity"
    BAD_MESSAGE_BYTES = "bad_message_bytes"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    REPLAY = "replay"
    AUDIT_NOT_DURABLE = "audit_not_durable"
    BACKEND_REJECTED = "backend_rejected"


class SignerBoundaryError(ValueError):
    """Fail-closed signer boundary error with redaction-safe details."""

    def __init__(
        self,
        failure: SignerBoundaryFailure,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class SignerBoundaryRequest:
    """Exact-message authorization envelope crossing into the signer service."""

    authorization_id: str
    opportunity_id: str
    message_sha256: str
    policy_identity_hash: str
    config_generation_hash: str
    reservation_hash: str
    requester_identity_hash: str
    nonce_digest: str
    issued_at_ns: int
    not_before_ns: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        _require_non_empty(self.authorization_id, "authorization_id")
        _require_non_empty(self.opportunity_id, "opportunity_id")
        for field_name in (
            "message_sha256",
            "policy_identity_hash",
            "config_generation_hash",
            "reservation_hash",
            "requester_identity_hash",
            "nonce_digest",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        if self.issued_at_ns < 0 or self.not_before_ns < 0 or self.expires_at_ns < 0:
            raise SignerBoundaryError(
                SignerBoundaryFailure.BAD_IDENTITY,
                "authorization timestamps must be non-negative",
            )
        if self.not_before_ns < self.issued_at_ns:
            raise SignerBoundaryError(
                SignerBoundaryFailure.BAD_IDENTITY,
                "not_before_ns cannot precede issued_at_ns",
            )
        if self.expires_at_ns <= self.not_before_ns:
            raise SignerBoundaryError(
                SignerBoundaryFailure.EXPIRED,
                "expires_at_ns must be after not_before_ns",
            )

    @property
    def envelope_hash(self) -> str:
        return _hash_json(
            {
                "schema_version": "mpr-close-05.signer-boundary-request.v1",
                "authorization_id": self.authorization_id,
                "opportunity_id": self.opportunity_id,
                "message_sha256": self.message_sha256,
                "policy_identity_hash": self.policy_identity_hash,
                "config_generation_hash": self.config_generation_hash,
                "reservation_hash": self.reservation_hash,
                "requester_identity_hash": self.requester_identity_hash,
                "nonce_digest": self.nonce_digest,
                "issued_at_ns": self.issued_at_ns,
                "not_before_ns": self.not_before_ns,
                "expires_at_ns": self.expires_at_ns,
            }
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Redacted signer audit event that must be durable before signing."""

    event_id: str
    authorization_id: str
    opportunity_id: str
    message_sha256: str
    envelope_hash: str
    policy_identity_hash: str
    config_generation_hash: str
    reservation_hash: str
    nonce_digest: str
    recorded_at_ns: int

    @property
    def event_hash(self) -> str:
        return _hash_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mpr-close-05.signer-audit-event.v1",
            "event_id": self.event_id,
            "authorization_id": self.authorization_id,
            "opportunity_id": self.opportunity_id,
            "message_sha256": self.message_sha256,
            "envelope_hash": self.envelope_hash,
            "policy_identity_hash": self.policy_identity_hash,
            "config_generation_hash": self.config_generation_hash,
            "reservation_hash": self.reservation_hash,
            "nonce_digest": self.nonce_digest,
            "recorded_at_ns": self.recorded_at_ns,
        }


@dataclass(frozen=True, slots=True)
class SignatureReceipt:
    """Redacted result proving the signer signed the exact approved message."""

    authorization_id: str
    opportunity_id: str
    message_sha256: str
    signature_sha256: str
    envelope_hash: str
    audit_event_hash: str
    signed_at_ns: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mpr-close-05.signature-receipt.v1",
            "authorization_id": self.authorization_id,
            "opportunity_id": self.opportunity_id,
            "message_sha256": self.message_sha256,
            "signature_sha256": self.signature_sha256,
            "envelope_hash": self.envelope_hash,
            "audit_event_hash": self.audit_event_hash,
            "signed_at_ns": self.signed_at_ns,
        }


class SigningBackend(Protocol):
    """Signer-local backend interface.  Implementations own key material."""

    def sign_exact_message(self, message: bytes) -> bytes: ...


class NonceStore(Protocol):
    def reserve(self, nonce_digest: str) -> bool: ...


class AuditLog(Protocol):
    def append_before_signing(self, event: AuditEvent) -> bool: ...


@dataclass(slots=True)
class InMemoryNonceStore:
    """Deterministic nonce store for tests and offline verifiers."""

    _seen: set[str] = field(default_factory=set)

    def reserve(self, nonce_digest: str) -> bool:
        if nonce_digest in self._seen:
            return False
        self._seen.add(nonce_digest)
        return True


@dataclass(slots=True)
class InMemoryAuditLog:
    """Durable-enough in-process audit sink for focused unit tests."""

    events: list[AuditEvent] = field(default_factory=list)
    fail_writes: bool = False

    def append_before_signing(self, event: AuditEvent) -> bool:
        if self.fail_writes:
            return False
        self.events.append(event)
        return True


@dataclass(slots=True)
class IsolatedSignerService:
    """Signer process boundary that validates, audits, then signs."""

    backend: SigningBackend
    nonce_store: NonceStore = field(default_factory=InMemoryNonceStore)
    audit_log: AuditLog = field(default_factory=InMemoryAuditLog)
    clock_ns: Callable[[], int] = time.time_ns

    def sign_authorized_message(
        self,
        request: SignerBoundaryRequest,
        *,
        exact_message_bytes: bytes,
    ) -> SignatureReceipt:
        now = int(self.clock_ns())
        if now < request.not_before_ns:
            raise SignerBoundaryError(
                SignerBoundaryFailure.NOT_YET_VALID,
                "authorization is not yet valid",
            )
        if now >= request.expires_at_ns:
            raise SignerBoundaryError(
                SignerBoundaryFailure.EXPIRED,
                "authorization expired before signing",
            )
        message = bytes(exact_message_bytes)
        if not message:
            raise SignerBoundaryError(
                SignerBoundaryFailure.BAD_MESSAGE_BYTES,
                "exact message bytes are required",
            )
        message_hash = hashlib.sha256(message).hexdigest()
        if message_hash != request.message_sha256:
            raise SignerBoundaryError(
                SignerBoundaryFailure.BAD_MESSAGE_BYTES,
                "message bytes do not match authorized hash",
                details={"authorized_hash": request.message_sha256},
            )
        if not self.nonce_store.reserve(request.nonce_digest):
            raise SignerBoundaryError(
                SignerBoundaryFailure.REPLAY,
                "authorization nonce was already used",
            )
        audit_event = AuditEvent(
            event_id=_hash_json(
                {
                    "authorization_id": request.authorization_id,
                    "message_sha256": request.message_sha256,
                    "nonce_digest": request.nonce_digest,
                    "recorded_at_ns": now,
                }
            ),
            authorization_id=request.authorization_id,
            opportunity_id=request.opportunity_id,
            message_sha256=request.message_sha256,
            envelope_hash=request.envelope_hash,
            policy_identity_hash=request.policy_identity_hash,
            config_generation_hash=request.config_generation_hash,
            reservation_hash=request.reservation_hash,
            nonce_digest=request.nonce_digest,
            recorded_at_ns=now,
        )
        if not self.audit_log.append_before_signing(audit_event):
            raise SignerBoundaryError(
                SignerBoundaryFailure.AUDIT_NOT_DURABLE,
                "signer audit event was not durable before signing",
            )
        try:
            signature = bytes(self.backend.sign_exact_message(message))
        except Exception as exc:
            raise SignerBoundaryError(
                SignerBoundaryFailure.BACKEND_REJECTED,
                "signing backend rejected the exact message",
                details={"exception_type": type(exc).__name__},
            ) from exc
        if len(signature) < _MIN_SIGNATURE_BYTES:
            raise SignerBoundaryError(
                SignerBoundaryFailure.BACKEND_REJECTED,
                "signing backend returned an invalid signature shape",
            )
        return SignatureReceipt(
            authorization_id=request.authorization_id,
            opportunity_id=request.opportunity_id,
            message_sha256=request.message_sha256,
            signature_sha256=hashlib.sha256(signature).hexdigest(),
            envelope_hash=request.envelope_hash,
            audit_event_hash=audit_event.event_hash,
            signed_at_ns=int(self.clock_ns()),
        )


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SignerBoundaryError(
            SignerBoundaryFailure.BAD_IDENTITY,
            f"{field_name} is required",
        )


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise SignerBoundaryError(
            SignerBoundaryFailure.BAD_HASH,
            f"{field_name} must be sha256 hex",
        )
    if len(set(value)) == 1:
        raise SignerBoundaryError(
            SignerBoundaryFailure.BAD_HASH,
            f"{field_name} must not be a placeholder hash",
        )


def _hash_json(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "AuditEvent",
    "AuditLog",
    "InMemoryAuditLog",
    "InMemoryNonceStore",
    "IsolatedSignerService",
    "SignerBoundaryError",
    "SignerBoundaryFailure",
    "SignerBoundaryRequest",
    "SignatureReceipt",
    "SigningBackend",
]
