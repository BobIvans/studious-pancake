from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.treasury.financial_risk import (
    AccountingStage,
    AssetAmount,
    AssetIdentity,
    AttemptOutcome,
    ChainRegistryManifest,
    DailyTreasuryReport,
    DurableRiskState,
    DurableTreasuryLedger,
    FundingSweepRequest,
    LedgerAccountKind,
    LedgerEntryKind,
    LedgerPosting,
    ObservationPolicy,
    PostingSide,
    ProgramDeploymentAttestation,
    RiskLedgerEntry,
    RiskWindow,
    RpcEndpointEvidence,
    RpcProviderRegistryEntry,
    RpcProviderRegistryManifest,
    SolvencyInputs,
    TreasuryAccountingError,
    TreasuryAuthorization,
    TreasuryScope,
    VerifiedChainRegistry,
    VerifiedRpcProviderRegistry,
    WalletClassification,
    WalletObservationPackage,
    WalletRegistryEntry,
    compute_solvency_report,
    domain_hash,
    fold_risk_counters,
    reject_caller_supplied_wallet_balance,
    sign_hmac_payload,
)


GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2h8"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
JUPITER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
WRAPPED_SOL = "So11111111111111111111111111111111111111112"
CHAIN_KEY = b"chain-registry-key-material-32!!"
PROVIDER_KEY = b"provider-registry-key-material!!"
APPROVER_KEY = b"treasury-approver-key-material!!"


def _h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _sol_asset() -> AssetIdentity:
    return AssetIdentity(
        cluster_genesis=GENESIS,
        symbol="SOL",
        mint=WRAPPED_SOL,
        token_program=TOKEN_PROGRAM,
        decimals=9,
    )


def _amount(value: int) -> AssetAmount:
    return AssetAmount(_sol_asset(), value)


def _chain_registry() -> VerifiedChainRegistry:
    manifest = ChainRegistryManifest(
        cluster_genesis=GENESIS,
        generation=4,
        policy_hash=_h("chain-policy"),
        created_at_ns=1_000,
        programs=tuple(
            ProgramDeploymentAttestation(
                program_id=program,
                program_data_hash=_h(f"program-data:{program}"),
                deployment_slot=100,
                authority_policy_hash=_h(f"authority:{program}"),
            )
            for program in (SYSTEM_PROGRAM, TOKEN_PROGRAM, JUPITER_PROGRAM)
        ),
    )
    signature = sign_hmac_payload(
        key=CHAIN_KEY,
        domain="mpr15/chain-registry-signature",
        payload_hash=manifest.manifest_hash,
    )
    return VerifiedChainRegistry.verify(
        manifest=manifest,
        signer_key_id="chain-root",
        signature=signature,
        trusted_keys={"chain-root": CHAIN_KEY},
    )


def _provider_registry(*, correlated: bool = False) -> VerifiedRpcProviderRegistry:
    entries = (
        RpcProviderRegistryEntry(
            provider_id="rpc-a",
            endpoint_identity_hash=_h("endpoint-a"),
            operator_group_hash=_h("operator-shared" if correlated else "operator-a"),
            network_path_group_hash=_h("path-a"),
            allowed_cluster_genesis=GENESIS,
        ),
        RpcProviderRegistryEntry(
            provider_id="rpc-b",
            endpoint_identity_hash=_h("endpoint-b"),
            operator_group_hash=_h("operator-shared" if correlated else "operator-b"),
            network_path_group_hash=_h("path-b"),
            allowed_cluster_genesis=GENESIS,
        ),
    )
    manifest = RpcProviderRegistryManifest(
        generation=7,
        policy_hash=_h("provider-policy"),
        created_at_ns=1_000,
        entries=entries,
    )
    signature = sign_hmac_payload(
        key=PROVIDER_KEY,
        domain="mpr15/provider-registry-signature",
        payload_hash=manifest.manifest_hash,
    )
    return VerifiedRpcProviderRegistry.verify(
        manifest=manifest,
        signer_key_id="provider-root",
        signature=signature,
        trusted_keys={"provider-root": PROVIDER_KEY},
    )


def _registry(*, approved_token_accounts: tuple[str, ...] = ()) -> WalletRegistryEntry:
    return WalletRegistryEntry(
        cluster_genesis=GENESIS,
        wallet_pubkey=SYSTEM_PROGRAM,
        purpose="limited-live execution wallet",
        signer_backend="isolated-signer",
        owner_custodian="treasury",
        classification=WalletClassification.HOT,
        approved_programs=(JUPITER_PROGRAM, SYSTEM_PROGRAM, TOKEN_PROGRAM),
        approved_token_accounts=approved_token_accounts,
        protected_reserve=_amount(2_000_000),
        maximum_exposure=_amount(10_000_000),
        funding_policy_id=_h("funding-policy"),
        sweep_policy_id=_h("sweep-policy"),
        registry_generation=5,
        registry_manifest_hash=_h("wallet-registry"),
        chain_registry=_chain_registry(),
    )


def _raw_bundle(
    *,
    balance: int = 20_000_000,
    context_slot: int = 100,
    root_slot: int = 105,
    token_accounts: list[dict[str, object]] | None = None,
) -> str:
    return json.dumps(
        {
            "schema": "mpr15.wallet-rpc-bundle.v1",
            "cluster_genesis": GENESIS,
            "wallet_pubkey": SYSTEM_PROGRAM,
            "context_slot": context_slot,
            "root_slot": root_slot,
            "native_balance_base_units": balance,
            "token_accounts": token_accounts or [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _endpoint(
    provider_id: str,
    *,
    raw: str | None = None,
    collected_at_ns: int = 10_000,
    context_slot: int = 100,
    root_slot: int = 105,
) -> RpcEndpointEvidence:
    raw = raw or _raw_bundle(context_slot=context_slot, root_slot=root_slot)
    return RpcEndpointEvidence(
        provider_id=provider_id,
        request_hash=_h("wallet-request"),
        raw_response_json=raw,
        response_hash=hashlib.sha256(raw.encode()).hexdigest(),
        transport_evidence_hash=_h(f"transport:{provider_id}"),
        commitment="finalized",
        context_slot=context_slot,
        root_slot=root_slot,
        collected_at_ns=collected_at_ns,
    )


def _observation(
    *,
    balance: int = 20_000_000,
    observed_at_ns: int = 10_000,
    provider_registry: VerifiedRpcProviderRegistry | None = None,
) -> WalletObservationPackage:
    raw = _raw_bundle(balance=balance)
    return WalletObservationPackage.from_rpc_quorum(
        registry_entry=_registry(),
        provider_registry=provider_registry or _provider_registry(),
        endpoint_evidence=(
            _endpoint("rpc-a", raw=raw, collected_at_ns=observed_at_ns - 1),
            _endpoint("rpc-b", raw=raw, collected_at_ns=observed_at_ns),
        ),
        policy_hash=_h("treasury-policy"),
        decoder_version="wallet-rpc-decoder-v1",
        observation_policy=ObservationPolicy(
            minimum_quorum=2,
            max_age_ns=1_000,
            max_future_skew_ns=10,
            max_collection_span_ns=50,
            max_root_slot_skew=2,
            max_root_lag_slots=20,
        ),
    )


def _posting_pair(
    kind: LedgerEntryKind,
    amount: int,
) -> tuple[LedgerPosting, LedgerPosting]:
    if kind is LedgerEntryKind.REALIZED_PNL:
        if amount > 0:
            debit, credit = LedgerAccountKind.CHAIN_WALLET, LedgerAccountKind.PNL_INCOME
        else:
            debit, credit = LedgerAccountKind.PNL_LOSS, LedgerAccountKind.CHAIN_WALLET
    else:
        topology = {
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
        debit, credit = topology[kind]
    absolute = abs(amount)
    return (
        LedgerPosting(
            account_kind=debit,
            account_id=(
                SYSTEM_PROGRAM
                if debit is LedgerAccountKind.CHAIN_WALLET
                else debit.value
            ),
            side=PostingSide.DEBIT,
            amount_base_units=absolute,
        ),
        LedgerPosting(
            account_kind=credit,
            account_id=(
                SYSTEM_PROGRAM
                if credit is LedgerAccountKind.CHAIN_WALLET
                else credit.value
            ),
            side=PostingSide.CREDIT,
            amount_base_units=absolute,
        ),
    )


def _entry(
    *,
    kind: LedgerEntryKind,
    amount: int,
    occurred_at_ns: int,
    movement: str,
    event: str,
    stage: AccountingStage = AccountingStage.FINALIZED,
    recorded_at_ns: int | None = None,
    attempt: str | None = None,
    outcome: AttemptOutcome | None = None,
) -> RiskLedgerEntry:
    return RiskLedgerEntry(
        event_id=_h(f"event:{event}"),
        movement_id=_h(f"movement:{movement}"),
        idempotency_key=_h(f"idempotency:{event}"),
        asset=_sol_asset(),
        kind=kind,
        stage=stage,
        amount_delta_base_units=amount,
        occurred_at_ns=occurred_at_ns,
        recorded_at_ns=recorded_at_ns or occurred_at_ns + 1,
        postings=_posting_pair(kind, amount),
        evidence_hash=_h(f"evidence:{movement}"),
        attempt_id=_h(f"attempt:{attempt}") if attempt else None,
        attempt_outcome=outcome,
        finalized_slot=123 if stage >= AccountingStage.FINALIZED else None,
        reason="test movement",
    )


def test_mpr15_rejects_caller_supplied_wallet_balance() -> None:
    with pytest.raises(TreasuryAccountingError, match="caller-supplied"):
        reject_caller_supplied_wallet_balance({"native_lamports": 20_000_000})

    with pytest.raises(TypeError):
        WalletObservationPackage()  # type: ignore[call-arg]


def test_mpr15_wallet_balance_is_derived_from_hashed_raw_rpc_bytes() -> None:
    observation = _observation(balance=21_000_000)
    assert observation.native_balance.base_units == 21_000_000
    assert len(observation.decoded_state_hash) == 64

    raw = _raw_bundle(balance=21_000_000)
    with pytest.raises(TreasuryAccountingError, match="response hash mismatch"):
        RpcEndpointEvidence(
            provider_id="rpc-a",
            request_hash=_h("wallet-request"),
            raw_response_json=raw,
            response_hash=_h("different-response"),
            transport_evidence_hash=_h("transport"),
            commitment="finalized",
            context_slot=100,
            root_slot=105,
            collected_at_ns=10_000,
        )


def test_mpr15_signed_provider_registry_enforces_real_independence() -> None:
    with pytest.raises(TreasuryAccountingError, match="operator groups"):
        _observation(provider_registry=_provider_registry(correlated=True))

    registry = _provider_registry()
    raw = _raw_bundle()
    with pytest.raises(TreasuryAccountingError, match="absent from signed registry"):
        WalletObservationPackage.from_rpc_quorum(
            registry_entry=_registry(),
            provider_registry=registry,
            endpoint_evidence=(
                _endpoint("rpc-a", raw=raw),
                _endpoint("rpc-fake", raw=raw),
            ),
            policy_hash=_h("treasury-policy"),
            decoder_version="wallet-rpc-decoder-v1",
            observation_policy=ObservationPolicy(2, 1_000, 10, 50, 2, 20),
        )


def test_mpr15_quorum_requires_same_decoded_state_and_same_request() -> None:
    raw_a = _raw_bundle(balance=20_000_000)
    raw_b = _raw_bundle(balance=19_000_000)
    with pytest.raises(TreasuryAccountingError, match="different wallet states"):
        WalletObservationPackage.from_rpc_quorum(
            registry_entry=_registry(),
            provider_registry=_provider_registry(),
            endpoint_evidence=(
                _endpoint("rpc-a", raw=raw_a),
                _endpoint("rpc-b", raw=raw_b),
            ),
            policy_hash=_h("treasury-policy"),
            decoder_version="wallet-rpc-decoder-v1",
            observation_policy=ObservationPolicy(2, 1_000, 10, 50, 2, 20),
        )

    second = replace(_endpoint("rpc-b", raw=raw_a), request_hash=_h("other-request"))
    with pytest.raises(TreasuryAccountingError, match="same request"):
        WalletObservationPackage.from_rpc_quorum(
            registry_entry=_registry(),
            provider_registry=_provider_registry(),
            endpoint_evidence=(_endpoint("rpc-a", raw=raw_a), second),
            policy_hash=_h("treasury-policy"),
            decoder_version="wallet-rpc-decoder-v1",
            observation_policy=ObservationPolicy(2, 1_000, 10, 50, 2, 20),
        )


def test_mpr15_freshness_future_and_root_lag_fail_closed() -> None:
    observation = _observation(observed_at_ns=10_000)
    observation.validate_freshness(
        trusted_now_ns=10_500,
        current_finalized_root_slot=110,
    )

    with pytest.raises(TreasuryAccountingError, match="stale"):
        observation.validate_freshness(
            trusted_now_ns=11_001,
            current_finalized_root_slot=110,
        )
    with pytest.raises(TreasuryAccountingError, match="future-dated"):
        observation.validate_freshness(
            trusted_now_ns=9_989,
            current_finalized_root_slot=110,
        )
    with pytest.raises(TreasuryAccountingError, match="too old"):
        observation.validate_freshness(
            trusted_now_ns=10_500,
            current_finalized_root_slot=126,
        )


def test_mpr15_token_inventory_requires_unique_hashed_accounts() -> None:
    token_account = JUPITER_PROGRAM
    token = {
        "account_pubkey": token_account,
        "owner_pubkey": SYSTEM_PROGRAM,
        "symbol": "SOL",
        "mint": WRAPPED_SOL,
        "token_program": TOKEN_PROGRAM,
        "decimals": 9,
        "amount_base_units": 10,
        "layout_version": "spl-token-v1",
        "account_hash": _h("token-account"),
        "delegated_authority": None,
        "close_authority": None,
    }
    raw = _raw_bundle(token_accounts=[token, token])
    with pytest.raises(
        TreasuryAccountingError, match="duplicate token account inventory"
    ):
        WalletObservationPackage.from_rpc_quorum(
            registry_entry=_registry(approved_token_accounts=(token_account,)),
            provider_registry=_provider_registry(),
            endpoint_evidence=(
                _endpoint("rpc-a", raw=raw),
                _endpoint("rpc-b", raw=raw),
            ),
            policy_hash=_h("treasury-policy"),
            decoder_version="wallet-rpc-decoder-v1",
            observation_policy=ObservationPolicy(2, 1_000, 10, 50, 2, 20),
        )

    missing_hash = dict(token)
    missing_hash["account_hash"] = ""
    raw_missing = _raw_bundle(token_accounts=[missing_hash])
    with pytest.raises(TreasuryAccountingError, match="account_hash"):
        WalletObservationPackage.from_rpc_quorum(
            registry_entry=_registry(approved_token_accounts=(token_account,)),
            provider_registry=_provider_registry(),
            endpoint_evidence=(
                _endpoint("rpc-a", raw=raw_missing),
                _endpoint("rpc-b", raw=raw_missing),
            ),
            policy_hash=_h("treasury-policy"),
            decoder_version="wallet-rpc-decoder-v1",
            observation_policy=ObservationPolicy(2, 1_000, 10, 50, 2, 20),
        )


def test_mpr15_chain_registry_rejects_noncanonical_identities_and_bad_signature(
) -> None:
    with pytest.raises(TreasuryAccountingError, match="32 bytes"):
        AssetIdentity(
            cluster_genesis=GENESIS,
            symbol="BAD",
            mint="not-a-pubkey",
            token_program=TOKEN_PROGRAM,
            decimals=9,
        )

    manifest = _chain_registry().manifest
    with pytest.raises(TreasuryAccountingError, match="signature verification"):
        VerifiedChainRegistry.verify(
            manifest=manifest,
            signer_key_id="chain-root",
            signature=_h("forged"),
            trusted_keys={"chain-root": CHAIN_KEY},
        )


def test_mpr15_solvency_uses_fresh_decoded_observation() -> None:
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
    report = compute_solvency_report(
        observation,
        inputs,
        trusted_now_ns=10_500,
        current_finalized_root_slot=110,
    )
    assert report.available_base_units == 9_000_000
    assert report.admission_allowed is True

    with pytest.raises(TreasuryAccountingError, match="does not match decoded"):
        compute_solvency_report(
            observation,
            replace(inputs, finalized_wallet_assets=_amount(19_000_000)),
            trusted_now_ns=10_500,
            current_finalized_root_slot=110,
        )


def test_mpr15_authorization_is_signed_scoped_not_before_and_one_time(tmp_path) -> None:
    unsigned = FundingSweepRequest(
        request_id=_h("request-1"),
        source_wallet=SYSTEM_PROGRAM,
        destination_wallet=JUPITER_PROGRAM,
        amount=_amount(100_000),
        scope=TreasuryScope.SWEEP,
        destination_policy_hash=_h("destination-policy"),
        simulated_message_hash=_h("simulated-message"),
        isolated_signer_required=True,
    )
    authorization = TreasuryAuthorization.issue(
        request_hash=unsigned.request_hash,
        approver_key_id="treasury-root",
        policy_hash=_h("treasury-policy"),
        scope=TreasuryScope.SWEEP,
        issued_at_ns=100,
        expires_at_ns=200,
        nonce=_h("nonce-1"),
        signing_key=APPROVER_KEY,
    )
    request = replace(unsigned, authorization=authorization)
    ledger_path = tmp_path / "treasury.sqlite3"
    with DurableTreasuryLedger(ledger_path) as ledger:
        with pytest.raises(TreasuryAccountingError, match="not active yet"):
            request.validate_and_consume(
                now_ns=99,
                policy_hash=_h("treasury-policy"),
                destination_allowlisted=True,
                trusted_approver_keys={"treasury-root": APPROVER_KEY},
                ledger=ledger,
            )
        consumption_hash = request.validate_and_consume(
            now_ns=150,
            policy_hash=_h("treasury-policy"),
            destination_allowlisted=True,
            trusted_approver_keys={"treasury-root": APPROVER_KEY},
            ledger=ledger,
        )
        assert len(consumption_hash) == 64

    with DurableTreasuryLedger(ledger_path) as reopened:
        with pytest.raises(TreasuryAccountingError, match="already consumed"):
            request.validate_and_consume(
                now_ns=151,
                policy_hash=_h("treasury-policy"),
                destination_allowlisted=True,
                trusted_approver_keys={"treasury-root": APPROVER_KEY},
                ledger=reopened,
            )


def test_mpr15_authorization_rejects_wrong_scope_and_tampered_request(tmp_path) -> None:
    request = FundingSweepRequest(
        request_id=_h("request-2"),
        source_wallet=SYSTEM_PROGRAM,
        destination_wallet=JUPITER_PROGRAM,
        amount=_amount(100_000),
        scope=TreasuryScope.FUNDING,
        destination_policy_hash=_h("destination-policy"),
        simulated_message_hash=_h("simulated-message"),
        isolated_signer_required=True,
    )
    wrong_scope = TreasuryAuthorization.issue(
        request_hash=request.request_hash,
        approver_key_id="treasury-root",
        policy_hash=_h("treasury-policy"),
        scope=TreasuryScope.SWEEP,
        issued_at_ns=100,
        expires_at_ns=200,
        nonce=_h("nonce-2"),
        signing_key=APPROVER_KEY,
    )
    with DurableTreasuryLedger(tmp_path / "auth.sqlite3") as ledger:
        with pytest.raises(TreasuryAccountingError, match="scope mismatch"):
            replace(request, authorization=wrong_scope).validate_and_consume(
                now_ns=150,
                policy_hash=_h("treasury-policy"),
                destination_allowlisted=True,
                trusted_approver_keys={"treasury-root": APPROVER_KEY},
                ledger=ledger,
            )

        correct = TreasuryAuthorization.issue(
            request_hash=request.request_hash,
            approver_key_id="treasury-root",
            policy_hash=_h("treasury-policy"),
            scope=TreasuryScope.FUNDING,
            issued_at_ns=100,
            expires_at_ns=200,
            nonce=_h("nonce-3"),
            signing_key=APPROVER_KEY,
        )
        tampered = replace(request, amount=_amount(100_001), authorization=correct)
        with pytest.raises(TreasuryAccountingError, match="another request"):
            tampered.validate_and_consume(
                now_ns=150,
                policy_hash=_h("treasury-policy"),
                destination_allowlisted=True,
                trusted_approver_keys={"treasury-root": APPROVER_KEY},
                ledger=ledger,
            )


def test_mpr15_expense_sign_and_double_entry_invariants_fail_closed() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    with pytest.raises(TreasuryAccountingError, match="amount must be positive"):
        _entry(
            kind=LedgerEntryKind.FEE,
            amount=-5,
            occurred_at_ns=window.start_ns + 1,
            movement="negative-fee",
            event="negative-fee",
        )

    with pytest.raises(TreasuryAccountingError, match="do not balance"):
        RiskLedgerEntry(
            event_id=_h("event:bad-posting"),
            movement_id=_h("movement:bad-posting"),
            idempotency_key=_h("idempotency:bad-posting"),
            asset=_sol_asset(),
            kind=LedgerEntryKind.FEE,
            stage=AccountingStage.FINALIZED,
            amount_delta_base_units=10,
            occurred_at_ns=window.start_ns + 1,
            recorded_at_ns=window.start_ns + 2,
            postings=(
                LedgerPosting(
                    LedgerAccountKind.FEE_EXPENSE,
                    "fee",
                    PostingSide.DEBIT,
                    10,
                ),
                LedgerPosting(
                    LedgerAccountKind.CHAIN_WALLET,
                    SYSTEM_PROGRAM,
                    PostingSide.CREDIT,
                    9,
                ),
            ),
            evidence_hash=_h("evidence:bad-posting"),
            finalized_slot=123,
        )


def test_mpr15_window_membership_comes_from_trusted_occurrence_time() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    old = _entry(
        kind=LedgerEntryKind.FEE,
        amount=5,
        occurred_at_ns=window.start_ns - 1,
        movement="old-fee",
        event="old-fee",
    )
    current = _entry(
        kind=LedgerEntryKind.FEE,
        amount=7,
        occurred_at_ns=window.start_ns + 1,
        movement="current-fee",
        event="current-fee",
    )
    snapshot = fold_risk_counters(
        entries=(old, current), window=window, asset=_sol_asset()
    )
    assert snapshot.fees_base_units == 7


def test_mpr15_stage_projection_counts_one_movement_once() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    finalized = _entry(
        kind=LedgerEntryKind.FEE,
        amount=11,
        occurred_at_ns=window.start_ns + 1,
        movement="fee-1",
        event="fee-finalized",
        stage=AccountingStage.FINALIZED,
    )
    reconciled = _entry(
        kind=LedgerEntryKind.FEE,
        amount=11,
        occurred_at_ns=window.start_ns + 1,
        movement="fee-1",
        event="fee-reconciled",
        stage=AccountingStage.RECONCILED,
        recorded_at_ns=window.start_ns + 3,
    )
    snapshot = fold_risk_counters(
        entries=(finalized, reconciled),
        window=window,
        asset=_sol_asset(),
    )
    assert snapshot.fees_base_units == 11

    conflict = replace(
        reconciled,
        amount_delta_base_units=12,
        postings=_posting_pair(LedgerEntryKind.FEE, 12),
    )
    with pytest.raises(TreasuryAccountingError, match="identity changed"):
        fold_risk_counters(
            entries=(finalized, conflict),
            window=window,
            asset=_sol_asset(),
        )


def test_mpr15_durable_ledger_enforces_idempotency_and_stage_fsm(tmp_path) -> None:
    window = RiskWindow.utc_day("2026-07-23")
    finalized = _entry(
        kind=LedgerEntryKind.FEE,
        amount=13,
        occurred_at_ns=window.start_ns + 1,
        movement="durable-fee",
        event="durable-finalized",
        stage=AccountingStage.FINALIZED,
    )
    reconciled = _entry(
        kind=LedgerEntryKind.FEE,
        amount=13,
        occurred_at_ns=window.start_ns + 1,
        movement="durable-fee",
        event="durable-reconciled",
        stage=AccountingStage.RECONCILED,
        recorded_at_ns=window.start_ns + 3,
    )
    path = tmp_path / "ledger.sqlite3"
    with DurableTreasuryLedger(path) as ledger:
        first_hash = ledger.append_event(finalized)
        assert ledger.append_event(finalized) == first_hash
        ledger.append_event(reconciled)
        assert len(ledger.events()) == 2

        booked = _entry(
            kind=LedgerEntryKind.FEE,
            amount=13,
            occurred_at_ns=window.start_ns + 1,
            movement="durable-fee",
            event="durable-booked",
            stage=AccountingStage.BOOKED,
            recorded_at_ns=window.start_ns + 4,
        )
        ledger.append_event(booked)

        regressed = _entry(
            kind=LedgerEntryKind.FEE,
            amount=13,
            occurred_at_ns=window.start_ns + 1,
            movement="durable-fee",
            event="durable-regressed",
            stage=AccountingStage.CONFIRMED,
            recorded_at_ns=window.start_ns + 5,
        )
        with pytest.raises(TreasuryAccountingError, match="illegal accounting stage"):
            ledger.append_event(regressed)

    with DurableTreasuryLedger(path) as reopened:
        state = reopened.replay_risk_state(windows=(window,), asset=_sol_asset())
        assert state.entry_count == 3
        assert state.movement_count == 1
        assert state.snapshots[0].fees_base_units == 13


def test_mpr15_consecutive_failures_count_unique_terminal_attempts() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    fail_1 = _entry(
        kind=LedgerEntryKind.FAILED_ATTEMPT_CHARGE,
        amount=5,
        occurred_at_ns=window.start_ns + 1,
        movement="fail-1",
        event="fail-1",
        attempt="attempt-1",
        outcome=AttemptOutcome.FAILED,
    )
    fail_1_reconciled = _entry(
        kind=LedgerEntryKind.FAILED_ATTEMPT_CHARGE,
        amount=5,
        occurred_at_ns=window.start_ns + 1,
        movement="fail-1",
        event="fail-1-reconciled",
        attempt="attempt-1",
        outcome=AttemptOutcome.FAILED,
        stage=AccountingStage.RECONCILED,
        recorded_at_ns=window.start_ns + 2,
    )
    fail_2 = _entry(
        kind=LedgerEntryKind.FAILED_ATTEMPT_CHARGE,
        amount=6,
        occurred_at_ns=window.start_ns + 3,
        movement="fail-2",
        event="fail-2",
        attempt="attempt-2",
        outcome=AttemptOutcome.FAILED,
    )
    success = _entry(
        kind=LedgerEntryKind.REALIZED_PNL,
        amount=10,
        occurred_at_ns=window.start_ns + 4,
        movement="success",
        event="success",
        attempt="attempt-3",
        outcome=AttemptOutcome.SUCCEEDED,
    )
    snapshot = fold_risk_counters(
        entries=(fail_1, fail_1_reconciled, fail_2, success),
        window=window,
        asset=_sol_asset(),
    )
    assert snapshot.failed_attempt_charges_base_units == 11
    assert snapshot.consecutive_failures == 0


def test_mpr15_durable_risk_state_is_replay_only_and_hash_chained() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    entries = (
        _entry(
            kind=LedgerEntryKind.REALIZED_PNL,
            amount=-700,
            occurred_at_ns=window.start_ns + 1,
            movement="pnl-1",
            event="pnl-1",
        ),
        _entry(
            kind=LedgerEntryKind.FEE,
            amount=25,
            occurred_at_ns=window.start_ns + 2,
            movement="fee-1",
            event="fee-1",
        ),
    )
    state = DurableRiskState.from_entries(
        entries=entries,
        windows=(window,),
        asset=_sol_asset(),
        previous_checkpoint_hash=_h("previous-checkpoint"),
    )
    state.verify_replay(entries=entries, windows=(window,), asset=_sol_asset())
    assert state.entry_count == 2
    assert state.movement_count == 2
    assert len(state.checkpoint_hash) == 64

    with pytest.raises(TypeError):
        DurableRiskState(  # type: ignore[call-arg]
            schema="forged",
            snapshots=(),
            ledger_hash=_h("fake"),
        )


def test_mpr15_daily_report_is_ledger_derived_and_unresolved_exposure_latches() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    entries = (
        _entry(
            kind=LedgerEntryKind.FUNDING,
            amount=1_000,
            occurred_at_ns=window.start_ns + 1,
            movement="funding",
            event="funding",
        ),
        _entry(
            kind=LedgerEntryKind.WITHDRAWAL,
            amount=500,
            occurred_at_ns=window.start_ns + 2,
            movement="withdrawal",
            event="withdrawal",
        ),
        _entry(
            kind=LedgerEntryKind.REALIZED_PNL,
            amount=-700,
            occurred_at_ns=window.start_ns + 3,
            movement="pnl",
            event="pnl",
        ),
        _entry(
            kind=LedgerEntryKind.FEE,
            amount=100,
            occurred_at_ns=window.start_ns + 4,
            movement="fee",
            event="fee",
        ),
        _entry(
            kind=LedgerEntryKind.UNRESOLVED_MAX_LOSS,
            amount=2_000,
            occurred_at_ns=window.start_ns + 5,
            movement="unresolved",
            event="unresolved",
        ),
    )
    report = DailyTreasuryReport.from_ledger(
        window=window,
        opening_finalized_balance=_amount(10_000),
        ending_finalized_balance=_amount(9_700),
        entries=entries,
        tolerance_base_units=0,
        unresolved_exposure_threshold_base_units=0,
    )
    assert report.expected_ending_balance.base_units == 9_700
    assert report.ledger_to_chain_variance_base_units == 0
    assert report.unresolved_exposure.base_units == 2_000
    assert report.hard_latch_required is True
    with pytest.raises(TreasuryAccountingError, match="unresolved exposure"):
        report.assert_balanced()


def test_mpr15_daily_report_rejects_variance_even_without_exposure() -> None:
    window = RiskWindow.utc_day("2026-07-23")
    report = DailyTreasuryReport.from_ledger(
        window=window,
        opening_finalized_balance=_amount(10_000),
        ending_finalized_balance=_amount(9_999),
        entries=(),
        tolerance_base_units=0,
    )
    assert report.hard_latch_required is True
    with pytest.raises(TreasuryAccountingError, match="variance"):
        report.assert_balanced()


def test_mpr15_domain_hash_is_deterministic() -> None:
    first = domain_hash("test", {"b": 2, "a": 1})
    second = domain_hash("test", {"a": 1, "b": 2})
    assert first == second
