"""SUPER-04 / W2-11 owned Address Lookup Table preparation contracts.

Runtime ALT reads remain owned by src.execution.transaction_compiler.AltValidator.
This module adds only default-off preparation planning and pure unsigned
instruction builders, derived from the pinned MIT solana-web3.js implementation.
It never signs, submits, freezes, or auto-closes a table.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.execution.models import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    ResolvedAddressLookupTable,
)
from src.execution.transaction_compiler import (
    AltValidator,
    TransactionCompileError,
)

ALT_UPSTREAM_REPOSITORY = "solana-foundation/solana-web3.js"
ALT_UPSTREAM_COMMIT = "0b600488afc85bb1f4d41827c7b800fb31c034f5"
ALT_UPSTREAM_FILE = "src/programs/address-lookup-table/index.ts"
ALT_UPSTREAM_LICENSE = "MIT"
SUPER04_ALT_SCHEMA = "super04.owned-alt-lifecycle.v1"
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OwnedAltError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AltPreparationDisposition(StrEnum):
    REUSE = "reuse"
    NO_BENEFIT = "no_benefit"
    CREATE_AND_EXTEND = "create_and_extend"
    EXTEND = "extend"
    BLOCKED = "blocked"


class AltAction(StrEnum):
    CREATE = "create"
    EXTEND = "extend"
    DEACTIVATE = "deactivate"
    CLOSE = "close"


class AltRetirementDisposition(StrEnum):
    BLOCKED = "blocked"
    DEACTIVATE = "deactivate"
    CLOSE = "close"
    NOOP = "noop"


def _nonnegative(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise OwnedAltError(f"SUPER04_ALT_INVALID_{label.upper()}")


def _positive(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise OwnedAltError(f"SUPER04_ALT_INVALID_{label.upper()}")


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise OwnedAltError(f"SUPER04_ALT_INVALID_{label.upper()}")


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class OwnedAltState:
    address: Pubkey
    authority: Pubkey | None
    addresses: tuple[Pubkey, ...]
    source_slot: int
    deactivated: bool = False

    def __post_init__(self) -> None:
        _nonnegative(self.source_slot, "source_slot")
        if len(set(self.addresses)) != len(self.addresses):
            raise OwnedAltError("SUPER04_ALT_DUPLICATE_ADDRESS")


@dataclass(frozen=True, slots=True)
class AltPreparationPolicy:
    format_id: str
    minimum_savings_bytes: int
    preparation_budget_lamports: int
    estimated_create_extend_cost_lamports: int
    maximum_addresses: int = 256

    def __post_init__(self) -> None:
        _nonnegative(
            self.minimum_savings_bytes,
            "minimum_savings_bytes",
        )
        _nonnegative(
            self.preparation_budget_lamports,
            "preparation_budget_lamports",
        )
        _nonnegative(
            self.estimated_create_extend_cost_lamports,
            "estimated_create_extend_cost_lamports",
        )
        _positive(self.maximum_addresses, "maximum_addresses")


@dataclass(frozen=True, slots=True)
class AltPreparationPlan:
    disposition: AltPreparationDisposition
    reason_code: str
    authority: Pubkey
    payer: Pubkey
    desired_addresses: tuple[Pubkey, ...]
    existing_table: Pubkey | None
    addresses_to_add: tuple[Pubkey, ...]
    estimated_savings_bytes: int
    estimated_cost_lamports: int
    plan_hash: str
    live_enabled: bool = False


def plan_owned_alt_preparation(
    *,
    authority: Pubkey,
    payer: Pubkey,
    desired_addresses: tuple[Pubkey, ...],
    existing: OwnedAltState | None,
    estimated_savings_bytes: int,
    policy: AltPreparationPolicy,
) -> AltPreparationPlan:
    """NF-341: plan only when v0 and measured benefit justify preparation."""

    _nonnegative(estimated_savings_bytes, "estimated_savings_bytes")
    if (
        not desired_addresses
        or len(set(desired_addresses)) != len(desired_addresses)
    ):
        raise OwnedAltError("SUPER04_ALT_DESIRED_ADDRESSES_INVALID")
    if len(desired_addresses) > policy.maximum_addresses:
        raise OwnedAltError("SUPER04_ALT_ADDRESS_BATCH_TOO_LARGE")

    disposition = AltPreparationDisposition.BLOCKED
    reason = "UNPROVEN_BENEFIT"
    existing_table: Pubkey | None = None
    to_add = desired_addresses

    if policy.format_id != "v0":
        reason = "FORMAT_NOT_V0"
    elif estimated_savings_bytes < policy.minimum_savings_bytes:
        disposition = AltPreparationDisposition.NO_BENEFIT
        reason = "UNPROVEN_BENEFIT"
    elif (
        policy.estimated_create_extend_cost_lamports
        > policy.preparation_budget_lamports
    ):
        reason = "PREPARATION_BUDGET_EXCEEDED"
    elif existing is not None:
        existing_table = existing.address
        if existing.deactivated:
            reason = "DEACTIVATING_TABLE"
        elif existing.authority != authority:
            reason = "INVALID_AUTHORITY"
        else:
            existing_addresses = set(existing.addresses)
            missing = tuple(
                address
                for address in desired_addresses
                if address not in existing_addresses
            )
            if (
                len(existing.addresses) + len(missing)
                > policy.maximum_addresses
            ):
                reason = "ADDRESS_BATCH_TOO_LARGE"
            elif not missing:
                disposition = AltPreparationDisposition.REUSE
                reason = "EXISTING_TABLE_COVERS_WORKLOAD"
                to_add = ()
            else:
                disposition = AltPreparationDisposition.EXTEND
                reason = "EXTENSION_MEASURED_BENEFIT"
                to_add = missing
    else:
        disposition = AltPreparationDisposition.CREATE_AND_EXTEND
        reason = "CREATE_MEASURED_BENEFIT"

    payload = {
        "schema": SUPER04_ALT_SCHEMA,
        "disposition": disposition.value,
        "reason": reason,
        "authority": str(authority),
        "payer": str(payer),
        "desired_addresses": [str(item) for item in desired_addresses],
        "existing_table": (
            None if existing_table is None else str(existing_table)
        ),
        "addresses_to_add": [str(item) for item in to_add],
        "estimated_savings_bytes": estimated_savings_bytes,
        "estimated_cost_lamports": (
            policy.estimated_create_extend_cost_lamports
        ),
        "policy": asdict(policy),
    }
    return AltPreparationPlan(
        disposition=disposition,
        reason_code=reason,
        authority=authority,
        payer=payer,
        desired_addresses=desired_addresses,
        existing_table=existing_table,
        addresses_to_add=to_add,
        estimated_savings_bytes=estimated_savings_bytes,
        estimated_cost_lamports=(
            policy.estimated_create_extend_cost_lamports
        ),
        plan_hash=_hash_json(payload),
        live_enabled=False,
    )


@dataclass(frozen=True, slots=True)
class OwnedAltInstruction:
    action: AltAction
    instruction: Instruction
    lookup_table: Pubkey
    provenance_hash: str
    upstream_repository: str = ALT_UPSTREAM_REPOSITORY
    upstream_commit: str = ALT_UPSTREAM_COMMIT
    upstream_file: str = ALT_UPSTREAM_FILE
    upstream_license: str = ALT_UPSTREAM_LICENSE


def _instruction_data(index: int) -> bytes:
    return int(index).to_bytes(4, "little")


def build_owned_alt_instruction(
    *,
    action: AltAction,
    authority: Pubkey,
    payer: Pubkey | None = None,
    lookup_table: Pubkey | None = None,
    addresses: tuple[Pubkey, ...] = (),
    recent_slot: int | None = None,
    recipient: Pubkey | None = None,
) -> OwnedAltInstruction:
    """NF-342: pure unsigned ALT builder matching pinned web3.js layout."""

    metas: tuple[AccountMeta, ...]

    if action is AltAction.CREATE:
        if (
            payer is None
            or recent_slot is None
            or lookup_table is not None
            or addresses
        ):
            raise OwnedAltError("INVALID_ACTION")
        _nonnegative(recent_slot, "recent_slot")
        lookup_table, bump = Pubkey.find_program_address(
            [bytes(authority), int(recent_slot).to_bytes(8, "little")],
            ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
        )
        data = (
            _instruction_data(0)
            + int(recent_slot).to_bytes(8, "little")
            + bytes([bump])
        )
        metas = (
            AccountMeta(lookup_table, False, True),
            AccountMeta(authority, True, False),
            AccountMeta(payer, True, True),
            AccountMeta(SYSTEM_PROGRAM_ID, False, False),
        )
    elif action is AltAction.EXTEND:
        if lookup_table is None or not addresses:
            raise OwnedAltError("INVALID_ACTION")
        if (
            len(addresses) > 256
            or len(set(addresses)) != len(addresses)
        ):
            raise OwnedAltError("ADDRESS_BATCH_TOO_LARGE")
        data = (
            _instruction_data(2)
            + len(addresses).to_bytes(8, "little")
            + b"".join(bytes(address) for address in addresses)
        )
        base = [
            AccountMeta(lookup_table, False, True),
            AccountMeta(authority, True, False),
        ]
        if payer is not None:
            base.extend(
                [
                    AccountMeta(payer, True, True),
                    AccountMeta(SYSTEM_PROGRAM_ID, False, False),
                ]
            )
        metas = tuple(base)
    elif action is AltAction.DEACTIVATE:
        if (
            lookup_table is None
            or payer is not None
            or addresses
            or recipient is not None
        ):
            raise OwnedAltError("INVALID_ACTION")
        data = _instruction_data(3)
        metas = (
            AccountMeta(lookup_table, False, True),
            AccountMeta(authority, True, False),
        )
    elif action is AltAction.CLOSE:
        if (
            lookup_table is None
            or recipient is None
            or payer is not None
            or addresses
        ):
            raise OwnedAltError("INVALID_ACTION")
        data = _instruction_data(4)
        metas = (
            AccountMeta(lookup_table, False, True),
            AccountMeta(authority, True, False),
            AccountMeta(recipient, False, True),
        )
    else:
        raise OwnedAltError("INVALID_ACTION")

    if lookup_table is None:
        raise OwnedAltError("INVALID_ACTION")
    instruction = Instruction(
        ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
        data,
        metas,
    )
    provenance = _hash_json(
        {
            "schema": SUPER04_ALT_SCHEMA,
            "action": action.value,
            "program_id": str(ADDRESS_LOOKUP_TABLE_PROGRAM_ID),
            "lookup_table": str(lookup_table),
            "authority": str(authority),
            "payer": None if payer is None else str(payer),
            "recipient": None if recipient is None else str(recipient),
            "addresses": [str(item) for item in addresses],
            "data_hex": data.hex(),
            "upstream_commit": ALT_UPSTREAM_COMMIT,
            "upstream_file": ALT_UPSTREAM_FILE,
        }
    )
    return OwnedAltInstruction(
        action=action,
        instruction=instruction,
        lookup_table=lookup_table,
        provenance_hash=provenance,
    )


@dataclass(frozen=True, slots=True)
class OwnedAltVersion:
    address: Pubkey
    addresses: tuple[Pubkey, ...]
    source_slot: int
    data_hash: str
    finalized_operation_hash: str
    version_hash: str


def publish_ready_alt_version(
    *,
    address: Pubkey,
    raw_data: bytes,
    owner: Pubkey,
    source_slot: int,
    expected_addresses: tuple[Pubkey, ...],
    finalized_operation_hash: str,
    validator: AltValidator | None = None,
) -> OwnedAltVersion:
    """NF-343: publish after finalized read accepted by AltValidator."""

    _sha(finalized_operation_hash, "finalized_operation_hash")
    if not expected_addresses:
        raise OwnedAltError("CONTENT_MISMATCH")
    try:
        resolved = (validator or AltValidator()).deserialize(
            address,
            raw_data,
            owner,
            source_slot,
            expected_addresses,
        )
    except TransactionCompileError as exc:
        raise OwnedAltError("NOT_YET_USABLE") from exc
    if tuple(resolved.addresses) != tuple(expected_addresses):
        raise OwnedAltError("CONTENT_MISMATCH")
    payload = {
        "schema": SUPER04_ALT_SCHEMA,
        "address": str(resolved.address),
        "addresses": [str(item) for item in resolved.addresses],
        "source_slot": resolved.source_slot,
        "data_hash": resolved.data_hash,
        "finalized_operation_hash": finalized_operation_hash,
    }
    return OwnedAltVersion(
        address=resolved.address,
        addresses=resolved.addresses,
        source_slot=resolved.source_slot,
        data_hash=resolved.data_hash,
        finalized_operation_hash=finalized_operation_hash,
        version_hash=_hash_json(payload),
    )


@dataclass(frozen=True, slots=True)
class AltRetirementPlan:
    disposition: AltRetirementDisposition
    reason_code: str
    lookup_table: Pubkey
    recipient: Pubkey | None
    live_enabled: bool = False


def plan_owned_alt_retirement(
    *,
    state: OwnedAltState,
    authority: Pubkey,
    recipient: Pubkey | None,
    outstanding_reference_leases: int,
    unknown_submissions: int,
    protocol_close_eligible: bool,
    recipient_allowed: bool,
) -> AltRetirementPlan:
    """NF-344: never retire a table that may still be referenced."""

    _nonnegative(
        outstanding_reference_leases,
        "outstanding_reference_leases",
    )
    _nonnegative(unknown_submissions, "unknown_submissions")
    if state.authority != authority:
        return AltRetirementPlan(
            AltRetirementDisposition.BLOCKED,
            "INVALID_AUTHORITY",
            state.address,
            None,
        )
    if outstanding_reference_leases or unknown_submissions:
        return AltRetirementPlan(
            AltRetirementDisposition.BLOCKED,
            "OUTSTANDING_TRANSACTION",
            state.address,
            None,
        )
    if not state.deactivated:
        return AltRetirementPlan(
            AltRetirementDisposition.DEACTIVATE,
            "DEACTIVATION_REQUIRED",
            state.address,
            None,
        )
    if not protocol_close_eligible:
        return AltRetirementPlan(
            AltRetirementDisposition.BLOCKED,
            "COOLDOWN_NOT_PASSED",
            state.address,
            None,
        )
    if recipient is None or not recipient_allowed:
        return AltRetirementPlan(
            AltRetirementDisposition.BLOCKED,
            "RECIPIENT_NOT_ALLOWED",
            state.address,
            None,
        )
    return AltRetirementPlan(
        AltRetirementDisposition.CLOSE,
        "CLOSE_ELIGIBLE",
        state.address,
        recipient,
    )


__all__ = [
    "ALT_UPSTREAM_COMMIT",
    "ALT_UPSTREAM_FILE",
    "ALT_UPSTREAM_LICENSE",
    "ALT_UPSTREAM_REPOSITORY",
    "AltAction",
    "AltPreparationDisposition",
    "AltPreparationPlan",
    "AltPreparationPolicy",
    "AltRetirementDisposition",
    "AltRetirementPlan",
    "OwnedAltError",
    "OwnedAltInstruction",
    "OwnedAltState",
    "OwnedAltVersion",
    "SUPER04_ALT_SCHEMA",
    "build_owned_alt_instruction",
    "plan_owned_alt_preparation",
    "plan_owned_alt_retirement",
    "publish_ready_alt_version",
]
