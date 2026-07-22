from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from src.observability.management_plane_pr170 import (
    ManagementDecision,
    ManagementPlanePolicy,
    ManagementReason,
    ManagementSurface,
    RuntimeTruth,
    SnapshotErrorCode,
    authorize_surface,
    build_ingress_limits,
    build_public_liveness_payload,
    is_external_bind,
    read_signed_state_snapshot,
    write_signed_state_snapshot,
)

SHA = "a" * 64
KEY = b"local-test-key"


def _truth(*, generation: int = 7, policy_hash: str = SHA) -> RuntimeTruth:
    return RuntimeTruth(
        process_boot_id="boot-123",
        release_id="release-2026-07-22",
        runtime_generation=generation,
        policy_bundle_hash=policy_hash,
        heartbeat_sequence=10,
        active_task_generation=4,
    )


def test_pr170_external_bind_requires_authenticated_proxy_and_token() -> None:
    policy = ManagementPlanePolicy(bind_host="0.0.0.0", policy_bundle_hash=SHA)

    decision = authorize_surface(policy, ManagementSurface.LIVENESS)

    assert decision.decision is ManagementDecision.DENY
    assert (
        decision.reason
        is ManagementReason.EXTERNAL_BIND_REQUIRES_AUTHENTICATED_PROXY
    )
    assert is_external_bind("::") is True


def test_pr170_loopback_liveness_is_minimal_and_no_topology() -> None:
    policy = ManagementPlanePolicy(bind_host="127.0.0.1", policy_bundle_hash=SHA)

    decision = authorize_surface(policy, ManagementSurface.LIVENESS)
    payload = build_public_liveness_payload(ok=True, now_ns=123)

    assert decision.allowed is True
    assert payload == {
        "schema_version": "pr170.liveness.v1",
        "ok": True,
        "status": "ok",
        "generated_at_unix_ns": 123,
    }
    assert "pid" not in json.dumps(payload)
    assert "wallet" not in json.dumps(payload)
    assert "provider" not in json.dumps(payload)


def test_pr170_metrics_and_operator_status_require_token() -> None:
    token = "operator-token"
    token_hash = __import__("hashlib").sha256(token.encode()).hexdigest()
    policy = ManagementPlanePolicy(
        bind_host="127.0.0.1",
        bearer_token_sha256=token_hash,
        policy_bundle_hash=SHA,
    )

    denied = authorize_surface(policy, ManagementSurface.OPERATOR_STATUS)
    wrong = authorize_surface(
        policy, ManagementSurface.METRICS, bearer_token="wrong-token"
    )
    allowed = authorize_surface(policy, ManagementSurface.METRICS, bearer_token=token)

    assert denied.reason is ManagementReason.TOKEN_REQUIRED
    assert wrong.reason is ManagementReason.TOKEN_INVALID
    assert allowed.allowed is True


def test_pr170_signed_state_snapshot_is_owner_only_and_verified(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"

    write_signed_state_snapshot(path, _truth(), KEY)
    result = read_signed_state_snapshot(
        path,
        KEY,
        minimum_generation=7,
        expected_policy_bundle_hash=SHA,
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload["runtime_generation"] == 7
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_pr170_state_tamper_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    write_signed_state_snapshot(path, _truth(), KEY)
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["payload"]["live_enabled"] = True
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    path.chmod(0o600)

    result = read_signed_state_snapshot(
        path,
        KEY,
        minimum_generation=7,
        expected_policy_bundle_hash=SHA,
    )

    assert result.ok is False
    assert result.reason is SnapshotErrorCode.STATE_MAC_INVALID


def test_pr170_stale_generation_and_policy_mismatch_are_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.json"
    write_signed_state_snapshot(path, _truth(generation=6), KEY)

    stale = read_signed_state_snapshot(
        path,
        KEY,
        minimum_generation=7,
        expected_policy_bundle_hash=SHA,
    )
    mismatch = read_signed_state_snapshot(
        path,
        KEY,
        minimum_generation=6,
        expected_policy_bundle_hash="b" * 64,
    )

    assert stale.reason is SnapshotErrorCode.STATE_GENERATION_STALE
    assert mismatch.reason is SnapshotErrorCode.STATE_POLICY_MISMATCH


def test_pr170_open_file_mode_is_not_authoritative(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    write_signed_state_snapshot(path, _truth(), KEY)
    path.chmod(0o644)

    result = read_signed_state_snapshot(
        path,
        KEY,
        minimum_generation=7,
        expected_policy_bundle_hash=SHA,
    )

    assert result.ok is False
    assert result.reason is SnapshotErrorCode.STATE_FILE_MODE_TOO_OPEN


def test_pr170_ingress_limits_are_machine_readable() -> None:
    policy = ManagementPlanePolicy(
        max_connections=3,
        request_timeout_seconds=1.25,
        max_response_bytes=4096,
        policy_bundle_hash=SHA,
    )

    limits = build_ingress_limits(policy)

    assert limits.max_connections == 3
    assert limits.request_timeout_seconds == 1.25
    assert limits.max_response_bytes == 4096
    assert limits.security_headers["X-Content-Type-Options"] == "nosniff"


def test_pr170_admin_mutation_is_disabled_by_default() -> None:
    policy = ManagementPlanePolicy(policy_bundle_hash=SHA)

    decision = authorize_surface(policy, ManagementSurface.ADMIN_MUTATION)

    assert decision.allowed is False
    assert decision.reason is ManagementReason.ADMIN_MUTATION_DISABLED


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", False),
        ("localhost", False),
        ("::1", False),
        ("0.0.0.0", True),
        ("::", True),
        ("192.0.2.10", True),
    ],
)
def test_pr170_bind_classification(host: str, expected: bool) -> None:
    assert is_external_bind(host) is expected
