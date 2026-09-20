"""Shared validation and hashing primitives for rooted runtime truth."""

from __future__ import annotations

from enum import StrEnum
import re

from src.kernel import canonical_json_bytes, domain_sha256

ROOTED_TRUTH_SCHEMA_ID = "mpr-sys-01.rooted-runtime-truth.v1"
ROOTED_TRUTH_EVIDENCE_SCHEMA_ID = "mpr-sys-01.rooted-runtime-truth-evidence.v1"
ROOTED_TRUTH_POLICY_SCHEMA_ID = "mpr-sys-01.rooted-runtime-policy.v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")


class RootedTruthError(ValueError):
    """Raised when rooted observations are inconsistent or unsafe."""


class AdmissionState(StrEnum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    REVOKED = "revoked"


def text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RootedTruthError(f"{name} must be normalized and non-empty")
    return value


def integer(value: int, name: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        kind = "positive" if positive else "non-negative"
        raise RootedTruthError(f"{name} must be {kind}")
    return value


def sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise RootedTruthError(f"{name} must be lowercase SHA-256")
    return value


def digest(domain: str, schema_id: str, payload: object) -> str:
    return domain_sha256(
        domain=domain,
        schema_id=schema_id,
        payload=canonical_json_bytes(payload),
    )
