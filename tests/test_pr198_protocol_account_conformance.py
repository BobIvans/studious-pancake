from __future__ import annotations

from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    BPF_UPGRADEABLE_LOADER_ADDRESS,
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
)
from src.protocol_account_conformance_pr198 import (
    AssociatedTokenAccountEvidence,
    KaminoProductionDecision,
    ProgramDeploymentEvidence,
    ProtocolAccountConformanceBundle,
    ProtocolDecisionEvidence,
    ProtocolName,
    TokenAccountEvidence,
    TokenMintEvidence,
    WsolLifecycleEvidence,
    ata_derivation_proof_sha256,
    evaluate_protocol_account_conformance,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
USER = SYSTEM_PROGRAM_ADDRESS
ATA = ASSOCIATED_TOKEN_PROGRAM_ADDRESS


def _deployment(**overrides: object) -> ProgramDeploymentEvidence:
    values = {
        "program_id": COMPUTE_BUDGET_PROGRAM_ADDRESS,
        "loader_program_id": BPF_UPGRADEABLE_LOADER_ADDRESS,
        "programdata_address": TOKEN_PROGRAM_ADDRESS,
        "executable": True,
        "binary_sha256": DIGEST_A,
        "idl_sha256": DIGEST_B,
        "attestation_sha256": DIGEST_C,
        "attested_slot": 10,
        "observed_slot": 12,
        "expiry_slot": 100,
        "upgrade_authority": None,
        "upgrade_authority_revoked": False,
    }
    values.update(overrides)
    return ProgramDeploymentEvidence(**values)


def _mint(**overrides: object) -> TokenMintEvidence:
    values = {
        "mint": NATIVE_SOL_MINT_ADDRESS,
        "token_program_id": TOKEN_PROGRAM_ADDRESS,
        "decimals": 9,
        "supply": 10_000_000,
        "initialized": True,
    }
    values.update(overrides)
    return TokenMintEvidence(**values)


def _account(**overrides: object) -> TokenAccountEvidence:
    values = {
        "account_address": ATA,
        "owner_wallet": USER,
        "mint": NATIVE_SOL_MINT_ADDRESS,
        "token_program_id": TOKEN_PROGRAM_ADDRESS,
        "amount": 1_000_000,
        "lamports": 3_039_280,
        "rent_exempt_minimum_lamports": 2_039_280,
        "native_lamports": 1_000_000,
        "created_by_attempt": True,
        "pre_existing": False,
    }
    values.update(overrides)
    return TokenAccountEvidence(**values)


def _ata(**overrides: object) -> AssociatedTokenAccountEvidence:
    values = {
        "ata_address": ATA,
        "wallet_owner": USER,
        "mint": NATIVE_SOL_MINT_ADDRESS,
        "token_program_id": TOKEN_PROGRAM_ADDRESS,
        "derivation_proof_sha256": ata_derivation_proof_sha256(
            wallet_owner=USER,
            mint=NATIVE_SOL_MINT_ADDRESS,
            token_program_id=TOKEN_PROGRAM_ADDRESS,
        ),
    }
    values.update(overrides)
    return AssociatedTokenAccountEvidence(**values)


def _bundle(**overrides: object) -> ProtocolAccountConformanceBundle:
    values = {
        "protocol_decision": ProtocolDecisionEvidence(
            protocol=ProtocolName.MARGINFI,
            credentialed_evidence_complete=True,
        ),
        "deployment": _deployment(),
        "mints": (_mint(),),
        "token_accounts": (_account(),),
        "ata_accounts": (_ata(),),
        "wsol_lifecycles": (
            WsolLifecycleEvidence(
                account_address=ATA,
                owner_wallet=USER,
                amount_lamports=1_000_000,
                rent_reserve_lamports=2_039_280,
                created_by_attempt=True,
                pre_existing_balance_lamports=0,
                may_close_after_attempt=True,
                close_destination=USER,
            ),
        ),
    }
    values.update(overrides)
    return ProtocolAccountConformanceBundle(**values)


def test_marginfi_complete_account_conformance_is_shadow_only() -> None:
    report = evaluate_protocol_account_conformance(_bundle(), current_slot=50)

    assert report.shadow_protocol_usable is True
    assert report.live_execution_allowed is False
    assert report.blockers == ()
    assert report.state.value == "shadow-conformant"
    assert report.evidence_hash


def test_marginfi_missing_credentialed_evidence_blocks() -> None:
    bundle = _bundle(
        protocol_decision=ProtocolDecisionEvidence(
            protocol=ProtocolName.MARGINFI,
            credentialed_evidence_complete=False,
        )
    )

    report = evaluate_protocol_account_conformance(bundle, current_slot=50)

    assert report.shadow_protocol_usable is False
    assert "MARGINFI_CREDENTIALLED_EVIDENCE_MISSING" in report.blockers


def test_kamino_must_be_removed_or_supported_with_real_combinations() -> None:
    missing_decision = _bundle(
        protocol_decision=ProtocolDecisionEvidence(
            protocol=ProtocolName.KAMINO,
            credentialed_evidence_complete=False,
        )
    )
    removed = _bundle(
        protocol_decision=ProtocolDecisionEvidence(
            protocol=ProtocolName.KAMINO,
            credentialed_evidence_complete=False,
            kamino_decision=KaminoProductionDecision.UNSUPPORTED_REMOVED,
            supported_combinations=0,
        )
    )

    blocked = evaluate_protocol_account_conformance(missing_decision, current_slot=50)
    accepted_removed = evaluate_protocol_account_conformance(removed, current_slot=50)

    assert "KAMINO_PRODUCTION_DECISION_MISSING" in blocked.blockers
    assert accepted_removed.shadow_protocol_usable is True


def test_unsupported_token_2022_extensions_fail_closed() -> None:
    token_2022_mint = _mint(
        token_program_id=TOKEN_2022_PROGRAM_ADDRESS,
        token_2022_extensions=("TransferFeeConfig",),
        transfer_fee_configured=True,
    )
    token_2022_account = _account(token_program_id=TOKEN_2022_PROGRAM_ADDRESS)
    token_2022_ata = _ata(
        token_program_id=TOKEN_2022_PROGRAM_ADDRESS,
        derivation_proof_sha256=ata_derivation_proof_sha256(
            wallet_owner=USER,
            mint=NATIVE_SOL_MINT_ADDRESS,
            token_program_id=TOKEN_2022_PROGRAM_ADDRESS,
        ),
    )
    report = evaluate_protocol_account_conformance(
        _bundle(
            mints=(token_2022_mint,),
            token_accounts=(token_2022_account,),
            ata_accounts=(token_2022_ata,),
        ),
        current_slot=50,
    )

    assert any(
        blocker.startswith("TOKEN_2022_UNSUPPORTED_EXTENSION")
        for blocker in report.blockers
    )
    assert any(
        blocker.startswith("TOKEN_2022_TRANSFER_FEE_UNSUPPORTED")
        for blocker in report.blockers
    )


def test_ata_derivation_and_account_binding_are_checked() -> None:
    report = evaluate_protocol_account_conformance(
        _bundle(ata_accounts=(_ata(derivation_proof_sha256=DIGEST_A),)),
        current_slot=50,
    )

    assert f"ATA_DERIVATION_PROOF_MISMATCH:{ATA}" in report.blockers


def test_wsol_pre_existing_balance_cannot_be_closed() -> None:
    lifecycle = WsolLifecycleEvidence(
        account_address=ATA,
        owner_wallet=USER,
        amount_lamports=1_000_000,
        rent_reserve_lamports=2_039_280,
        created_by_attempt=False,
        pre_existing_balance_lamports=1,
        may_close_after_attempt=True,
        close_destination=USER,
    )

    report = evaluate_protocol_account_conformance(
        _bundle(wsol_lifecycles=(lifecycle,)),
        current_slot=50,
    )

    assert "WSOL_CLOSE_REQUIRES_ATTEMPT_CREATED_ACCOUNT" in report.blockers
    assert "WSOL_PRE_EXISTING_BALANCE_CLOSE_FORBIDDEN" in report.blockers


def test_deployment_drift_and_expiry_block_protocol() -> None:
    report = evaluate_protocol_account_conformance(
        _bundle(
            deployment=_deployment(
                executable=False,
                observed_slot=5,
                expiry_slot=20,
                upgrade_authority=USER,
                upgrade_authority_revoked=False,
            )
        ),
        current_slot=50,
    )

    assert "PROGRAM_NOT_EXECUTABLE" in report.blockers
    assert "PROGRAM_OBSERVED_BEFORE_ATTESTED_SLOT" in report.blockers
    assert "PROGRAM_ATTESTATION_EXPIRED" in report.blockers
    assert "PROGRAM_UPGRADE_AUTHORITY_NOT_REVOKED" in report.blockers
