"""Signer-boundary policy for unsigned transaction messages.

This module deliberately does not sign. It creates an auditable permit only
after the unsigned message and signer reference pass policy checks. A later
signing adapter can require this permit before touching isolated key material.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable
import time

from .secret_scan import PlaintextKeyMaterialError, assert_no_plaintext_key_material


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
    """Redacted permit proving that policy ran before signing."""

    message_sha256: str
    signer_reference_scheme: str
    program_ids: tuple[str, ...]
    issued_at: float
    max_message_bytes: int


@dataclass(frozen=True, slots=True)
class SignerPolicy:
    """Fail-closed policy for unsigned message handoff to an isolated signer."""

    allowed_program_ids: frozenset[str]
    allowed_signer_reference_schemes: frozenset[str] = frozenset(
        {"env", "file", "keychain"}
    )
    max_message_bytes: int = 1232

    def evaluate(
        self,
        *,
        unsigned_message: UnsignedMessage,
        signer_reference: str,
        expected_message_sha256: str | None = None,
        now: float | None = None,
    ) -> SignerPolicyPermit:
        """Return a permit only when every signer-boundary check passes."""

        self._validate_signer_reference(signer_reference)
        self._validate_unsigned_message(unsigned_message, expected_message_sha256)
        scheme = signer_reference.split(":", 1)[0]
        return SignerPolicyPermit(
            message_sha256=unsigned_message.message_sha256,
            signer_reference_scheme=scheme,
            program_ids=tuple(sorted(set(unsigned_message.program_ids))),
            issued_at=time.time() if now is None else now,
            max_message_bytes=self.max_message_bytes,
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


def build_signer_policy(allowed_program_ids: Iterable[str]) -> SignerPolicy:
    """Build a normalized signer policy from an allowlist iterable."""

    normalized = frozenset(str(program_id) for program_id in allowed_program_ids)
    if not normalized:
        raise SignerPolicyError("signer policy requires at least one allowed program")
    return SignerPolicy(allowed_program_ids=normalized)
