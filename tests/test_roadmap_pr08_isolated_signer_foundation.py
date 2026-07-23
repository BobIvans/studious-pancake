from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC = ROOT / "isolated_signer_service" / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from flashloan_isolated_signer import (  # noqa: E402
    COMPILE_TIME_SUBMISSION_ENABLED,
    ActivationBundle,
    ApprovalEvidence,
    BoundaryFailure,
    DurableSubmissionIntentStore,
    IntentState,
    IsolatedSignerBoundary,
    KillSwitchState,
    MessageReview,
    PR08BoundaryError,
    SignerPolicy,
    SubmissionPermit,
    TransportKind,
)
from flashloan_isolated_signer.service import status_payload  # noqa: E402


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def approvals(release: str, policy_hash: str) -> tuple[ApprovalEvidence, ...]:
    return tuple(
        ApprovalEvidence(
            roadmap_pr=number,
            evidence_sha256=digest(f"evidence-{number}"),
            release_id=release,
            policy_bundle_hash=policy_hash,
            reviewer_id="reviewer-a" if number % 2 else "reviewer-b",
            approval_identity=f"approval-{number}",
            passed=True,
            independently_reviewed=True,
        )
        for number in range(1, 8)
    )


def fixture(tmp_path: Path):
    now = 1_000_000_000
    release = "release-pr08"
    bundle_hash = digest("policy-bundle")
    signer = "remote-signer-primary"
    activation = ActivationBundle(
        release,
        bundle_hash,
        signer,
        1,
        approvals(release, bundle_hash),
    )
    payer = "payer-primary"
    program = "system-program"
    policy = SignerPolicy(
        "signer-policy-v1",
        signer,
        frozenset({payer}),
        frozenset({payer}),
        frozenset({program}),
        frozenset({TransportKind.RPC, TransportKind.JITO_SINGLE}),
        (100_000, 10_000, 5_000, 5_000, 8, 12, 1232),
    )
    review = MessageReview(
        "attempt-pr08",
        1,
        release,
        bundle_hash,
        digest("message"),
        payer,
        (payer,),
        (program,),
        (payer,),
        2,
        600,
        50_000,
        5_000,
        1_000,
        0,
        tuple(digest(name) for name in ("plan", "sim", "cpi", "fee", "block", "alt")),
    )
    permit = SubmissionPermit(
        "permit-pr08",
        signer,
        TransportKind.RPC,
        release,
        bundle_hash,
        policy.policy_hash,
        activation.activation_hash,
        review.attempt_id,
        review.generation,
        review.message_sha256,
        review.review_hash,
        digest("nonce"),
        now,
        now + 60_000_000_000,
    )
    kill_switch = KillSwitchState(1, False, frozenset(), digest("inactive"))
    boundary = IsolatedSignerBoundary(
        DurableSubmissionIntentStore(tmp_path / "submission.sqlite"),
        approval_verifier=lambda item: item.approval_identity.startswith("approval-"),
        permit_verifier=lambda item: item.nonce_digest == digest("nonce"),
        clock_ns=lambda: now + 1,
    )
    return boundary, activation, policy, kill_switch, permit, review


def prepare(boundary, activation, policy, kill_switch, permit, review, wire="wire"):
    return boundary.prepare(
        activation=activation,
        policy=policy,
        kill_switch=kill_switch,
        permit=permit,
        review=review,
        signed_wire_sha256=digest(wire),
    )


def test_pr08_is_separate_from_paper_wheel_and_source_import_graph() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["src*"]' in pyproject
    assert "isolated_signer_service" not in pyproject
    for path in (ROOT / "src").rglob("*.py"):
        assert "flashloan_isolated_signer" not in path.read_text(encoding="utf-8")


def test_pr08_requires_every_independently_reviewed_prerequisite(
    tmp_path: Path,
) -> None:
    boundary, activation, policy, switch, permit, review = fixture(tmp_path)
    with pytest.raises(PR08BoundaryError) as error:
        prepare(
            boundary,
            replace(activation, approvals=activation.approvals[:-1]),
            policy,
            switch,
            permit,
            review,
        )
    assert error.value.failure is BoundaryFailure.PREREQUISITES


def test_pr08_binding_and_limits_fail_closed(tmp_path: Path) -> None:
    boundary, activation, policy, switch, permit, review = fixture(tmp_path)
    changed = replace(review, message_sha256=digest("changed"))
    with pytest.raises(PR08BoundaryError) as binding:
        prepare(boundary, activation, policy, switch, permit, changed)
    assert binding.value.failure is BoundaryFailure.BINDING_INVALID

    excessive = replace(review, spend_lamports=policy.limits[0] + 1)
    limited_permit = replace(permit, review_hash=excessive.review_hash)
    with pytest.raises(PR08BoundaryError) as limit:
        prepare(boundary, activation, policy, switch, limited_permit, excessive)
    assert limit.value.failure is BoundaryFailure.POLICY_LIMIT


def test_pr08_kill_switch_and_revocation_block_before_intent(tmp_path: Path) -> None:
    boundary, activation, policy, switch, permit, review = fixture(tmp_path)
    with pytest.raises(PR08BoundaryError) as active:
        prepare(
            boundary,
            activation,
            policy,
            replace(switch, active=True),
            permit,
            review,
        )
    assert active.value.failure is BoundaryFailure.KILL_SWITCH

    revoked = replace(switch, revoked_signers=frozenset({permit.signer_identity}))
    with pytest.raises(PR08BoundaryError) as error:
        prepare(boundary, activation, policy, revoked, permit, review)
    assert error.value.failure is BoundaryFailure.SIGNER_REVOKED


def test_pr08_exact_retry_is_idempotent_and_conflict_is_rejected(
    tmp_path: Path,
) -> None:
    boundary, activation, policy, switch, permit, review = fixture(tmp_path)
    first = prepare(boundary, activation, policy, switch, permit, review)
    second = prepare(boundary, activation, policy, switch, permit, review)
    assert first == second
    assert first.state is IntentState.PREPARED
    with pytest.raises(PR08BoundaryError) as conflict:
        prepare(boundary, activation, policy, switch, permit, review, "other-wire")
    assert conflict.value.failure is BoundaryFailure.REPLAY_CONFLICT


def test_pr08_indeterminate_intent_cannot_be_redispatched(tmp_path: Path) -> None:
    boundary, activation, policy, switch, permit, review = fixture(tmp_path)
    intent = prepare(boundary, activation, policy, switch, permit, review)
    boundary.store.transition(
        intent.intent_id,
        expected=IntentState.PREPARED,
        target=IntentState.DISPATCHED,
        now_ns=2_000_000_000,
    )
    result = boundary.store.transition(
        intent.intent_id,
        expected=IntentState.DISPATCHED,
        target=IntentState.INDETERMINATE,
        now_ns=2_000_000_001,
    )
    assert result.state is IntentState.INDETERMINATE
    with pytest.raises(PR08BoundaryError) as retry:
        boundary.store.transition(
            intent.intent_id,
            expected=IntentState.PREPARED,
            target=IntentState.DISPATCHED,
            now_ns=2_000_000_002,
        )
    assert retry.value.failure is BoundaryFailure.INTENT_STATE


def test_pr08_transport_is_unreachable_while_compile_time_disabled(
    tmp_path: Path,
) -> None:
    boundary, activation, policy, switch, permit, review = fixture(tmp_path)
    intent = prepare(boundary, activation, policy, switch, permit, review)
    calls = 0

    class Transport:
        def send(self, **_: object):
            nonlocal calls
            calls += 1
            return {"accepted": True}

    assert COMPILE_TIME_SUBMISSION_ENABLED is False
    with pytest.raises(PR08BoundaryError) as error:
        boundary.dispatch_once(
            intent=intent, signed_wire=b"wire", transport=Transport()
        )
    assert error.value.failure is BoundaryFailure.COMPILE_DISABLED
    assert calls == 0


def test_pr08_status_exposes_no_key_or_network_capability() -> None:
    payload = status_payload()
    assert payload["compile_time_submission_enabled"] is False
    assert payload["private_key_loader_present"] is False
    assert payload["network_transport_implementation_present"] is False
    assert payload["roadmap_prerequisites_required"] == list(range(1, 8))
    completed = subprocess.run(
        [sys.executable, "-m", "flashloan_isolated_signer.service", "status", "--json"],
        env={"PYTHONPATH": str(PACKAGE_SRC)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert '"compile_time_submission_enabled":false' in completed.stdout
