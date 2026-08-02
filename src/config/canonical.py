"""Domain-separated canonical JSON identities for configuration activation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.kernel import canonical_json_bytes as _kernel_canonical_json_bytes


class CanonicalizationError(ValueError):
    pass


def to_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            name: to_json_value(getattr(value, name))
            for name in type(value).model_fields
        }
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("non-finite numbers are forbidden")
        return format(value, ".17g")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical object keys must be strings")
            if key in result:
                raise CanonicalizationError(f"duplicate canonical key: {key}")
            result[key] = to_json_value(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    raise CanonicalizationError(f"unsupported canonical type: {type(value).__name__}")


def canonical_envelope(
    payload: Any,
    *,
    domain: str,
    schema_version: str,
    environment: str,
    serialization_version: str = "pr190.canonical-json.v1",
) -> dict[str, Any]:
    if not all(
        isinstance(item, str) and item for item in (domain, schema_version, environment)
    ):
        raise CanonicalizationError(
            "domain, schema_version and environment are required"
        )
    return {
        "serialization_version": serialization_version,
        "domain": domain,
        "schema_version": schema_version,
        "environment": environment,
        "payload": to_json_value(payload),
    }


def canonical_config_json_bytes(payload: Any, **envelope: str) -> bytes:
    """Normalize configuration values, then use the kernel JSON encoder."""

    wrapped = canonical_envelope(payload, **envelope)
    return _kernel_canonical_json_bytes(wrapped)


canonical_json_bytes = canonical_config_json_bytes


def canonical_digest(payload: Any, **envelope: str) -> str:
    return hashlib.sha256(canonical_json_bytes(payload, **envelope)).hexdigest()


__all__ = [
    "CanonicalizationError",
    "canonical_config_json_bytes",
    "canonical_digest",
    "canonical_envelope",
    "canonical_json_bytes",
    "to_json_value",
]
