from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.shadow_soak.evidence import (
    MINIMUM_SOAK_SECONDS,
    ShadowSoakError,
    SoakEnvironment,
)
from src.shadow_soak.pr092_actual_soak import REQUIRED_PR092_ARTIFACTS
from src.shadow_soak.pr105_harness import (
    PR105HarnessRunSnapshot,
    PR105HarnessState,
    PR105ShadowSoakHarnessConfig,
    build_pr105_shadow_soak_harness,
    evaluate_pr105_harness_snapshot,
)

GIT_SHA = "1234567890abcdef1234567890abcdef12345678"
STARTED_AT = datetime(2026, 7, 21, 0, 0, tzinfo=UTC)


def _config(**overrides) -> PR105ShadowSoakHarnessConfig:
    data = {
        "run_id": "pr105-real-shadow-soak-001",
        "code_commit": GIT_SHA,
        "operator": "shadow-operator",
        "started_at": STARTED_AT,
        "environment": SoakEnvironment.SHADOW,
    }
    data.update(overrides)
    return PR105ShadowSoakHarnessConfig(**data)


def _snapshot(plan, **overrides) -> PR105HarnessRunSnapshot:
    data = {
        "run_id": plan.run_id,
        "observed_at": STARTED_AT + timedelta(seconds=MINIMUM_SOAK_SECONDS + 1),
        "started_at": STARTED_AT,
        "ended_at": STARTED_AT + timedelta(seconds=MINIMUM_SOAK_SECONDS + 1),
        "events_recorded": 25,
        "candidates_seen": 3,
        "materialized_artifact_paths": tuple(
            artifact.path for artifact in plan.artifacts
        ),
        "replay_verified": True,
        "operator_review_recorded": True,
        "sender_imports_observed": False,
        "submission_endpoints_enabled": False,
        "live_submissions_observed": 0,
    }
    data.update(overrides)
    return PR105HarnessRunSnapshot(**data)


def test_pr105_plan_is_sender_free_and_targets_pr092_artifacts() -> None:
    plan = build_pr105_shadow_soak_harness(_config())

    assert plan.state is PR105HarnessState.READY_TO_START
    assert plan.live_allowed is False
    assert plan.sender_enabled is False
    assert plan.submission_endpoints_enabled is False
    assert plan.pr092_evidence_claimed is False
    assert set(plan.required_pr092_prerequisites)
    assert {artifact.kind for artifact in plan.artifacts} == set(
        REQUIRED_PR092_ARTIFACTS
    )
    assert all(
        artifact.path.startswith("artifacts/pr105/pr105-real-shadow-soak-001/")
        for artifact in plan.artifacts
    )


def test_pr105_rejects_recorded_fixture_environment() -> None:
    with pytest.raises(ShadowSoakError, match="recorded fixtures"):
        _config(environment=SoakEnvironment.RECORDED)


def test_pr105_unsafe_sender_or_live_flags_block_plan() -> None:
    plan = build_pr105_shadow_soak_harness(
        _config(
            sender_enabled=True,
            live_submission_enabled=True,
            submission_endpoints_enabled=True,
        )
    )

    assert plan.state is PR105HarnessState.BLOCKED
    assert "SENDER_ENABLED" in plan.blockers
    assert "LIVE_SUBMISSION_ENABLED" in plan.blockers
    assert "SUBMISSION_ENDPOINTS_ENABLED" in plan.blockers
    assert plan.live_allowed is False


def test_pr105_running_snapshot_before_72h_is_not_pr092_ready() -> None:
    plan = build_pr105_shadow_soak_harness(_config())
    result = evaluate_pr105_harness_snapshot(
        plan,
        _snapshot(
            plan,
            observed_at=STARTED_AT + timedelta(hours=6),
            ended_at=None,
            replay_verified=False,
        ),
    )

    assert result.state is PR105HarnessState.RUNNING
    assert result.ready_for_pr092_assembly is False
    assert "PR105_DURATION_BELOW_72H" in result.blockers
    assert "PR105_RUN_NOT_FINALIZED" in result.blockers
    assert "REPLAY_NOT_VERIFIED" in result.blockers
    assert result.live_allowed is False
    assert result.runtime_submission_enabled is False


def test_pr105_missing_materialized_artifacts_block_assembly() -> None:
    plan = build_pr105_shadow_soak_harness(_config())
    result = evaluate_pr105_harness_snapshot(
        plan,
        _snapshot(plan, materialized_artifact_paths=()),
    )

    assert result.state is PR105HarnessState.BLOCKED
    assert result.ready_for_pr092_assembly is False
    assert result.missing_artifact_paths == tuple(
        artifact.path for artifact in plan.artifacts
    )
    assert any(
        blocker.startswith("ARTIFACT_NOT_MATERIALIZED:")
        for blocker in result.blockers
    )


def test_pr105_complete_harness_only_allows_pr092_assembly_not_live() -> None:
    plan = build_pr105_shadow_soak_harness(
        _config(duration_seconds=MINIMUM_SOAK_SECONDS + 600)
    )
    result = evaluate_pr105_harness_snapshot(plan, _snapshot(plan))

    assert result.state is PR105HarnessState.READY_FOR_PR092_ASSEMBLY
    assert result.ready_for_pr092_assembly is True
    assert result.live_allowed is False
    assert result.runtime_submission_enabled is False
    assert result.blockers == ()
    assert result.to_dict()["live_allowed"] is False


def test_pr105_observed_sender_or_submission_blocks_even_after_72h() -> None:
    plan = build_pr105_shadow_soak_harness(_config())
    result = evaluate_pr105_harness_snapshot(
        plan,
        _snapshot(
            plan,
            sender_imports_observed=True,
            submission_endpoints_enabled=True,
            live_submissions_observed=1,
        ),
    )

    assert "SENDER_IMPORT_OBSERVED" in result.blockers
    assert "SUBMISSION_ENDPOINT_ENABLED" in result.blockers
    assert "LIVE_SUBMISSIONS_OBSERVED" in result.blockers
    assert result.live_allowed is False


def test_pr105_run_id_cannot_be_fixture_slug() -> None:
    with pytest.raises(ShadowSoakError, match="fixture"):
        _config(run_id="fixture-pr105-shadow-soak")
