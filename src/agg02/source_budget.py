"""Shared source budgets, entitlements, retry policy and subscription fanout."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from src.data_plane.bounded_provider_plane_pr197 import (
    ProviderPlaneError,
    QuotaReservation,
    SQLiteQuotaAuthority,
)

from .contracts import Agg02Error, canonical_hash


class SourceAccess(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class SourceRegistryEntry:
    source_id: str
    role: str
    metering_unit: str
    credential_scope: str
    storage_allowed: bool
    access: SourceAccess
    entitlement_expires_at_ms: int | None = None
    correlation_group: str = "unknown"

    def assert_usable(self, *, now_ms: int) -> None:
        if self.access is not SourceAccess.ACTIVE:
            raise Agg02Error("AGG02_SOURCE_NOT_ACTIVE")
        if (
            self.entitlement_expires_at_ms is not None
            and now_ms >= self.entitlement_expires_at_ms
        ):
            raise Agg02Error("AGG02_SOURCE_ENTITLEMENT_EXPIRED")


@dataclass(frozen=True, slots=True)
class BudgetDimension:
    name: str
    limit: int
    span_ms: int
    units: int = 1

    def __post_init__(self) -> None:
        if not self.name:
            raise Agg02Error("AGG02_BUDGET_DIMENSION_NAME_REQUIRED")
        for value, field in (
            (self.limit, "limit"),
            (self.span_ms, "span_ms"),
            (self.units, "units"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise Agg02Error("AGG02_INVALID_BUDGET_DIMENSION", field)
        if self.units > self.limit:
            raise Agg02Error("AGG02_BUDGET_UNITS_EXCEED_LIMIT")


@dataclass(frozen=True, slots=True)
class SourceBudgetReservation:
    source_id: str
    reservations: tuple[QuotaReservation, ...]
    reservation_hash: str


class SourceBudgetAuthority:
    """AGG-02 adapter over the existing PR-197 SQLite quota authority.

    It deliberately does not create another quota database. Multiple workers
    receive adapters pointing at the same SQLiteQuotaAuthority backing path.
    Multi-dimension reservation is conservative: if a later dimension fails,
    earlier reservations stay consumed instead of being released.
    """

    def __init__(self, authority: SQLiteQuotaAuthority) -> None:
        self._authority = authority

    def reserve(
        self,
        *,
        source: SourceRegistryEntry,
        key_fingerprint: str,
        now_ms: int,
        dimensions: Iterable[BudgetDimension],
    ) -> SourceBudgetReservation:
        source.assert_usable(now_ms=now_ms)
        ordered = tuple(sorted(dimensions, key=lambda item: (item.span_ms, item.name)))
        if not ordered:
            raise Agg02Error("AGG02_EMPTY_BUDGET_REQUEST")
        reservations: list[QuotaReservation] = []
        try:
            for dimension in ordered:
                reservations.append(
                    self._authority.reserve(
                        provider=f"{source.source_id}/{dimension.name}",
                        key_fingerprint=key_fingerprint,
                        now_ms=now_ms,
                        limit=dimension.limit,
                        bucket_span_ms=dimension.span_ms,
                        units=dimension.units,
                    )
                )
        except ProviderPlaneError as exc:
            raise Agg02Error("AGG02_SOURCE_BUDGET_DENIED", exc.reason_code) from exc
        reservation_hash = canonical_hash(
            {
                "source_id": source.source_id,
                "reservations": [item.reservation_id for item in reservations],
            }
        )
        return SourceBudgetReservation(
            source_id=source.source_id,
            reservations=tuple(reservations),
            reservation_hash=reservation_hash,
        )


@dataclass(frozen=True, slots=True)
class UsageEvent:
    source_id: str
    request_units: int = 0
    response_bytes: int = 0
    retry_units: int = 0
    backfill_units: int = 0

    @property
    def total_units(self) -> int:
        return self.request_units + self.retry_units + self.backfill_units


@dataclass(frozen=True, slots=True)
class UsageSummary:
    source_id: str
    request_units: int
    response_bytes: int
    retry_units: int
    backfill_units: int


def summarize_usage(events: Iterable[UsageEvent]) -> tuple[UsageSummary, ...]:
    totals: dict[str, list[int]] = {}
    for event in events:
        values = (
            event.request_units,
            event.response_bytes,
            event.retry_units,
            event.backfill_units,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise Agg02Error("AGG02_INVALID_USAGE_EVENT")
        current = totals.setdefault(event.source_id, [0, 0, 0, 0])
        for index, value in enumerate(values):
            current[index] += value
    return tuple(
        UsageSummary(source_id, *totals[source_id]) for source_id in sorted(totals)
    )


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    reason: str
    delay_ms: int | None


def classify_retry(
    *,
    status_code: int | None,
    retry_after_ms: int | None,
    attempt: int,
    max_attempts: int,
    now_ms: int,
    deadline_ms: int,
) -> RetryDecision:
    if attempt >= max_attempts:
        return RetryDecision(False, "attempt_budget_exhausted", None)
    if now_ms >= deadline_ms:
        return RetryDecision(False, "deadline_expired", None)
    if status_code in {401, 403}:
        return RetryDecision(False, "authorization_failure", None)
    if status_code == 429:
        delay = 0 if retry_after_ms is None else retry_after_ms
        if delay < 0 or now_ms + delay >= deadline_ms:
            return RetryDecision(False, "retry_after_exceeds_deadline", None)
        return RetryDecision(True, "rate_limited", delay)
    if status_code is None or status_code >= 500:
        remaining = deadline_ms - now_ms
        delay = min(250 * (2**attempt), max(0, remaining - 1))
        return RetryDecision(delay > 0, "transient", delay if delay > 0 else None)
    return RetryDecision(False, "non_retryable", None)


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    source_id: str
    accounts: tuple[str, ...]
    consumers_by_account: Mapping[str, tuple[str, ...]]
    plan_hash: str


def build_subscription_plan(
    *,
    source_id: str,
    requirements: Mapping[str, Iterable[str]],
) -> SubscriptionPlan:
    account_consumers: dict[str, set[str]] = {}
    for consumer, accounts in requirements.items():
        if not consumer:
            raise Agg02Error("AGG02_EMPTY_SUBSCRIPTION_CONSUMER")
        for account in accounts:
            if not account:
                raise Agg02Error("AGG02_EMPTY_SUBSCRIPTION_ACCOUNT")
            account_consumers.setdefault(account, set()).add(consumer)
    if not account_consumers:
        raise Agg02Error("AGG02_EMPTY_SUBSCRIPTION_PLAN")
    normalized = {
        account: tuple(sorted(consumers))
        for account, consumers in sorted(account_consumers.items())
    }
    plan_hash = canonical_hash(
        {"source_id": source_id, "consumers_by_account": normalized}
    )
    return SubscriptionPlan(
        source_id=source_id,
        accounts=tuple(normalized),
        consumers_by_account=normalized,
        plan_hash=plan_hash,
    )


@dataclass(frozen=True, slots=True)
class SourceSloVerdict:
    qualified: bool
    reason: str
    freshness_ms: int | None
    gap_count: int
    unknown_share_bps: int


def evaluate_source_slo(
    *,
    freshness_ms: int | None,
    gap_count: int,
    unknown_share_bps: int,
    max_freshness_ms: int,
    max_gaps: int,
    max_unknown_share_bps: int,
) -> SourceSloVerdict:
    if freshness_ms is None:
        return SourceSloVerdict(
            False, "freshness_unknown", None, gap_count, unknown_share_bps
        )
    if freshness_ms > max_freshness_ms:
        return SourceSloVerdict(
            False, "stale", freshness_ms, gap_count, unknown_share_bps
        )
    if gap_count > max_gaps:
        return SourceSloVerdict(
            False, "gaps_exceeded", freshness_ms, gap_count, unknown_share_bps
        )
    if unknown_share_bps > max_unknown_share_bps:
        return SourceSloVerdict(
            False,
            "unknown_share_exceeded",
            freshness_ms,
            gap_count,
            unknown_share_bps,
        )
    return SourceSloVerdict(True, "ok", freshness_ms, gap_count, unknown_share_bps)
