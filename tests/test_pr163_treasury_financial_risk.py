from __future__ import annotations

import pytest

from src.treasury.financial_risk import (
    AccountingStage,
    AssetAmount,
    AssetIdentity,
    BalanceSource,
    DailyTreasuryReport,
    DurableRiskState,
    FundingSweepRequest,
    LedgerEntryKind,
    RiskLedgerEntry,
    RiskWindow,
    RpcEndpointEvidence,
    SolvencyInputs,
    TreasuryAccountingError,
    TreasuryAuthorization,
    WalletClassification,
    WalletObservationPackage,
    WalletRegistryEntry,
    compute_solvency_report,
    reject_caller_supplied_wallet_balance,
)


def _sol_asset() -> AssetIdentity:
    return AssetIdentity(
        cluster_genesis="mainnet-beta-genesis",
        symbol="SOL",
        mint="native",
        token_program="system",
        decimals=9,
    )


def _amount(units: int) -> AssetAmount:
    return AssetAmount(_sol_asset(), units)


def _registry() -> WalletRegistryEntry:
    return WalletRegistryEntry(
        cluster_genesis="mainnet-beta-genesis",
        wallet_pubkey="Treasury111111111111111111111111111111111",
        purpose="limited-live-canary",
        signer_backend="isolated-signer",
        owner_custodian="treasury-admin",
        classification=WalletClassification.HOT,
        approved_programs=("jupiter-v6", "system"),
        approved_token_accounts=(),
        protected_reserve=_amount(2_000_000),
        maximum_exposure=_amount(10_000_000),
        funding_policy_id="funding-policy-v1",
        sweep_policy_id="sweep-policy-v1",
    )


def _endpoint(endpoint_id: str, identity: str) -> RpcEndpointEvidence:
    return RpcEndpointEvidence(
        endpoint_id=endpoint_id,
        endpoint_identity_hash=identity,
        commitment="finalized",
        context_slot=100,
        root_slot=105,
        response_hash=f"response-{endpoint_id}",
    )


def _observation(balance: int = 20_000_000) -> WalletObservationPackage:
    return WalletObservationPackage(
        registry_entry=_registry(),
        native_balance=_amount(balance),
        token_accounts=(),
        endpoint_evidence=(
            _endpoint("rpc-a", "identity-a"),
            _endpoint("rpc-b", "identity-b"),
        ),
        observed_at_ns=10_000,
        policy_hash="policy-hash",
    )


def test_pr163_rejects_caller_supplied_wallet_balance() -> None:
    with pytest.raises(TreasuryAccountingError, match="caller-supplied"):
        reject_caller_supplied_wallet_balance({"native_lamports": 20_000_000})

    with pytest.raises(TreasuryAccountingError, match="caller-supplied"):
        WalletObservationPackage(
            registry_entry=_registry(),
            native_balance=_amount(20_000_000),
            token_accounts=(),
            endpoint_evidence=(
                _endpoint("rpc-a", "identity-a"),
                _endpoint("rpc-b", "identity-b"),
            ),
            observed_at_ns=10_000,
            policy_hash="policy-hash",
            source=BalanceSource.CALLER_SUPPLIED,
        )


def test_pr163_wallet_observation_requires_independent_quorum() -> None:
    with pytest.raises(TreasuryAccountingError, match="RPC quorum"):
        WalletObservationPackage(
            registry_entry=_registry(),
            native_balance=_amount(20_000_000),
            token_accounts=(),
            endpoint_evidence=(_endpoint("rpc-a", "identity-a"),),
            observed_at_ns=10_000,
            policy_hash="policy-hash",
        )

    with pytest.raises(TreasuryAccountingError, match="correlated"):
        WalletObservationPackage(
            registry_entry=_registry(),
            native_balance=_amount(20_000_000),
            token_accounts=(),
            endpoint_evidence=(
                _endpoint("rpc-a", "shared-identity"),
                _endpoint("rpc-b", "shared-identity"),
            ),
            observed_at_ns=10_000,
            policy_hash="policy-hash",
        )


def test_pr163_solvency_subtracts_all_protected_reserves_and_holds() -> None:
    observation = _observation(balance=20_000_000)
    inputs = SolvencyInputs(
        finalized_wallet_assets=_amount(20_000_000),
        protected_treasury_reserve=_amount(2_000_000),
        active_capital_reservations=_amount(3_000_000),
        pending_submission_max_debit=_amount(4_000_000),
        unresolved_ambiguous_attempt_reserve=_amount(4_000_000),
        rent_liabilities=_amount(500_000),
        estimated_failure_charges=_amount(300_000),
        provider_network_fee_buffer=_amount(200_000),
        withdrawal_sweep_holds=_amount(1_000_000),
    )

    report = compute_solvency_report(observation, inputs)

    assert report.available_base_units == 9_000_000
    assert report.deficit_base_units == 0
    assert report.admission_allowed is True
    assert report.observation_hash == observation.observation_hash


def test_pr163_solvency_fail_closes_when_reserve_exceeds_balance() -> None:
    observation = _observation(balance=3_000_000)
    inputs = SolvencyInputs(
        finalized_wallet_assets=_amount(3_000_000),
        protected_treasury_reserve=_amount(2_000_000),
        active_capital_reservations=_amount(1_000_000),
        pending_submission_max_debit=_amount(2_000_000),
        unresolved_ambiguous_attempt_reserve=_amount(2_000_000),
        rent_liabilities=_amount(100_000),
        estimated_failure_charges=_amount(100_000),
        provider_network_fee_buffer=_amount(100_000),
        withdrawal_sweep_holds=_amount(100_000),
    )

    report = compute_solvency_report(observation, inputs)

    assert report.available_base_units == 0
    assert report.deficit_base_units == 2_400_000
    assert report.admission_allowed is False


def test_pr163_multi_asset_mixing_is_rejected() -> None:
    usdc = AssetIdentity(
        cluster_genesis="mainnet-beta-genesis",
        symbol="USDC",
        mint="usdc-mint",
        token_program="token",
        decimals=6,
    )

    with pytest.raises(TreasuryAccountingError, match="different assets"):
        _amount(1) + AssetAmount(usdc, 1)

    with pytest.raises(TreasuryAccountingError, match="different assets"):
        SolvencyInputs(
            finalized_wallet_assets=_amount(10),
            protected_treasury_reserve=AssetAmount(usdc, 1),
            active_capital_reservations=_amount(0),
            pending_submission_max_debit=_amount(0),
            unresolved_ambiguous_attempt_reserve=_amount(0),
            rent_liabilities=_amount(0),
            estimated_failure_charges=_amount(0),
            provider_network_fee_buffer=_amount(0),
            withdrawal_sweep_holds=_amount(0),
        )


def test_pr163_utc_day_and_rolling_24h_windows_are_distinct() -> None:
    day = RiskWindow.utc_day("2026-07-22")
    rolling = RiskWindow.rolling_24h(end_ns=day.end_ns)

    assert day.kind.value == "utc_day"
    assert rolling.kind.value == "rolling_24h"
    assert day.key != rolling.key
    assert day.start_ns == rolling.start_ns
    assert day.end_ns == rolling.end_ns


def test_pr163_durable_risk_state_survives_restart_snapshot_round_trip() -> None:
    window = RiskWindow.utc_day("2026-07-22")
    entries = (
        RiskLedgerEntry(
            entry_id="pnl-1",
            asset=_sol_asset(),
            kind=LedgerEntryKind.REALIZED_PNL,
            stage=AccountingStage.FINALIZED,
            amount_delta_base_units=-700_000,
            observed_at_ns=window.start_ns + 1,
            window_keys=(window.key,),
            attempt_id="attempt-1",
            finalized_slot=123,
        ),
        RiskLedgerEntry(
            entry_id="fail-1",
            asset=_sol_asset(),
            kind=LedgerEntryKind.FAILED_ATTEMPT_CHARGE,
            stage=AccountingStage.RECONCILED,
            amount_delta_base_units=-25_000,
            observed_at_ns=window.start_ns + 2,
            window_keys=(window.key,),
            attempt_id="attempt-1",
            finalized_slot=124,
        ),
    )

    state = DurableRiskState.from_entries(
        entries=entries,
        windows=(window,),
        asset=_sol_asset(),
    )
    payload = state.to_json()

    assert payload["schema"] == "pr163.treasury-wallet-solvency.v1"
    assert payload["snapshots"][0]["realized_pnl_base_units"] == "-700000"
    assert payload["snapshots"][0]["failed_attempt_charges_base_units"] == "-25000"
    assert payload["snapshots"][0]["consecutive_failures"] == 1
    assert len(payload["ledger_hash"]) == 64


def test_pr163_unresolved_attempt_reserve_must_cover_max_possible_debit() -> None:
    with pytest.raises(
        TreasuryAccountingError,
        match="unresolved attempt reserve",
    ):
        SolvencyInputs(
            finalized_wallet_assets=_amount(10_000_000),
            protected_treasury_reserve=_amount(1_000_000),
            active_capital_reservations=_amount(0),
            pending_submission_max_debit=_amount(500_000),
            unresolved_ambiguous_attempt_reserve=_amount(1_000_000),
            rent_liabilities=_amount(0),
            estimated_failure_charges=_amount(0),
            provider_network_fee_buffer=_amount(0),
            withdrawal_sweep_holds=_amount(0),
        )


def test_pr163_funding_sweep_requires_treasury_authorization() -> None:
    request = FundingSweepRequest(
        source_wallet="Treasury111111111111111111111111111111111",
        destination_wallet="Cold1111111111111111111111111111111111",
        amount=_amount(100_000),
        request_hash="request-hash",
        destination_allowlisted=True,
        simulated_message_hash="message-hash",
        isolated_signer_required=True,
    )

    with pytest.raises(TreasuryAccountingError, match="authorization"):
        request.validate(now_ns=20, policy_hash="policy-hash")

    authorized = FundingSweepRequest(
        source_wallet=request.source_wallet,
        destination_wallet=request.destination_wallet,
        amount=request.amount,
        request_hash=request.request_hash,
        destination_allowlisted=True,
        simulated_message_hash=request.simulated_message_hash,
        isolated_signer_required=True,
        authorization=TreasuryAuthorization(
            authorization_hash="auth-hash",
            request_hash="request-hash",
            approver_principal_hash="approver-hash",
            policy_hash="policy-hash",
            scope="treasury-sweep",
            issued_at_ns=10,
            expires_at_ns=30,
        ),
    )

    authorized.validate(now_ns=20, policy_hash="policy-hash")


def test_pr163_daily_report_variance_triggers_hard_latch() -> None:
    window = RiskWindow.utc_day("2026-07-22")
    report = DailyTreasuryReport(
        window=window,
        opening_finalized_balance=_amount(10_000),
        funding=_amount(1_000),
        withdrawals=_amount(500),
        realized_pnl=_amount(-700),
        fees=_amount(100),
        ending_finalized_balance=_amount(9_600),
        unresolved_exposure=_amount(2_000),
        tolerance_base_units=0,
    )

    assert report.expected_ending_balance.base_units == 9_700
    assert report.ledger_to_chain_variance_base_units == 100
    assert report.hard_latch_required is True
    with pytest.raises(TreasuryAccountingError, match="variance"):
        report.assert_balanced()
