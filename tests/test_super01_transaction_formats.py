from __future__ import annotations

import pytest

from src.agg02 import (
    TransactionFormat,
    decode_versioned_transaction_envelope,
    normalize_format_specific_resources,
    qualify_transaction_read_capabilities,
    record_format_coverage_gap,
)
from src.agg02.contracts import Agg02Error

pytestmark = pytest.mark.unit

A = "a" * 64


def _capability(*formats: TransactionFormat):
    return qualify_transaction_read_capabilities(
        provider_id="rpc-a",
        chain_identity="solana-mainnet",
        sdk_identity="pinned-sdk",
        supported_formats=tuple(formats),
        evidence_sha256=A,
        observed_at_ms=100,
        expires_at_ms=1_000,
    )


def _decoder(_raw: bytes) -> dict[str, object]:
    return {
        "signatures": ["sig-a"],
        "account_keys": ["account-a", "account-b"],
        "instruction_count": 2,
        "fee_lamports": 5_000,
        "resource_config": "v1-default",
    }


def test_unqualified_v1_cannot_be_silently_read() -> None:
    capability = _capability(TransactionFormat.V0)
    with pytest.raises(Agg02Error, match="SUPER01_PROVIDER_VERSION_UNSUPPORTED"):
        decode_versioned_transaction_envelope(
            b"wire",
            declared_format=TransactionFormat.V1,
            capability=capability,
            now_ms=200,
            decoder_registry={TransactionFormat.V1: ("decoder-v1", _decoder)},
        )


def test_qualified_format_requires_explicit_decoder_and_preserves_raw_identity(
) -> None:
    capability = _capability(TransactionFormat.V1)
    with pytest.raises(Agg02Error, match="SUPER01_SDK_CODEC_UNAVAILABLE"):
        decode_versioned_transaction_envelope(
            b"wire",
            declared_format=TransactionFormat.V1,
            capability=capability,
            now_ms=200,
            decoder_registry={},
        )

    envelope = decode_versioned_transaction_envelope(
        b"wire",
        declared_format=TransactionFormat.V1,
        capability=capability,
        now_ms=200,
        decoder_registry={TransactionFormat.V1: ("decoder-v1", _decoder)},
    )
    resources = normalize_format_specific_resources(envelope)
    assert envelope.format_id is TransactionFormat.V1
    assert envelope.decoder_identity == "decoder-v1"
    assert resources.fee_lamports == 5_000
    assert resources.fee_unit == "lamports"


def test_malformed_decoder_output_and_expired_capability_fail_closed() -> None:
    capability = _capability(TransactionFormat.V1)

    def malformed(_raw: bytes) -> dict[str, object]:
        return {"signatures": [], "instruction_count": "two"}

    def not_a_mapping(_raw: bytes) -> object:
        return None

    with pytest.raises(Agg02Error, match="SUPER01_RESPONSE_SCHEMA_MISMATCH"):
        decode_versioned_transaction_envelope(
            b"wire",
            declared_format=TransactionFormat.V1,
            capability=capability,
            now_ms=200,
            decoder_registry={
                TransactionFormat.V1: (
                    "not-a-mapping",
                    not_a_mapping,  # type: ignore[arg-type]
                )
            },
        )

    with pytest.raises(Agg02Error, match="SUPER01_RESPONSE_SCHEMA_MISMATCH"):
        decode_versioned_transaction_envelope(
            b"wire",
            declared_format=TransactionFormat.V1,
            capability=capability,
            now_ms=200,
            decoder_registry={TransactionFormat.V1: ("bad-decoder", malformed)},
        )

    with pytest.raises(Agg02Error, match="SUPER01_PROVIDER_VERSION_UNSUPPORTED"):
        decode_versioned_transaction_envelope(
            b"wire",
            declared_format=TransactionFormat.V1,
            capability=capability,
            now_ms=1_000,
            decoder_registry={TransactionFormat.V1: ("decoder-v1", _decoder)},
        )


def test_failed_format_read_records_gap_and_forbids_silent_checkpoint_advance() -> None:
    capability = _capability(TransactionFormat.V0)
    gap = record_format_coverage_gap(
        capability=capability,
        requested_start=100,
        requested_end=110,
        format_id=TransactionFormat.V1,
        failure_code="SDK_CODEC_UNAVAILABLE",
        evidence_sha256=A,
    )
    assert gap.checkpoint_advance_allowed is False
    assert gap.requested_start == 100
    assert gap.requested_end == 110
