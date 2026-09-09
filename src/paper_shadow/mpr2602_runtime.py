"""MPR-2602 sender-free prepared-plan identity helpers.

Every execution-semantic dataclass field is bound by default. Only the explicit
acquisition timestamp allowlist is omitted; slots, expiry and policies remain
bound. Opaque objects are rejected rather than hashed from incomplete public
state. Schema v2 deliberately cannot reuse v1 attempt intents or terminals.
This module never signs, submits, funds, or activates live trading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import math
from pathlib import Path
import re
from typing import Any

from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.durability.unified_authority_pr02 import (
    AuthorityFence,
    UnifiedLifecycleAuthority,
)
from src.kernel import canonical_json_bytes
from src.paper_shadow.atomic_vertical import AtomicVerticalCandidate

MPR2602_PREPARED_PLAN_SCHEMA = "mpr2602.prepared-plan-identity.v2"

# Do not add expiry, deadline, slot or policy fields: they change executability.
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
    """Bind the complete candidate, rejecting opaque execution semantics.

    Dataclass fields are included recursively, including private fields. New
    fields therefore enter the identity automatically. Arbitrary callables,
    objects with __dict__, and unregistered slot objects have no sufficiently
    defined semantic encoding and are rejected before an intent or RPC effect.
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
    """Fail closed unless both the digest representation and semantics match."""
    if not isinstance(expected_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_hash
    ):
        raise ValueError("MPR2602_PREPARED_PLAN_HASH_INVALID")
    actual = _prepared_plan_hash(candidate)
    if actual != expected_hash:
        raise ValueError("MPR2602_PREPARED_PLAN_IDENTITY_MISMATCH")
    return actual


def begin_prepared_attempt_intent(
    authority: UnifiedLifecycleAuthority,
    *,
    attempt_id: str,
    attempt_generation: int,
    candidate: AtomicVerticalCandidate,
) -> tuple[AuthorityFence, str]:
    """Bind complete prepared semantics to the existing durable PR-02 owner.

    A changed plan or schema conflicts before simulation. Historical v1 records
    are never relabelled, rewritten, or silently accepted as v2 evidence.
    """
    if not isinstance(authority, UnifiedLifecycleAuthority):
        raise TypeError("MPR2602_UNIFIED_AUTHORITY_REQUIRED")
    plan_hash = _prepared_plan_hash(candidate)
    opportunity_id = str(getattr(candidate.request, "opportunity_id", ""))
    if not opportunity_id.strip():
        raise ValueError("MPR2602_OPPORTUNITY_ID_REQUIRED")
    fence = authority.begin_attempt_intent(
        attempt_id=attempt_id,
        attempt_generation=attempt_generation,
        request_payload={
            "schema": MPR2602_PREPARED_PLAN_SCHEMA,
            "opportunity_id": opportunity_id,
            "prepared_plan_hash": plan_hash,
        },
    )
    return fence, plan_hash


def _semantic_value(value: Any) -> Any:
    # StrEnum and IntEnum must precede their scalar base classes. The policy's
    # enum type is part of its identity, not merely the underlying scalar value.
    if isinstance(value, Enum):
        return {
            "__enum__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _semantic_value(value.value),
        }
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("MPR2602_NONFINITE_PLAN_VALUE")
        # Exact binary metadata without weakening integer-only canonical JSON.
        return {"__float_hex__": value.hex()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes_hex__": bytes(value).hex()}
    if isinstance(value, Path):
        return {"__path__": str(value)}

    # Concrete SDK types, not duck-typed objects that may hide extra semantics.
    if isinstance(value, Instruction):
        return {
            "__instruction__": f"{type(value).__module__}.{type(value).__qualname__}",
            "program_id": str(value.program_id),
            "accounts": [_semantic_account_meta(item) for item in value.accounts],
            "data": bytes(value.data).hex(),
        }
    if isinstance(value, AccountMeta):
        return {"__account_meta__": _semantic_account_meta(value)}
    if isinstance(value, AddressLookupTableAccount):
        return {
            "__lookup_table_account__": {
                "key": str(value.key),
                "addresses": [str(address) for address in value.addresses],
            }
        }

    if is_dataclass(value) and not isinstance(value, type):
        encoded_fields = {
            field.name: _semantic_value(getattr(value, field.name))
            for field in fields(value)
            if field.name not in _ACQUISITION_ONLY_FIELDS
        }
        return {
            "__dataclass__": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": encoded_fields,
        }

    if isinstance(value, Mapping):
        encoded_items = [
            (_semantic_mapping_key(key), _semantic_value(item))
            for key, item in value.items()
        ]
        encoded_items.sort(key=lambda pair: canonical_json_bytes(pair[0]))
        return {"__mapping__": encoded_items}

    if isinstance(value, Set):
        encoded_set = [_semantic_value(item) for item in value]
        encoded_set.sort(key=canonical_json_bytes)
        return {"__set__": encoded_set}

    if isinstance(value, Sequence):
        return [_semantic_value(item) for item in value]

    # Only concrete immutable SDK scalars have an approved string encoding.
    # In particular, signing keys and arbitrary solders objects are not allowed.
    if isinstance(value, (Pubkey, Hash)):
        return {
            "__solders__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": str(value),
        }

    raise TypeError(
        "MPR2602_UNSUPPORTED_PLAN_VALUE:"
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _semantic_mapping_key(value: Any) -> Any:
    if isinstance(value, Enum):
        return _semantic_value(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (Pubkey, Hash)):
        # Preserve key type: a Pubkey and its string representation can both be
        # present in a mapping, and must not collide or depend on insertion order.
        return _semantic_value(value)
    raise TypeError("MPR2602_UNSUPPORTED_PLAN_MAPPING_KEY")


def _semantic_account_meta(value: AccountMeta) -> dict[str, Any]:
    return {
        "pubkey": str(value.pubkey),
        "is_signer": value.is_signer,
        "is_writable": value.is_writable,
    }


__all__ = [
    "MPR2602_PREPARED_PLAN_SCHEMA",
    "_prepared_plan_hash",
    "begin_prepared_attempt_intent",
    "validate_prepared_plan_hash",
]
