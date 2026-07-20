from typing import Any

from src.providers.jupiter.quota import JupiterQuotaManager

from .adapters import ProviderAdapter
from .models import NormalizedQuote, ProviderStatus, QuoteRequest
from .transport import Transport


class ProviderRequestError(RuntimeError):
    provider: str
    reason: Any
    detail: str
    retryable: bool
    status_code: int | None


class JupiterRouterAdapter(ProviderAdapter):
    endpoint: str
    api_key: str | None
    quota: JupiterQuotaManager

    def __init__(
        self,
        api_key: str | None = ...,
        *,
        require_api_key: bool = ...,
        jupiter_quota: JupiterQuotaManager | None = ...,
        transport: Transport | None = ...,
        **kwargs: Any,
    ) -> None: ...

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote: ...
    def status(self) -> ProviderStatus: ...


class OkxDexAdapter(ProviderAdapter):
    endpoint: str

    def __init__(
        self,
        api_key: str | None = ...,
        passphrase: str | None = ...,
        secret: str | None = ...,
        *,
        transport: Transport | None = ...,
        **kwargs: Any,
    ) -> None: ...

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote: ...
    def status(self) -> ProviderStatus: ...


class OpenOceanAdapter(ProviderAdapter):
    endpoint: str

    def __init__(
        self,
        api_key: str | None = ...,
        *,
        transport: Transport | None = ...,
        **kwargs: Any,
    ) -> None: ...

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote: ...
    def status(self) -> ProviderStatus: ...


class OdosAdapter(ProviderAdapter):
    endpoint: str

    def __init__(
        self,
        *,
        transport: Transport | None = ...,
        **kwargs: Any,
    ) -> None: ...

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote: ...
    def status(self) -> ProviderStatus: ...
