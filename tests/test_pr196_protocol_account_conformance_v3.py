from __future__ import annotations

from dataclasses import asdict
import json

import pytest

from src.pr196_protocol_account_conformance_v3 import (
    NATIVE_SOL_SENTINEL,
    OFFICIAL_TOKEN_2022_PROGRAM_ID,
    PR196ProtocolConformanceClaim,
    PR196ProtocolConformanceError,
    REQUIREMENTS,
    SCHEMA_VERSION,
    WSOL_MINT,
    assert_token_2022_program_id,
    complete_offline_claim,
    evaluate_pr196_protocol_conformance,
    false_token_2022_program_ids,
    render_report_json,
)


def test_pr196_default_claim_is_fail_closed() -> None:
    report = evaluate_pr196_protocol_conformance(PR196ProtocolConformanceClaim())

    assert report.schema_version == SCHEMA_VERSION
    assert not report.ready
    assert not report.live_execution_allowed
    assert not report.signer_or_sender_allowed
    assert len(report.requirement_results) == len(REQUIREMENTS)
    assert all(not item.satisfied for item in report.requirement_results)
    assert "CANONICAL_CHAIN_PROGRAM_IDENTITY:MISSING_PROOF" in report.reason_codes
    assert "PACKAGED_MARGINFI_PROVENANCE:MISSING_PROOF" in report.reason_codes


def test_pr196_complete_sender_free_claim_is_ready_and_deterministic() -> None:
    claim = complete_offline_claim(
        evidence_refs=("evidence/pr196/protocol-account-conformance.json",)
    )

    first = evaluate_pr196_protocol_conformance(claim)
    second = evaluate_pr196_protocol_conformance(claim)

    assert first.ready
    assert first.reason_codes == ()
    assert first.claim_hash == second.claim_hash
    assert {item.requirement_id for item in first.requirement_results} == {
        item.requirement_id for item in REQUIREMENTS
    }


def test_pr196_live_or_signer_enablement_is_rejected() -> None:
    claim = complete_offline_claim(evidence_refs=("fixtures/pr196/complete.json",))

    report = evaluate_pr196_protocol_conformance(
        claim,
        live_execution_allowed=True,
        signer_or_sender_allowed=True,
    )

    assert not report.ready
    assert "LIVE_EXECUTION_NOT_ALLOWED_IN_PR196" in report.reason_codes
    assert "SIGNER_OR_SENDER_NOT_ALLOWED_IN_PR196" in report.reason_codes


def test_pr196_token_2022_identity_rejects_known_false_literals() -> None:
    assert_token_2022_program_id(OFFICIAL_TOKEN_2022_PROGRAM_ID)

    for value in false_token_2022_program_ids():
        with pytest.raises(PR196ProtocolConformanceError, match="false Token-2022"):
            assert_token_2022_program_id(value)

    with pytest.raises(PR196ProtocolConformanceError, match="non-canonical"):
        assert_token_2022_program_id("11111111111111111111111111111111")


def test_pr196_native_sol_and_wsol_are_separate_identities() -> None:
    report = evaluate_pr196_protocol_conformance(
        complete_offline_claim(evidence_refs=("tests/pr196/identity.json",))
    )
    payload = report.to_dict()["canonical_program_ids"]

    assert NATIVE_SOL_SENTINEL == "11111111111111111111111111111111"
    assert WSOL_MINT == "So11111111111111111111111111111111111111112"
    assert NATIVE_SOL_SENTINEL != WSOL_MINT
    assert payload["native_sol_sentinel"] != payload["wsol_mint"]


def test_pr196_chain_identity_requirement_lists_v3_findings() -> None:
    almost = complete_offline_claim(evidence_refs=("evidence/pr196/chain.json",))
    claim = PR196ProtocolConformanceClaim(
        **{
            **asdict(almost),
            "false_token_2022_literals_rejected": False,
            "native_sol_and_wsol_are_distinct_types": False,
        }
    )

    report = evaluate_pr196_protocol_conformance(claim)
    result = next(
        item
        for item in report.requirement_results
        if item.requirement_id == "CANONICAL_CHAIN_PROGRAM_IDENTITY"
    )

    assert not report.ready
    assert result.finding_ids == ("F-129", "F-130")
    assert result.missing_claim_fields == (
        "false_token_2022_literals_rejected",
        "native_sol_and_wsol_are_distinct_types",
    )


def test_pr196_provider_boundary_requires_transport_dns_retry_and_quota() -> None:
    almost = complete_offline_claim(evidence_refs=("evidence/pr196/provider.json",))
    claim = PR196ProtocolConformanceClaim(
        **{
            **asdict(almost),
            "dns_public_ip_pinning": False,
            "retry_quota_budget_is_typed_and_shared": False,
        }
    )

    report = evaluate_pr196_protocol_conformance(claim)
    result = next(
        item
        for item in report.requirement_results
        if item.requirement_id == "BOUNDED_PROVIDER_TRANSPORT_AND_QUOTA"
    )

    assert not report.ready
    assert result.missing_claim_fields == (
        "dns_public_ip_pinning",
        "retry_quota_budget_is_typed_and_shared",
    )


def test_pr196_mapping_input_is_strict_and_evidence_paths_are_safe() -> None:
    with pytest.raises(PR196ProtocolConformanceError, match="unknown"):
        PR196ProtocolConformanceClaim.from_mapping({"surprise": True})

    with pytest.raises(PR196ProtocolConformanceError, match="must be boolean"):
        PR196ProtocolConformanceClaim.from_mapping(
            {"canonical_chain_registry_used": "true"}
        )

    with pytest.raises(PR196ProtocolConformanceError, match="safe evidence paths"):
        PR196ProtocolConformanceClaim.from_mapping(
            {"evidence_refs": ["../../secrets.env"]}
        )


def test_pr196_render_report_json_is_stable() -> None:
    rendered = render_report_json(
        {
            "canonical_chain_registry_used": True,
            "token_2022_program_id_matches_official": True,
            "false_token_2022_literals_rejected": True,
            "native_sol_and_wsol_are_distinct_types": True,
            "marginfi_provenance_packaged_and_mandatory": True,
            "rooted_account_mint_alt_oracle_snapshots": True,
            "token_2022_default_fail_closed": True,
            "marginfi_kamino_layouts_pinned": True,
            "bounded_provider_bodies_and_redirects": True,
            "dns_public_ip_pinning": True,
            "retry_quota_budget_is_typed_and_shared": True,
            "jupiter_build_alt_blockhash_semantics_validated": True,
            "credentialed_fixtures_reviewed": True,
            "provider_registry_signed": True,
            "evidence_refs": ["docs/pr196/reviewed-fixtures.json"],
        }
    )
    payload = json.loads(rendered)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["ready"] is True
    assert payload["reason_codes"] == []
    assert len(payload["claim_hash"]) == 64
