from __future__ import annotations

import copy

import pytest

from src.production_sandbox_pr200 import (
    PR200_SCHEMA_VERSION,
    PR200SandboxError,
    live_capability_allowed,
    validate_production_sandbox_manifest,
)

_DIGEST = "a" * 64
_OTHER_DIGEST = "b" * 64


def _manifest() -> dict[str, object]:
    return {
        "schema_version": PR200_SCHEMA_VERSION,
        "artifact_hashes": {
            "source_commit_sha": "1" * 64,
            "wheel_sha256": "2" * 64,
            "runtime_image_digest": "3" * 64,
            "sbom_sha256": "4" * 64,
            "config_generation_hash": "5" * 64,
            "protocol_registry_hash": "6" * 64,
        },
        "egress": {
            "deny_by_default": True,
            "allowed_origins": [
                "https://api.mainnet-beta.solana.com",
                "https://api.jup.ag",
                "https://mainnet.block-engine.jito.wtf",
                "https://webhook.helius.xyz",
            ],
        },
        "services": [
            {
                "name": "runtime",
                "role": "runtime",
                "image": f"ghcr.io/bobivans/flashloan-runtime@sha256:{_DIGEST}",
                "read_only_root": True,
                "no_new_privileges": True,
                "cap_drop_all": True,
                "arbitrary_internet": False,
                "can_read_signer_key": False,
                "secret_sources": ["secret-manager://flashloan/runtime-env"],
                "networks": ["runtime-egress"],
            },
            {
                "name": "signer",
                "role": "signer",
                "image": f"ghcr.io/bobivans/flashloan-signer@sha256:{_OTHER_DIGEST}",
                "read_only_root": True,
                "no_new_privileges": True,
                "cap_drop_all": True,
                "arbitrary_internet": False,
                "can_read_signer_key": True,
                "secret_sources": ["keychain://flashloan/canary-signer"],
                "networks": ["signer-ipc"],
            },
        ],
        "active_submitters": 1,
        "live_enabled": False,
        "signer_key_exportable": False,
        "signed_release_pointer": True,
        "rollback_rehearsed": True,
        "outstanding_attempts_reconciled": True,
    }


def _codes(report) -> set[str]:
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_pr200_accepts_digest_pinned_deny_default_isolated_manifest() -> None:
    report = validate_production_sandbox_manifest(_manifest())

    assert report.ok is True
    assert report.diagnostics == ()
    assert len(report.manifest_hash) == 64
    assert live_capability_allowed() is False


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("ghcr.io/bobivans/flashloan-runtime:latest", "pinned"),
        (f"ghcr.io/bobivans/flashloan-runtime:latest@sha256:{_DIGEST}", "mutable"),
        ("ghcr.io/bobivans/flashloan-runtime:not-a-digest@sha256:abc", "digest"),
    ],
)
def test_pr200_rejects_mutable_or_unpinned_images(image: str, expected: str) -> None:
    manifest = _manifest()
    services = copy.deepcopy(manifest["services"])
    services[0]["image"] = image
    manifest["services"] = services

    with pytest.raises(PR200SandboxError, match=expected):
        validate_production_sandbox_manifest(manifest)


def test_pr200_rejects_example_secret_sources() -> None:
    manifest = _manifest()
    services = copy.deepcopy(manifest["services"])
    services[0]["secret_sources"] = ["./runtime.env.example"]
    manifest["services"] = services

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "EXAMPLE_SECRET_SOURCE" in _codes(report)


def test_pr200_rejects_runtime_access_to_signer_key() -> None:
    manifest = _manifest()
    services = copy.deepcopy(manifest["services"])
    services[0]["can_read_signer_key"] = True
    manifest["services"] = services

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "RUNTIME_CAN_READ_SIGNER_KEY" in _codes(report)


def test_pr200_rejects_signer_with_arbitrary_internet() -> None:
    manifest = _manifest()
    services = copy.deepcopy(manifest["services"])
    services[1]["arbitrary_internet"] = True
    manifest["services"] = services

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "SIGNER_HAS_ARBITRARY_INTERNET" in _codes(report)


def test_pr200_rejects_non_deny_default_network_policy() -> None:
    manifest = _manifest()
    manifest["egress"] = {"deny_by_default": False, "allowed_origins": []}

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "EGRESS_NOT_DENY_BY_DEFAULT" in _codes(report)
    assert "EGRESS_ALLOWLIST_EMPTY" in _codes(report)


def test_pr200_rejects_multiple_active_submitters() -> None:
    manifest = _manifest()
    manifest["active_submitters"] = 2

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "ACTIVE_SUBMITTER_FENCE_INVALID" in _codes(report)


def test_pr200_rejects_live_enablement_in_foundation_slice() -> None:
    manifest = _manifest()
    manifest["live_enabled"] = True

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "LIVE_ENABLEMENT_OUT_OF_SCOPE" in _codes(report)
    assert live_capability_allowed() is False


def test_pr200_rejects_incomplete_release_and_rollback_evidence() -> None:
    manifest = _manifest()
    manifest["signed_release_pointer"] = False
    manifest["rollback_rehearsed"] = False
    manifest["outstanding_attempts_reconciled"] = False

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "UNSIGNED_RELEASE_POINTER" in _codes(report)
    assert "ROLLBACK_NOT_REHEARSED" in _codes(report)
    assert "OUTSTANDING_ATTEMPTS_NOT_RECONCILED" in _codes(report)


def test_pr200_rejects_missing_artifact_hashes() -> None:
    manifest = _manifest()
    manifest["artifact_hashes"] = {"source_commit_sha": "1" * 64}

    report = validate_production_sandbox_manifest(manifest)

    assert report.ok is False
    assert "ARTIFACT_HASH_MISSING" in _codes(report)
