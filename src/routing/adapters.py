"""Provider-specific normalization into the canonical MPR-041 semantic model."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode

from src.providers.jupiter.quota import JupiterQuotaManager

from .capabilities import *
from .circuit import ProviderCircuit
from .dimensions import (
    BasisPoints,
    exact_non_negative_int,
    exact_positive_int,
    serialize_provider_bps,
)
from .limiter import Clock, FixedWindowLimiter
from .models import *
from .route_graph import RouteEdge, RouteEdgeKind, RouteGraph
from .utils import raw_hash, require_base58, require_base64


class Transport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], Any]: ...


class ProviderAdapter:
    provider_id: str
    capabilities: ProviderCapabilities

    def __init__(
        self, *, transport: Transport | None = None, clock: Clock | None = None
    ) -> None:
        self.transport = transport
        self.clock = clock or Clock()
        self.circuit = ProviderCircuit(self.clock)

    def startup_state(self) -> dict[str, str]:
        state = (
            "ready"
            if self.capabilities.role is ProviderRole.EXECUTABLE
            else "discovery_only"
        )
        return {
            "provider": self.provider_id,
            "state": state,
            "reason": self.capabilities.admission_reason,
            "artifact_kind": self.capabilities.artifact_kind.value,
            "capability_pin": self.capabilities.schema_version_pin,
            "rate_policy": self.capabilities.rate_limit_policy,
        }

    def _expiry(
        self, payload: dict[str, Any]
    ) -> tuple[datetime | None, FreshnessSource]:
        now = self.clock.now()
        for key in ("expiresAt", "expiry", "expirationTime", "validUntil"):
            raw = payload.get(key)
            if raw is None:
                continue
            if isinstance(raw, str):
                text = raw.replace("Z", "+00:00")
                try:
                    value = datetime.fromisoformat(text)
                except ValueError as exc:
                    raise ValueError(f"invalid provider expiry field {key}") from exc
                if value.tzinfo is None:
                    raise ValueError(f"provider expiry field {key} lacks timezone")
            elif type(raw) is int:
                # Epoch seconds are accepted only as exact integers.
                value = datetime.fromtimestamp(raw, timezone.utc)
            else:
                raise ValueError(f"invalid provider expiry field {key}")
            if value <= now:
                raise ValueError("provider quote is already expired")
            return value, FreshnessSource.PROVIDER_NATIVE
        ttl = self.capabilities.quote_ttl_seconds
        if ttl is None:
            return None, FreshnessSource.ABSENT
        if type(ttl) is not int or ttl <= 0:
            raise ValueError("reviewed provider TTL must be a positive integer")
        return now + timedelta(seconds=ttl), FreshnessSource.REVIEWED_CONTRACT_TTL


class JupiterRouterAdapter(ProviderAdapter):
    provider_id = "jupiter_router"
    capabilities = JUPITER_CAPABILITIES

    def __init__(
        self,
        *,
        jupiter_quota: JupiterQuotaManager | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.quota = jupiter_quota or JupiterQuotaManager()

    @staticmethod
    def _route_graph(
        req: QuoteRequest,
        payload: dict[str, Any],
        *,
        out: int,
        minimum: int,
    ) -> RouteGraph:
        route_plan = payload.get("routePlan")
        if not isinstance(route_plan, list) or not route_plan:
            raise ValueError("missing jupiter route identity")

        edges: list[RouteEdge] = []
        produced_stage: dict[str, int] = {}
        branch_by_stage: dict[int, int] = {}
        single = len(route_plan) == 1
        for index, step in enumerate(route_plan):
            if not isinstance(step, dict):
                raise ValueError("jupiter routePlan entry must be an object")
            swap = step.get("swapInfo")
            if not isinstance(swap, dict):
                raise ValueError("jupiter routePlan.swapInfo must be an object")
            venue = swap.get("label")
            if not isinstance(venue, str) or not venue:
                raise ValueError("jupiter route venue label is required")
            input_mint = swap.get("inputMint") or (req.input_mint if single else None)
            output_mint = swap.get("outputMint") or (
                req.output_mint if single else None
            )
            if not isinstance(input_mint, str) or not isinstance(output_mint, str):
                raise ValueError("jupiter route hop mints are required")
            input_amount = exact_positive_int(
                swap.get("inAmount", req.amount_base_units if single else None),
                f"routePlan[{index}].swapInfo.inAmount",
            )
            output_amount = exact_positive_int(
                swap.get("outAmount", out if single else None),
                f"routePlan[{index}].swapInfo.outAmount",
            )
            if input_mint == req.input_mint:
                stage = 0
            elif input_mint in produced_stage:
                stage = produced_stage[input_mint]
            else:
                raise ValueError("jupiter route hop is not topologically connected")
            branch = branch_by_stage.get(stage, 0)
            branch_by_stage[stage] = branch + 1
            produced_stage[output_mint] = stage + 1
            bps_raw = step.get("bps")
            percent_raw = step.get("percent")
            if bps_raw is None and percent_raw is None:
                raise ValueError("jupiter route allocation is required")
            bps_value = (
                None
                if bps_raw is None
                else exact_non_negative_int(bps_raw, f"routePlan[{index}].bps")
            )
            percent_bps = (
                None
                if percent_raw is None
                else exact_non_negative_int(
                    percent_raw, f"routePlan[{index}].percent", maximum=100
                )
                * 100
            )
            if (
                bps_value is not None
                and percent_bps is not None
                and bps_value != percent_bps
            ):
                raise ValueError("jupiter route allocation fields disagree")
            allocation = BasisPoints(
                bps_value if bps_value is not None else percent_bps
            )
            pool_key = swap.get("ammKey")
            if not isinstance(pool_key, str) or not pool_key:
                raise ValueError("jupiter route ammKey is required")
            program_id = swap.get("programId")
            if program_id is not None and not isinstance(program_id, str):
                raise ValueError("jupiter route programId must be text")
            edges.append(
                RouteEdge(
                    stage=stage,
                    branch=branch,
                    kind=RouteEdgeKind.SWAP,
                    provider="jupiter_router",
                    venue=venue,
                    pool_key=pool_key,
                    program_id=program_id,
                    input_mint=input_mint,
                    output_mint=output_mint,
                    input_amount=input_amount,
                    output_amount=output_amount,
                    allocation_bps=allocation,
                    source_path=f"routePlan[{index}].swapInfo",
                )
            )
        return RouteGraph(
            provider="jupiter_router",
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            guaranteed_output=minimum,
            edges=tuple(edges),
            asset_generation=(f"decimals:{req.input_decimals}:{req.output_decimals}"),
        )

    def normalize_build(
        self, req: QuoteRequest, payload: dict[str, Any]
    ) -> NormalizedQuote:
        if payload.get("inputMint") != req.input_mint:
            raise ValueError("jupiter response input mint does not match request")
        if payload.get("outputMint") != req.output_mint:
            raise ValueError("jupiter response output mint does not match request")
        if str(payload.get("inAmount")) != str(req.amount_base_units):
            raise ValueError("jupiter response amount does not match request")
        if "swapMode" not in payload:
            raise ValueError("jupiter response swap mode echo is required")
        if payload["swapMode"] != req.swap_mode.value:
            raise ValueError("jupiter response swap mode does not match request")
        if "slippageBps" not in payload:
            raise ValueError("jupiter response slippage echo is required")
        response_slippage = exact_non_negative_int(
            payload["slippageBps"], "slippageBps", maximum=10_000
        )
        if response_slippage != req.slippage_bps:
            raise ValueError("jupiter response slippage does not match request")

        out = exact_positive_int(payload.get("outAmount"), "outAmount")
        minimum = exact_positive_int(
            payload.get("otherAmountThreshold"), "otherAmountThreshold"
        )
        graph = self._route_graph(req, payload, out=out, minimum=minimum)
        expires_at, freshness_source = self._expiry(payload)
        platform_fee = payload.get("platformFee")
        fees: tuple[QuoteFeeComponent, ...] = ()
        if platform_fee is not None:
            fees = (
                QuoteFeeComponent(
                    kind="platform",
                    rate=str(platform_fee),
                    source_field="platformFee",
                    inclusion_state=SemanticState.PROVEN,
                    original_provider_text=str(platform_fee),
                ),
            )
        response_hash = raw_hash(payload)
        external_id = payload.get("requestId") or response_hash[:16]
        return NormalizedQuote(
            provider=self.provider_id,
            request_fingerprint=req.fingerprint,
            raw_response_hash=response_hash,
            external_id=external_id,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            minimum_output=minimum,
            minimum_output_state=MinimumOutputState.PROVEN,
            swap_mode=req.swap_mode,
            slippage_bps=req.slippage_bps,
            route_provenance=(graph.semantic_hash,),
            dex_sources=graph.route_labels,
            price_impact_pct=(
                str(payload["priceImpactPct"])
                if payload.get("priceImpactPct") is not None
                else None
            ),
            provider_fee=None,
            platform_fee=(None if platform_fee is None else str(platform_fee)),
            context_slot=(
                None
                if payload.get("contextSlot") is None
                else int(payload["contextSlot"])
            ),
            received_at=self.clock.now(),
            expires_at=expires_at,
            artifact_kind=self.capabilities.artifact_kind,
            capabilities=self.capabilities,
            diagnostic_trace_id=external_id,
            input_decimals=req.input_decimals,
            output_decimals=req.output_decimals,
            fees=fees,
            route_graph=graph,
            guarantee_source=GuaranteeSource.PROVIDER_THRESHOLD,
            freshness_source=freshness_source,
            response_echo_state=EchoProofState.PROVEN,
        )


class OkxAuth:
    @staticmethod
    def canonical_query(params: dict[str, str]) -> str:
        return urlencode(sorted(params.items()))

    @staticmethod
    def sign(
        secret: str,
        timestamp: str,
        method: str,
        request_path_with_query: str,
        body: str = "",
    ) -> str:
        msg = f"{timestamp}{method.upper()}{request_path_with_query}{body}".encode()
        return base64.b64encode(
            hmac.new(secret.encode(), msg, hashlib.sha256).digest()
        ).decode()


class OkxDexAdapter(ProviderAdapter):
    provider_id = "okx_dex"
    capabilities = OKX_CAPABILITIES
    path = "/api/v6/dex/aggregator/swap-instruction"
    base_url = "https://web3.okx.com"

    def __init__(
        self,
        api_key: str | None = None,
        passphrase: str | None = None,
        secret: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key
        self.passphrase = passphrase
        self.secret = secret
        if not all((api_key, passphrase, secret)):
            self.capabilities = replace(
                self.capabilities,
                role=ProviderRole.DISABLED,
                admission_reason=(
                    "disabled_missing_credentials: OKX key/passphrase/secret required"
                ),
            )
            self.circuit.health = ProviderHealth.DISABLED_MISSING_CREDENTIALS

    def build_params(self, req: QuoteRequest) -> dict[str, str]:
        return {
            "chainIndex": "501",
            "amount": str(req.amount_base_units),
            "fromTokenAddress": req.input_mint,
            "toTokenAddress": req.output_mint,
            "userWalletAddress": req.user_wallet,
            "slippagePercent": serialize_provider_bps(
                self.provider_id, "slippagePercent", req.slippage
            ),
        }

    def auth_headers(self, timestamp: str, params: dict[str, str]) -> dict[str, str]:
        query = OkxAuth.canonical_query(params)
        pathq = f"{self.path}?{query}"
        return {
            "OK-ACCESS-KEY": self.api_key or "",
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase or "",
            "OK-ACCESS-SIGN": OkxAuth.sign(self.secret or "", timestamp, "GET", pathq),
        }

    @staticmethod
    def _validate_optional_echo(
        router: dict[str, Any], req: QuoteRequest
    ) -> EchoProofState:
        checks = {
            "fromTokenAddress": req.input_mint,
            "toTokenAddress": req.output_mint,
            "userWalletAddress": req.user_wallet,
            "swapMode": req.swap_mode.value,
            "slippagePercent": serialize_provider_bps(
                "okx_dex", "slippagePercent", req.slippage
            ),
        }
        found = 0
        for field, expected in checks.items():
            if field not in router:
                continue
            found += 1
            if str(router[field]) != str(expected):
                raise ValueError(f"okx response {field} does not match request")
        return EchoProofState.PROVEN if found == len(checks) else EchoProofState.PARTIAL

    def normalize(self, req: QuoteRequest, payload: dict[str, Any]) -> NormalizedQuote:
        data = payload.get("data")
        data = data[0] if isinstance(data, list) else data
        if payload.get("code") not in ("0", 0) or not isinstance(data, dict):
            raise ValueError("okx non-success envelope")
        router = data.get("routerResult")
        if not isinstance(router, dict):
            raise ValueError("okx routerResult must be an object")
        if router.get("chainIndex") != "501":
            raise ValueError("okx response chain does not match Solana")
        if str(router.get("fromTokenAmount")) != str(req.amount_base_units):
            raise ValueError("okx response amount does not match request")
        echo_state = self._validate_optional_echo(router, req)
        out = exact_positive_int(router.get("toTokenAmount"), "toTokenAmount")
        tx = router.get("tx") if isinstance(router.get("tx"), dict) else {}
        minimum_raw = tx.get("minReceiveAmount", router.get("minReceiveAmount"))
        minimum = exact_positive_int(minimum_raw, "minReceiveAmount")

        for instruction in data.get("instructionLists", []):
            require_base58(instruction.get("programId", ""), "programId")
            require_base64(instruction.get("data", ""), "instruction data")
            for account in instruction.get("accounts", []):
                require_base58(account.get("pubkey", ""), "account pubkey")
                if not isinstance(account.get("isSigner"), bool):
                    raise ValueError("OKX account isSigner must be bool")
                if not isinstance(account.get("isWritable"), bool):
                    raise ValueError("OKX account isWritable must be bool")

        venues: list[str] = []
        pools: list[str] = []
        for route_item in router.get("dexRouterList", []):
            if not isinstance(route_item, dict):
                continue
            nested = route_item.get("subRouterList")
            if not isinstance(nested, list):
                nested = route_item.get("router")
            if not isinstance(nested, list):
                continue
            for pool in nested:
                if not isinstance(pool, dict):
                    continue
                protocols = pool.get("dexProtocol")
                protocol = (
                    protocols[0] if isinstance(protocols, list) and protocols else {}
                )
                venue = protocol.get("dexName") if isinstance(protocol, dict) else None
                if isinstance(venue, str) and venue:
                    venues.append(venue)
                key = pool.get("poolId") or pool.get("poolAddress")
                if isinstance(key, str) and key:
                    pools.append(key)
        venue = venues[0] if venues else "okx"
        pool_key = pools[0] if pools else f"okx-router:{venue}"
        graph = RouteGraph(
            provider=self.provider_id,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            guaranteed_output=minimum,
            edges=(
                RouteEdge(
                    stage=0,
                    branch=0,
                    kind=RouteEdgeKind.SWAP,
                    provider=self.provider_id,
                    venue=venue,
                    pool_key=pool_key,
                    program_id=None,
                    input_mint=req.input_mint,
                    output_mint=req.output_mint,
                    input_amount=req.amount_base_units,
                    output_amount=out,
                    allocation_bps=BasisPoints(10_000),
                    source_path="data.routerResult.dexRouterList",
                ),
            ),
            asset_generation=f"decimals:{req.input_decimals}:{req.output_decimals}",
        )
        expires_at, freshness_source = self._expiry(router | data)
        fee = router.get("tradeFee") or router.get("estimateGasFee")
        fees = ()
        if fee is not None:
            fees = (
                QuoteFeeComponent(
                    kind="provider",
                    amount_base_units=(int(fee) if str(fee).isdigit() else None),
                    rate=(None if str(fee).isdigit() else str(fee)),
                    source_field="tradeFee/estimateGasFee",
                    inclusion_state=SemanticState.PROVEN,
                    original_provider_text=str(fee),
                ),
            )
        response_hash = raw_hash(payload)
        external_id = data.get("requestId") or response_hash[:16]
        return NormalizedQuote(
            provider=self.provider_id,
            request_fingerprint=req.fingerprint,
            raw_response_hash=response_hash,
            external_id=external_id,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            minimum_output=minimum,
            minimum_output_state=MinimumOutputState.PROVEN,
            swap_mode=req.swap_mode,
            slippage_bps=req.slippage_bps,
            route_provenance=(graph.semantic_hash,),
            dex_sources=graph.route_labels,
            price_impact_pct=(
                str(router["priceImpactPercent"])
                if router.get("priceImpactPercent") is not None
                else None
            ),
            provider_fee=(None if fee is None else str(fee)),
            platform_fee=None,
            context_slot=(
                None if data.get("contextSlot") is None else int(data["contextSlot"])
            ),
            received_at=self.clock.now(),
            expires_at=expires_at,
            artifact_kind=ExecutionArtifactKind.RAW_INSTRUCTIONS,
            capabilities=self.capabilities,
            diagnostic_trace_id=external_id,
            input_decimals=req.input_decimals,
            output_decimals=req.output_decimals,
            fees=fees,
            route_graph=graph,
            guarantee_source=GuaranteeSource.PROVIDER_MIN_RECEIVE,
            freshness_source=freshness_source,
            response_echo_state=echo_state,
        )


class OpenOceanAdapter(ProviderAdapter):
    provider_id = "openocean"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self.capabilities = (
            OPENOCEAN_CAPABILITIES if api_key else OPENOCEAN_DISABLED_CAPABILITIES
        )
        super().__init__(**kwargs)
        self.api_key = api_key
        self.limiter = FixedWindowLimiter(2, 1, self.clock)
        if not api_key:
            self.circuit.health = ProviderHealth.DISABLED_MISSING_CREDENTIALS

    def normalize(self, req: QuoteRequest, payload: dict[str, Any]) -> NormalizedQuote:
        if str(payload.get("inAmount") or payload.get("inAmountBaseUnits")) != str(
            req.amount_base_units
        ):
            raise ValueError("openocean response amount does not match request")
        for field, expected in (
            ("inTokenAddress", req.input_mint),
            ("outTokenAddress", req.output_mint),
            ("account", req.user_wallet),
        ):
            if field in payload and str(payload[field]) != expected:
                raise ValueError(f"openocean response {field} does not match request")
        out = exact_positive_int(
            payload.get("outAmount") or payload.get("outAmountBaseUnits"),
            "openocean.outAmount",
        )
        sources = tuple(
            str(item)
            for item in (
                payload.get("sources") or payload.get("dexes") or ("openocean-meta",)
            )
        )
        venue = "+".join(sources)
        graph = RouteGraph(
            provider=self.provider_id,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            guaranteed_output=None,
            edges=(
                RouteEdge(
                    stage=0,
                    branch=0,
                    kind=RouteEdgeKind.SWAP,
                    provider=self.provider_id,
                    venue=venue,
                    pool_key=f"openocean-meta:{venue}",
                    program_id=None,
                    input_mint=req.input_mint,
                    output_mint=req.output_mint,
                    input_amount=req.amount_base_units,
                    output_amount=out,
                    allocation_bps=BasisPoints(10_000),
                    source_path="sources",
                ),
            ),
            asset_generation=f"decimals:{req.input_decimals}:{req.output_decimals}",
        )
        expires_at, freshness_source = self._expiry(payload)
        fee = payload.get("fee")
        fee_text = "unknown" if fee is None else str(fee)
        fee_state = (
            SemanticState.UNAVAILABLE
            if fee_text.lower() == "unknown"
            else SemanticState.PROVEN
        )
        fees = (
            QuoteFeeComponent(
                kind="provider",
                rate=fee_text,
                source_field="fee",
                inclusion_state=fee_state,
                original_provider_text=fee_text,
            ),
        )
        response_hash = raw_hash(payload)
        external_id = payload.get("traceId") or response_hash[:16]
        return NormalizedQuote(
            provider=self.provider_id,
            request_fingerprint=req.fingerprint,
            raw_response_hash=response_hash,
            external_id=external_id,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            minimum_output=None,
            minimum_output_state=MinimumOutputState.UNPROVEN,
            swap_mode=req.swap_mode,
            slippage_bps=req.slippage_bps,
            route_provenance=(graph.semantic_hash,),
            dex_sources=graph.route_labels,
            price_impact_pct=(
                str(payload["priceImpact"])
                if payload.get("priceImpact") is not None
                else None
            ),
            provider_fee=fee_text,
            platform_fee=(
                str(payload["platformFee"])
                if payload.get("platformFee") is not None
                else "unknown"
            ),
            context_slot=(
                None
                if payload.get("contextSlot") is None
                else int(payload["contextSlot"])
            ),
            received_at=self.clock.now(),
            expires_at=expires_at,
            artifact_kind=ExecutionArtifactKind.NONE,
            capabilities=self.capabilities,
            diagnostic_trace_id=external_id,
            input_decimals=req.input_decimals,
            output_decimals=req.output_decimals,
            fees=fees,
            route_graph=graph,
            guarantee_source=GuaranteeSource.UNAVAILABLE,
            freshness_source=freshness_source,
            response_echo_state=EchoProofState.PARTIAL,
        )


class OdosAdapter(ProviderAdapter):
    provider_id = "odos"
    capabilities = ODOS_CAPABILITIES
    base_url = "https://solana-beta-api.odos.xyz"

    def quote_body(self, req: QuoteRequest) -> dict[str, Any]:
        return {
            "chainId": 101,
            "inputTokens": [
                {"tokenAddress": req.input_mint, "amount": str(req.amount_base_units)}
            ],
            "outputTokens": [{"tokenAddress": req.output_mint, "proportion": 1}],
            "userAddr": req.user_wallet,
            "slippageLimitPercent": serialize_provider_bps(
                self.provider_id, "slippageLimitPercent", req.slippage
            ),
        }

    def normalize_quote(
        self, req: QuoteRequest, payload: dict[str, Any]
    ) -> NormalizedQuote:
        path = payload.get("pathId")
        outs = payload.get("outAmounts")
        if not isinstance(path, str) or not path or not outs:
            raise ValueError("odos quote missing pathId/outAmounts")
        raw_out = outs[0] if isinstance(outs, list) else next(iter(outs.values()))
        out = exact_positive_int(raw_out, "odos.outAmounts[0]")
        sources = tuple(
            str(item)
            for item in (payload.get("pathViz") or payload.get("sources") or ("odos",))
        )
        venue = "+".join(sources)
        graph = RouteGraph(
            provider=self.provider_id,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            guaranteed_output=None,
            edges=(
                RouteEdge(
                    stage=0,
                    branch=0,
                    kind=RouteEdgeKind.SWAP,
                    provider=self.provider_id,
                    venue=venue,
                    pool_key=f"odos-path:{path}",
                    program_id=None,
                    input_mint=req.input_mint,
                    output_mint=req.output_mint,
                    input_amount=req.amount_base_units,
                    output_amount=out,
                    allocation_bps=BasisPoints(10_000),
                    source_path="pathViz",
                ),
            ),
            asset_generation=f"decimals:{req.input_decimals}:{req.output_decimals}",
        )
        expires_at, freshness_source = self._expiry(payload)
        provider_fee = payload.get("providerFee")
        referral_fee = payload.get("referralFee")
        fees: list[QuoteFeeComponent] = []
        for kind, value, field_name in (
            ("provider", provider_fee, "providerFee"),
            ("referral", referral_fee, "referralFee"),
        ):
            if value is not None:
                fees.append(
                    QuoteFeeComponent(
                        kind=kind,
                        amount_base_units=(
                            int(value) if str(value).isdigit() else None
                        ),
                        rate=(None if str(value).isdigit() else str(value)),
                        source_field=field_name,
                        inclusion_state=SemanticState.PROVEN,
                        original_provider_text=str(value),
                    )
                )
        response_hash = raw_hash(payload)
        return NormalizedQuote(
            provider=self.provider_id,
            request_fingerprint=req.fingerprint,
            raw_response_hash=response_hash,
            external_id=path,
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            input_amount=req.amount_base_units,
            expected_output=out,
            minimum_output=None,
            minimum_output_state=MinimumOutputState.UNPROVEN,
            swap_mode=req.swap_mode,
            slippage_bps=req.slippage_bps,
            route_provenance=(graph.semantic_hash,),
            dex_sources=graph.route_labels,
            price_impact_pct=(
                str(payload["priceImpact"])
                if payload.get("priceImpact") is not None
                else None
            ),
            provider_fee=(None if provider_fee is None else str(provider_fee)),
            platform_fee=(None if referral_fee is None else str(referral_fee)),
            context_slot=(
                None
                if payload.get("contextSlot") is None
                else int(payload["contextSlot"])
            ),
            received_at=self.clock.now(),
            expires_at=expires_at,
            artifact_kind=ExecutionArtifactKind.ASSEMBLED_TRANSACTION,
            capabilities=self.capabilities,
            diagnostic_trace_id=path,
            input_decimals=req.input_decimals,
            output_decimals=req.output_decimals,
            fees=tuple(fees),
            route_graph=graph,
            guarantee_source=GuaranteeSource.UNAVAILABLE,
            freshness_source=freshness_source,
            response_echo_state=EchoProofState.PARTIAL,
        )

    def normalize_assemble(
        self, payload: dict[str, Any]
    ) -> AssembledTransactionArtifact:
        tx = payload.get("transaction") or payload.get("transactionData")
        require_base64(tx, "odos assembled transaction")
        return AssembledTransactionArtifact(
            self.capabilities,
            hashlib.sha256(tx.encode()).hexdigest(),
        )
