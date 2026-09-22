from __future__ import annotations

import pytest

from src.evidence_bundle_pr147 import (
    PR147BundleError,
    PR147EvidenceBundleManifest,
    PR147EvidenceEntry,
    REQUIRED_BUNDLE_GATES,
    assert_pr147_evidence_bundle,
    evaluate_pr147_evidence_bundle,
)

SHA1 = "a" * 40
HASH = "1" * 64


def _entry(gate_id: str, **overrides: object) -> PR147EvidenceEntry:
    kwargs: dict[str, object] = {
        "gate_id": gate_id,
        "artifact_path": f"evidence/{gate_id.lower()}/report.json",
        "evidence_sha256": HASH,
        "source_pr_number": int(gate_id.split("-")[1]),
        "source_head_sha": SHA1,
        "produced_by": "github-actions",
    }
    kwargs.update(overrides)
    return PR147EvidenceEntry(**kwargs)  # type: ignore[arg-type]


def _manifest(
    *entries: PR147EvidenceEntry,
    **overrides: object,
) -> PR147EvidenceBundleManifest:
    payload: dict[str, object] = {
        "repo_full_name": "BobIvans/studious-pancake",
        "base_main_sha": SHA1,
        "bundle_branch": "pr-147-evidence-bundle-manifest",
        "generated_at_utc": "2026-07-22T16:50:00Z",
        "entries": entries
        or tuple(_entry(gate_id) for gate_id in REQUIRED_BUNDLE_GATES),
    }
    payload.update(overrides)
    return PR147EvidenceBundleManifest(**payload)  # type: ignore[arg-type]


def test_pr147_complete_bundle_is_review_ready() -> None:
    decision = assert_pr147_evidence_bundle(_manifest())

    assert decision.review_ready is True
    assert decision.paper_claim_allowed is False
    assert decision.live_claim_allowed is False
    assert decision.blockers == ()
    assert decision.state.value == "evidence-bundle-review-ready"
    assert set(decision.present_gate_ids) == set(REQUIRED_BUNDLE_GATES)


def test_pr147_missing_required_gate_blocks() -> None:
    entries = tuple(
        _entry(gate_id)
        for gate_id in REQUIRED_BUNDLE_GATES
        if gate_id != "PR-138"
    )
    decision = evaluate_pr147_evidence_bundle(_manifest(*entries))

    assert decision.review_ready is False
    assert "REQUIRED_GATE_EVIDENCE_MISSING:PR-138" in decision.blockers


def test_pr147_duplicate_required_gate_blocks() -> None:
    entries = tuple(_entry(gate_id) for gate_id in REQUIRED_BUNDLE_GATES) + (
        _entry("PR-140", artifact_path="evidence/pr-140/extra.json"),
    )
    decision = evaluate_pr147_evidence_bundle(_manifest(*entries))

    assert decision.review_ready is False
    assert "DUPLICATE_GATE_EVIDENCE:PR-140" in decision.blockers


def test_pr147_unexpected_gate_blocks() -> None:
    entries = tuple(_entry(gate_id) for gate_id in REQUIRED_BUNDLE_GATES) + (
        _entry("PR-999", artifact_path="evidence/pr-999/report.json"),
    )
    decision = evaluate_pr147_evidence_bundle(_manifest(*entries))

    assert decision.review_ready is False
    assert "UNEXPECTED_GATE_EVIDENCE:PR-999" in decision.blockers


def test_pr147_unreviewed_unredacted_or_mutable_evidence_blocks() -> None:
    entries = tuple(
        _entry(
            gate_id,
            reviewed=False if gate_id == "PR-128" else True,
            redacted=False if gate_id == "PR-129" else True,
            immutable=False if gate_id == "PR-130" else True,
        )
        for gate_id in REQUIRED_BUNDLE_GATES
    )
    decision = evaluate_pr147_evidence_bundle(_manifest(*entries))

    assert "EVIDENCE_NOT_REVIEWED:PR-128" in decision.blockers
    assert "EVIDENCE_NOT_REDACTED:PR-129" in decision.blockers
    assert "EVIDENCE_NOT_IMMUTABLE:PR-130" in decision.blockers


def test_pr147_synthetic_evidence_fails_closed_by_default() -> None:
    entries = tuple(
        _entry(gate_id, synthetic=(gate_id == "PR-144"))
        for gate_id in REQUIRED_BUNDLE_GATES
    )
    blocked = evaluate_pr147_evidence_bundle(_manifest(*entries))
    allowed_for_fixture_review = evaluate_pr147_evidence_bundle(
        _manifest(*entries, allow_synthetic_evidence=True)
    )

    assert blocked.review_ready is False
    assert "SYNTHETIC_EVIDENCE_NOT_ALLOWED:PR-144" in blocked.blockers
    assert allowed_for_fixture_review.review_ready is True


def test_pr147_expiring_evidence_is_not_release_bundle_evidence() -> None:
    entries = tuple(
        _entry(
            gate_id,
            expires_at_utc="2026-07-23T00:00:00Z"
            if gate_id == "PR-139"
            else None,
        )
        for gate_id in REQUIRED_BUNDLE_GATES
    )
    decision = evaluate_pr147_evidence_bundle(_manifest(*entries))

    assert decision.review_ready is False
    assert "EXPIRING_EVIDENCE_NOT_ALLOWED:PR-139" in decision.blockers


def test_pr147_bundle_hash_must_match_when_supplied() -> None:
    manifest = _manifest()
    ok = evaluate_pr147_evidence_bundle(
        _manifest(expected_bundle_sha256=manifest.bundle_sha256)
    )
    bad = evaluate_pr147_evidence_bundle(_manifest(expected_bundle_sha256="b" * 64))

    assert ok.review_ready is True
    assert bad.review_ready is False
    assert "BUNDLE_HASH_MISMATCH" in bad.blockers


def test_pr147_paper_and_live_claims_are_forbidden_in_this_slice() -> None:
    paper = evaluate_pr147_evidence_bundle(_manifest(paper_claim_requested=True))
    live = evaluate_pr147_evidence_bundle(_manifest(live_claim_requested=True))

    assert paper.review_ready is False
    assert "PAPER_CLAIM_FORBIDDEN_IN_PR147" in paper.blockers
    assert live.review_ready is False
    assert "LIVE_CLAIM_FORBIDDEN_IN_PR147" in live.blockers


def test_pr147_rejects_malformed_hashes_and_unsafe_paths() -> None:
    with pytest.raises(PR147BundleError):
        _entry("PR-128", evidence_sha256="not-a-hash")

    with pytest.raises(PR147BundleError):
        _entry("PR-128", artifact_path="../secrets.env")

    with pytest.raises(PR147BundleError):
        _manifest(base_main_sha="short")
