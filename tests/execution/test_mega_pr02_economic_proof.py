from dataclasses import replace

from src.config.chain_registry import TOKEN_PROGRAM_ADDRESS
from src.execution.economic_reconciliation.mega_pr02_proof import (
    ConservativeAssetQuote,
    ConservativeValuationSnapshot,
    MarginfiRegistrySnapshot,
    QualificationReason,
    QualificationStatus,
    RawAccountBinding,
    RawSimulationStateProof,
    RawStateEconomicProofAuthority,
    decoded_marginfi_hash,
    decoded_observation_hash,
)
from src.execution.economic_reconciliation.models import (
    AssetBreakdown,
    AssetKey,
    FeeEvidence,
    MarginfiRepaymentObservation,
    NATIVE_SOL_ASSET,
    NativeObservation,
    NativeState,
    ReconciliationEvidence,
    ReconciliationReason,
    ReconciliationReport,
    ReconciliationStatus,
    RepaymentProof,
    TokenObservation,
    TokenState,
)

SLOT = 223_344
HASH = "a" * 64
RESPONSE_HASH = "b" * 64
LOGS_HASH = "c" * 64
RAW_HASH = "d" * 64
SOURCE_HASH = "e" * 64
REPORT_HASH = "f" * 64
PAYER = "payer"
AUTHORITY = "wallet-authority"
MARGINFI = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
BANK = "bank"
VAULT = "vault"
MARGIN_ACCOUNT = "margin-account"
USDC = AssetKey("usdc-mint", TOKEN_PROGRAM_ADDRESS, 6)


def native(pre: int = 1_000_000, post: int = 992_000) -> NativeObservation:
    return NativeObservation(
        PAYER,
        NativeState(PAYER, "system", pre, SLOT),
        NativeState(PAYER, "system", post, SLOT),
    )


def token_state(address: str, asset: AssetKey, amount: int, authority: str) -> TokenState:
    return TokenState(
        address,
        asset.token_program,
        authority,
        asset,
        amount,
        2_039_280,
        SLOT,
    )


def token(
    address: str,
    asset: AssetKey,
    pre: int,
    post: int,
    *,
    authority: str = AUTHORITY,
    include: bool = True,
) -> TokenObservation:
    return TokenObservation(
        address,
        authority,
        asset,
        token_state(address, asset, pre, authority),
        token_state(address, asset, post, authority),
        include_in_wallet_delta=include,
    )


def marginfi(
    *,
    program_id: str = MARGINFI,
    asset: AssetKey = USDC,
    borrowed: int = 1_000,
    required: int = 1_010,
    vault_before: int = 100_000,
    vault_after: int = 100_010,
) -> MarginfiRepaymentObservation:
    return MarginfiRepaymentObservation(
        program_id,
        MARGIN_ACCOUNT,
        BANK,
        VAULT,
        asset,
        SLOT,
        program_id,
        program_id,
        program_id,
        program_id,
        0,
        0,
        0,
        0,
        borrowed,
        required,
        vault_before,
        vault_after,
    )


def evidence(
    *,
    wallet_pre: int = 1_000,
    wallet_post: int = 1_120,
    native_pre: int = 1_000_000,
    native_post: int = 992_000,
    fees: FeeEvidence | None = None,
    margin: MarginfiRepaymentObservation | None = None,
) -> ReconciliationEvidence:
    vault_before, vault_after = 100_000, 100_010
    repayment = margin or marginfi()
    return ReconciliationEvidence(
        HASH,
        HASH,
        SLOT,
        SLOT,
        SLOT - 1,
        True,
        RESPONSE_HASH,
        LOGS_HASH,
        USDC,
        (native(native_pre, native_post),),
        (
            token("wallet-token", USDC, wallet_pre, wallet_post),
            token(
                VAULT,
                USDC,
                vault_before,
                vault_after,
                authority="vault-authority",
                include=False,
            ),
        ),
        fees or FeeEvidence(5_000, 1_000, 1_000),
        repayment,
        (PAYER, "wallet-token", VAULT),
    )


def legacy_profit_report(
    *,
    settlement_net: int,
    usdc_net: int,
    native_net: int,
) -> ReconciliationReport:
    return ReconciliationReport(
        ReconciliationStatus.PROVEN_PROFIT,
        ReconciliationReason.RECONCILED_PROFIT,
        True,
        HASH,
        SLOT,
        USDC,
        settlement_net,
        (
            AssetBreakdown(USDC, usdc_net, 0, 0, 0, 0, 0, 0, usdc_net),
            AssetBreakdown(NATIVE_SOL_ASSET, native_net, 0, 0, 0, 0, 0, 0, native_net),
        ),
        RepaymentProof(True, 1_000, 1_010, 1_010, 10),
        RESPONSE_HASH,
        LOGS_HASH,
        REPORT_HASH,
    )


def registry(program_id: str = MARGINFI) -> MarginfiRegistrySnapshot:
    return MarginfiRegistrySnapshot.build(
        program_id=program_id,
        banks={BANK},
        liquidity_vaults={VAULT},
        margin_accounts={MARGIN_ACCOUNT},
    )


def valuation(
    *,
    include_native: bool = True,
    usdc_units: int = 1_000,
    sol_lamport_units: int = 20,
    min_profit: int = 100,
) -> ConservativeValuationSnapshot:
    quotes = [ConservativeAssetQuote(USDC, usdc_units, SOURCE_HASH, SLOT)]
    if include_native:
        quotes.append(
            ConservativeAssetQuote(NATIVE_SOL_ASSET, sol_lamport_units, SOURCE_HASH, SLOT)
        )
    return ConservativeValuationSnapshot(
        quote_currency="micro-usdc",
        quotes=tuple(quotes),
        slot=SLOT,
        max_slot_lag=2,
        min_profit_quote_units=min_profit,
    )


def raw_state(ev: ReconciliationEvidence, *, mutate: str | None = None) -> RawSimulationStateProof:
    native_binding = RawAccountBinding(
        PAYER,
        "system",
        SLOT,
        RAW_HASH,
        "0" * 64 if mutate == PAYER else decoded_observation_hash(ev.native[0]),
    )
    wallet_binding = RawAccountBinding(
        "wallet-token",
        TOKEN_PROGRAM_ADDRESS,
        SLOT,
        RAW_HASH,
        "0" * 64
        if mutate == "wallet-token"
        else decoded_observation_hash(ev.tokens[0]),
    )
    vault_binding = RawAccountBinding(
        VAULT,
        TOKEN_PROGRAM_ADDRESS,
        SLOT,
        RAW_HASH,
        decoded_observation_hash(ev.tokens[1]),
    )
    bank_binding = RawAccountBinding(
        BANK,
        ev.marginfi.program_id,
        SLOT,
        RAW_HASH,
        decoded_marginfi_hash(ev.marginfi),
    )
    margin_binding = RawAccountBinding(
        MARGIN_ACCOUNT,
        ev.marginfi.program_id,
        SLOT,
        RAW_HASH,
        decoded_marginfi_hash(ev.marginfi),
    )
    return RawSimulationStateProof(
        HASH,
        RESPONSE_HASH,
        LOGS_HASH,
        SLOT,
        (native_binding, wallet_binding, vault_binding, bank_binding, margin_binding),
    )


def qualify(ev: ReconciliationEvidence, report: ReconciliationReport, **kwargs):
    return RawStateEconomicProofAuthority().qualify(
        evidence=ev,
        report=report,
        raw_state=kwargs.get("raw") or raw_state(ev),
        registry=kwargs.get("registry_snapshot") or registry(),
        valuation=kwargs.get("valuation_snapshot") or valuation(),
    )


def test_old_settlement_profit_with_negative_native_value_is_not_qualified():
    ev = evidence()
    report = legacy_profit_report(settlement_net=120, usdc_net=120, native_net=-8_000)
    proof = qualify(ev, report)

    assert report.status is ReconciliationStatus.PROVEN_PROFIT
    assert report.settlement_net == 120
    assert proof.status is QualificationStatus.PROVEN_LOSS
    assert proof.reason is QualificationReason.NEGATIVE_CROSS_ASSET_NET
    assert proof.quote_net < 0
    assert not proof.qualified


def test_strictly_positive_conservative_total_can_be_qualified():
    ev = evidence(wallet_post=2_200, native_post=999_990, fees=FeeEvidence(0, 0, 0))
    report = legacy_profit_report(settlement_net=1_200, usdc_net=1_200, native_net=-10)
    proof = qualify(ev, report)

    assert proof.status is QualificationStatus.QUALIFIED_PROFIT
    assert proof.reason is QualificationReason.QUALIFIED_STRICT_POSITIVE_VALUE
    assert proof.qualified
    assert proof.quote_net > proof.min_profit_quote_units


def test_zero_total_value_is_break_even_not_profit():
    ev = evidence(wallet_post=1_000, native_post=1_000_000, fees=FeeEvidence(0, 0, 0))
    report = legacy_profit_report(settlement_net=0, usdc_net=0, native_net=0)
    proof = qualify(ev, report, valuation_snapshot=valuation(min_profit=0))

    assert report.status is ReconciliationStatus.PROVEN_PROFIT
    assert proof.status is QualificationStatus.BREAK_EVEN
    assert proof.reason is QualificationReason.NET_NOT_STRICTLY_POSITIVE
    assert proof.quote_net == 0
    assert not proof.qualified


def test_unpriced_residual_asset_fails_closed():
    ev = evidence()
    report = legacy_profit_report(settlement_net=120, usdc_net=120, native_net=-8_000)
    proof = qualify(ev, report, valuation_snapshot=valuation(include_native=False))

    assert proof.status is QualificationStatus.INDETERMINATE
    assert proof.reason is QualificationReason.VALUATION_MISSING
    assert not proof.qualified


def test_arbitrary_marginfi_program_is_not_registry_qualified():
    ev = evidence(margin=marginfi(program_id="ATTACKER_CONTROLLED_PROGRAM"))
    report = legacy_profit_report(settlement_net=120, usdc_net=120, native_net=-8_000)
    proof = qualify(ev, report)

    assert proof.status is QualificationStatus.INDETERMINATE
    assert proof.reason is QualificationReason.MARGINFI_REGISTRY_MISMATCH
    assert not proof.qualified


def test_mutated_decoded_account_hash_fails_closed():
    ev = evidence(wallet_post=2_200, native_post=999_990, fees=FeeEvidence(0, 0, 0))
    report = legacy_profit_report(settlement_net=1_200, usdc_net=1_200, native_net=-10)
    proof = RawStateEconomicProofAuthority().qualify(
        evidence=ev,
        report=report,
        raw_state=raw_state(ev, mutate="wallet-token"),
        registry=registry(),
        valuation=valuation(),
    )

    assert proof.status is QualificationStatus.INDETERMINATE
    assert proof.reason is QualificationReason.RAW_DECODE_BINDING_MISMATCH
    assert not proof.qualified


def test_stale_valuation_fails_closed():
    ev = evidence(wallet_post=2_200, native_post=999_990, fees=FeeEvidence(0, 0, 0))
    report = legacy_profit_report(settlement_net=1_200, usdc_net=1_200, native_net=-10)
    stale = replace(
        valuation(),
        quotes=(
            ConservativeAssetQuote(USDC, 1_000, SOURCE_HASH, SLOT - 10),
            ConservativeAssetQuote(NATIVE_SOL_ASSET, 20, SOURCE_HASH, SLOT),
        ),
    )
    proof = qualify(ev, report, valuation_snapshot=stale)

    assert proof.status is QualificationStatus.INDETERMINATE
    assert proof.reason is QualificationReason.VALUATION_STALE
    assert not proof.qualified
