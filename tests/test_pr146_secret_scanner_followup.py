from __future__ import annotations

import pytest

from src.security.secret_scan import (
    PlaintextKeyMaterialError,
    assert_no_plaintext_key_material,
    scan_text_for_key_material,
)


def test_secret_metadata_names_are_not_treated_as_credentials() -> None:
    assert_no_plaintext_key_material(
        {
            "SECRET_LOCATOR_DOMAIN": "pr146.secret-locator-domain.v1",
            "CREDENTIAL_REFERENCE_DOMAIN": "pr146.credential-reference-domain.v1",
            "TOKEN_LOCATOR_REF": "env:SAFE_TOKEN_REFERENCE",
        },
        source="unit",
    )


def test_code_references_without_literal_fallbacks_are_allowed() -> None:
    source = "\n".join(
        (
            "api_key = settings.api_key",
            "auth_token = os.getenv('AUTH_TOKEN')",
            "client_secret = secrets.get('client_secret')",
            "password = env_values['PASSWORD']",
            "access_token = provider_token_shape",
        )
    )

    assert scan_text_for_key_material(source, source="code") == ()


def test_literal_fallback_inside_lookup_expression_fails_closed() -> None:
    source = (
        "api_key = os.getenv('MISTRAL_API_KEY', "
        "'tok_A1B2C3D4E5F6G7H8I9J0K1L2')"
    )

    findings = scan_text_for_key_material(source, source="code")

    assert {finding.reason for finding in findings} == {
        "literal credential in secret-named field"
    }


def test_literal_provider_token_inside_lookup_expression_fails_closed() -> None:
    provider_token = "sk" + "-" + ("A1b2C3d4E5f6G7h8" * 2)
    source = f"api_key = os.getenv('OPENAI_API_KEY', '{provider_token}')"

    with pytest.raises(PlaintextKeyMaterialError) as exc_info:
        assert_no_plaintext_key_material(source, source="code")

    assert provider_token not in str(exc_info.value)
    assert "literal credential in secret-named field" in str(exc_info.value)


def test_real_mapping_credential_still_fails_closed() -> None:
    credential = "tok_A1B2C3D4E5F6G7H8I9J0K1L2"

    with pytest.raises(PlaintextKeyMaterialError):
        assert_no_plaintext_key_material(
            {"REAL_API_KEY": credential},
            source="unit",
        )
