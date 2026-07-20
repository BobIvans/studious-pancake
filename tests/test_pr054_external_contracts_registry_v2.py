from __future__ import annotations

import json

from src.external_contracts.conformance import run_read_only_conformance
from src.external_contracts.drift import detect_drift
from src.external_contracts.models import (
    ConformanceProbe,
    ExternalContractRegistryModel,
)
from src.external_contracts.registry import ExternalContractRegistry


def test_pr054_default_registry_v2_has_explicit_promotion_gates() -> None:
    registry = ExternalContractRegistry.load_default()
    payload = registry.status_payload()

    assert payload["schema_version"] == "pr054.external-contracts.v2"
    assert payload["execution_allowed"] is False
    assert payload["execution_contracts"] == []

    by_id = {item["id"]: item for item in payload["contracts"]}
    assert by_id["jupiter.swap-v2-build"]["promotion_state"] == (
        "credentialed-conformance-pending"
    )
    assert (
        by_id["jupiter.swap-v2-build"]["evidence"]["local_artifact_integrity"]
        is True
    )
    assert by_id["jupiter.swap-v2-build"]["evidence"]["execution_conformance"] is False
    assert by_id["jito.low-latency-json-rpc"]["credential_mode"] == "optional-uuid"
    assert by_id["openocean.solana-v4-quote"]["required_env"] == [
        "OPENOCEAN_API_KEY"
    ]


def test_pr054_drift_report_does_not_promote_from_local_hashes() -> None:
    registry = ExternalContractRegistry.load_default()
    report = detect_drift(registry).to_dict()

    assert report["schema_version"] == "pr054.contract-drift.v2"
    assert report["ok"] is True
    assert report["execution_allowed"] is False
    assert report["diagnostic"] == "blocked-no-execution-conformance"

    states = {item["contract_id"]: item for item in report["contract_states"]}
    assert states["jupiter.swap-v2-build"]["local_artifact_integrity"] is True
    assert states["jupiter.swap-v2-build"]["remote_schema_freshness"] is False
    assert states["jupiter.swap-v2-build"]["execution_allowed"] is False


def test_pr054_online_probe_skips_when_required_credentials_missing() -> None:
    registry = ExternalContractRegistry.load_default()
    contract = registry.get("jupiter.swap-v2-build")

    result = run_read_only_conformance(
        contract, enable_online=True, environ={}, transport=lambda *_: (200, b"{}")
    )

    assert result.state == "skipped-missing-env"
    assert result.verified is False
    assert "JUPITER_API_KEY" in (result.error or "")


def test_pr054_jito_optional_uuid_probe_can_run_without_secret() -> None:
    registry = ExternalContractRegistry.load_default()
    contract = registry.get("jito.low-latency-json-rpc")

    def transport(_url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        assert "x-jito-auth" not in headers
        return 200, b"not-json-is-ok-when-no-json-paths-are-required"

    result = run_read_only_conformance(
        contract, enable_online=True, environ={}, transport=transport
    )

    assert result.state == "verified"
    assert result.verified is True
    assert "credential-mode:optional-uuid" in result.assertions


def test_pr054_okx_signed_probe_uses_signed_headers_and_redacts_secret() -> None:
    registry = ExternalContractRegistry.load_default()
    contract = registry.get("okx.solana-swap-instruction-v6")
    observed_headers: dict[str, str] = {}

    def transport(_url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        observed_headers.update(headers)
        return 200, json.dumps({"code": "0", "data": []}).encode("utf-8")

    result = run_read_only_conformance(
        contract,
        enable_online=True,
        environ={
            "OKX_API_KEY": "okx-key",
            "OKX_SECRET_KEY": "super-secret",
            "OKX_API_PASSPHRASE": "passphrase",
        },
        transport=transport,
    )

    assert result.state == "verified"
    assert result.verified is True
    assert observed_headers["OK-ACCESS-KEY"] == "okx-key"
    assert observed_headers["OK-ACCESS-PASSPHRASE"] == "passphrase"
    assert "OK-ACCESS-SIGN" in observed_headers
    assert "super-secret" not in repr(result.to_dict())


def test_pr054_registry_model_accepts_legacy_v1_schema_for_old_fixtures() -> None:
    model = ExternalContractRegistryModel.model_validate(
        {
            "schema_version": "pr027.external-contracts.v1",
            "contracts": [
                {
                    "id": "jito.legacy",
                    "provider": "jito",
                    "status": "disabled-unverified",
                    "capabilities": ["read-only-rpc"],
                    "official_source_url": "https://docs.jito.wtf/lowlatencytxnsend/",
                    "source_ref": "legacy-fixture",
                    "artifacts": [],
                    "deployment_program_id": None,
                    "cluster": "mainnet-beta",
                    "conformance_probe": None,
                    "notes": "legacy shape still parses for focused unit tests",
                }
            ],
        }
    )

    assert model.schema_version == "pr027.external-contracts.v1"
    assert model.contracts[0].promotion_state == "local-artifact-integrity-only"


def test_pr054_conformance_probe_rejects_undeclared_header_env() -> None:
    try:
        ConformanceProbe.model_validate(
            {
                "url": "https://api.example.test/probe",
                "credential_mode": "header-api-key",
                "required_env": ["EXAMPLE_API_KEY"],
                "credential_header_name": "x-api-key",
                "credential_header_env": "OTHER_API_KEY",
            }
        )
    except ValueError as exc:
        assert "credential_header_env" in str(exc)
    else:
        raise AssertionError("undeclared credential header env should be rejected")
