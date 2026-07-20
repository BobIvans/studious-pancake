"""Provider registry and failure-isolated discovery orchestration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

from src.providers.jupiter.quota import (
    JupiterQuotaError,
    JupiterQuotaManager,
    JupiterQuotaPurpose,
)

from .adapters import ProviderAdapter
from .clients import (
    JupiterRouterAdapter,
    OdosAdapter,
    OkxDexAdapter,
    OpenOceanAdapter,
    ProviderRequestError,
)
from .models import (
    DiscoveryBatch,
    DiscoveryResult,
    MinimumOutputState,
    NonSelectionReason,
    NormalizedQuote,
    ProviderFailure,
    ProviderFailureReason,
    ProviderRole,
    QuoteRequest,
)
from .transport import Transport

_LOAD_DEFAULT_CONTRACT_REGISTRY = object()
_PROVIDER_CONTRACT_NAMES = {
    "jupiter_router": "jupiter",
    "okx_dex": "okx",
    "openocean": "openocean",
    "odos": "odos",
}


def _load_default_contract_registry() -> Any | None:
    try:
        from src.external_contracts.registry import ExternalContractRegistry
    except ModuleNotFoundError:
        return None
    return ExternalContractRegistry.load_default()


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _bind_contract_admission(adapter: ProviderAdapter, registry: Any) -> None:
    provider = _PROVIDER_CONTRACT_NAMES[adapter.provider_id]
    entries = tuple(registry.provider(provider))
    if len(entries) != 1:
        adapter.capabilities = replace(
            adapter.capabilities,
            role=ProviderRole.DISABLED,
            admission_reason=(
                "disabled_contract_registry: expected one provider contract"
            ),
        )
        return

    contract = entries[0]
    status = _enum_value(contract.status)
    capabilities = {_enum_value(item) for item in contract.capabilities}
    if status == "active" and "composable-instructions" in capabilities:
        contract_role = ProviderRole.EXECUTABLE
    elif status in {"active", "discovery-only"} and "quote" in capabilities:
        contract_role = ProviderRole.DISCOVERY_ONLY
    else:
        contract_role = ProviderRole.DISABLED

    current_role = adapter.capabilities.role
    role = (
        ProviderRole.DISABLED
        if current_role is ProviderRole.DISABLED
        else contract_role
    )
    reason = (
        adapter.capabilities.admission_reason
        if current_role is ProviderRole.DISABLED
        else f"contract_registry:{contract.id}:{status}"
    )
    adapter.capabilities = replace(
        adapter.capabilities,
        role=role,
        schema_version_pin=f"{contract.id}@{contract.source_ref}",
        admission_reason=reason,
    )


@dataclass(frozen=True)
class CandidateSelection:
    selected: NormalizedQuote | None
    reasons: dict[str, NonSelectionReason]


class ProviderRegistry:
    def __init__(self, adapters: tuple[ProviderAdapter, ...]):
        provider_ids = [adapter.provider_id for adapter in adapters]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider registry contains duplicate provider IDs")
        self.adapters = adapters

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        transport: Transport | None = None,
        jupiter_quota: JupiterQuotaManager | None = None,
        contract_registry: Any = _LOAD_DEFAULT_CONTRACT_REGISTRY,
    ) -> "ProviderRegistry":
        adapters = (
            JupiterRouterAdapter(
                api_key=env.get("JUPITER_API_KEY"),
                require_api_key=False,
                transport=transport,
                jupiter_quota=jupiter_quota,
            ),
            OkxDexAdapter(
                api_key=env.get("OKX_API_KEY"),
                passphrase=env.get("OKX_PASSPHRASE"),
                secret=env.get("OKX_SECRET_KEY"),
                transport=transport,
            ),
            OpenOceanAdapter(
                api_key=env.get("OPENOCEAN_API_KEY"),
                transport=transport,
            ),
            OdosAdapter(transport=transport),
        )
        active_contract_registry = (
            _load_default_contract_registry()
            if contract_registry is _LOAD_DEFAULT_CONTRACT_REGISTRY
            else contract_registry
        )
        if active_contract_registry is not None:
            for adapter in adapters:
                _bind_contract_admission(adapter, active_contract_registry)
        return cls(adapters)

    def startup_report(self) -> tuple[dict[str, str], ...]:
        rows: list[dict[str, str]] = []
        for adapter in self.adapters:
            row = adapter.startup_state()
            if (
                adapter.capabilities.role is ProviderRole.DISABLED
                and row["state"] != "disabled_missing_credentials"
            ):
                row["state"] = "disabled_contract"
            rows.append(row)
        return tuple(rows)

    def enabled_adapters(self) -> tuple[ProviderAdapter, ...]:
        return tuple(
            adapter
            for adapter in self.adapters
            if adapter.capabilities.role is not ProviderRole.DISABLED
        )


class DiscoveryPlane:
    """Call enabled providers concurrently without coupling their failures."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        provider_timeout_seconds: float = 8.0,
    ) -> None:
        if provider_timeout_seconds <= 0:
            raise ValueError("provider_timeout_seconds must be positive")
        self.registry = registry
        self.provider_timeout_seconds = provider_timeout_seconds

    async def _call_provider(
        self,
        adapter: ProviderAdapter,
        request: QuoteRequest,
    ) -> NormalizedQuote | ProviderFailure:
        if (
            adapter.provider_id == "jupiter_router"
            and getattr(adapter, "api_key", None)
        ):
            quota = getattr(adapter, "quota", None)
            if quota is None:
                quota = JupiterQuotaManager()
                adapter.quota = quota
            try:
                reservation = await quota.reserve(
                    JupiterQuotaPurpose.DISCOVERY,
                    request_fingerprint=request.fingerprint,
                )
            except JupiterQuotaError as exc:
                return ProviderFailure(
                    provider=adapter.provider_id,
                    reason=ProviderFailureReason.RATE_LIMITED,
                    retryable=True,
                    detail=exc.reason,
                )
            await quota.mark_used(reservation)

        try:
            return await asyncio.wait_for(
                adapter.request_quote(request),
                timeout=self.provider_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            adapter.circuit.record_failure()
            return ProviderFailure(
                provider=adapter.provider_id,
                reason=ProviderFailureReason.TIMEOUT,
                retryable=True,
                detail="provider quote deadline exceeded",
            )
        except ProviderRequestError as exc:
            if (
                adapter.provider_id == "jupiter_router"
                and exc.status_code == 429
                and getattr(adapter, "quota", None) is not None
            ):
                adapter.quota.record_http_429()
            return ProviderFailure(
                provider=adapter.provider_id,
                reason=exc.reason,
                retryable=exc.retryable,
                detail=exc.detail,
                status_code=exc.status_code,
            )
        except Exception:
            adapter.circuit.record_failure()
            return ProviderFailure(
                provider=adapter.provider_id,
                reason=ProviderFailureReason.INVALID_SCHEMA,
                retryable=False,
                detail="provider failed closed with an unexpected response",
            )

    async def discover(self, request: QuoteRequest) -> DiscoveryBatch:
        adapters = self.registry.enabled_adapters()
        results = await asyncio.gather(
            *(self._call_provider(adapter, request) for adapter in adapters)
        )
        quotes: list[NormalizedQuote] = []
        failures: list[ProviderFailure] = []
        for result in results:
            if isinstance(result, NormalizedQuote):
                quotes.append(result)
            else:
                failures.append(result)
        statuses = tuple(adapter.status() for adapter in self.registry.adapters)
        return DiscoveryBatch(
            request_fingerprint=request.fingerprint,
            quotes=tuple(quotes),
            failures=tuple(failures),
            statuses=statuses,
        )


class RouteDiscoveryService:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry
        self.plane = DiscoveryPlane(registry)

    async def discover(self, request: QuoteRequest) -> DiscoveryBatch:
        return await self.plane.discover(request)

    def classify(
        self,
        quotes: tuple[NormalizedQuote, ...],
        now: datetime | None = None,
    ) -> DiscoveryResult:
        discovery: list[NormalizedQuote] = []
        executable: list[NormalizedQuote] = []
        reasons: dict[str, NonSelectionReason] = {}
        seen: set[tuple[object, ...]] = set()
        for quote in quotes:
            key = quote.dedupe_key()
            if key in seen:
                reasons[quote.external_id] = NonSelectionReason.DUPLICATE
                continue
            seen.add(key)
            if not quote.is_fresh(now):
                reasons[quote.external_id] = NonSelectionReason.STALE
                discovery.append(quote)
                continue
            discovery.append(quote)
            if quote.minimum_output_state is not MinimumOutputState.PROVEN:
                reasons[quote.external_id] = NonSelectionReason.UNPROVEN_MIN_OUTPUT
                continue
            if (
                not quote.capabilities.admits_raw_instructions()
                or quote.artifact_kind is not quote.capabilities.artifact_kind
            ):
                reasons[quote.external_id] = NonSelectionReason.NON_COMPOSABLE
                continue
            executable.append(quote)
        return DiscoveryResult(tuple(discovery), tuple(executable), reasons)

    def select_executable(
        self,
        quotes: tuple[NormalizedQuote, ...],
    ) -> CandidateSelection:
        now = max((quote.received_at for quote in quotes), default=None)
        result = self.classify(quotes, now=now)
        reasons = dict(result.non_selection_reasons)
        candidates = [
            quote
            for quote in result.executable_candidates
            if quote.conservative_net_result is not None
        ]
        for quote in result.executable_candidates:
            if quote.conservative_net_result is None:
                reasons[quote.external_id] = NonSelectionReason.MISSING_COST
        if not candidates:
            return CandidateSelection(None, reasons)
        selected = max(
            candidates,
            key=lambda quote: quote.conservative_net_result or -(10**30),
        )
        for quote in candidates:
            if quote is not selected:
                reasons[quote.external_id] = NonSelectionReason.LOWER_CONSERVATIVE_NET
        return CandidateSelection(selected, reasons)
