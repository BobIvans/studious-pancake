"""Stream J RentSponsorPlanner offline fixtures: positive and negative.

Everything here is local arithmetic simulation over synthetic pubkeys: no
network, no signing, no account creation, no transaction submission.  The
Slumlord adapter is exercised read-only through its own order validation.
"""

from __future__ import annotations

import dataclasses

import pytest
from solders.pubkey import Pubkey

from src.lending.slumlord import (
    SLUMLORD_INSTRUCTIONS_BLOB,
    SLUMLORD_LIBRARY_BLOB,
    SLUMLORD_PDA,
    SLUMLORD_PROGRAM_ID,
    SLUMLORD_UPSTREAM_COMMIT,
    SLUMLORD_UPSTREAM_REPOSITORY,
    SlumlordReserveState,
    SYSTEM_PROGRAM_ID,
)
from src.planning.rent_sponsor_planner import (
    KNOWN_PROVIDER_SPONSORS,
    LAMPORTS_PER_SIGNATURE,
    MAX_COMPUTE_UNITS,
    MAX_PACKET_BYTES,
    NOTE_FEES_NEVER_SPONSORED,
    NOTE_SPONSOR_TIER_INACTIVE,
    RENT_SPONSOR_CONTRACT_VERSION,
    RENT_SPONSOR_PLANNER_VERSION,
    RENT_SPONSOR_PROVENANCE,
    SYSTEM_ACCOUNT_RENT_EXEMPT_MINIMUM,
    TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM,
    UNSIGNED_BUILDERS_CONTRACT_VERSION,
    EphemeralLifecycleRefs,
    FeeLineKind,
    InstructionRef,
    LamportFlowKind,
    PlanInstructionRef,
    ProviderSponsorshipClaim,
    RentSponsorCapacityStatus,
    RentSponsorPlanRequest,
    RentSponsorPlanStatus,
    RentSponsorPlanner,
    RentSponsorPlannerError,
    RentSponsorRejectionCode,
    RentSponsorTier,
    RouteAccountRequest,
    RouteFeeInputs,
    TokenAccountQualification,
    assert_rent_capacity_never_execution_ready,
    estimate_message_bytes,
    rent_exempt_minimum_lamports,
)
from src.lending.unsigned_builders.contract import BuildStatus

pytestmark = pytest.mark.unit

ATA_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

SLUMLORD_PROGRAM_ID_STR = str(SLUMLORD_PROGRAM_ID)
SLUMLORD_PDA_STR = str(SLUMLORD_PDA)
SYSTEM_PROGRAM_ID_STR = str(SYSTEM_PROGRAM_ID)


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes((seed,)) * 32)


PAYER = str(_pk(1))
TEMP_AT = str(_pk(2))
OUTPUT_AT = str(_pk(3))
REPAY_SOURCE = str(_pk(4))
MINT = str(_pk(5))

# Exact rent arithmetic: the reserve must hold rent_minimum + 1 so the fixed
# upstream Borrow amount (reserve_balance - 1) exactly covers a 165-byte
# SPL token account's rent-exempt minimum.
RESERVE_BALANCE = TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM + 1

PAYER_BALANCE = 50_000_000
EXPECTED_EPHEMERAL_RENT = TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM
EXPECTED_SIGNATURE_FEE = LAMPORTS_PER_SIGNATURE * 2
EXPECTED_PRIORITY_FEE = 10_000
EXPECTED_NET_PAYER = EXPECTED_EPHEMERAL_RENT + EXPECTED_SIGNATURE_FEE + (
    EXPECTED_PRIORITY_FEE
)


def _reserve(
    *,
    lamports: int = RESERVE_BALANCE,
    data: bytes = b"",
    slot: int = 7,
) -> SlumlordReserveState:
    return SlumlordReserveState(
        address=SLUMLORD_PDA,
        owner=SLUMLORD_PROGRAM_ID,
        lamports=lamports,
        data=data,
        slot=slot,
    )


def _lifecycle(
    *,
    drains_to_zero: bool = True,
    closes_in_transaction: bool = True,
    declared_close_refund_lamports: int | None = None,
    close_refund_destination: str = REPAY_SOURCE,
) -> EphemeralLifecycleRefs:
    return EphemeralLifecycleRefs(
        create_ref=InstructionRef(
            label="ata_create_idempotent",
            program_id=ATA_PROGRAM_ID,
            data_len=0,
            account_pubkeys=(TEMP_AT, PAYER, MINT),
        ),
        drain_ref=InstructionRef(
            label="drain_tokens_to_zero",
            program_id=TOKEN_PROGRAM_ID,
            data_len=1,
            account_pubkeys=(TEMP_AT,),
        ),
        close_ref=InstructionRef(
            label="close_token_account",
            program_id=TOKEN_PROGRAM_ID,
            data_len=1,
            account_pubkeys=(TEMP_AT, close_refund_destination),
        ),
        close_refund_destination=close_refund_destination,
        drains_to_zero=drains_to_zero,
        closes_in_transaction=closes_in_transaction,
        declared_close_refund_lamports=declared_close_refund_lamports,
    )


def _positive_request(
    **overrides: object,
) -> RentSponsorPlanRequest:
    kwargs: dict[str, object] = dict(
        payer=PAYER,
        payer_lamports=PAYER_BALANCE,
        payer_evidence_slot=7,
        accounts=(
            RouteAccountRequest(
                address=TEMP_AT,
                data_len=165,
                temporary=True,
                lifecycle=_lifecycle(),
            ),
            RouteAccountRequest(address=OUTPUT_AT, data_len=165),
        ),
        route_body=(
            InstructionRef(
                label="route_swap",
                program_id=str(_pk(9)),
                data_len=100,
                account_pubkeys=(TEMP_AT, OUTPUT_AT),
            ),
        ),
        fee_inputs=RouteFeeInputs(
            required_signatures=2,
            priority_fee_lamports=EXPECTED_PRIORITY_FEE,
            estimated_compute_units=300_000,
        ),
        repayment_source=REPAY_SOURCE,
        repayment_source_lamports=0,
        slumlord_reserve=_reserve(),
    )
    kwargs.update(overrides)
    return RentSponsorPlanRequest(**kwargs)  # type: ignore[arg-type]


# --- Rent arithmetic ---------------------------------------------------------


def test_rent_exempt_minimums_are_exact() -> None:
    assert rent_exempt_minimum_lamports(0) == 890_880
    assert rent_exempt_minimum_lamports(165) == 2_039_280
    assert SYSTEM_ACCOUNT_RENT_EXEMPT_MINIMUM == 890_880
    assert TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM == 2_039_280
    # Exact equivalence with the canonical f64 formula floor((128+n)*3480*2.0).
    for data_len in (0, 1, 10, 128, 165, 256, 1024):
        expected = int((128 + data_len) * 3480 * 2.0)
        assert rent_exempt_minimum_lamports(data_len) == expected
    assert rent_exempt_minimum_lamports(165) > rent_exempt_minimum_lamports(164)


def test_provenance_binds_the_pinned_slumlord_source_and_contract() -> None:
    assert RENT_SPONSOR_PROVENANCE.slumlord_upstream_repository == (
        SLUMLORD_UPSTREAM_REPOSITORY
    )
    assert RENT_SPONSOR_PROVENANCE.slumlord_upstream_commit == (
        "5c5565cb106f5316a66df8ba616034a7810fa850"
    )
    assert RENT_SPONSOR_PROVENANCE.slumlord_upstream_commit == (
        SLUMLORD_UPSTREAM_COMMIT
    )
    assert RENT_SPONSOR_PROVENANCE.slumlord_instructions_blob == (
        SLUMLORD_INSTRUCTIONS_BLOB
    )
    assert RENT_SPONSOR_PROVENANCE.slumlord_library_blob == SLUMLORD_LIBRARY_BLOB
    assert RENT_SPONSOR_PROVENANCE.unsigned_builders_contract_version == (
        UNSIGNED_BUILDERS_CONTRACT_VERSION
    )
    assert RENT_SPONSOR_PLANNER_VERSION == "rent-sponsor-planner.v1"
    assert RENT_SPONSOR_CONTRACT_VERSION == "rent-sponsor.v1"


# --- Positive: ephemeral ATA route financed via Slumlord ----------------------


def test_positive_ephemeral_ata_route_financed_by_slumlord() -> None:
    result = RentSponsorPlanner().plan(_positive_request())

    assert result.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED
    assert result.blockers == ()
    plan = result.plan
    assert plan is not None

    # Account -> tier mapping: temporary account uses Slumlord, final output
    # account uses persistent local funding.
    tiers = {binding.address: binding.tier for binding in plan.account_bindings}
    assert tiers == {
        TEMP_AT: RentSponsorTier.SLUMLORD_EPHEMERAL,
        OUTPUT_AT: RentSponsorTier.PERSISTENT_LOCAL_FUNDING,
    }
    temp_binding = plan.account_bindings[0]
    output_binding = plan.account_bindings[1]
    assert temp_binding.rent_exempt_lamports == TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM
    assert temp_binding.newly_funded_lamports == EXPECTED_EPHEMERAL_RENT
    assert output_binding.rent_exempt_lamports == TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM
    assert output_binding.newly_funded_lamports == TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM

    # Exact rent arithmetic: borrow == close refund == Slumlord repayment ==
    # the 165-byte rent-exempt minimum. The ephemeral account nets to zero.
    flows = {flow.kind: flow for flow in plan.lamport_flows}
    assert flows[LamportFlowKind.RENT_BORROW_IN].lamports == EXPECTED_EPHEMERAL_RENT
    assert flows[LamportFlowKind.RENT_REFUND].lamports == EXPECTED_EPHEMERAL_RENT
    assert flows[LamportFlowKind.SLUMLORD_REPAY_OUT].lamports == (
        EXPECTED_EPHEMERAL_RENT
    )
    assert flows[LamportFlowKind.RENT_BORROW_IN].from_address == SLUMLORD_PDA_STR
    assert flows[LamportFlowKind.RENT_REFUND].to_address == REPAY_SOURCE
    assert flows[LamportFlowKind.SLUMLORD_REPAY_OUT].from_address == REPAY_SOURCE
    assert flows[LamportFlowKind.PERSISTENT_RENT_FUNDING].lamports == (
        TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM
    )
    assert flows[LamportFlowKind.PERSISTENT_RENT_FUNDING].from_address == PAYER
    assert flows[LamportFlowKind.PERSISTENT_RENT_FUNDING].to_address == OUTPUT_AT

    # Fees are separate, persistent lines -- never "free".
    fee_lines = {line.kind: line for line in plan.fee_lines}
    assert fee_lines[FeeLineKind.SIGNATURE_FEE].lamports == EXPECTED_SIGNATURE_FEE
    assert fee_lines[FeeLineKind.PRIORITY_FEE].lamports == EXPECTED_PRIORITY_FEE
    assert all(
        line.covered_by is RentSponsorTier.PERSISTENT_LOCAL_FUNDING
        for line in plan.fee_lines
    )
    assert all(line.note == NOTE_FEES_NEVER_SPONSORED for line in plan.fee_lines)

    # Payer funds persistent rent + fees only; the ephemeral rent nets out.
    assert plan.net_payer_lamports == EXPECTED_NET_PAYER
    assert plan.transient_repayment_buffer_lamports == 0
    assert plan.estimated_compute_units == 300_000
    assert plan.capacity_status is RentSponsorCapacityStatus.NOT_EVALUATED

    # Slumlord adapter's own order certificate: Borrow -> Repay -> CheckRepaid.
    certificate = plan.slumlord_certificate
    assert certificate is not None
    assert certificate.borrow_index == 0
    assert certificate.repay_index == 5
    assert certificate.check_repaid_index == 6
    labels = [ref.label for ref in plan.instruction_sequence]
    assert labels == [
        "slumlord_borrow",
        "ata_create_idempotent",
        "route_swap",
        "drain_tokens_to_zero",
        "close_token_account",
        "slumlord_repay",
        "slumlord_check_repaid",
    ]
    # Drain and close sit strictly between Borrow and Repay.
    assert 0 < labels.index("drain_tokens_to_zero") < labels.index(
        "close_token_account"
    ) < certificate.repay_index

    # Packet estimate stays inside the pinned limit.
    assert plan.estimated_message_bytes <= MAX_PACKET_BYTES
    assert plan.estimated_message_bytes == estimate_message_bytes(
        plan.instruction_sequence, required_signatures=2
    )
    assert NOTE_SPONSOR_TIER_INACTIVE in result.inactive_tier_notes[0]

    # Deterministic canonical fingerprint (aligned with the R-03 contract).
    assert len(plan.build_fingerprint) == 64
    assert (
        RentSponsorPlanner().plan(_positive_request()).plan is not None
        and RentSponsorPlanner().plan(_positive_request()).plan.build_fingerprint
        == plan.build_fingerprint
    )


def test_positive_message_byte_estimate_is_exact_upper_bound() -> None:
    plan = RentSponsorPlanner().plan(_positive_request()).plan
    assert plan is not None
    # Hand-computed conservative layout: signature section (3 + 64*2), header
    # counts (3*3), static key table (3 + 32*8 unique accounts incl. the
    # system program on the Slumlord repay instruction), and per-instruction
    # (3 + 3 + 3*accounts + 3 + data).
    assert plan.estimated_message_bytes == 612
    assert plan.estimated_message_bytes <= MAX_PACKET_BYTES


def test_positive_affordability_boundary_is_inclusive() -> None:
    request = _positive_request(payer_lamports=EXPECTED_NET_PAYER)
    result = RentSponsorPlanner().plan(request)
    assert result.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED
    assert result.plan is not None
    assert result.plan.net_payer_lamports == EXPECTED_NET_PAYER


def test_positive_reuse_tier_wins_for_qualified_existing_account() -> None:
    qualified = TokenAccountQualification(
        observed_lamports=TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM,
        data_len=165,
        owner_program=TOKEN_PROGRAM_ID,
        observed_slot=42,
        evidence_source="pinned-offline-fixture",
        qualified=True,
    )
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=OUTPUT_AT,
                data_len=165,
                exists_today=True,
                qualification=qualified,
            ),
        ),
        slumlord_reserve=None,
        repayment_source=None,
    )
    result = RentSponsorPlanner().plan(request)
    assert result.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED
    plan = result.plan
    assert plan is not None
    assert plan.slumlord_certificate is None
    binding = plan.account_bindings[0]
    assert binding.tier is RentSponsorTier.REUSE_QUALIFIED_EXISTING
    assert binding.newly_funded_lamports == 0
    kinds = {flow.kind for flow in plan.lamport_flows}
    assert LamportFlowKind.RENT_BORROW_IN not in kinds
    assert LamportFlowKind.PERSISTENT_RENT_FUNDING not in kinds
    assert plan.net_payer_lamports == (
        EXPECTED_SIGNATURE_FEE + EXPECTED_PRIORITY_FEE
    )


def test_positive_excess_borrow_is_still_closeable_and_refundable() -> None:
    # Reserve holds more than the minimum: Borrow gives reserve_balance - 1,
    # the temporary account is created with excess lamports, and the close
    # refund returns the full balance so repayment stays exact.
    excess = 777_000
    request = _positive_request(
        slumlord_reserve=_reserve(lamports=RESERVE_BALANCE + excess),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED
    plan = result.plan
    assert plan is not None
    flows = {flow.kind: flow for flow in plan.lamport_flows}
    borrowed = RESERVE_BALANCE + excess - 1
    assert flows[LamportFlowKind.RENT_BORROW_IN].lamports == borrowed
    assert flows[LamportFlowKind.RENT_REFUND].lamports == borrowed
    assert flows[LamportFlowKind.SLUMLORD_REPAY_OUT].lamports == borrowed
    assert flows[LamportFlowKind.RENT_BORROW_IN].lamports >= (
        TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM
    )


def test_positive_payer_as_repayment_source_needs_no_transient_buffer() -> None:
    request = _positive_request(
        repayment_source=PAYER,
        repayment_source_lamports=PAYER_BALANCE,
        accounts=(
            RouteAccountRequest(
                address=TEMP_AT,
                data_len=165,
                temporary=True,
                lifecycle=_lifecycle(close_refund_destination=PAYER),
            ),
            RouteAccountRequest(address=OUTPUT_AT, data_len=165),
        ),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED
    plan = result.plan
    assert plan is not None
    # The close refund covers the repayment exactly, so the transient buffer
    # is zero even when the payer is the repayment source.
    assert plan.transient_repayment_buffer_lamports == 0
    assert plan.net_payer_lamports == EXPECTED_NET_PAYER


# --- Negative: persistent account offered to Slumlord -------------------------


def test_negative_persistent_account_offered_to_slumlord_is_rejected() -> None:
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=OUTPUT_AT,
                data_len=165,
                requested_tier=RentSponsorTier.SLUMLORD_EPHEMERAL,
            ),
        ),
        route_body=(),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,)
    assert result.status is RentSponsorPlanStatus.BLOCKED_POLICY
    assert "must remain open" in result.blockers[0].message


def test_negative_temporary_account_not_emptied_is_rejected() -> None:
    for lifecycle in (
        _lifecycle(drains_to_zero=False),
        _lifecycle(closes_in_transaction=False),
    ):
        request = _positive_request(
            accounts=(
                RouteAccountRequest(
                    address=TEMP_AT,
                    data_len=165,
                    temporary=True,
                    lifecycle=lifecycle,
                ),
                RouteAccountRequest(address=OUTPUT_AT, data_len=165),
            ),
            route_body=(),
        )
        result = RentSponsorPlanner().plan(request)
        assert result.plan is None
        assert result.blocker_codes == (
            RentSponsorRejectionCode.RSP_TEMP_NOT_EMPTYABLE,
        )
        assert result.status is RentSponsorPlanStatus.BLOCKED_POLICY


def test_negative_missing_lifecycle_refs_is_rejected() -> None:
    request = _positive_request(
        accounts=(
            RouteAccountRequest(address=TEMP_AT, data_len=165, temporary=True),
            RouteAccountRequest(address=OUTPUT_AT, data_len=165),
        ),
        route_body=(),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert RentSponsorRejectionCode.RSP_TEMP_NOT_EMPTYABLE in result.blocker_codes


def test_negative_close_refund_to_wrong_destination_is_rejected() -> None:
    request = _positive_request()
    patched = dataclasses.replace(
        request,
        accounts=(
            RouteAccountRequest(
                address=TEMP_AT,
                data_len=165,
                temporary=True,
                lifecycle=_lifecycle(close_refund_destination=str(_pk(8))),
            ),
            RouteAccountRequest(address=OUTPUT_AT, data_len=165),
        ),
    )
    result = RentSponsorPlanner().plan(patched)
    assert result.plan is None
    assert result.blocker_codes == (
        RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
    )


def test_negative_rent_shortfall_when_reserve_cannot_cover_minimum() -> None:
    # reserve_balance - 1 < rent-exempt minimum for a 165-byte token account.
    request = _positive_request(
        slumlord_reserve=_reserve(lamports=TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_RENT_SHORTFALL,)
    assert result.status is RentSponsorPlanStatus.BLOCKED_POLICY


def test_negative_active_slumlord_loan_is_unavailable() -> None:
    active = _reserve(lamports=500_000, data=(1_000_000).to_bytes(8, "little"))
    request = _positive_request(slumlord_reserve=active)
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_SLUMLORD_UNAVAILABLE,)
    assert "BORROW_ALREADY_ACTIVE" in result.blockers[0].message


def test_negative_missing_reserve_observation_is_unavailable() -> None:
    request = _positive_request(slumlord_reserve=None)
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_SLUMLORD_UNAVAILABLE,)


def test_negative_two_temporary_accounts_exceed_slumlord_capacity() -> None:
    second_temp = str(_pk(6))
    accounts = (
        RouteAccountRequest(
            address=TEMP_AT,
            data_len=165,
            temporary=True,
            lifecycle=_lifecycle(),
        ),
        RouteAccountRequest(
            address=second_temp,
            data_len=165,
            temporary=True,
            lifecycle=_lifecycle(),
        ),
        RouteAccountRequest(address=OUTPUT_AT, data_len=165),
    )
    request = _positive_request(accounts=accounts)
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert RentSponsorRejectionCode.RSP_SLUMLORD_CAPACITY in result.blocker_codes


def test_negative_temporary_account_cannot_be_its_own_repayment_source() -> None:
    request = _positive_request(repayment_source=TEMP_AT)
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (
        RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
    )


def test_negative_declared_close_refund_mismatch_is_rejected() -> None:
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=TEMP_AT,
                data_len=165,
                temporary=True,
                lifecycle=_lifecycle(declared_close_refund_lamports=1_000_000),
            ),
            RouteAccountRequest(address=OUTPUT_AT, data_len=165),
        ),
        route_body=(),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (
        RentSponsorRejectionCode.RSP_LIFECYCLE_ARITHMETIC_MISMATCH,
    )


def test_negative_repayment_below_borrow_when_refund_is_short() -> None:
    # A declared short refund would leave the repayment source unable to
    # cover the full Slumlord repayment; the arithmetic-mismatch gate fires
    # before any repayment shortfall can be planned.
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=TEMP_AT,
                data_len=165,
                temporary=True,
                lifecycle=_lifecycle(declared_close_refund_lamports=0),
            ),
            RouteAccountRequest(address=OUTPUT_AT, data_len=165),
        ),
        route_body=(),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (
        RentSponsorRejectionCode.RSP_LIFECYCLE_ARITHMETIC_MISMATCH,
    )


# --- Negative: sponsor tier ----------------------------------------------------


def test_negative_sponsor_claim_without_evidence_is_refused() -> None:
    # No provider sponsor is verified offline today; the tier is inactive.
    assert all(
        not profile.verified_offline
        for profile in KNOWN_PROVIDER_SPONSORS.values()
    )
    request = _positive_request(
        sponsor_claim=ProviderSponsorshipClaim(provider="titan_payer"),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_SPONSOR_UNVERIFIED,)
    assert result.status is RentSponsorPlanStatus.BLOCKED_POLICY
    assert (RentSponsorTier.PROVIDER_SPONSORED, NOTE_SPONSOR_TIER_INACTIVE) in (
        result.inactive_tier_notes
    )


def test_negative_unknown_sponsor_claim_is_refused() -> None:
    request = _positive_request(
        sponsor_claim=ProviderSponsorshipClaim(provider="not_a_sponsor"),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_SPONSOR_UNVERIFIED,)


def test_negative_sponsor_claim_with_fake_blob_is_refused() -> None:
    request = _positive_request(
        sponsor_claim=ProviderSponsorshipClaim(
            provider="0x_sponsor",
            evidence_slot=99,
            evidence_blob_sha256="0" * 64,
        ),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_SPONSOR_UNVERIFIED,)


# --- Negative: reuse tier ------------------------------------------------------


def test_negative_existing_account_without_evidence_is_rejected() -> None:
    request = _positive_request(
        accounts=(
            RouteAccountRequest(address=OUTPUT_AT, data_len=165, exists_today=True),
        ),
        route_body=(),
        slumlord_reserve=None,
        repayment_source=None,
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_REUSE_UNQUALIFIED,)
    assert result.status is RentSponsorPlanStatus.BLOCKED_POLICY


def test_negative_unqualified_evidence_flag_is_rejected() -> None:
    evidence = TokenAccountQualification(
        observed_lamports=TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM,
        data_len=165,
        owner_program=TOKEN_PROGRAM_ID,
        observed_slot=42,
        evidence_source="pinned-offline-fixture",
        qualified=False,
    )
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=OUTPUT_AT,
                data_len=165,
                exists_today=True,
                qualification=evidence,
            ),
        ),
        route_body=(),
        slumlord_reserve=None,
        repayment_source=None,
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_REUSE_UNQUALIFIED,)


def test_negative_evidence_below_rent_minimum_is_rejected() -> None:
    evidence = TokenAccountQualification(
        observed_lamports=TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM - 1,
        data_len=165,
        owner_program=TOKEN_PROGRAM_ID,
        observed_slot=42,
        evidence_source="pinned-offline-fixture",
        qualified=True,
    )
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=OUTPUT_AT,
                data_len=165,
                exists_today=True,
                qualification=evidence,
            ),
        ),
        route_body=(),
        slumlord_reserve=None,
        repayment_source=None,
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_REUSE_UNQUALIFIED,)


def test_negative_requested_tier_mismatch_is_rejected() -> None:
    request = _positive_request(
        accounts=(
            RouteAccountRequest(
                address=OUTPUT_AT,
                data_len=165,
                requested_tier=RentSponsorTier.REUSE_QUALIFIED_EXISTING,
            ),
        ),
        route_body=(),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,)


# --- Negative: route economics -------------------------------------------------


def test_negative_route_unaffordable_is_rejected() -> None:
    request = _positive_request(payer_lamports=EXPECTED_NET_PAYER - 1)
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_ROUTE_UNAFFORDABLE,)
    assert result.status is RentSponsorPlanStatus.BLOCKED_ECONOMICS
    assert str(EXPECTED_NET_PAYER - 1) in result.blockers[0].message


def test_negative_message_bytes_exceeded_is_rejected() -> None:
    huge = InstructionRef(
        label="oversized_route_step",
        program_id=str(_pk(9)),
        data_len=1400,
        account_pubkeys=(TEMP_AT, OUTPUT_AT),
    )
    request = _positive_request(route_body=(huge,))
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (
        RentSponsorRejectionCode.RSP_MESSAGE_BYTES_EXCEEDED,
    )
    assert result.status is RentSponsorPlanStatus.BLOCKED_ECONOMICS


def test_negative_compute_units_over_budget_fail_closed_at_input() -> None:
    with pytest.raises(RentSponsorPlannerError) as excinfo:
        RouteFeeInputs(
            required_signatures=1,
            priority_fee_lamports=0,
            estimated_compute_units=MAX_COMPUTE_UNITS + 1,
        )
    assert excinfo.value.rejections[0].code is (
        RentSponsorRejectionCode.RSP_INVALID_INPUT
    )


def test_negative_temporary_account_that_exists_today_fails_construction() -> None:
    with pytest.raises(RentSponsorPlannerError) as excinfo:
        RouteAccountRequest(
            address=TEMP_AT,
            data_len=165,
            temporary=True,
            exists_today=True,
            lifecycle=_lifecycle(),
        )
    assert excinfo.value.rejections[0].code is (
        RentSponsorRejectionCode.RSP_INVALID_INPUT
    )


def test_negative_route_body_cannot_carry_slumlord_instructions() -> None:
    # Fail-closed at input: the planner owns Slumlord placement exclusively.
    with pytest.raises(RentSponsorPlannerError) as excinfo:
        _positive_request(
            route_body=(
                InstructionRef(
                    label="fake_borrow",
                    program_id=SLUMLORD_PROGRAM_ID_STR,
                    data_len=1,
                    account_pubkeys=(TEMP_AT,),
                ),
            ),
        )
    assert excinfo.value.rejections[0].code is (
        RentSponsorRejectionCode.RSP_INVALID_INPUT
    )


def test_negative_reserved_label_prefix_is_rejected() -> None:
    request = _positive_request(
        route_body=(
            InstructionRef(
                label="slumlord_borrow_impersonation",
                program_id=str(_pk(9)),
                data_len=0,
                account_pubkeys=(TEMP_AT, OUTPUT_AT),
            ),
        ),
    )
    result = RentSponsorPlanner().plan(request)
    assert result.plan is None
    assert result.blocker_codes == (RentSponsorRejectionCode.RSP_INVALID_INPUT,)


# --- Fail-closed result/plan invariants ----------------------------------------


def test_blocked_results_never_carry_plans_and_built_results_never_blockers() -> None:
    blocked = RentSponsorPlanner().plan(
        _positive_request(payer_lamports=0, slumlord_reserve=None)
    )
    assert blocked.plan is None
    assert blocked.blockers
    built = RentSponsorPlanner().plan(_positive_request())
    assert built.blockers == ()
    assert built.plan is not None
    assert built.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED
    with pytest.raises(RentSponsorPlannerError):
        dataclasses.replace(
            built, blockers=blocked.blockers
        )
    with pytest.raises(RentSponsorPlannerError):
        dataclasses.replace(blocked, plan=built.plan)


def test_built_plan_is_unsigned_and_has_no_execution_payload() -> None:
    plan = RentSponsorPlanner().plan(_positive_request()).plan
    assert plan is not None
    field_names = {f.name for f in dataclasses.fields(plan)}
    for forbidden in ("sign", "send", "submit", "signed_tx", "serialized_tx"):
        assert not any(forbidden in name for name in field_names)
    # Instruction references carry shapes only, never executable payloads.
    for ref in plan.instruction_sequence:
        assert isinstance(ref.data_len, int)
        assert not hasattr(ref, "data_hex")
        assert not hasattr(ref, "data")
    borrow_ref = plan.instruction_sequence[0]
    assert borrow_ref.program_id == SLUMLORD_PROGRAM_ID_STR
    assert borrow_ref.data_len == 1
    assert borrow_ref.account_pubkeys == (
        SLUMLORD_PDA_STR,
        TEMP_AT,
        "Sysvar1nstructions1111111111111111111111111",
    )
    repay_ref = plan.instruction_sequence[5]
    assert repay_ref.account_pubkeys == (
        SLUMLORD_PDA_STR,
        REPAY_SOURCE,
        SYSTEM_PROGRAM_ID_STR,
    )


def test_capacity_status_never_admits_execution() -> None:
    assert_rent_capacity_never_execution_ready()
    members = {member.value for member in RentSponsorCapacityStatus}
    assert "not_evaluated" in members
    for forbidden in ("execution_ready", "execution-ready", "live_admitted"):
        assert forbidden not in members
    # Parity with the R-03 contract: build status stays offline-only too.
    assert BuildStatus.BUILT_OFFLINE_UNQUALIFIED.value == "built_offline_unqualified"


def test_estimator_is_monotone_and_counts_unique_accounts_once() -> None:
    base = (
        PlanInstructionRef(
            label="a",
            program_id=str(_pk(9)),
            data_len=10,
            account_pubkeys=(PAYER, OUTPUT_AT),
        ),
    )
    duplicate = PlanInstructionRef(
        label="b",
        program_id=str(_pk(9)),
        data_len=10,
        account_pubkeys=(PAYER, OUTPUT_AT),
    )
    one = estimate_message_bytes(base, required_signatures=1)
    two = estimate_message_bytes(base + (duplicate,), required_signatures=1)
    # Hand-computed: one instruction = 3 + 64 + 9 + 3 + 32*2 + (3+3+3*2+3+10)
    # = 168 bytes; a second instruction reusing the same accounts adds only
    # its own per-instruction bytes (25), never a second key table.
    assert one == 168
    assert two == 193
    assert two - one == 25
