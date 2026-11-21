"""R03-D Project 0 conditional builder tests: typed BLOCKED outcomes only."""

from __future__ import annotations

import pytest

from src.lending.unsigned_builders.contract import (
    BuildStatus,
    ConformanceErrorCode,
    ConformanceViolation,
    SequenceItem,
    UnsignedBuilderError,
)
from src.lending.unsigned_builders.project0_builder import (
    PROJECT0_BUILDER_SOURCE_PIN,
    Project0BracketCertificate,
    Project0BuildOutcome,
    build_project0_flashloan_plan,
)
from tests.r03_support import SYNTHETIC, load_fixture

pytestmark = pytest.mark.unit


def test_without_existing_account_is_typed_operator_account_blocked() -> None:
    fixture = load_fixture("project0_golden.json")
    outcome = build_project0_flashloan_plan(existing_marginfi_account=None)
    assert outcome.build_status == fixture["without_account_status"]
    assert outcome.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
    assert outcome.blockers[0].code.value == fixture["without_account_blocker_code"]
    assert (
        outcome.blockers[0].code is ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED
    )
    assert outcome.bracket_certificate is None
    assert outcome.existing_account_used is False


def test_blank_account_is_also_blocked() -> None:
    for blank in ("", "   "):
        outcome = build_project0_flashloan_plan(existing_marginfi_account=blank)
        assert outcome.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
        assert (
            outcome.blockers[0].code
            is ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED
        )


def test_with_supplied_existing_account_yields_pinned_bracket_certificate() -> None:
    fixture = load_fixture("project0_golden.json")
    outcome = build_project0_flashloan_plan(
        existing_marginfi_account=SYNTHETIC["p0_account"],
        route_instructions=[
            SequenceItem(
                program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                data_hex="01020304",
            )
        ],
    )
    certificate = outcome.bracket_certificate
    assert certificate is not None
    assert certificate.begin_index == fixture["expected_begin_index"]
    assert certificate.end_index == fixture["expected_end_index"]
    assert certificate.route_instruction_count == fixture["route_instruction_count"]
    assert (
        certificate.start_flashloan_discriminator_hex
        == fixture["expected_start_flashloan_discriminator_hex"]
    )
    assert (
        certificate.end_flashloan_discriminator_hex
        == fixture["expected_end_flashloan_discriminator_hex"]
    )
    # Even with an account supplied, the generated instruction ABI is absent:
    # the outcome stays typed-BLOCKED with no fabricated instruction bytes.
    assert outcome.build_status == fixture["with_account_status"]
    assert outcome.build_status is BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI
    assert outcome.blockers[0].code.value == fixture["with_account_blocker_code"]


def test_end_index_math_follows_pinned_make_flash_loan_tx() -> None:
    account = SYNTHETIC["p0_account"]
    empty = build_project0_flashloan_plan(existing_marginfi_account=account)
    assert empty.bracket_certificate.end_index == 1
    two = build_project0_flashloan_plan(
        existing_marginfi_account=account,
        route_instructions=[
            SequenceItem(program_id="11111111111111111111111111111111", data_hex="00"),
            SequenceItem(program_id="11111111111111111111111111111111", data_hex="01"),
        ],
    )
    assert two.bracket_certificate.end_index == 3


def test_outcome_can_never_claim_built() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        Project0BuildOutcome(
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            blockers=(),
            bracket_certificate=None,
            source_pin=PROJECT0_BUILDER_SOURCE_PIN,
            existing_account_used=False,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE
    )


def test_blocker_is_mandatory_on_outcome() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        Project0BuildOutcome(
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
            blockers=(),
            bracket_certificate=None,
            source_pin=PROJECT0_BUILDER_SOURCE_PIN,
            existing_account_used=False,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT


def test_bracket_certificate_requires_bound_account() -> None:
    outcome = build_project0_flashloan_plan(existing_marginfi_account=None)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        Project0BuildOutcome(
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
            blockers=outcome.blockers,
            bracket_certificate=Project0BracketCertificate(
                begin_index=0,
                route_instruction_count=0,
                end_index=1,
                pinned_end_index=1,
                start_flashloan_discriminator_hex="ab" * 8,
                end_flashloan_discriminator_hex="cd" * 8,
            ),
            source_pin=PROJECT0_BUILDER_SOURCE_PIN,
            existing_account_used=False,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE
    )


def test_invalid_supplied_account_fails_closed() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_project0_flashloan_plan(existing_marginfi_account="not-a-pubkey")
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT


def test_end_index_math_violation_fails_closed() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        Project0BracketCertificate(
            begin_index=0,
            route_instruction_count=2,
            end_index=2,
            pinned_end_index=2,
            start_flashloan_discriminator_hex="ab" * 8,
            end_flashloan_discriminator_hex="cd" * 8,
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_ORDER_INVALID
    )


def test_project0_source_pin_matches_pinned_kit() -> None:
    fixture = load_fixture("project0_golden.json")
    assert PROJECT0_BUILDER_SOURCE_PIN.verified_offline is True
    assert PROJECT0_BUILDER_SOURCE_PIN.commit == fixture["source_pin"]["commit"]
    assert PROJECT0_BUILDER_SOURCE_PIN.version == fixture["source_pin"]["git_version"]


def test_typed_blocker_codes_are_frozen_strings() -> None:
    outcome = build_project0_flashloan_plan(existing_marginfi_account=None)
    assert outcome.blockers[0].code.value == "R03_OPERATOR_ACCOUNT_INPUT_REQUIRED"


# ---------------------------------------------------------------------------
# N07 deployment rebind: 0.1.12 IDL-pinned metas and start-instruction bytes.
# ---------------------------------------------------------------------------


def test_n07_start_flashloan_data_encoding_is_pinned() -> None:
    from src.lending.unsigned_builders.project0_builder import (
        encode_p0_start_flashloan_data,
    )

    fixture = load_fixture("project0_golden.json")
    data = encode_p0_start_flashloan_data(2)
    assert data == bytes.fromhex(
        fixture["expected_start_flashloan_discriminator_hex"]
    ) + (2).to_bytes(8, "little")
    assert len(data) == 16
    with pytest.raises(UnsignedBuilderError):
        encode_p0_start_flashloan_data(-1)
    with pytest.raises(UnsignedBuilderError):
        encode_p0_start_flashloan_data("2")  # type: ignore[arg-type]


def test_n07_account_metas_match_vendored_0_1_12_idl() -> None:
    from src.lending.unsigned_builders.project0_builder import (
        INSTRUCTIONS_SYSVAR_ADDRESS,
        P0_END_FLASHLOAN_ACCOUNT_METAS,
        P0_END_FLASHLOAN_REBIND_NOTE,
        P0_START_FLASHLOAN_ACCOUNT_METAS,
        Project0PinnedStartInstruction,
    )

    # Pin-lock: metas come from the vendored 0.1.12 IDL.
    assert P0_START_FLASHLOAN_ACCOUNT_METAS == (
        ("marginfi_account", "writable"),
        ("authority", "signer"),
        ("instructions_sysvar", "readonly"),
    )
    # Rebind finding: 0.1.12 adds the readonly `group` account to end_flashloan.
    assert P0_END_FLASHLOAN_ACCOUNT_METAS == (
        ("marginfi_account", "writable"),
        ("group", "readonly"),
        ("authority", "signer"),
    )
    assert "computeHealthAccountMetas" in P0_END_FLASHLOAN_REBIND_NOTE
    assert INSTRUCTIONS_SYSVAR_ADDRESS.endswith("1111111111111111111111111")

    with pytest.raises(UnsignedBuilderError, match="instructions sysvar"):
        Project0PinnedStartInstruction(
            program_id=SYNTHETIC["p0_account"],
            marginfi_account=SYNTHETIC["p0_account"],
            authority=SYNTHETIC["p0_account"],
            instructions_sysvar="WRONG",
            end_index=1,
            data_hex="00",
            metas=P0_START_FLASHLOAN_ACCOUNT_METAS,
        )
    with pytest.raises(UnsignedBuilderError, match="metas"):
        Project0PinnedStartInstruction(
            program_id=SYNTHETIC["p0_account"],
            marginfi_account=SYNTHETIC["p0_account"],
            authority=SYNTHETIC["p0_account"],
            instructions_sysvar=INSTRUCTIONS_SYSVAR_ADDRESS,
            end_index=1,
            data_hex="00",
            metas=(("marginfi_account", "readonly"),),
        )


def test_n07_pinned_start_instruction_requires_authority_and_is_recorded() -> None:
    account = SYNTHETIC["p0_account"]
    without_authority = build_project0_flashloan_plan(existing_marginfi_account=account)
    assert without_authority.pinned_start_instruction is None
    assert without_authority.bracket_certificate is not None
    assert (
        without_authority.build_status is BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI
    )

    outcome = build_project0_flashloan_plan(
        existing_marginfi_account=account,
        authority=account,
        route_instructions=[
            SequenceItem(
                program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                data_hex="01020304",
            )
        ],
    )
    pinned = outcome.pinned_start_instruction
    assert pinned is not None
    assert pinned.marginfi_account == account
    assert pinned.authority == account
    assert pinned.end_index == 2
    from src.lending.unsigned_builders.project0_builder import (
        P0_START_FLASHLOAN_ACCOUNT_METAS,
        encode_p0_start_flashloan_data,
    )

    assert pinned.data_hex == encode_p0_start_flashloan_data(2).hex()
    assert pinned.metas == P0_START_FLASHLOAN_ACCOUNT_METAS
    # The outcome still stays typed-BLOCKED (end instruction incomplete).
    assert outcome.build_status is BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI
