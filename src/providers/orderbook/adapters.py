from __future__ import annotations

import struct
import time

from .models import (
    DepthQuote,
    L2Level,
    MarketLotConfig,
    OrderbookDepth,
    OrderbookInstructionPlan,
    OrderbookMarketSnapshot,
    OrderbookReject,
    OrderbookRejectCode,
    Side,
    SimulationReport,
    TakerFeeConfig,
    VenueKind,
    VenueProgramSpec,
    sha256,
)
from .quote import OrderbookQuoteEngine
from src.execution.models import Instruction


class _BinaryAdapter:
    venue_kind: VenueKind
    decoder_version = "pr049.fixture-gated.v1"

    def __init__(self, spec: VenueProgramSpec):
        self.spec = spec
        self.quote_engine = OrderbookQuoteEngine()

    @property
    def layout_discriminator(self) -> bytes:
        return self.spec.layout_discriminator

    def validate_market_account(self, *, market: str, owner: str, data: bytes) -> None:
        if owner != self.spec.expected_owner:
            raise OrderbookReject(
                OrderbookRejectCode.VENUE_PROGRAM_MISMATCH,
                "owner mismatch",
            )
        if not (self.spec.min_data_len <= len(data) <= self.spec.max_data_len):
            raise OrderbookReject(
                OrderbookRejectCode.MARKET_LAYOUT_INVALID,
                "data length invalid",
            )
        if not self.layout_discriminator:
            raise OrderbookReject(
                OrderbookRejectCode.MARKET_LAYOUT_INVALID,
                "venue layout discriminator is not pinned for decoding",
            )
        if not data.startswith(self.layout_discriminator):
            raise OrderbookReject(
                OrderbookRejectCode.MARKET_LAYOUT_INVALID,
                "discriminator invalid",
            )
        if market not in self.spec.markets:
            raise OrderbookReject(
                OrderbookRejectCode.MARKET_UNSUPPORTED,
                "market not allowlisted",
            )

    def decode_snapshot(
        self,
        *,
        market: str,
        owner: str,
        market_data: bytes,
        book_data: bytes,
        context_slot: int,
        source_slot: int,
    ) -> OrderbookMarketSnapshot:
        self.validate_market_account(market=market, owner=owner, data=market_data)
        if abs(context_slot - source_slot) > 2:
            raise OrderbookReject(OrderbookRejectCode.SLOT_INCONSISTENT, "slot skew")
        offset = len(self.layout_discriminator)
        (
            base_lot,
            quote_lot,
            tick,
            fee_num,
            fee_den,
            base_decimals,
            quote_decimals,
            bid_count,
            ask_count,
        ) = struct.unpack_from("<QQQIIHHHH", market_data, offset)
        if fee_den == 0:
            raise OrderbookReject(
                OrderbookRejectCode.TAKER_FEE_UNKNOWN,
                "fee denominator missing",
            )

        def levels(pos: int, count: int, side: Side) -> tuple[tuple[L2Level, ...], int]:
            out: list[L2Level] = []
            for _ in range(count):
                price, qty = struct.unpack_from("<QQ", book_data, pos)
                pos += 16
                if price <= 0 or qty <= 0:
                    raise OrderbookReject(
                        OrderbookRejectCode.MARKET_LAYOUT_INVALID,
                        "bad level",
                    )
                out.append(L2Level(side, price, qty))
            return tuple(out), pos

        bids, pos = levels(0, bid_count, Side.BID)
        asks, _ = levels(pos, ask_count, Side.ASK)
        return OrderbookMarketSnapshot(
            market,
            self.spec,
            self.spec.program_id,
            "BaseMint11111111111111111111111111111111",
            "QuoteMint1111111111111111111111111111111",
            self.spec.supported_token_programs[0],
            self.spec.supported_token_programs[0],
            sha256(market_data),
            (sha256(book_data),),
            context_slot,
            source_slot,
            int(time.time()),
            self.decoder_version,
            MarketLotConfig(
                base_lot,
                quote_lot,
                tick,
                base_decimals,
                quote_decimals,
            ),
            TakerFeeConfig(fee_num, fee_den, self.spec.source),
            OrderbookDepth(bids, asks).sorted(),
        )

    def build_ioc_instruction(
        self,
        snapshot: OrderbookMarketSnapshot,
        quote: DepthQuote,
        authority: str,
        user_base_ata: str,
        user_quote_ata: str,
    ) -> OrderbookInstructionPlan:
        data = (
            b"IOC"
            + self.venue_kind.value.encode()
            + b":"
            + quote.direction.value.encode()
            + b":"
            + str(quote.executable_base_lots).encode()
        )
        ix = Instruction(
            snapshot.program_id,
            (snapshot.market_pubkey, authority, user_base_ata, user_quote_ata),
            data,
            "place_ioc_taker",
            f"{self.venue_kind.value}_ioc",
        )
        settle = Instruction(
            snapshot.program_id,
            (snapshot.market_pubkey, authority, user_base_ata, user_quote_ata),
            b"SETTLE_PROVEN",
            "settle_funds",
            f"{self.venue_kind.value}_settle",
        )
        return OrderbookInstructionPlan(
            (ix,),
            (settle,),
            (snapshot.market_pubkey, authority, user_base_ata, user_quote_ata),
            True,
            "zero_residual_orders_and_locked_funds",
        )

    def prove_postconditions(self, report: SimulationReport, account: str) -> None:
        states = {account_state.address: account_state for account_state in report.post_account_states}
        state = states.get(account)
        if not report.success:
            raise OrderbookReject(
                OrderbookRejectCode.ORDERBOOK_POSTCONDITION_UNPROVEN,
                "simulation failed",
            )
        if state is None:
            raise OrderbookReject(
                OrderbookRejectCode.ORDERBOOK_POSTCONDITION_UNPROVEN,
                "post account missing",
            )
        if b"RESTING" in state.data:
            raise OrderbookReject(
                OrderbookRejectCode.ORDERBOOK_RESIDUAL_ORDER,
                "resting marker",
            )
        if b"LOCKED" in state.data:
            raise OrderbookReject(
                OrderbookRejectCode.ORDERBOOK_RESIDUAL_LOCKED_FUNDS,
                "locked marker",
            )


class PhoenixLegacyVenueAdapter(_BinaryAdapter):
    venue_kind = VenueKind.PHOENIX_LEGACY_SPOT


class OpenBookV2VenueAdapter(_BinaryAdapter):
    venue_kind = VenueKind.OPENBOOK_V2
