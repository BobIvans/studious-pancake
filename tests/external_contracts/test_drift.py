from __future__ import annotations

import hashlib
import json

from src.external_contracts.drift import detect_drift
from src.external_contracts.registry import ExternalContractRegistry


def _write_registry(tmp_path, artifact_bytes: bytes):
    artifact = tmp_path / "contracts" / "marginfi" / "fixture.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(artifact_bytes)
    sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    payload = {
        "schema_version": "pr054.external-contracts.v2",
        "contracts": [
            {
                "id": "marginfi.test",
                "provider": "marginfi",
                "status": "disabled-unverified",
                "capabilities": ["protocol-source"],
                "official_source_url": "https://github.com/mrgnlabs/marginfi-v2",
                "source_ref": "test-ref",
                "artifacts": [
                    {
                        "path": "contracts/marginfi/fixture.bin",
                        "sha256": sha256,
                        "kind": "golden-bytes",
                        "fetched_at": "2026-07-20T11:55:00Z",
                        "required": True,
                    }
                ],
                "deployment_program_id": None,
                "cluster": "mainnet-beta",
                "conformance_probe": None,
                "promotion_state": "local-artifact-integrity-only",
                "evidence": {
                    "local_artifact_integrity": True,
                    "remote_schema_freshness": False,
                    "credentialed_api_conformance": False,
                    "deployed_program_attestation": False,
                    "execution_conformance": False,
                    "promotion_evidence": False,
                },
                "notes": "test",
            }
        ],
    }
    registry_path = tmp_path / "external_contracts.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path, artifact


def test_drift_report_changes_to_fail_closed(tmp_path) -> None:
    registry_path, artifact = _write_registry(tmp_path, b"pinned")
    registry = ExternalContractRegistry.load(registry_path, artifact_root=tmp_path)
    clean = detect_drift(registry)
    assert clean.ok is True
    assert clean.execution_allowed is False
    assert clean.diagnostic == "blocked-no-execution-conformance"
    assert clean.contract_states[0].local_artifact_integrity is True
    assert clean.contract_states[0].execution_allowed is False

    artifact.write_bytes(b"changed")
    drifted = detect_drift(registry)
    assert drifted.ok is False
    assert drifted.execution_allowed is False
    assert drifted.diagnostic == "disabled-contract-drift"
    assert drifted.findings[0].state == "mismatch"
    assert drifted.contract_states[0].local_artifact_integrity is False
