"""Regression checks for repeated requests, invalid evidence and bounded children."""

import json
from pathlib import Path
import sys

import pytest

from src import qualification_report as q

SHA = "a" * 40


@pytest.fixture
def rig(tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    baseline = {
        "git_sha": SHA,
        "dirty": False,
        "package_installed": True,
        "console_target": "src.cli_pr189:main",
        "installed_source_matches": True,
    }
    monkeypatch.setattr(q, "inspect_baseline", lambda _: dict(baseline))
    calls = []

    def capture(argv, root, timeout):
        calls.append(argv)
        name, _, schema = next(step for step in q.STEPS if list(step[1]) == argv[1:])
        payload = {
            "schema_version": schema,
            "live_available": False,
            "signer_loaded": False,
            "sender_loaded": False,
            "capability_contract_valid": True,
            "runtime_modes": {"live": {"available": False}},
            "ok": True,
            "admitted": False,
        }
        return {
            "exit_code": 5 if name == "admission" else 0,
            "error": None,
            "stdout": json.dumps(payload).encode(),
            "stderr": b"",
            "started_at": "start",
            "ended_at": "end",
        }

    monkeypatch.setattr(q, "_capture", capture)
    original_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda p: p.name in {"flashloan-bot", "flashloan-bot.exe"}
        or original_is_file(p),
    )
    kwargs = {
        "repo_root": repo,
        "output_root": tmp_path / "runs",
        "request_id": "r1",
        "expected_sha": SHA,
        "timeout_seconds": 1,
    }
    return kwargs, calls, baseline


def test_report_completion_does_not_promote_blocked_admission(rig):
    args, calls, _ = rig
    receipt = q.qualify_and_report(**args)
    assert len(calls) == 4
    assert receipt["execution_status"] == "COMPLETE"
    assert receipt["domain_verdict"] == "BLOCKED"
    assert receipt["qualified"] is False
    assert receipt["transactions_sent"] == 0
    assert "admission:DOMAIN_BLOCKED" in receipt["blockers"]
    assert all(
        "--online" not in argv and "--check-secrets" not in argv for argv in calls
    )


def test_retry_returns_evidence_without_reexecuting(rig):
    args, calls, _ = rig
    q.qualify_and_report(**args)
    second = q.qualify_and_report(**args)
    assert second["reused"] is True
    assert len(calls) == 4


def test_same_id_cannot_change_inputs(rig):
    args, calls, _ = rig
    q.qualify_and_report(**args)
    with pytest.raises(ValueError, match="INPUT_CONFLICT"):
        q.qualify_and_report(**{**args, "timeout_seconds": 2})
    assert len(calls) == 4


def test_raw_and_receipt_tampering_are_detected(rig):
    args, _, _ = rig
    q.qualify_and_report(**args)
    run = args["output_root"] / "r1"
    (run / "status.stdout.txt").write_text("{}")
    with pytest.raises(ValueError, match="INTEGRITY_FAILED"):
        q.qualify_and_report(**args)


def test_receipt_tampering_is_detected(rig):
    args, _, _ = rig
    q.qualify_and_report(**args)
    receipt = args["output_root"] / "r1" / "qualification_receipt.json"
    receipt.write_text('{"qualified":true}')
    with pytest.raises(ValueError, match="RECEIPT_INTEGRITY_FAILED"):
        q.qualify_and_report(**args)


def test_interrupted_request_is_not_restarted(rig):
    args, calls, _ = rig
    q.qualify_and_report(**args)
    (args["output_root"] / "r1" / "qualification_receipt.json").unlink()
    with pytest.raises(ValueError, match="INCOMPLETE_RECONCILE"):
        q.qualify_and_report(**args)
    assert len(calls) == 4


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("dirty", True, "CHECKOUT_DIRTY"),
        ("git_sha", "b" * 40, "BASE_SHA_CHANGED"),
        ("installed_source_matches", False, "INSTALLED_SOURCE_MISMATCH"),
    ],
)
def test_baseline_rejection_prevents_children(rig, field, value, reason):
    args, calls, baseline = rig
    baseline[field] = value
    report = q.qualify_and_report(**args)
    assert reason in report["blockers"]
    assert calls == []


def test_malformed_success_json_is_not_evidence(rig, monkeypatch):
    args, _, _ = rig
    monkeypatch.setattr(
        q,
        "_capture",
        lambda *a: {
            "stdout": b"not json",
            "stderr": b"",
            "exit_code": 0,
            "error": None,
        },
    )
    report = q.qualify_and_report(**args)
    assert report["domain_verdict"] == "BLOCKED"
    assert all("RESPONSE_JSON_INVALID" in b for b in report["blockers"])


def test_successful_inspections_still_do_not_qualify_market(rig, monkeypatch):
    args, _, _ = rig
    original = q._capture

    def admitted(*a):
        result = original(*a)
        payload = json.loads(result["stdout"])
        payload["admitted"] = True
        result.update(stdout=json.dumps(payload).encode(), exit_code=0)
        return result

    monkeypatch.setattr(q, "_capture", admitted)
    receipt = q.qualify_and_report(**args)
    assert receipt["domain_verdict"] == "INSPECTED"
    assert receipt["qualified"] is False
    assert receipt["market_run_performed"] is False


def test_paths_and_request_parameters_fail_before_execution(rig):
    args, calls, _ = rig
    for change in (
        {"request_id": "../escape"},
        {"expected_sha": "main"},
        {"timeout_seconds": True},
        {"output_root": args["repo_root"] / "runs"},
    ):
        with pytest.raises(ValueError):
            q.qualify_and_report(**{**args, **change})
    assert not calls


def test_capture_enforces_timeout_and_output_limit(tmp_path):
    timeout = q._capture(
        [sys.executable, "-I", "-c", "import time; time.sleep(10)"], tmp_path, 1
    )
    assert timeout["error"] == "TIMEOUT"
    oversized = q._capture(
        [sys.executable, "-I", "-c", "print('x' * 2000000)"], tmp_path, 3
    )
    assert oversized["error"] == "OUTPUT_LIMIT"
    assert len(oversized["stdout"]) <= q.MAX_OUTPUT


def test_child_does_not_inherit_runtime_or_api_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-sentinel")
    monkeypatch.setenv("FLASHLOAN_PRIVATE_KEY", "test-sentinel")
    probe = q._capture(
        [
            sys.executable,
            "-I",
            "-c",
            "import os,json; print(json.dumps([k for k in os.environ if k in ('OPENAI_API_KEY','FLASHLOAN_PRIVATE_KEY')]))",
        ],
        tmp_path,
        3,
    )
    assert json.loads(probe["stdout"]) == []
