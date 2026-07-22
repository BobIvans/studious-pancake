from __future__ import annotations

from src.readiness_gate_pr142 import (
    LIVE_CANARY_REQUIRED_GATES,
    PAPER_REQUIRED_GATES,
    EvidenceStatus,
    ReadinessDecision,
    ReadinessEvidence,
    ReadinessMode,
    ReadinessPolicy,
    ReadinessReason,
    evaluate_readiness,
    release_claim,
)


def _hash(label: str) -> str:
    return hashlib_like(label)


def hashlib_like(label: str) -> str:
    return (label.encode("utf-8").hex() * 8)[:64]


def _evidence(gate: str, *, slot: int = 1000) -> ReadinessEvidence:
    return ReadinessEvidence(
        gate=gate,
        status=EvidenceStatus.PRESENT,
        evidence_hash=_hash(gate),
        reviewed_by_human=True,
        observed_at_slot=slot,
        max_age_slots=100,
    )


def test_pr142_paper_ready_requires_every_paper_gate() -> None:
    report = evaluate_readiness(
        [_evidence(gate) for gate in PAPER_REQUIRED_GATES],
        ReadinessPolicy(ReadinessMode.PAPER, current_slot=1010),
    )

    assert report.decision is ReadinessDecision.READY
    assert report.ready is True
    assert report.failures == ()


def test_pr142_missing_cpi_call_graph_blocks_paper_claim() -> None:
    evidence = [
        _evidence(gate)
        for gate in PAPER_REQUIRED_GATES
        if gate != "pr137_cpi_call_graph"
    ]

    report = evaluate_readiness(
        evidence,
        ReadinessPolicy(ReadinessMode.PAPER, current_slot=1010),
    )

    assert report.ready is False
    assert any(
        failure.gate == "pr137_cpi_call_graph"
        and failure.reason is ReadinessReason.MISSING_EVIDENCE
        for failure in report.failures
    )


def test_pr142_placeholder_hash_is_not_release_evidence() -> None:
    evidence = [_evidence(gate) for gate in PAPER_REQUIRED_GATES]
    evidence[0] = ReadinessEvidence(
        gate=PAPER_REQUIRED_GATES[0],
        status=EvidenceStatus.PRESENT,
        evidence_hash="0" * 64,
        reviewed_by_human=True,
    )

    report = evaluate_readiness(evidence, ReadinessPolicy(ReadinessMode.PAPER))

    assert report.ready is False
    assert any(
        failure.reason is ReadinessReason.PLACEHOLDER_HASH
        for failure in report.failures
    )


def test_pr142_unreviewed_evidence_blocks_even_when_present() -> None:
    evidence = [_evidence(gate) for gate in PAPER_REQUIRED_GATES]
    evidence[-1] = ReadinessEvidence(
        gate=PAPER_REQUIRED_GATES[-1],
        status=EvidenceStatus.PRESENT,
        evidence_hash=_hash("unreviewed"),
        reviewed_by_human=False,
    )

    report = evaluate_readiness(evidence, ReadinessPolicy(ReadinessMode.PAPER))

    assert report.ready is False
    assert any(
        failure.gate == PAPER_REQUIRED_GATES[-1]
        and failure.reason is ReadinessReason.UNREVIEWED_EVIDENCE
        for failure in report.failures
    )


def test_pr142_slot_freshness_budget_blocks_stale_evidence() -> None:
    evidence = [_evidence(gate, slot=1000) for gate in PAPER_REQUIRED_GATES]

    report = evaluate_readiness(
        evidence,
        ReadinessPolicy(ReadinessMode.PAPER, current_slot=1201),
    )

    assert report.ready is False
    assert any(
        failure.reason is ReadinessReason.STALE_EVIDENCE
        for failure in report.failures
    )


def test_pr142_live_canary_requires_paper_and_live_only_gates() -> None:
    report = evaluate_readiness(
        [_evidence(gate) for gate in LIVE_CANARY_REQUIRED_GATES],
        ReadinessPolicy(ReadinessMode.LIVE_CANARY, current_slot=1001),
    )

    assert report.ready is True
    assert set(PAPER_REQUIRED_GATES).issubset(set(report.required_gates))
    assert "pr138_finalized_settlement" in report.required_gates
    assert "pr134_production_sandbox" in report.required_gates


def test_pr142_live_flag_blocks_readiness_before_approval() -> None:
    evidence = [_evidence(gate) for gate in LIVE_CANARY_REQUIRED_GATES]
    evidence[0] = ReadinessEvidence(
        gate=LIVE_CANARY_REQUIRED_GATES[0],
        status=EvidenceStatus.PRESENT,
        evidence_hash=_hash("live-enabled"),
        reviewed_by_human=True,
        live_enabled=True,
    )

    report = evaluate_readiness(
        evidence,
        ReadinessPolicy(ReadinessMode.LIVE_CANARY),
    )

    assert report.ready is False
    assert any(
        failure.reason is ReadinessReason.LIVE_ENABLED_BEFORE_GATE
        for failure in report.failures
    )


def test_pr142_failed_or_stale_status_is_not_accepted() -> None:
    evidence = [_evidence(gate) for gate in PAPER_REQUIRED_GATES]
    evidence[1] = ReadinessEvidence(
        gate=PAPER_REQUIRED_GATES[1],
        status=EvidenceStatus.FAILED,
        evidence_hash=_hash("failed"),
        reviewed_by_human=True,
    )

    report = evaluate_readiness(evidence, ReadinessPolicy(ReadinessMode.PAPER))

    assert report.ready is False
    assert any(
        failure.gate == PAPER_REQUIRED_GATES[1]
        and failure.reason is ReadinessReason.FAILED_EVIDENCE
        for failure in report.failures
    )


def test_pr142_latest_evidence_for_duplicate_gate_wins() -> None:
    old = ReadinessEvidence(
        gate=PAPER_REQUIRED_GATES[0],
        status=EvidenceStatus.FAILED,
        evidence_hash=_hash("old"),
        reviewed_by_human=True,
        observed_at_slot=10,
    )
    new = ReadinessEvidence(
        gate=PAPER_REQUIRED_GATES[0],
        status=EvidenceStatus.PRESENT,
        evidence_hash=_hash("new"),
        reviewed_by_human=True,
        observed_at_slot=20,
    )
    evidence = [old, new, *[_evidence(gate) for gate in PAPER_REQUIRED_GATES[1:]]]

    report = evaluate_readiness(evidence, ReadinessPolicy(ReadinessMode.PAPER))

    assert report.ready is True


def test_pr142_release_claim_cannot_label_paper_report_as_live_ready() -> None:
    report = evaluate_readiness(
        [_evidence(gate) for gate in PAPER_REQUIRED_GATES],
        ReadinessPolicy(ReadinessMode.PAPER),
    )

    claim = release_claim(report=report, claim="Live Canary Ready")

    assert claim["allowed"] is False
    assert claim["decision"] == "ready"


def test_pr142_report_hash_is_deterministic() -> None:
    evidence = [_evidence(gate) for gate in PAPER_REQUIRED_GATES]
    policy = ReadinessPolicy(ReadinessMode.PAPER, current_slot=1010)

    first = evaluate_readiness(evidence, policy)
    second = evaluate_readiness(list(reversed(evidence)), policy)

    assert first.evidence_hash == second.evidence_hash
