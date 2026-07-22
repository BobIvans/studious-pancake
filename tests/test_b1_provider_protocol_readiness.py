from __future__ import annotations

from src.external_contracts.provider_protocol_b1 import (
    DEFAULT_B1_PROVIDERS,
    b1_exit_code,
    evaluate_b1_provider_protocol_readiness,
)


def _provider(report, provider: str):
    return next(item for item in report.providers if item.provider == provider)


def test_b1_default_report_is_fail_closed_without_online_conformance() -> None:
    report = evaluate_b1_provider_protocol_readiness(environ={})

    assert report.schema_version == "b1.provider-protocol-readiness.v1"
    assert report.online_enabled is False
    assert report.paper_vertical_ready is False
    assert tuple(item.provider for item in report.providers) == DEFAULT_B1_PROVIDERS
    assert report.diagnostic == "blocked-provider-protocol-conformance"


def test_b1_jupiter_requires_credentials_and_remote_evidence() -> None:
    report = evaluate_b1_provider_protocol_readiness(environ={})
    jupiter = _provider(report, "jupiter")

    assert jupiter.contract_id == "jupiter.swap-v2-build"
    assert jupiter.status == "active"
    assert jupiter.has_conformance_probe is True
    assert jupiter.execution_allowed is False
    assert "JUPITER_API_KEY" in jupiter.required_env
    assert "JUPITER_API_KEY" in jupiter.missing_env
    assert "credentialed-conformance-not-run" in jupiter.blockers
    assert "evidence-missing:remote_schema_freshness" in jupiter.blockers
    assert "evidence-missing:credentialed_api_conformance" in jupiter.blockers
    assert jupiter.can_feed_paper_vertical is False


def test_b1_marginfi_blocks_without_deployment_attestation() -> None:
    report = evaluate_b1_provider_protocol_readiness(environ={})
    marginfi = _provider(report, "marginfi")

    assert marginfi.contract_id == "marginfi.v2-mainnet-source-identity"
    assert marginfi.execution_allowed is False
    assert "contract-not-active:disabled-unverified" in marginfi.blockers
    assert "missing-conformance-probe" in marginfi.blockers
    assert "evidence-missing:deployed_program_attestation" in marginfi.blockers
    assert marginfi.can_feed_paper_vertical is False


def test_b1_jito_is_read_only_and_not_settlement_evidence() -> None:
    report = evaluate_b1_provider_protocol_readiness(environ={})
    jito = _provider(report, "jito")

    assert jito.contract_id == "jito.low-latency-json-rpc"
    assert jito.execution_allowed is False
    assert jito.status == "disabled-unverified"
    assert "contract-not-active:disabled-unverified" in jito.blockers
    assert "credentialed-conformance-not-run" in jito.blockers
    assert "evidence-missing:execution_conformance" in jito.blockers


def test_b1_can_scope_to_one_provider() -> None:
    report = evaluate_b1_provider_protocol_readiness(
        providers=("jupiter",),
        environ={"JUPITER_API_KEY": "redacted-test-key"},
    )

    assert [item.provider for item in report.providers] == ["jupiter"]
    assert _provider(report, "jupiter").missing_env == ()


def test_b1_unknown_provider_is_explicitly_blocked() -> None:
    report = evaluate_b1_provider_protocol_readiness(
        providers=("unknown-provider",),
        environ={},
    )
    item = report.providers[0]

    assert item.provider == "unknown-provider"
    assert item.contract_id is None
    assert item.blockers == ("missing-external-contract",)
    assert report.paper_vertical_ready is False


def test_b1_online_missing_credentials_is_not_success() -> None:
    report = evaluate_b1_provider_protocol_readiness(
        providers=("jupiter",),
        enable_online=True,
        environ={},
    )
    jupiter = _provider(report, "jupiter")

    assert jupiter.conformance_state == "skipped-missing-env"
    assert (
        "credentialed-conformance-not-verified:skipped-missing-env"
        in jupiter.blockers
    )
    assert report.paper_vertical_ready is False


def test_b1_exit_code_only_fails_when_required() -> None:
    report = evaluate_b1_provider_protocol_readiness(environ={})

    assert b1_exit_code(report) == 0
    assert b1_exit_code(report, require_ready=True) == 3
