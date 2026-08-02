"""Canonical provider-routing semantic models.

MPR-041 replaces the active V1 quote meaning with a lossless V2 contract while
retaining the historical ``NormalizedQuote`` import as an alias.  Active
routing code consumes typed fees, exact dimensions and a conserved route graph;
legacy display strings remain diagnostic compatibility inputs only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any, Optional

from .dimensions import (
    BasisPoints,
    DimensionError,
    PercentMicros,
    Slot,
    TokenDecimals,
    exact_non_negative_int,
    exact_positive_int,
)
from .route_graph import OpportunityResourceFootprint, RouteGraph

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_NORMALIZATION_VERSION = "canonical-quote-v2"


class ProviderCapability(str, Enum):
    QUOTE_ONLY = "quote_only"
    COMPOSABLE_INSTRUCTIONS = "composable_instructions"
    IMMUTABLE_TRANSACTION = "immutable_transaction"


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


class ProviderFailureReason(str, Enum):
    DISABLED = "disabled"
    CIRCUIT_OPEN = "circuit_open"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    HTTP_ERROR = "http_error"
    INVALID_SCHEMA = "invalid_schema"
    CANCELLED = "cancelled"


class AuthKind(str, Enum):
    API_KEY = "api_key"
    HMAC = "hmac"
    NONE = "none"


class SemanticState(StrEnum):
    PROVEN = "proven"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class MinimumOutputState(str, Enum):
    PROVEN = "proven"
    UNPROVEN = "minimum_output_unproven"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class SwapMode(str, Enum):
    EXACT_IN = "ExactIn"
    EXACT_OUT = "ExactOut"


class GuaranteeSource(StrEnum):
    PROVIDER_THRESHOLD = "provider_threshold"
    PROVIDER_MIN_RECEIVE = "provider_min_receive"
    UNAVAILABLE = "unavailable"


class FreshnessSource(StrEnum):
    PROVIDER_NATIVE = "provider_native"
    REVIEWED_CONTRACT_TTL = "reviewed_contract_ttl"
    ABSENT = "absent"


class EchoProofState(StrEnum):
    PROVEN = "proven"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


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
    INVALID_ROUTE_GRAPH = "invalid_route_graph"
    UNPROVEN_RESPONSE_ECHO = "unproven_response_echo"


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

    @property
    def discovery_capability(self) -> ProviderCapability:
        if self.artifact_kind is ExecutionArtifactKind.RAW_INSTRUCTIONS:
            return ProviderCapability.COMPOSABLE_INSTRUCTIONS
        if self.artifact_kind is ExecutionArtifactKind.ASSEMBLED_TRANSACTION:
            return ProviderCapability.IMMUTABLE_TRANSACTION
        return ProviderCapability.QUOTE_ONLY

    def admits_raw_instructions(self) -> bool:
        return (
            self.role is ProviderRole.EXECUTABLE
            and self.discovery_capability is ProviderCapability.COMPOSABLE_INSTRUCTIONS
        )


@dataclass(frozen=True)
class QuoteRequest:
    input_mint: str
    output_mint: str
    amount_base_units: int
    user_wallet: str
    slippage_bps: int
    swap_mode: SwapMode = SwapMode.EXACT_IN
    input_decimals: int | None = None
    output_decimals: int | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("input_mint", self.input_mint),
            ("output_mint", self.output_mint),
            ("user_wallet", self.user_wallet),
        ):
            if not isinstance(value, str) or not _BASE58_RE.fullmatch(value):
                raise ValueError(f"invalid base58 {label}")
        if self.input_mint == self.output_mint:
            raise ValueError("input_mint and output_mint must differ")
        try:
            exact_positive_int(self.amount_base_units, "amount_base_units")
            BasisPoints(self.slippage_bps)
            if self.input_decimals is not None:
                TokenDecimals(self.input_decimals)
            if self.output_decimals is not None:
                TokenDecimals(self.output_decimals)
        except DimensionError as exc:
            raise ValueError(str(exc)) from exc
        if not isinstance(self.swap_mode, SwapMode):
            raise ValueError("swap_mode must be a SwapMode")

    @property
    def slippage(self) -> BasisPoints:
        return BasisPoints(self.slippage_bps)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "in": self.input_mint,
                "out": self.output_mint,
                "amount": str(self.amount_base_units),
                "wallet": self.user_wallet,
                "slippage_bps": self.slippage_bps,
                "mode": self.swap_mode.value,
                "input_decimals": self.input_decimals,
                "output_decimals": self.output_decimals,
                "semantic_version": _NORMALIZATION_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class QuoteFeeComponent:
    kind: str
    amount_base_units: int | None = None
    mint: str | None = None
    rate: str | None = None
    source_field: str | None = None
    payer: str | None = None
    recipient: str | None = None
    inclusion_state: SemanticState = SemanticState.UNKNOWN
    original_provider_text: str | None = None
    rate_percent_micros: PercentMicros | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("fee kind is required")
        if self.amount_base_units is not None:
            exact_non_negative_int(self.amount_base_units, "fee.amount_base_units")
        if self.mint is not None and (
            not isinstance(self.mint, str) or not _BASE58_RE.fullmatch(self.mint)
        ):
            raise ValueError("fee mint must be base58")
        state = self.inclusion_state
        if not isinstance(state, SemanticState):
            state = SemanticState(state)
            object.__setattr__(self, "inclusion_state", state)
        if self.rate is not None and self.rate_percent_micros is None:
            if self.rate.strip().lower() in {"unknown", "unavailable", "n/a"}:
                object.__setattr__(self, "inclusion_state", SemanticState.UNAVAILABLE)
            else:
                try:
                    object.__setattr__(
                        self,
                        "rate_percent_micros",
                        PercentMicros.parse(self.rate, "fee.rate"),
                    )
                except DimensionError:
                    if state is SemanticState.PROVEN:
                        raise
        if self.original_provider_text is None and self.rate is not None:
            object.__setattr__(self, "original_provider_text", self.rate)

    @property
    def semantic_rate_text(self) -> str | None:
        if self.rate_percent_micros is None:
            return None
        return self.rate_percent_micros.to_decimal_text()


# Historical import retained as a compatibility alias.  Active code uses the
# richer semantics of QuoteFeeComponent.
QuoteFee = QuoteFeeComponent


@dataclass(frozen=True)
class QuoteProvenance:
    provider: str
    endpoint: str
    schema_version_pin: str
    response_hash: str
    provider_request_id: str | None = None
    context_slot: int | None = None
    provider_timestamp: datetime | None = None
    correlation_labels: tuple[str, ...] = ()
    request_fingerprint: str | None = None
    normalization_version: str = _NORMALIZATION_VERSION
    raw_field_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalQuoteV2:
    # Positional field order intentionally preserves the former NormalizedQuote
    # constructor so archived fixtures and report-only consumers can migrate
    # without creating a second active semantic implementation.
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
    input_decimals: int | None = None
    output_decimals: int | None = None
    provider_timestamp: datetime | None = None
    correlation_labels: tuple[str, ...] = ()
    fees: tuple[QuoteFeeComponent, ...] = ()
    provenance: QuoteProvenance | None = None
    route_graph: RouteGraph | None = None
    guarantee_source: GuaranteeSource = GuaranteeSource.UNAVAILABLE
    freshness_source: FreshnessSource = FreshnessSource.ABSENT
    response_echo_state: EchoProofState = EchoProofState.UNAVAILABLE
    normalization_version: str = _NORMALIZATION_VERSION
    provider_contract_generation: str | None = None
    price_impact_percent_micros: PercentMicros | None = None
    semantic_quote_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider:
            raise ValueError("provider is required")
        if (
            not isinstance(self.request_fingerprint, str)
            or not self.request_fingerprint
        ):
            raise ValueError("request_fingerprint is required")
        if not isinstance(self.raw_response_hash, str) or not self.raw_response_hash:
            raise ValueError("raw_response_hash is required")
        if self.input_mint == self.output_mint:
            raise ValueError("canonical quote cannot be a self-swap")
        exact_positive_int(self.input_amount, "quote.input_amount")
        exact_positive_int(self.expected_output, "quote.expected_output")
        BasisPoints(self.slippage_bps)
        if self.minimum_output is not None:
            exact_positive_int(self.minimum_output, "quote.minimum_output")
        if self.minimum_output_state is MinimumOutputState.PROVEN:
            if self.minimum_output is None:
                raise ValueError("proven minimum output requires a value")
            if self.minimum_output > self.expected_output:
                raise ValueError("minimum_output cannot exceed expected_output")
        if self.context_slot is not None:
            Slot(self.context_slot)
        if self.input_decimals is not None:
            TokenDecimals(self.input_decimals)
        if self.output_decimals is not None:
            TokenDecimals(self.output_decimals)
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at must be timezone-aware")
            if self.expires_at <= self.received_at:
                raise ValueError("expires_at must be after received_at")
        if (
            self.provider_timestamp is not None
            and self.provider_timestamp.tzinfo is None
        ):
            raise ValueError("provider_timestamp must be timezone-aware")
        if not isinstance(self.capabilities, ProviderCapabilities):
            raise ValueError("capabilities must be ProviderCapabilities")
        if self.provider_contract_generation is None:
            object.__setattr__(
                self,
                "provider_contract_generation",
                self.capabilities.schema_version_pin,
            )
        if (
            self.expires_at is not None
            and self.freshness_source is FreshnessSource.ABSENT
        ):
            object.__setattr__(
                self, "freshness_source", FreshnessSource.REVIEWED_CONTRACT_TTL
            )
        route_labels = tuple(self.route_provenance)
        dex_sources = tuple(self.dex_sources)
        object.__setattr__(self, "route_provenance", route_labels)
        object.__setattr__(self, "dex_sources", dex_sources)
        object.__setattr__(self, "fees", tuple(self.fees))
        if self.route_graph is not None:
            if self.route_graph.input_mint != self.input_mint:
                raise ValueError("route graph input mint mismatch")
            if self.route_graph.output_mint != self.output_mint:
                raise ValueError("route graph output mint mismatch")
            if self.route_graph.input_amount != self.input_amount:
                raise ValueError("route graph input amount mismatch")
            if self.route_graph.expected_output != self.expected_output:
                raise ValueError("route graph expected output mismatch")
            if self.route_graph.guaranteed_output != self.minimum_output:
                raise ValueError("route graph guaranteed output mismatch")
        if (
            self.price_impact_pct is not None
            and self.price_impact_percent_micros is None
        ):
            try:
                object.__setattr__(
                    self,
                    "price_impact_percent_micros",
                    PercentMicros.parse(
                        self.price_impact_pct, "quote.price_impact_pct"
                    ),
                )
            except DimensionError as exc:
                raise ValueError(str(exc)) from exc
        semantic_payload = {
            "provider": self.provider,
            "request": self.request_fingerprint,
            "response": self.raw_response_hash,
            "contract_generation": self.provider_contract_generation,
            "normalization_version": self.normalization_version,
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "input_amount": str(self.input_amount),
            "expected_output": str(self.expected_output),
            "guaranteed_output": (
                None if self.minimum_output is None else str(self.minimum_output)
            ),
            "route_hash": (
                None if self.route_graph is None else self.route_graph.semantic_hash
            ),
        }
        object.__setattr__(
            self,
            "semantic_quote_id",
            hashlib.sha256(
                json.dumps(
                    semantic_payload, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        )

    @property
    def guaranteed_output(self) -> int | None:
        return self.minimum_output

    @property
    def fee_components(self) -> tuple[QuoteFeeComponent, ...]:
        return self.fees

    @property
    def resource_footprint(self) -> OpportunityResourceFootprint | None:
        if self.route_graph is None:
            return None
        return self.route_graph.resource_footprint

    def is_fresh(self, now: Optional[datetime] = None) -> bool:
        if self.expires_at is None or self.freshness_source is FreshnessSource.ABSENT:
            return False
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("freshness comparison requires timezone-aware time")
        return current < self.expires_at

    def dedupe_key(self) -> tuple[Any, ...]:
        bucket = int(self.expires_at.timestamp() // 10) if self.expires_at else None
        return (
            self.request_fingerprint,
            self.input_mint,
            self.output_mint,
            self.input_amount,
            self.swap_mode.value,
            self.slippage_bps,
            bucket,
            self.route_provenance,
            self.normalization_version,
        )


# The installed product has one quote class.  The old name is an import alias,
# not a parallel model or conversion authority.
NormalizedQuote = CanonicalQuoteV2


@dataclass(frozen=True)
class RawInstructionArtifact:
    capabilities: ProviderCapabilities
    instructions: tuple[Any, ...]
    lookup_table_addresses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capabilities.admits_raw_instructions():
            raise TypeError(
                "only executable RAW_INSTRUCTIONS capabilities may create "
                "raw instruction artifacts"
            )


@dataclass(frozen=True)
class AssembledTransactionArtifact:
    capabilities: ProviderCapabilities
    transaction_base64_hash: str

    def __post_init__(self) -> None:
        if (
            self.capabilities.artifact_kind
            is not ExecutionArtifactKind.ASSEMBLED_TRANSACTION
        ):
            raise TypeError(
                "assembled artifacts require ASSEMBLED_TRANSACTION capability"
            )


@dataclass(frozen=True)
class ProviderFailure:
    provider: str
    reason: ProviderFailureReason
    retryable: bool
    detail: str
    status_code: int | None = None


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    health: ProviderHealth
    role: ProviderRole
    capability: ProviderCapability
    reason: str


@dataclass(frozen=True)
class DiscoveryBatch:
    request_fingerprint: str
    quotes: tuple[CanonicalQuoteV2, ...]
    failures: tuple[ProviderFailure, ...] = ()
    statuses: tuple[ProviderStatus, ...] = ()


@dataclass(frozen=True)
class DiscoveryResult:
    discovery_candidates: tuple[CanonicalQuoteV2, ...]
    executable_candidates: tuple[CanonicalQuoteV2, ...]
    non_selection_reasons: dict[str, NonSelectionReason] = field(default_factory=dict)


__all__ = [
    "AssembledTransactionArtifact",
    "AuthKind",
    "CanonicalQuoteV2",
    "DiscoveryBatch",
    "DiscoveryResult",
    "EchoProofState",
    "ExecutionArtifactKind",
    "FreshnessSource",
    "GuaranteeSource",
    "MinimumOutputState",
    "NonSelectionReason",
    "NormalizedQuote",
    "ProviderCapabilities",
    "ProviderCapability",
    "ProviderFailure",
    "ProviderFailureReason",
    "ProviderHealth",
    "ProviderRole",
    "ProviderStatus",
    "QuoteFee",
    "QuoteFeeComponent",
    "QuoteProvenance",
    "QuoteRequest",
    "RawInstructionArtifact",
    "SemanticState",
    "SwapMode",
]
