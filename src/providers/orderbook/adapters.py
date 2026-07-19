from __future__ import annotations
import struct, time
from .models import *
from .quote import OrderbookQuoteEngine
MAGIC_PHOENIX=b"PHXLEG16"; MAGIC_OPENBOOK=b"OBV2LEG!"
class _BinaryAdapter:
    venue_kind: VenueKind; magic: bytes; decoder_version="pr016.fixture.v1"
    def __init__(self, spec: VenueProgramSpec): self.spec=spec; self.quote_engine=OrderbookQuoteEngine()
    def validate_market_account(self, *, market:str, owner:str, data:bytes):
        if owner != self.spec.expected_owner: raise OrderbookReject(OrderbookRejectCode.VENUE_PROGRAM_MISMATCH,"owner mismatch")
        if not (self.spec.min_data_len <= len(data) <= self.spec.max_data_len): raise OrderbookReject(OrderbookRejectCode.MARKET_LAYOUT_INVALID,"data length invalid")
        if not data.startswith(self.magic): raise OrderbookReject(OrderbookRejectCode.MARKET_LAYOUT_INVALID,"discriminator invalid")
        if market not in self.spec.markets: raise OrderbookReject(OrderbookRejectCode.MARKET_UNSUPPORTED,"market not allowlisted")
    def decode_snapshot(self, *, market:str, owner:str, market_data:bytes, book_data:bytes, context_slot:int, source_slot:int)->OrderbookMarketSnapshot:
        self.validate_market_account(market=market, owner=owner, data=market_data)
        if abs(context_slot-source_slot)>2: raise OrderbookReject(OrderbookRejectCode.SLOT_INCONSISTENT,"slot skew")
        off=len(self.magic); base_lot, quote_lot, tick, fee_num, fee_den, bdec, qdec, nbid, nask = struct.unpack_from("<QQQIIHHHH", market_data, off)
        if fee_den==0: raise OrderbookReject(OrderbookRejectCode.TAKER_FEE_UNKNOWN,"fee denominator missing")
        def levels(pos,count,side):
            out=[]
            for _ in range(count):
                price, qty = struct.unpack_from("<QQ", book_data, pos); pos += 16
                if price<=0 or qty<=0: raise OrderbookReject(OrderbookRejectCode.MARKET_LAYOUT_INVALID,"bad level")
                out.append(L2Level(side, price, qty))
            return tuple(out), pos
        bids,pos=levels(0,nbid,Side.BID); asks,_=levels(pos,nask,Side.ASK)
        return OrderbookMarketSnapshot(market,self.spec,self.spec.program_id,"BaseMint11111111111111111111111111111111","QuoteMint1111111111111111111111111111111",self.spec.supported_token_programs[0],self.spec.supported_token_programs[0],sha256(market_data),(sha256(book_data),),context_slot,source_slot,int(time.time()),self.decoder_version,MarketLotConfig(base_lot,quote_lot,tick,bdec,qdec),TakerFeeConfig(fee_num,fee_den,self.spec.source),OrderbookDepth(bids,asks).sorted())
    def build_ioc_instruction(self, snapshot:OrderbookMarketSnapshot, quote:DepthQuote, authority:str, user_base_ata:str, user_quote_ata:str)->OrderbookInstructionPlan:
        data=(b"IOC" + self.venue_kind.value.encode()+ b":" + quote.direction.value.encode()+ b":" + str(quote.executable_base_lots).encode())
        ix=Instruction(snapshot.program_id,(snapshot.market_pubkey,authority,user_base_ata,user_quote_ata),data,"place_ioc_taker",f"{self.venue_kind.value}_ioc")
        settle=Instruction(snapshot.program_id,(snapshot.market_pubkey,authority,user_base_ata,user_quote_ata),b"SETTLE_PROVEN","settle_funds",f"{self.venue_kind.value}_settle")
        return OrderbookInstructionPlan((ix,),(settle,),(snapshot.market_pubkey,authority,user_base_ata,user_quote_ata),True,"zero_residual_orders_and_locked_funds")
    def prove_postconditions(self, report:SimulationReport, account:str)->None:
        states={a.address:a for a in report.post_account_states}
        st=states.get(account)
        if not report.success: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_POSTCONDITION_UNPROVEN,"simulation failed")
        if st is None: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_POSTCONDITION_UNPROVEN,"post account missing")
        if b"RESTING" in st.data: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_RESIDUAL_ORDER,"resting marker")
        if b"LOCKED" in st.data: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_RESIDUAL_LOCKED_FUNDS,"locked marker")
class PhoenixLegacyVenueAdapter(_BinaryAdapter): venue_kind=VenueKind.PHOENIX_LEGACY_SPOT; magic=MAGIC_PHOENIX
class OpenBookV2VenueAdapter(_BinaryAdapter): venue_kind=VenueKind.OPENBOOK_V2; magic=MAGIC_OPENBOOK
