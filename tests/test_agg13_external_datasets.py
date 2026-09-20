import hashlib

import pytest

from src.agg02 import (
    Agg02Error,
    BudgetDimension,
    SourceAccess,
    SourceBudgetAuthority,
    SourceRegistryEntry,
    StateRecord,
)
from src.data_plane.bounded_provider_plane_pr197 import SQLiteQuotaAuthority
from src.data_plane.external_datasets import (
    BoundedInterval,
    DatasetKind,
    ExternalDatasetError,
    ExternalMarketRecord,
    ExternalUsePolicy,
    normalize_external_dataset,
    reserve_external_budget,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source(*, expires_at_ms: int | None = 10_000, storage_allowed: bool = True):
    return SourceRegistryEntry(
        source_id="derivatives-feed",
        role="external-derivatives",
        metering_unit="request",
        credential_scope="market-read",
        storage_allowed=storage_allowed,
        access=SourceAccess.ACTIVE,
        entitlement_expires_at_ms=expires_at_ms,
        correlation_group="external-feed",
    )


def _policy(*, trading: bool = False) -> ExternalUsePolicy:
    return ExternalUsePolicy(
        product="public-perp-data",
        terms_sha256=_h("terms"),
        redistribution_allowed=False,
        trading_authorized=trading,
        trading_scope_sha256=_h("trade-scope") if trading else None,
    )


def _record(kind: DatasetKind, available_at: int, revision: int = 0):
    return ExternalMarketRecord(
        source_id="derivatives-feed",
        product="public-perp-data",
        dataset_kind=kind,
        market_scope="offchain-derivatives",
        instrument_id="BTC-PERP",
        event_time_ms=available_at - 10,
        received_at_ms=available_at - 5,
        available_at_ms=available_at,
        decoder_version="perp-v1",
        cursor_partition="btc-perp",
        cursor_offset=available_at,
        reconnect_epoch=0,
        revision=revision,
        payload_sha256=_h(f"payload:{kind}:{available_at}:{revision}"),
        fields={"price_ticks": 123_456, "funding_bps_x1e4": -25},
        units={"price_ticks": "quote-ticks", "funding_bps_x1e4": "bps-x1e4"},
        source_sequence=available_at,
    )


def test_agg13_data_reuses_agg02_quota_and_causal_contracts(tmp_path) -> None:
    quota = SQLiteQuotaAuthority(tmp_path / "quota.sqlite3")
    try:
        authority = SourceBudgetAuthority(quota)
        reservation = reserve_external_budget(
            authority=authority,
            source=_source(),
            key_fingerprint=_h("credential"),
            now_ms=100,
            dimensions=(BudgetDimension("http", 100, 1_000, 2),),
        )
        live = _record(DatasetKind.LIVE, 200)
        archive = _record(DatasetKind.ARCHIVE, 150)
        dataset = normalize_external_dataset(
            source=_source(),
            policy=_policy(),
            reservation=reservation,
            interval=BoundedInterval(100, 300, 10),
            records=(live, archive),
            now_ms=250,
        )
        assert dataset.dataset_kinds == (DatasetKind.ARCHIVE, DatasetKind.LIVE)
        assert dataset.first_available_at_ms == 150
        assert dataset.last_available_at_ms == 200
        assert dataset.trading_authorized is False
        assert len(dataset.manifest_sha256) == 64
        assert all(isinstance(item, StateRecord) for item in dataset.state_records)
        envelope = live.to_raw_envelope()
        assert envelope.source_id == "derivatives-feed"
        assert envelope.available_at_ms == 200
        assert envelope.source_event_time_ms == 190
        assert envelope.cursor_source == "derivatives-feed"
    finally:
        quota.close()


def test_agg13_public_data_does_not_grant_order_authority() -> None:
    with pytest.raises(
        ExternalDatasetError, match="AGG13_MARKET_DATA_NOT_TRADING_AUTHORIZATION"
    ):
        _policy().assert_execution_access()
    _policy(trading=True).assert_execution_access()


def test_agg13_uses_agg02_expiry_and_storage_gates(tmp_path) -> None:
    quota = SQLiteQuotaAuthority(tmp_path / "quota.sqlite3")
    try:
        authority = SourceBudgetAuthority(quota)
        with pytest.raises(Agg02Error, match="AGG02_SOURCE_ENTITLEMENT_EXPIRED"):
            reserve_external_budget(
                authority=authority,
                source=_source(expires_at_ms=100),
                key_fingerprint=_h("credential"),
                now_ms=100,
                dimensions=(BudgetDimension("http", 10, 1_000),),
            )
        reservation = reserve_external_budget(
            authority=authority,
            source=_source(),
            key_fingerprint=_h("credential"),
            now_ms=101,
            dimensions=(BudgetDimension("http", 10, 1_000),),
        )
        with pytest.raises(
            ExternalDatasetError, match="AGG13_SOURCE_STORAGE_NOT_ALLOWED"
        ):
            normalize_external_dataset(
                source=_source(storage_allowed=False),
                policy=_policy(),
                reservation=reservation,
                interval=BoundedInterval(100, 300, 10),
                records=(_record(DatasetKind.LIVE, 200),),
                now_ms=250,
            )
    finally:
        quota.close()


def test_agg13_float_fields_fail_closed() -> None:
    with pytest.raises(
        ExternalDatasetError, match="AGG13_FLOAT_NUMERIC_FIELD_FORBIDDEN"
    ):
        ExternalMarketRecord(
            source_id="derivatives-feed",
            product="public-perp-data",
            dataset_kind=DatasetKind.LIVE,
            market_scope="offchain-derivatives",
            instrument_id="BTC-PERP",
            event_time_ms=10,
            received_at_ms=11,
            available_at_ms=12,
            decoder_version="perp-v1",
            cursor_partition="btc-perp",
            cursor_offset=1,
            reconnect_epoch=0,
            revision=0,
            payload_sha256=_h("float"),
            fields={"price": 1.2},
            units={"price": "USD"},
        )
