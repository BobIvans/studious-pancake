"""Domain-separated SHA-256 helpers."""

from __future__ import annotations

import hashlib


def _frame(value: str | bytes) -> bytes:
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    return len(raw).to_bytes(8, "big") + raw


def domain_sha256(*, domain: str, schema_id: str, payload: bytes) -> str:
    """Hash a payload with unambiguous domain and schema separation."""

    if not domain or not schema_id:
        raise ValueError("domain and schema_id are required")
    digest = hashlib.sha256()
    digest.update(b"studious-pancake-domain-sha256-v1\0")
    digest.update(_frame(domain))
    digest.update(_frame(schema_id))
    digest.update(_frame(payload))
    return digest.hexdigest()
