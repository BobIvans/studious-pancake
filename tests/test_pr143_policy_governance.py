from __future__ import annotations

import pytest

from src.policy_governance_pr143 import (
    MAX_SAFE_JSON_INTEGER,
    POLICY_BUNDLE_DOMAIN,
    REQUIRED_POLICY_COMPONENTS,
    AtomicPolicyActivator,
    AttemptPolicySnapshot,
    EvidenceEnvelope,
    GovernanceRecord,
    GovernanceState,
    HashRef,
    PolicyBundle,
    PolicyGovernanceError,
    RetryDisposition,
    assert_no_hot_env_decision,
    assert_no_raw_exception_persistence,
    canonical_json_bytes,
    fingerprint_secret_locator,
    parse_json_no_duplicate_keys,
    redact_mapping,
    require_hash_domain,
    safe_diagnostic_from_exception,
    validate_attempt_policy,
)


def _digest(label: str) -> str:
    return (label.encode("utf-8").hex() * 8)[:64].ljust(64, "0")[:64]


def _bundle(*, generation: int = 1, approval: bool = False) -> PolicyBundle:
    components = {
        name: HashRef(domain=f"flashloan-bot/{name}", digest=_digest(name))
        for name in REQUIRED_POLICY_COMPONENTS
    }
    operator_approval = (
        HashRef(domain="flashloan-bot/operator-approval", digest=_digest("approval"))
        if approval
        else None
    )
    return PolicyBundle(
        cluster_genesis="mainnet-genesis",
        components=components,
        generation=generation,
        operator_approval=operator_approval,
    )


def test_pr143_policy_bundle_requires_complete_component_set() -> None:
    components = {
        name: HashRef(domain=f"flashloan-bot/{name}", digest=_digest(name))
        for name in REQUIRED_POLICY_COMPONENTS[:-1]
    }

    with pytest.raises(PolicyGovernanceError, match="missing policy components"):
        PolicyBundle(cluster_genesis="mainnet-genesis", components=components)


def test_pr143_policy_bundle_digest_changes_when_secret_locator_identity_changes() -> None:
    first = fingerprint_secret_locator("env:KEY_A")
    second = fingerprint_secret_locator("env:KEY_B")

    assert first.digest != second.digest
    assert first.domain == second.domain
    assert "KEY_A" not in first.digest
    assert "KEY_B" not in second.digest


def test_pr143_domain_separated_hash_blocks_cross_domain_substitution() -> None:
    envelope = EvidenceEnvelope(
        domain=POLICY_BUNDLE_DOMAIN,
        schema_version="pr143.policy-bundle.v1",
        cluster_genesis="mainnet-genesis",
        payload={"policy": "same"},
    )

    with pytest.raises(PolicyGovernanceError, match="hash domain mismatch"):
        require_hash_domain(envelope.to_hash_ref(), "flashloan-bot/simulation")


def test_pr143_attempt_snapshot_binds_exact_policy_hash() -> None:
    current = _bundle(generation=1)
    snapshot = AttemptPolicySnapshot(
        attempt_id="attempt-1",
        attempt_generation=1,
        policy_bundle_hash=current.digest,
        config_version="cfg-1",
        evidence_max_age_slots=64,
        registry_versions={"assets": "v1"},
        model_version="model-disabled",
        operator_approval_version="review-1",
        cluster_genesis="mainnet-genesis",
    )

    compatible = validate_attempt_policy(snapshot, current)

    assert compatible.submission_allowed is True
    assert compatible.requires_rebuild is False


def test_pr143_changed_policy_invalidates_pending_attempt_submission() -> None:
    old = _bundle(generation=1)
    new = _bundle(generation=2)
    snapshot = AttemptPolicySnapshot(
        attempt_id="attempt-1",
        attempt_generation=1,
        policy_bundle_hash=old.digest,
        config_version="cfg-1",
        evidence_max_age_slots=64,
        registry_versions={"assets": "v1"},
        model_version="model-disabled",
        operator_approval_version="review-1",
        cluster_genesis="mainnet-genesis",
    )

    decision = validate_attempt_policy(snapshot, new)

    assert decision.submission_allowed is False
    assert decision.requires_rebuild is True
    assert decision.reason == "policy_bundle_hash_changed"


def test_pr143_canonical_json_rejects_binary_floats_and_encodes_huge_ints() -> None:
    with pytest.raises(PolicyGovernanceError, match="binary float"):
        canonical_json_bytes({"lamports": 1.1})

    encoded = canonical_json_bytes({"slot": MAX_SAFE_JSON_INTEGER + 1})

    assert b'"$int"' in encoded
    assert str(MAX_SAFE_JSON_INTEGER + 1).encode("ascii") in encoded


def test_pr143_json_duplicate_keys_are_rejected() -> None:
    with pytest.raises(PolicyGovernanceError, match="duplicate JSON key"):
        parse_json_no_duplicate_keys('{"policy": 1, "policy": 2}')


def test_pr143_redaction_removes_nested_secret_url_query_and_bearer() -> None:
    redacted = redact_mapping(
        {
            "provider_url": "https://rpc.example/?api_key=SECRET&safe=1",
            "headers": {"Authorization": "Bearer super-secret-token"},
            "nested": {"private_key": "abc123"},
        }
    )

    assert "SECRET" not in str(redacted)
    assert "super-secret-token" not in str(redacted)
    assert redacted["nested"]["private_key"] == "<redacted:secret>"


def test_pr143_safe_diagnostic_never_persists_raw_exception_string() -> None:
    exc = RuntimeError(
        "provider failed with api_key=SECRET and wallet "
        "11111111111111111111111111111111"
    )
    diagnostic = safe_diagnostic_from_exception(
        code="PROVIDER_ERROR",
        category="provider",
        retry=RetryDisposition.AFTER_REVIEW,
        correlation_id="corr-1",
        exc=exc,
        context={"url": "https://host/?token=SECRET", "api_key": "SECRET"},
        internal_debug_ref="debug-1",
    )

    payload_text = str(diagnostic.envelope.to_payload())

    assert "RuntimeError" in payload_text
    assert "api_key=SECRET" not in payload_text
    assert "wallet 11111111111111111111111111111111" not in payload_text
    assert diagnostic.exception_type == "RuntimeError"


def test_pr143_static_guards_reject_hot_env_and_raw_exception_persistence() -> None:
    with pytest.raises(PolicyGovernanceError, match="hot environment"):
        assert_no_hot_env_decision('enabled = os.getenv("DECISION_MODEL_ENABLED")')

    with pytest.raises(PolicyGovernanceError, match="raw exception"):
        assert_no_raw_exception_persistence('event = {"error": str(exc)}')


def test_pr143_atomic_activation_requires_approval_and_dual_live_approval() -> None:
    bundle = _bundle()
    operator = _digest("operator")
    review = _digest("review")
    activator = AtomicPolicyActivator()

    with pytest.raises(PolicyGovernanceError, match="only approved"):
        activator.activate(
            GovernanceRecord(
                bundle_hash=bundle.digest,
                state=GovernanceState.VALIDATED,
                operator_identity_hash=operator,
                reason="validated only",
                review_record_hash=review,
            )
        )

    with pytest.raises(PolicyGovernanceError, match="dual approval"):
        activator.activate(
            GovernanceRecord(
                bundle_hash=bundle.digest,
                state=GovernanceState.CANARY_APPROVED,
                operator_identity_hash=operator,
                reason="live change",
                review_record_hash=review,
                live_impacting=True,
            )
        )


def test_pr143_rollback_restores_previous_known_good_bundle() -> None:
    first = _bundle(generation=1)
    second = _bundle(generation=2)
    operator = _digest("operator")
    review = _digest("review")
    activator = AtomicPolicyActivator()

    activator.activate(
        GovernanceRecord(
            bundle_hash=first.digest,
            state=GovernanceState.SHADOW_APPROVED,
            operator_identity_hash=operator,
            reason="first",
            review_record_hash=review,
        )
    )
    activator.activate(
        GovernanceRecord(
            bundle_hash=second.digest,
            state=GovernanceState.SHADOW_APPROVED,
            operator_identity_hash=operator,
            reason="second",
            review_record_hash=review,
        )
    )

    rolled_back = activator.rollback(
        operator_identity_hash=operator,
        reason="bad rollout",
    )

    assert rolled_back.state is GovernanceState.ROLLED_BACK
    assert rolled_back.bundle_hash == first.digest
    assert activator.active == rolled_back


def test_pr143_live_submission_requires_operator_approval_hash() -> None:
    bundle = _bundle(approval=False)
    snapshot = AttemptPolicySnapshot(
        attempt_id="attempt-live",
        attempt_generation=1,
        policy_bundle_hash=bundle.digest,
        config_version="cfg-1",
        evidence_max_age_slots=64,
        registry_versions={},
        model_version="model-disabled",
        operator_approval_version="none",
        cluster_genesis="mainnet-genesis",
    )

    decision = validate_attempt_policy(snapshot, bundle, live_submission_requested=True)

    assert decision.submission_allowed is False
    assert decision.reason == "live_submission_requires_operator_approval"
