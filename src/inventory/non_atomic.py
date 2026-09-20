"""AGG-13 durable non-atomic inventory and OMS/EMS evidence boundary.

This is deliberately not a sender. It persists intents and exchange receipts,
reconciles fills idempotently, exposes unresolved exposure, and preserves partial
or unknown outcomes across restart. Treasury/capital authorization remains owned
by the existing repository authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

AGG13_INVENTORY_SCHEMA = "agg13.inventory.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,191}$")


class InventoryError(ValueError):
    """Fail-closed inventory validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if message is None else f"{reason_code}: {message}")


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    FILLED = "filled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    RECONCILE_UNKNOWN_ORDER = "reconcile_unknown_order"
    CANCEL_REMAINDER = "cancel_remainder"
    HEDGE_OPEN_POSITION = "hedge_open_position"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    venue: str
    instrument: str
    settlement_asset: str
    quantity_unit: str

    def __post_init__(self) -> None:
        _require_id(self.venue, "venue")
        _require_id(self.instrument, "instrument")
        _require_id(self.settlement_asset, "settlement_asset")
        _require_id(self.quantity_unit, "quantity_unit")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.venue, self.instrument, self.settlement_asset)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    client_order_id: str
    strategy_id: str
    instrument: InstrumentIdentity
    side: OrderSide
    quantity_base_units: int
    max_partial_fill_loss_quote_units: int
    created_at_ns: int
    policy_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.client_order_id, "client_order_id")
        _require_id(self.strategy_id, "strategy_id")
        _require_positive_int(self.quantity_base_units, "quantity_base_units")
        _require_nonnegative_int(
            self.max_partial_fill_loss_quote_units,
            "max_partial_fill_loss_quote_units",
        )
        _require_nonnegative_int(self.created_at_ns, "created_at_ns")
        _require_sha256(self.policy_sha256, "policy_sha256")

    @property
    def intent_sha256(self) -> str:
        return _domain_hash("agg13/order-intent", _intent_payload(self))


@dataclass(frozen=True, slots=True)
class FillReceipt:
    fill_id: str
    client_order_id: str
    exchange_order_id: str
    quantity_base_units: int
    cash_delta_quote_base_units: int
    fee_quote_base_units: int
    observed_at_ns: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.fill_id, "fill_id")
        _require_id(self.client_order_id, "client_order_id")
        _require_id(self.exchange_order_id, "exchange_order_id")
        _require_positive_int(self.quantity_base_units, "quantity_base_units")
        _require_signed_int(
            self.cash_delta_quote_base_units,
            "cash_delta_quote_base_units",
        )
        _require_nonnegative_int(self.fee_quote_base_units, "fee_quote_base_units")
        _require_nonnegative_int(self.observed_at_ns, "observed_at_ns")
        _require_sha256(self.evidence_sha256, "evidence_sha256")

    @property
    def receipt_sha256(self) -> str:
        return _domain_hash("agg13/fill-receipt", _fill_payload(self))


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    client_order_id: str
    exchange_order_id: str | None
    status: OrderStatus
    requested_quantity_base_units: int
    cumulative_filled_base_units: int
    remaining_quantity_base_units: int
    version: int
    last_event_ns: int


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    instrument: InstrumentIdentity
    signed_quantity_base_units: int
    cash_delta_quote_base_units: int
    fees_quote_base_units: int
    updated_at_ns: int


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    client_order_id: str
    order_status: OrderStatus
    position_quantity_base_units: int
    remaining_order_quantity_base_units: int
    actions: tuple[RecoveryAction, ...]
    exposure_open: bool


_ALLOWED_STATUS_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset(
        {OrderStatus.OPEN, OrderStatus.REJECTED, OrderStatus.UNKNOWN}
    ),
    OrderStatus.OPEN: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELED,
            OrderStatus.FILLED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELED,
            OrderStatus.FILLED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.CANCEL_PENDING: frozenset(
        {
            OrderStatus.CANCEL_PENDING,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELED,
            OrderStatus.FILLED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.UNKNOWN: frozenset(
        {
            OrderStatus.UNKNOWN,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELED,
            OrderStatus.FILLED,
            OrderStatus.REJECTED,
        }
    ),
    OrderStatus.CANCELED: frozenset({OrderStatus.UNKNOWN}),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


class DurableInventoryLedger:
    """SQLite owner for non-atomic order/fill/position evidence only."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._create_schema()

    def _create_schema(self) -> None:
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS orders ("
            "client_order_id TEXT PRIMARY KEY, "
            "intent_json TEXT NOT NULL, intent_sha256 TEXT NOT NULL, "
            "exchange_order_id TEXT, status TEXT NOT NULL, "
            "requested_quantity INTEGER NOT NULL, cumulative_filled INTEGER NOT NULL, "
            "version INTEGER NOT NULL, last_event_ns INTEGER NOT NULL)"
        )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_exchange_id "
            "ON orders(exchange_order_id) WHERE exchange_order_id IS NOT NULL"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS fills ("
            "fill_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL, "
            "receipt_json TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, "
            "FOREIGN KEY(client_order_id) REFERENCES orders(client_order_id))"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS positions ("
            "venue TEXT NOT NULL, instrument TEXT NOT NULL, "
            "settlement_asset TEXT NOT NULL, quantity_unit TEXT NOT NULL, "
            "signed_quantity INTEGER NOT NULL, cash_delta_quote INTEGER NOT NULL, "
            "fees_quote INTEGER NOT NULL, updated_at_ns INTEGER NOT NULL, "
            "PRIMARY KEY(venue, instrument, settlement_asset))"
        )

    def register_order(self, intent: OrderIntent) -> OrderSnapshot:
        payload = json.dumps(
            _intent_payload(intent),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                "SELECT intent_sha256 FROM orders WHERE client_order_id=?",
                (intent.client_order_id,),
            ).fetchone()
            if row is not None:
                if str(row["intent_sha256"]) != intent.intent_sha256:
                    raise InventoryError("AGG13_ORDER_IDEMPOTENCY_CONFLICT")
                return self.order_snapshot(intent.client_order_id)
            self._db.execute(
                "INSERT INTO orders(client_order_id, intent_json, intent_sha256, "
                "exchange_order_id, status, requested_quantity, cumulative_filled, "
                "version, last_event_ns) VALUES (?, ?, ?, NULL, ?, ?, 0, 1, ?)",
                (
                    intent.client_order_id,
                    payload,
                    intent.intent_sha256,
                    OrderStatus.PENDING.value,
                    intent.quantity_base_units,
                    intent.created_at_ns,
                ),
            )
        return self.order_snapshot(intent.client_order_id)

    def acknowledge_order(
        self,
        *,
        client_order_id: str,
        exchange_order_id: str,
        observed_at_ns: int,
    ) -> OrderSnapshot:
        _require_id(exchange_order_id, "exchange_order_id")
        return self._transition(
            client_order_id=client_order_id,
            status=OrderStatus.OPEN,
            observed_at_ns=observed_at_ns,
            exchange_order_id=exchange_order_id,
        )

    def mark_status(
        self,
        *,
        client_order_id: str,
        status: OrderStatus,
        observed_at_ns: int,
    ) -> OrderSnapshot:
        return self._transition(
            client_order_id=client_order_id,
            status=status,
            observed_at_ns=observed_at_ns,
            exchange_order_id=None,
        )

    def _transition(
        self,
        *,
        client_order_id: str,
        status: OrderStatus,
        observed_at_ns: int,
        exchange_order_id: str | None,
    ) -> OrderSnapshot:
        _require_id(client_order_id, "client_order_id")
        _require_nonnegative_int(observed_at_ns, "observed_at_ns")
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._order_row(client_order_id)
            current = OrderStatus(str(row["status"]))
            existing_exchange = (
                None
                if row["exchange_order_id"] is None
                else str(row["exchange_order_id"])
            )
            if exchange_order_id is not None and existing_exchange not in {
                None,
                exchange_order_id,
            }:
                raise InventoryError("AGG13_EXCHANGE_ORDER_ID_CONFLICT")
            if observed_at_ns < int(row["last_event_ns"]):
                raise InventoryError("AGG13_ORDER_EVENT_TIME_REGRESSION")
            if status != current and status not in _ALLOWED_STATUS_TRANSITIONS[current]:
                raise InventoryError("AGG13_ILLEGAL_ORDER_STATUS_TRANSITION")
            final_exchange = exchange_order_id or existing_exchange
            self._db.execute(
                "UPDATE orders SET exchange_order_id=?, status=?, version=version+1, "
                "last_event_ns=? WHERE client_order_id=?",
                (final_exchange, status.value, observed_at_ns, client_order_id),
            )
        return self.order_snapshot(client_order_id)

    def record_fill(
        self,
        receipt: FillReceipt,
    ) -> tuple[OrderSnapshot, PositionSnapshot]:
        payload = json.dumps(
            _fill_payload(receipt),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self._db.execute(
                "SELECT receipt_sha256 FROM fills WHERE fill_id=?",
                (receipt.fill_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["receipt_sha256"]) != receipt.receipt_sha256:
                    raise InventoryError("AGG13_FILL_IDEMPOTENCY_CONFLICT")
                order = self.order_snapshot(receipt.client_order_id)
                return order, self.position_for_order(receipt.client_order_id)

            order_row = self._order_row(receipt.client_order_id)
            intent = _intent_from_json(str(order_row["intent_json"]))
            existing_exchange = (
                None
                if order_row["exchange_order_id"] is None
                else str(order_row["exchange_order_id"])
            )
            if existing_exchange not in {None, receipt.exchange_order_id}:
                raise InventoryError("AGG13_FILL_EXCHANGE_ORDER_MISMATCH")
            if receipt.observed_at_ns < int(order_row["last_event_ns"]):
                raise InventoryError("AGG13_FILL_EVENT_TIME_REGRESSION")
            if (
                intent.side is OrderSide.BUY
                and receipt.cash_delta_quote_base_units > 0
            ):
                raise InventoryError("AGG13_BUY_FILL_CASH_SIGN_INVALID")
            if (
                intent.side is OrderSide.SELL
                and receipt.cash_delta_quote_base_units < 0
            ):
                raise InventoryError("AGG13_SELL_FILL_CASH_SIGN_INVALID")

            cumulative = (
                int(order_row["cumulative_filled"]) + receipt.quantity_base_units
            )
            requested = int(order_row["requested_quantity"])
            if cumulative > requested:
                raise InventoryError("AGG13_ORDER_OVERFILL")

            self._db.execute(
                "INSERT INTO fills(fill_id, client_order_id, receipt_json, "
                "receipt_sha256) VALUES (?, ?, ?, ?)",
                (
                    receipt.fill_id,
                    receipt.client_order_id,
                    payload,
                    receipt.receipt_sha256,
                ),
            )
            current = OrderStatus(str(order_row["status"]))
            if cumulative == requested:
                next_status = OrderStatus.FILLED
            elif current in {OrderStatus.CANCEL_PENDING, OrderStatus.CANCELED}:
                next_status = current
            else:
                next_status = OrderStatus.PARTIALLY_FILLED
            self._db.execute(
                "UPDATE orders SET exchange_order_id=?, status=?, "
                "cumulative_filled=?, version=version+1, last_event_ns=? "
                "WHERE client_order_id=?",
                (
                    receipt.exchange_order_id,
                    next_status.value,
                    cumulative,
                    receipt.observed_at_ns,
                    receipt.client_order_id,
                ),
            )
            signed_delta = (
                receipt.quantity_base_units
                if intent.side is OrderSide.BUY
                else -receipt.quantity_base_units
            )
            self._apply_position_delta(
                instrument=intent.instrument,
                quantity_delta=signed_delta,
                cash_delta=receipt.cash_delta_quote_base_units,
                fee_delta=receipt.fee_quote_base_units,
                observed_at_ns=receipt.observed_at_ns,
            )
        return (
            self.order_snapshot(receipt.client_order_id),
            self.position_for_order(receipt.client_order_id),
        )

    def reconcile_exchange_state(
        self,
        *,
        client_order_id: str,
        exchange_status: OrderStatus,
        exchange_cumulative_filled_base_units: int,
        observed_at_ns: int,
    ) -> OrderSnapshot:
        """Reconcile status without fabricating missing fill economics."""

        _require_nonnegative_int(
            exchange_cumulative_filled_base_units,
            "exchange_cumulative_filled_base_units",
        )
        row = self._order_row(client_order_id)
        local = int(row["cumulative_filled"])
        if exchange_cumulative_filled_base_units < local:
            raise InventoryError("AGG13_EXCHANGE_FILL_REGRESSION")
        if exchange_cumulative_filled_base_units > local:
            return self.mark_status(
                client_order_id=client_order_id,
                status=OrderStatus.UNKNOWN,
                observed_at_ns=observed_at_ns,
            )
        return self.mark_status(
            client_order_id=client_order_id,
            status=exchange_status,
            observed_at_ns=observed_at_ns,
        )

    def order_snapshot(self, client_order_id: str) -> OrderSnapshot:
        row = self._order_row(client_order_id)
        requested = int(row["requested_quantity"])
        cumulative = int(row["cumulative_filled"])
        return OrderSnapshot(
            client_order_id=str(row["client_order_id"]),
            exchange_order_id=(
                None
                if row["exchange_order_id"] is None
                else str(row["exchange_order_id"])
            ),
            status=OrderStatus(str(row["status"])),
            requested_quantity_base_units=requested,
            cumulative_filled_base_units=cumulative,
            remaining_quantity_base_units=requested - cumulative,
            version=int(row["version"]),
            last_event_ns=int(row["last_event_ns"]),
        )

    def position_for_order(self, client_order_id: str) -> PositionSnapshot:
        row = self._order_row(client_order_id)
        intent = _intent_from_json(str(row["intent_json"]))
        return self.position_snapshot(intent.instrument)

    def position_snapshot(
        self,
        instrument: InstrumentIdentity,
    ) -> PositionSnapshot:
        row = self._db.execute(
            "SELECT * FROM positions WHERE venue=? AND instrument=? "
            "AND settlement_asset=?",
            instrument.key,
        ).fetchone()
        if row is None:
            return PositionSnapshot(
                instrument=instrument,
                signed_quantity_base_units=0,
                cash_delta_quote_base_units=0,
                fees_quote_base_units=0,
                updated_at_ns=0,
            )
        return PositionSnapshot(
            instrument=InstrumentIdentity(
                venue=str(row["venue"]),
                instrument=str(row["instrument"]),
                settlement_asset=str(row["settlement_asset"]),
                quantity_unit=str(row["quantity_unit"]),
            ),
            signed_quantity_base_units=int(row["signed_quantity"]),
            cash_delta_quote_base_units=int(row["cash_delta_quote"]),
            fees_quote_base_units=int(row["fees_quote"]),
            updated_at_ns=int(row["updated_at_ns"]),
        )

    def recovery_plan(self, client_order_id: str) -> RecoveryPlan:
        order = self.order_snapshot(client_order_id)
        position = self.position_for_order(client_order_id)
        actions: list[RecoveryAction] = []
        if order.status is OrderStatus.UNKNOWN:
            actions.append(RecoveryAction.RECONCILE_UNKNOWN_ORDER)
        if order.remaining_quantity_base_units > 0 and order.status in {
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.UNKNOWN,
        }:
            actions.append(RecoveryAction.CANCEL_REMAINDER)
        if position.signed_quantity_base_units != 0:
            actions.append(RecoveryAction.HEDGE_OPEN_POSITION)
        if (
            order.status is OrderStatus.UNKNOWN
            and position.signed_quantity_base_units != 0
        ):
            actions.append(RecoveryAction.MANUAL_REVIEW)
        return RecoveryPlan(
            client_order_id=client_order_id,
            order_status=order.status,
            position_quantity_base_units=position.signed_quantity_base_units,
            remaining_order_quantity_base_units=order.remaining_quantity_base_units,
            actions=tuple(dict.fromkeys(actions)),
            exposure_open=(
                position.signed_quantity_base_units != 0
                or order.status in {
                    OrderStatus.UNKNOWN,
                    OrderStatus.CANCEL_PENDING,
                }
            ),
        )

    def _apply_position_delta(
        self,
        *,
        instrument: InstrumentIdentity,
        quantity_delta: int,
        cash_delta: int,
        fee_delta: int,
        observed_at_ns: int,
    ) -> None:
        row = self._db.execute(
            "SELECT signed_quantity, cash_delta_quote, fees_quote, updated_at_ns "
            "FROM positions WHERE venue=? AND instrument=? AND settlement_asset=?",
            instrument.key,
        ).fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO positions(venue, instrument, settlement_asset, "
                "quantity_unit, signed_quantity, cash_delta_quote, fees_quote, "
                "updated_at_ns) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    instrument.venue,
                    instrument.instrument,
                    instrument.settlement_asset,
                    instrument.quantity_unit,
                    quantity_delta,
                    cash_delta,
                    fee_delta,
                    observed_at_ns,
                ),
            )
            return
        if observed_at_ns < int(row["updated_at_ns"]):
            raise InventoryError("AGG13_POSITION_EVENT_TIME_REGRESSION")
        self._db.execute(
            "UPDATE positions SET signed_quantity=?, cash_delta_quote=?, "
            "fees_quote=?, updated_at_ns=? WHERE venue=? AND instrument=? "
            "AND settlement_asset=?",
            (
                int(row["signed_quantity"]) + quantity_delta,
                int(row["cash_delta_quote"]) + cash_delta,
                int(row["fees_quote"]) + fee_delta,
                observed_at_ns,
                *instrument.key,
            ),
        )

    def _order_row(self, client_order_id: str) -> sqlite3.Row:
        _require_id(client_order_id, "client_order_id")
        row = self._db.execute(
            "SELECT * FROM orders WHERE client_order_id=?",
            (client_order_id,),
        ).fetchone()
        if row is None:
            raise InventoryError("AGG13_UNKNOWN_CLIENT_ORDER")
        return row

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> DurableInventoryLedger:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        self.close()


def _intent_payload(intent: OrderIntent) -> dict[str, Any]:
    return {
        "schema": AGG13_INVENTORY_SCHEMA,
        "client_order_id": intent.client_order_id,
        "strategy_id": intent.strategy_id,
        "instrument": {
            "venue": intent.instrument.venue,
            "instrument": intent.instrument.instrument,
            "settlement_asset": intent.instrument.settlement_asset,
            "quantity_unit": intent.instrument.quantity_unit,
        },
        "side": intent.side.value,
        "quantity_base_units": intent.quantity_base_units,
        "max_partial_fill_loss_quote_units": (
            intent.max_partial_fill_loss_quote_units
        ),
        "created_at_ns": intent.created_at_ns,
        "policy_sha256": intent.policy_sha256,
    }


def _fill_payload(receipt: FillReceipt) -> dict[str, Any]:
    return {
        "schema": AGG13_INVENTORY_SCHEMA,
        "fill_id": receipt.fill_id,
        "client_order_id": receipt.client_order_id,
        "exchange_order_id": receipt.exchange_order_id,
        "quantity_base_units": receipt.quantity_base_units,
        "cash_delta_quote_base_units": receipt.cash_delta_quote_base_units,
        "fee_quote_base_units": receipt.fee_quote_base_units,
        "observed_at_ns": receipt.observed_at_ns,
        "evidence_sha256": receipt.evidence_sha256,
    }


def _intent_from_json(raw: str) -> OrderIntent:
    payload = json.loads(raw)
    instrument = payload["instrument"]
    return OrderIntent(
        client_order_id=str(payload["client_order_id"]),
        strategy_id=str(payload["strategy_id"]),
        instrument=InstrumentIdentity(
            venue=str(instrument["venue"]),
            instrument=str(instrument["instrument"]),
            settlement_asset=str(instrument["settlement_asset"]),
            quantity_unit=str(instrument["quantity_unit"]),
        ),
        side=OrderSide(str(payload["side"])),
        quantity_base_units=int(payload["quantity_base_units"]),
        max_partial_fill_loss_quote_units=int(
            payload["max_partial_fill_loss_quote_units"]
        ),
        created_at_ns=int(payload["created_at_ns"]),
        policy_sha256=str(payload["policy_sha256"]),
    )


def _domain_hash(domain: str, payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(
        domain.encode("utf-8") + b"\0" + raw.encode("utf-8")
    ).hexdigest()


def _require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise InventoryError("AGG13_INVALID_IDENTIFIER", field)


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise InventoryError("AGG13_INVALID_SHA256", field)


def _require_positive_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InventoryError("AGG13_POSITIVE_INTEGER_REQUIRED", field)


def _require_nonnegative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InventoryError("AGG13_NONNEGATIVE_INTEGER_REQUIRED", field)


def _require_signed_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InventoryError("AGG13_INTEGER_REQUIRED", field)
