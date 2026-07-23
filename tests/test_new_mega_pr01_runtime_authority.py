from __future__ import annotations

import copy

import pytest

from src.runtime_authority_pr01 import (
    AttemptGeneration,
    RuntimeAuthorityError,
    SemanticCommandIdentity,
    SemanticIdempotencyLedger,
    TerminalTransitionTable,
    evaluate_runtime_authority_map,
    load_default_authority_map,
)

pytestmark = pytest.mark.unit


def test_new_mega_pr01_default_runtime_authority_map_is_accepted() -> None:
    report = evaluate_runtime_authority_map()

    assert report.accepted is True
    assert report.blockers == ()
    assert report.active_composition_root == "src.cli_pr189:main"
    assert report.lifecycle_authority.endswith("UnifiedLifecycleAuthority")
    assert report.capital_authority.endswith("DurableCapitalCoordinator")


def test_new_mega_pr01_rejects_second_active_runtime_surface() -> None:
    payload = copy.deepcopy(load_default_authority_map())
    payload["alternate_runtime_surfaces"][0]["active"] = True

    report = evaluate_runtime_authority_map(payload)

    assert report.accepted is False
    assert any(blocker.startswith("ALTERNATE_RUNTIME_ACTIVE") for blocker in report.blockers)


def test_new_mega_pr01_requires_sensitive_writes_to_bind_fence_and_payload() -> None:
    payload = copy.deepcopy(load_default_authority_map())
    payload["sensitive_writes"][0]["invariants"].remove("fencing_token")

    report = evaluate_runtime_authority_map(payload)

    assert report.accepted is False
    assert any("SENSITIVE_WRITE_INVARIANTS_MISSING" in blocker for blocker in report.blockers)


def test_new_mega_pr01_attempt_generation_is_positive() -> None:
    assert int(AttemptGeneration(1)) == 1
    with pytest.raises(RuntimeAuthorityError, match=">= 1"):
        AttemptGeneration(0)


def test_new_mega_pr01_semantic_idempotency_rejects_drift() -> None:
    ledger = SemanticIdempotencyLedger()
    first = SemanticCommandIdentity(
        attempt_id="attempt-1",
        attempt_generation=1,
        candidate_id="candidate-a",
        reservation_id="reservation-a",
        policy_bundle_hash="policy-a",
        payload_hash="payload-a",
    )
    replay = SemanticCommandIdentity(
        attempt_id="attempt-1",
        attempt_generation=1,
        candidate_id="candidate-a",
        reservation_id="reservation-a",
        policy_bundle_hash="policy-a",
        payload_hash="payload-a",
    )
    drift = SemanticCommandIdentity(
        attempt_id="attempt-1",
        attempt_generation=1,
        candidate_id="candidate-b",
        reservation_id="reservation-a",
        policy_bundle_hash="policy-a",
        payload_hash="payload-a",
    )

    assert ledger.record("idem-1", first) is False
    assert ledger.record("idem-1", replay) is True
    with pytest.raises(RuntimeAuthorityError, match="IDEMPOTENCY_SEMANTIC_CONFLICT"):
        ledger.record("idem-1", drift)


def test_new_mega_pr01_terminal_state_cannot_regress() -> None:
    table = TerminalTransitionTable()

    assert table.decide("NONTERMINAL", "TERMINAL").accepted is True
    decision = table.decide("TERMINAL", "NONTERMINAL")

    assert decision.accepted is False
    assert decision.reason == "TERMINAL_REGRESSION_FORBIDDEN"
