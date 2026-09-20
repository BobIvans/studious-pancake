"""Canonical AGG-02 composition over existing repository authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.data_plane.bounded_provider_plane_pr197 import SQLiteQuotaAuthority
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)

from .capital import BudgetEnvelope, observe_budget_envelope
from .contracts import RawEventEnvelope, StateFrame, StateRecord, build_state_frame
from .graph import AffectedRouteIndex
from .source_budget import (
    BudgetDimension,
    SourceBudgetAuthority,
    SourceBudgetReservation,
    SourceRegistryEntry,
)
from .storage import DurableRawJournal, JournalReceipt


@dataclass(frozen=True, slots=True)
class Agg02Owners:
    quota_authority: str
    capital_authority: str
    raw_journal: str


class Agg02Composition:
    """Aggregate seam; it owns no signer, sender or financial reservation state."""

    def __init__(
        self,
        *,
        quota_authority: SQLiteQuotaAuthority,
        raw_journal: DurableRawJournal,
        capital_coordinator: DurableCapitalCoordinator,
    ) -> None:
        self.source_budget = SourceBudgetAuthority(quota_authority)
        self.raw_journal = raw_journal
        self.capital_coordinator = capital_coordinator

    @property
    def owners(self) -> Agg02Owners:
        return Agg02Owners(
            quota_authority=(
                "src.data_plane.bounded_provider_plane_pr197:SQLiteQuotaAuthority"
            ),
            capital_authority=(
                "src.economics.durable_reservations:DurableCapitalCoordinator"
            ),
            raw_journal="src.agg02.storage:DurableRawJournal",
        )

    def reserve_source_budget(
        self,
        *,
        source: SourceRegistryEntry,
        key_fingerprint: str,
        now_ms: int,
        dimensions: Iterable[BudgetDimension],
    ) -> SourceBudgetReservation:
        return self.source_budget.reserve(
            source=source,
            key_fingerprint=key_fingerprint,
            now_ms=now_ms,
            dimensions=dimensions,
        )

    def ingest_raw(self, envelope: RawEventEnvelope, payload: bytes) -> JournalReceipt:
        return self.raw_journal.append(envelope, payload)

    @staticmethod
    def state_frame(
        records: Iterable[StateRecord],
        *,
        required_dependencies: Iterable[str],
        decision_time_ms: int,
    ) -> StateFrame:
        return build_state_frame(
            records,
            required_dependencies=required_dependencies,
            decision_time_ms=decision_time_ms,
        )

    @staticmethod
    def affected_routes(
        index: AffectedRouteIndex, *, changed_dependencies: Iterable[str]
    ) -> tuple[str, ...]:
        return index.affected_by(changed_dependencies)

    def budget_envelope(
        self,
        *,
        snapshot: WalletBalanceSnapshot | None,
        active_reserved_lamports: int,
        native_fee_floor_lamports: int,
        peak_rent_lamports: int,
        now_ns: int,
        max_snapshot_age_ns: int,
        expected_genesis: str | None = None,
    ) -> BudgetEnvelope:
        return observe_budget_envelope(
            snapshot=snapshot,
            active_reserved_lamports=active_reserved_lamports,
            native_fee_floor_lamports=native_fee_floor_lamports,
            peak_rent_lamports=peak_rent_lamports,
            now_ns=now_ns,
            max_snapshot_age_ns=max_snapshot_age_ns,
            expected_genesis=expected_genesis,
        )
