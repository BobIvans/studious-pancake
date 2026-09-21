from __future__ import annotations

from src.execution.transaction_format_qualification import (
    CANONICAL_V0_OWNER,
    FormatQualificationStatus,
    TransactionDialect,
    TransactionFormatCapabilityEvidence,
    V1ExecutionEvidenceRequest,
    assess_transaction_format,
    bind_v1_exact_execution_evidence,
)


def _evidence(**overrides):
    values = {
        "dialect": TransactionDialect.V1,
        "sdk_name": "future-qualified-codec",
        "sdk_version": "1.0.0",
        "sdk_artifact_hash": "1" * 64,
        "source_repository": "official/example",
        "source_commit": "2" * 40,
        "codec_symbol": "compile_v1_unsigned",
        "license_decision": "APPROVED",
        "evidence_hash": "3" * 64,
        "observed_at_ms": 100,
        "expires_at_ms": 1000,
        "compile_supported": True,
        "decode_supported": True,
        "simulation_supported": True,
        "finalized_decode_supported": True,
    }
    values.update(overrides)
    return TransactionFormatCapabilityEvidence(**values)


def test_nf349_v0_remains_current_canonical_owner() -> None:
    result = assess_transaction_format(
        dialect=TransactionDialect.V0,
        evidence=None,
        now_ms=200,
    )
    assert result.status is FormatQualificationStatus.QUALIFIED_OFFLINE
    assert result.reason_code == "CANONICAL_V0_OWNER"
    assert result.canonical_owner == CANONICAL_V0_OWNER
    assert result.live_enabled is False
    assert result.signing_enabled is False
    assert result.submission_enabled is False


def test_nf349_v1_missing_or_expired_evidence_fails_closed() -> None:
    missing = assess_transaction_format(
        dialect=TransactionDialect.V1,
        evidence=None,
        now_ms=200,
    )
    assert missing.status is FormatQualificationStatus.BLOCKED
    assert missing.reason_code == "V1_CAPABILITY_EVIDENCE_MISSING"

    expired = assess_transaction_format(
        dialect=TransactionDialect.V1,
        evidence=_evidence(),
        now_ms=1000,
    )
    assert expired.status is FormatQualificationStatus.BLOCKED
    assert expired.reason_code == "CAPABILITY_EXPIRED"


def test_nf349_unresolved_license_or_incomplete_capability_blocks() -> None:
    unresolved = assess_transaction_format(
        dialect=TransactionDialect.V1,
        evidence=_evidence(license_decision="UNSPECIFIED"),
        now_ms=200,
    )
    assert unresolved.reason_code == "V1_LICENSE_UNRESOLVED"

    incomplete = assess_transaction_format(
        dialect=TransactionDialect.V1,
        evidence=_evidence(finalized_decode_supported=False),
        now_ms=200,
    )
    assert incomplete.reason_code == "V1_CAPABILITY_INCOMPLETE"


def test_nf350_352_external_evidence_cannot_invent_local_v1_compiler() -> None:
    assessment = assess_transaction_format(
        dialect=TransactionDialect.V1,
        evidence=_evidence(),
        now_ms=200,
    )
    assert assessment.status is FormatQualificationStatus.BLOCKED
    assert assessment.reason_code == "V1_CANONICAL_COMPILER_NOT_IMPLEMENTED"

    request = V1ExecutionEvidenceRequest(
        plan_hash="4" * 64,
        message_hash="5" * 64,
        simulation_hash="6" * 64,
        permit_hash="7" * 64,
        decoder_evidence_hash="8" * 64,
        finalized_evidence_hash="9" * 64,
    )
    verdict = bind_v1_exact_execution_evidence(
        assessment=assessment,
        request=request,
    )
    assert verdict.accepted is False
    assert verdict.reason_code == "V1_CANONICAL_COMPILER_NOT_IMPLEMENTED"
    assert verdict.live_enabled is False
