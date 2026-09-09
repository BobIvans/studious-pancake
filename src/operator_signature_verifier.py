"""Detached SSH signature verification for MPR-2603 operator decisions.

The verifier is deliberately sender-free and verification-only.  It never loads
operator private keys, an ssh-agent, trading credentials, or wallet material.
The trust registry is reviewed public material and the verifier executes
``ssh-keygen -Y verify`` with a fixed namespace, fixed argument shape,
``shell=False``, a bounded timeout, and a sanitized environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping

from src.human_intervention import VerifiedApproval

SSH_OPERATOR_NAMESPACE = "studious-pancake/operator-intervention/v1"
REGISTRY_SCHEMA_VERSION = "mpr2603.operator-trust-registry.v1"
DECISION_SCHEMA_VERSION = "mpr2603.operator-decision.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KEY_PREFIXES = ("ssh-ed25519 ", "sk-ssh-ed25519@openssh.com ")


class OperatorVerificationError(ValueError):
    """Fail-closed operator signature verification error."""


@dataclass(frozen=True, slots=True)
class EnrolledPrincipal:
    principal_id: str
    subject_id: str
    credential_id: str
    roles: tuple[str, ...]
    public_key: str
    active: bool = True

    def __post_init__(self) -> None:
        for name in ("principal_id", "subject_id", "credential_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise OperatorVerificationError(f"{name} is required")
        if not self.roles or any(not role.strip() for role in self.roles):
            raise OperatorVerificationError("at least one non-empty role is required")
        if not self.public_key.startswith(_ALLOWED_KEY_PREFIXES):
            raise OperatorVerificationError("unsupported SSH public-key algorithm")
        if "\n" in self.public_key or "\r" in self.public_key:
            raise OperatorVerificationError("public key must be one line")


@dataclass(frozen=True, slots=True)
class OperatorTrustRegistry:
    trust_epoch: str
    principals: tuple[EnrolledPrincipal, ...]
    schema_version: str = REGISTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_SCHEMA_VERSION:
            raise OperatorVerificationError("unsupported registry schema")
        _require_sha256(self.trust_epoch, "trust_epoch")
        if not self.principals:
            raise OperatorVerificationError("registry must enroll at least one principal")
        principal_ids = [item.principal_id for item in self.principals]
        credential_ids = [item.credential_id for item in self.principals]
        if len(set(principal_ids)) != len(principal_ids):
            raise OperatorVerificationError("duplicate principal_id")
        if len(set(credential_ids)) != len(credential_ids):
            raise OperatorVerificationError("duplicate credential_id")

    def by_principal(self, principal_id: str) -> EnrolledPrincipal:
        for principal in self.principals:
            if principal.principal_id == principal_id:
                return principal
        raise OperatorVerificationError("MPR2603_UNKNOWN_PRINCIPAL")

    @classmethod
    def from_json_bytes(cls, raw: bytes, *, max_bytes: int = 64 * 1024) -> "OperatorTrustRegistry":
        if len(raw) > max_bytes:
            raise OperatorVerificationError("registry exceeds size limit")
        payload = _strict_json_object(raw)
        allowed = {"schema_version", "trust_epoch", "principals"}
        if set(payload) != allowed:
            raise OperatorVerificationError("registry fields do not match schema")
        items = payload["principals"]
        if not isinstance(items, list) or not items:
            raise OperatorVerificationError("principals must be a non-empty list")
        principals: list[EnrolledPrincipal] = []
        for item in items:
            if not isinstance(item, Mapping):
                raise OperatorVerificationError("principal entry must be an object")
            expected = {
                "principal_id",
                "subject_id",
                "credential_id",
                "roles",
                "public_key",
                "active",
            }
            if set(item) != expected:
                raise OperatorVerificationError("principal fields do not match schema")
            roles = item["roles"]
            if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
                raise OperatorVerificationError("roles must be strings")
            if type(item["active"]) is not bool:
                raise OperatorVerificationError("active must be boolean")
            principals.append(
                EnrolledPrincipal(
                    principal_id=_required_string(item["principal_id"], "principal_id"),
                    subject_id=_required_string(item["subject_id"], "subject_id"),
                    credential_id=_required_string(item["credential_id"], "credential_id"),
                    roles=tuple(roles),
                    public_key=_required_string(item["public_key"], "public_key"),
                    active=item["active"],
                )
            )
        return cls(
            trust_epoch=_required_string(payload["trust_epoch"], "trust_epoch"),
            principals=tuple(principals),
            schema_version=_required_string(payload["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class SignedOperatorDecision:
    request_hash: str
    decision: str
    principal_id: str
    credential_id: str
    signed_at_utc: str
    expires_at_utc: str
    nonce: str
    trust_epoch: str
    namespace: str = SSH_OPERATOR_NAMESPACE
    schema_version: str = DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DECISION_SCHEMA_VERSION:
            raise OperatorVerificationError("unsupported decision schema")
        if self.namespace != SSH_OPERATOR_NAMESPACE:
            raise OperatorVerificationError("operator namespace mismatch")
        _require_sha256(self.request_hash, "request_hash")
        _require_sha256(self.trust_epoch, "trust_epoch")
        if self.decision not in {"APPROVE", "REJECT"}:
            raise OperatorVerificationError("decision must be APPROVE or REJECT")
        for name in ("principal_id", "credential_id", "nonce"):
            _required_string(getattr(self, name), name)
        start = _parse_utc(self.signed_at_utc)
        end = _parse_utc(self.expires_at_utc)
        if end <= start:
            raise OperatorVerificationError("decision expiry must follow signed time")

    def canonical_bytes(self) -> bytes:
        payload = {
            "credential_id": self.credential_id,
            "decision": self.decision,
            "expires_at_utc": self.expires_at_utc,
            "namespace": self.namespace,
            "nonce": self.nonce,
            "principal_id": self.principal_id,
            "request_hash": self.request_hash,
            "schema_version": self.schema_version,
            "signed_at_utc": self.signed_at_utc,
            "trust_epoch": self.trust_epoch,
        }
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")


class SSHOperatorVerifier:
    """Real OpenSSH detached-signature verification adapter."""

    def __init__(
        self,
        registry: OperatorTrustRegistry,
        *,
        ssh_keygen_path: str = "ssh-keygen",
        timeout_seconds: float = 3.0,
    ) -> None:
        if not ssh_keygen_path or any(ch in ssh_keygen_path for ch in "\r\n\x00"):
            raise OperatorVerificationError("invalid ssh-keygen path")
        if timeout_seconds <= 0 or timeout_seconds > 10:
            raise OperatorVerificationError("verification timeout outside allowed range")
        self.registry = registry
        self.ssh_keygen_path = ssh_keygen_path
        self.timeout_seconds = timeout_seconds

    def verify(
        self,
        decision: SignedOperatorDecision,
        *,
        signature: bytes,
        current_utc: str,
        required_roles: frozenset[str] | None = None,
    ) -> VerifiedApproval:
        if not signature or len(signature) > 32 * 1024:
            raise OperatorVerificationError("signature missing or too large")
        if decision.trust_epoch != self.registry.trust_epoch:
            raise OperatorVerificationError("MPR2603_TRUST_EPOCH_CHANGED")
        principal = self.registry.by_principal(decision.principal_id)
        if not principal.active:
            raise OperatorVerificationError("MPR2603_PRINCIPAL_REVOKED")
        if principal.credential_id != decision.credential_id:
            raise OperatorVerificationError("MPR2603_CREDENTIAL_MISMATCH")
        if required_roles and not required_roles.intersection(principal.roles):
            raise OperatorVerificationError("MPR2603_REQUIRED_ROLE_MISSING")
        now = _parse_utc(current_utc)
        signed_at = _parse_utc(decision.signed_at_utc)
        expires = _parse_utc(decision.expires_at_utc)
        if now < signed_at or now >= expires:
            raise OperatorVerificationError("MPR2603_DECISION_OUTSIDE_VALIDITY")

        canonical = decision.canonical_bytes()
        allowed_line = f"{decision.principal_id} {principal.public_key}\n"
        with tempfile.TemporaryDirectory(prefix="mpr2603-verify-") as tmpdir:
            root = Path(tmpdir)
            allowed_path = root / "allowed_signers"
            signature_path = root / "decision.sig"
            allowed_path.write_text(allowed_line, encoding="utf-8")
            signature_path.write_bytes(signature)
            try:
                result = subprocess.run(
                    [
                        self.ssh_keygen_path,
                        "-Y",
                        "verify",
                        "-f",
                        str(allowed_path),
                        "-I",
                        decision.principal_id,
                        "-n",
                        SSH_OPERATOR_NAMESPACE,
                        "-s",
                        str(signature_path),
                    ],
                    input=canonical,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    timeout=self.timeout_seconds,
                    check=False,
                    env={"PATH": "/usr/bin:/bin"},
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                raise OperatorVerificationError("MPR2603_VERIFIER_UNAVAILABLE") from exc
        if result.returncode != 0:
            raise OperatorVerificationError("MPR2603_SIGNATURE_INVALID")
        return VerifiedApproval(
            principal_id=principal.subject_id,
            credential_id=principal.credential_id,
            request_hash=decision.request_hash,
            decision=decision.decision,
            verified_payload_hash=hashlib.sha256(canonical).hexdigest(),
            trust_epoch=decision.trust_epoch,
            valid_from_utc=decision.signed_at_utc,
            expires_at_utc=decision.expires_at_utc,
        )


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise OperatorVerificationError(f"invalid JSON constant {value}")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise OperatorVerificationError(f"duplicate JSON key {key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorVerificationError("invalid registry JSON") from exc
    if not isinstance(decoded, dict):
        raise OperatorVerificationError("registry must be a JSON object")
    return decoded


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperatorVerificationError(f"{field_name} is required")
    if "\x00" in value:
        raise OperatorVerificationError(f"{field_name} contains NUL")
    return value


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OperatorVerificationError("timestamp must use UTC Z format")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperatorVerificationError("invalid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise OperatorVerificationError(f"{field_name} must be a non-placeholder sha256")
    return value
