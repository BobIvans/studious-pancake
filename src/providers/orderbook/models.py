from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
import hashlib, json, time
from typing import Mapping
from src.execution.models import Instruction, SimulationReport, AccountSnapshot

class OrderbookRejectCode(str, Enum):
    UNKNOWN_VENUE_OR_POOL="UNKNOWN_VENUE_OR_POOL"; VENUE_PROGRAM_MISMATCH="VENUE_PROGRAM_MISMATCH"; VENUE_IDL_VERSION_MISMATCH="VENUE_IDL_VERSION_MISMATCH"; MARKET_LAYOUT_INVALID="MARKET_LAYOUT_INVALID"; MARKET_UNSUPPORTED="MARKET_UNSUPPORTED"; MARKET_STATE_STALE="MARKET_STATE_STALE"; SLOT_INCONSISTENT="SLOT_INCONSISTENT"; ORDERBOOK_DEPTH_INSUFFICIENT="ORDERBOOK_DEPTH_INSUFFICIENT"; LOT_SIZE_INVALID="LOT_SIZE_INVALID"; TICK_ROUNDING_UNREPRESENTABLE="TICK_ROUNDING_UNREPRESENTABLE"; TAKER_FEE_UNKNOWN="TAKER_FEE_UNKNOWN"; TOKEN_PROGRAM_UNSUPPORTED="TOKEN_PROGRAM_UNSUPPORTED"; VENUE_ACCOUNT_NOT_READY="VENUE_ACCOUNT_NOT_READY"; SEAT_INVALID="SEAT_INVALID"; OPEN_ORDERS_INVALID="OPEN_ORDERS_INVALID"; IOC_MODE_UNSUPPORTED="IOC_MODE_UNSUPPORTED"; SETTLEMENT_PATH_UNPROVEN="SETTLEMENT_PATH_UNPROVEN"; ORDERBOOK_POSTCONDITION_UNPROVEN="ORDERBOOK_POSTCONDITION_UNPROVEN"; ORDERBOOK_RESIDUAL_ORDER="ORDERBOOK_RESIDUAL_ORDER"; ORDERBOOK_RESIDUAL_LOCKED_FUNDS="ORDERBOOK_RESIDUAL_LOCKED_FUNDS"; ORDERBOOK_AMM_THRESHOLD_NOT_MET="ORDERBOOK_AMM_THRESHOLD_NOT_MET"; ORDERBOOK_PROFILE_MISSING="ORDERBOOK_PROFILE_MISSING"; ORDERBOOK_PROFILE_EXCEEDED="ORDERBOOK_PROFILE_EXCEEDED"
class VenueKind(str, Enum): PHOENIX_LEGACY_SPOT="phoenix_legacy_spot"; OPENBOOK_V2="openbook_v2"
class Side(str, Enum): BID="bid"; ASK="ask"
class TradeDirection(str, Enum): BUY_BASE="buy_base"; SELL_BASE="sell_base"
class VenueAccountStatus(str, Enum): UNSUPPORTED="UNSUPPORTED"; NOT_READY="NOT_READY"; PREPARATION_REQUIRED="PREPARATION_REQUIRED"; READY="READY"; RETIREMENT_REQUIRED="RETIREMENT_REQUIRED"; CLOSED="CLOSED"

class OrderbookReject(ValueError):
    def __init__(self, code: OrderbookRejectCode, message: str, diagnostics: Mapping[str, object] | None=None): super().__init__(message); self.code=code; self.diagnostics=dict(diagnostics or {})

@dataclass(frozen=True, slots=True)
class VenueProgramSpec:
    venue_kind: VenueKind; cluster: str; program_id: str; source: str; pinned_version: str; artifact_sha256: str; expected_owner: str; layout_discriminator: bytes; min_data_len: int; max_data_len: int; supported_token_programs: tuple[str,...]; enabled_shadow: bool; enabled_live: bool; status: str; checked_at: str; markets: tuple[str,...]
    def verify_digest(self)->str:
        payload=json.dumps({"venue_kind":self.venue_kind.value,"cluster":self.cluster,"program_id":self.program_id,"version":self.pinned_version,"artifact":self.artifact_sha256,"markets":self.markets},sort_keys=True).encode(); return hashlib.sha256(payload).hexdigest()
@dataclass(frozen=True, slots=True)
class MarketLotConfig: base_lot_size:int; quote_lot_size:int; tick_size_in_quote_lots_per_base_lot:int; base_decimals:int; quote_decimals:int
@dataclass(frozen=True, slots=True)
class TakerFeeConfig: numerator:int; denominator:int; source:str
@dataclass(frozen=True, slots=True)
class L2Level: side: Side; price_lots:int; base_lots:int
@dataclass(frozen=True, slots=True)
class OrderbookDepth:
    bids: tuple[L2Level,...]; asks: tuple[L2Level,...]
    def sorted(self): return OrderbookDepth(tuple(sorted(self.bids,key=lambda x:x.price_lots,reverse=True)), tuple(sorted(self.asks,key=lambda x:x.price_lots)))
@dataclass(frozen=True, slots=True)
class OrderbookMarketSnapshot:
    market_pubkey:str; venue_spec:VenueProgramSpec; program_id:str; base_mint:str; quote_mint:str; base_token_program:str; quote_token_program:str; raw_market_hash:str; raw_book_hashes:tuple[str,...]; context_slot:int; source_slot:int; observed_unix:int; decoder_version:str; lot_config:MarketLotConfig; fee_config:TakerFeeConfig; depth:OrderbookDepth
@dataclass(frozen=True, slots=True)
class DepthQuote:
    direction:TradeDirection; input_amount:int; executable_base_lots:int; gross_quote_lots:int; fee_amount:int; min_out:int; max_in:int; vwap:Fraction; consumed_levels:tuple[L2Level,...]; source_hashes:tuple[str,...]
@dataclass(frozen=True, slots=True)
class VenueAccountState: status:VenueAccountStatus; venue_kind:VenueKind; market:str; authority:str; account:str|None; reason:OrderbookRejectCode|None=None; diagnostics:Mapping[str,object]|None=None
@dataclass(frozen=True, slots=True)
class VenueAccountPreparationPlan: state:VenueAccountState; instructions:tuple[Instruction,...]; rent_lamports:int; costed_once:bool=True
@dataclass(frozen=True, slots=True)
class OrderbookInstructionPlan: instructions:tuple[Instruction,...]; settlement_instructions:tuple[Instruction,...]; required_accounts:tuple[str,...]; ioc_only:bool; expected_postcondition:str
@dataclass(frozen=True, slots=True)
class ExecutionProfile: venue_kind:VenueKind; market_family:str; max_static_accounts:int; max_writable_accounts:int; max_serialized_bytes:int; cu_limit:int; max_depth_levels:int; max_slot_skew:int; requires_alt:bool=False

def sha256(data:bytes)->str: return hashlib.sha256(data).hexdigest()
