from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Optional

Pubkey = str
Rational = Fraction
FixedI80F48 = Fraction


class LendingProtocol(str, Enum):
    KAMINO = "kamino"
    MARGINFI = "marginfi"


class Commitment(str, Enum):
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


class RiskRequirement(str, Enum):
    INITIAL = "initial"
    MAINTENANCE = "maintenance"


class OracleStatus(str, Enum):
    VALID = "valid"
    STALE = "stale"
    INVALID = "invalid"
    MISSING = "missing"
    CONFIDENCE_TOO_WIDE = "confidence_too_wide"


class AssessmentValidity(str, Enum):
    VALID = "valid"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


class CandidateStatus(str, Enum):
    WATCH = "watch"
    POTENTIALLY_LIQUIDATABLE = "potentially_liquidatable"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


class ReasonCode(str, Enum):
    DISABLED_UNVERIFIED_CONTRACT = "DISABLED_UNVERIFIED_CONTRACT"
    INVALID_PROGRAM_ID = "INVALID_PROGRAM_ID"
    INVALID_OWNER = "INVALID_OWNER"
    INVALID_EXECUTABLE = "INVALID_EXECUTABLE"
    INVALID_DISCRIMINATOR = "INVALID_DISCRIMINATOR"
    INVALID_ACCOUNT_SIZE = "INVALID_ACCOUNT_SIZE"
    INVALID_LAYOUT_VERSION = "INVALID_LAYOUT_VERSION"
    JSON_PARSED_REJECTED = "JSON_PARSED_REJECTED"
    SNAPSHOT_INCOMPLETE = "SNAPSHOT_INCOMPLETE"
    SNAPSHOT_SLOT_MISMATCH = "SNAPSHOT_SLOT_MISMATCH"
    ORACLE_STALE = "ORACLE_STALE"
    ORACLE_INVALID = "ORACLE_INVALID"
    ORACLE_CONFIDENCE_TOO_WIDE = "ORACLE_CONFIDENCE_TOO_WIDE"
    PROTOCOL_PAUSED = "PROTOCOL_PAUSED"
    RISK_MODE_UNVERIFIED = "RISK_MODE_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class RawAccount:
    pubkey: Pubkey
    owner: Pubkey
    data: bytes
    executable: bool
    slot: int
    commitment: Commitment

    def hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.pubkey.encode())
        h.update(self.owner.encode())
        h.update(self.data)
        h.update(str(self.slot).encode())
        h.update(self.commitment.value.encode())
        return h.hexdigest()


@dataclass(frozen=True, slots=True)
class LendingSnapshot:
    protocol: LendingProtocol
    deployment_id: str
    read_slot: int
    commitment: Commitment
    market_or_group: Pubkey
    accounts: tuple[RawAccount, ...]
    account_set_hash: str
    fixture_or_contract_version: str


@dataclass(frozen=True, slots=True)
class RiskEvidence:
    account_hashes: tuple[str, ...]
    risk_config_hash: str
    oracle_pubkeys: tuple[Pubkey, ...]
    slots: tuple[int, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    account: Pubkey
    requirement: RiskRequirement
    weighted_assets: Rational
    weighted_liabilities: Rational
    health: Rational
    health_factor: Optional[Rational]
    oracle_status: OracleStatus
    validity: AssessmentValidity
    evidence: RiskEvidence


@dataclass(frozen=True, slots=True)
class IndexedPosition:
    bank_or_reserve: Pubkey
    mint: Pubkey
    token_program: Pubkey
    amount_base_units: int
    mint_decimals: int
    share_index: Rational
    asset_weight: Rational
    liability_weight: Rational
    oracle_pubkey: Pubkey


@dataclass(frozen=True, slots=True)
class LiquidationConstraints:
    close_factor_bps: int | None
    liquidation_bonus_bps: int | None
    protocol_fees_bps: int | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LiquidationCandidate:
    candidate_id: str
    protocol: LendingProtocol
    account: Pubkey
    snapshot_slot: int
    assessment: RiskAssessment
    positions: tuple[IndexedPosition, ...]
    liquidation_constraints: LiquidationConstraints
    status: CandidateStatus
    exclusion_reason: Optional[ReasonCode]
