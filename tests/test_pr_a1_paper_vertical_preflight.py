from pathlib import Path
from types import SimpleNamespace

from src.paper_shadow.a1_vertical_preflight import (
    PR_A1_INVALID,
    PR_A1_READY,
    PR_A1_SCHEMA,
    PR_A1_UNWIRED,
    evaluate_paper_vertical_a1,
)


class MissingDependencies:
    def missing(self):
        return (
            "atomic_stage_suite",
            "exact_fee_workflow",
            "verified_marginfi_provider",
            "jupiter_v2_build",
        )

    def invalid(self):
        return ()


class InvalidDependencies:
    atomic_stage_suite = object()
    exact_fee_workflow = object()
    verified_marginfi_provider = object()
    jupiter_v2_build = object()

    def missing(self):
        return ()

    def invalid(self):
        return ("verified_marginfi_provider_contract",)


class CompleteDependencies:
    atomic_stage_suite = object()
    exact_fee_workflow = object()
    verified_marginfi_provider = object()
    jupiter_v2_build = object()

    def missing(self):
        return ()

    def invalid(self):
        return ()


def _config():
    return SimpleNamespace(
        fingerprint=lambda: "cfg-sha",
        runtime=SimpleNamespace(mode=SimpleNamespace(value="paper")),
    )


def test_a1_default_dependencies_fail_closed_with_named_surface_reasons():
    report = evaluate_paper_vertical_a1(_config(), MissingDependencies())

    assert report.ready is False
    assert report.reason_code == PR_A1_UNWIRED
    assert "missing_atomic_stage_suite" in report.dependency_reasons()
    assert report.to_dict()["safety"] == {
        "live_enabled": False,
        "signer_reachable": False,
        "sender_reachable": False,
        "private_key_loading": False,
        "fake_success_permitted": False,
        "network_io_performed": False,
    }


def test_a1_invalid_dependencies_are_separate_from_unwired_dependencies():
    report = evaluate_paper_vertical_a1(_config(), InvalidDependencies())

    assert report.ready is False
    assert report.reason_code == PR_A1_INVALID
    assert "invalid_verified_marginfi_provider_contract" in report.dependency_reasons()


def test_a1_complete_dependencies_are_ready_but_still_sender_free():
    report = evaluate_paper_vertical_a1(_config(), CompleteDependencies())
    payload = report.to_dict()

    assert report.ready is True
    assert report.reason_code == PR_A1_READY
    assert payload["runtime_mode"] == "paper"
    assert payload["available_surfaces"] == {
        "atomic_stage_suite": True,
        "exact_fee_workflow": True,
        "verified_marginfi_provider": True,
        "jupiter_v2_build": True,
    }
    assert payload["safety"]["live_enabled"] is False
    assert payload["safety"]["sender_reachable"] is False


def test_a1_json_schema_and_required_surface_order_are_stable():
    payload = evaluate_paper_vertical_a1(_config(), MissingDependencies()).to_dict()

    assert payload["schema_version"] == PR_A1_SCHEMA
    assert payload["required_surfaces"] == [
        "atomic_stage_suite",
        "exact_fee_workflow",
        "verified_marginfi_provider",
        "jupiter_v2_build",
    ]


def test_a1_is_exposed_through_supported_cli_source():
    source = Path("src/cli.py").read_text(encoding="utf-8")

    assert "paper-vertical-preflight" in source
    assert "evaluate_paper_vertical_a1" in source
    assert "PaperShadowRuntimeDependencies()" in source
