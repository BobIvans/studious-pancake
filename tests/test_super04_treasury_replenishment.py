from __future__ import annotations

import pytest

from src.durability import DurableLifecycleStore
from src.economics.treasury_replenishment import (
    ReconciliationStatus,
    ReplenishmentDisposition,
    ReplenishmentPolicy,
    ReplenishmentQuoteEvidence,
    SourceReservationEvidence,
    TreasuryBalanceEvidence,
    TreasuryReplenishmentError,
    bind_replenishment_quote,
    plan_fee_reserve_replenishment,
    reconcile_replenishment_operation,
    reserve_replenishment_operation,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def _evidence(**overrides: object) -> TreasuryBalanceEvidence:
    values: dict[str, object] = {
        "wallet_pubkey": "wallet-1",
        "native_lamports": 10_000_000,
        "source_asset_id": "spl:USDC:6",
        "source_balance_base_units": 5_000_000,
        "source_reserved_base_units": 1_000_000,
        "observed_slot": 100,
        "observed_at_ns": 1_000,
        "evidence_hash": H1,
    }
    values.update(overrides)
    return TreasuryBalanceEvidence(**values)  # type: ignore[arg-type]


def _policy(**overrides: object) -> ReplenishmentPolicy:
    values: dict[str, object] = {
        "policy_hash": H2,
        "protected_native_reserve_lamports": 5_000_000,
        "target_native_lamports": 20_000_000,
        "minimum_bootstrap_fee_lamports": 1_000_000,
        "maximum_source_spend_base_units": 2_000_000,
        "maximum_balance_age_ns": 100,
        "allowed_source_asset_ids": ("spl:USDC:6",),
    }
    values.update(overrides)
    return ReplenishmentPolicy(**values)  # type: ignore[arg-type]


def _bound():
    decision = plan_fee_reserve_replenishment(
        evidence=_evidence(), policy=_policy(), trusted_now_ns=1_050
    )
    assert decision.disposition is ReplenishmentDisposition.INTENT
    assert decision.intent is not None
    quote = ReplenishmentQuoteEvidence(
        quote_id="quote-1",
        source_asset_id="spl:USDC:6",
        source_input_base_units=1_500_000,
        minimum_native_output_lamports=12_000_000,
        estimated_network_fee_lamports=1_000_000,
        estimated_rent_loss_lamports=0,
        state_frame_hash=H1,
        route_hash=H3,
        expires_at_ns=2_000,
    )
    return bind_replenishment_quote(
        intent=decision.intent,
        quote=quote,
        current_native_lamports=10_000_000,
        target_native_lamports=20_000_000,
        trusted_now_ns=1_050,
    )


def test_nf329_no_bootstrap_and_stale_balance_fail_closed() -> None:
    stale = plan_fee_reserve_replenishment(
        evidence=_evidence(), policy=_policy(), trusted_now_ns=1_101
    )
    assert stale.disposition is ReplenishmentDisposition.BLOCKED
    assert stale.reason_code == "STALE_BALANCE"

    bootstrap = plan_fee_reserve_replenishment(
        evidence=_evidence(native_lamports=5_500_000),
        policy=_policy(minimum_bootstrap_fee_lamports=1_000_000),
        trusted_now_ns=1_050,
    )
    assert bootstrap.disposition is ReplenishmentDisposition.BLOCKED
    assert bootstrap.reason_code == "NO_BOOTSTRAP_FEE"


def test_nf329_uses_free_source_not_legacy_half_balance_rule() -> None:
    decision = plan_fee_reserve_replenishment(
        evidence=_evidence(
            source_balance_base_units=5_000_000,
            source_reserved_base_units=4_000_000,
        ),
        policy=_policy(maximum_source_spend_base_units=3_000_000),
        trusted_now_ns=1_050,
    )
    assert decision.intent is not None
    assert decision.intent.maximum_source_input_base_units == 1_000_000


def test_nf330_quote_must_improve_native_reserve() -> None:
    decision = plan_fee_reserve_replenishment(
        evidence=_evidence(), policy=_policy(), trusted_now_ns=1_050
    )
    assert decision.intent is not None
    weak = ReplenishmentQuoteEvidence(
        quote_id="weak",
        source_asset_id="spl:USDC:6",
        source_input_base_units=1_000_000,
        minimum_native_output_lamports=1_000_000,
        estimated_network_fee_lamports=900_000,
        estimated_rent_loss_lamports=0,
        state_frame_hash=H1,
        route_hash=H3,
        expires_at_ns=2_000,
    )
    with pytest.raises(
        TreasuryReplenishmentError,
        match="NET_RESERVE_NOT_IMPROVED",
    ):
        bind_replenishment_quote(
            intent=decision.intent,
            quote=weak,
            current_native_lamports=10_000_000,
            target_native_lamports=20_000_000,
            trusted_now_ns=1_050,
        )


def test_nf331_reuses_canonical_lifecycle_store_and_is_idempotent(
    tmp_path,
) -> None:
    bound = _bound()
    source = SourceReservationEvidence(
        reservation_hash=H3,
        asset_id="spl:USDC:6",
        reserved_base_units=1_500_000,
        generation=1,
        expires_at_ns=2_000,
    )
    with DurableLifecycleStore(
        tmp_path / "lifecycle.db",
        clock_ns=lambda: 1_100,
    ) as store:
        first = reserve_replenishment_operation(
            bound=bound,
            source_reservation=source,
            store=store,
            generation=1,
            trusted_now_ns=1_100,
        )
        second = reserve_replenishment_operation(
            bound=bound,
            source_reservation=source,
            store=store,
            generation=1,
            trusted_now_ns=1_100,
        )
        assert first.attempt.attempt_id == second.attempt.attempt_id
        assert first.attempt.reserved_lamports == 1_000_000
        assert store.count_rows("durable_attempts") == 1
        assert store.count_rows("durable_reservations") == 1


def test_nf332_unknown_never_releases_or_fabricates_pnl() -> None:
    bound = _bound()
    unknown = reconcile_replenishment_operation(
        bound=bound,
        status=ReconciliationStatus.UNKNOWN,
        evidence_hash=H3,
    )
    assert unknown.release_reservation is False
    assert unknown.strategy_pnl_lamports == 0
    assert unknown.native_received_lamports is None

    finalized = reconcile_replenishment_operation(
        bound=bound,
        status=ReconciliationStatus.FINALIZED,
        evidence_hash=H3,
        source_spent_base_units=1_500_000,
        native_received_lamports=12_000_000,
        actual_network_fee_lamports=1_000_000,
        actual_rent_loss_lamports=0,
        native_reserve_after_lamports=21_000_000,
    )
    assert finalized.release_reservation is True
    assert finalized.strategy_pnl_lamports == 0
