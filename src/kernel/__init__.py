"""Dependency-light canonical serialization and hashing primitives."""

from .canonical_json import (
    CanonicalJsonError,
    canonical_json_bytes,
    canonical_json_text,
)
from .hashing import domain_sha256

__all__ = [
    "CanonicalJsonError",
    "canonical_json_bytes",
    "canonical_json_text",
    "domain_sha256",
]
