from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from src import automation_cli_pr189
from src import qualification_report as q

SHA = "a" * 40


def _payload(name: str, schema: str) -> dict[str, object]:
    payload: dict[str, object] = {"schema_version": schema}
    if name == "status":
        payload.update(
            capability_contract_valid=True,
            live_available=False,
            live_enabled=False,
        )
    elif name == "capabilities":
        payload["runtime_modes"] = {"live": {"available": False}}
    elif name == "doctor":
        payload["ok"] = True
    elif name == "admission":
        payload.update(
            admitted=True,
            platform={"admitted": True},
            command={"admitted": True},
        )
    elif name == "paper-shadow":
        payload.update(
            status="healthy_idle",
            terminal_reason="healthy_idle",
            readiness={"ready_for_next_cycle": True, "dependency_reasons": []},
        )
    return payload


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    bot = tmp_path / "flashloan-bot"
    bot.write_text("#!/bin/sh\n", encoding="utf-8")
    baseline = {
        "schema_version": q.BASELINE_SCHEMA,
        "repository_root": str(repo),
        "git_sha": SHA,
        "dirty": False,
        "python_version": "3.13",
        "python_executable": sys.executable,
        "package_installed": True,
        "package_version": "test",
        "flashloan_bot_target": "src.cli_pr189:main",
        "flashloan_checks_target": "src.automation_cli_pr189:main",
        "record_sha256": "1" * 64,
        "installed_source_matches": True,
        "installed_console_script": str(bot),
        "capabilities_sha256": "2" * 64,
    }
    monkeypatch.setattr(q, "inspect_baseline", lambda _repo: dict(baseline))
    calls: list[list[str]] = []

    def capture(argv, *, repo, timeout_seconds, environment):
        calls.append(list(argv))
        args = tuple(argv[1:])
        step = None
        schema = None
        for name, fixed, expected_schema in q.PREFLIGHT_STEPS:
            if args == fixed:
                step = name
                schema = expected_schema
                break
        if step is None and args[0] == "paper-shadow":
            step = "paper-shadow"
            schema = q.PAPER_STEP[2]
        assert step is not None and schema is not None
        return {
            "exit_code": 0,
            "error": None,
            "stdout": json.dumps(_payload(step, schema)).encode("utf-8"),
            "stderr": b"",
            "started_at": "start",
            "ended_at": "end",
        }

    monkeypatch.setattr(q, "_capture", capture)
    kwargs = {
        "repo_root": repo,
        "output_root": tmp_path / "runs",
        "request_id": "job-1",
        "expected_sha": SHA,
        "profile": q.PROFILE,
        "timeout_seconds": 1,
    }
    return kwargs, calls, baseline


def test_success_runs_exactly_four_preflights_then_one_paper_pass(rig):
    args, calls, _ = rig
    receipt = q.qualify_and_report(**args)
    assert len(calls) == 5
    assert [Path(call[0]).name for call in calls] == ["flashloan-bot"] * 5
    assert receipt["execution_status"] == "COMPLETE"
    assert receipt["domain_verdict"] == "PAPER_PASS"
    assert receipt["sender_free_pass"] is True
    assert receipt["paper_shadow_performed"] is True
    assert receipt["qualified"] is False
    assert receipt["release_authorized"] is False
    assert receipt["live_authorized"] is False
    assert receipt["transactions_sent"] == 0
    run = Path(receipt["run_directory"])
    assert (run / "paper-shadow.jsonl").exists() is False
    assert (run / "qualification_receipt.json").is_file()
    assert (run / "run_manifest.json").is_file()
    assert (run / "BLOCKERS_RU.txt").is_file()


def test_blocked_admission_skips_paper_shadow(rig, monkeypatch: pytest.MonkeyPatch):
    args, calls, _ = rig
    original = q._capture

    def blocked(argv, **kwargs):
        result = original(argv, **kwargs)
        if "runtime-admission" in argv:
            payload = json.loads(result["stdout"])
            payload["admitted"] = False
            payload["platform"] = {"admitted": False}
            result["stdout"] = json.dumps(payload).encode()
            result["exit_code"] = 3
        return result

    monkeypatch.setattr(q, "_capture", blocked)
    receipt = q.qualify_and_report(**args)
    assert len(calls) == 4
    assert receipt["sender_free_pass"] is False
    assert receipt["paper_shadow_performed"] is False
    assert receipt["domain_verdict"] == "BLOCKED"
    assert any(item.startswith("admission:") for item in receipt["blockers"])


def test_paper_shadow_block_is_preserved_not_promoted(rig, monkeypatch):
    args, _, _ = rig
    original = q._capture

    def blocked(argv, **kwargs):
        result = original(argv, **kwargs)
        if "paper-shadow" in argv:
            payload = json.loads(result["stdout"])
            payload["status"] = "blocked"
            payload["terminal_reason"] = "blocked_no_discovery_composition"
            payload["readiness"] = {
                "ready_for_next_cycle": False,
                "dependency_reasons": ["blocked_no_discovery_composition"],
            }
            result["stdout"] = json.dumps(payload).encode()
            result["exit_code"] = 3
        return result

    monkeypatch.setattr(q, "_capture", blocked)
    receipt = q.qualify_and_report(**args)
    assert receipt["paper_shadow_performed"] is True
    assert receipt["sender_free_pass"] is False
    assert "paper-shadow:blocked_no_discovery_composition" in receipt["blockers"]
    assert receipt["transactions_sent"] == 0


def test_same_request_reuses_receipt_without_reexecution(rig):
    args, calls, _ = rig
    first = q.qualify_and_report(**args)
    second = q.qualify_and_report(**args)
    assert first["input_digest"] == second["input_digest"]
    assert second["reused"] is True
    assert len(calls) == 5


def test_same_request_id_with_changed_input_conflicts(rig):
    args, calls, _ = rig
    q.qualify_and_report(**args)
    with pytest.raises(ValueError, match="REQUEST_ID_INPUT_CONFLICT"):
        q.qualify_and_report(**{**args, "timeout_seconds": 2})
    assert len(calls) == 5


def test_incomplete_run_is_not_retried_blindly(rig):
    args, calls, _ = rig
    receipt = q.qualify_and_report(**args)
    run = Path(receipt["run_directory"])
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["state"] = "RUNNING"
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="RUN_INCOMPLETE_RECONCILE_BEFORE_RETRY"):
        q.qualify_and_report(**args)
    assert len(calls) == 5


def test_raw_tampering_is_detected_on_reuse(rig):
    args, _, _ = rig
    receipt = q.qualify_and_report(**args)
    run = Path(receipt["run_directory"])
    (run / "status.stdout.bin").write_bytes(b"{}")
    with pytest.raises(ValueError, match="ARTIFACT_INTEGRITY_FAILED"):
        q.qualify_and_report(**args)


def test_receipt_tampering_is_detected_on_reuse(rig):
    args, _, _ = rig
    receipt = q.qualify_and_report(**args)
    run = Path(receipt["run_directory"])
    (run / "qualification_receipt.json").write_text(
        '{"qualified": true}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ARTIFACT_INTEGRITY_FAILED|RECEIPT"):
        q.qualify_and_report(**args)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("dirty", True, "CHECKOUT_DIRTY"),
        ("git_sha", "b" * 40, "BASE_SHA_CHANGED"),
        ("installed_source_matches", False, "INSTALLED_SOURCE_MISMATCH"),
        ("flashloan_bot_target", "legacy:main", "INSTALLED_BOT_ENTRYPOINT_MISMATCH"),
    ],
)
def test_bad_baseline_prevents_child_commands(rig, field, value, reason):
    args, calls, baseline = rig
    baseline[field] = value
    receipt = q.qualify_and_report(**args)
    assert reason in receipt["blockers"]
    assert calls == []
    assert receipt["paper_shadow_performed"] is False


def test_invalid_json_is_evidence_blocker(rig, monkeypatch):
    args, _, _ = rig
    monkeypatch.setattr(
        q,
        "_capture",
        lambda *a, **kw: {
            "exit_code": 0,
            "error": None,
            "stdout": b"not-json",
            "stderr": b"",
            "started_at": "start",
            "ended_at": "end",
        },
    )
    receipt = q.qualify_and_report(**args)
    assert receipt["domain_verdict"] == "BLOCKED"
    assert receipt["blockers"] == ["status:RESPONSE_JSON_INVALID"]


def test_stop_file_cancels_before_children(rig, monkeypatch):
    args, calls, _ = rig
    monkeypatch.setattr(q, "_stop_requested", lambda _run: True)
    receipt = q.qualify_and_report(**args)
    assert receipt["execution_status"] == "CANCELLED"
    assert "CANCELLED_BY_STOP_FILE" in receipt["blockers"]
    assert calls == []


def test_paths_profile_and_request_parameters_fail_before_execution(rig):
    args, calls, _ = rig
    for change in (
        {"request_id": "../escape"},
        {"expected_sha": "main"},
        {"profile": "online"},
        {"timeout_seconds": True},
        {"output_root": args["repo_root"] / "runs"},
    ):
        with pytest.raises(ValueError):
            q.qualify_and_report(**{**args, **change})
    assert calls == []


def test_capture_enforces_timeout_and_streaming_output_limit(tmp_path):
    timeout = q._capture(
        [sys.executable, "-I", "-c", "import time; time.sleep(10)"],
        repo=tmp_path,
        timeout_seconds=1,
        environment=q._environment(),
    )
    assert timeout["error"] == "TIMEOUT"
    oversized = q._capture(
        [sys.executable, "-I", "-c", "print('x' * 2000000)"],
        repo=tmp_path,
        timeout_seconds=5,
        environment=q._environment(),
    )
    assert oversized["error"] == "OUTPUT_LIMIT"
    assert len(oversized["stdout"]) <= q.MAX_OUTPUT


def test_child_environment_drops_credentials_and_proxy_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("FLASHLOAN_PRIVATE_KEY", "secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://example.invalid")
    env = q._environment()
    assert "OPENAI_API_KEY" not in env
    assert "FLASHLOAN_PRIVATE_KEY" not in env
    assert "HTTPS_PROXY" not in env
    assert env["LIVE_TRADING_ENABLED"] == "false"
    assert env["FLASHLOAN_JUPITER_ENABLED"] == "false"


def test_cli_inspect_preserves_blocked_domain_as_successful_inspection(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        q,
        "qualify_and_report",
        lambda **kwargs: {
            "schema_version": q.SCHEMA,
            "sender_free_pass": False,
            "blockers": ["admission:RUNTIME_ADMISSION_BLOCKED"],
            "qualified": False,
            "live_authorized": False,
        },
    )
    code = automation_cli_pr189.main(
        [
            "qualify-and-report",
            "inspect",
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path.parent / "out"),
            "--request-id",
            "r",
            "--expected-sha",
            SHA,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["verdict"] == "blocked"
    assert payload["ready"] is False
    assert payload["details"]["qualified"] is False
