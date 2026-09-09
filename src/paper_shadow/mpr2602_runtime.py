"""MPR-2602 sender-free prepared-plan identity helpers.

This module deliberately does not sign, submit, fund, or activate live trading.
It owns one narrow invariant: a durable terminal/replay identity must cover every
execution-relevant semantic input of an ``AtomicVerticalCandidate``.  A previous
terminal must therefore not be reusable after a route, instruction bucket, ALT,
raw-state, decoder-policy, account, fee, tip, or settlement mutation.

Acquisition-only timestamps are excluded so semantically identical provider
material can replay deterministically.  Expiry, slot, blockhash, amount, policy,
and other execution semantics remain bound.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import math
from pathlib import Path
from typing import Any

from src.kernel import canonical_json_bytes
from src.paper_shadow.atomic_vertical import AtomicVerticalCandidate

MPR2602_PREPARED_PLAN_SCHEMA = "mpr2602.prepared-plan-identity.v1"

# These fields describe when otherwise identical material was acquired.  They
# are intentionally not part of deterministic terminal replay identity.  Do
# not add expiry/deadline/slot fields here: those change executability.
_ACQUISITION_ONLY_FIELDS = frozenset(
    {
        "received_at",
        "acquired_at",
        "acquired_at_ns",
        "captured_at",
        "captured_at_ns",
    }
)


def _prepared_plan_hash(candidate: AtomicVerticalCandidate) -> str:
    """Return the canonical execution-semantic identity for ``candidate``.

    The serializer is intentionally recursive rather than maintaining a second
    hand-written shadow schema.  Every dataclass field is bound by default, so a
    newly added execution field cannot silently reuse an old terminal.  Only the
    small acquisition-only allowlist above is omitted.
    """

    if not isinstance(candidate, AtomicVerticalCandidate):
        raise TypeError("MPR2602_PREPARED_PLAN_CANDIDATE_REQUIRED")
    payload = {
        "schema": MPR2602_PREPARED_PLAN_SCHEMA,
        "candidate": _semantic_value(candidate),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def validate_prepared_plan_hash(
    candidate: AtomicVerticalCandidate,
    expected_hash: str,
) -> str:
    """Fail closed if durable/replay identity does not match the prepared plan."""

    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("MPR2602_PREPARED_PLAN_HASH_INVALID")
    try:
        int(expected_hash, 16)
    except ValueError as exc:
        raise ValueError("MPR2602_PREPARED_PLAN_HASH_INVALID") from exc
    actual = _prepared_plan_hash(candidate)
    if actual != expected_hash:
        raise ValueError("MPR2602_PREPARED_PLAN_IDENTITY_MISMATCH")
    return actual


def _semantic_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("MPR2602_NONFINITE_PLAN_VALUE")
        return value
    if isinstance(value, Enum):
        return {
            "__enum__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _semantic_value(value.value),
        }
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes_hex__": bytes(value).hex()}
    if isinstance(value, Path):
        return {"__path__": str(value)}

    # solders Instruction / AccountMeta need privilege-preserving encoding.
    if _looks_like_instruction(value):
        return {
            "__instruction__": f"{type(value).__module__}.{type(value).__qualname__}",
            "program_id": str(value.program_id),
            "accounts": [_semantic_account_meta(item) for item in value.accounts],
            "data": bytes(value.data).hex(),
        }
    if _looks_like_account_meta(value):
        return _semantic_account_meta(value)

    if is_dataclass(value) and not isinstance(value, type):
        encoded: dict[str, Any] = {
            "__type__": f"{type(value).__module__}.{type(value).__qualname__}"
        }
        for field in fields(value):
            if field.name in _ACQUISITION_ONLY_FIELDS:
                continue
            encoded[field.name] = _semantic_value(getattr(value, field.name))
        return encoded

    if isinstance(value, Mapping):
        encoded_items = [
            (_semantic_mapping_key(key), _semantic_value(item))
            for key, item in value.items()
        ]
        encoded_items.sort(key=lambda pair: canonical_json_bytes(pair[0]))
        return {"__mapping__": encoded_items}

    if isinstance(value, Set):
        encoded = [_semantic_value(item) for item in value]
        encoded.sort(key=canonical_json_bytes)
        return {"__set__": encoded}

    if isinstance(value, Sequence):
        return [_semantic_value(item) for item in value]

    # Pubkey, Hash, Signature and other solders value objects have stable string
    # forms.  Instructions/metas were handled above so privileges are not lost.
    if type(value).__module__.startswith("solders."):
        return {
            "__solders__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": str(value),
        }

    # A small fail-closed structural fallback supports immutable repository value
    # objects that use slots instead of dataclasses.  Callables/private caches are
    # never serialized into execution identity.
    slot_names = getattr(type(value), "__slots__", ())
    if isinstance(slot_names, str):
        slot_names = (slot_names,)
    public_slots = tuple(
        name
        for name in slot_names
        if isinstance(name, str)
        and not name.startswith("_")
        and name not in _ACQUISITION_ONLY_FIELDS
        and hasattr(value, name)
    )
    if public_slots:
        return {
            "__type__": f"{type(value).__module__}.{type(value).__qualname__}",
            "slots": {
                name: _semantic_value(getattr(value, name)) for name in public_slots
            },
        }

    state = getattr(value, "__dict__", None)
    if isinstance(state, Mapping):
        public_state = {
            str(key): item
            for key, item in state.items()
            if not str(key).startswith("_")
            and str(key) not in _ACQUISITION_ONLY_FIELDS
            and not callable(item)
        }
        return {
            "__type__": f"{type(value).__module__}.{type(value).__qualname__}",
            "state": _semantic_value(public_state),
        }

    raise TypeError(
        "MPR2602_UNSUPPORTED_PLAN_VALUE:"
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _semantic_mapping_key(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Enum):
        return _semantic_value(value)
    if type(value).__module__.startswith("solders."):
        return str(value)
    raise TypeError("MPR2602_UNSUPPORTED_PLAN_MAPPING_KEY")


def _looks_like_instruction(value: Any) -> bool:
    return all(hasattr(value, name) for name in ("program_id", "accounts", "data"))


def _looks_like_account_meta(value: Any) -> bool:
    return all(
        hasattr(value, name)
        for name in ("pubkey", "is_signer", "is_writable")
    )


def _semantic_account_meta(value: Any) -> dict[str, Any]:
    return {
        "pubkey": str(value.pubkey),
        "is_signer": bool(value.is_signer),
        "is_writable": bool(value.is_writable),
    }


__all__ = [
    "MPR2602_PREPARED_PLAN_SCHEMA",
    "_prepared_plan_hash",
    "validate_prepared_plan_hash",
]
