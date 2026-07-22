"""Cryptographic trust-anchor registry and signed envelope verification for PR-183.

Hash-shaped references are not signatures. The registry verifies a canonical,
domain-separated envelope against a currently valid, non-revoked trust anchor.
The default verifier uses the already-pinned ``solders`` Ed25519 implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Protocol

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")


class TrustAnchorError(ValueError):
    """Raised for malformed trust-anchor or signed-envelope metadata."""


class TrustUsage(StrEnum):
    RELEASE = "release"
    EVIDENCE = "evidence"
    OPERATOR_APPROVAL = "operator-approval"
    SIGNER_POLICY = "signer-policy"


class TrustAnchorState(StrEnum):
    STAGED = "staged"
    ACTIVE = "active"
    RETIRING = "retiring"
    REVOKED = "revoked"


class SignatureVerifier(Protocol):
    def verify(
        self,
        *,
        public_key_base58: str,
        signature_base58: str,
        message: bytes,
    ) -> bool: ...


class SoldersEd25519Verifier:
    """Verify Ed25519 signatures using the repository's pinned solders package."""

    def verify(
        self,
        *,
        public_key_base58: str,
        signature_base58: str,
        message: bytes,
    ) -> bool:
        try:
            from solders.pubkey import Pubkey
            from solders.signature import Signature

            public_key = Pubkey.from_string(public_key_base58)
            signature = Signature.from_string(signature_base58)
            return bool(signature.verify(public_key, message))
        except (ImportError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class TrustAnchor:
    key_id: str
    algorithm: str
    public_key_base58: str
    usages: tuple[TrustUsage, ...]
    issuer: str
    environment: str
    valid_from: datetime
    valid_until: datetime
    state: TrustAnchorState = TrustAnchorState.STAGED
    revoked_at: datetime | None = None
    minimum_security_level: int = 128

    def __post_init__(self) -> None:
        for label, value in (
            ("key_id", self.key_id),
            ("algorithm", self.algorithm),
            ("public_key_base58", self.public_key_base58),
            ("issuer", self.issuer),
            ("environment", self.environment),
        ):
            if not value.strip():
                raise TrustAnchorError(f"{label} is required")
        if self.algorithm != "ed25519":
            raise TrustAnchorError("only reviewed ed25519 trust anchors are supported")
        if not _BASE58_RE.fullmatch(self.public_key_base58):
            raise TrustAnchorError("trust anchor public key must be base58")
        if not self.usages:
            raise TrustAnchorError("trust anchor must declare at least one usage")
        _require_time("valid_from", self.valid_from)
        _require_time("valid_until", self.valid_until)
        if self.valid_until <= self.valid_from:
            raise TrustAnchorError("trust anchor validity window is invalid")
        if self.revoked_at is not None:
            _require_time("revoked_at", self.revoked_at)
        if self.state is TrustAnchorState.REVOKED and self.revoked_at is None:
            raise TrustAnchorError("revoked trust anchor requires revoked_at")
        if self.minimum_security_level < 128:
            raise TrustAnchorError("trust anchor security level is below policy")


@dataclass(frozen=True, slots=True)
class SignedEnvelope:
    domain: str
    schema_version: str
    environment: str
    key_id: str
    issued_at: datetime
    expires_at: datetime
    payload_sha256: str
    signature_base58: str

    def __post_init__(self) -> None:
        for label, value in (
            ("domain", self.domain),
            ("schema_version", self.schema_version),
            ("environment", self.environment),
            ("key_id", self.key_id),
            ("signature_base58", self.signature_base58),
        ):
            if not value.strip():
                raise TrustAnchorError(f"{label} is required")
        _require_time("issued_at", self.issued_at)
        _require_time("expires_at", self.expires_at)
        if self.expires_at <= self.issued_at:
            raise TrustAnchorError("signed envelope expiry must follow issuance")
        if not _SHA256_RE.fullmatch(self.payload_sha256):
            raise TrustAnchorError("payload_sha256 must be lowercase SHA-256")
        if _SHA256_RE.fullmatch(self.signature_base58.lower()):
            raise TrustAnchorError("hash-shaped reference is not a signature")
        if not _BASE58_RE.fullmatch(self.signature_base58):
            raise TrustAnchorError("signature must be base58 encoded")

    def canonical_message(self) -> bytes:
        payload = {
            "domain": self.domain,
            "environment": self.environment,
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "issued_at": self.issued_at.astimezone(timezone.utc).isoformat(),
            "key_id": self.key_id,
            "payload_sha256": self.payload_sha256,
            "schema_version": self.schema_version,
        }
        return (
            "pr183.signed-envelope.v1\0"
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class TrustVerificationResult:
    verified: bool
    key_id: str
    blockers: tuple[str, ...]
    payload_sha256: str
    registry_generation: str


class TrustAnchorRegistry:
    """Immutable registry used to verify release/evidence/operator signatures."""

    def __init__(
        self,
        anchors: tuple[TrustAnchor, ...],
        *,
        generation: str,
        verifier: SignatureVerifier | None = None,
    ) -> None:
        if not generation.strip():
            raise TrustAnchorError("trust anchor registry generation is required")
        by_id = {anchor.key_id: anchor for anchor in anchors}
        if len(by_id) != len(anchors):
            raise TrustAnchorError("duplicate trust anchor key_id")
        self._anchors: Mapping[str, TrustAnchor] = by_id
        self.generation = generation
        self._verifier = verifier or SoldersEd25519Verifier()

    @property
    def anchors(self) -> tuple[TrustAnchor, ...]:
        return tuple(self._anchors.values())

    def verify(
        self,
        envelope: SignedEnvelope,
        payload: bytes,
        *,
        usage: TrustUsage,
        evaluated_at: datetime,
        expected_domain: str,
        expected_environment: str,
    ) -> TrustVerificationResult:
        _require_time("evaluated_at", evaluated_at)
        blockers: list[str] = []
        observed_payload_hash = hashlib.sha256(payload).hexdigest()
        anchor = self._anchors.get(envelope.key_id)

        if envelope.domain != expected_domain:
            blockers.append("SIGNED_DOMAIN_MISMATCH")
        if envelope.environment != expected_environment:
            blockers.append("SIGNED_ENVIRONMENT_MISMATCH")
        if envelope.payload_sha256 != observed_payload_hash:
            blockers.append("SIGNED_PAYLOAD_HASH_MISMATCH")
        if not (envelope.issued_at <= evaluated_at < envelope.expires_at):
            blockers.append("SIGNED_ENVELOPE_EXPIRED_OR_NOT_YET_VALID")
        if anchor is None:
            blockers.append("TRUST_ANCHOR_NOT_FOUND")
        else:
            if anchor.state not in {
                TrustAnchorState.ACTIVE,
                TrustAnchorState.RETIRING,
            }:
                blockers.append("TRUST_ANCHOR_NOT_ACTIVE")
            if anchor.revoked_at is not None and evaluated_at >= anchor.revoked_at:
                blockers.append("TRUST_ANCHOR_REVOKED")
            if not (anchor.valid_from <= evaluated_at < anchor.valid_until):
                blockers.append("TRUST_ANCHOR_OUTSIDE_VALIDITY")
            if usage not in anchor.usages:
                blockers.append("TRUST_ANCHOR_USAGE_NOT_ALLOWED")
            if anchor.environment != expected_environment:
                blockers.append("TRUST_ANCHOR_ENVIRONMENT_MISMATCH")
            if not blockers and not self._verifier.verify(
                public_key_base58=anchor.public_key_base58,
                signature_base58=envelope.signature_base58,
                message=envelope.canonical_message(),
            ):
                blockers.append("CRYPTOGRAPHIC_SIGNATURE_INVALID")

        unique_blockers = tuple(dict.fromkeys(blockers))
        return TrustVerificationResult(
            verified=not unique_blockers,
            key_id=envelope.key_id,
            blockers=unique_blockers,
            payload_sha256=observed_payload_hash,
            registry_generation=self.generation,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "anchors": [
                {
                    **asdict(anchor),
                    "usages": [usage.value for usage in anchor.usages],
                    "state": anchor.state.value,
                    "valid_from": anchor.valid_from.isoformat(),
                    "valid_until": anchor.valid_until.isoformat(),
                    "revoked_at": (
                        anchor.revoked_at.isoformat()
                        if anchor.revoked_at is not None
                        else None
                    ),
                }
                for anchor in self.anchors
            ],
        }


def signable_payload_bytes(payload: object) -> bytes:
    """Return deterministic JSON bytes for a release/evidence/operator payload."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _require_time(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TrustAnchorError(f"{label} must be timezone-aware")


__all__ = [
    "SignatureVerifier",
    "SignedEnvelope",
    "SoldersEd25519Verifier",
    "TrustAnchor",
    "TrustAnchorError",
    "TrustAnchorRegistry",
    "TrustAnchorState",
    "TrustUsage",
    "TrustVerificationResult",
    "signable_payload_bytes",
]
