"""AGG-13 external-market adapters over the accepted AGG-02 data plane.

AGG-02 owns causal envelopes, source entitlements, shared quota authority, raw
journaling and point-in-time state.  This module only adds the external-market
semantics required by DATA-05.  It never opens sockets, loads credentials, places
orders, or upgrades market-data access into trading authorization.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import re

from src.agg02 import (
    BudgetDimension,
    RawEventEnvelope,
    SourceBudgetAuthority,
    SourceBudgetReservation,
    SourceRegistryEntry,
    StateRecord,
    canonical_hash,
)

AGG13_DATASET_SCHEMA = "agg13.external-dataset.v2"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,191}$")


class ExternalDatasetError(ValueError):
    """Fail-closed AGG-13 adapter validation with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if message is None else f"{reason_code}: {message}")


class DatasetKind(StrEnum):
    LIVE = "live"
    ARCHIVE = "archive"
    REFERENCE = "reference"
    SLOW_FACTOR = "slow_factor"


Scalar = str | int | bool | None


@dataclass(frozen=True, slots=True)
class ExternalUsePolicy:
    """DATA-05 rights that complement, rather than replace, AGG-02 entitlements."""

    product: str
    terms_sha256: str
    redistribution_allowed: bool
    trading_authorized: bool = False
    trading_scope_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.product, "product")
        _require_sha256(self.terms_sha256, "terms_sha256")
        if self.trading_scope_sha256 is not None:
            _require_sha256(self.trading_scope_sha256, "trading_scope_sha256")
        if self.trading_authorized and self.trading_scope_sha256 is None:
            raise ExternalDatasetError("AGG13_TRADING_SCOPE_EVIDENCE_REQUIRED")

    def assert_execution_access(self) -> None:
        if not self.trading_authorized or self.trading_scope_sha256 is None:
            raise ExternalDatasetError("AGG13_MARKET_DATA_NOT_TRADING_AUTHORIZATION")


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
class ExternalMarketRecord:
    """Normalized external-market observation before AGG-02 materialization."""

    source_id: str
    product: str
    dataset_kind: DatasetKind
    market_scope: str
    instrument_id: str
    event_time_ms: int
    received_at_ms: int
    available_at_ms: int
    decoder_version: str
    cursor_partition: str
    cursor_offset: int
    reconnect_epoch: int
    revision: int
    payload_sha256: str
    fields: Mapping[str, Scalar]
    units: Mapping[str, str]
    source_sequence: int | None = None
    uncertainty_ms: int = 0
    gap_before: bool = False

    def __post_init__(self) -> None:
        _require_id(self.source_id, "source_id")
        _require_id(self.product, "product")
        _require_id(self.market_scope, "market_scope")
        _require_id(self.instrument_id, "instrument_id")
        _require_id(self.decoder_version, "decoder_version")
        _require_id(self.cursor_partition, "cursor_partition")
        _require_nonnegative_int(self.event_time_ms, "event_time_ms")
        _require_nonnegative_int(self.received_at_ms, "received_at_ms")
        _require_nonnegative_int(self.available_at_ms, "available_at_ms")
        _require_nonnegative_int(self.cursor_offset, "cursor_offset")
        _require_nonnegative_int(self.reconnect_epoch, "reconnect_epoch")
        _require_nonnegative_int(self.revision, "revision")
        _require_nonnegative_int(self.uncertainty_ms, "uncertainty_ms")
        if self.available_at_ms < self.received_at_ms:
            raise ExternalDatasetError("AGG13_AVAILABLE_BEFORE_RECEIVE")
        if self.source_sequence is not None:
            _require_nonnegative_int(self.source_sequence, "source_sequence")
        _require_sha256(self.payload_sha256, "payload_sha256")
        if not isinstance(self.gap_before, bool):
            raise ExternalDatasetError("AGG13_INVALID_GAP_FLAG")
        if not self.fields:
            raise ExternalDatasetError("AGG13_EMPTY_OBSERVATION_FIELDS")
        for field_name, field_value in self.fields.items():
            _require_id(field_name, "field_name")
            _require_scalar(field_value, field_name)
        for key, unit in self.units.items():
            _require_id(key, "unit_field")
            _require_id(unit, "unit")
        if set(self.units).difference(self.fields):
            raise ExternalDatasetError("AGG13_UNIT_WITHOUT_FIELD")

    @property
    def identity(self) -> str:
        return canonical_hash(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": AGG13_DATASET_SCHEMA,
            "source_id": self.source_id,
            "product": self.product,
            "dataset_kind": self.dataset_kind.value,
            "market_scope": self.market_scope,
            "instrument_id": self.instrument_id,
            "event_time_ms": self.event_time_ms,
            "received_at_ms": self.received_at_ms,
            "available_at_ms": self.available_at_ms,
            "decoder_version": self.decoder_version,
            "cursor_partition": self.cursor_partition,
            "cursor_offset": self.cursor_offset,
            "reconnect_epoch": self.reconnect_epoch,
            "revision": self.revision,
            "payload_sha256": self.payload_sha256,
            "fields": dict(self.fields),
            "units": dict(self.units),
            "source_sequence": self.source_sequence,
            "uncertainty_ms": self.uncertainty_ms,
            "gap_before": self.gap_before,
        }

    def to_raw_envelope(self) -> RawEventEnvelope:
        """Bind the record to the canonical AGG-02 causal envelope."""

        return RawEventEnvelope(
            event_id=self.identity,
            source_id=self.source_id,
            chain_id=self.market_scope,
            payload_sha256=self.payload_sha256,
            received_at_ms=self.received_at_ms,
            available_at_ms=self.available_at_ms,
            decoder_version=self.decoder_version,
            cursor_source=self.source_id,
            cursor_partition=self.cursor_partition,
            cursor_offset=self.cursor_offset,
            reconnect_epoch=self.reconnect_epoch,
            slot=None,
            commitment=f"external-{self.dataset_kind.value}",
            source_event_time_ms=self.event_time_ms,
            source_sequence=self.source_sequence,
            uncertainty_ms=self.uncertainty_ms,
            gap_before=self.gap_before,
        )

    def to_state_record(self) -> StateRecord:
        """Project external data into the accepted AGG-02 as-of state contract."""

        payload = {
            "schema_version": AGG13_DATASET_SCHEMA,
            "record_id": self.identity,
            "dataset_kind": self.dataset_kind.value,
            "market_scope": self.market_scope,
            "instrument_id": self.instrument_id,
            "event_time_ms": self.event_time_ms,
            "revision": self.revision,
            "fields": dict(self.fields),
            "units": dict(self.units),
        }
        return StateRecord.from_mapping(
            dependency_id=(
                f"external:{self.source_id}:{self.product}:{self.instrument_id}"
            ),
            generation=f"{self.decoder_version}:revision-{self.revision}",
            available_at_ms=self.available_at_ms,
            payload=payload,
            slot=None,
            quarantined=False,
            gap_affected=self.gap_before,
        )


@dataclass(frozen=True, slots=True)
class NormalizedExternalDataset:
    schema_version: str
    source_id: str
    product: str
    terms_sha256: str
    source_budget_reservation_hash: str
    record_ids: tuple[str, ...]
    dataset_kinds: tuple[DatasetKind, ...]
    first_available_at_ms: int
    last_available_at_ms: int
    state_records: tuple[StateRecord, ...]
    manifest_sha256: str
    redistribution_allowed: bool
    trading_authorized: bool


def reserve_external_budget(
    *,
    authority: SourceBudgetAuthority,
    source: SourceRegistryEntry,
    key_fingerprint: str,
    now_ms: int,
    dimensions: Sequence[BudgetDimension],
) -> SourceBudgetReservation:
    """Delegate DATA-05 quota consumption to the accepted AGG-02 authority."""

    return authority.reserve(
        source=source,
        key_fingerprint=key_fingerprint,
        now_ms=now_ms,
        dimensions=dimensions,
    )


def normalize_external_dataset(
    *,
    source: SourceRegistryEntry,
    policy: ExternalUsePolicy,
    reservation: SourceBudgetReservation,
    interval: BoundedInterval,
    records: Sequence[ExternalMarketRecord],
    now_ms: int,
) -> NormalizedExternalDataset:
    """Build an AGG-02-backed DATA-05 dataset without inventing access or freshness."""

    source.assert_usable(now_ms=now_ms)
    if not source.storage_allowed:
        raise ExternalDatasetError("AGG13_SOURCE_STORAGE_NOT_ALLOWED")
    if reservation.source_id != source.source_id:
        raise ExternalDatasetError("AGG13_SOURCE_BUDGET_MISMATCH")
    if len(records) > interval.max_records:
        raise ExternalDatasetError("AGG13_DATASET_RECORD_LIMIT_EXCEEDED")
    if not records:
        raise ExternalDatasetError("AGG13_EMPTY_DATASET")

    seen: set[str] = set()
    ordered: list[ExternalMarketRecord] = []
    for record in records:
        if record.source_id != source.source_id or record.product != policy.product:
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
        ordered.append(record)

    ordered.sort(key=lambda item: (item.available_at_ms, item.identity))
    state_records = tuple(item.to_state_record() for item in ordered)
    kinds = tuple(sorted({item.dataset_kind for item in ordered}, key=lambda x: x.value))
    record_ids = tuple(item.identity for item in ordered)
    manifest_payload = {
        "schema_version": AGG13_DATASET_SCHEMA,
        "source_id": source.source_id,
        "product": policy.product,
        "terms_sha256": policy.terms_sha256,
        "source_budget_reservation_hash": reservation.reservation_hash,
        "record_ids": record_ids,
        "dataset_kinds": [item.value for item in kinds],
        "first_available_at_ms": ordered[0].available_at_ms,
        "last_available_at_ms": ordered[-1].available_at_ms,
        "state_record_hashes": [item.value_sha256 for item in state_records],
        "redistribution_allowed": policy.redistribution_allowed,
        "trading_authorized": policy.trading_authorized,
    }
    return NormalizedExternalDataset(
        schema_version=AGG13_DATASET_SCHEMA,
        source_id=source.source_id,
        product=policy.product,
        terms_sha256=policy.terms_sha256,
        source_budget_reservation_hash=reservation.reservation_hash,
        record_ids=record_ids,
        dataset_kinds=kinds,
        first_available_at_ms=ordered[0].available_at_ms,
        last_available_at_ms=ordered[-1].available_at_ms,
        state_records=state_records,
        manifest_sha256=canonical_hash(manifest_payload),
        redistribution_allowed=policy.redistribution_allowed,
        trading_authorized=policy.trading_authorized,
    )


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
