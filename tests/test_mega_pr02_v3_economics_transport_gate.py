from __future__ import annotations

from dataclasses import replace

from src.mega_pr02_v3_economics_transport_gate import (
    REQUIRED_FINDINGS,
    REQUIRED_MONETARY_FUZZ_CASES,
    REQUIRED_PROVIDER_FAILURE_CASES,
    CanonicalProviderHttpEvidence,
    IntegerEconomicsEvidence,
    MegaPR02V3Evidence,
    MegaPR02V3State,
    blockers_by_code,
    evaluate_mega_pr02_v3_evidence,
)


HASH = "a" * 64


def valid_evidence() -> MegaPR02V3Evidence:
    return MegaPR02V3Evidence(
        merged_mega_pr02_gate_hash=HASH,
        findings_covered=REQUIRED_FINDINGS,
        economics=IntegerEconomicsEvidence(
            immutable_economics_object_hash=HASH,
            opportunity_profit_lamports=1000,
            admission_profit_lamports=1000,
            terminal_profit_lamports=1000,
            integer_denominated_only=True,
            float_inputs_rejected=True,
            metadata_profit_truth_absent=True,
            expected_profit_bound_to_object=True,
            min_out_bound_to_object=True,
            repayment_bound_to_protocol_evidence=True,
            protocol_fee_bound_to_protocol_evidence=True,
            silent_principal_default_forbidden=True,
            monetary_fuzz_cases=REQUIRED_MONETARY_FUZZ_CASES,
        ),
        provider_http=CanonicalProviderHttpEvidence(
            canonical_transport_hash=HASH,
            host_allowlist_hash=HASH,
            retry_policy_hash=HASH,
            all_provider_clients_use_canonical_transport=True,
            streamed_response_size_limit_bytes=1_048_576,
            content_type_limits_enforced=True,
            schema_limits_enforced_before_business_logic=True,
            method_aware_idempotent_retry_policy=True,
            retry_after_and_jitter_proven=True,
            non_idempotent_requests_not_retried=True,
            deadline_budget_enforced=True,
            oversized_response_fails_closed_before_decode=True,
            malformed_response_fails_closed=True,
            slow_response_fails_closed=True,
            no_oom_or_duplicate_side_effects=True,
            provider_failure_cases=REQUIRED_PROVIDER_FAILURE_CASES,
        ),
    )


def test_valid_v3_evidence_is_ready_but_paper_only() -> None:
    report = evaluate_mega_pr02_v3_evidence(valid_evidence())

    assert report.state is MegaPR02V3State.READY
    assert report.blockers == ()
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.private_key_material_allowed is False


def test_impl40_and_impl41_are_required() -> None:
    evidence = replace(valid_evidence(), findings_covered=("IMPL-40",))

    report = evaluate_mega_pr02_v3_evidence(evidence)

    blocker = blockers_by_code(report)["MEGA_PR02_V3_FINDINGS_INCOMPLETE"]
    assert "IMPL-41" in blocker.message


def test_float_and_duplicate_profit_truth_fail_closed() -> None:
    economics = replace(
        valid_evidence().economics,
        float_inputs_rejected=False,
        admission_profit_lamports=999,
    )
    evidence = replace(valid_evidence(), economics=economics)

    report = evaluate_mega_pr02_v3_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_V3_FLOAT_ACCEPTED"]
    assert codes["MEGA_PR02_V3_DUPLICATE_PROFIT_TRUTH"]


def test_repayment_and_protocol_fee_must_be_protocol_bound() -> None:
    economics = replace(
        valid_evidence().economics,
        repayment_bound_to_protocol_evidence=False,
        protocol_fee_bound_to_protocol_evidence=False,
        silent_principal_default_forbidden=False,
    )
    evidence = replace(valid_evidence(), economics=economics)

    report = evaluate_mega_pr02_v3_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_V3_REPAYMENT_UNBOUND"]
    assert codes["MEGA_PR02_V3_PROTOCOL_FEE_UNBOUND"]
    assert codes["MEGA_PR02_V3_SILENT_PRINCIPAL_DEFAULT"]


def test_provider_transport_must_be_canonical_and_bounded() -> None:
    provider_http = replace(
        valid_evidence().provider_http,
        all_provider_clients_use_canonical_transport=False,
        streamed_response_size_limit_bytes=0,
    )
    evidence = replace(valid_evidence(), provider_http=provider_http)

    report = evaluate_mega_pr02_v3_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_V3_TRANSPORT_FRAGMENTED"]
    assert codes["MEGA_PR02_V3_RESPONSE_LIMIT_INVALID"]


def test_provider_oversize_malformed_and_slow_fail_closed() -> None:
    provider_http = replace(
        valid_evidence().provider_http,
        oversized_response_fails_closed_before_decode=False,
        malformed_response_fails_closed=False,
        slow_response_fails_closed=False,
        provider_failure_cases=("oversized_response",),
    )
    evidence = replace(valid_evidence(), provider_http=provider_http)

    report = evaluate_mega_pr02_v3_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_V3_OVERSIZED_NOT_FAIL_CLOSED"]
    assert codes["MEGA_PR02_V3_MALFORMED_NOT_FAIL_CLOSED"]
    assert codes["MEGA_PR02_V3_SLOW_NOT_FAIL_CLOSED"]
    assert codes["MEGA_PR02_V3_PROVIDER_CASES_INCOMPLETE"]


def test_live_signer_sender_and_private_key_remain_forbidden() -> None:
    evidence = replace(
        valid_evidence(),
        live_execution_requested=True,
        signer_requested=True,
        sender_requested=True,
        private_key_material_present=True,
    )

    report = evaluate_mega_pr02_v3_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_V3_LIVE_REQUESTED"]
    assert codes["MEGA_PR02_V3_SIGNER_REQUESTED"]
    assert codes["MEGA_PR02_V3_SENDER_REQUESTED"]
    assert codes["MEGA_PR02_V3_PRIVATE_KEY_PRESENT"]
