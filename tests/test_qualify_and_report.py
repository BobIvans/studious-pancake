from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from src import cli_entrypoint
from src import qualify_and_report as q


def _payload(step: q.Step) -> dict:
    payload = {"schema_version": step.schema}
    if step.name == "status":
        payload.update(
            capability_contract_valid=True, live_available=False, live_enabled=False
        )
    elif step.name == "capabilities":
        payload["runtime_modes"] = {"live": {"available": False}}
    elif step.name == "config-doctor":
        payload["ok"] = True
    elif step.name == "runtime-admission":
        payload.update(
            admitted=True, platform={"admitted": True}, command={"admitted": True}
        )
    elif step.name == "paper-vertical":
        payload.update(
            command="paper-vertical",
            command_mode="check",
            ready=True,
            check_passed=True,
            verdict="passed",
            exit_code=0,
            details={
                "safety": {
                    key: False
                    for key in (
                        "live_enabled",
                        "signer_reachable",
                        "sender_reachable",
                        "private_key_loading",
                        "network_io_performed",
                    )
                }
            },
        )
    else:
        payload.update(status="healthy_idle", readiness={"ready_for_next_cycle": True})
    return payload


def _receipt(step: q.Step, *, state: str = "passed", reasons=()) -> dict:
    return {
        "step": step.name,
        "state": state,
        "reason_codes": list(reasons),
        "exit_code": 0 if state == "passed" else 3,
        "payload": _payload(step),
    }


def _fixture_install(monkeypatch) -> None:
    monkeypatch.setattr(
        q,
        "installed_identity",
        lambda: (Path("/installed/flashloan-bot"), {"available": True}),
    )
    monkeypatch.setattr(
        q, "source_identity", lambda *a: {"available": True, "commit": "a" * 40}
    )


def test_blocker_skips_paper_shadow_and_preserves_all_receipts(tmp_path, monkeypatch):
    _fixture_install(monkeypatch)
    calls = []

    def execute(executable, step, **kwargs):
        calls.append(step.name)
        if step.name == "paper-vertical":
            return _receipt(step, state="blocked", reasons=("A1_UNWIRED",))
        return _receipt(step)

    monkeypatch.setattr(q, "execute_step", execute)
    report = q.collect_report(output_dir=tmp_path, project_root=tmp_path)
    assert calls == [s.name for s in q.PREFLIGHT_STEPS]
    assert report["state"] == "blocked" and report["exit_code"] == 3
    assert report["first_blocker"]["step"] == "paper-vertical"
    assert report["receipts"][-1]["state"] == "skipped"
    for artifact in report["receipt_files"]:
        raw = (Path(report["run_dir"]) / artifact["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
    assert (Path(report["run_dir"]) / "summary_ru.txt").is_file()


def test_paper_check_cannot_promote_release_or_claim_laya(tmp_path, monkeypatch):
    _fixture_install(monkeypatch)
    monkeypatch.setattr(
        q, "execute_step", lambda executable, step, **kw: _receipt(step)
    )
    report = q.collect_report(output_dir=tmp_path, project_root=tmp_path)
    assert report["paper_check_passed"] is True and report["exit_code"] == 0
    assert report["receipts"][-1]["step"] == "paper-shadow"
    for key in (
        "production_qualification_passed",
        "release_claim_allowed",
        "live_enabled",
        "laya_inference_performed",
    ):
        assert report[key] is False
    again = q.collect_report(output_dir=tmp_path, project_root=tmp_path)
    assert report["run_dir"] != again["run_dir"]


def test_later_error_does_not_hide_first_blocker(tmp_path, monkeypatch):
    _fixture_install(monkeypatch)

    def execute(executable, step, **kwargs):
        if step.name == "status":
            return _receipt(step, state="blocked", reasons=("CONTRACT_INVALID",))
        if step.name == "runtime-admission":
            return _receipt(step, state="error", reasons=("COMMAND_TIMEOUT",))
        return _receipt(step)

    monkeypatch.setattr(q, "execute_step", execute)
    report = q.collect_report(output_dir=tmp_path, project_root=tmp_path)
    assert report["state"] == "error" and report["exit_code"] == 2
    assert report["first_blocker"]["step"] == "status"
    assert len(report["blockers"]) == 2


def test_child_environment_excludes_keys_config_and_python_injection():
    env = q.child_environment(
        {
            "PATH": "/bin",
            "SystemRoot": "C:/Windows",
            "OPENAI_API_KEY": "private",
            "SOLANA_RPC_HTTP": "https://rpc/?api-key=private",
            "FLASHLOAN_CONFIG_FILE": "private.yaml",
            "FLASHLOAN_SIGNER_REFERENCE": "env:PRIVATE",
            "FLASHLOAN_VERIFY_RPC_AT_STARTUP": "true",
            "PYTHONPATH": "/injected",
            "HTTP_PROXY": "https://private",
            "CODEX_HOME": "/private",
        }
    )
    assert env["PATH"] == "/bin" and env["SystemRoot"] == "C:/Windows"
    assert env["FLASHLOAN_VERIFY_RPC_AT_STARTUP"] == "false"
    assert env["FLASHLOAN_RUNTIME_MODE"] == "disabled"
    assert env["FLASHLOAN_JITO_ENABLED"] == "false"
    assert "private" not in json.dumps(env).lower()
    assert "PYTHONPATH" not in env


def _execute(monkeypatch, tmp_path, payload, *, exit_code=0):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def run(*args, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(
            args[0], exit_code, stdout=raw, stderr=b"secret diagnostic"
        )

    monkeypatch.setattr(q.subprocess, "run", run)
    return q.execute_step(
        Path("/installed/flashloan-bot"),
        q.PREFLIGHT_STEPS[0],
        cwd=tmp_path,
        environ={},
        timeout_seconds=1,
    )


@pytest.mark.parametrize(
    "raw", [b"{}", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"log\n{}"]
)
def test_malformed_or_wrong_schema_is_error_even_on_zero_exit(
    raw, tmp_path, monkeypatch
):
    receipt = _execute(monkeypatch, tmp_path, raw)
    assert receipt["state"] == "error"
    assert receipt["reason_codes"] == ["INVALID_COMMAND_EVIDENCE"]
    assert "secret diagnostic" not in json.dumps(receipt)


def test_zero_exit_does_not_hide_semantic_blocker(tmp_path, monkeypatch):
    payload = _payload(q.PREFLIGHT_STEPS[0])
    payload["capability_contract_valid"] = False
    receipt = _execute(monkeypatch, tmp_path, payload)
    assert receipt["state"] == "blocked"
    assert receipt["reason_codes"] == ["CAPABILITY_CONTRACT_INVALID"]


def test_nonzero_exit_cannot_pass_ready_json(tmp_path, monkeypatch):
    receipt = _execute(
        monkeypatch, tmp_path, _payload(q.PREFLIGHT_STEPS[0]), exit_code=2
    )
    assert receipt["state"] == "error"
    assert receipt["reason_codes"] == ["EXIT_CODE_CONTRADICTS_READY_PAYLOAD"]


def test_admission_checks_nested_authorities():
    step = q.PREFLIGHT_STEPS[3]
    payload = _payload(step)
    payload["platform"] = {"admitted": False, "blockers": ["PLATFORM_UNSUPPORTED"]}
    assert q._semantic_reasons(step, payload) == ["PLATFORM_UNSUPPORTED"]


def test_paper_vertical_requires_sender_free_safety():
    step = q.PREFLIGHT_STEPS[4]
    payload = _payload(step)
    payload["details"]["safety"]["sender_reachable"] = True
    assert q._semantic_reasons(step, payload) == ["PAPER_VERTICAL_SAFETY_UNPROVEN"]


@pytest.mark.parametrize(
    "failure,reason",
    [
        (
            subprocess.TimeoutExpired("fixed command", 1, output=b"secret"),
            "COMMAND_TIMEOUT",
        ),
        (FileNotFoundError("secret path"), "COMMAND_UNAVAILABLE"),
    ],
)
def test_timeout_and_spawn_error_are_redacted(failure, reason, tmp_path, monkeypatch):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(q.subprocess, "run", run)
    receipt = q.execute_step(
        Path("/installed/flashloan-bot"),
        q.PREFLIGHT_STEPS[0],
        cwd=tmp_path,
        environ={},
        timeout_seconds=1,
    )
    assert receipt["state"] == "error" and receipt["reason_codes"] == [reason]
    assert "secret" not in json.dumps(receipt)


def test_no_fallback_to_source_when_installed_entrypoint_missing(tmp_path):
    receipt = q.execute_step(
        None, q.PREFLIGHT_STEPS[0], cwd=tmp_path, environ={}, timeout_seconds=1
    )
    assert receipt["reason_codes"] == ["INSTALLED_ENTRYPOINT_UNAVAILABLE"]


@pytest.mark.parametrize("timeout", [0, 301])
def test_invalid_deadline_does_not_create_run(tmp_path, timeout):
    with pytest.raises(ValueError):
        q.collect_report(
            output_dir=tmp_path, project_root=tmp_path, timeout_seconds=timeout
        )
    assert not list(tmp_path.iterdir())


def test_inspection_cli_dispatches_report_without_legacy_owner(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(q, "run_cli", lambda **kwargs: calls.append(kwargs) or 3)

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy runtime reached")

    monkeypatch.setattr(cli_entrypoint.legacy_cli, "main", forbidden)
    assert (
        cli_entrypoint.main(["qualify-and-report", "--output-dir", str(tmp_path)]) == 3
    )
    assert calls[0]["timeout_seconds"] == 30


def test_report_cli_rejects_arbitrary_yaml(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("collector should not start")

    monkeypatch.setattr(q, "run_cli", forbidden)
    assert (
        cli_entrypoint.main(["--config-file", "private.yaml", "qualify-and-report"])
        == 2
    )
