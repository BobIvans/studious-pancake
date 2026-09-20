"""AGG-13 bounded external-dataset contracts.

The module normalizes already-observed public/authorized market data.  It does not
open sockets, load credentials, submit orders, or infer trading authorization from
market-data access.  Quota ownership remains with the repository provider-plane
authority and is represented here by a narrow reservation protocol.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Protocol

AGG13_DATASET_SCHEMA = "agg13.external-dataset.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,191}$")


class ExternalDatasetError(ValueError):
    """Fail-closed external-data validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if message is None else f"{reason_code}: {message}")


class DatasetKind(StrEnum):
    LIVE = "live"
    ARCHIVE = "archive"
    REFERENCE = "reference"
    SLOW_FACTOR = "slow_factor"


Scalar = str | int | bool | None


class QuotaReservationLike(Protocol):
    provider: str
    reservation_id: str


class QuotaAuthorityLike(Protocol):
    def reserve(
        self,
        *,
        provider: str,
        key_fingerprint: str,
        now_ms: int,
        limit: int,
        bucket_span_ms: int,
        units: int = 1,
    ) -> QuotaReservationLike: ...


@dataclass(frozen=True, slots=True)
class SourceEntitlement:
    provider: str
    product: str
    terms_sha256: str
    credential_fingerprint: str
    expires_at_ms: int | None
    storage_allowed: bool
    redistribution_allowed: bool
    trading_authorized: bool = False
    trading_scope_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.provider, "provider")
        _require_id(self.product, "product")
        _require_sha256(self.terms_sha256, "terms_sha256")
        _require_sha256(self.credential_fingerprint, "credential_fingerprint")
        if self.expires_at_ms is not None and self.expires_at_ms <= 0:
            raise ExternalDatasetError("AGG13_INVALID_ENTITLEMENT_EXPIRY")
        if self.trading_scope_sha256 is not None:
            _require_sha256(self.trading_scope_sha256, "trading_scope_sha256")
        if self.trading_authorized and self.trading_scope_sha256 is None:
            raise ExternalDatasetError("AGG13_TRADING_SCOPE_EVIDENCE_REQUIRED")

    def assert_active(self, *, now_ms: int) -> None:
        _require_nonnegative_int(now_ms, "now_ms")
        if self.expires_at_ms is not None and now_ms >= self.expires_at_ms:
            raise ExternalDatasetError("AGG13_SOURCE_ENTITLEMENT_EXPIRED")

    def assert_execution_access(self) -> None:
        if not self.trading_authorized or self.trading_scope_sha256 is None:
            raise ExternalDatasetError("AGG13_MARKET_DATA_NOT_TRADING_AUTHORIZATION")


@dataclass(frozen=True, slots=True)
class SourceLease:
    provider: str
    reservation_id: str
    reserved_units: int
    observed_at_ms: int

    def __post_init__(self) -> None:
        _require_id(self.provider, "provider")
        _require_sha256(self.reservation_id, "reservation_id")
        _require_positive_int(self.reserved_units, "reserved_units")
        _require_nonnegative_int(self.observed_at_ms, "observed_at_ms")


@dataclass(frozen=True, slots=True)
class BoundedInterval:
    start_available_at_ms: int
    end_available_at_ms: int
    max_records: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.start_available_at_ms, "start_available_at_ms")
        _require_nonnegative_int(self.end_available_at_ms, "end_available_at_ms")
        _require_positive_int(self.max_records, "max_records")
        if self.end_available_at_ms < self.start_available_at_ms:
            raise ExternalDatasetError("AGG13_INTERVAL_REVERSED")


@dataclass(frozen=True, slots=True)
class ExternalObservation:
    source: str
    product: str
    dataset_kind: DatasetKind
    instrument_id: str
    event_time_ms: int
    available_at_ms: int
    revision: int
    payload_sha256: str
    fields: Mapping[str, Scalar]
    units: Mapping[str, str]
    sequence: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.source, "source")
        _require_id(self.product, "product")
        _require_id(self.instrument_id, "instrument_id")
        _require_nonnegative_int(self.event_time_ms, "event_time_ms")
        _require_nonnegative_int(self.available_at_ms, "available_at_ms")
        _require_nonnegative_int(self.revision, "revision")
        _require_sha256(self.payload_sha256, "payload_sha256")
        if self.available_at_ms < self.event_time_ms:
            raise ExternalDatasetError("AGG13_AVAILABLE_BEFORE_EVENT_TIME")
        if self.sequence is not None:
            _require_id(self.sequence, "sequence")
        if not self.fields:
            raise ExternalDatasetError("AGG13_EMPTY_OBSERVATION_FIELDS")
        for key, value in self.fields.items():
            _require_id(key, "field_name")
            _require_scalar(value, key)
        for key, unit in self.units.items():
            _require_id(key, "unit_field")
            _require_id(unit, "unit")
        unknown_units = set(self.units).difference(self.fields)
        if unknown_units:
            raise ExternalDatasetError("AGG13_UNIT_WITHOUT_FIELD")

    @property
    def identity(self) -> str:
        return _hash_payload(
            "agg13/external-observation",
            {
                "source": self.source,
                "product": self.product,
                "dataset_kind": self.dataset_kind.value,
                "instrument_id": self.instrument_id,
                "event_time_ms": self.event_time_ms,
                "available_at_ms": self.available_at_ms,
                "revision": self.revision,
                "payload_sha256": self.payload_sha256,
                "fields": dict(self.fields),
                "units": dict(self.units),
                "sequence": self.sequence,
            },
        )


@dataclass(frozen=True, slots=True)
class NormalizedExternalDataset:
    schema_version: str
    provider: str
    product: str
    entitlement_terms_sha256: str
    lease_reservation_id: str
    record_ids: tuple[str, ...]
    dataset_kinds: tuple[DatasetKind, ...]
    first_available_at_ms: int
    last_available_at_ms: int
    manifest_sha256: str
    storage_allowed: bool
    redistribution_allowed: bool
    trading_authorized: bool


def reserve_source_budget(
    *,
    authority: QuotaAuthorityLike,
    entitlement: SourceEntitlement,
    now_ms: int,
    limit: int,
    bucket_span_ms: int,
    units: int,
) -> SourceLease:
    """Reserve source quota through the already-authoritative provider plane."""

    entitlement.assert_active(now_ms=now_ms)
    reservation = authority.reserve(
        provider=entitlement.provider,
        key_fingerprint=entitlement.credential_fingerprint,
        now_ms=now_ms,
        limit=limit,
        bucket_span_ms=bucket_span_ms,
        units=units,
    )
    if reservation.provider != entitlement.provider:
        raise ExternalDatasetError("AGG13_QUOTA_PROVIDER_MISMATCH")
    _require_sha256(reservation.reservation_id, "reservation_id")
    return SourceLease(
        provider=entitlement.provider,
        reservation_id=reservation.reservation_id,
        reserved_units=units,
        observed_at_ms=now_ms,
    )


def normalize_external_dataset(
    *,
    entitlement: SourceEntitlement,
    lease: SourceLease,
    interval: BoundedInterval,
    records: Sequence[ExternalObservation],
    now_ms: int,
) -> NormalizedExternalDataset:
    """Normalize one bounded capture without upgrading evidence or access rights."""

    entitlement.assert_active(now_ms=now_ms)
    if lease.provider != entitlement.provider:
        raise ExternalDatasetError("AGG13_SOURCE_LEASE_PROVIDER_MISMATCH")
    if len(records) > interval.max_records:
        raise ExternalDatasetError("AGG13_DATASET_RECORD_LIMIT_EXCEEDED")
    if not records:
        raise ExternalDatasetError("AGG13_EMPTY_DATASET")

    seen: set[str] = set()
    kinds: set[DatasetKind] = set()
    for record in records:
        if record.source != entitlement.provider or record.product != entitlement.product:
            raise ExternalDatasetError("AGG13_RECORD_SOURCE_PRODUCT_MISMATCH")
        if not (
            interval.start_available_at_ms
            <= record.available_at_ms
            <= interval.end_available_at_ms
        ):
            raise ExternalDatasetError("AGG13_RECORD_OUTSIDE_BOUNDED_INTERVAL")
        record_id = record.identity
        if record_id in seen:
            raise ExternalDatasetError("AGG13_DUPLICATE_OBSERVATION")
        seen.add(record_id)
        kinds.add(record.dataset_kind)

    ordered = sorted(records, key=lambda item: (item.available_at_ms, item.identity))
    ordered_ids = tuple(item.identity for item in ordered)
    ordered_kinds = tuple(sorted(kinds, key=lambda item: item.value))
    manifest_payload = {
        "schema_version": AGG13_DATASET_SCHEMA,
        "provider": entitlement.provider,
        "product": entitlement.product,
        "terms_sha256": entitlement.terms_sha256,
        "lease_reservation_id": lease.reservation_id,
        "record_ids": ordered_ids,
        "dataset_kinds": [item.value for item in ordered_kinds],
        "first_available_at_ms": ordered[0].available_at_ms,
        "last_available_at_ms": ordered[-1].available_at_ms,
        "storage_allowed": entitlement.storage_allowed,
        "redistribution_allowed": entitlement.redistribution_allowed,
        "trading_authorized": entitlement.trading_authorized,
    }
    return NormalizedExternalDataset(
        schema_version=AGG13_DATASET_SCHEMA,
        provider=entitlement.provider,
        product=entitlement.product,
        entitlement_terms_sha256=entitlement.terms_sha256,
        lease_reservation_id=lease.reservation_id,
        record_ids=ordered_ids,
        dataset_kinds=ordered_kinds,
        first_available_at_ms=ordered[0].available_at_ms,
        last_available_at_ms=ordered[-1].available_at_ms,
        manifest_sha256=_hash_payload("agg13/external-dataset", manifest_payload),
        storage_allowed=entitlement.storage_allowed,
        redistribution_allowed=entitlement.redistribution_allowed,
        trading_authorized=entitlement.trading_authorized,
    )


def _hash_payload(domain: str, payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(
        domain.encode("utf-8") + b"\0" + raw.encode("utf-8")
    ).hexdigest()


def _require_scalar(value: Scalar, field: str) -> None:
    if isinstance(value, float):
        raise ExternalDatasetError("AGG13_FLOAT_NUMERIC_FIELD_FORBIDDEN", field)
    if not isinstance(value, (str, int, bool, type(None))):
        raise ExternalDatasetError("AGG13_NONSCALAR_FIELD_FORBIDDEN", field)
    if isinstance(value, str) and not value:
        raise ExternalDatasetError("AGG13_EMPTY_STRING_FIELD", field)


def _require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ExternalDatasetError("AGG13_INVALID_IDENTIFIER", field)


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExternalDatasetError("AGG13_INVALID_SHA256", field)


def _require_positive_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExternalDatasetError("AGG13_POSITIVE_INTEGER_REQUIRED", field)


def _require_nonnegative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExternalDatasetError("AGG13_NONNEGATIVE_INTEGER_REQUIRED", field)
