from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from aiohttp import ClientSession
import pytest

from src.canonical_readiness import PR174_SCHEMA_VERSION
from src.observability.active_management import (
    ActiveManagementHttpServer,
    SignedRuntimeStateProvider,
    validate_canonical_readiness_payload,
)
from src.observability.management_plane_pr170 import (
    ManagementPlanePolicy,
    RuntimeTruth,
    write_signed_state_snapshot,
)
from src.release_gate.materialized_evidence import (
    collect_materialized_artifacts,
    produce_materialized_evidence,
    verify_materialized_evidence,
    write_manifest_atomic,
)

pytestmark = pytest.mark.unit


def _canonical_readiness(*, paper_ready: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": PR174_SCHEMA_VERSION,
        "product_state": (
            "paper-review-ready" if paper_ready else "not-production-ready"
        ),
        "paper_capability": "review-ready" if paper_ready else "blocked",
        "live_capability": "blocked",
        "production_ready": False,
        "paper_ready": paper_ready,
        "live_ready": False,
        "requirements": [],
        "requirement_blockers": {} if paper_ready else {"runtime.paper": ["BLOCKED"]},
        "global_blockers": [],
        "legacy_reports": [],
        "evaluated_release": "release-test",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["state_hash"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _write_state(
    path: Path,
    *,
    key: bytes,
    token_policy_hash: str,
    generation: int = 7,
    paper_ready: bool = False,
) -> None:
    truth = RuntimeTruth(
        process_boot_id="boot-test",
        release_id="release-test",
        runtime_generation=generation,
        policy_bundle_hash=token_policy_hash,
        heartbeat_sequence=1,
        active_task_generation=0,
        live_enabled=False,
        trading_enabled=False,
    )
    write_signed_state_snapshot(
        path,
        truth,
        key,
        extra={
            "schema_version": "o1.container-runtime.v1",
            "pid": os.getpid(),
            "heartbeat_unix_ns": 1_700_000_000_000_000_000,
            "mode": "disabled",
            "diagnostic": "SAFE_IDLE_NO_EXECUTION",
            "canonical_readiness": _canonical_readiness(paper_ready=paper_ready),
        },
    )


def test_o1_canonical_readiness_rejects_caller_boolean_without_valid_hash() -> None:
    payload = _canonical_readiness(paper_ready=True)
    payload["paper_ready"] = False

    result = validate_canonical_readiness_payload(payload)

    assert result.ok is False
    assert result.reason == "CANONICAL_READINESS_HASH_INVALID"


@pytest.mark.enable_socket
@pytest.mark.asyncio
async def test_o1_management_protects_ready_and_consumes_signed_state(
    tmp_path: Path,
) -> None:
    key = b"state-signing-key-32-bytes-value!"
    policy_hash = "a" * 64
    token = "operator-token"
    state_path = tmp_path / "state.json"
    _write_state(state_path, key=key, token_policy_hash=policy_hash)
    provider = SignedRuntimeStateProvider(
        state_path,
        key,
        minimum_generation=7,
        expected_policy_bundle_hash=policy_hash,
    )
    policy = ManagementPlanePolicy(
        bind_host="127.0.0.1",
        bearer_token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        release_id="release-test",
        runtime_generation=7,
        policy_bundle_hash=policy_hash,
    )
    server = ActiveManagementHttpServer(
        provider,
        policy=policy,
        clock_ns=lambda: 1_700_000_000_000_000_000,
    )
    await server.start(port=0)
    try:
        async with ClientSession() as client:
            health = await client.get(f"{server.base_url}/health")
            assert health.status == 200
            health_payload = await health.json()
            assert set(health_payload) == {
                "generated_at_unix_ns",
                "ok",
                "schema_version",
                "status",
            }

            denied = await client.get(f"{server.base_url}/ready")
            assert denied.status == 401

            ready = await client.get(
                f"{server.base_url}/ready",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert ready.status == 503
            ready_payload = await ready.json()
            assert ready_payload["ok"] is False
            assert ready_payload["canonical_readiness"]["paper_ready"] is False
    finally:
        await server.stop()


@pytest.mark.enable_socket
@pytest.mark.asyncio
async def test_o1_tampered_or_stale_state_cannot_affect_readiness(
    tmp_path: Path,
) -> None:
    key = b"state-signing-key-32-bytes-value!"
    policy_hash = "b" * 64
    token = "operator-token"
    state_path = tmp_path / "state.json"
    _write_state(state_path, key=key, token_policy_hash=policy_hash, generation=6)
    provider = SignedRuntimeStateProvider(
        state_path,
        key,
        minimum_generation=7,
        expected_policy_bundle_hash=policy_hash,
    )
    policy = ManagementPlanePolicy(
        bearer_token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        release_id="release-test",
        runtime_generation=7,
        policy_bundle_hash=policy_hash,
    )
    server = ActiveManagementHttpServer(provider, policy=policy)
    await server.start(port=0)
    try:
        async with ClientSession() as client:
            response = await client.get(
                f"{server.base_url}/ready",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status == 503
            assert (await response.json())["reason"] == "state_generation_stale"

            wrapper = json.loads(state_path.read_text(encoding="utf-8"))
            wrapper["payload"]["runtime_generation"] = 99
            state_path.write_text(json.dumps(wrapper), encoding="utf-8")
            os.chmod(state_path, 0o600)
            response = await client.get(
                f"{server.base_url}/ready",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status == 503
            assert (await response.json())["reason"] == "state_mac_invalid"
    finally:
        await server.stop()


def test_o1_materialized_artifacts_recompute_real_files(tmp_path: Path) -> None:
    (tmp_path / "wheel.whl").write_bytes(b"wheel-bytes")
    artifacts = collect_materialized_artifacts(tmp_path, ("wheel.whl",))

    assert artifacts[0].size_bytes == len(b"wheel-bytes")
    assert artifacts[0].sha256 == hashlib.sha256(b"wheel-bytes").hexdigest()
    with pytest.raises(ValueError, match="relative child"):
        collect_materialized_artifacts(tmp_path, ("../outside",))


def test_o1_ed25519_manifest_verifies_and_detects_materialized_drift(
    tmp_path: Path,
) -> None:
    solders = pytest.importorskip("solders.keypair")
    keypair = solders.Keypair()
    key_path = tmp_path / "release-attestation-key.json"
    key_path.write_text(json.dumps(list(bytes(keypair))), encoding="utf-8")
    os.chmod(key_path, 0o600)
    artifact_path = tmp_path / "candidate.whl"
    artifact_path.write_bytes(b"candidate-wheel")
    manifest = produce_materialized_evidence(
        root=tmp_path,
        paths=("candidate.whl",),
        source_commit="1" * 40,
        policy_bundle_digest="2" * 64,
        producer_id="o1-release-builder",
        keypair_path=key_path,
        produced_at_unix_ns=123,
    )
    manifest_path = tmp_path / "release-evidence.json"
    write_manifest_atomic(manifest_path, manifest)

    accepted = verify_materialized_evidence(
        root=tmp_path,
        manifest_path=manifest_path,
        expected_policy_bundle_digest="2" * 64,
        expected_signer_pubkey=str(keypair.pubkey()),
    )
    assert accepted.accepted is True
    assert accepted.artifacts_verified == 1

    artifact_path.write_bytes(b"modified-wheel")
    rejected = verify_materialized_evidence(
        root=tmp_path,
        manifest_path=manifest_path,
        expected_policy_bundle_digest="2" * 64,
        expected_signer_pubkey=str(keypair.pubkey()),
    )
    assert rejected.accepted is False
    assert "MATERIALIZED_ARTIFACT_HASH_MISMATCH" in rejected.blockers
