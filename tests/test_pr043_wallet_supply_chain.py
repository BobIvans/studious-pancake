from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from src.config.chain_registry import SYSTEM_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS
from src.config.runtime import ConfigurationLoadError, load_runtime_config
from src.security.secret_scan import (
    PlaintextKeyMaterialError,
    assert_no_plaintext_key_material,
    scan_text_for_key_material,
)
from src.security.signer_policy import (
    SignerPolicyError,
    UnsignedMessage,
    build_signer_policy,
)
from src.security.supply_chain import (
    DependencyAuditPolicy,
    Severity,
    VulnerabilityRecord,
)


def _solana_keypair_fixture() -> str:
    return "[" + ",".join(str(index % 256) for index in range(64)) + "]"


def test_production_config_rejects_inline_private_key(tmp_path: Path) -> None:
    config_path = tmp_path / "live-inline-key.yaml"
    config_path.write_text(
        "\n".join(
            (
                "runtime:",
                "  mode: live",
                "wallet:",
                "  signer_reference: this-is-private-key-material",
                "validation:",
                "  verify_rpc_at_startup: true",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationLoadError, match="inline secrets are forbidden"):
        load_runtime_config(config_path, environ={})


def test_plaintext_key_scanner_flags_keypair_without_leaking_value() -> None:
    key_material = _solana_keypair_fixture()

    with pytest.raises(PlaintextKeyMaterialError) as exc_info:
        assert_no_plaintext_key_material(
            {"SOLANA_PRIVATE_KEY": key_material},
            source="production-env",
        )

    message = str(exc_info.value)
    assert "SOLANA_PRIVATE_KEY" in message
    assert "plaintext wallet/signing key material" in message
    assert key_material not in message


def test_unsigned_message_must_pass_signer_policy_before_signing() -> None:
    policy = build_signer_policy((SYSTEM_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS))
    message = UnsignedMessage(
        message_bytes=b"unsigned-v0-message",
        program_ids=(SYSTEM_PROGRAM_ADDRESS,),
        min_context_slot=42,
    )
    expected_hash = sha256(message.message_bytes).hexdigest()

    permit = policy.evaluate(
        unsigned_message=message,
        signer_reference="file:/var/run/flashloan/signer.sock",
        expected_message_sha256=expected_hash,
        now=123.0,
    )

    assert permit.message_sha256 == expected_hash
    assert permit.signer_reference_scheme == "file"
    assert permit.issued_at == 123.0


def test_signer_policy_rejects_malicious_program_and_swapped_message() -> None:
    policy = build_signer_policy((SYSTEM_PROGRAM_ADDRESS,))

    with pytest.raises(SignerPolicyError, match="non-allowlisted programs"):
        policy.evaluate(
            unsigned_message=UnsignedMessage(
                message_bytes=b"unsigned-v0-message",
                program_ids=("Malicious111111111111111111111111111111111",),
            ),
            signer_reference="keychain:flashloan/signer",
        )

    with pytest.raises(SignerPolicyError, match="hash does not match"):
        policy.evaluate(
            unsigned_message=UnsignedMessage(
                message_bytes=b"tampered-message",
                program_ids=(SYSTEM_PROGRAM_ADDRESS,),
            ),
            signer_reference="keychain:flashloan/signer",
            expected_message_sha256=sha256(b"original-message").hexdigest(),
        )


def test_dependency_critical_cve_gate_blocks_promotion() -> None:
    decision = DependencyAuditPolicy().evaluate(
        (
            VulnerabilityRecord(
                package="requests",
                vulnerability_id="CVE-2099-0001",
                severity=Severity.CRITICAL,
                fixed_versions=("99.0.1",),
                source="normalized-pip-audit",
            ),
        )
    )

    assert decision.allowed is False
    assert decision.blockers == (
        "requests:CVE-2099-0001:severity=critical:"
        "fixed=99.0.1:source=normalized-pip-audit",
    )


def test_dependency_gate_fails_closed_on_unknown_severity() -> None:
    decision = DependencyAuditPolicy().evaluate(
        (
            VulnerabilityRecord(
                package="mystery-package",
                vulnerability_id="GHSA-unknown",
                severity="vendor-unspecified",
            ),
        )
    )

    assert decision.allowed is False
    assert "severity=unknown" in decision.blockers[0]


def test_malicious_fixture_private_key_schema_fails_closed() -> None:
    fixture = '{"route":"ok","secretKey":' + _solana_keypair_fixture() + "}"

    findings = scan_text_for_key_material(fixture, source="malicious-fixture")

    assert {finding.reason for finding in findings} >= {
        "private-key JSON field",
        "Solana-style keypair byte array",
    }


def test_key_and_jito_rotation_drill_is_documented() -> None:
    text = Path("docs/security/key_rotation_runbook.md").read_text(encoding="utf-8")

    assert "Wallet signer rotation" in text
    assert "Jito credential rotation" in text
    assert "No inline key material" in text
