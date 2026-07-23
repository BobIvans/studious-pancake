from __future__ import annotations

from dataclasses import replace

from src.pr208_rooted_protocol_provider_attestation import (
    PR208ProtocolProviderEvidence,
    ExecutionAssetSet,
    MaterializedEvidenceRef,
    ProviderResponseEvidence,
    RootedAccountEvidence,
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    WSOL_MINT,
    evaluate_pr208_protocol_provider,
)

H = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
TOKEN2022_MINT = "Token2022Mint111111111111111111111111111111"
ATA = "Ata111111111111111111111111111111111111111"
PROGRAM = TOKEN_2022_PROGRAM_ID
PROTOCOL_ACCOUNT = "MarginfiAccount11111111111111111111111111"


def ref(path: str, digest: str = H) -> MaterializedEvidenceRef:
    return MaterializedEvidenceRef(
        path=path,
        sha256=digest,
        size_bytes=128,
        media_type="application/octet-stream",
        producer_id="pr208-fetcher",
        created_at_slot=100,
        retained_until_slot=200,
        attestation_sha256=H2,
    )


def account(
    address: str,
    *,
    kind: str = "protocol_account",
    owner: str = "Owner1111111111111111111111111111111111111",
    digest: str = H,
    executable: bool = False,
    extensions: tuple[str, ...] = (),
) -> RootedAccountEvidence:
    return RootedAccountEvidence(
        address=address,
        kind=kind,
        owner_program=owner,
        slot=120,
        min_context_slot=100,
        genesis_hash=H3,
        commitment="confirmed",
        raw_bytes_sha256=digest,
        evidence=ref(f"evidence/{address}.bin", digest),
        executable=executable,
        extensions=extensions,
    )


def provider(bound: tuple[str, ...]) -> ProviderResponseEvidence:
    return ProviderResponseEvidence(
        provider_id="helius-mainnet",
        endpoint_id="helius-mainnet-rpc-primary",
        credential_scope="readonly-accounts",
        response_kind="getMultipleAccounts",
        request_sha256=H,
        response_sha256=H2,
        tls_peer_fingerprint_sha256=H4,
        observed_slot=120,
        min_context_slot=100,
        genesis_hash=H3,
        commitment="confirmed",
        request_evidence=ref("provider/request.json", H),
        response_evidence=ref("provider/response.json", H2),
        bound_addresses=bound,
    )


def good_evidence() -> PR208ProtocolProviderEvidence:
    assets = ExecutionAssetSet(
        plan_sha256=H4,
        required_addresses=(PROTOCOL_ACCOUNT,),
        required_programs=(PROGRAM,),
        required_mints=(TOKEN2022_MINT,),
        token_2022_mints=(TOKEN2022_MINT,),
        ata_accounts=(ATA,),
        wsol_mint=WSOL_MINT,
    )
    required = (
        PROTOCOL_ACCOUNT,
        PROGRAM,
        TOKEN2022_MINT,
        ATA,
        WSOL_MINT,
    )
    return PR208ProtocolProviderEvidence(
        chain_genesis_hash=H3,
        commitment="confirmed",
        min_context_slot=100,
        execution_assets=assets,
        rooted_accounts=(
            account(PROTOCOL_ACCOUNT),
            account(PROGRAM, kind="program", owner="bpf-loader", executable=True),
            account(
                TOKEN2022_MINT,
                kind="mint",
                owner=TOKEN_2022_PROGRAM_ID,
                extensions=("transfer_fee_config_none",),
            ),
            account(ATA, kind="ata", owner=TOKEN_2022_PROGRAM_ID),
            account(WSOL_MINT, kind="mint", owner=SPL_TOKEN_PROGRAM_ID),
        ),
        provider_responses=(provider(required),),
    )


def test_pr208_rooted_protocol_provider_passes_for_materialized_bundle() -> None:
    report = evaluate_pr208_protocol_provider(good_evidence())

    assert report.passed is True
    assert report.blockers == ()
    assert report.live_capability_allowed is False
    assert report.sender_capability_allowed is False
    assert report.signer_capability_allowed is False


def test_pr208_rejects_boolean_claim_api_shape() -> None:
    evidence = replace(
        good_evidence(),
        caller_supplied_claims_present=True,
        exported_complete_claim_helper=True,
    )

    report = evaluate_pr208_protocol_provider(evidence)

    assert report.passed is False
    assert "PR208_CALLER_SUPPLIED_CLAIMS_PRESENT" in report.blockers
    assert "PR208_COMPLETE_CLAIM_HELPER_EXPORTED" in report.blockers


def test_pr208_rejects_non_materialized_or_placeholder_evidence() -> None:
    evidence = good_evidence()
    bad_ref = replace(
        evidence.rooted_accounts[0].evidence,
        path="../fake",
        sha256="0" * 64,
        materialized=False,
    )
    bad_account = replace(
        evidence.rooted_accounts[0],
        raw_bytes_sha256="0" * 64,
        evidence=bad_ref,
    )
    report = evaluate_pr208_protocol_provider(
        replace(evidence, rooted_accounts=(bad_account, *evidence.rooted_accounts[1:]))
    )

    assert "PR208_ROOTED_ACCOUNT_0_EVIDENCE_PATH_NOT_NORMALIZED" in report.blockers
    assert "PR208_ROOTED_ACCOUNT_0_EVIDENCE_SHA256_INVALID" in report.blockers
    assert "PR208_ROOTED_ACCOUNT_0_EVIDENCE_NOT_MATERIALIZED" in report.blockers


def test_pr208_requires_execution_asset_set_to_equal_rooted_bundle() -> None:
    evidence = good_evidence()
    assets = replace(
        evidence.execution_assets,
        required_addresses=("MissingAccount111111111111111111111111",),
    )

    report = evaluate_pr208_protocol_provider(replace(evidence, execution_assets=assets))

    assert (
        "PR208_EXECUTION_ASSET_NOT_ROOTED:MissingAccount111111111111111111111111"
        in report.blockers
    )


def test_pr208_rejects_token2022_identity_without_extension_materialization() -> None:
    evidence = good_evidence()
    bad_mint = replace(
        evidence.rooted_accounts[2],
        owner_program=SPL_TOKEN_PROGRAM_ID,
        extensions=(),
    )

    report = evaluate_pr208_protocol_provider(
        replace(
            evidence,
            rooted_accounts=(
                evidence.rooted_accounts[0],
                evidence.rooted_accounts[1],
                bad_mint,
                evidence.rooted_accounts[3],
                evidence.rooted_accounts[4],
            ),
        )
    )

    assert f"PR208_TOKEN2022_EXTENSIONS_NOT_MATERIALIZED:{TOKEN2022_MINT}" in report.blockers


def test_pr208_rejects_provider_without_endpoint_credential_or_tls_binding() -> None:
    evidence = good_evidence()
    bad_provider = replace(
        evidence.provider_responses[0],
        endpoint_id="",
        credential_scope="",
        tls_peer_fingerprint_sha256="f" * 64,
    )

    report = evaluate_pr208_protocol_provider(replace(evidence, provider_responses=(bad_provider,)))

    assert "PR208_PROVIDER_RESPONSE_0_ENDPOINT_ID_MISSING" in report.blockers
    assert "PR208_PROVIDER_RESPONSE_0_CREDENTIAL_SCOPE_MISSING" in report.blockers
    assert "PR208_PROVIDER_RESPONSE_0_TLS_PEER_FINGERPRINT_INVALID" in report.blockers


def test_pr208_rejects_provider_response_not_covering_execution_assets() -> None:
    evidence = good_evidence()
    bad_provider = replace(evidence.provider_responses[0], bound_addresses=(PROTOCOL_ACCOUNT,))

    report = evaluate_pr208_protocol_provider(replace(evidence, provider_responses=(bad_provider,)))

    assert f"PR208_ASSET_NOT_BOUND_TO_PROVIDER_RESPONSE:{TOKEN2022_MINT}" in report.blockers
    assert f"PR208_ASSET_NOT_BOUND_TO_PROVIDER_RESPONSE:{ATA}" in report.blockers


def test_pr208_rejects_cross_context_rooted_evidence() -> None:
    evidence = good_evidence()
    bad_account = replace(evidence.rooted_accounts[0], genesis_hash=H4, min_context_slot=101)

    report = evaluate_pr208_protocol_provider(
        replace(evidence, rooted_accounts=(bad_account, *evidence.rooted_accounts[1:]))
    )

    assert f"PR208_ROOTED_ACCOUNT_GENESIS_DRIFT:{PROTOCOL_ACCOUNT}" in report.blockers
    assert f"PR208_ROOTED_ACCOUNT_CONTEXT_DRIFT:{PROTOCOL_ACCOUNT}" in report.blockers


def test_pr208_rejects_live_sender_or_signer_capability() -> None:
    report = evaluate_pr208_protocol_provider(
        replace(
            good_evidence(),
            live_capability_enabled=True,
            sender_capability_enabled=True,
            signer_capability_enabled=True,
        )
    )

    assert "PR208_LIVE_CAPABILITY_ENABLED" in report.blockers
    assert "PR208_SENDER_CAPABILITY_ENABLED" in report.blockers
    assert "PR208_SIGNER_CAPABILITY_ENABLED" in report.blockers
