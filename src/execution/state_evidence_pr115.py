"""PR-115 simulation-owned pre/post state evidence.

The PR-115 boundary derives economic observations from raw RPC account evidence
owned by the exact simulation report.  It intentionally does not accept
caller-supplied native/token/MarginFi observations, and it does not submit,
sign, or contact RPC.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any

from .exact_simulation import ExactSimulationReport

PR115_SCHEMA_VERSION = "pr115.simulation-owned-economic-proof.v1"
PR115_DECODER_VERSION = "pr115.decoder.native-and-legacy-spl.v1"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPw1N1qEHxZC6kzNRQdB"
SPL_TOKEN_ACCOUNT_LEN = 165
SPL_TOKEN_MINT_OFFSET = 0
SPL_TOKEN_OWNER_OFFSET = 32
SPL_TOKEN_AMOUNT_OFFSET = 64
SPL_TOKEN_AMOUNT_LEN = 8


class PR115StateEvidenceError(ValueError):
    """Raised when raw state evidence cannot prove an economic observation."""


class PR115StateEvidenceCode(StrEnum):
    """Stable PR-115 fail-closed reason codes."""

    ADDRESS_SET_MISMATCH = "address_set_mismatch"
    CONTEXT_SLOT_VIOLATION = "context_slot_violation"
    COPIED_HASH_MISMATCH = "copied_hash_mismatch"
    DUPLICATE_ADDRESS = "duplicate_address"
    MALFORMED_ACCOUNT = "malformed_account"
    MISSING_ACCOUNT = "missing_account"
    UNEXPECTED_EXECUTABLE = "unexpected_executable"
    UNREQUESTED_ACCOUNT = "unrequested_account"
    UNSUPPORTED_ACCOUNT_OWNER = "unsupported_account_owner"
    UNSUPPORTED_TOKEN_2022 = "unsupported_token_2022"
    WRONG_DATA_LENGTH = "wrong_data_length"
    WRONG_OWNER = "wrong_owner"


@dataclass(frozen=True, slots=True)
class PR115DecodePolicy:
    """Strict decoder policy for simulation-owned evidence."""

    expected_owner_by_address: Mapping[str, str] | None = None
    allow_legacy_spl_token_accounts: bool = True
    allow_token_2022_accounts: bool = False
    allow_marginfi_accounts: bool = False
    max_account_data_bytes: int = 4096

    def __post_init__(self) -> None:
        if self.max_account_data_bytes <= 0:
            raise PR115StateEvidenceError("max_account_data_bytes must be positive")


@dataclass(frozen=True, slots=True)
class PR115RawAccountSnapshot:
    """One monitored account bound to address, index, owner, bytes and hashes."""

    address: str
    index: int
    owner: str
    executable: bool
    lamports: int
    data_base64: str
    data_hash: str
    raw_hash: str
    decoded_hash: str


@dataclass(frozen=True, slots=True)
class PR115NativeLamportDelta:
    """Native lamport delta derived only from raw pre/post account objects."""

    address: str
    pre_lamports: int
    post_lamports: int
    delta_lamports: int
    pre_raw_hash: str
    post_raw_hash: str


@dataclass(frozen=True, slots=True)
class PR115TokenAccountDelta:
    """Legacy SPL Token account amount delta derived from raw account bytes."""

    address: str
    mint_hash: str
    owner_hash: str
    pre_amount: int
    post_amount: int
    delta_amount: int
    pre_raw_hash: str
    post_raw_hash: str


@dataclass(frozen=True, slots=True)
class PR115SimulationOwnedEconomicProof:
    """Final PR-115 proof: deltas are decoded from raw evidence, not caller data."""

    schema_version: str
    decoder_version: str
    message_hash: str
    simulation_response_hash: str
    monitored_accounts: tuple[str, ...]
    pre_state_slot: int
    post_state_slot: int
    pre_root_slot: int | None
    post_root_slot: int | None
    min_context_slot: int
    pre_state_hash: str
    post_state_hash: str
    raw_evidence_hash: str
    native_deltas: tuple[PR115NativeLamportDelta, ...]
    token_deltas: tuple[PR115TokenAccountDelta, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decoder_version": self.decoder_version,
            "message_hash": self.message_hash,
            "simulation_response_hash": self.simulation_response_hash,
            "monitored_accounts": list(self.monitored_accounts),
            "pre_state_slot": self.pre_state_slot,
            "post_state_slot": self.post_state_slot,
            "pre_root_slot": self.pre_root_slot,
            "post_root_slot": self.post_root_slot,
            "min_context_slot": self.min_context_slot,
            "pre_state_hash": self.pre_state_hash,
            "post_state_hash": self.post_state_hash,
            "raw_evidence_hash": self.raw_evidence_hash,
            "native_deltas": [item.__dict__ for item in self.native_deltas],
            "token_deltas": [item.__dict__ for item in self.token_deltas],
        }


def build_pr115_proof_from_report(
    report: ExactSimulationReport,
    *,
    pre_state_accounts: Sequence[Mapping[str, Any] | None],
    pre_state_slot: int,
    pre_root_slot: int | None = None,
    post_root_slot: int | None = None,
    policy: PR115DecodePolicy | None = None,
) -> PR115SimulationOwnedEconomicProof:
    """Derive economic proof from exact simulation raw account evidence only."""

    if not report.final.returned_accounts:
        raise PR115StateEvidenceError("final simulation did not preserve raw accounts")
    return build_pr115_simulation_owned_economic_proof(
        monitored_accounts=report.monitored_accounts,
        pre_state_accounts=pre_state_accounts,
        post_state_accounts=report.final.returned_accounts,
        message_hash=report.message_hash,
        simulation_response_hash=report.final.response_hash,
        pre_state_slot=pre_state_slot,
        post_state_slot=report.final.slot,
        min_context_slot=report.min_context_slot,
        pre_root_slot=pre_root_slot,
        post_root_slot=post_root_slot,
        expected_post_account_hashes=report.final.returned_account_hashes,
        policy=policy,
    )


def build_pr115_simulation_owned_economic_proof(
    *,
    monitored_accounts: Sequence[str],
    pre_state_accounts: Sequence[Mapping[str, Any] | None],
    post_state_accounts: Sequence[Mapping[str, Any] | None],
    message_hash: str,
    simulation_response_hash: str,
    pre_state_slot: int,
    post_state_slot: int,
    min_context_slot: int,
    pre_root_slot: int | None = None,
    post_root_slot: int | None = None,
    expected_post_account_hashes: Sequence[str] | None = None,
    policy: PR115DecodePolicy | None = None,
) -> PR115SimulationOwnedEconomicProof:
    """Build a PR-115 proof without accepting caller-supplied observations."""

    active_policy = policy or PR115DecodePolicy()
    addresses = tuple(str(address) for address in monitored_accounts)
    _validate_addresses(addresses)
    _validate_slots(
        pre_state_slot=pre_state_slot,
        post_state_slot=post_state_slot,
        min_context_slot=min_context_slot,
        pre_root_slot=pre_root_slot,
        post_root_slot=post_root_slot,
    )
    if len(pre_state_accounts) != len(addresses):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.ADDRESS_SET_MISMATCH)
    if len(post_state_accounts) != len(addresses):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.UNREQUESTED_ACCOUNT)

    pre_snapshots = tuple(
        _decode_snapshot(address, index, account, active_policy)
        for index, (address, account) in enumerate(zip(addresses, pre_state_accounts))
    )
    post_snapshots = tuple(
        _decode_snapshot(address, index, account, active_policy)
        for index, (address, account) in enumerate(zip(addresses, post_state_accounts))
    )
    if expected_post_account_hashes is not None:
        expected = tuple(expected_post_account_hashes)
        actual = tuple(snapshot.raw_hash for snapshot in post_snapshots)
        if expected != actual:
            raise PR115StateEvidenceError(PR115StateEvidenceCode.COPIED_HASH_MISMATCH)

    native_deltas: list[PR115NativeLamportDelta] = []
    token_deltas: list[PR115TokenAccountDelta] = []
    for pre, post in zip(pre_snapshots, post_snapshots):
        if pre.owner != post.owner:
            raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_OWNER)
        if post.owner == SYSTEM_PROGRAM_ID:
            native_deltas.append(_native_delta(pre, post))
        elif post.owner == SPL_TOKEN_PROGRAM_ID:
            token_deltas.append(_token_delta(pre, post))
        elif post.owner == TOKEN_2022_PROGRAM_ID:
            raise PR115StateEvidenceError(PR115StateEvidenceCode.UNSUPPORTED_TOKEN_2022)
        else:
            raise PR115StateEvidenceError(
                PR115StateEvidenceCode.UNSUPPORTED_ACCOUNT_OWNER
            )

    pre_state_hash = _hash_json([item.__dict__ for item in pre_snapshots])
    post_state_hash = _hash_json([item.__dict__ for item in post_snapshots])
    raw_evidence_hash = _hash_json(
        {
            "message_hash": message_hash,
            "simulation_response_hash": simulation_response_hash,
            "pre_state_hash": pre_state_hash,
            "post_state_hash": post_state_hash,
            "pre_state_slot": pre_state_slot,
            "post_state_slot": post_state_slot,
            "pre_root_slot": pre_root_slot,
            "post_root_slot": post_root_slot,
            "min_context_slot": min_context_slot,
            "decoder_version": PR115_DECODER_VERSION,
        }
    )
    return PR115SimulationOwnedEconomicProof(
        schema_version=PR115_SCHEMA_VERSION,
        decoder_version=PR115_DECODER_VERSION,
        message_hash=message_hash,
        simulation_response_hash=simulation_response_hash,
        monitored_accounts=addresses,
        pre_state_slot=pre_state_slot,
        post_state_slot=post_state_slot,
        pre_root_slot=pre_root_slot,
        post_root_slot=post_root_slot,
        min_context_slot=min_context_slot,
        pre_state_hash=pre_state_hash,
        post_state_hash=post_state_hash,
        raw_evidence_hash=raw_evidence_hash,
        native_deltas=tuple(native_deltas),
        token_deltas=tuple(token_deltas),
    )


def _decode_snapshot(
    address: str,
    index: int,
    account: Mapping[str, Any] | None,
    policy: PR115DecodePolicy,
) -> PR115RawAccountSnapshot:
    if account is None:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MISSING_ACCOUNT)
    owner = account.get("owner")
    executable = account.get("executable")
    lamports = account.get("lamports")
    if not isinstance(owner, str) or not owner.strip():
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if not isinstance(executable, bool):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if executable:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.UNEXPECTED_EXECUTABLE)
    if not isinstance(lamports, int) or isinstance(lamports, bool) or lamports < 0:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    expected_owner = (policy.expected_owner_by_address or {}).get(address)
    if expected_owner is not None and owner != expected_owner:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_OWNER)
    data_base64, data = _decode_account_data(account.get("data"))
    if len(data) > policy.max_account_data_bytes:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)
    decoded_hash = _hash_json(
        {
            "address": address,
            "index": index,
            "owner": owner,
            "executable": executable,
            "lamports": lamports,
            "data_hash": _hash_bytes(data),
            "decoder_version": PR115_DECODER_VERSION,
        }
    )
    return PR115RawAccountSnapshot(
        address=address,
        index=index,
        owner=owner,
        executable=executable,
        lamports=lamports,
        data_base64=data_base64,
        data_hash=_hash_bytes(data),
        raw_hash=_hash_json(account),
        decoded_hash=decoded_hash,
    )


def _native_delta(
    pre: PR115RawAccountSnapshot,
    post: PR115RawAccountSnapshot,
) -> PR115NativeLamportDelta:
    if pre.data_base64 or post.data_base64:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)
    return PR115NativeLamportDelta(
        address=post.address,
        pre_lamports=pre.lamports,
        post_lamports=post.lamports,
        delta_lamports=post.lamports - pre.lamports,
        pre_raw_hash=pre.raw_hash,
        post_raw_hash=post.raw_hash,
    )


def _token_delta(
    pre: PR115RawAccountSnapshot,
    post: PR115RawAccountSnapshot,
) -> PR115TokenAccountDelta:
    pre_bytes = base64.b64decode(pre.data_base64) if pre.data_base64 else b""
    post_bytes = base64.b64decode(post.data_base64) if post.data_base64 else b""
    if len(pre_bytes) != SPL_TOKEN_ACCOUNT_LEN or len(post_bytes) != SPL_TOKEN_ACCOUNT_LEN:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_DATA_LENGTH)
    pre_mint = pre_bytes[SPL_TOKEN_MINT_OFFSET:SPL_TOKEN_OWNER_OFFSET]
    post_mint = post_bytes[SPL_TOKEN_MINT_OFFSET:SPL_TOKEN_OWNER_OFFSET]
    pre_owner = pre_bytes[SPL_TOKEN_OWNER_OFFSET:SPL_TOKEN_AMOUNT_OFFSET]
    post_owner = post_bytes[SPL_TOKEN_OWNER_OFFSET:SPL_TOKEN_AMOUNT_OFFSET]
    if pre_mint != post_mint or pre_owner != post_owner:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.WRONG_OWNER)
    pre_amount = int.from_bytes(
        pre_bytes[SPL_TOKEN_AMOUNT_OFFSET:SPL_TOKEN_AMOUNT_OFFSET + SPL_TOKEN_AMOUNT_LEN],
        "little",
    )
    post_amount = int.from_bytes(
        post_bytes[SPL_TOKEN_AMOUNT_OFFSET:SPL_TOKEN_AMOUNT_OFFSET + SPL_TOKEN_AMOUNT_LEN],
        "little",
    )
    return PR115TokenAccountDelta(
        address=post.address,
        mint_hash=_hash_bytes(post_mint),
        owner_hash=_hash_bytes(post_owner),
        pre_amount=pre_amount,
        post_amount=post_amount,
        delta_amount=post_amount - pre_amount,
        pre_raw_hash=pre.raw_hash,
        post_raw_hash=post.raw_hash,
    )


def _decode_account_data(value: Any) -> tuple[str, bytes]:
    if value in (None, ""):
        return "", b""
    if isinstance(value, list) and len(value) == 2 and value[1] == "base64":
        encoded = value[0]
    elif isinstance(value, str):
        encoded = value
    else:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if not isinstance(encoded, str):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)
    if not encoded:
        return "", b""
    try:
        return encoded, base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise PR115StateEvidenceError(
            PR115StateEvidenceCode.MALFORMED_ACCOUNT
        ) from exc


def _validate_addresses(addresses: tuple[str, ...]) -> None:
    if not addresses:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.ADDRESS_SET_MISMATCH)
    if len(addresses) != len(set(addresses)):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.DUPLICATE_ADDRESS)
    if any(not address.strip() for address in addresses):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT)


def _validate_slots(
    *,
    pre_state_slot: int,
    post_state_slot: int,
    min_context_slot: int,
    pre_root_slot: int | None,
    post_root_slot: int | None,
) -> None:
    values = (pre_state_slot, post_state_slot, min_context_slot)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if pre_state_slot < min_context_slot or post_state_slot < min_context_slot:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    if post_state_slot < pre_state_slot:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
    for root_slot, state_slot in (
        (pre_root_slot, pre_state_slot),
        (post_root_slot, post_state_slot),
    ):
        if root_slot is None:
            continue
        if not isinstance(root_slot, int) or isinstance(root_slot, bool):
            raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)
        if root_slot < state_slot:
            raise PR115StateEvidenceError(PR115StateEvidenceCode.CONTEXT_SLOT_VIOLATION)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PR115StateEvidenceError(PR115StateEvidenceCode.MALFORMED_ACCOUNT) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "PR115_DECODER_VERSION",
    "PR115_SCHEMA_VERSION",
    "PR115DecodePolicy",
    "PR115NativeLamportDelta",
    "PR115RawAccountSnapshot",
    "PR115SimulationOwnedEconomicProof",
    "PR115StateEvidenceCode",
    "PR115StateEvidenceError",
    "PR115TokenAccountDelta",
    "SPL_TOKEN_PROGRAM_ID",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "build_pr115_proof_from_report",
    "build_pr115_simulation_owned_economic_proof",
]
