from dataclasses import replace
from types import SimpleNamespace

from src.config.chain_registry import TOKEN_2022_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS
from src.execution.economic_reconciliation import (
    AccountLifecycle,
    AssetKey,
    EconomicReconciler,
    FeeEvidence,
    MarginfiRepaymentObservation,
    NATIVE_SOL_ASSET,
    NativeObservation,
    NativeState,
    ReconciliationEvidence,
    ReconciliationReason,
    ReconciliationStatus,
    TokenObservation,
    TokenState,
)

SLOT = 123_456
HASH = "a" * 64
RESPONSE_HASH = "b" * 64
LOGS_HASH = "c" * 64
PAYER = "payer"
AUTHORITY = "wallet-authority"
MARGINFI = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
VAULT = "vault"
USDC = AssetKey("usdc-mint", TOKEN_PROGRAM_ADDRESS, 6)
T22 = AssetKey("token-2022-mint", TOKEN_2022_PROGRAM_ADDRESS, 6)


def native(pre=1_000_000, post=992_000):
    return NativeObservation(
        PAYER,
        NativeState(PAYER, "system", pre, SLOT),
        NativeState(PAYER, "system", post, SLOT),
    )


def token(
    address,
    asset,
    pre,
    post,
    *,
    authority=AUTHORITY,
    lifecycle=AccountLifecycle.STABLE,
    include=True,
    extensions=(),
    pre_lamports=2_039_280,
    post_lamports=2_039_280,
):
    def state(amount, lamports):
        return TokenState(
            address,
            asset.token_program,
            authority,
            asset,
            amount,
            lamports,
            SLOT,
            extensions,
        )

    return TokenObservation(
        address,
        authority,
        asset,
        None if pre is None else state(pre, pre_lamports),
        None if post is None else state(post, post_lamports),
        lifecycle,
        include,
    )


def marginfi(
    asset=USDC,
    *,
    borrowed=1_000,
    required=1_010,
    vault_before=100_000,
    vault_after=100_010,
    liability_after=0,
):
    return MarginfiRepaymentObservation(
        MARGINFI,
        "margin-account",
        "bank",
        VAULT,
        asset,
        SLOT,
        MARGINFI,
        MARGINFI,
        MARGINFI,
        MARGINFI,
        0,
        0,
        0,
        liability_after,
        borrowed,
        required,
        vault_before,
        vault_after,
    )


def evidence(
    *,
    asset=USDC,
    wallet_pre=1_000,
    wallet_post=1_120,
    extra_tokens=(),
    margin=None,
    required=(),
):
    vault_before, vault_after = 100_000, 100_010
    tokens = (
        token("wallet-token", asset, wallet_pre, wallet_post),
        token(
            VAULT,
            asset,
            vault_before,
            vault_after,
            authority="vault-authority",
            include=False,
        ),
        *extra_tokens,
    )
    return ReconciliationEvidence(
        HASH,
        HASH,
        SLOT,
        SLOT,
        SLOT - 1,
        True,
        RESPONSE_HASH,
        LOGS_HASH,
        asset,
        (native(),),
        tokens,
        FeeEvidence(5_000, 1_000, 1_000),
        margin or marginfi(asset),
        (PAYER, "wallet-token", VAULT, *required),
    )


def breakdown(report, asset):
    return next(item for item in report.breakdowns if item.asset == asset)


def test_positive_state_reconciliation_and_decomposition():
    report = EconomicReconciler().reconcile(evidence())
    assert report.status is ReconciliationStatus.PROVEN_PROFIT
    assert report.complete and report.repayment.proven
    assert report.settlement_net == 120
    settlement = breakdown(report, USDC)
    assert (settlement.gross, settlement.protocol_fee, settlement.net) == (130, 10, 120)
    native_result = breakdown(report, NATIVE_SOL_ASSET)
    assert native_result.net == -8_000
    assert (
        native_result.network_fee,
        native_result.priority_fee,
        native_result.tip,
    ) == (5_000, 1_000, 1_000)
    assert len(report.reconciliation_hash) == 64


def test_loss_is_complete():
    report = EconomicReconciler().reconcile(evidence(wallet_post=995))
    assert report.status is ReconciliationStatus.PROVEN_LOSS
    assert report.complete and report.settlement_net == -5


def test_partial_required_state_fails_closed():
    report = EconomicReconciler().reconcile(evidence(required=("missing",)))
    assert report.status is ReconciliationStatus.INDETERMINATE
    assert report.reason is ReconciliationReason.REQUIRED_ACCOUNT_MISSING


def test_token_2022_immutable_owner_is_supported():
    wallet = token("wallet-t22", T22, 50, 75, extensions=("immutable_owner",))
    vault = token(
        VAULT,
        T22,
        100_000,
        100_010,
        authority="vault-authority",
        include=False,
        extensions=("immutable_owner",),
    )
    ev = replace(
        evidence(),
        settlement_asset=T22,
        tokens=(wallet, vault),
        required_accounts=(PAYER, "wallet-t22", VAULT),
        marginfi=marginfi(T22),
    )
    report = EconomicReconciler().reconcile(ev)
    assert report.status is ReconciliationStatus.PROVEN_PROFIT
    assert report.settlement_net == 25


def test_unknown_token_2022_extension_is_rejected():
    bad = token("bad-t22", T22, 1, 2, extensions=("confidential_transfer_account",))
    ev = replace(
        evidence(),
        tokens=(*evidence().tokens, bad),
        required_accounts=(*evidence().required_accounts, "bad-t22"),
    )
    report = EconomicReconciler().reconcile(ev)
    assert report.reason is ReconciliationReason.TOKEN_EXTENSION_UNSUPPORTED


def test_created_ata_rent_is_native_only():
    created = token(
        "new-ata",
        USDC,
        None,
        0,
        lifecycle=AccountLifecycle.CREATED,
        post_lamports=2_039_280,
    )
    ev = replace(
        evidence(extra_tokens=(created,), required=("new-ata",)),
        native=(native(pre=5_000_000, post=5_000_000 - 2_039_280 - 8_000),),
    )
    report = EconomicReconciler().reconcile(ev)
    assert report.status is ReconciliationStatus.PROVEN_PROFIT
    assert breakdown(report, NATIVE_SOL_ASSET).rent_locked == 2_039_280
    assert breakdown(report, USDC).rent_locked == 0


def test_failed_vault_return_is_repayment_failure():
    ev = replace(
        evidence(),
        tokens=(
            evidence().tokens[0],
            token(
                VAULT,
                USDC,
                100_000,
                100_005,
                authority="vault-authority",
                include=False,
            ),
        ),
        marginfi=marginfi(vault_after=100_005),
    )
    report = EconomicReconciler().reconcile(ev)
    assert report.status is ReconciliationStatus.REPAYMENT_FAILED
    assert report.reason is ReconciliationReason.MARGINFI_VAULT_MISMATCH
    assert not report.repayment.proven


def test_logs_alone_never_prove_repayment():
    report = EconomicReconciler().reconcile(replace(evidence(), marginfi=None))
    assert report.status is ReconciliationStatus.REPAYMENT_FAILED
    assert report.reason is ReconciliationReason.MARGINFI_EVIDENCE_MISSING


def test_exact_message_hash_and_slot_are_required():
    assert (
        EconomicReconciler()
        .reconcile(replace(evidence(), simulated_message_hash="d" * 64))
        .reason
        is ReconciliationReason.MESSAGE_HASH_MISMATCH
    )
    assert (
        EconomicReconciler()
        .reconcile(replace(evidence(), snapshot_slot=SLOT - 1))
        .reason
        is ReconciliationReason.SLOT_MISMATCH
    )


def test_unknown_token_program_is_rejected():
    unknown = AssetKey("unknown", "Unknown1111111111111111111111111111111111", 6)
    ev = replace(evidence(), settlement_asset=unknown)
    report = EconomicReconciler().reconcile(ev)
    assert report.status is ReconciliationStatus.INDETERMINATE
    assert report.reason is ReconciliationReason.TOKEN_PROGRAM_UNSUPPORTED


def test_pr036_adapter_binds_hashes_and_decomposes_fee():
    from src.execution.exact_simulation import (
        ExactSimulationReport,
        FinalizedSimulation,
        RpcSimulationEvidence,
    )
    from src.execution.economic_reconciliation import evidence_from_exact_simulation

    rpc = RpcSimulationEvidence(
        HASH, RESPONSE_HASH, LOGS_HASH, SLOT, 100, None, ("h1", "h2", "h3")
    )
    report = ExactSimulationReport(
        rpc,
        rpc,
        200_000,
        5_000,
        7_000,
        SLOT,
        "confirmed",
        SLOT - 1,
        SLOT + 100,
        (PAYER, "wallet-token", VAULT),
    )
    finalized = FinalizedSimulation(SimpleNamespace(message_hash=HASH), report)
    ev = evidence_from_exact_simulation(
        finalized,
        settlement_asset=USDC,
        native=(native(),),
        tokens=evidence().tokens,
        marginfi=marginfi(),
        decoded_account_hashes=("h1", "h2", "h3"),
    )
    assert ev.fees.priority_fee_lamports == 1_000
    assert ev.fees.base_network_fee_lamports == 6_000
    assert EconomicReconciler().reconcile(ev).complete
