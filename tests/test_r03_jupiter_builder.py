"""R03-A Jupiter Lend unsigned builder tests: golden bytes + fail-closed negatives."""

from __future__ import annotations

import pytest
from solders.pubkey import Pubkey

from src.lending.jupiter_lend import (
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JupiterLendAdapterError,
    JupiterLendRejectionCode,
)
from src.lending.unsigned_builders.contract import (
    BuildStatus,
    CapacityStatus,
    ConformanceErrorCode,
    SequenceItem,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    UnsignedBuilderError,
    finalize_unsigned_solana_plan,
)
from src.lending.unsigned_builders.jupiter_builder import (
    JUPITER_BORROW_DISCRIMINATOR_HEX,
    JUPITER_BUILDER_CHAIN,
    JUPITER_BUILDER_PROVIDER,
    JUPITER_BUILDER_SOURCE_PIN,
    JUPITER_PAYBACK_DISCRIMINATOR_HEX,
    assemble_jupiter_lend_message,
    build_jupiter_lend_borrow_plan,
    build_jupiter_lend_repay_plan,
    jupiter_state_fingerprint,
)
from tests.r03_support import JUPITER_AMOUNT, SYNTHETIC, jupiter_accounts, load_fixture

pytestmark = pytest.mark.unit

PROGRAM_ID = str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID)


def _built_pair(state_fingerprint: str | None = None):
    accounts = jupiter_accounts()
    fingerprint = state_fingerprint or jupiter_state_fingerprint(accounts)
    borrow = build_jupiter_lend_borrow_plan(
        accounts=accounts,
        amount=JUPITER_AMOUNT,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    repay = build_jupiter_lend_repay_plan(
        accounts=accounts,
        borrow_plan=borrow,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    return accounts, fingerprint, borrow, repay


def test_golden_borrow_and_repay_bytes_match_pinned_idl() -> None:
    fixture = load_fixture("jupiter_lend_golden.json")
    _, _, borrow, repay = _built_pair()
    assert fixture["program_id"] == PROGRAM_ID
    assert fixture["borrow_discriminator_hex"] == JUPITER_BORROW_DISCRIMINATOR_HEX
    assert fixture["payback_discriminator_hex"] == JUPITER_PAYBACK_DISCRIMINATOR_HEX
    assert borrow.bookend.data_hex == fixture["expected_borrow_data_hex"]
    assert repay.bookend.data_hex == fixture["expected_repay_data_hex"]
    assert bytes.fromhex(borrow.bookend.data_hex)[8:] == JUPITER_AMOUNT.to_bytes(
        8, "little"
    )
    assert len(borrow.bookend.account_metas) == 14


def test_golden_account_metas_order_and_flags() -> None:
    fixture = load_fixture("jupiter_lend_golden.json")
    _, _, borrow, _ = _built_pair()
    expected = fixture["expected_account_metas"]
    actual = [
        {"pubkey": m.pubkey, "is_signer": m.is_signer, "is_writable": m.is_writable}
        for m in borrow.bookend.account_metas
    ]
    assert actual == expected
    assert actual[0]["pubkey"] == SYNTHETIC["signer"]
    assert actual[0]["is_signer"] is True
    assert actual[1]["pubkey"] == fixture["accounts"]["flashloan_admin"]


def test_golden_assembled_sequence_fingerprint_replays_deterministically() -> None:
    fixture = load_fixture("jupiter_lend_golden.json")
    accounts = jupiter_accounts()
    fingerprint = jupiter_state_fingerprint(accounts)
    borrow = build_jupiter_lend_borrow_plan(
        accounts=accounts,
        amount=JUPITER_AMOUNT,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    repay = build_jupiter_lend_repay_plan(
        accounts=accounts,
        borrow_plan=borrow,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    prepend = SequenceItem(program_id="11111111111111111111111111111111", data_hex="00")
    route = SequenceItem(program_id=SYNTHETIC["generic_route"], data_hex="deadbeef")
    final = assemble_jupiter_lend_message(
        borrow_plan=borrow,
        repay_plan=repay,
        before_borrow=[prepend],
        route_between=[route],
    )
    assert fixture["expected_sequence"] == [
        {"program_id": i.program_id, "data_hex": i.data_hex} for i in final.sequence
    ]
    assert (
        final.certificate.borrow_index
        == fixture["expected_certificate"]["borrow_index"]
    )
    assert (
        final.certificate.repay_index == fixture["expected_certificate"]["repay_index"]
    )
    assert final.sequence_fingerprint == fixture["expected_sequence_fingerprint"]
    replay = assemble_jupiter_lend_message(
        borrow_plan=borrow,
        repay_plan=repay,
        before_borrow=[prepend],
        route_between=[route],
    )
    assert replay.sequence_fingerprint == final.sequence_fingerprint


def test_built_status_is_offline_unqualified_and_capacity_never_admitted() -> None:
    _, _, borrow, repay = _built_pair()
    assert borrow.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert repay.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert borrow.capacity_status is CapacityStatus.NOT_EVALUATED
    assert repay.capacity_status is CapacityStatus.NOT_EVALUATED
    assert borrow.blockers == ()
    assert repay.required_repayment_base_units == JUPITER_AMOUNT


def test_unconfirmed_token_account_is_needs_account_setup_blocked() -> None:
    accounts = jupiter_accounts()
    fingerprint = jupiter_state_fingerprint(accounts)
    borrow = build_jupiter_lend_borrow_plan(
        accounts=accounts,
        amount=JUPITER_AMOUNT,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=False,
    )
    assert borrow.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
    assert borrow.bookend is None
    assert borrow.blockers[0].code is ConformanceErrorCode.NEEDS_ACCOUNT_SETUP
    built_borrow = build_jupiter_lend_borrow_plan(
        accounts=accounts,
        amount=JUPITER_AMOUNT,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    repay = build_jupiter_lend_repay_plan(
        accounts=accounts,
        borrow_plan=built_borrow,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=False,
    )
    assert repay.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
    assert repay.blockers[0].code is ConformanceErrorCode.NEEDS_ACCOUNT_SETUP
    assert repay.bookend is None


def test_wrong_admin_pda_is_rejected_by_pinned_layout() -> None:
    from src.lending.jupiter_lend import JUPITER_FLASHLOAN_ADMIN_PDA

    wrong_admin = str(Pubkey.from_bytes(bytes(range(32))))
    assert wrong_admin != str(JUPITER_FLASHLOAN_ADMIN_PDA)
    with pytest.raises(JupiterLendAdapterError) as excinfo:
        jupiter_accounts(flashloan_admin=wrong_admin)
    assert excinfo.value.code is JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT


def test_zero_amount_is_rejected_by_pinned_abi() -> None:
    accounts = jupiter_accounts()
    with pytest.raises(JupiterLendAdapterError):
        build_jupiter_lend_borrow_plan(
            accounts=accounts,
            amount=0,
            state_fingerprint=jupiter_state_fingerprint(accounts),
            borrow_token_account_confirmed=True,
        )


def test_repay_before_borrow_order_fails_closed() -> None:
    _, _, borrow, repay = _built_pair()
    sequence = [repay.bookend.to_sequence_item(), borrow.bookend.to_sequence_item()]
    with pytest.raises(UnsignedBuilderError) as excinfo:
        finalize_unsigned_solana_plan(
            provider=JUPITER_BUILDER_PROVIDER,
            program_id=PROGRAM_ID,
            borrow_plan=borrow,
            repay_plan=repay,
            sequence=sequence,
            borrow_discriminator_hex=JUPITER_BORROW_DISCRIMINATOR_HEX,
            repay_discriminator_hex=JUPITER_PAYBACK_DISCRIMINATOR_HEX,
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_ORDER_INVALID
    )


def test_duplicate_borrow_bookend_fails_closed() -> None:
    _, _, borrow, repay = _built_pair()
    borrow_item = borrow.bookend.to_sequence_item()
    sequence = [borrow_item, borrow_item, repay.bookend.to_sequence_item()]
    with pytest.raises(UnsignedBuilderError) as excinfo:
        finalize_unsigned_solana_plan(
            provider=JUPITER_BUILDER_PROVIDER,
            program_id=PROGRAM_ID,
            borrow_plan=borrow,
            repay_plan=repay,
            sequence=sequence,
            borrow_discriminator_hex=JUPITER_BORROW_DISCRIMINATOR_HEX,
            repay_discriminator_hex=JUPITER_PAYBACK_DISCRIMINATOR_HEX,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_MISSING


def test_missing_repay_bookend_fails_closed() -> None:
    _, _, borrow, _ = _built_pair()
    from src.lending.unsigned_builders.contract import check_bookend_sequence

    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_bookend_sequence(
            provider=JUPITER_BUILDER_PROVIDER,
            program_id=PROGRAM_ID,
            sequence=[borrow.bookend.to_sequence_item()],
            borrow_discriminator_hex=JUPITER_BORROW_DISCRIMINATOR_HEX,
            repay_discriminator_hex=JUPITER_PAYBACK_DISCRIMINATOR_HEX,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_MISSING


def test_wrong_program_id_bookend_fails_closed() -> None:
    _, _, borrow, repay = _built_pair()
    impostor_borrow = SequenceItem(
        program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        data_hex=JUPITER_BORROW_DISCRIMINATOR_HEX + (1).to_bytes(8, "little").hex(),
    )
    sequence = [impostor_borrow, repay.bookend.to_sequence_item()]
    with pytest.raises(UnsignedBuilderError) as excinfo:
        finalize_unsigned_solana_plan(
            provider=JUPITER_BUILDER_PROVIDER,
            program_id=PROGRAM_ID,
            borrow_plan=borrow,
            repay_plan=repay,
            sequence=sequence,
            borrow_discriminator_hex=JUPITER_BORROW_DISCRIMINATOR_HEX,
            repay_discriminator_hex=JUPITER_PAYBACK_DISCRIMINATOR_HEX,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PROGRAM_ID_MISMATCH


def test_account_order_mismatch_between_borrow_and_repay() -> None:
    accounts = jupiter_accounts()
    different_signer_accounts = jupiter_accounts(signer=SYNTHETIC["generic_a"])
    fingerprint = jupiter_state_fingerprint(accounts)
    borrow = build_jupiter_lend_borrow_plan(
        accounts=accounts,
        amount=JUPITER_AMOUNT,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_jupiter_lend_repay_plan(
            accounts=different_signer_accounts,
            borrow_plan=borrow,
            state_fingerprint=fingerprint,
            borrow_token_account_confirmed=True,
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.ACCOUNT_ORDER_MISMATCH
    )


def test_state_fingerprint_binds_the_account_binding() -> None:
    accounts = jupiter_accounts()
    other = jupiter_accounts(signer=SYNTHETIC["generic_b"])
    assert jupiter_state_fingerprint(accounts) != jupiter_state_fingerprint(other)
    fingerprint = jupiter_state_fingerprint(accounts)
    build_jupiter_lend_borrow_plan(
        accounts=accounts,
        amount=JUPITER_AMOUNT,
        state_fingerprint=fingerprint,
        borrow_token_account_confirmed=True,
    )
    with pytest.raises(UnsignedBuilderError):
        build_jupiter_lend_borrow_plan(
            accounts=accounts,
            amount=JUPITER_AMOUNT,
            state_fingerprint="not-a-sha256",
            borrow_token_account_confirmed=True,
        )


def test_evidence_binding_fails_closed_on_provider_mismatch() -> None:
    from src.lending.financing import FinancingEvidence

    accounts = jupiter_accounts()
    fingerprint = jupiter_state_fingerprint(accounts)
    evidence = FinancingEvidence(
        lender_id="other-lender",
        program_id=PROGRAM_ID,
        deployment_generation=1,
        evidence_sha256="a" * 64,
        decoder_identity="decoder",
        decoder_generation=1,
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_jupiter_lend_borrow_plan(
            accounts=accounts,
            amount=JUPITER_AMOUNT,
            state_fingerprint=fingerprint,
            borrow_token_account_confirmed=True,
            evidence=evidence,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PROGRAM_ID_MISMATCH


def test_builder_source_pin_matches_pinned_upstream() -> None:
    fixture = load_fixture("jupiter_lend_golden.json")
    assert JUPITER_BUILDER_SOURCE_PIN.verified_offline is True
    assert JUPITER_BUILDER_SOURCE_PIN.commit == fixture["source_pin"]["commit"]
    assert JUPITER_BUILDER_SOURCE_PIN.blob_sha1s == (
        fixture["source_pin"]["idl_blob_sha1"],
    )
    assert JUPITER_BUILDER_CHAIN == "solana"
    assert JUPITER_BUILDER_PROVIDER == "jupiter-lend"
