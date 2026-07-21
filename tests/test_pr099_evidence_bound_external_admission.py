from __future__ import annotations

from src.config.runtime import load_runtime_config
from src.external_contracts.admission import evaluate_runtime_admission
from src.external_contracts.cli import _conformance_exit_code
from src.external_contracts.policy import evaluate_contract_execution_admission
from src.external_contracts.registry import ExternalContractRegistry


def _provider(report, provider: str):
    return next(item for item in report.providers if item.provider == provider)


def test_pr099_jupiter_false_promotion_is_denied_by_admission() -> None:
    registry = ExternalContractRegistry.load_default()
    config = load_runtime_config(environ={})
    jupiter = registry.provider("jupiter")[0]

    assert jupiter.execution_allowed is False

    decision = evaluate_contract_execution_admission(jupiter, environ={})
    assert decision.allowed is False
    assert (
        decision.reason == "execution-evidence-blocked:credentialed-conformance-pending"
    )

    report = evaluate_runtime_admission(config, registry=registry, environ={})
    jupiter_report = _provider(report, "jupiter")
    assert report.execution_allowed is False
    assert jupiter_report.allowed is False
    assert jupiter_report.contract_id == "jupiter.swap-v2-build"
    assert jupiter_report.required_env == ("JUPITER_API_KEY",)
    assert jupiter_report.missing_env == ("JUPITER_API_KEY",)
    assert jupiter_report.reason == decision.reason


def test_pr099_execution_allowed_requires_decisive_promotion_state() -> None:
    registry = ExternalContractRegistry.load_default()

    for contract in registry.contracts:
        decision = evaluate_contract_execution_admission(
            contract,
            environ={
                "JUPITER_API_KEY": "jup-key",
                "OKX_API_KEY": "okx-key",
                "OKX_SECRET_KEY": "okx-secret",
                "OKX_API_PASSPHRASE": "okx-passphrase",
                "OPENOCEAN_API_KEY": "openocean-key",
            },
        )
        if contract.provider == "jupiter":
            assert decision.allowed is False
            assert decision.reason.startswith("execution-evidence-blocked:")
        else:
            assert decision.allowed is False


def test_pr099_requested_online_skip_is_non_zero_but_optional_skip_stays_zero() -> None:
    skipped = [{"state": "skipped-missing-env", "verified": False}]

    assert _conformance_exit_code(skipped) == 0
    assert _conformance_exit_code(skipped, online_requested=True) == 3
    assert (
        _conformance_exit_code(
            [{"state": "failed-assertion", "verified": False}],
            online_requested=True,
        )
        == 2
    )
