"""Verified Solana swap provider adapters and simulation-gated route selection."""
from __future__ import annotations

import base64, hashlib, hmac, random, time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum, IntFlag, auto
from typing import Any, Mapping, Protocol, Sequence

import aiohttp

from src.domain.money import BasisPoints, NATIVE_SOL_MINT, TOKEN_2022_PROGRAM, TOKEN_PROGRAM, TokenAmount, WSOL_MINT
from src.domain.cost_model import FeeComponent, TradeAmounts, TradeCostModel, FlashLoanTerms, ConversionSnapshot
from src.execution.models import COMPUTE_BUDGET_PROGRAM_ID, Instruction, SimulationReport, TransactionPlan

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
JITO_TIP_PROGRAM_IDS = frozenset({SYSTEM_PROGRAM_ID})

class SwapMode(str, Enum):
    EXACT_IN = "ExactIn"
    EXACT_OUT = "ExactOut"

class ProviderHealth(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"

class CircuitReason(str, Enum):
    AUTHENTICATION_FAILURE = "authentication_failure"
    SCHEMA_MISMATCH = "schema_mismatch"
    RATE_LIMIT = "rate_limit"
    UNSUPPORTED_TOKEN = "unsupported_token"
    TIMEOUT = "timeout"
    MALFORMED_INSTRUCTION = "malformed_instruction"
    UNRESOLVED_ALT = "unresolved_alt"
    STALE_RESPONSE = "stale_response"

class SwapCapability(IntFlag):
    INDICATIVE_QUOTES = auto(); FIRM_QUOTES = auto(); RAW_INSTRUCTIONS = auto(); SERIALIZED_TRANSACTIONS = auto()
    EXACT_IN = auto(); EXACT_OUT = auto(); LEGACY_SPL_TOKEN = auto(); TOKEN_2022 = auto(); NATIVE_SOL = auto(); WSOL = auto()
    ADDRESS_LOOKUP_TABLES = auto(); JITO_COMPATIBLE_ROUTING = auto()

@dataclass(frozen=True, slots=True)
class ProviderFreshnessPolicy:
    quote_ttl: timedelta = timedelta(seconds=2)
    instruction_ttl: timedelta = timedelta(seconds=2)

@dataclass(frozen=True, slots=True)
class QuoteRequest:
    input_mint: str; output_mint: str; amount: TokenAmount; swap_mode: SwapMode; taker: str; payer: str
    slippage_bps: BasisPoints; token_program: str = TOKEN_PROGRAM; max_accounts: int = 64
    wrap_and_unwrap_sol: bool = False; for_jito_bundle: bool = False
    included_dexes: tuple[str, ...] = (); excluded_dexes: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class CostComponent:
    fee: FeeComponent
    provider_behavior: str

@dataclass(frozen=True, slots=True)
class NormalizedRouteStep:
    dex: str; input_mint: str; output_mint: str; in_amount: TokenAmount; out_amount: TokenAmount; fee: CostComponent | None = None

@dataclass(frozen=True, slots=True)
class NormalizedQuote:
    provider: str; request: QuoteRequest; expected_output: TokenAmount; minimum_output: TokenAmount; swap_mode: SwapMode
    route_steps: tuple[NormalizedRouteStep, ...]; fees: tuple[CostComponent, ...]; provider_fee_behavior: str
    raw: Mapping[str, Any]; received_at: float; context_slot: int | None = None; firm: bool = False
    def is_fresh(self, policy: ProviderFreshnessPolicy, now: float | None = None) -> bool:
        return (now or time.time()) - self.received_at <= policy.quote_ttl.total_seconds()

@dataclass(frozen=True, slots=True)
class InstructionRequest:
    quote: NormalizedQuote; use_jito: bool; existing_wsol_ata: str | None = None

@dataclass(frozen=True, slots=True)
class InstructionBundle:
    provider: str; swap_instructions: tuple[Instruction, ...]; setup_instructions: tuple[Instruction, ...] = (); cleanup_instructions: tuple[Instruction, ...] = (); other_instructions: tuple[Instruction, ...] = (); compute_budget_instructions: tuple[Instruction, ...] = (); tip_instructions: tuple[Instruction, ...] = (); address_lookup_table_addresses: tuple[str, ...] = (); blockhash_metadata: Mapping[str, Any] = field(default_factory=dict); raw: Mapping[str, Any] = field(default_factory=dict); received_at: float = field(default_factory=time.time)
    def __post_init__(self):
        if not self.swap_instructions:
            raise ProviderResponseError("empty provider swap instruction list is not a recoverable success")

@dataclass(frozen=True, slots=True)
class SwapProviderStatus:
    provider: str; health: ProviderHealth; capabilities: SwapCapability; circuit_reason: CircuitReason | None = None; retry_after: float | None = None

@dataclass(frozen=True, slots=True)
class ProviderPerformanceRecord:
    provider: str; quote_latency_ms: float | None = None; build_latency_ms: float | None = None; expected_output: int | None = None; minimum_output: int | None = None; simulated_output: int | None = None; realized_output: int | None = None; quote_to_simulation_delta: int | None = None; simulation_to_realized_delta: int | None = None; rate_limited: bool = False; schema_failures: int = 0; route_dexes: tuple[str, ...] = (); account_count: int | None = None; serialized_transaction_size: int | None = None; units_consumed: int | None = None

class ProviderResponseError(ValueError): pass
class UnsupportedProviderCapability(ValueError): pass

class SwapProvider(Protocol):
    name: str; capabilities: SwapCapability; freshness: ProviderFreshnessPolicy
    async def quote(self, session: aiohttp.ClientSession, request: QuoteRequest) -> NormalizedQuote: ...
    async def instructions(self, session: aiohttp.ClientSession, request: InstructionRequest) -> InstructionBundle: ...
    def status(self) -> SwapProviderStatus: ...

def _require_str(data: Mapping[str, Any], key: str) -> str:
    val = data.get(key)
    if not isinstance(val, str) or not val:
        raise ProviderResponseError(f"missing or malformed {key}")
    return val

def _require_positive_int(data: Mapping[str, Any], key: str) -> int:
    try: val = int(data[key])
    except Exception as exc: raise ProviderResponseError(f"missing or malformed {key}") from exc
    if val <= 0: raise ProviderResponseError(f"non-positive {key}")
    return val

def decode_provider_instruction(raw: Mapping[str, Any]) -> Instruction:
    program_id = _require_str(raw, "programId")
    accounts_raw = raw.get("accounts")
    if not isinstance(accounts_raw, list): raise ProviderResponseError("instruction accounts must be a list")
    accounts = []
    for acct in accounts_raw:
        if isinstance(acct, str): accounts.append(acct)
        elif isinstance(acct, Mapping): accounts.append(_require_str(acct, "pubkey"))
        else: raise ProviderResponseError("malformed account entry")
    data_s = raw.get("data", "")
    if not isinstance(data_s, str): raise ProviderResponseError("instruction data must be base64/base58 string")
    try: data = base64.b64decode(data_s + "=" * (-len(data_s) % 4)) if data_s else b""
    except Exception as exc: raise ProviderResponseError("malformed instruction data") from exc
    if program_id == SYSTEM_PROGRAM_ID and data and data[:4] == (2).to_bytes(4, "little") and len(accounts) < 2:
        raise ProviderResponseError("malformed system transfer")
    kind = "compute_budget" if program_id == COMPUTE_BUDGET_PROGRAM_ID else "generic"
    return Instruction(program_id=program_id, accounts=tuple(accounts), data=data, kind=kind)

def _split_ix(raw_list: Sequence[Mapping[str, Any]]) -> tuple[tuple[Instruction,...], tuple[Instruction,...], tuple[Instruction,...]]:
    swap=[]; cb=[]; tip=[]
    for raw in raw_list:
        ix=decode_provider_instruction(raw)
        if ix.kind == "compute_budget": cb.append(ix)
        elif ix.program_id in JITO_TIP_PROGRAM_IDS and ix.name.lower().find("tip") >= 0: tip.append(ix)
        else: swap.append(ix)
    return tuple(swap), tuple(cb), tuple(tip)

class BaseAdapter:
    freshness=ProviderFreshnessPolicy(); _circuit: CircuitReason|None=None
    def status(self): return SwapProviderStatus(self.name, ProviderHealth.CIRCUIT_OPEN if self._circuit else ProviderHealth.AVAILABLE, self.capabilities, self._circuit)
    def _validate_request_capabilities(self, r: QuoteRequest):
        if r.swap_mode == SwapMode.EXACT_OUT and not self.capabilities & SwapCapability.EXACT_OUT: raise UnsupportedProviderCapability(f"{self.name} does not advertise ExactOut")
        if r.token_program == TOKEN_2022_PROGRAM and not self.capabilities & SwapCapability.TOKEN_2022: raise UnsupportedProviderCapability(f"{self.name} rejects Token-2022")
        if (r.input_mint == NATIVE_SOL_MINT or r.output_mint == NATIVE_SOL_MINT) and not self.capabilities & SwapCapability.NATIVE_SOL: raise UnsupportedProviderCapability(f"{self.name} rejects native SOL")

class JupiterSwapV2Adapter(BaseAdapter):
    name="jupiter_swap_v2"; endpoint="https://api.jup.ag/swap/v2/build"
    capabilities=SwapCapability.FIRM_QUOTES|SwapCapability.RAW_INSTRUCTIONS|SwapCapability.EXACT_IN|SwapCapability.EXACT_OUT|SwapCapability.LEGACY_SPL_TOKEN|SwapCapability.TOKEN_2022|SwapCapability.NATIVE_SOL|SwapCapability.WSOL|SwapCapability.ADDRESS_LOOKUP_TABLES|SwapCapability.JITO_COMPATIBLE_ROUTING
    def __init__(self, api_key: str = "", tier_rps: float | None = None): self.headers={"x-api-key":api_key} if api_key else {}; self.rps = tier_rps if tier_rps else (1.0 if api_key else 0.5)
    async def quote(self, session, request):
        self._validate_request_capabilities(request)
        params={"inputMint":request.input_mint,"outputMint":request.output_mint,"amount":str(request.amount.base_units),"taker":request.taker,"payer":request.payer,"slippageBps":str(request.slippage_bps.value),"maxAccounts":str(request.max_accounts or 64),"wrapAndUnwrapSol":str(request.wrap_and_unwrap_sol).lower(),"forJitoBundle":str(request.for_jito_bundle).lower()}
        if request.included_dexes: params["includedDexes"]=",".join(request.included_dexes)
        if request.excluded_dexes: params["excludedDexes"]=",".join(request.excluded_dexes)
        async with session.get(self.endpoint, params=params, headers=self.headers) as resp: data=await resp.json(content_type=None)
        return self._normalize(data, request)
    def _normalize(self, data, request):
        if not isinstance(data, Mapping): raise ProviderResponseError("Jupiter response is not an object")
        q=data.get("quote") if isinstance(data.get("quote"), Mapping) else data
        if _require_str(q,"inputMint") != request.input_mint or _require_str(q,"outputMint") != request.output_mint: raise ProviderResponseError("Jupiter mint mismatch")
        if _require_positive_int(q,"inAmount") != request.amount.base_units: raise ProviderResponseError("Jupiter input amount mismatch")
        out=_require_positive_int(q,"outAmount"); min_out=int(q.get("otherAmountThreshold") or q.get("minOutAmount") or 0)
        if min_out <= 0: raise ProviderResponseError("Jupiter missing minimum output")
        steps=tuple(NormalizedRouteStep(str(s.get("swapInfo",{}).get("label") or s.get("label") or "unknown"), request.input_mint, request.output_mint, request.amount, TokenAmount(request.output_mint,out,request.amount.decimals)) for s in q.get("routePlan",[]) if isinstance(s,Mapping))
        return NormalizedQuote(self.name,request,TokenAmount(request.output_mint,out,request.amount.decimals),TokenAmount(request.output_mint,min_out,request.amount.decimals),request.swap_mode,steps,(),"no external platform/partner/positive-slippage fees by default",data,time.time(),q.get("contextSlot"),True)
    async def instructions(self, session, request):
        data=request.quote.raw; raw_swap=[]
        for key in ("swapInstruction","setupInstructions","cleanupInstruction","otherInstructions"):
            val=data.get(key)
            if isinstance(val, list): raw_swap.extend(val)
            elif isinstance(val, Mapping): raw_swap.append(val)
        swap,cb,tip=_split_ix(raw_swap)
        return InstructionBundle(self.name, swap, compute_budget_instructions=cb, tip_instructions=tip, address_lookup_table_addresses=tuple(data.get("addressLookupTableAddresses") or data.get("addressLookupTableAddresses" ) or ()), raw=data)

class OKXSolanaAdapter(BaseAdapter):
    name="okx_solana"; endpoint_path="/api/v6/dex/aggregator/swap-instruction"; base_url="https://web3.okx.com"; capabilities=SwapCapability.FIRM_QUOTES|SwapCapability.RAW_INSTRUCTIONS|SwapCapability.EXACT_IN|SwapCapability.LEGACY_SPL_TOKEN|SwapCapability.NATIVE_SOL|SwapCapability.WSOL|SwapCapability.ADDRESS_LOOKUP_TABLES|SwapCapability.JITO_COMPATIBLE_ROUTING
    def __init__(self,key="",signing_material="",passphrase="",approved_rps:float|None=None): self.key=key; self.signing_material=signing_material; self.passphrase=passphrase; self.rps=approved_rps
    def auth_headers(self, method, path, body="", timestamp="2026-07-19T00:00:00.000Z"):
        sign=base64.b64encode(hmac.new(self.signing_material.encode(), f"{timestamp}{method.upper()}{path}{body}".encode(), hashlib.sha256).digest()).decode()
        return {"OK-ACCESS-KEY":self.key,"OK-ACCESS-TIMESTAMP":timestamp,"OK-ACCESS-PASSPHRASE":self.passphrase,"OK-ACCESS-SIGN":sign}
    async def quote(self, session, request):
        self._validate_request_capabilities(request); params={"chainIndex":"501","fromTokenAddress":request.input_mint,"toTokenAddress":request.output_mint,"amount":str(request.amount.base_units),"userWalletAddress":request.taker,"slippagePercent":str(request.slippage_bps.value/100),"forJitoBundle":str(request.for_jito_bundle).lower()}
        path=self.endpoint_path
        async with session.get(self.base_url+path, params=params, headers=self.auth_headers("GET",path)) as resp:
            data=await resp.json(content_type=None)
        return self._normalize(data, request)
    def _normalize(self,data,request):
        root=data.get("data", data) if isinstance(data,Mapping) else {}; item=root[0] if isinstance(root,list) and root else root
        rr=item.get("routerResult", item) if isinstance(item,Mapping) else {}
        if _require_str(rr,"fromTokenAddress") != request.input_mint or _require_str(rr,"toTokenAddress") != request.output_mint: raise ProviderResponseError("OKX mint mismatch")
        if _require_positive_int(rr,"fromTokenAmount") != request.amount.base_units: raise ProviderResponseError("OKX amount mismatch")
        out=_require_positive_int(rr,"toTokenAmount"); min_out=int(rr.get("minReceiveAmount") or rr.get("toTokenAmount") or 0)
        return NormalizedQuote(self.name,request,TokenAmount(request.output_mint,out,request.amount.decimals),TokenAmount(request.output_mint,min_out,request.amount.decimals),request.swap_mode,(),(),"partner/referral/positive-slippage fees disabled by default",data,time.time(),None,True)
    async def instructions(self, session, request):
        root=request.quote.raw.get("data", request.quote.raw); item=root[0] if isinstance(root,list) and root else root; lists=item.get("instructionLists") or []
        raw=[ix for group in lists for ix in (group if isinstance(group,list) else [group])]
        swap,cb,tip=_split_ix(raw); return InstructionBundle(self.name,swap,compute_budget_instructions=cb,tip_instructions=tip,address_lookup_table_addresses=tuple(item.get("addressLookupTableAddresses") or ()), raw=item)

class ZeroXSolanaAdapter(BaseAdapter):
    name="zero_x_solana"; endpoint="https://api.0x.org/solana/swap-instructions"; capabilities=SwapCapability.FIRM_QUOTES|SwapCapability.RAW_INSTRUCTIONS|SwapCapability.EXACT_IN|SwapCapability.LEGACY_SPL_TOKEN|SwapCapability.WSOL|SwapCapability.ADDRESS_LOOKUP_TABLES
    def __init__(self, enabled=False, api_key=""): self.enabled=enabled; self.headers={"0x-api-key":api_key} if api_key else {}
    async def quote(self, session, request):
        if not self.enabled: raise UnsupportedProviderCapability("0x Solana requires priority access feature gate")
        self._validate_request_capabilities(request); return NormalizedQuote(self.name,request,TokenAmount(request.output_mint,1,request.amount.decimals),TokenAmount(request.output_mint,1,request.amount.decimals),request.swap_mode,(),(),"0x fees only when explicit in cost model",{},time.time(),None,True)
    async def instructions(self, session, request): raise UnsupportedProviderCapability("live 0x calls are priority-access gated in this build")

class OpenOceanSolanaAdapter(BaseAdapter):
    name="openocean_solana"; quote_endpoint="https://open-api.openocean.finance/v4/solana/quote"; capabilities=SwapCapability.INDICATIVE_QUOTES|SwapCapability.EXACT_IN|SwapCapability.LEGACY_SPL_TOKEN|SwapCapability.NATIVE_SOL|SwapCapability.WSOL
    async def quote(self, session, request): raise UnsupportedProviderCapability("OpenOcean Solana unavailable without authorized whitelist access")
    async def instructions(self, session, request): raise UnsupportedProviderCapability("OpenOcean Solana is quote-only until an official raw-instruction contract is verified")
    def status(self): return SwapProviderStatus(self.name, ProviderHealth.UNAVAILABLE, self.capabilities)

def active_solana_providers() -> tuple[SwapProvider,...]:
    return (JupiterSwapV2Adapter(), OKXSolanaAdapter(), ZeroXSolanaAdapter(enabled=False), OpenOceanSolanaAdapter())

def execution_shortlist(quotes: Sequence[NormalizedQuote], providers: Mapping[str, SwapProvider]) -> tuple[NormalizedQuote,...]:
    return tuple(q for q in quotes if q.is_fresh(providers[q.provider].freshness) and providers[q.provider].capabilities & SwapCapability.RAW_INSTRUCTIONS)

async def select_after_simulation(candidates: Sequence[tuple[NormalizedQuote, InstructionBundle, TransactionPlan, SimulationReport]], *, cost_model: TradeCostModel, flash_loan_terms: FlashLoanTerms, conversions: ConversionSnapshot, min_net_profit: TokenAmount, safety_buffer: TokenAmount) -> NormalizedQuote | None:
    best=None; best_profit=None
    for quote,bundle,plan,sim in candidates:
        if not sim.success or sim.simulated_net_profit is None: continue
        amounts=TradeAmounts(quote.request.amount, quote.expected_output, quote.minimum_output, TokenAmount(quote.request.output_mint, max(0, sim.simulated_net_profit.amount), quote.request.amount.decimals))
        decision=cost_model.evaluate(settlement_mint=quote.request.amount.mint, amounts=amounts, flash_loan_terms=flash_loan_terms, fees=[c.fee for c in quote.fees], conversions=conversions, min_net_profit=min_net_profit, safety_buffer=safety_buffer, use_simulated=True)
        profit=decision.breakdown.get("net_profit_base_units", -1) if decision.should_execute else -1
        if profit >= 0 and (best_profit is None or profit > best_profit): best=quote; best_profit=profit
    return best
