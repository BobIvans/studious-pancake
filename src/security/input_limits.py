"""Bounded JSON and binary materialization for untrusted inputs."""

from __future__ import annotations

from dataclasses import dataclass, fields
import json
from typing import Any, cast


class InputSecurityError(ValueError):
    """Untrusted input violated a declared resource or syntax policy."""


@dataclass(frozen=True, slots=True)
class InputLimits:
    max_bytes: int = 1_048_576
    max_depth: int = 32
    max_nodes: int = 100_000
    max_list_length: int = 10_000
    max_string_length: int = 65_536
    max_integer_digits: int = 78

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value <= 0:
                raise ValueError(f"{field.name} must be positive")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputSecurityError("duplicate JSON object key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise InputSecurityError(f"non-finite JSON constant is forbidden: {value}")


def _parse_int(value: str, *, limits: InputLimits) -> int:
    digits = value.lstrip("-")
    if len(digits) > limits.max_integer_digits:
        raise InputSecurityError("JSON integer exceeds digit limit")
    return int(value)


def _walk(value: Any, *, limits: InputLimits, depth: int = 0) -> int:
    if depth > limits.max_depth:
        raise InputSecurityError("JSON nesting exceeds depth limit")
    if value is None or isinstance(value, (bool, int)):
        return 1
    if isinstance(value, float):
        raise InputSecurityError("floating-point JSON numbers are forbidden")
    if isinstance(value, str):
        if len(value) > limits.max_string_length:
            raise InputSecurityError("JSON string exceeds length limit")
        return 1
    if isinstance(value, list):
        if len(value) > limits.max_list_length:
            raise InputSecurityError("JSON list exceeds length limit")
        count = 1
        for item in value:
            count += _walk(item, limits=limits, depth=depth + 1)
            if count > limits.max_nodes:
                raise InputSecurityError("JSON node count exceeds limit")
        return count
    if isinstance(value, dict):
        if len(value) > limits.max_list_length:
            raise InputSecurityError("JSON object width exceeds limit")
        count = 1
        for key, item in value.items():
            if len(key) > limits.max_string_length:
                raise InputSecurityError("JSON key exceeds length limit")
            count += 1 + _walk(item, limits=limits, depth=depth + 1)
            if count > limits.max_nodes:
                raise InputSecurityError("JSON node count exceeds limit")
        return count
    raise InputSecurityError("unsupported decoded JSON value")


def decode_bounded_json(data: bytes, *, limits: InputLimits) -> object:
    """Decode strict UTF-8 JSON while enforcing bounds and duplicate-key denial."""

    if len(data) > limits.max_bytes:
        raise InputSecurityError("input exceeds byte limit")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InputSecurityError("input is not valid UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_int=lambda raw: _parse_int(raw, limits=limits),
            parse_float=lambda _raw: (_ for _ in ()).throw(
                InputSecurityError("floating-point JSON numbers are forbidden")
            ),
        )
    except InputSecurityError:
        raise
    except json.JSONDecodeError as exc:
        raise InputSecurityError("input is not valid JSON") from exc
    _walk(value, limits=limits)
    return value


def decode_bounded_json_object(
    data: bytes, *, limits: InputLimits
) -> dict[str, object]:
    value = decode_bounded_json(data, limits=limits)
    if not isinstance(value, dict):
        raise InputSecurityError("top-level JSON value must be an object")
    return cast(dict[str, object], value)
