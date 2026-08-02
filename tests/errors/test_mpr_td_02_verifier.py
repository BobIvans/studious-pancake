from __future__ import annotations

from scripts.verify_mpr_td_02_failure_verification import build_evidence


def test_failure_verifier_accepts_canonical_contract() -> None:
    evidence = build_evidence()
    assert evidence["accepted"] is True, evidence["errors"]
    assert evidence["unknown_reason_code_rejected"] is True
    assert evidence["ambiguous_retry_denied"] is True
    assert evidence["cancellation_propagates"] is True
