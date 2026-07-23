"""MPR-04 protocol-bound atomic economic execution gate.

This module starts the V4 MPR-04 cutover without enabling live trading, signing,
provider calls or transaction submission. It is an offline acceptance contract for
protocol-bound paper/shadow attempts: exact instruction roles, blockhash/current
height freshness, raw simulation state retention and decoder-owned conservative
accounting must be inseparable before any supported runtime can claim a candidate
is economically admissible.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence, Self

SCHEMA_VERSION = "mpr04.protocol-bound-economic-execution.v1"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
LEGACY_SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
WSOL_MINT = "So11111111111111111111111111111111111111112"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"

_ALLOWED_PROGRAMS: frozenset[str] = frozenset(
    {
        "marginfi.v2",
        "kamino.lending",
        "jupiter.swap",
        LEGACY_SPL_TOKEN_PROGRAM_ID,
        TOKEN_2022_PROGRAM_ID,
        SYSTEM_PROGRAM_ID,
        ASSOCIATED_TOKEN_PROGRAM_ID,
    }
)
_REQUIRED_ROLE_SEQUENCE: tuple[str, ...] = (
    "marginfi.borrow",
    "jupiter.leg_a",
    "jupiter.leg_b",
    "marginfi.repay",
)
_EXACTLY_ONCE_ROLES: frozenset[str] = frozenset(_REQUIRED_ROLE_SEQUENCE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")


class MPR04ProtocolExecutionError(ValueError):
    """Stable fail-closed MPR-04 validation error."""


@dataclass(frozen=True, slots=True)
class ChainProgramRegistry:
    """Canonical MPR-04 chain/program identity registry."""

    token_2022_program_id: str = TOKEN_2022_PROGRAM_ID
    legacy_spl_token_program_id: str = LEGACY_SPL_TOKEN_PROGRAM_ID
    system_program_id: str = SYSTEM_PROGRAM_ID
    wsol_mint: str = WSOL_MINT
    associated_token_program_id: str = ASSOCIATED_TOKEN_PROGRAM_ID
    allowed_protocol_programs: tuple[str, ...] = tuple(sorted(_ALLOWED_PROGRAMS))

    def validate(self) -> None:
        if self.token_2022_program_id != TOKEN_2022_PROGRAM_ID:
            raise MPR04ProtocolExecutionError("MPR04_NON_CANONICAL_TOKEN_2022_PROGRAM")
        if self.associated_token_program_id != ASSOCIATED_TOKEN_PROGRAM_ID:
            raise MPR04ProtocolExecutionError(
                "MPR04_NON_CANONICAL_ASSOCIATED_TOKEN_PROGRAM"
            )
        if self.wsol_mint == self.system_program_id:
            raise MPR04ProtocolExecutionError("MPR04_NATIVE_SOL_AND_WSOL_COLLAPSED")
        for value in (
            self.token_2022_program_id,
            self.legacy_spl_token_program_id,
            self.system_program_id,
            self.wsol_mint,
            self.associated_token_program_id,
            *self.allowed_protocol_programs,
        ):
            _require_safe_id(value, "program_or_asset_id")


@dataclass(frozen=True, slots=True)
class InstructionEvidence:
    """Decoded instruction evidence owned by a protocol adapter."""

    index: int
    role: str
    program_id: str
    account_keys_hash: str
    data_hash: str
    writable_account_count: int

    def validate(self, registry: ChainProgramRegistry) -> None:
        if self.index < 0:
            raise MPR04ProtocolExecutionError("MPR04_INSTRUCTION_INDEX_NEGATIVE")
        _require_safe_id(self.role, "instruction_role")
        _require_safe_id(self.program_id, "program_id")
        _require_sha256(self.account_keys_hash, "account_keys_hash")
        _require_sha256(self.data_hash, "data_hash")
        if self.writable_account_count < 0:
            raise MPR04ProtocolExecutionError("MPR04_WRITABLE_ACCOUNT_COUNT_NEGATIVE")
        if self.program_id not in set(registry.allowed_protocol_programs):
            raise MPR04ProtocolExecutionError("MPR04_PROGRAM_NOT_IN_REGISTRY")


@dataclass(frozen=True, slots=True)
class InstructionFirewallEvidence:
    """Exact-cardinality firewall for protocol side-effecting instructions."""

    instructions: tuple[InstructionEvidence, ...]

    def validate(self, registry: ChainProgramRegistry) -> str:
        if not self.instructions:
            raise MPR04ProtocolExecutionError("MPR04_INSTRUCTION_EVIDENCE_REQUIRED")
        ordered = tuple(sorted(self.instructions, key=lambda item: item.index))
        if tuple(item.index for item in ordered) != tuple(range(len(ordered))):
            raise MPR04ProtocolExecutionError("MPR04_INSTRUCTION_INDEX_GAP")
        for item in ordered:
            item.validate(registry)
        roles = [item.role for item in ordered]
        for required in _EXACTLY_ONCE_ROLES:
            if roles.count(required) != 1:
                raise MPR04ProtocolExecutionError("MPR04_REQUIRED_ROLE_NOT_EXACTLY_ONCE")
        required_positions = [roles.index(role) for role in _REQUIRED_ROLE_SEQUENCE]
        if required_positions != sorted(required_positions):
            raise MPR04ProtocolExecutionError("MPR04_REQUIRED_ROLE_ORDER_INVALID")
        for role in roles:
            if (
                role.startswith(("marginfi.", "kamino.", "jupiter."))
                and role not in _EXACTLY_ONCE_ROLES
            ):
                raise MPR04ProtocolExecutionError("MPR04_UNKNOWN_SIDE_EFFECTING_ROLE")
        return _stable_hash(
            {
                "schema": SCHEMA_VERSION,
                "instructions": [_dataclass_payload(item) for item in ordered],
            }
        )


@dataclass(frozen=True, slots=True)
class BlockhashFreshnessEvidence:
    blockhash: str
    fetched_at_slot: int
    current_block_height: int
    last_valid_block_height: int
    safety_margin_blocks: int

    def validate(self) -> None:
        _require_safe_id(self.blockhash, "blockhash")
        if self.fetched_at_slot < 0:
            raise MPR04ProtocolExecutionError("MPR04_BLOCKHASH_SLOT_NEGATIVE")
        if self.current_block_height < 0 or self.last_valid_block_height < 0:
            raise MPR04ProtocolExecutionError("MPR04_BLOCKHEIGHT_NEGATIVE")
        if self.safety_margin_blocks < 0:
            raise MPR04ProtocolExecutionError("MPR04_BLOCKHEIGHT_MARGIN_NEGATIVE")
        if (
            self.current_block_height + self.safety_margin_blocks
            > self.last_valid_block_height
        ):
            raise MPR04ProtocolExecutionError("MPR04_BLOCKHASH_EXPIRED_OR_TOO_CLOSE")


@dataclass(frozen=True, slots=True)
class SerializedTransactionEvidence:
    message_hash: str
    versioned_message_bytes_hash: str
    unsigned_transaction_bytes: int
    required_signature_count: int
    max_wire_bytes: int = 1232

    def validate(self) -> None:
        _require_sha256(self.message_hash, "message_hash")
        _require_sha256(self.versioned_message_bytes_hash, "versioned_message_bytes_hash")
        if self.unsigned_transaction_bytes <= 0 or self.required_signature_count <= 0:
            raise MPR04ProtocolExecutionError(
                "MPR04_SERIALIZED_TRANSACTION_SHAPE_INVALID"
            )
        signed_size = self.unsigned_transaction_bytes + 1 + (
            64 * self.required_signature_count
        )
        if signed_size > self.max_wire_bytes:
            raise MPR04ProtocolExecutionError(
                "MPR04_SIGNED_TRANSACTION_WIRE_SIZE_EXCEEDED"
            )


@dataclass(frozen=True, slots=True)
class SimulationRawAccount:
    account_key: str
    owner_program_id: str
    pre_hash: str
    post_hash: str
    pre_lamports: int
    post_lamports: int

    def validate(self) -> None:
        _require_safe_id(self.account_key, "account_key")
        _require_safe_id(self.owner_program_id, "owner_program_id")
        _require_sha256(self.pre_hash, "pre_hash")
        _require_sha256(self.post_hash, "post_hash")
        if self.pre_lamports < 0 or self.post_lamports < 0:
            raise MPR04ProtocolExecutionError("MPR04_ACCOUNT_LAMPORTS_NEGATIVE")


@dataclass(frozen=True, slots=True)
class ExactSimulationArtifact:
    message_hash: str
    blockhash: str
    slot: int
    success: bool
    units_consumed: int
    decoder_version: str
    returned_accounts: tuple[SimulationRawAccount, ...]

    def validate(self, *, expected_message_hash: str, expected_blockhash: str) -> str:
        _require_sha256(self.message_hash, "message_hash")
        _require_safe_id(self.blockhash, "blockhash")
        _require_safe_id(self.decoder_version, "decoder_version")
        if self.message_hash != expected_message_hash:
            raise MPR04ProtocolExecutionError("MPR04_SIMULATION_MESSAGE_HASH_MISMATCH")
        if self.blockhash != expected_blockhash:
            raise MPR04ProtocolExecutionError("MPR04_SIMULATION_BLOCKHASH_MISMATCH")
        if self.slot < 0 or self.units_consumed <= 0:
            raise MPR04ProtocolExecutionError("MPR04_SIMULATION_METADATA_INVALID")
        if not self.success:
            raise MPR04ProtocolExecutionError("MPR04_SIMULATION_NOT_SUCCESSFUL")
        if not self.returned_accounts:
            raise MPR04ProtocolExecutionError("MPR04_RAW_RETURNED_ACCOUNTS_REQUIRED")
        for account in self.returned_accounts:
            account.validate()
        return _stable_hash(
            {
                "message_hash": self.message_hash,
                "blockhash": self.blockhash,
                "slot": self.slot,
                "decoder_version": self.decoder_version,
                "accounts": [
                    _dataclass_payload(item) for item in self.returned_accounts
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class DecoderOwnedEconomics:
    principal_lamports: int
    flash_fee_lamports: int
    repayment_lamports: int
    gross_output_lamports: int
    network_fee_lamports: int
    priority_tip_lamports: int
    rent_loss_lamports: int
    transfer_fee_lamports: int
    contingency_lamports: int
    realized_account_delta_lamports: int
    minimum_profit_lamports: int
    source_simulation_hash: str
    decoder_version: str

    def validate(self, *, simulation_hash: str, decoder_version: str) -> tuple[int, int]:
        non_negative_fields = {
            "principal_lamports",
            "flash_fee_lamports",
            "repayment_lamports",
            "gross_output_lamports",
            "network_fee_lamports",
            "priority_tip_lamports",
            "rent_loss_lamports",
            "transfer_fee_lamports",
            "contingency_lamports",
            "minimum_profit_lamports",
        }
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in {"source_simulation_hash", "decoder_version"}:
                continue
            if not isinstance(value, int):
                raise MPR04ProtocolExecutionError("MPR04_ECONOMIC_FIELD_NOT_INTEGER")
            if field.name in non_negative_fields and value < 0:
                raise MPR04ProtocolExecutionError("MPR04_ECONOMIC_FIELD_NEGATIVE")
        _require_sha256(self.source_simulation_hash, "source_simulation_hash")
        _require_safe_id(self.decoder_version, "decoder_version")
        if self.source_simulation_hash != simulation_hash:
            raise MPR04ProtocolExecutionError("MPR04_ECONOMICS_NOT_BOUND_TO_SIMULATION")
        if self.decoder_version != decoder_version:
            raise MPR04ProtocolExecutionError("MPR04_ECONOMICS_DECODER_MISMATCH")
        if self.repayment_lamports != self.principal_lamports + self.flash_fee_lamports:
            raise MPR04ProtocolExecutionError("MPR04_FLASH_REPAYMENT_FORMULA_INVALID")
        total_cost = (
            self.repayment_lamports
            + self.network_fee_lamports
            + self.priority_tip_lamports
            + self.rent_loss_lamports
            + self.transfer_fee_lamports
            + self.contingency_lamports
        )
        conservative_profit = self.gross_output_lamports - total_cost
        if conservative_profit != self.realized_account_delta_lamports:
            raise MPR04ProtocolExecutionError("MPR04_DECODER_DELTA_MISMATCH")
        if conservative_profit < self.minimum_profit_lamports:
            raise MPR04ProtocolExecutionError(
                "MPR04_CONSERVATIVE_PROFIT_BELOW_THRESHOLD"
            )
        return total_cost, conservative_profit


@dataclass(frozen=True, slots=True)
class MPR04ExecutionCandidate:
    registry: ChainProgramRegistry
    firewall: InstructionFirewallEvidence
    blockhash: BlockhashFreshnessEvidence
    serialized_transaction: SerializedTransactionEvidence
    simulation: ExactSimulationArtifact
    economics: DecoderOwnedEconomics
    attempt_generation: int
    capital_reservation_hash: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> Self:
        raise MPR04ProtocolExecutionError(
            "MPR04_PUBLIC_RUNTIME_MAPPING_CONSTRUCTOR_DISABLED"
        )


def evaluate_mpr04_candidate(
    candidate: MPR04ExecutionCandidate,
    *,
    live_execution_allowed: bool = False,
    signer_or_sender_allowed: bool = False,
) -> dict[str, object]:
    """Evaluate one MPR-04 sender-free protocol/economics candidate."""

    if live_execution_allowed:
        raise MPR04ProtocolExecutionError("MPR04_LIVE_EXECUTION_NOT_ALLOWED")
    if signer_or_sender_allowed:
        raise MPR04ProtocolExecutionError("MPR04_SIGNER_OR_SENDER_NOT_ALLOWED")
    if candidate.attempt_generation <= 0:
        raise MPR04ProtocolExecutionError("MPR04_ATTEMPT_GENERATION_REQUIRED")
    _require_sha256(candidate.capital_reservation_hash, "capital_reservation_hash")

    candidate.registry.validate()
    firewall_hash = candidate.firewall.validate(candidate.registry)
    candidate.blockhash.validate()
    candidate.serialized_transaction.validate()
    simulation_hash = candidate.simulation.validate(
        expected_message_hash=candidate.serialized_transaction.message_hash,
        expected_blockhash=candidate.blockhash.blockhash,
    )
    total_cost, conservative_profit = candidate.economics.validate(
        simulation_hash=simulation_hash,
        decoder_version=candidate.simulation.decoder_version,
    )
    evidence_hash = _stable_hash(
        {
            "schema": SCHEMA_VERSION,
            "attempt_generation": candidate.attempt_generation,
            "capital_reservation_hash": candidate.capital_reservation_hash,
            "firewall_hash": firewall_hash,
            "simulation_hash": simulation_hash,
            "message_hash": candidate.serialized_transaction.message_hash,
            "blockhash": candidate.blockhash.blockhash,
            "total_required_output_lamports": total_cost,
            "conservative_profit_lamports": conservative_profit,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ready_sender_free": True,
        "live_execution_allowed": False,
        "signer_or_sender_allowed": False,
        "evidence_hash": evidence_hash,
        "firewall_hash": firewall_hash,
        "simulation_hash": simulation_hash,
        "total_required_output_lamports": total_cost,
        "conservative_profit_lamports": conservative_profit,
    }


def _dataclass_payload(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise MPR04ProtocolExecutionError("MPR04_DATACLASS_PAYLOAD_REQUIRED")
    return {field.name: getattr(value, field.name) for field in fields(value)}


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MPR04ProtocolExecutionError(f"MPR04_INVALID_{field_name.upper()}_SHA256")


def _require_safe_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise MPR04ProtocolExecutionError(f"MPR04_INVALID_{field_name.upper()}")


def _stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
