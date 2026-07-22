# fmt: off
from __future__ import annotations

from copy import deepcopy

from src.scheduled_drift_pr139 import (
    PR139_SCHEMA_VERSION,
    evaluate_pr139_scheduled_drift,
    immutable_evidence_hash,
    main,
    redact_secrets,
)

_NOW = 1_785_000_000
_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def test_weekly_full_matching_evidence_allows_execution() -> None:
    manifest, observations = _manifest_and_observations()

    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="weekly-full",
    )

    assert result.execution_capability_allowed is True
    assert result.operator_alert is False
    assert result.blockers == ()
    assert result.drift_events == ()
    assert len(result.immutable_evidence_hash) == 64


def test_external_api_hash_drift_revokes_and_requires_pin_rotation() -> None:
    manifest, observations = _manifest_and_observations()
    observation = _find_observation(observations, "api-jupiter")
    observation["status"] = "drift"
    observation["observed_hash"] = _SHA_C

    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="daily-lightweight",
    )

    assert result.execution_capability_allowed is False
    assert result.operator_alert is True
    assert result.pin_rotation_pr_required is True
    assert "PR139_DRIFT:api-jupiter:jupiter" in result.drift_events
    assert "PR139_HASH_DRIFT:api-jupiter:jupiter" in result.drift_events


def test_stale_evidence_revokes_admission() -> None:
    manifest, observations = _manifest_and_observations()
    observation = _find_observation(observations, "rpc-genesis")
    observation["observed_at_unix"] = _NOW - 200_000

    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="daily-lightweight",
    )

    assert result.execution_capability_allowed is False
    assert "PR139_EVIDENCE_STALE:rpc-genesis" in result.blockers


def test_credentialed_probe_requires_protected_environment() -> None:
    manifest, observations = _manifest_and_observations()
    probe = _find_probe(manifest, "api-jito")
    probe["protected_environment"] = False
    observation = _find_observation(observations, "api-jito")
    observation["credentialed"] = False

    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="manual",
    )

    assert result.execution_capability_allowed is False
    assert "PR139_PROTECTED_ENVIRONMENT_REQUIRED:api-jito" in result.blockers
    assert "PR139_CREDENTIALED_PROBE_UNAVAILABLE:api-jito" in result.blockers


def test_no_automated_acceptance_of_new_hashes() -> None:
    manifest, observations = _manifest_and_observations()
    manifest["allow_automated_acceptance"] = True

    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="weekly-full",
    )

    assert result.execution_capability_allowed is False
    assert "PR139_AUTOMATED_ACCEPTANCE_FORBIDDEN" in result.blockers


def test_weekly_full_requires_onchain_coverage() -> None:
    manifest, observations = _manifest_and_observations()
    probes = manifest["probes"]
    assert isinstance(probes, list)
    manifest["probes"] = [
        item for item in probes if item["target"] != "alt-lifecycle"
    ]

    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="weekly-full",
    )

    assert result.execution_capability_allowed is False
    assert "PR139_ONCHAIN_PROBE_MISSING:alt-lifecycle" in result.blockers


def test_evidence_hash_redacts_secret_shaped_fields() -> None:
    manifest, observations = _manifest_and_observations()
    before = immutable_evidence_hash(manifest, observations)
    _find_observation(observations, "api-odos")["authorization"] = "different-secret"
    after = immutable_evidence_hash(manifest, observations)

    assert before == after
    assert redact_secrets({"api_key": "raw", "safe": "value"}) == {
        "api_key": "<redacted>",
        "safe": "value",
    }


def test_cli_self_check_passes_and_prints_json(capsys) -> None:
    assert main(["--json"]) == 0
    captured = capsys.readouterr()
    assert '"execution_capability_allowed": true' in captured.out


def _manifest_and_observations() -> tuple[dict[str, object], dict[str, object]]:
    probes = [
        _probe(f"api-{target}", "external-api", target)
        for target in ["jupiter", "jito", "okx", "openocean", "odos"]
    ]
    probes.extend(
        _probe(f"chain-{target}", "on-chain", target)
        for target in [
            "programdata-hash",
            "upgrade-authority",
            "deployment-slot",
            "marginfi-group-bank-oracle",
            "token-mint-extensions",
            "alt-lifecycle",
        ]
    )
    probes.extend(
        _probe(f"rpc-{target}", "rpc", target)
        for target in ["genesis", "node-version", "feature-capability"]
    )
    manifest: dict[str, object] = {
        "schema_version": PR139_SCHEMA_VERSION,
        "now_unix": _NOW,
        "max_evidence_age_seconds": 86_400,
        "allow_automated_acceptance": False,
        "probes": probes,
    }
    observations = {
        "observations": [
            _observation(str(probe["probe_id"])) for probe in probes
        ],
        "historical_drift_timeline": [
            {"run_id": "fixture-1", "outcome": "match", "at_unix": _NOW}
        ],
    }
    return deepcopy(manifest), deepcopy(observations)


def _probe(probe_id: str, kind: str, target: str) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "kind": kind,
        "target": target,
        "expected_hash": _SHA_A,
        "credential_required": kind == "external-api",
        "protected_environment": kind == "external-api",
    }


def _observation(probe_id: str) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "status": "match",
        "observed_at_unix": _NOW - 60,
        "observed_hash": _SHA_A,
        "evidence_hash": _SHA_B,
        "credentialed": True,
        "authorization": "secret-value",
    }


def _find_probe(
    manifest: dict[str, object],
    probe_id: str,
) -> dict[str, object]:
    probes = manifest["probes"]
    assert isinstance(probes, list)
    for probe in probes:
        if probe["probe_id"] == probe_id:
            return probe
    raise AssertionError(probe_id)


def _find_observation(
    observations: dict[str, object],
    probe_id: str,
) -> dict[str, object]:
    items = observations["observations"]
    assert isinstance(items, list)
    for item in items:
        if item["probe_id"] == probe_id:
            return item
    raise AssertionError(probe_id)
# fmt: on
