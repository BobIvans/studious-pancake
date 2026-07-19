from __future__ import annotations
from dataclasses import replace
from datetime import timedelta
import base64, hashlib, hmac, json
from typing import Any, Protocol
from urllib.parse import urlencode
from .capabilities import *
from .circuit import ProviderCircuit
from .limiter import Clock, FixedWindowLimiter
from .models import *
from .utils import raw_hash, require_base58, require_base64

class Transport(Protocol):
    async def request(self, method: str, url: str, *, headers: dict[str,str] | None = None, params: dict[str,str] | None = None, json_body: dict[str,Any] | None = None) -> tuple[int, dict[str,str], Any]: ...

class ProviderAdapter:
    provider_id: str
    capabilities: ProviderCapabilities
    def __init__(self, *, transport: Transport | None=None, clock: Clock | None=None):
        self.transport=transport; self.clock=clock or Clock(); self.circuit=ProviderCircuit(self.clock)
    def startup_state(self) -> dict[str, str]:
        state = "ready" if self.capabilities.role is ProviderRole.EXECUTABLE else "discovery_only"
        return {"provider": self.provider_id, "state": state, "reason": self.capabilities.admission_reason, "artifact_kind": self.capabilities.artifact_kind.value, "capability_pin": self.capabilities.schema_version_pin, "rate_policy": self.capabilities.rate_limit_policy}

class JupiterRouterAdapter(ProviderAdapter):
    provider_id="jupiter_router"; capabilities=JUPITER_CAPABILITIES
    def __init__(self, **kw): super().__init__(**kw); self.limiter=FixedWindowLimiter(60,60,self.clock)
    def normalize_build(self, req: QuoteRequest, payload: dict[str,Any]) -> NormalizedQuote:
        if payload.get("inputMint") != req.input_mint or payload.get("outputMint") != req.output_mint or str(payload.get("inAmount")) != str(req.amount_base_units): raise ValueError("jupiter response does not match request")
        out=int(payload["outAmount"]); min_out=int(payload["otherAmountThreshold"])
        route=tuple(step.get("swapInfo",{}).get("label","unknown") for step in payload.get("routePlan",[]))
        if not route: raise ValueError("missing jupiter route identity")
        return NormalizedQuote(self.provider_id, req.fingerprint, raw_hash(payload), payload.get("requestId") or raw_hash(payload)[:16], req.input_mint, req.output_mint, req.amount_base_units, out, min_out, MinimumOutputState.PROVEN, req.swap_mode, int(payload.get("slippageBps", req.slippage_bps)), route, route, payload.get("priceImpactPct"), str(payload.get("platformFee")) if payload.get("platformFee") is not None else None, None, payload.get("contextSlot"), self.clock.now(), self.clock.now()+timedelta(seconds=30), self.capabilities.artifact_kind, self.capabilities, payload.get("requestId") or raw_hash(payload)[:16])

class OkxAuth:
    @staticmethod
    def canonical_query(params: dict[str,str]) -> str: return urlencode(sorted(params.items()))
    @staticmethod
    def sign(secret: str, timestamp: str, method: str, request_path_with_query: str, body: str="") -> str:
        msg=f"{timestamp}{method.upper()}{request_path_with_query}{body}".encode()
        return base64.b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()

class OkxDexAdapter(ProviderAdapter):
    provider_id="okx_dex"; capabilities=OKX_CAPABILITIES
    path="/api/v6/dex/aggregator/swap-instruction"; base_url="https://web3.okx.com"
    def __init__(self, api_key: str|None=None, passphrase: str|None=None, secret: str|None=None, **kw):
        super().__init__(**kw); self.api_key=api_key; self.passphrase=passphrase; self.secret=secret
        if not all((api_key, passphrase, secret)):
            self.capabilities=replace(self.capabilities, role=ProviderRole.DISABLED, admission_reason="disabled_missing_credentials: OKX key/passphrase/secret required")
            self.circuit.health=ProviderHealth.DISABLED_MISSING_CREDENTIALS
    def build_params(self, req: QuoteRequest) -> dict[str,str]:
        return {"chainIndex":"501","amount":str(req.amount_base_units),"fromTokenAddress":req.input_mint,"toTokenAddress":req.output_mint,"userWalletAddress":req.user_wallet,"slippagePercent":str(req.slippage_bps/100)}
    def auth_headers(self, timestamp: str, params: dict[str,str]) -> dict[str,str]:
        query=OkxAuth.canonical_query(params); pathq=f"{self.path}?{query}"
        return {"OK-ACCESS-KEY":self.api_key or "","OK-ACCESS-TIMESTAMP":timestamp,"OK-ACCESS-PASSPHRASE":self.passphrase or "","OK-ACCESS-SIGN":OkxAuth.sign(self.secret or "", timestamp, "GET", pathq)}
    def normalize(self, req: QuoteRequest, payload: dict[str,Any]) -> NormalizedQuote:
        data=payload.get("data"); data=data[0] if isinstance(data,list) else data
        if payload.get("code") not in ("0",0) or not isinstance(data,dict): raise ValueError("okx non-success envelope")
        rr=data.get("routerResult") or {}
        if rr.get("chainIndex") != "501" or str(rr.get("fromTokenAmount")) != str(req.amount_base_units): raise ValueError("okx response does not match request")
        out=int(rr["toTokenAmount"]); min_out=int((rr.get("tx") or {}).get("minReceiveAmount"))
        for ix in data.get("instructionLists",[]):
            require_base58(ix.get("programId",""), "programId"); require_base64(ix.get("data",""), "instruction data")
            for acct in ix.get("accounts",[]): require_base58(acct.get("pubkey",""), "account pubkey"); assert isinstance(acct.get("isSigner"), bool) and isinstance(acct.get("isWritable"), bool)
        route=tuple(p.get("dexProtocol", [{}])[0].get("dexName", "okx") for r in rr.get("dexRouterList",[]) for p in r.get("subRouterList", r.get("router",[]) if isinstance(r.get("router"),list) else [])) or ("okx",)
        return NormalizedQuote(self.provider_id, req.fingerprint, raw_hash(payload), raw_hash(rr)[:16], req.input_mint, req.output_mint, req.amount_base_units, out, min_out, MinimumOutputState.PROVEN, req.swap_mode, req.slippage_bps, route, route, rr.get("priceImpactPercent"), rr.get("tradeFee") or rr.get("estimateGasFee"), None, None, self.clock.now(), self.clock.now()+timedelta(seconds=30), ExecutionArtifactKind.RAW_INSTRUCTIONS, self.capabilities, raw_hash(payload)[:16])

class OpenOceanAdapter(ProviderAdapter):
    provider_id="openocean"
    def __init__(self, api_key: str|None=None, **kw):
        self.capabilities=OPENOCEAN_CAPABILITIES if api_key else OPENOCEAN_DISABLED_CAPABILITIES; super().__init__(**kw); self.api_key=api_key; self.limiter=FixedWindowLimiter(2,1,self.clock)
        if not api_key: self.circuit.health=ProviderHealth.DISABLED_MISSING_CREDENTIALS
    def normalize(self, req: QuoteRequest, payload: dict[str,Any]) -> NormalizedQuote:
        if str(payload.get("inAmount") or payload.get("inAmountBaseUnits")) != str(req.amount_base_units): raise ValueError("openocean response does not match request")
        out=int(payload.get("outAmount") or payload.get("outAmountBaseUnits")); route=tuple(payload.get("sources") or payload.get("dexes") or ("openocean-meta",))
        fee = payload.get("fee") or "unknown"
        return NormalizedQuote(self.provider_id, req.fingerprint, raw_hash(payload), payload.get("traceId") or raw_hash(payload)[:16], req.input_mint, req.output_mint, req.amount_base_units, out, None, MinimumOutputState.UNPROVEN, req.swap_mode, req.slippage_bps, tuple(f"openocean:{x}" for x in route), tuple(str(x) for x in route), payload.get("priceImpact"), str(fee), str(payload.get("platformFee")) if payload.get("platformFee") is not None else "unknown", payload.get("contextSlot"), self.clock.now(), self.clock.now()+timedelta(seconds=30), ExecutionArtifactKind.NONE, self.capabilities, payload.get("traceId") or raw_hash(payload)[:16])

class OdosAdapter(ProviderAdapter):
    provider_id="odos"; capabilities=ODOS_CAPABILITIES; base_url="https://solana-beta-api.odos.xyz"
    def quote_body(self, req: QuoteRequest) -> dict[str,Any]:
        return {"chainId":101,"inputTokens":[{"tokenAddress":req.input_mint,"amount":str(req.amount_base_units)}],"outputTokens":[{"tokenAddress":req.output_mint,"proportion":1}],"userAddr":req.user_wallet,"slippageLimitPercent":req.slippage_bps/100}
    def normalize_quote(self, req: QuoteRequest, payload: dict[str,Any]) -> NormalizedQuote:
        path=payload.get("pathId"); outs=payload.get("outAmounts")
        if not path or not outs: raise ValueError("odos quote missing pathId/outAmounts")
        out=int(outs[0] if isinstance(outs,list) else next(iter(outs.values())))
        route=tuple(payload.get("pathViz") or payload.get("sources") or ("odos",))
        return NormalizedQuote(self.provider_id, req.fingerprint, raw_hash(payload), path, req.input_mint, req.output_mint, req.amount_base_units, out, None, MinimumOutputState.UNPROVEN, req.swap_mode, req.slippage_bps, route, tuple(str(x) for x in route), str(payload.get("priceImpact")) if payload.get("priceImpact") is not None else None, str(payload.get("providerFee")) if payload.get("providerFee") is not None else None, str(payload.get("referralFee")) if payload.get("referralFee") is not None else None, None, self.clock.now(), self.clock.now()+timedelta(seconds=60), ExecutionArtifactKind.ASSEMBLED_TRANSACTION, self.capabilities, path)
    def normalize_assemble(self, payload: dict[str,Any]) -> AssembledTransactionArtifact:
        tx=payload.get("transaction") or payload.get("transactionData")
        require_base64(tx, "odos assembled transaction")
        return AssembledTransactionArtifact(self.capabilities, hashlib.sha256(tx.encode()).hexdigest())
