"""Double-entry movement model and replay-derived risk state for MPR-15."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from .mpr15_common import (
    AccountingStage, AssetIdentity, AttemptOutcome, LedgerAccountKind,
    LedgerEntryKind, MPR15_SCHEMA, PostingSide, RiskWindowKind,
    TreasuryAccountingError, _ALLOWED_STAGE_TRANSITIONS, _DAY_RE,
    _NANOSECONDS_PER_SECOND, _as_int, _ensure_mapping,
    _as_mapping, _as_str, _datetime_to_ns, _require_int, _require_pubkey,
    _require_sha256, _require_text, domain_hash,
)

@dataclass(frozen=True, slots=True)
class RiskWindow:
    kind: RiskWindowKind
    key: str
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        _require_text(self.key, "window key")
        _require_int(self.start_ns, "window start", lower=0)
        _require_int(self.end_ns, "window end", lower=0)
        if self.end_ns <= self.start_ns:
            raise TreasuryAccountingError("window end must be after start")
        if self.kind is RiskWindowKind.UTC_DAY and not _DAY_RE.fullmatch(self.key):
            raise TreasuryAccountingError("UTC day window key must be YYYY-MM-DD")

    @staticmethod
    def utc_day(day: str) -> RiskWindow:
        if not _DAY_RE.fullmatch(day):
            raise TreasuryAccountingError("UTC day must be YYYY-MM-DD")
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        return RiskWindow(
            kind=RiskWindowKind.UTC_DAY,
            key=day,
            start_ns=_datetime_to_ns(start),
            end_ns=_datetime_to_ns(end),
        )

    @staticmethod
    def rolling_24h(*, end_ns: int) -> RiskWindow:
        _require_int(
            end_ns,
            "rolling window end",
            lower=24 * 60 * 60 * _NANOSECONDS_PER_SECOND,
        )
        return RiskWindow(
            kind=RiskWindowKind.ROLLING_24H,
            key=f"rolling_24h:{end_ns}",
            start_ns=end_ns - 24 * 60 * 60 * _NANOSECONDS_PER_SECOND,
            end_ns=end_ns,
        )

    def contains(self, occurred_at_ns: int) -> bool:
        return self.start_ns <= occurred_at_ns < self.end_ns

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "key": self.key,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
        }


@dataclass(frozen=True, slots=True)
class LedgerPosting:
    account_kind: LedgerAccountKind
    account_id: str
    side: PostingSide
    amount_base_units: int

    def __post_init__(self) -> None:
        _require_text(self.account_id, "ledger account_id")
        _require_int(self.amount_base_units, "posting amount", lower=1)
        if self.account_kind is LedgerAccountKind.CHAIN_WALLET:
            _require_pubkey(self.account_id, "chain wallet account_id")

    def to_json(self) -> dict[str, object]:
        return {
            "account_kind": self.account_kind.value,
            "account_id": self.account_id,
            "side": self.side.value,
            "amount_base_units": str(self.amount_base_units),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> LedgerPosting:
        return cls(
            account_kind=LedgerAccountKind(_as_str(payload, "account_kind")),
            account_id=_as_str(payload, "account_id"),
            side=PostingSide(_as_str(payload, "side")),
            amount_base_units=int(_as_str(payload, "amount_base_units")),
        )


@dataclass(frozen=True, slots=True)
class RiskLedgerEntry:
    """One immutable stage event for one double-entry economic movement."""

    event_id: str
    movement_id: str
    idempotency_key: str
    asset: AssetIdentity
    kind: LedgerEntryKind
    stage: AccountingStage
    amount_delta_base_units: int
    occurred_at_ns: int
    recorded_at_ns: int
    postings: tuple[LedgerPosting, ...]
    evidence_hash: str
    attempt_id: str | None = None
    attempt_outcome: AttemptOutcome | None = None
    finalized_slot: int | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _require_sha256(self.event_id, "event_id")
        _require_sha256(self.movement_id, "movement_id")
        _require_sha256(self.idempotency_key, "idempotency_key")
        _require_sha256(self.evidence_hash, "evidence_hash")
        _require_int(self.amount_delta_base_units, "amount_delta_base_units")
        _require_int(self.occurred_at_ns, "occurred_at_ns", lower=0)
        _require_int(self.recorded_at_ns, "recorded_at_ns", lower=self.occurred_at_ns)
        if not self.postings:
            raise TreasuryAccountingError("economic movement requires postings")
        _validate_double_entry(self.postings, abs(self.amount_delta_base_units))
        _validate_movement_topology(self)
        if self.stage >= AccountingStage.FINALIZED:
            if self.finalized_slot is None:
                raise TreasuryAccountingError(
                    "finalized accounting requires slot proof"
                )
            _require_int(self.finalized_slot, "finalized_slot", lower=0)
        elif self.finalized_slot is not None:
            raise TreasuryAccountingError(
                "pre-finalized event cannot carry finalized slot"
            )
        if self.attempt_id is not None:
            _require_sha256(self.attempt_id, "attempt_id")
        if self.attempt_outcome is not None and self.attempt_id is None:
            raise TreasuryAccountingError("attempt outcome requires attempt_id")
        if self.kind is LedgerEntryKind.FAILED_ATTEMPT_CHARGE:
            if self.attempt_outcome is not AttemptOutcome.FAILED:
                raise TreasuryAccountingError(
                    "failed attempt charge requires failed outcome"
                )
        if self.attempt_outcome is AttemptOutcome.SUCCEEDED:
            if self.kind is not LedgerEntryKind.REALIZED_PNL:
                raise TreasuryAccountingError("success outcome must bind realized PnL")

    @property
    def movement_fingerprint(self) -> str:
        return domain_hash("mpr15/economic-movement", self.movement_json())

    @property
    def event_hash(self) -> str:
        return domain_hash("mpr15/ledger-event", self.to_json())

    def movement_json(self) -> dict[str, object]:
        return {
            "movement_id": self.movement_id,
            "asset": self.asset.to_json(),
            "kind": self.kind.value,
            "amount_delta_base_units": str(self.amount_delta_base_units),
            "occurred_at_ns": self.occurred_at_ns,
            "postings": [item.to_json() for item in self.postings],
            "evidence_hash": self.evidence_hash,
            "attempt_id": self.attempt_id,
            "attempt_outcome": (
                self.attempt_outcome.value if self.attempt_outcome is not None else None
            ),
            "reason": self.reason,
        }

    def to_json(self) -> dict[str, object]:
        return {
            "schema": MPR15_SCHEMA,
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            **self.movement_json(),
            "stage": self.stage.label,
            "recorded_at_ns": self.recorded_at_ns,
            "finalized_slot": self.finalized_slot,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> RiskLedgerEntry:
        if _as_str(payload, "schema") != MPR15_SCHEMA:
            raise TreasuryAccountingError("unsupported ledger event schema")
        raw_postings = payload.get("postings")
        if not isinstance(raw_postings, list):
            raise TreasuryAccountingError("ledger postings must be a list")
        raw_outcome = payload.get("attempt_outcome")
        if raw_outcome is not None and not isinstance(raw_outcome, str):
            raise TreasuryAccountingError("attempt_outcome must be text or null")
        raw_attempt = payload.get("attempt_id")
        if raw_attempt is not None and not isinstance(raw_attempt, str):
            raise TreasuryAccountingError("attempt_id must be text or null")
        raw_slot = payload.get("finalized_slot")
        if raw_slot is not None and (
            isinstance(raw_slot, bool) or not isinstance(raw_slot, int)
        ):
            raise TreasuryAccountingError("finalized_slot must be integer or null")
        return cls(
            event_id=_as_str(payload, "event_id"),
            movement_id=_as_str(payload, "movement_id"),
            idempotency_key=_as_str(payload, "idempotency_key"),
            asset=AssetIdentity.from_json(_as_mapping(payload, "asset")),
            kind=LedgerEntryKind(_as_str(payload, "kind")),
            stage=AccountingStage[_as_str(payload, "stage").upper()],
            amount_delta_base_units=int(_as_str(payload, "amount_delta_base_units")),
            occurred_at_ns=_as_int(payload, "occurred_at_ns"),
            recorded_at_ns=_as_int(payload, "recorded_at_ns"),
            postings=tuple(
                LedgerPosting.from_json(_ensure_mapping(item, "posting"))
                for item in raw_postings
            ),
            evidence_hash=_as_str(payload, "evidence_hash"),
            attempt_id=raw_attempt,
            attempt_outcome=AttemptOutcome(raw_outcome) if raw_outcome else None,
            finalized_slot=raw_slot,
            reason=str(payload.get("reason", "")),
        )


@dataclass(frozen=True, slots=True)
class RiskCounterSnapshot:
    asset: AssetIdentity
    window: RiskWindow
    realized_pnl_base_units: int = 0
    fees_base_units: int = 0
    rent_locked_base_units: int = 0
    rent_refunded_base_units: int = 0
    tips_base_units: int = 0
    transfer_fees_base_units: int = 0
    failed_attempt_charges_base_units: int = 0
    unresolved_max_loss_base_units: int = 0
    provider_spend_base_units: int = 0
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        _require_int(self.realized_pnl_base_units, "realized_pnl_base_units")
        for field in (
            "fees_base_units",
            "rent_locked_base_units",
            "rent_refunded_base_units",
            "tips_base_units",
            "transfer_fees_base_units",
            "failed_attempt_charges_base_units",
            "unresolved_max_loss_base_units",
            "provider_spend_base_units",
            "consecutive_failures",
        ):
            _require_int(getattr(self, field), field, lower=0)

    def to_json(self) -> dict[str, object]:
        return {
            "asset": self.asset.to_json(),
            "window": self.window.to_json(),
            "realized_pnl_base_units": str(self.realized_pnl_base_units),
            "fees_base_units": str(self.fees_base_units),
            "rent_locked_base_units": str(self.rent_locked_base_units),
            "rent_refunded_base_units": str(self.rent_refunded_base_units),
            "tips_base_units": str(self.tips_base_units),
            "transfer_fees_base_units": str(self.transfer_fees_base_units),
            "failed_attempt_charges_base_units": str(
                self.failed_attempt_charges_base_units
            ),
            "unresolved_max_loss_base_units": str(self.unresolved_max_loss_base_units),
            "provider_spend_base_units": str(self.provider_spend_base_units),
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass(frozen=True, slots=True, init=False)
class DurableRiskState:
    schema: str
    snapshots: tuple[RiskCounterSnapshot, ...]
    ledger_hash: str
    entry_count: int
    movement_count: int
    previous_checkpoint_hash: str
    checkpoint_hash: str

    @classmethod
    def from_entries(
        cls,
        *,
        entries: Sequence[RiskLedgerEntry],
        windows: Sequence[RiskWindow],
        asset: AssetIdentity,
        previous_checkpoint_hash: str | None = None,
    ) -> DurableRiskState:
        previous = previous_checkpoint_hash or "0" * 64
        _require_sha256(previous, "previous_checkpoint_hash")
        latest = materialize_latest_movements(entries)
        snapshots = tuple(
            fold_risk_counters(
                entries=tuple(latest.values()),
                window=window,
                asset=asset,
            )
            for window in windows
        )
        ordered_events = sorted(
            entries, key=lambda item: (item.recorded_at_ns, item.event_id)
        )
        ledger_hash = domain_hash(
            "mpr15/ledger-head",
            [entry.to_json() for entry in ordered_events],
        )
        checkpoint_payload = {
            "schema": MPR15_SCHEMA,
            "snapshots": [snapshot.to_json() for snapshot in snapshots],
            "ledger_hash": ledger_hash,
            "entry_count": len(ordered_events),
            "movement_count": len(latest),
            "previous_checkpoint_hash": previous,
        }
        instance = object.__new__(cls)
        object.__setattr__(instance, "schema", MPR15_SCHEMA)
        object.__setattr__(instance, "snapshots", snapshots)
        object.__setattr__(instance, "ledger_hash", ledger_hash)
        object.__setattr__(instance, "entry_count", len(ordered_events))
        object.__setattr__(instance, "movement_count", len(latest))
        object.__setattr__(instance, "previous_checkpoint_hash", previous)
        object.__setattr__(
            instance,
            "checkpoint_hash",
            domain_hash("mpr15/risk-checkpoint", checkpoint_payload),
        )
        return instance

    def verify_replay(
        self,
        *,
        entries: Sequence[RiskLedgerEntry],
        windows: Sequence[RiskWindow],
        asset: AssetIdentity,
    ) -> None:
        replayed = DurableRiskState.from_entries(
            entries=entries,
            windows=windows,
            asset=asset,
            previous_checkpoint_hash=self.previous_checkpoint_hash,
        )
        if replayed.to_json() != self.to_json():
            raise TreasuryAccountingError("durable risk checkpoint differs from replay")

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "snapshots": [snapshot.to_json() for snapshot in self.snapshots],
            "ledger_hash": self.ledger_hash,
            "entry_count": self.entry_count,
            "movement_count": self.movement_count,
            "previous_checkpoint_hash": self.previous_checkpoint_hash,
            "checkpoint_hash": self.checkpoint_hash,
        }


def materialize_latest_movements(
    entries: Sequence[RiskLedgerEntry],
) -> dict[str, RiskLedgerEntry]:
    latest: dict[str, RiskLedgerEntry] = {}
    idempotency: dict[str, str] = {}
    event_ids: dict[str, str] = {}
    for entry in sorted(
        entries,
        key=lambda item: (item.recorded_at_ns, int(item.stage), item.event_id),
    ):
        previous_event_hash = event_ids.get(entry.event_id)
        if previous_event_hash is not None:
            if previous_event_hash != entry.event_hash:
                raise TreasuryAccountingError("ledger event_id reused with new payload")
            continue
        event_ids[entry.event_id] = entry.event_hash
        previous_idempotency_hash = idempotency.get(entry.idempotency_key)
        if previous_idempotency_hash is not None:
            if previous_idempotency_hash != entry.event_hash:
                raise TreasuryAccountingError("idempotency key reused with new payload")
            continue
        idempotency[entry.idempotency_key] = entry.event_hash

        current = latest.get(entry.movement_id)
        if current is None:
            latest[entry.movement_id] = entry
            continue
        if current.movement_fingerprint != entry.movement_fingerprint:
            raise TreasuryAccountingError(
                "economic movement identity changed across stages"
            )
        if entry.stage == current.stage:
            continue
        expected = _ALLOWED_STAGE_TRANSITIONS.get(current.stage)
        if expected is None or entry.stage != expected:
            raise TreasuryAccountingError("illegal accounting stage transition")
        latest[entry.movement_id] = entry
    return latest


def fold_risk_counters(
    *,
    entries: Sequence[RiskLedgerEntry],
    window: RiskWindow,
    asset: AssetIdentity,
) -> RiskCounterSnapshot:
    latest = materialize_latest_movements(entries)
    totals = {kind: 0 for kind in LedgerEntryKind}
    outcomes: dict[str, tuple[int, AttemptOutcome]] = {}
    for entry in latest.values():
        if entry.asset != asset or not window.contains(entry.occurred_at_ns):
            continue
        if entry.stage < AccountingStage.FINALIZED:
            continue
        totals[entry.kind] += entry.amount_delta_base_units
        if entry.attempt_id and entry.attempt_outcome:
            existing = outcomes.get(entry.attempt_id)
            candidate = (entry.occurred_at_ns, entry.attempt_outcome)
            if existing is not None and existing[1] is not entry.attempt_outcome:
                raise TreasuryAccountingError(
                    "attempt has conflicting terminal outcomes"
                )
            if existing is None or candidate[0] < existing[0]:
                outcomes[entry.attempt_id] = candidate

    consecutive_failures = 0
    for _, outcome in sorted(outcomes.values(), key=lambda item: item[0]):
        if outcome is AttemptOutcome.FAILED:
            consecutive_failures += 1
        else:
            consecutive_failures = 0

    return RiskCounterSnapshot(
        asset=asset,
        window=window,
        realized_pnl_base_units=totals[LedgerEntryKind.REALIZED_PNL],
        fees_base_units=totals[LedgerEntryKind.FEE],
        rent_locked_base_units=totals[LedgerEntryKind.RENT_LOCKED],
        rent_refunded_base_units=totals[LedgerEntryKind.RENT_REFUNDED],
        tips_base_units=totals[LedgerEntryKind.TIP],
        transfer_fees_base_units=totals[LedgerEntryKind.TRANSFER_FEE],
        failed_attempt_charges_base_units=totals[
            LedgerEntryKind.FAILED_ATTEMPT_CHARGE
        ],
        unresolved_max_loss_base_units=totals[LedgerEntryKind.UNRESOLVED_MAX_LOSS],
        provider_spend_base_units=totals[LedgerEntryKind.PROVIDER_SPEND],
        consecutive_failures=consecutive_failures,
    )


def _validate_double_entry(postings: Sequence[LedgerPosting], amount: int) -> None:
    if amount <= 0:
        raise TreasuryAccountingError("economic movement amount cannot be zero")
    debits = sum(
        posting.amount_base_units
        for posting in postings
        if posting.side is PostingSide.DEBIT
    )
    credits = sum(
        posting.amount_base_units
        for posting in postings
        if posting.side is PostingSide.CREDIT
    )
    if debits != credits:
        raise TreasuryAccountingError("double-entry postings do not balance")
    if debits != amount:
        raise TreasuryAccountingError("postings do not explain movement amount")


def _validate_movement_topology(entry: RiskLedgerEntry) -> None:
    if entry.kind is LedgerEntryKind.REALIZED_PNL:
        if entry.amount_delta_base_units == 0:
            raise TreasuryAccountingError("realized PnL cannot be zero")
        if entry.amount_delta_base_units > 0:
            _require_posting_pair(
                entry.postings,
                debit=LedgerAccountKind.CHAIN_WALLET,
                credit=LedgerAccountKind.PNL_INCOME,
            )
        else:
            _require_posting_pair(
                entry.postings,
                debit=LedgerAccountKind.PNL_LOSS,
                credit=LedgerAccountKind.CHAIN_WALLET,
            )
        return
    if entry.amount_delta_base_units <= 0:
        raise TreasuryAccountingError(f"{entry.kind.value} amount must be positive")
    topology: dict[LedgerEntryKind, tuple[LedgerAccountKind, LedgerAccountKind]] = {
        LedgerEntryKind.FUNDING: (
            LedgerAccountKind.CHAIN_WALLET,
            LedgerAccountKind.FUNDING_SOURCE,
        ),
        LedgerEntryKind.WITHDRAWAL: (
            LedgerAccountKind.WITHDRAWAL_DESTINATION,
            LedgerAccountKind.CHAIN_WALLET,
        ),
        LedgerEntryKind.FEE: (
            LedgerAccountKind.FEE_EXPENSE,
            LedgerAccountKind.CHAIN_WALLET,
        ),
        LedgerEntryKind.RENT_LOCKED: (
            LedgerAccountKind.RENT_ASSET,
            LedgerAccountKind.CHAIN_WALLET,
        ),
        LedgerEntryKind.RENT_REFUNDED: (
            LedgerAccountKind.CHAIN_WALLET,
            LedgerAccountKind.RENT_ASSET,
        ),
        LedgerEntryKind.TIP: (
            LedgerAccountKind.TIP_EXPENSE,
            LedgerAccountKind.CHAIN_WALLET,
        ),
        LedgerEntryKind.TRANSFER_FEE: (
            LedgerAccountKind.TRANSFER_FEE_EXPENSE,
            LedgerAccountKind.CHAIN_WALLET,
        ),
        LedgerEntryKind.FAILED_ATTEMPT_CHARGE: (
            LedgerAccountKind.FAILED_ATTEMPT_EXPENSE,
            LedgerAccountKind.CHAIN_WALLET,
        ),
        LedgerEntryKind.UNRESOLVED_MAX_LOSS: (
            LedgerAccountKind.UNRESOLVED_RESERVE,
            LedgerAccountKind.RISK_CONTRA,
        ),
        LedgerEntryKind.PROVIDER_SPEND: (
            LedgerAccountKind.PROVIDER_EXPENSE,
            LedgerAccountKind.CHAIN_WALLET,
        ),
    }
    debit, credit = topology[entry.kind]
    _require_posting_pair(entry.postings, debit=debit, credit=credit)


def _require_posting_pair(
    postings: Sequence[LedgerPosting],
    *,
    debit: LedgerAccountKind,
    credit: LedgerAccountKind,
) -> None:
    if len(postings) != 2:
        raise TreasuryAccountingError(
            "movement requires exactly one debit and one credit"
        )
    actual = {(item.side, item.account_kind) for item in postings}
    expected = {(PostingSide.DEBIT, debit), (PostingSide.CREDIT, credit)}
    if actual != expected:
        raise TreasuryAccountingError("movement posting topology is invalid")
