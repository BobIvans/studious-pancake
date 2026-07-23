from __future__ import annotations

from dataclasses import replace

from src.mpr02_v6_protocol_correctness_gate import (
    CABundleEvidence,
    ChainIdentityRegistryEvidence,
    JupiterV2BuildRequest,
    JupiterV2BuildResponse,
    MPR02V6Evidence,
    MPR02V6State,
    MarginFiTokenAccountEvidence,
    OFFICIAL_ASSOCIATED_TOKEN_PROGRAM_ID,
    OFFICIAL_TOKEN_2022_PROGRAM_ID,
    OFFICIAL_TOKEN_PROGRAM_ID,
    REQUIRED_FINDINGS,
    RoutePlanSegment,
    SCHEMA_VERSION,
    Token2022RentEvidence,
    evaluate_mpr02_v6_protocol_correctness,
)

SHA = "a" * 64
SHA2 = "b" * 64
PUB_A = "11111111111111111111111111111111"
PUB_B = "So11111111111111111111111111111111111111112"
PUB_C = "SysvarRent111111111111111111111111111111111"


def registry() -> ChainIdentityRegistryEvidence:
    return ChainIdentityRegistryEvidence(
        registry_generation=1,
        genesis_hash=SHA,
        registry_artifact_sha256=SHA,
        token_program_id=OFFICIAL_TOKEN_PROGRAM_ID,
        token_2022_program_id=OFFICIAL_TOKEN_2022_PROGRAM_ID,
        associated_token_program_id=OFFICIAL_ASSOCIATED_TOKEN_PROGRAM_ID,
        independent_golden_vectors=True,
        expected_ids_not_imported_from_modules_under_test=True,
    )


def request() -> JupiterV2BuildRequest:
    return JupiterV2BuildRequest(
        input_mint=PUB_A,
        output_mint=PUB_B,
        amount=1_000,
        taker=PUB_C,
        slippage_bps=50,
        dexes=("Raydium",),
        max_accounts=32,
        blockhash_slots_to_expiry=120,
    )


def segment(
    *,
    bps: int = 10_000,
    input_mint: str = PUB_A,
    output_mint: str = PUB_B,
    in_amount: int = 1_000,
    out_amount: int = 990,
) -> RoutePlanSegment:
    return RoutePlanSegment(
        bps=bps,
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=in_amount,
        out_amount=out_amount,
        amm_key=PUB_C,
        program_id=OFFICIAL_TOKEN_PROGRAM_ID,
        label="Raydium",
        swap_info={
            "ammKey": PUB_C,
            "label": "Raydium",
            "inputMint": input_mint,
            "outputMint": output_mint,
            "inAmount": str(in_amount),
            "outAmount": str(out_amount),
        },
    )


def response() -> JupiterV2BuildResponse:
    return JupiterV2BuildResponse(
        route_plan=(segment(),),
        top_level_input_mint=PUB_A,
        top_level_output_mint=PUB_B,
        last_valid_block_height=1_000,
        current_rooted_block_height=800,
        remaining_height_margin=50,
        blockhash_metadata_sha256=SHA,
    )


def marginfi_account() -> MarginFiTokenAccountEvidence:
    return MarginFiTokenAccountEvidence(
        account_pubkey=PUB_C,
        token_program_id=OFFICIAL_TOKEN_PROGRAM_ID,
        owner_program_id=OFFICIAL_TOKEN_PROGRAM_ID,
        mint=PUB_A,
        expected_mint=PUB_A,
        authority=PUB_B,
        expected_authority=PUB_B,
        raw_account_sha256=SHA,
        rooted_slot=123,
        frozen=False,
        delegate_present=False,
        native_lamports_present=False,
        included_in_final_instruction_accounts=True,
    )


def rent() -> Token2022RentEvidence:
    return Token2022RentEvidence(
        token_program_id=OFFICIAL_TOKEN_2022_PROGRAM_ID,
        base_account_size=165,
        extension_sizes=(2, 34),
        rent_exempt_lamports=2_039_280,
        rent_context_slot=123,
        rent_response_sha256=SHA,
        final_create_account_instruction_sha256=SHA,
    )


def ca() -> CABundleEvidence:
    return CABundleEvidence(
        expected_sha256=SHA,
        reviewed_bytes_sha256=SHA,
        ssl_loaded_bytes_sha256=SHA,
        private_copy_inode_sha256=SHA,
        deployment_image_digest=f"sha256:{SHA}",
        check_then_reopen_path=False,
    )


def evidence() -> MPR02V6Evidence:
    return MPR02V6Evidence(
        schema_version=SCHEMA_VERSION,
        covered_findings=REQUIRED_FINDINGS,
        chain_registry=registry(),
        jupiter_request=request(),
        jupiter_response=response(),
        marginfi_accounts=(marginfi_account(),),
        token2022_rent=rent(),
        ca_bundle=ca(),
    )


def codes(item: MPR02V6Evidence) -> set[str]:
    return {blocker.code for blocker in evaluate_mpr02_v6_protocol_correctness(item).blockers}


def test_valid_v6_protocol_correctness_gate_is_review_ready() -> None:
    report = evaluate_mpr02_v6_protocol_correctness(evidence())
    assert report.state is MPR02V6State.READY_FOR_PHYSICAL_PROTOCOL_CUTOVER
    assert report.protocol_correctness_review_allowed is True
    assert report.operational_paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert len(report.evidence_hash) == 64


def test_requires_all_v6_findings_without_duplicates() -> None:
    missing = replace(evidence(), covered_findings=REQUIRED_FINDINGS[:-1])
    assert "MPR02_V6_MISSING_FINDINGS" in codes(missing)
    dup = replace(evidence(), covered_findings=REQUIRED_FINDINGS + ("IMPL-81",))
    assert "MPR02_V6_DUPLICATE_FINDINGS" in codes(dup)


def test_canonical_program_ids_come_from_independent_registry() -> None:
    wrong = replace(
        registry(),
        token_2022_program_id="TokenzQdBNbLqP5VEhdkAS6EPw1N1qEHxZC6kzNRQdB",
    )
    assert "MPR02_V6_NON_CANONICAL_PROGRAM_ID" in codes(
        replace(evidence(), chain_registry=wrong)
    )
    self_certifying = replace(
        registry(), expected_ids_not_imported_from_modules_under_test=False
    )
    assert "MPR02_V6_SELF_CERTIFYING_PROGRAM_IDS" in codes(
        replace(evidence(), chain_registry=self_certifying)
    )


def test_jupiter_build_request_rejects_invalid_pubkeys_and_filters() -> None:
    bad = replace(
        request(),
        taker="not-a-solana-pubkey",
        slippage_bps=-1,
        dexes=("Raydium",),
        exclude_dexes=("Orca",),
    )
    found = codes(replace(evidence(), jupiter_request=bad))
    assert "MPR02_V6_INVALID_JUPITER_PUBKEY" in found
    assert "MPR02_V6_BAD_SLIPPAGE_BPS" in found
    assert "MPR02_V6_CONFLICTING_DEX_FILTERS" in found


def test_jupiter_v2_is_exact_in_only_and_bounds_request_numbers() -> None:
    bad = replace(
        request(), swap_mode="ExactOut", max_accounts=65, blockhash_slots_to_expiry=301
    )
    found = codes(replace(evidence(), jupiter_request=bad))
    assert "MPR02_V6_SWAP_MODE_NOT_SUPPORTED" in found
    assert "MPR02_V6_BAD_MAX_ACCOUNTS" in found
    assert "MPR02_V6_BAD_BLOCKHASH_SLOTS_TO_EXPIRY" in found


def test_route_plan_must_be_non_empty_complete_and_sum_to_10000_bps() -> None:
    empty = replace(response(), route_plan=())
    assert "MPR02_V6_EMPTY_ROUTE_PLAN" in codes(
        replace(evidence(), jupiter_response=empty)
    )
    bad_segment = replace(segment(bps=-500), swap_info={})
    found = codes(
        replace(evidence(), jupiter_response=replace(response(), route_plan=(bad_segment,)))
    )
    assert "MPR02_V6_BAD_ROUTE_BPS" in found
    assert "MPR02_V6_INCOMPLETE_SWAP_INFO" in found
    assert "MPR02_V6_ROUTE_BPS_SUM_MISMATCH" in found


def test_route_plan_requires_mint_continuity_and_top_level_consistency() -> None:
    first = segment(bps=5_000, input_mint=PUB_A, output_mint=PUB_C)
    second = segment(bps=5_000, input_mint=PUB_A, output_mint=PUB_B)
    found = codes(
        replace(evidence(), jupiter_response=replace(response(), route_plan=(first, second)))
    )
    assert "MPR02_V6_ROUTE_MINT_DISCONTINUITY" in found


def test_last_valid_block_height_must_be_positive_and_not_near_expiry() -> None:
    bad = replace(response(), last_valid_block_height=-1)
    assert "MPR02_V6_BAD_LAST_VALID_BLOCK_HEIGHT" in codes(
        replace(evidence(), jupiter_response=bad)
    )
    near = replace(
        response(),
        last_valid_block_height=810,
        current_rooted_block_height=800,
        remaining_height_margin=50,
    )
    assert "MPR02_V6_BLOCKHASH_TOO_CLOSE_TO_EXPIRY" in codes(
        replace(evidence(), jupiter_response=near)
    )


def test_marginfi_accounts_are_rooted_and_bound_to_final_instruction_set() -> None:
    bad = replace(
        marginfi_account(),
        owner_program_id=OFFICIAL_TOKEN_2022_PROGRAM_ID,
        mint=PUB_B,
        authority=PUB_A,
        frozen=True,
        delegate_present=True,
        included_in_final_instruction_accounts=False,
    )
    found = codes(replace(evidence(), marginfi_accounts=(bad,)))
    assert "MPR02_V6_TOKEN_ACCOUNT_OWNER_MISMATCH" in found
    assert "MPR02_V6_TOKEN_ACCOUNT_MINT_MISMATCH" in found
    assert "MPR02_V6_TOKEN_ACCOUNT_AUTHORITY_MISMATCH" in found
    assert "MPR02_V6_TOKEN_ACCOUNT_FROZEN" in found
    assert "MPR02_V6_TOKEN_ACCOUNT_DELEGATE_PRESENT" in found
    assert "MPR02_V6_ACCOUNT_NOT_IN_FINAL_MESSAGE" in found


def test_token2022_rent_is_extension_aware_not_hardcoded_165() -> None:
    bad = replace(rent(), extension_sizes=())
    assert "MPR02_V6_TOKEN2022_EXTENSION_SIZE_REQUIRED" in codes(
        replace(evidence(), token2022_rent=bad)
    )


def test_ca_bundle_must_load_same_reviewed_private_copy() -> None:
    bad = replace(ca(), ssl_loaded_bytes_sha256=SHA2, check_then_reopen_path=True)
    found = codes(replace(evidence(), ca_bundle=bad))
    assert "MPR02_V6_CA_HASH_LOAD_MISMATCH" in found
    assert "MPR02_V6_CA_CHECK_THEN_REOPEN" in found


def test_v6_gate_cannot_promote_paper_live_or_sender() -> None:
    item = replace(
        evidence(),
        operational_paper_ready_requested=True,
        live_execution_requested=True,
        sender_requested=True,
    )
    found = codes(item)
    assert "MPR02_V6_PAPER_READY_PROMOTION_FORBIDDEN" in found
    assert "MPR02_V6_LIVE_FORBIDDEN" in found
    assert "MPR02_V6_SENDER_FORBIDDEN" in found
