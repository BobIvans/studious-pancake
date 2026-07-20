"""Version-aware Pump adapter models (shadow-only)."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Mapping

Pubkey = str
Commitment = str
Rational = Fraction


class PumpFamily(str, Enum):
    BONDING_CURVE = "bonding_curve"
    PUMPSWAP = "pumpswap"


class PumpLifecycle(str, Enum):
    BONDING_ACTIVE = "bonding_active"
    BONDING_COMPLETE_PENDING_DESTINATION = "bonding_complete_pending_destination"
    MIGRATION_CONFIRMED = "migration_confirmed"
    PUMPSWAP_ACTIVE = "pumpswap_active"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_OR_AMBIGUOUS = "invalid_or_ambiguous"


class SwapDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


class ReasonCode(str, Enum):
    DISABLED_UNVERIFIED_CONTRACT = "DISABLED_UNVERIFIED_CONTRACT"
    PUMP_OFFICIAL_PROVENANCE_REQUIRED = "PUMP_OFFICIAL_PROVENANCE_REQUIRED"
    PUMP_OWNER_MISMATCH = "PUMP_OWNER_MISMATCH"
    PUMP_DISCRIMINATOR_MISMATCH = "PUMP_DISCRIMINATOR_MISMATCH"
    PUMP_LAYOUT_SIZE_MISMATCH = "PUMP_LAYOUT_SIZE_MISMATCH"
    PUMP_SNAPSHOT_STALE = "PUMP_SNAPSHOT_STALE"
    PUMP_MIXED_SLOT = "PUMP_MIXED_SLOT"
    PUMP_FEE_STATE_INCOMPLETE = "PUMP_FEE_STATE_INCOMPLETE"
    PUMP_UNSUPPORTED_TOKEN_EXTENSION = "PUMP_UNSUPPORTED_TOKEN_EXTENSION"
    PUMP_MINT_OWNER_MISMATCH = "PUMP_MINT_OWNER_MISMATCH"
    PUMP_LIFECYCLE_NOT_EXECUTABLE = "PUMP_LIFECYCLE_NOT_EXECUTABLE"
    PUMP_MUTATED_INSTRUCTION = "PUMP_MUTATED_INSTRUCTION"
    PUMP_LEGACY_HEURISTIC_DISABLED = "PUMP_LEGACY_HEURISTIC_DISABLED"


@dataclass(frozen=True)
class RawAccount:
    address: Pubkey
    owner: Pubkey
    data: bytes
    executable: bool
    slot: int
    commitment: Commitment = "processed"


@dataclass(frozen=True)
class FeeBreakdown:
    protocol_fee: int = 0
    creator_fee: int = 0
    sharing_fee: int = 0
    total_fee: int = 0


@dataclass(frozen=True)
class PumpSnapshot:
    family: PumpFamily
    lifecycle: PumpLifecycle
    read_slot: int
    commitment: Commitment
    mint: Pubkey
    quote_mint: Pubkey
    accounts: tuple[RawAccount, ...]
    token_programs: Mapping[Pubkey, Pubkey]
    contract_version: str
    account_set_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_programs", MappingProxyType(dict(self.token_programs)))


@dataclass(frozen=True)
class PumpQuote:
    direction: SwapDirection
    exact_in_amount: int
    consumed_in_amount: int
    gross_out_amount: int
    net_out_amount: int
    minimum_out: int
    fees: FeeBreakdown
    price_impact: Rational
    snapshot_hash: str
    lifecycle: PumpLifecycle
    executable_in_shadow: bool
    reject_reason: ReasonCode | None
