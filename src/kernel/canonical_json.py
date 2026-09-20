"""Deterministic JSON serialization for identity and evidence payloads."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import math
from typing import Mapping, Sequence, TypeAlias

JsonScalar: TypeAlias = None | bool | int | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class CanonicalJsonError(ValueError):
    """A value cannot be represented by the canonical JSON contract."""


def _convert(value: object, *, depth: int = 0) -> JsonValue:
    if depth > 64:
        raise CanonicalJsonError("canonical JSON nesting exceeds 64 levels")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError("non-finite numbers are forbidden")
        raise CanonicalJsonError("floating-point values are forbidden")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalJsonError("non-finite decimals are forbidden")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalJsonError("naive datetimes are forbidden")
        utc_value = value.astimezone(timezone.utc)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _convert(value.value, depth=depth + 1)
    if is_dataclass(value) and not isinstance(value, type):
        return _convert(asdict(value), depth=depth + 1)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJsonError("canonical JSON object keys must be strings")
            if key in result:
                raise CanonicalJsonError("duplicate canonical JSON object key")
            result[key] = _convert(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_convert(item, depth=depth + 1) for item in value]
    raise CanonicalJsonError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json_text(value: object) -> str:
    """Return deterministic compact JSON text for a supported value."""

    converted = _convert(value)
    return json.dumps(
        converted,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON bytes."""

    return canonical_json_text(value).encode("utf-8")
