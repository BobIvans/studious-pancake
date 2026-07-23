from __future__ import annotations

import hashlib
import json

from src.canonical_paper.installed_artifact import (
    CANONICAL_ENTRYPOINT,
    REQUIRED_COMMANDS,
    SCHEMA_VERSION,
    evaluate_installed_artifact_evidence,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _observation(name: str, stdout: str = "", exit_code: int = 0) -> dict[str, object]:
    argv = [
        "/tmp/mpr01/canonical-paper.sqlite3" if item == "{paper_db_path}" else item
        for item in REQUIRED_COMMANDS[name]
    ]
    return {
        "name": name,
        "argv": argv,
        "exit_code": exit_code,
        "stdout_sha256": _sha(stdout),
        "stderr_sha256": _sha(""),
        "stdout_text": stdout,
        "stderr_text": "",
    }


def _evidence(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "entrypoint": {
            "flashloan-bot": CANONICAL_ENTRYPOINT,
            "root_wrapper_target": CANONICAL_ENTRYPOINT,
            "source_main_target": CANONICAL_ENTRYPOINT,
            "package_excludes": ["src.ingest*", "src.execution.senders*"],
        },
        "runtime_claims": {
            "live_enabled": False,
            "live_available": False,
            "live_execution_allowed": False,
            "jito_enabled": False,
            "signer_loaded": False,
            "signer_allowed": False,
            "sender_loaded": False,
            "sender_allowed": False,
            "private_key_material_allowed": False,
        },
        "command_observations": [
            _observation("help", "usage: flashloan-bot\n"),
            _observation(
                "status",
                json.dumps({"product_state": "not-production-ready"}),
            ),
            _observation(
                "capabilities",
                json.dumps({"live_available": False, "sender_allowed": False}),
            ),
            _observation(
                "config_doctor",
                json.dumps({"ok": True, "jito_enabled": False}),
            ),
            _observation(
                "canonical_paper_cycle",
                json.dumps(
                    {
                        "outcome": "PAPER_ACCEPTED",
                        "live_enabled": False,
                        "signer_loaded": False,
                        "sender_loaded": False,
                    }
                ),
            ),
        ],
    }
    payload.update(overrides)
    return payload


def test_valid_evidence_accepts_sender_free_installed_surface() -> None:
    report = evaluate_installed_artifact_evidence(_evidence())

    assert report.ok
    assert report.reason_code == "mpr01_installed_artifact_parity_verified"
    assert len(report.command_surface_digest) == 64
    payload = report.to_dict()
    assert payload["live_enabled"] is False
    assert payload["signer_loaded"] is False
    assert payload["sender_loaded"] is False


def test_missing_required_command_blocks_parity() -> None:
    evidence = _evidence()
    evidence["command_observations"] = evidence["command_observations"][:-1]

    report = evaluate_installed_artifact_evidence(evidence)

    assert not report.ok
    assert any(item.code == "MPR01_COMMAND_MISSING" for item in report.violations)


def test_duplicate_required_command_blocks_parity() -> None:
    evidence = _evidence()
    evidence["command_observations"] = [
        *evidence["command_observations"],
        _observation("help", "usage: duplicate\n"),
    ]

    report = evaluate_installed_artifact_evidence(evidence)

    assert not report.ok
    assert any(item.code == "MPR01_DUPLICATE_COMMAND" for item in report.violations)


def test_live_surface_in_json_output_blocks_mpr01() -> None:
    observations = list(_evidence()["command_observations"])
    observations[-1] = _observation(
        "canonical_paper_cycle",
        json.dumps(
            {"live_enabled": True, "signer_loaded": False, "sender_loaded": False}
        ),
    )

    report = evaluate_installed_artifact_evidence(
        _evidence(command_observations=observations)
    )

    assert not report.ok
    assert any(
        item.code == "MPR01_FORBIDDEN_RUNTIME_SURFACE"
        and "live_enabled" in item.message
        for item in report.violations
    )


def test_wrong_console_entrypoint_blocks_mpr01() -> None:
    report = evaluate_installed_artifact_evidence(
        _evidence(
            entrypoint={
                "flashloan-bot": "src.cli:main",
                "root_wrapper_target": CANONICAL_ENTRYPOINT,
                "source_main_target": CANONICAL_ENTRYPOINT,
                "package_excludes": ["src.execution.senders*"],
            }
        )
    )

    assert not report.ok
    assert any(item.code == "MPR01_ENTRYPOINT_DRIFT" for item in report.violations)


def test_sender_namespace_must_remain_excluded() -> None:
    report = evaluate_installed_artifact_evidence(
        _evidence(
            entrypoint={
                "flashloan-bot": CANONICAL_ENTRYPOINT,
                "root_wrapper_target": CANONICAL_ENTRYPOINT,
                "source_main_target": CANONICAL_ENTRYPOINT,
                "package_excludes": ["src.ingest*"],
            }
        )
    )

    assert not report.ok
    assert any(
        item.code == "MPR01_SENDER_NAMESPACE_NOT_EXCLUDED"
        for item in report.violations
    )


def test_command_argv_drift_blocks_surface_claim() -> None:
    observations = list(_evidence()["command_observations"])
    bad = dict(observations[-1])
    bad["argv"] = ["run", "--mode", "live", "--json"]
    observations[-1] = bad

    report = evaluate_installed_artifact_evidence(
        _evidence(command_observations=observations)
    )

    assert not report.ok
    assert any(item.code == "MPR01_COMMAND_ARGV_DRIFT" for item in report.violations)


def test_runtime_claims_cannot_enable_jito_or_signer() -> None:
    report = evaluate_installed_artifact_evidence(
        _evidence(
            runtime_claims={
                "live_enabled": False,
                "jito_enabled": True,
                "signer_allowed": True,
                "sender_allowed": False,
            }
        )
    )

    assert not report.ok
    assert sum(
        item.code == "MPR01_FORBIDDEN_RUNTIME_SURFACE"
        for item in report.violations
    ) >= 2
