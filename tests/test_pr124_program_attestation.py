# fmt: off
from __future__ import annotations

from copy import deepcopy

from src.program_attestation_pr124 import (
    BPF_UPGRADEABLE_LOADER_ID,
    PR124_SCHEMA_VERSION,
    evaluate_pr124_program_attestation,
    main,
    make_program_evidence_hash,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_GENESIS = "Gen111111111111111111111111111111111111111"
_OWNER = BPF_UPGRADEABLE_LOADER_ID
_PROG_TOKEN = "Tokn111111111111111111111111111111111111111"
_PROG_JUP = "Jup1111111111111111111111111111111111111111"
_PROG_MARGINFI = "Marg11111111111111111111111111111111111111"
_PROG_T22 = "T2211111111111111111111111111111111111111"
_PROG_ATA = "ATA111111111111111111111111111111111111111"
_PROGDATA = "Data111111111111111111111111111111111111111"
_AUTHORITY = "Auth111111111111111111111111111111111111111"


def test_address_and_owner_alone_never_grant_execution_capability() -> None:
    registry = _registry(active_label="token")
    evidence_item = _complete_evidence(_PROG_TOKEN)
    evidence_item["programdata_address"] = None
    evidence_item["deployed_slot"] = None
    evidence_item["executable_hash"] = None
    evidence_item["evidence_hash"] = make_program_evidence_hash(evidence_item)

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="startup",
    )

    assert result.execution_capability_allowed is False
    assert "PR124_PROGRAMDATA_ADDRESS_MISSING:token" in result.blockers
    assert "PR124_DEPLOYED_SLOT_MISSING:token" in result.blockers
    assert "PR124_EXECUTABLE_HASH_MISSING:token" in result.blockers


def test_reviewed_immutable_program_with_full_evidence_is_allowed() -> None:
    registry = _registry(active_label="token")
    evidence_item = _complete_evidence(_PROG_TOKEN)

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="promotion",
    )

    assert result.execution_capability_allowed is True
    assert result.degraded_discovery_allowed is False
    assert result.operator_alert is False
    assert result.blockers == ()
    assert result.drift_events == ()


def test_upgrade_authority_drift_revokes_execution_and_alerts_operator() -> None:
    registry = _registry(
        active_label="token",
        authority_policy="fixed-upgrade-authority",
        expected_upgrade_authority=_AUTHORITY,
    )
    evidence_item = _complete_evidence(
        _PROG_TOKEN,
        upgrade_authority="Auth222222222222222222222222222222222222222",
    )

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="programdata-change",
        explicit_degraded_discovery_mode=True,
    )

    assert result.execution_capability_allowed is False
    assert result.degraded_discovery_allowed is True
    assert result.operator_alert is True
    assert "PR124_UPGRADE_AUTHORITY_DRIFT:token" in result.drift_events


def test_executable_hash_drift_revokes_execution() -> None:
    registry = _registry(active_label="token")
    evidence_item = _complete_evidence(_PROG_TOKEN)
    evidence_item["executable_hash"] = _SHA_C
    evidence_item["evidence_hash"] = make_program_evidence_hash(evidence_item)

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="periodic",
    )

    assert result.execution_capability_allowed is False
    assert result.operator_alert is True
    assert "PR124_EXECUTABLE_HASH_DRIFT:token" in result.drift_events


def test_custom_cluster_requires_reviewed_identity() -> None:
    registry = _registry(active_label="token")
    cluster = registry["cluster"]
    assert isinstance(cluster, dict)
    cluster["cluster"] = "custom-devnet"
    cluster["reviewed"] = False
    cluster["reviewer"] = None
    evidence_item = _complete_evidence(_PROG_TOKEN)

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="startup",
    )

    assert result.execution_capability_allowed is False
    assert result.cluster_identity_reviewed is False
    assert "PR124_CLUSTER_IDENTITY_NOT_REVIEWED" in result.blockers


def test_evidence_hash_mismatch_blocks_execution() -> None:
    registry = _registry(active_label="token")
    evidence_item = _complete_evidence(_PROG_TOKEN)
    evidence_item["evidence_hash"] = _SHA_C

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="release",
    )

    assert result.execution_capability_allowed is False
    assert f"PR124_EVIDENCE_HASH_MISMATCH:{_PROG_TOKEN}" in result.blockers


def test_observed_programdata_change_triggers_drift() -> None:
    registry = _registry(active_label="token")
    evidence_item = _complete_evidence(_PROG_TOKEN)
    evidence_item["observed_programdata_address"] = (
        "Data222222222222222222222222222222222222222"
    )
    evidence_item["evidence_hash"] = make_program_evidence_hash(evidence_item)

    result = evaluate_pr124_program_attestation(
        registry,
        {"programs": [evidence_item]},
        attestation_action="programdata-change",
    )

    assert result.execution_capability_allowed is False
    assert "PR124_OBSERVED_PROGRAMDATA_CHANGE:token" in result.drift_events
    assert result.reattestation_required is True


def test_cli_self_check_passes_and_prints_json(capsys) -> None:
    assert main(["--json"]) == 0
    captured = capsys.readouterr()
    assert '"execution_capability_allowed": true' in captured.out


def _registry(
    *,
    active_label: str,
    authority_policy: str = "immutable",
    expected_upgrade_authority: str | None = None,
) -> dict[str, object]:
    programs = {
        "marginfi": _expectation(
            "marginfi",
            _PROG_MARGINFI,
            admission="discovery-only",
        ),
        "jupiter-aggregator": _expectation(
            "jupiter-aggregator",
            _PROG_JUP,
            admission="discovery-only",
        ),
        "token": _expectation(
            "token",
            _PROG_TOKEN,
            authority_policy=authority_policy,
            expected_upgrade_authority=expected_upgrade_authority,
        ),
        "token-2022": _expectation(
            "token-2022",
            _PROG_T22,
            admission="discovery-only",
        ),
        "associated-token-account": _expectation(
            "associated-token-account",
            _PROG_ATA,
            admission="discovery-only",
        ),
    }
    for label, payload in programs.items():
        if label != active_label:
            payload["admission"] = "discovery-only"
    return {
        "schema_version": PR124_SCHEMA_VERSION,
        "cluster": {
            "cluster": "mainnet-beta",
            "expected_genesis_hash": _GENESIS,
            "observed_genesis_hash": _GENESIS,
            "reviewed": True,
            "reviewer": "operator",
            "evidence_hash": _SHA_A,
            "source": "fixture",
        },
        "programs": list(programs.values()),
    }


def _expectation(
    label: str,
    program_id: str,
    *,
    admission: str = "active",
    authority_policy: str = "immutable",
    expected_upgrade_authority: str | None = None,
) -> dict[str, object]:
    return {
        "label": label,
        "program_id": program_id,
        "admission": admission,
        "expected_account_owner": _OWNER,
        "expected_loader": _OWNER,
        "expected_executable": True,
        "expected_code_hash": _SHA_B,
        "authority_policy": authority_policy,
        "expected_upgrade_authority": expected_upgrade_authority,
        "allowed_upgrade_authorities": [],
        "expected_programdata_address": _PROGDATA,
        "verified_source_pin": None,
        "required": True,
    }


def _complete_evidence(
    program_id: str,
    *,
    upgrade_authority: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "program_id": program_id,
        "account_owner": _OWNER,
        "executable": True,
        "loader": _OWNER,
        "programdata_address": _PROGDATA,
        "deployed_slot": 100,
        "upgrade_authority": upgrade_authority,
        "executable_hash": _SHA_B,
        "attested_at_slot": 200,
        "attested_at_utc": "2026-07-21T00:00:00Z",
        "evidence_hash": None,
        "observed_programdata_address": _PROGDATA,
    }
    item["evidence_hash"] = make_program_evidence_hash(item)
    return deepcopy(item)
# fmt: on
