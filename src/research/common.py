"""Shared fail-closed primitives for AGG-14 research and product experiments.

The research package is deliberately offline/default-off.  It records evidence,
plans, benchmarks, and accounting attribution, but it never signs or submits a
transaction and never promotes itself to a live trading authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_json(domain: str, value: Any) -> str:
    require_text(domain, "domain")
    return hashlib.sha256(f"{domain}\n{stable_json(value)}".encode()).hexdigest()


def require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def require_id(value: str, field: str) -> str:
    require_text(value, field)
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} has invalid characters")
    return value


def require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase sha256")
    if value == "0" * 64:
        raise ValueError(f"{field} cannot be a placeholder digest")
    return value


def require_nonnegative(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def require_positive(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def unique_nonempty(values: Iterable[str], field: str) -> tuple[str, ...]:
    normalized = tuple(require_text(value, field).strip() for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} contains duplicates")
    return normalized


class EvidenceStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    STALE = "stale"
    CONTRADICTED = "contradicted"


class SourceKind(StrEnum):
    OFFICIAL = "official"
    PAPER = "paper"
    CODE = "code"
    DATASET = "dataset"
    AI_SUGGESTION = "ai-suggestion"


class ResearchDisposition(StrEnum):
    REQUIRED = "required"
    RESEARCH = "research"
    DEFERRED = "deferred"
    REJECTED_WITH_EVIDENCE = "rejected-with-evidence"


class ResearchOutcome(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"


class ResearchFailure(RuntimeError):
    """Typed, safe research/product failure compatible with AGG error semantics."""

    def __init__(
        self,
        code: str,
        *,
        stage: str,
        description: str,
        retryable: bool = False,
        dependency_ids: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
    ) -> None:
        self.code = require_id(code, "code")
        self.stage = require_id(stage, "stage")
        self.description = require_text(description, "description")
        self.retryable = bool(retryable)
        self.dependency_ids = unique_nonempty(dependency_ids, "dependency_id")
        self.evidence_refs = unique_nonempty(evidence_refs, "evidence_ref")
        super().__init__(f"{self.code}:{self.stage}:{self.description}")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "stage": self.stage,
            "retryable": self.retryable,
            "dependency_ids": list(self.dependency_ids),
            "evidence_refs": list(self.evidence_refs),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class EvidencePointer:
    evidence_id: str
    sha256: str
    kind: str

    def __post_init__(self) -> None:
        require_id(self.evidence_id, "evidence_id")
        require_sha256(self.sha256, "sha256")
        require_id(self.kind, "kind")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EffectBoundary:
    """Explicit capabilities for an AGG-14 operation.

    The package has no implementation capable of signing/submitting.  These
    booleans are retained in evidence so callers cannot reinterpret a research
    result as permission for a later effectful component.
    """

    local_read: bool = True
    local_build_test: bool = True
    network_read: bool = False
    remote_change: bool = False
    signing: bool = False
    submission: bool = False
    live_trading: bool = False

    def __post_init__(self) -> None:
        if self.signing or self.submission or self.live_trading:
            raise ValueError("AGG-14 research boundary cannot grant trade authority")
        if self.remote_change:
            raise ValueError("AGG-14 offline boundary cannot grant remote mutation")


OFFLINE_RESEARCH_BOUNDARY = EffectBoundary()


__all__ = [
    "EvidencePointer",
    "EvidenceStatus",
    "EffectBoundary",
    "OFFLINE_RESEARCH_BOUNDARY",
    "ResearchDisposition",
    "ResearchFailure",
    "ResearchOutcome",
    "SourceKind",
    "hash_json",
    "require_id",
    "require_nonnegative",
    "require_positive",
    "require_sha256",
    "require_text",
    "stable_json",
    "unique_nonempty",
]
