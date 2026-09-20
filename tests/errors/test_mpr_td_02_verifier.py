from __future__ import annotations

from scripts.verify_mpr_td_02_failure_verification import build_evidence


def test_failure_verifier_accepts_canonical_contract() -> None:
    evidence = build_evidence()
    assert evidence["accepted"] is True, evidence["errors"]
    assert evidence["unknown_reason_code_rejected"] is True
    assert evidence["exercised_reason_code_count"] == evidence["active_reason_code_count"]
    assert len(evidence["exercised_reason_codes"]) == evidence["active_reason_code_count"]
    assert evidence["ambiguous_retry_denied"] is True
    assert evidence["cancellation_propagates"] is True
