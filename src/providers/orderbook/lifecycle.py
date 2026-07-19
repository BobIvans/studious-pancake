from __future__ import annotations
from .models import *
class VenueAccountLifecycleService:
    def validate(self, *, venue_kind:VenueKind, market:str, authority:str, account:str|None, data:bytes|None, expected_marker:bytes)->VenueAccountPreparationPlan:
        if not account or data is None:
            st=VenueAccountState(VenueAccountStatus.PREPARATION_REQUIRED,venue_kind,market,authority,account,OrderbookRejectCode.VENUE_ACCOUNT_NOT_READY,{"mutation":"operator_preparation_only"})
            return VenueAccountPreparationPlan(st,(),0)
        if authority.encode() not in data or market.encode() not in data or expected_marker not in data:
            code=OrderbookRejectCode.SEAT_INVALID if venue_kind is VenueKind.PHOENIX_LEGACY_SPOT else OrderbookRejectCode.OPEN_ORDERS_INVALID
            raise OrderbookReject(code,"venue account binding invalid")
        st=VenueAccountState(VenueAccountStatus.READY,venue_kind,market,authority,account,None,{})
        return VenueAccountPreparationPlan(st,(),0)
