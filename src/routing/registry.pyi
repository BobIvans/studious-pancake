from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from src.providers.jupiter.quota import JupiterQuotaManager

from .circuit import ProviderCircuit
from .models import (
    DiscoveryBatch,
    DiscoveryResult,
    NonSelectionReason,
    NormalizedQuote,
    ProviderCapabilities,
    ProviderStatus,
    QuoteRequest,
)
from .transport import Transport


class DiscoveryProvider(Protocol):
    provider_id: str
    capabilities: ProviderCapabilities
    circuit: ProviderCircuit

    def startup_state(self) -> dict[str, str]: ...
    def status(self) -> ProviderStatus: ...
    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote: ...


@dataclass(frozen=True)
class CandidateSelection:
    selected: NormalizedQuote | None
    reasons: dict[str, NonSelectionReason]


class ProviderRegistry:
    adapters: tuple[DiscoveryProvider, ...]

    def __init__(self, adapters: tuple[DiscoveryProvider, ...]) -> None: ...

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        transport: Transport | None = ...,
        jupiter_quota: JupiterQuotaManager | None = ...,
        contract_registry: Any = ...,
    ) -> ProviderRegistry: ...

    def startup_report(self) -> tuple[dict[str, str], ...]: ...
    def enabled_adapters(self) -> tuple[DiscoveryProvider, ...]: ...


class DiscoveryPlane:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        provider_timeout_seconds: float = ...,
    ) -> None: ...

    async def discover(self, request: QuoteRequest) -> DiscoveryBatch: ...


class RouteDiscoveryService:
    def __init__(self, registry: ProviderRegistry) -> None: ...
    async def discover(self, request: QuoteRequest) -> DiscoveryBatch: ...

    def classify(
        self,
        quotes: tuple[NormalizedQuote, ...],
        now: datetime | None = ...,
    ) -> DiscoveryResult: ...

    def select_executable(
        self,
        quotes: tuple[NormalizedQuote, ...],
    ) -> CandidateSelection: ...
