"""Capability-safe provider routing domain models for PR-012."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib, json, re
from typing import Any, Optional

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

class ExecutionArtifactKind(str, Enum):
    RAW_INSTRUCTIONS = "raw_instructions"
    ASSEMBLED_TRANSACTION = "assembled_transaction"
    NONE = "none"

class ProviderRole(str, Enum):
    EXECUTABLE = "executable"
    DISCOVERY_ONLY = "discovery_only"
    DISABLED = "disabled"

class ProviderHealth(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNHEALTHY = "unhealthy"
    DISABLED_MISSING_CREDENTIALS = "disabled_missing_credentials"

class AuthKind(str, Enum):
    API_KEY = "api_key"
    HMAC = "hmac"
    NONE = "none"

class MinimumOutputState(str, Enum):
    PROVEN = "proven"
    UNPROVEN = "minimum_output_unproven"

class SwapMode(str, Enum):
    EXACT_IN = "ExactIn"
    EXACT_OUT = "ExactOut"

class NonSelectionReason(str, Enum):
    STALE = "stale"
    DUPLICATE = "duplicate"
    NON_COMPOSABLE = "non_composable"
    CAPABILITY_MISMATCH = "capability_mismatch"
    MISSING_COST = "missing_cost"
    LOWER_CONSERVATIVE_NET = "lower_conservative_net_result"
    QUOTA_OR_CIRCUIT = "quota_circuit_state"
    FEASIBILITY_REJECTION = "feasibility_rejection"
    UNPROVEN_MIN_OUTPUT = "unproven_minimum_output"

@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    schema_version_pin: str
    quote: bool
    artifact_kind: ExecutionArtifactKind
    exact_in: bool
    exact_out: bool
    legacy_spl: bool
    token_2022: bool
    native_sol: bool
    wsol: bool
    jito_compatible: bool
    exposes_accounts: bool
    exposes_alts: bool
    quote_ttl_seconds: Optional[int]
    rate_limit_policy: str
    auth_kind: AuthKind
    role: ProviderRole
    admission_reason: str

    def admits_raw_instructions(self) -> bool:
        return self.role is ProviderRole.EXECUTABLE and self.artifact_kind is ExecutionArtifactKind.RAW_INSTRUCTIONS

@dataclass(frozen=True)
class QuoteRequest:
    input_mint: str
    output_mint: str
    amount_base_units: int
    user_wallet: str
    slippage_bps: int
    swap_mode: SwapMode = SwapMode.EXACT_IN

    def __post_init__(self) -> None:
        for label, value in (("input_mint", self.input_mint), ("output_mint", self.output_mint), ("user_wallet", self.user_wallet)):
            if not _BASE58_RE.match(value):
                raise ValueError(f"invalid base58 {label}")
        if self.amount_base_units <= 0:
            raise ValueError("amount_base_units must be positive")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps({"in": self.input_mint, "out": self.output_mint, "amount": str(self.amount_base_units), "wallet": self.user_wallet, "slippage_bps": self.slippage_bps, "mode": self.swap_mode.value}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

@dataclass(frozen=True)
class NormalizedQuote:
    provider: str
    request_fingerprint: str
    raw_response_hash: str
    external_id: str
    input_mint: str
    output_mint: str
    input_amount: int
    expected_output: int
    minimum_output: Optional[int]
    minimum_output_state: MinimumOutputState
    swap_mode: SwapMode
    slippage_bps: int
    route_provenance: tuple[str, ...]
    dex_sources: tuple[str, ...]
    price_impact_pct: Optional[str]
    provider_fee: Optional[str]
    platform_fee: Optional[str]
    context_slot: Optional[int]
    received_at: datetime
    expires_at: Optional[datetime]
    artifact_kind: ExecutionArtifactKind
    capabilities: ProviderCapabilities
    diagnostic_trace_id: str
    conservative_net_result: Optional[int] = None

    def is_fresh(self, now: Optional[datetime] = None) -> bool:
        return self.expires_at is None or (now or datetime.now(timezone.utc)) < self.expires_at

    def dedupe_key(self) -> tuple[Any, ...]:
        bucket = None if self.expires_at is None else int(self.expires_at.timestamp() // 10)
        return (self.request_fingerprint, self.input_mint, self.output_mint, self.input_amount, self.swap_mode.value, self.slippage_bps, bucket, self.route_provenance)

@dataclass(frozen=True)
class RawInstructionArtifact:
    capabilities: ProviderCapabilities
    instructions: tuple[Any, ...]
    lookup_table_addresses: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        if not self.capabilities.admits_raw_instructions():
            raise TypeError("only executable RAW_INSTRUCTIONS capabilities may create raw instruction artifacts")

@dataclass(frozen=True)
class AssembledTransactionArtifact:
    capabilities: ProviderCapabilities
    transaction_base64_hash: str
    def __post_init__(self) -> None:
        if self.capabilities.artifact_kind is not ExecutionArtifactKind.ASSEMBLED_TRANSACTION:
            raise TypeError("assembled artifacts require ASSEMBLED_TRANSACTION capability")

@dataclass(frozen=True)
class DiscoveryResult:
    discovery_candidates: tuple[NormalizedQuote, ...]
    executable_candidates: tuple[NormalizedQuote, ...]
    non_selection_reasons: dict[str, NonSelectionReason] = field(default_factory=dict)
