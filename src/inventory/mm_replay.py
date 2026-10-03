"""One-venue offline queue/cancel/markout experiment using AGG13 inventory.

The FIFO queue model is an explicit synthetic assumption. No exchange orders
are sent; resting exposure requires wallet inventory, never atomic flash funding.
"""

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from .non_atomic import (
    DurableInventoryLedger,
    FillReceipt,
    OrderIntent,
    OrderSide,
    OrderStatus,
    InventoryError,
)


@dataclass(frozen=True, slots=True)
class TapeTrade:
    trade_id: str
    available_at_ns: int
    price_quote_atoms_per_base_atom: int
    quantity_base_atoms: int
    aggressive_side: OrderSide

    def __post_init__(self):
        if not self.trade_id.strip():
            raise InventoryError("MM_TRADE_ID_REQUIRED")
        for field in (
            "available_at_ns",
            "price_quote_atoms_per_base_atom",
            "quantity_base_atoms",
        ):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise InventoryError("MM_INTEGER_TAPE_REQUIRED")
        if not isinstance(self.aggressive_side, OrderSide):
            raise InventoryError("MM_SIDE_REQUIRED")


@dataclass(frozen=True, slots=True)
class MarketMakerReplayReport:
    filled_base_atoms: int
    remaining_base_atoms: int
    markout_quote_atoms: int
    terminal_marked_net_quote_atoms: int
    queue_model: str = "synthetic-fifo-v1"
    execution_right: bool = False


def replay_resting_order(
    *,
    ledger: DurableInventoryLedger,
    intent: OrderIntent,
    tape: tuple[TapeTrade, ...],
    limit_price_quote_atoms_per_base_atom: int,
    queue_ahead_base_atoms: int,
    arrival_latency_ns: int,
    cancel_acknowledged_at_ns: int | None,
    terminal_mid_quote_atoms_per_base_atom: int,
    fee_bps: int,
    hedge_cost_quote_atoms: int,
    wallet_available_base_atoms: int,
    wallet_available_quote_atoms: int,
    funding_mode: str = "wallet",
) -> MarketMakerReplayReport:
    if funding_mode != "wallet":
        raise InventoryError("MM_RESTING_FLASH_FINANCING_FORBIDDEN")
    for value in (
        limit_price_quote_atoms_per_base_atom,
        queue_ahead_base_atoms,
        arrival_latency_ns,
        terminal_mid_quote_atoms_per_base_atom,
        fee_bps,
        hedge_cost_quote_atoms,
        wallet_available_base_atoms,
        wallet_available_quote_atoms,
    ):
        if type(value) is not int or value < 0:
            raise InventoryError("MM_INTEGER_TERMS_REQUIRED")
    if (
        not limit_price_quote_atoms_per_base_atom
        or fee_bps >= 10000
        or not terminal_mid_quote_atoms_per_base_atom
    ):
        raise InventoryError("MM_PRICE_OR_FEE_INVALID")
    if len(tape) > 10000 or len({t.trade_id for t in tape}) != len(tape):
        raise InventoryError("MM_TAPE_BOUND_OR_DUPLICATE")
    arrival = intent.created_at_ns + arrival_latency_ns
    if cancel_acknowledged_at_ns is not None and (
        type(cancel_acknowledged_at_ns) is not int
        or cancel_acknowledged_at_ns < arrival
    ):
        raise InventoryError("MM_CANCEL_ACK_INVALID")
    notional = intent.quantity_base_units * limit_price_quote_atoms_per_base_atom
    total_fee_bound = intent.quantity_base_units * (
        (limit_price_quote_atoms_per_base_atom * fee_bps + 9999) // 10000
    )
    if intent.side is OrderSide.BUY:
        if (
            wallet_available_quote_atoms
            < notional + total_fee_bound + hedge_cost_quote_atoms
        ):
            raise InventoryError("MM_WALLET_CAPACITY")
    elif (
        wallet_available_base_atoms < intent.quantity_base_units
        or wallet_available_quote_atoms < total_fee_bound + hedge_cost_quote_atoms
    ):
        raise InventoryError("MM_WALLET_CAPACITY")
    order = ledger.register_order(intent)
    exchange_id = "offline/" + intent.client_order_id
    if order.status is OrderStatus.PENDING:
        ledger.acknowledge_order(
            client_order_id=intent.client_order_id,
            exchange_order_id=exchange_id,
            observed_at_ns=arrival,
        )
    remaining = intent.quantity_base_units
    ahead = queue_ahead_base_atoms
    filled = fees = 0
    for trade in sorted(tape, key=lambda t: (t.available_at_ns, t.trade_id)):
        if (
            trade.available_at_ns < arrival
            or (
                cancel_acknowledged_at_ns is not None
                and trade.available_at_ns >= cancel_acknowledged_at_ns
            )
            or not remaining
        ):
            continue
        crosses = (
            intent.side is OrderSide.BUY
            and trade.aggressive_side is OrderSide.SELL
            and trade.price_quote_atoms_per_base_atom
            <= limit_price_quote_atoms_per_base_atom
        ) or (
            intent.side is OrderSide.SELL
            and trade.aggressive_side is OrderSide.BUY
            and trade.price_quote_atoms_per_base_atom
            >= limit_price_quote_atoms_per_base_atom
        )
        if not crosses:
            continue
        consumed_queue = min(ahead, trade.quantity_base_atoms)
        ahead -= consumed_queue
        qty = min(remaining, trade.quantity_base_atoms - consumed_queue)
        if not qty:
            continue
        cash = qty * limit_price_quote_atoms_per_base_atom
        fee = (cash * fee_bps + 9999) // 10000
        sign = -1 if intent.side is OrderSide.BUY else 1
        digest = sha256(
            repr((intent.intent_sha256, trade, qty, cash, fee)).encode()
        ).hexdigest()
        ledger.record_fill(
            FillReceipt(
                "offline/" + intent.client_order_id + "/" + trade.trade_id,
                intent.client_order_id,
                exchange_id,
                qty,
                sign * cash,
                fee,
                trade.available_at_ns,
                digest,
            )
        )
        filled += qty
        remaining -= qty
        fees += fee
    if cancel_acknowledged_at_ns is not None and remaining:
        ledger.mark_status(
            client_order_id=intent.client_order_id,
            status=OrderStatus.CANCELED,
            observed_at_ns=cancel_acknowledged_at_ns,
        )
    sign = 1 if intent.side is OrderSide.BUY else -1
    markout = (
        sign
        * filled
        * (
            terminal_mid_quote_atoms_per_base_atom
            - limit_price_quote_atoms_per_base_atom
        )
    )
    return MarketMakerReplayReport(
        filled,
        remaining,
        markout,
        markout - fees - (hedge_cost_quote_atoms if filled else 0),
    )
