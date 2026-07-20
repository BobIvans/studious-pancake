"""Network-capable provider clients for the PR-030 discovery plane.

The older ``adapters`` module remains the normalization compatibility layer.
These clients add one shared transport, bounded calls, strict network-response
validation and typed failure reporting without creating another execution path.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timezone
from typing import Any

from .adapters import (
    JupiterRouterAdapter as _JupiterNormalizer,
    OdosAdapter as _OdosNormalizer,
    OkxDexAdapter as _OkxNormalizer,
    OpenOceanAdapter as _OpenOceanNormalizer,
)
from .models import (
    NormalizedQuote,
    ProviderFailureReason,
    ProviderHealth,
    ProviderRole,
    ProviderStatus,
    QuoteFee,
    QuoteProvenance,
    QuoteRequest,
)
from .transport import SanitizedTransportError, Transport
from .utils import raw_hash, require_base58, require_base64


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        provider: str,
        reason: ProviderFailureReason,
        detail: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"{provider}: {detail}")
        self.provider = provider
        self.reason = reason
        self.detail = detail
        self.retryable = retryable
        self.status_code = status_code


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _instruction(value: Any, label: str) -> None:
    instruction = _mapping(value, label)
    require_base58(instruction.get("programId", ""), f"{label}.programId")
    require_base64(instruction.get("data", ""), f"{label}.data")
    for index, account in enumerate(
        _sequence(instruction.get("accounts", []), f"{label}.accounts")
    ):
        account = _mapping(account, f"{label}.accounts[{index}]")
        require_base58(account.get("pubkey", ""), "account pubkey")
        if not isinstance(account.get("isSigner"), bool):
            raise ValueError("account isSigner must be bool")
        if not isinstance(account.get("isWritable"), bool):
            raise ValueError("account isWritable must be bool")


def _slot(value: Any) -> int | None:
    if value is None:
        return None
    result = int(value)
    if result < 0:
        raise ValueError("context slot cannot be negative")
    return result


def _correlation(provider: str, sources: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                f"aggregator:{provider}",
                *(f"underlying:{source.lower()}" for source in sources),
            )
        )
    )


class _NetworkClientMixin:
    endpoint: str
    transport: Transport | None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.provider_id,
            health=self.circuit.health,
            role=self.capabilities.role,
            capability=self.capabilities.discovery_capability,
            reason=self.capabilities.admission_reason,
        )

    def startup_state(self) -> dict[str, str]:
        row = super().startup_state()
        row["capability"] = self.capabilities.discovery_capability.value
        if self.circuit.health is ProviderHealth.DISABLED_MISSING_CREDENTIALS:
            row["state"] = "disabled_missing_credentials"
        return row

    async def _request_json(
        self,
        method: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.capabilities.role is ProviderRole.DISABLED:
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.DISABLED,
                self.capabilities.admission_reason,
                retryable=False,
            )
        if self.transport is None:
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.TRANSPORT,
                "transport is not configured",
                retryable=False,
            )
        if not self.circuit.can_call():
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.CIRCUIT_OPEN,
                "provider circuit is open",
                retryable=True,
            )
        limiter = getattr(self, "limiter", None)
        if limiter is not None and not limiter.allow():
            self.circuit.record_failure(ProviderHealth.RATE_LIMITED)
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.RATE_LIMITED,
                "provider request budget is exhausted",
                retryable=True,
            )

        try:
            status, _, payload = await self.transport.request(
                method,
                self.endpoint,
                headers=headers,
                params=params,
                json_body=body,
            )
        except asyncio.CancelledError:
            raise
        except SanitizedTransportError as exc:
            self.circuit.record_failure()
            reason = (
                ProviderFailureReason.TIMEOUT
                if "timed out" in str(exc)
                else ProviderFailureReason.TRANSPORT
            )
            raise ProviderRequestError(
                self.provider_id,
                reason,
                "sanitized transport failure",
                retryable=exc.retryable,
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            self.circuit.record_failure()
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.TRANSPORT,
                "unexpected transport failure",
                retryable=True,
            ) from exc

        if status == 429:
            self.circuit.record_failure(ProviderHealth.RATE_LIMITED)
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.RATE_LIMITED,
                "provider returned HTTP 429",
                retryable=True,
                status_code=status,
            )
        if not 200 <= status < 300:
            self.circuit.record_failure()
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.HTTP_ERROR,
                f"provider returned HTTP {status}",
                retryable=status >= 500,
                status_code=status,
            )
        if not isinstance(payload, dict):
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.INVALID_SCHEMA,
                "provider response must be a JSON object",
                retryable=False,
            )
        return payload

    def _enrich(
        self,
        quote: NormalizedQuote,
        request: QuoteRequest,
        payload: dict[str, Any],
        *,
        sources: tuple[str, ...],
        context_slot: int | None,
        fees: tuple[QuoteFee, ...] = (),
    ) -> NormalizedQuote:
        correlation = _correlation(self.provider_id, sources)
        response_hash = raw_hash(payload)
        return replace(
            quote,
            input_decimals=request.input_decimals,
            output_decimals=request.output_decimals,
            context_slot=context_slot,
            correlation_labels=correlation,
            fees=fees,
            provenance=QuoteProvenance(
                provider=self.provider_id,
                endpoint=self.endpoint,
                schema_version_pin=self.capabilities.schema_version_pin,
                response_hash=response_hash,
                provider_request_id=quote.external_id,
                context_slot=context_slot,
                correlation_labels=correlation,
            ),
        )


class JupiterRouterAdapter(_NetworkClientMixin, _JupiterNormalizer):
    endpoint = "https://api.jup.ag/swap/v2/build"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        require_api_key: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key
        if require_api_key and not api_key:
            self.capabilities = replace(
                self.capabilities,
                role=ProviderRole.DISABLED,
                admission_reason=(
                    "disabled_missing_credentials: JUPITER_API_KEY required"
                ),
            )
            self.circuit.health = ProviderHealth.DISABLED_MISSING_CREDENTIALS

    def build_params(self, request: QuoteRequest) -> dict[str, str]:
        return {
            "inputMint": request.input_mint,
            "outputMint": request.output_mint,
            "amount": str(request.amount_base_units),
            "taker": request.user_wallet,
            "slippageBps": str(request.slippage_bps),
        }

    @staticmethod
    def _validate_artifacts(payload: dict[str, Any]) -> None:
        _instruction(payload.get("swapInstruction"), "swapInstruction")
        for field in (
            "computeBudgetInstructions",
            "setupInstructions",
            "otherInstructions",
        ):
            for index, instruction in enumerate(
                _sequence(payload.get(field, []), field)
            ):
                _instruction(instruction, f"{field}[{index}]")
        cleanup = payload.get("cleanupInstruction")
        if cleanup is not None:
            _instruction(cleanup, "cleanupInstruction")
        if not isinstance(payload.get("blockhashWithMetadata"), dict):
            raise ValueError("blockhashWithMetadata is required")
        addresses = payload.get("addressesByLookupTableAddress")
        if addresses is not None and not isinstance(addresses, dict):
            raise ValueError("lookup-table mapping must be an object")

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote:
        if not self.api_key:
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.DISABLED,
                "Jupiter API key is not configured",
                retryable=False,
            )
        payload = await self._request_json(
            "GET",
            headers={"x-api-key": self.api_key},
            params=self.build_params(request),
        )
        try:
            self._validate_artifacts(payload)
            quote = self.normalize_build(request, payload)
            context_slot = _slot(payload.get("contextSlot"))
            fee = payload.get("platformFee")
            fees = (
                (
                    QuoteFee(
                        "platform",
                        rate=str(fee),
                        source_field="platformFee",
                    ),
                )
                if fee is not None
                else ()
            )
            result = self._enrich(
                quote,
                request,
                payload,
                sources=quote.dex_sources,
                context_slot=context_slot,
                fees=fees,
            )
        except (TypeError, ValueError, KeyError) as exc:
            self.circuit.record_failure()
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.INVALID_SCHEMA,
                "Jupiter response failed schema validation",
                retryable=False,
            ) from exc
        self.circuit.record_success()
        return result


class OkxDexAdapter(_NetworkClientMixin, _OkxNormalizer):
    endpoint = "https://web3.okx.com/api/v6/dex/aggregator/swap-instruction"

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote:
        params = self.build_params(request)
        timestamp = (
            self.clock.now()
            .astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        payload = await self._request_json(
            "GET",
            headers=self.auth_headers(timestamp, params),
            params=params,
        )
        try:
            data = payload.get("data")
            data = data[0] if isinstance(data, list) else data
            data = _mapping(data, "data")
            router = _mapping(data.get("routerResult"), "routerResult")
            if (
                router.get("minReceiveAmount") is not None
                and not isinstance(router.get("tx"), dict)
            ):
                router["tx"] = {
                    "minReceiveAmount": router["minReceiveAmount"]
                }
            instructions = _sequence(
                data.get("instructionLists"), "instructionLists"
            )
            if not instructions:
                raise ValueError("instructionLists cannot be empty")
            for index, instruction in enumerate(instructions):
                _instruction(instruction, f"instructionLists[{index}]")
            for address in _sequence(
                data.get("addressLookupTableAccount", []),
                "addressLookupTableAccount",
            ):
                require_base58(address, "lookup table address")
            quote = self.normalize(request, payload)
            context_slot = _slot(
                data.get("contextSlot") or router.get("contextSlot")
            )
            fee = router.get("tradeFee") or router.get("estimateGasFee")
            result = self._enrich(
                quote,
                request,
                payload,
                sources=quote.dex_sources,
                context_slot=context_slot,
                fees=(
                    (
                        QuoteFee(
                            "provider",
                            rate=str(fee),
                            source_field="tradeFee/estimateGasFee",
                        ),
                    )
                    if fee is not None
                    else ()
                ),
            )
        except (TypeError, ValueError, KeyError, AssertionError) as exc:
            self.circuit.record_failure()
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.INVALID_SCHEMA,
                "OKX response failed schema validation",
                retryable=False,
            ) from exc
        self.circuit.record_success()
        return result


class OpenOceanAdapter(_NetworkClientMixin, _OpenOceanNormalizer):
    endpoint = "https://open-api.openocean.finance/v4/solana/quote"

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote:
        payload = await self._request_json(
            "GET",
            headers={"x-api-key": self.api_key or ""},
            params={
                "inTokenAddress": request.input_mint,
                "outTokenAddress": request.output_mint,
                "amountDecimals": str(request.amount_base_units),
                "slippage": str(request.slippage_bps / 100),
                "account": request.user_wallet,
            },
        )
        try:
            data = _mapping(payload.get("data", payload), "OpenOcean response")
            quote = self.normalize(request, data)
            result = self._enrich(
                quote,
                request,
                payload,
                sources=quote.dex_sources,
                context_slot=_slot(data.get("contextSlot")),
                fees=(
                    QuoteFee(
                        "provider",
                        rate=quote.provider_fee,
                        source_field="fee",
                    ),
                ),
            )
        except (TypeError, ValueError, KeyError) as exc:
            self.circuit.record_failure()
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.INVALID_SCHEMA,
                "OpenOcean response failed schema validation",
                retryable=False,
            ) from exc
        self.circuit.record_success()
        return result


class OdosAdapter(_NetworkClientMixin, _OdosNormalizer):
    endpoint = "https://solana-beta-api.odos.xyz/sor/quote/v3"

    async def request_quote(self, request: QuoteRequest) -> NormalizedQuote:
        payload = await self._request_json(
            "POST",
            body=self.quote_body(request),
        )
        try:
            quote = self.normalize_quote(request, payload)
            result = self._enrich(
                quote,
                request,
                payload,
                sources=quote.dex_sources,
                context_slot=_slot(payload.get("contextSlot")),
            )
        except (TypeError, ValueError, KeyError) as exc:
            self.circuit.record_failure()
            raise ProviderRequestError(
                self.provider_id,
                ProviderFailureReason.INVALID_SCHEMA,
                "Odos response failed schema validation",
                retryable=False,
            ) from exc
        self.circuit.record_success()
        return result
