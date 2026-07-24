from __future__ import annotations

import copy

from src.provider_protocol_conformance_mpr_next_03 import (
    evaluate_provider_conformance,
    load_default_manifest,
)


def _provider(payload: dict[str, object], provider_id: str) -> dict[str, object]:
    providers = payload["providers"]
    assert isinstance(providers, list)
    for provider in providers:
        assert isinstance(provider, dict)
        if provider["id"] == provider_id:
            return provider
    raise AssertionError(f"missing provider {provider_id}")


def test_mpr_next_03_default_manifest_is_accepted_and_live_disabled() -> None:
    report = evaluate_provider_conformance()

    assert report.accepted is True
    assert report.live_enabled is False
    assert report.blockers == ()
    assert report.provider_count >= 5
    assert report.drift_artifact_count >= 5
    assert report.manifest_digest is not None


def test_mpr_next_03_rejects_active_jupiter_v1_paths() -> None:
    payload = copy.deepcopy(load_default_manifest())
    jupiter = _provider(payload, "jupiter_swap_v2_build")
    active_paths = jupiter["active_paths"]
    assert isinstance(active_paths, list)
    active_paths.append("/swap/v1/quote")

    report = evaluate_provider_conformance(payload)

    assert report.accepted is False
    assert "JUPITER_ACTIVE_SWAP_V1_PATH_PRESENT" in report.blockers


def test_mpr_next_03_requires_jupiter_v2_build_for_composable_raw_instructions() -> None:
    payload = copy.deepcopy(load_default_manifest())
    jupiter = _provider(payload, "jupiter_swap_v2_build")
    jupiter["active_paths"] = ["/order", "/execute"]

    report = evaluate_provider_conformance(payload)

    assert report.accepted is False
    assert "JUPITER_V2_BUILD_PATH_MISSING" in report.blockers


def test_mpr_next_03_requires_solana_v0_max_supported_transaction_version() -> None:
    payload = copy.deepcopy(load_default_manifest())
    solana = _provider(payload, "solana_rpc_v0")
    rpc = solana["rpc"]
    assert isinstance(rpc, dict)
    rpc["maxSupportedTransactionVersion"] = None

    report = evaluate_provider_conformance(payload)

    assert report.accepted is False
    assert "SOLANA_V0_MAX_SUPPORTED_VERSION_REQUIRED" in report.blockers


def test_mpr_next_03_keeps_optional_providers_discovery_only() -> None:
    payload = copy.deepcopy(load_default_manifest())
    okx = _provider(payload, "okx_signed_discovery")
    okx["runtime_admission_enabled"] = True

    report = evaluate_provider_conformance(payload)

    assert report.accepted is False
    assert "OKX_SIGNED_DISCOVERY_MUST_REMAIN_DISCOVERY_ONLY" in report.blockers


def test_mpr_next_03_requires_signed_redacted_immutable_drift_artifacts() -> None:
    payload = copy.deepcopy(load_default_manifest())
    artifacts = payload["drift_artifacts"]
    assert isinstance(artifacts, list)
    first = artifacts[0]
    assert isinstance(first, dict)
    first["signed"] = False
    first["redacted"] = False
    first["immutable"] = False

    report = evaluate_provider_conformance(payload)

    assert report.accepted is False
    assert any(blocker.startswith("DRIFT_ARTIFACT_UNSIGNED") for blocker in report.blockers)
    assert any(blocker.startswith("DRIFT_ARTIFACT_UNREDACTED") for blocker in report.blockers)
    assert any(blocker.startswith("DRIFT_ARTIFACT_MUTABLE") for blocker in report.blockers)


def test_mpr_next_03_rejects_live_or_submission_enablement() -> None:
    payload = copy.deepcopy(load_default_manifest())
    payload["live_enabled"] = True
    payload["transaction_submission_enabled"] = True

    report = evaluate_provider_conformance(payload)

    assert report.accepted is False
    assert "LIVE_MUST_REMAIN_DISABLED" in report.blockers
    assert "SUBMISSION_MUST_REMAIN_DISABLED" in report.blockers
