import hashlib

import pytest

from src.data_plane.external_datasets import (
    BoundedInterval,
    DatasetKind,
    ExternalDatasetError,
    ExternalObservation,
    SourceEntitlement,
    normalize_external_dataset,
    reserve_source_budget,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Reservation:
    def __init__(self, provider: str, reservation_id: str) -> None:
        self.provider = provider
        self.reservation_id = reservation_id


class _Quota:
    def reserve(self, **kwargs):
        return _Reservation(kwargs["provider"], _h("reservation"))


def _entitlement(*, trading: bool = False, expires_at_ms: int | None = 10_000):
    return SourceEntitlement(
        provider="derivatives-feed",
        product="public-perp-data",
        terms_sha256=_h("terms"),
        credential_fingerprint=_h("credential"),
        expires_at_ms=expires_at_ms,
        storage_allowed=True,
        redistribution_allowed=False,
        trading_authorized=trading,
        trading_scope_sha256=_h("trade-scope") if trading else None,
    )


def _record(kind: DatasetKind, available_at: int, revision: int = 0):
    return ExternalObservation(
        source="derivatives-feed",
        product="public-perp-data",
        dataset_kind=kind,
        instrument_id="BTC-PERP",
        event_time_ms=available_at - 5,
        available_at_ms=available_at,
        revision=revision,
        payload_sha256=_h(f"payload:{kind}:{available_at}:{revision}"),
        fields={"price_ticks": 123_456, "funding_bps_x1e4": -25},
        units={"price_ticks": "quote-ticks", "funding_bps_x1e4": "bps-x1e4"},
        sequence=str(available_at),
    )


def test_agg13_data_live_and_archive_are_explicit_and_manifested() -> None:
    entitlement = _entitlement()
    lease = reserve_source_budget(
        authority=_Quota(),
        entitlement=entitlement,
        now_ms=100,
        limit=100,
        bucket_span_ms=1_000,
        units=2,
    )
    dataset = normalize_external_dataset(
        entitlement=entitlement,
        lease=lease,
        interval=BoundedInterval(100, 300, 10),
        records=(_record(DatasetKind.LIVE, 200), _record(DatasetKind.ARCHIVE, 150)),
        now_ms=250,
    )
    assert dataset.dataset_kinds == (DatasetKind.ARCHIVE, DatasetKind.LIVE)
    assert dataset.first_available_at_ms == 150
    assert dataset.last_available_at_ms == 200
    assert dataset.trading_authorized is False
    assert len(dataset.manifest_sha256) == 64


def test_agg13_public_data_does_not_grant_order_authority() -> None:
    with pytest.raises(
        ExternalDatasetError, match="AGG13_MARKET_DATA_NOT_TRADING_AUTHORIZATION"
    ):
        _entitlement().assert_execution_access()
    _entitlement(trading=True).assert_execution_access()


def test_agg13_trial_expiry_and_float_fields_fail_closed() -> None:
    expired = _entitlement(expires_at_ms=100)
    with pytest.raises(ExternalDatasetError, match="AGG13_SOURCE_ENTITLEMENT_EXPIRED"):
        reserve_source_budget(
            authority=_Quota(),
            entitlement=expired,
            now_ms=100,
            limit=10,
            bucket_span_ms=1_000,
            units=1,
        )
    with pytest.raises(
        ExternalDatasetError, match="AGG13_FLOAT_NUMERIC_FIELD_FORBIDDEN"
    ):
        ExternalObservation(
            source="derivatives-feed",
            product="public-perp-data",
            dataset_kind=DatasetKind.LIVE,
            instrument_id="BTC-PERP",
            event_time_ms=10,
            available_at_ms=11,
            revision=0,
            payload_sha256=_h("float"),
            fields={"price": 1.2},
            units={"price": "USD"},
        )
