from __future__ import annotations

from pathlib import Path

import pytest

from scripts.security_gate import _iter_scan_files
from src.security.secret_scan import (
    PlaintextKeyMaterialError,
    assert_no_plaintext_key_material,
    scan_text_for_key_material,
)


def _google_key_fixture() -> str:
    return "AIza" + "AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"


def _generic_token_fixture() -> str:
    return "tok_" + ("A1b2C3d4E5" * 4)


def test_pr112_litellm_production_config_is_removed_and_example_is_reference_only() -> (
    None
):
    production = Path("litellm_config.yaml")
    example = Path("litellm_config.example.yaml")

    assert not production.exists()
    text = example.read_text(encoding="utf-8")
    assert "api_key: os.environ/" in text
    assert scan_text_for_key_material(text, source=str(example)) == ()


def test_pr112_generic_api_key_field_is_detected_without_value_leakage() -> None:
    literal = _google_key_fixture()
    text = "api_" + "key: " + literal

    findings = scan_text_for_key_material(text, source="litellm_config.yaml")

    assert findings
    assert {finding.reason for finding in findings} >= {
        "literal credential in secret-named field",
        "provider API token shaped value",
    }
    assert literal not in "; ".join(finding.redacted_message() for finding in findings)


def test_pr112_secret_named_mapping_values_are_detected_without_value_leakage() -> None:
    literal = _generic_token_fixture()

    with pytest.raises(PlaintextKeyMaterialError) as exc_info:
        assert_no_plaintext_key_material(
            {"MISTRAL_API_KEY": literal},
            source="operator-env",
        )

    message = str(exc_info.value)
    assert "MISTRAL_API_KEY" in message
    assert "literal credential in secret-named field" in message
    assert literal not in message


def test_pr112_safe_secret_references_are_not_reported() -> None:
    for value in (
        "env:GEMINI_API_KEY",
        "file:/run/secrets/mistral_api_key",
        "keychain:flashloan/litellm/mistral",
        "os.environ/GEMINI_API_KEY",
        "${OPENOCEAN_API_KEY}",
    ):
        assert scan_text_for_key_material(value, source="reference") == ()


def test_pr112_security_gate_scans_root_litellm_files(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "security_supply_chain_policy.json").write_text(
        '{"schema_version":"pr043.security-supply-chain-policy.v1"}',
        encoding="utf-8",
    )
    (tmp_path / "litellm_config.yaml").write_text(
        "model_list:\n- litellm_params:\n    api_key: os.environ/GEMINI_API_KEY\n",
        encoding="utf-8",
    )

    scanned = {
        path.relative_to(tmp_path).as_posix() for path in _iter_scan_files(tmp_path)
    }

    assert "litellm_config.yaml" in scanned


def test_pr112_incident_manifest_schema_is_redacted() -> None:
    schema = Path("config/security/pr112_credential_incident_manifest.schema.json")
    text = schema.read_text(encoding="utf-8")

    assert "credential_value" not in text
    assert "sha256" not in text
    assert "reversible" not in text.lower()
    assert "rotation_status" in text
