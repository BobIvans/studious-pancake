from __future__ import annotations
from fractions import Fraction
from .models import *

def ceil_div(a:int,b:int)->int: return -(-a//b)
class OrderbookQuoteEngine:
    def quote(self, snapshot: OrderbookMarketSnapshot, direction: TradeDirection, input_amount:int, min_output:int=0, max_slot_skew:int=0)->DepthQuote:
        if input_amount<=0: raise OrderbookReject(OrderbookRejectCode.LOT_SIZE_INVALID,"input must be positive")
        if abs(snapshot.context_slot-snapshot.source_slot)>max_slot_skew: raise OrderbookReject(OrderbookRejectCode.SLOT_INCONSISTENT,"snapshot slots exceed policy")
        lc=snapshot.lot_config; fee=snapshot.fee_config
        if lc.base_lot_size<=0 or lc.quote_lot_size<=0 or lc.tick_size_in_quote_lots_per_base_lot<=0: raise OrderbookReject(OrderbookRejectCode.LOT_SIZE_INVALID,"invalid lot config")
        if fee.denominator<=0 or fee.numerator<0: raise OrderbookReject(OrderbookRejectCode.TAKER_FEE_UNKNOWN,"invalid fee")
        depth=snapshot.depth.sorted(); levels = depth.asks if direction is TradeDirection.BUY_BASE else depth.bids
        if not levels: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_DEPTH_INSUFFICIENT,"empty depth")
        consumed=[]; base_lots=0; quote_lots=0
        if direction is TradeDirection.BUY_BASE:
            budget_quote_lots=input_amount // lc.quote_lot_size
            if budget_quote_lots<=0: raise OrderbookReject(OrderbookRejectCode.TICK_ROUNDING_UNREPRESENTABLE,"input below quote lot")
            remaining=budget_quote_lots
            for lvl in levels:
                level_quote=lvl.price_lots*lvl.base_lots
                take_quote=min(remaining, level_quote)
                take_base=take_quote//lvl.price_lots
                if take_base<=0: break
                consumed.append(L2Level(lvl.side,lvl.price_lots,take_base)); base_lots+=take_base; spent=take_base*lvl.price_lots; quote_lots+=spent; remaining-=spent
                if remaining<=0: break
            if base_lots<=0: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_DEPTH_INSUFFICIENT,"no executable lots")
            fee_base=ceil_div(base_lots*lc.base_lot_size*fee.numerator, fee.denominator)
            out=base_lots*lc.base_lot_size-fee_base
            max_in=quote_lots*lc.quote_lot_size
            if out<min_output: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_AMM_THRESHOLD_NOT_MET,"min output not met")
            return DepthQuote(direction,input_amount,base_lots,quote_lots,fee_base,out,max_in,Fraction(quote_lots*lc.quote_lot_size, base_lots*lc.base_lot_size),tuple(consumed),(snapshot.raw_market_hash,*snapshot.raw_book_hashes))
        # sell base: input base is rounded down to executable lots; fee charged in quote conservatively
        remaining=input_amount//lc.base_lot_size
        if remaining<=0: raise OrderbookReject(OrderbookRejectCode.TICK_ROUNDING_UNREPRESENTABLE,"input below base lot")
        for lvl in levels:
            take=min(remaining,lvl.base_lots); consumed.append(L2Level(lvl.side,lvl.price_lots,take)); base_lots+=take; quote_lots+=take*lvl.price_lots; remaining-=take
            if remaining<=0: break
        if base_lots*lc.base_lot_size>input_amount: raise AssertionError("lot conversion increased input")
        if remaining>0: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_DEPTH_INSUFFICIENT,"full book exhausted")
        gross=quote_lots*lc.quote_lot_size; fee_quote=ceil_div(gross*fee.numerator,fee.denominator); out=gross-fee_quote
        if out<min_output: raise OrderbookReject(OrderbookRejectCode.ORDERBOOK_AMM_THRESHOLD_NOT_MET,"min output not met")
        return DepthQuote(direction,input_amount,base_lots,quote_lots,fee_quote,out,base_lots*lc.base_lot_size,Fraction(gross,base_lots*lc.base_lot_size),tuple(consumed),(snapshot.raw_market_hash,*snapshot.raw_book_hashes))
