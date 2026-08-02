from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SIGNER = ROOT / "deployment" / "signer"


def test_signer_artifact_is_separate_minimal_and_non_root() -> None:
    dockerfile = (SIGNER / "Dockerfile").read_text()
    assert "COPY isolated_signer_service" in dockerfile
    assert "COPY src" not in dockerfile
    assert "--no-deps" in dockerfile
    assert "USER 65532:65532" in dockerfile
    assert "flashloan-isolated-signer" in dockerfile


def test_signer_has_no_network_egress_or_writable_filesystem() -> None:
    network = yaml.safe_load((SIGNER / "network-policy.yaml").read_text())
    spec = network["spec"]
    assert spec["policyTypes"] == ["Ingress", "Egress"]
    assert spec["ingress"] == []
    assert spec["egress"] == []

    filesystem = json.loads((SIGNER / "filesystem-policy.json").read_text())
    assert filesystem["readOnlyRootFilesystem"] is True
    assert filesystem["runAsNonRoot"] is True
    assert filesystem["allowPrivilegeEscalation"] is False
    assert filesystem["writableMounts"] == []


def test_missing_real_image_signature_and_keystore_fail_closed() -> None:
    attestation = json.loads((SIGNER / "artifact-attestation.json").read_text())
    assert attestation["base_image_digest"] is None
    assert attestation["artifact_digest"] is None
    assert attestation["artifact_signature"] is None
    assert attestation["isolated_keystore_attestation"] is None
    assert attestation["signer_allowed"] is False
    assert attestation["canary_allowed"] is False
    assert attestation["blocker"] == (
        "SIGNER_IMAGE_BASE_DIGEST_BUILD_DIGEST_OR_SIGNATURE_MISSING"
    )


def test_capability_manifest_excludes_key_network_and_transaction_authority() -> None:
    capabilities = json.loads((SIGNER / "capabilities.json").read_text())
    assert capabilities["private_key_loader"] is False
    assert capabilities["network_egress"] == []
    assert capabilities["direct_provider_access"] is False
    assert capabilities["direct_rpc_access"] is False
    assert capabilities["build_transactions"] is False
    assert capabilities["general_application_imports"] is False
    assert capabilities["status_only"] is True
