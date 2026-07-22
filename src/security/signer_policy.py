"""Signer-boundary policy for unsigned transaction messages.

This module deliberately does not sign. It creates an auditable permit only
after the unsigned message and signer reference pass policy checks. PR-182 can
bind that permit to a trusted boot/time domain; permits created without a
TimeAuthority remain review-only and cannot satisfy clock-safe live issuance.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable
import time

from src.time_authority import PersistedExpiry, TimeAuthority

from .secret_scan import (
    PlaintextKeyMaterialError,
    assert_no_plaintext_key_material,
)


class SignerPolicyError(ValueError):
    """Raised when an unsigned message must not reach a signer."""


@dataclass(frozen=True, slots=True)
class UnsignedMessage:
    """Minimal unsigned-message evidence evaluated before signing."""

    message_bytes: bytes
    program_ids: tuple[str, ...]
    payer: str | None = None
    min_context_slot: int | None = None

    @property
    def message_sha256(self) -> str:
        return sha256(self.message_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class SignerPolicyPermit:
    """Redacted permit proving that policy ran before signing.

    The original fields remain for compatibility. PR-182 fields are populated
    only when the policy has a trusted TimeAuthority. A permit with
    ``clock_safe=False`` must never authorize a live signer operation.
    """

    message_sha256: str
    signer_reference_scheme: str
    program_ids: tuple[str, ...]
    issued_at: float
    max_message_bytes: int
    clock_safe: bool = False
    boot_id: str | None = None
    process_generation: int | None = None
    issued_at_monotonic_ns: int | None = None
    expires_at_monotonic_ns: int | None = None
    expires_at_utc_ns: int | None = None


@dataclass(frozen=True, slots=True)
class SignerPolicy:
    """Fail-closed policy for unsigned message handoff to an isolated signer."""

    allowed_program_ids: frozenset[str]
    allowed_signer_reference_schemes: frozenset[str] = frozenset(
        {"env", "file", "keychain"}
    )
    max_message_bytes: int = 1232
    time_authority: TimeAuthority | None = None
    permit_ttl_ns: int = 60_000_000_000

    def __post_init__(self) -> None:
        if self.max_message_bytes <= 0:
            raise SignerPolicyError("max_message_bytes must be positive")
        if self.permit_ttl_ns <= 0:
            raise SignerPolicyError("permit_ttl_ns must be positive")

    def evaluate(
        self,
        *,
        unsigned_message: UnsignedMessage,
        signer_reference: str,
        expected_message_sha256: str | None = None,
        now: float | None = None,
    ) -> SignerPolicyPermit:
        """Return a permit only when every signer-boundary check passes.

        ``now`` is retained only for deterministic legacy/review tests. A
        trusted-time policy refuses a caller-supplied wall clock because that
        would bypass PR-182 clock ownership.
        """

        self._validate_signer_reference(signer_reference)
        self._validate_unsigned_message(unsigned_message, expected_message_sha256)
        scheme = signer_reference.split(":", 1)[0]
        if self.time_authority is None:
            return SignerPolicyPermit(
                message_sha256=unsigned_message.message_sha256,
                signer_reference_scheme=scheme,
                program_ids=tuple(sorted(set(unsigned_message.program_ids))),
                issued_at=time.time() if now is None else now,
                max_message_bytes=self.max_message_bytes,
                clock_safe=False,
            )
        if now is not None:
            raise SignerPolicyError(
                "caller-supplied wall time is forbidden with TimeAuthority"
            )
        expiry = PersistedExpiry.issue(
            self.time_authority,
            ttl_ns=self.permit_ttl_ns,
        )
        return SignerPolicyPermit(
            message_sha256=unsigned_message.message_sha256,
            signer_reference_scheme=scheme,
            program_ids=tuple(sorted(set(unsigned_message.program_ids))),
            issued_at=expiry.issued_at_utc_ns / 1_000_000_000,
            max_message_bytes=self.max_message_bytes,
            clock_safe=True,
            boot_id=expiry.boot_id,
            process_generation=expiry.process_generation,
            issued_at_monotonic_ns=expiry.issued_at_monotonic_ns,
            expires_at_monotonic_ns=expiry.expires_at_monotonic_ns,
            expires_at_utc_ns=expiry.expires_at_utc_ns,
        )

    def assert_permit_current(self, permit: SignerPolicyPermit) -> None:
        """Reject legacy, expired, cross-boot, or clock-anomalous permits."""

        if self.time_authority is None:
            raise SignerPolicyError(
                "TimeAuthority is required to validate a signer permit"
            )
        required = (
            permit.boot_id,
            permit.process_generation,
            permit.issued_at_monotonic_ns,
            permit.expires_at_monotonic_ns,
            permit.expires_at_utc_ns,
        )
        if not permit.clock_safe or any(value is None for value in required):
            raise SignerPolicyError("legacy signer permit is not clock-safe")
        assert permit.boot_id is not None
        assert permit.process_generation is not None
        assert permit.issued_at_monotonic_ns is not None
        assert permit.expires_at_monotonic_ns is not None
        assert permit.expires_at_utc_ns is not None
        expiry = PersistedExpiry(
            boot_id=permit.boot_id,
            process_generation=permit.process_generation,
            issued_at_utc_ns=int(permit.issued_at * 1_000_000_000),
            expires_at_utc_ns=permit.expires_at_utc_ns,
            issued_at_monotonic_ns=permit.issued_at_monotonic_ns,
            expires_at_monotonic_ns=permit.expires_at_monotonic_ns,
        )
        if not expiry.valid_at(self.time_authority.snapshot()):
            raise SignerPolicyError(
                "signer permit expired, crossed boot domain, or clock is unhealthy"
            )

    def _validate_signer_reference(self, signer_reference: str) -> None:
        try:
            assert_no_plaintext_key_material(
                {"signer_reference": signer_reference},
                source="signer-policy",
            )
        except PlaintextKeyMaterialError as exc:
            raise SignerPolicyError(str(exc)) from exc
        if ":" not in signer_reference:
            raise SignerPolicyError("signer reference must be structural, not inline")
        scheme, locator = signer_reference.split(":", 1)
        if scheme not in self.allowed_signer_reference_schemes:
            raise SignerPolicyError(f"signer reference scheme is not allowed: {scheme}")
        if not locator.strip():
            raise SignerPolicyError("signer reference locator is empty")

    def _validate_unsigned_message(
        self,
        unsigned_message: UnsignedMessage,
        expected_message_sha256: str | None,
    ) -> None:
        if not unsigned_message.message_bytes:
            raise SignerPolicyError("unsigned message is empty")
        if len(unsigned_message.message_bytes) > self.max_message_bytes:
            raise SignerPolicyError("unsigned message exceeds signer policy size limit")
        if expected_message_sha256 is not None:
            actual_hash = unsigned_message.message_sha256
            if actual_hash != expected_message_sha256:
                raise SignerPolicyError(
                    "unsigned message hash does not match permit input"
                )
        unknown_programs = sorted(
            set(unsigned_message.program_ids).difference(self.allowed_program_ids)
        )
        if unknown_programs:
            raise SignerPolicyError(
                "unsigned message references non-allowlisted programs: "
                + ", ".join(unknown_programs)
            )
        if unsigned_message.min_context_slot is not None and (
            unsigned_message.min_context_slot < 0
        ):
            raise SignerPolicyError("min_context_slot must not be negative")


def build_signer_policy(
    allowed_program_ids: Iterable[str],
    *,
    time_authority: TimeAuthority | None = None,
    permit_ttl_ns: int = 60_000_000_000,
) -> SignerPolicy:
    """Build a normalized signer policy from an allowlist iterable."""

    normalized = frozenset(str(program_id) for program_id in allowed_program_ids)
    if not normalized:
        raise SignerPolicyError("signer policy requires at least one allowed program")
    return SignerPolicy(
        allowed_program_ids=normalized,
        time_authority=time_authority,
        permit_ttl_ns=permit_ttl_ns,
    )
