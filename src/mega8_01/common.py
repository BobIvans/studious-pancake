"""Shared deterministic, signer-free primitives for MEGA8-01.

This package is an offline evidence/qualification layer.  It deliberately has no
network, signer, submission, wallet, or capital authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class Disposition(StrEnum):
    PASS = "PASS"
    REJECT = "REJECT"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


FAIL_CLOSED_REASONS = frozenset(
    {
        "STALE_EVIDENCE",
        "IDENTITY_MISMATCH",
        "UNSUPPORTED_VERSION",
        "INCONSISTENT_STATE",
        "BUDGET_EXCEEDED",
        "INSUFFICIENT_EVIDENCE",
        "TEMPORALLY_AMBIGUOUS",
        "MALFORMED_INPUT",
        "QUARANTINED_SOURCE",
    }
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def require_non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def require_positive_int(value: object, name: str) -> int:
    checked = require_non_negative_int(value, name)
    if checked == 0:
        raise ValueError(f"{name} must be a positive integer")
    return checked


def require_sha256(value: object, name: str) -> str:
    checked = require_text(value, name).lower()
    if not _SHA256_RE.fullmatch(checked) or checked == "0" * 64:
        raise ValueError(f"{name} must be a non-placeholder sha256")
    return checked


def require_git_sha(value: object, name: str = "git_sha") -> str:
    checked = require_text(value, name).lower()
    if not _GIT_SHA_RE.fullmatch(checked) or checked == "0" * 40:
        raise ValueError(f"{name} must be a non-placeholder full git sha")
    return checked


def bounded_ratio(numerator: int, denominator: int) -> float:
    require_non_negative_int(numerator, "numerator")
    require_non_negative_int(denominator, "denominator")
    if denominator == 0:
        return 0.0
    return min(1.0, max(0.0, numerator / denominator))


def sorted_unique(values: Sequence[str]) -> tuple[str, ...]:
    checked = tuple(require_text(value, "value") for value in values)
    return tuple(sorted(set(checked)))


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    child: str
    nf: str
    action: str
    subject_id: str
    disposition: Disposition
    reason: str
    payload: Mapping[str, object]
    valid_from_ms: int
    valid_until_ms: int

    def __post_init__(self) -> None:
        require_text(self.child, "child")
        require_text(self.nf, "nf")
        require_text(self.action, "action")
        require_text(self.subject_id, "subject_id")
        require_text(self.reason, "reason")
        require_non_negative_int(self.valid_from_ms, "valid_from_ms")
        require_non_negative_int(self.valid_until_ms, "valid_until_ms")
        if self.valid_until_ms < self.valid_from_ms:
            raise ValueError("valid_until_ms must not precede valid_from_ms")
        canonical_json(dict(self.payload))

    @property
    def content_hash(self) -> str:
        return canonical_hash(
            {
                "child": self.child,
                "nf": self.nf,
                "action": self.action,
                "subject_id": self.subject_id,
                "disposition": self.disposition.value,
                "reason": self.reason,
                "payload": dict(self.payload),
                "valid_from_ms": self.valid_from_ms,
                "valid_until_ms": self.valid_until_ms,
            }
        )


def artifact(
    *,
    child: str,
    nf: str,
    action: str,
    subject_id: str,
    payload: Mapping[str, object],
    valid_from_ms: int = 0,
    valid_until_ms: int = 0,
    disposition: Disposition = Disposition.PASS,
    reason: str = "OK",
) -> EvidenceArtifact:
    return EvidenceArtifact(
        child=child,
        nf=nf,
        action=action,
        subject_id=subject_id,
        disposition=disposition,
        reason=reason,
        payload=dict(payload),
        valid_from_ms=valid_from_ms,
        valid_until_ms=valid_until_ms,
    )


def fail_closed(
    *,
    child: str,
    nf: str,
    action: str,
    subject_id: str,
    reason: str,
    payload: Mapping[str, object] | None = None,
    valid_from_ms: int = 0,
    valid_until_ms: int = 0,
) -> EvidenceArtifact:
    checked_reason = require_text(reason, "reason")
    disposition = (
        Disposition.BLOCKED
        if checked_reason in FAIL_CLOSED_REASONS
        else Disposition.REJECT
    )
    return artifact(
        child=child,
        nf=nf,
        action=action,
        subject_id=subject_id,
        disposition=disposition,
        reason=checked_reason,
        payload={} if payload is None else payload,
        valid_from_ms=valid_from_ms,
        valid_until_ms=valid_until_ms,
    )
