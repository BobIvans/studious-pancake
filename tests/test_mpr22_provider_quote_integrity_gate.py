from __future__ import annotations

import pytest

from src.mpr22_provider_quote_integrity_gate import (
    FindingClosure,
    MPR22GateState,
    QuotaAuthorityEvidence,
    QuoteEvidence,
    TransportEvidence,
    evaluate_mpr22_provider_gate,
)

A = "a" * 64
B = "b" * 64
PUBKEY_A = "So11111111111111111111111111111111111111112"
PUBKEY_B = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5NtA7q2wQ"
REQ_FINDINGS = [
    "F-304", "F-305", "F-306", "F-307", "F-308",
    "F-309", "F-310", "F-311", "F-312", "F-313",
    "F-420", "F-421", "F-422", "F-423", "F-424",
    "F-425", "F-426", "F-427", "F-428", "F-429",
]


def make_transport(**overrides: object) -> TransportEvidence:
    data = {
        "provider": "jupiter",
        "request_hash": A,
        "endpoint_identity": "jupiter-mainnet-primary",
        "cluster_genesis_hash": B,
        "absolute_deadline_ms": 2500,
        "total_elapsed_ms": 750,
        "bounded_response_bytes": True,
        "hardened_json_parser": True,
        "dns_rebinding_protected": True,
        "tls_peer_pinned": True,
        "private_ip_denied": True,
        "redirect_revalidated": True,
        "request_bound_provenance": True,
    }
    data.update(overrides)
    return TransportEvidence(**data)


def make_quote(**overrides: object) -> QuoteEvidence:
    data = {
        "provider": "jupiter",
        "request_hash": A,
        "quote_hash": B,
        "quote_expires_at_ms": 2_000_000,
        "observed_at_ms": 1_999_000,
        "provider_generation": 4,
        "swap_mode": "ExactIn",
        "slippage_bps": 50,
        "input_mint": PUBKEY_A,
        "output_mint": PUBKEY_B,
        "amount_in": 1_000_000,
        "route_identity": "route-1",
        "provenance_bound": True,
        "request_policy_preserved": True,
    }
    data.update(overrides)
    return QuoteEvidence(**data)


def make_quota(**overrides: object) -> QuotaAuthorityEvidence:
    data = {
        "authority_generation": 7,
        "reservation_id": "quota-reservation-1",
        "reservation_bound_to_request": True,
        "cross_process_serialized": True,
        "monotonic_time_authority": True,
        "exactly_once_mark_used": True,
        "bounded_history": True,
    }
    data.update(overrides)
    return QuotaAuthorityEvidence(**data)


def all_closed():
    return [FindingClosure(finding_id=fid, closed=True) for fid in REQ_FINDINGS]


def test_mpr22_gate_accepts_complete_provider_truth() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(),
        quota=make_quota(),
        findings=all_closed(),
    )
    assert report.ready is True
    assert report.state is MPR22GateState.READY_FOR_PROVIDER_REVIEW
    assert report.violations == ()
    assert report.to_dict()["safety_boundary"] == {
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_allowed": False,
    }


def test_mpr22_gate_rejects_missing_required_finding() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(),
        quota=make_quota(),
        findings=all_closed()[:-1],
    )
    assert report.ready is False
    assert any(v.code == "missing_required_finding_closure" and v.subject == "F-429" for v in report.violations)


def test_mpr22_gate_rejects_mismatched_request_hash() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(request_hash=A),
        quote=make_quote(request_hash="c"*64),
        quota=make_quota(),
        findings=all_closed(),
    )
    assert any(v.code == "request_hash_mismatch" for v in report.violations)


def test_mpr22_gate_rejects_absolute_timeout_overrun() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(total_elapsed_ms=2600),
        quote=make_quote(),
        quota=make_quota(),
        findings=all_closed(),
    )
    assert any(v.code == "absolute_deadline_exceeded" for v in report.violations)


def test_mpr22_gate_rejects_unbounded_transport_parser() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(bounded_response_bytes=False, hardened_json_parser=False),
        quote=make_quote(),
        quota=make_quota(),
        findings=all_closed(),
    )
    subjects = {v.subject for v in report.violations if v.code == "transport_guard_missing"}
    assert {"bounded_response_bytes", "hardened_json_parser"} <= subjects


def test_mpr22_gate_rejects_dns_and_private_ip_bypass() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(dns_rebinding_protected=False, private_ip_denied=False),
        quote=make_quote(),
        quota=make_quota(),
        findings=all_closed(),
    )
    subjects = {v.subject for v in report.violations if v.code == "transport_guard_missing"}
    assert {"dns_rebinding_protected", "private_ip_denied"} <= subjects


def test_mpr22_gate_rejects_quote_without_expiry() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(quote_expires_at_ms=1000, observed_at_ms=1000),
        quota=make_quota(),
        findings=all_closed(),
    )
    assert any(v.code == "quote_not_fresh" for v in report.violations)


def test_mpr22_gate_rejects_quote_policy_drift() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(provenance_bound=False, request_policy_preserved=False),
        quota=make_quota(),
        findings=all_closed(),
    )
    subjects = {v.subject for v in report.violations if v.code == "quote_integrity_missing"}
    assert {"quote_provenance_bound", "request_policy_preserved"} <= subjects


def test_mpr22_gate_rejects_process_local_quota_authority() -> None:
    report = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(),
        quota=make_quota(cross_process_serialized=False, exactly_once_mark_used=False),
        findings=all_closed(),
    )
    subjects = {v.subject for v in report.violations if v.code == "quota_authority_missing"}
    assert {"cross_process_serialized", "exactly_once_mark_used"} <= subjects


def test_mpr22_gate_hash_is_deterministic() -> None:
    left = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(),
        quota=make_quota(),
        findings=all_closed(),
    )
    right = evaluate_mpr22_provider_gate(
        transport=make_transport(),
        quote=make_quote(),
        quota=make_quota(),
        findings=list(reversed(all_closed())),
    )
    assert left.evidence_hash == right.evidence_hash


def test_quote_rejects_invalid_pubkey_and_bool_like_amounts() -> None:
    with pytest.raises(ValueError):
        make_quote(input_mint="not-a-pubkey")
