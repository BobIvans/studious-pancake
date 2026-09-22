from __future__ import annotations

import copy

from src.deployment_supply_chain_mpr44 import (
    REQUIRED_DEPLOYMENT_CONTROLS,
    REQUIRED_RELEASE_ARTIFACTS,
    REQUIRED_SECRET_CONTROLS,
    evaluate_deployment_supply_chain,
)

_HASH = "a" * 64
_ACTION_SHA = "actions/checkout@" + ("b" * 40)


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "mpr44.enforced-deployment-supply-chain.v1",
        "paper_release_candidate": True,
        "live_enabled": False,
        "source_checkout_production_allowed": False,
        "raw_secret_environment_allowed": False,
        "network_install_allowed": False,
        "untrusted_pr_code_can_access_secrets": False,
        "github_actions_uses": [_ACTION_SHA],
        "deployment_controls": {key: True for key in REQUIRED_DEPLOYMENT_CONTROLS},
        "secret_controls": {key: True for key in REQUIRED_SECRET_CONTROLS},
        "egress_policy": {
            "mode": "deny-by-default",
            "allowed_endpoints": ["https://api.mainnet-beta.solana.com"],
        },
        "probes": {
            "readiness_endpoint": "/ready",
            "liveness_endpoint": "/health",
            "startup_endpoint": "/startup",
        },
        "release_artifacts": [
            {
                "id": artifact_id,
                "digest": "sha256:" + _HASH,
                "materialized": True,
                "independently_verified": True,
            }
            for artifact_id in REQUIRED_RELEASE_ARTIFACTS
        ],
    }


def test_mpr44_accepts_fully_materialized_sender_free_release_bundle() -> None:
    report = evaluate_deployment_supply_chain(_manifest())

    assert report.accepted is True
    assert report.paper_release_ready is True
    assert report.live_ready is False
    assert report.blockers == ()
    assert report.evidence_digest is not None


def test_mpr44_rejects_floating_github_actions_and_network_install() -> None:
    manifest = _manifest()
    manifest["github_actions_uses"] = ["actions/checkout@v4"]
    manifest["network_install_allowed"] = True

    report = evaluate_deployment_supply_chain(manifest)

    assert report.accepted is False
    assert "FLOATING_GITHUB_ACTION:actions/checkout@v4" in report.blockers
    assert "NETWORK_INSTALL_FORBIDDEN" in report.blockers


def test_mpr44_rejects_plaintext_secret_env_and_source_checkout_production() -> None:
    manifest = _manifest()
    manifest["raw_secret_environment_allowed"] = True
    manifest["source_checkout_production_allowed"] = True

    report = evaluate_deployment_supply_chain(manifest)

    assert report.accepted is False
    assert "RAW_SECRET_ENVIRONMENT_FORBIDDEN" in report.blockers
    assert "SOURCE_CHECKOUT_PRODUCTION_FORBIDDEN" in report.blockers


def test_mpr44_rejects_missing_sandbox_controls() -> None:
    manifest = _manifest()
    deployment_controls = manifest["deployment_controls"]
    assert isinstance(deployment_controls, dict)
    deployment_controls["seccomp_profile_present"] = False
    deployment_controls["apparmor_profile_present"] = False
    deployment_controls["readiness_probe_uses_ready"] = False

    report = evaluate_deployment_supply_chain(manifest)

    assert report.accepted is False
    assert "CONTROL_NOT_PROVEN:deployment_controls.seccomp_profile_present" in report.blockers
    assert "CONTROL_NOT_PROVEN:deployment_controls.apparmor_profile_present" in report.blockers
    assert "CONTROL_NOT_PROVEN:deployment_controls.readiness_probe_uses_ready" in report.blockers


def test_mpr44_rejects_missing_or_unverified_release_artifact() -> None:
    manifest = _manifest()
    artifacts = manifest["release_artifacts"]
    assert isinstance(artifacts, list)
    artifacts.pop()
    first = copy.deepcopy(artifacts[0])
    assert isinstance(first, dict)
    first["id"] = "egress_policy_digest"
    first["materialized"] = False
    first["independently_verified"] = False
    artifacts.append(first)

    report = evaluate_deployment_supply_chain(manifest)

    assert report.accepted is False
    assert "ARTIFACT_NOT_MATERIALIZED:egress_policy_digest" in report.blockers
    assert "ARTIFACT_NOT_INDEPENDENTLY_VERIFIED:egress_policy_digest" in report.blockers


def test_mpr44_rejects_live_and_wrong_readiness_probe() -> None:
    manifest = _manifest()
    manifest["live_enabled"] = True
    probes = manifest["probes"]
    assert isinstance(probes, dict)
    probes["readiness_endpoint"] = "/health"

    report = evaluate_deployment_supply_chain(manifest)

    assert report.accepted is False
    assert report.live_ready is False
    assert "LIVE_MUST_REMAIN_DISABLED" in report.blockers
    assert "READINESS_PROBE_NOT_READY_ENDPOINT" in report.blockers
