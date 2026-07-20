from __future__ import annotations

import json

from src.config.runtime import load_runtime_config
from src.external_contracts.admission import evaluate_runtime_admission
from src.external_contracts.conformance import run_read_only_conformance
from src.external_contracts.models import ExternalContract
from src.external_contracts.registry import ExternalContractRegistry


def test_default_runtime_admission_is_denied() -> None:
    config = load_runtime_config()
    report = evaluate_runtime_admission(
        config, ExternalContractRegistry.load_default()
    )
    assert report.execution_allowed is False
    assert report.diagnostic == "disabled-contract-admission"
    assert {item.provider for item in report.providers} == {
        "jupiter",
        "jito",
        "marginfi",
    }


def test_conformance_skip_is_not_verified() -> None:
    contract = ExternalContract.model_validate(
        {
            "id": "jupiter.test",
            "provider": "jupiter",
            "status": "disabled-unverified",
            "capabilities": ["quote"],
            "official_source_url": "https://dev.jup.ag/docs",
            "source_ref": "test",
            "artifacts": [],
            "deployment_program_id": None,
            "cluster": "mainnet-beta",
            "conformance_probe": {
                "url": "https://dev.jup.ag/test",
                "credential_env": None,
                "expected_status": 200,
                "required_json_paths": ["data.outAmount"],
            },
            "notes": "test",
        }
    )
    result = run_read_only_conformance(contract, enable_online=False)
    assert result.state == "skipped-not-enabled"
    assert result.verified is False


def test_conformance_asserts_status_and_json_paths() -> None:
    contract = ExternalContract.model_validate(
        {
            "id": "jupiter.test",
            "provider": "jupiter",
            "status": "disabled-unverified",
            "capabilities": ["quote"],
            "official_source_url": "https://dev.jup.ag/docs",
            "source_ref": "test",
            "artifacts": [],
            "deployment_program_id": None,
            "cluster": "mainnet-beta",
            "conformance_probe": {
                "url": "https://dev.jup.ag/test",
                "credential_env": None,
                "expected_status": 200,
                "required_json_paths": ["data.outAmount"],
            },
            "notes": "test",
        }
    )

    def transport(_url, _headers):
        return 200, json.dumps({"data": {"outAmount": "42"}}).encode()

    result = run_read_only_conformance(
        contract, enable_online=True, transport=transport
    )
    assert result.state == "verified"
    assert result.verified is True
