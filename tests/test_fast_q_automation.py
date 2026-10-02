from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src import fast_q_automation as a

SHA = "a" * 40


def request(action="qualify_and_report", *, request_id="job-1", inputs=None):
    return {
        "schema_version": a.REQUEST_SCHEMA,
        "request_id": request_id,
        "idempotency_key": request_id,
        "action": action,
        "text": None,
        "inputs": {} if inputs is None else inputs,
        "proposal": None,
    }


def child_receipt(root: Path, request_id="qualification-1", blockers=None):
    run = root / "qualification" / request_id
    run.mkdir(parents=True)
    receipt = {
        "schema_version": "fast-q1.qualification-receipt.v2",
        "action_id": "qualify_and_report",
        "profile": "offline_sender_free",
        "input_digest": "d" * 64,
        "request_id": request_id,
        "git_sha": SHA,
        "domain_verdict": "BLOCKED" if blockers else "PAPER_PASS",
        "sender_free_pass": not blockers,
        "qualified": False,
        "release_authorized": False,
        "live_authorized": False,
        "transactions_sent": 0,
        "blockers": list(blockers or ()),
        "next_action": (
            "resolve_first_blocker" if blockers else "review_sender_free_evidence"
        ),
    }
    path = run / "qualification_receipt.json"
    path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": "fast-q1.run-manifest.v2",
        "action_id": "qualify_and_report",
        "input_digest": "d" * 64,
        "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "state": "COMPLETE",
    }
    (run / "run_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return receipt


def test_legacy_archive_request_routes_exact_russian_phrase():
    normalized = a.validate_request(
        {
            "schema_version": a.LEGACY_REQUEST_SCHEMA,
            "request_id": "qualification-next-001",
            "text": "Проверь готовность бота",
        }
    )
    assert normalized["action"] == "qualify_and_report"
    assert normalized["idempotency_key"] == "qualification-next-001"


@pytest.mark.parametrize(
    "raw,reason",
    [
        (
            {
                "schema_version": a.REQUEST_SCHEMA,
                "request_id": "x",
                "idempotency_key": "x",
                "action": None,
                "text": "please do live trading",
                "inputs": {},
                "proposal": None,
            },
            "LIVE_OR_UNSAFE",
        ),
        (
            {
                "schema_version": a.REQUEST_SCHEMA,
                "request_id": "x",
                "idempotency_key": "x",
                "action": None,
                "text": "do not check bot readiness",
                "inputs": {},
                "proposal": None,
            },
            "NEGATED",
        ),
        (
            {
                "schema_version": a.REQUEST_SCHEMA,
                "request_id": "x",
                "idempotency_key": "x",
                "action": None,
                "text": "maybe do something useful",
                "inputs": {},
                "proposal": None,
            },
            "AMBIGUOUS",
        ),
    ],
)
def test_unsafe_negated_and_ambiguous_text_fail_closed(raw, reason):
    with pytest.raises(ValueError, match=reason):
        a.validate_request(raw)


def test_unknown_action_and_action_text_conflict_are_rejected():
    raw = request()
    raw["action"] = "trade_live"
    with pytest.raises(ValueError, match="ACTION_UNKNOWN"):
        a.validate_request(raw)
    raw = request("qualify_and_report")
    raw["text"] = "inspect current blocker"
    with pytest.raises(ValueError, match="ACTION_TEXT_CONFLICT"):
        a.validate_request(raw)


def test_model_proposal_is_advisory_only(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    monkeypatch.setattr(
        a,
        "_execute_qualification",
        lambda *args, **kwargs: {
            "status": "INSPECTED",
            "blockers": [],
            "first_blocker": None,
            "next_action": "review_sender_free_evidence",
            "limitations": [],
        },
    )
    raw = request()
    raw["proposal"] = {"source": "model", "action": "transcribe_local_audio"}
    result = a.execute_request(
        raw,
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    assert result["action"] == "qualify_and_report"
    assert result["proposal"]["advisory_only"] is True
    assert result["proposal"]["matched"] is False


def test_secret_bearing_input_is_rejected():
    raw = request(
        "inspect_current_blocker",
        inputs={"qualification_request_id": "q1", "api_key": "secret"},
    )
    with pytest.raises(ValueError, match="SECRET_BEARING"):
        a.validate_request(raw)


def test_unknown_input_field_is_rejected():
    raw = request("qualify_and_report", inputs={"unexpected": "x"})
    with pytest.raises(ValueError, match="ACTION_INPUT_FIELDS_INVALID"):
        a.validate_request(raw)


def test_same_request_reuses_receipt_without_second_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    calls = []

    def execute(*args, **kwargs):
        calls.append(1)
        return {
            "status": "INSPECTED",
            "next_action": "inspect_current_blocker",
            "limitations": [],
        }

    monkeypatch.setattr(a, "_execute_qualification", execute)
    raw = request()
    first = a.execute_request(
        raw,
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    second = a.execute_request(
        raw,
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    assert len(calls) == 1
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert second["reused"] is True


def test_changed_input_cannot_reuse_idempotency_key(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    monkeypatch.setattr(
        a,
        "_execute_qualification",
        lambda *args, **kwargs: {
            "status": "INSPECTED",
            "next_action": None,
            "limitations": [],
        },
    )
    a.execute_request(
        request(),
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_CONFLICT"):
        a.execute_request(
            request("ingest_local_content"),
            repo_root=tmp_path / "repo",
            output_root=tmp_path / "out",
            expected_sha=SHA,
        )


def test_incomplete_claim_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    claim = tmp_path / "out/actions/job-1"
    claim.mkdir(parents=True)
    with pytest.raises(ValueError, match="ACTION_INCOMPLETE_OR_CONCURRENT"):
        a.execute_request(
            request(),
            repo_root=tmp_path / "repo",
            output_root=tmp_path / "out",
            expected_sha=SHA,
        )


def test_tampered_action_receipt_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    monkeypatch.setattr(
        a,
        "_execute_qualification",
        lambda *args, **kwargs: {
            "status": "INSPECTED",
            "next_action": None,
            "limitations": [],
        },
    )
    raw = request()
    a.execute_request(
        raw,
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    path = tmp_path / "out/actions/job-1/receipt.json"
    payload = json.loads(path.read_text())
    payload["live_authorized"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="RECEIPT_DIGEST_MISMATCH"):
        a.execute_request(
            raw,
            repo_root=tmp_path / "repo",
            output_root=tmp_path / "out",
            expected_sha=SHA,
        )


def test_current_blocker_and_bounded_external_repair_task(tmp_path, monkeypatch):
    output = tmp_path / "out"
    child_receipt(
        output,
        blockers=["paper-shadow:blocked_missing_wallet_public_key", "other"],
    )
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    inspect = a.execute_request(
        request(
            "inspect_current_blocker",
            request_id="inspect-1",
            inputs={"qualification_request_id": "qualification-1"},
        ),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    assert inspect["result"]["first_blocker"] == (
        "paper-shadow:blocked_missing_wallet_public_key"
    )
    task = a.execute_request(
        request(
            "prepare_repair_task",
            request_id="repair-1",
            inputs={"qualification_request_id": "qualification-1"},
        ),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )["result"]["repair_task"]
    assert task["owner_files"] == ["src/runtime_discovery_coordinator.py"]
    assert task["patch_allowed"] is False
    assert task["stop_reason"] == "EXTERNAL_OPERATOR_INPUT_REQUIRED"
    assert task["automatic_patch_performed"] is False
    assert task["max_runtime_blockers_per_iteration"] == 1


def test_corrupt_or_stale_child_receipt_is_rejected(tmp_path, monkeypatch):
    output = tmp_path / "out"
    child_receipt(output, blockers=["paper-shadow:blocked_missing_wallet_public_key"])
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    manifest = output / "qualification/qualification-1/run_manifest.json"
    payload = json.loads(manifest.read_text())
    payload["receipt_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="CHILD_RECEIPT_DIGEST_MISMATCH"):
        a.execute_request(
            request(
                "inspect_current_blocker",
                inputs={"qualification_request_id": "qualification-1"},
            ),
            repo_root=tmp_path / "repo",
            output_root=output,
            expected_sha=SHA,
        )


def test_fixed_validation_runs_only_registry_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    seen = []

    def run(argv, repo, timeout):
        seen.append(tuple(argv))
        return {"argv": list(argv), "exit_code": 0}

    monkeypatch.setattr(a, "_run_command", run)
    result = a.execute_request(
        request(
            "run_focused_validation",
            inputs={"validation_set": "fast_q_automation"},
        ),
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    assert result["status"] == "TEST_PASSED"
    assert seen == list(a.FIXED_VALIDATIONS["fast_q_automation"])


def test_external_adapters_are_contract_only(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    result = a.execute_request(
        request("transcribe_local_audio"),
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "out",
        expected_sha=SHA,
    )
    contract = result["result"]["adapter_contract"]
    assert result["status"] == "EXTERNAL_ADAPTER_REQUIRED"
    assert contract["core_execution_performed"] is False
    assert contract["model_supplied_paths_allowed"] is False
    assert contract["heavy_dependencies_in_core"] is False
    assert result["paid_api_fallback"] is False


def test_state_generation_does_not_promote_qualification(tmp_path, monkeypatch):
    output = tmp_path / "out"
    child_receipt(output, blockers=["paper-shadow:blocked_missing_wallet_public_key"])
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    monkeypatch.setattr(
        a,
        "_run_command",
        lambda argv, repo, timeout: {
            "argv": [Path(argv[0]).name, *argv[1:]],
            "exit_code": 0,
        },
    )
    test_receipt = a.execute_request(
        request(
            "run_focused_validation",
            request_id="validation-1",
            inputs={"validation_set": "fast_q_automation"},
        ),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    assert test_receipt["status"] in {"TEST_PASSED", "TEST_FAILED"}
    state = a.execute_request(
        request(
            "update_receipt_state",
            request_id="state-1",
            inputs={
                "source_idempotency_key": "validation-1",
                "qualification_request_id": "qualification-1",
            },
        ),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    assert state["result"]["status_ladder"]["qualified"] == "NOT_QUALIFIED"
    assert state["result"]["status_ladder"]["test_passed"] == "CONFIRMED"
    assert state["live_authorized"] is False
    assert state["transactions_sent"] == 0


@pytest.mark.parametrize(
    "text",
    ["Проверь квалификацию бота", "qualify and report", "Check bot readiness"],
)
def test_archive_qualification_uses_canonical_bridge_intent(text):
    normalized = a.validate_request(
        {"schema_version": a.LEGACY_REQUEST_SCHEMA, "request_id": "q1", "text": text}
    )
    assert normalized["action"] == "qualify_and_report"


def test_archive_qualification_schema_cannot_route_external_actions():
    with pytest.raises(ValueError, match="COMMAND_INTENT_NOT_ADMITTED"):
        a.validate_request(
            {
                "schema_version": a.LEGACY_REQUEST_SCHEMA,
                "request_id": "q1",
                "text": "prepare local audio transcription",
            }
        )


def test_current_occ_envelope_requires_provenance_profile():
    from src.occ_memory_qualification_bridge import validate_request

    envelope = {
        "schema_version": a.LEGACY_REQUEST_SCHEMA,
        "request_id": "q1",
        "action_id": "qualify_and_report",
        "text": "Проверь готовность бота",
    }
    assert validate_request(envelope) == envelope
    with pytest.raises(ValueError, match="OCC_OPERATOR_PROFILE_REQUIRED"):
        a.validate_request(envelope)


def _write_action_receipt(path, payload):
    payload = {
        k: v for k, v in payload.items() if k not in {"receipt_sha256", "reused"}
    }
    payload["output_sha256"] = a._digest(payload["result"])
    payload["receipt_sha256"] = a._digest(payload)
    path.write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"source_commit": "b" * 40}, "STATE_SOURCE_RECEIPT_STALE_SHA"),
        ({"idempotency_key": "other"}, "STATE_SOURCE_RECEIPT_ID_MISMATCH"),
        ({"transactions_sent": False}, "RECEIPT_EFFECT_BOUNDARY_INVALID"),
        ({"live_authorized": True}, "RECEIPT_EFFECT_BOUNDARY_INVALID"),
    ],
)
def test_state_rejects_hash_valid_but_unbound_evidence(
    tmp_path, monkeypatch, mutation, reason
):
    output = tmp_path / "out"
    child_receipt(output)
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    prior = a.execute_request(
        request("ingest_local_content", request_id="source-1"),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    _write_action_receipt(
        output / "actions/source-1/receipt.json", {**prior, **mutation}
    )
    with pytest.raises(ValueError, match=reason):
        a.execute_request(
            request(
                "update_receipt_state",
                request_id="state-1",
                inputs={
                    "source_idempotency_key": "source-1",
                    "qualification_request_id": "qualification-1",
                },
            ),
            repo_root=tmp_path / "repo",
            output_root=output,
            expected_sha=SHA,
        )
    assert not (output / "actions/state-1/state.json").exists()


def test_state_rejects_empty_test_pass_even_with_valid_digest(tmp_path, monkeypatch):
    output = tmp_path / "out"
    child_receipt(output)
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    monkeypatch.setattr(
        a,
        "_run_command",
        lambda argv, repo, timeout: {
            "argv": [Path(argv[0]).name, *argv[1:]],
            "exit_code": 0,
        },
    )
    prior = a.execute_request(
        request(
            "run_focused_validation",
            request_id="tests-1",
            inputs={
                "validation_set": "fast_q_automation",
            },
        ),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    prior["result"]["tests"] = []
    _write_action_receipt(output / "actions/tests-1/receipt.json", prior)
    with pytest.raises(ValueError, match="STATE_VALIDATION_EVIDENCE_INVALID"):
        a.execute_request(
            request(
                "update_receipt_state",
                request_id="state-1",
                inputs={
                    "source_idempotency_key": "tests-1",
                    "qualification_request_id": "qualification-1",
                },
            ),
            repo_root=tmp_path / "repo",
            output_root=output,
            expected_sha=SHA,
        )


def test_external_contract_does_not_confirm_implementation(tmp_path, monkeypatch):
    output = tmp_path / "out"
    child_receipt(output)
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    a.execute_request(
        request("ingest_local_content", request_id="external-1"),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    result = a.execute_request(
        request(
            "update_receipt_state",
            request_id="state-1",
            inputs={
                "source_idempotency_key": "external-1",
                "qualification_request_id": "qualification-1",
            },
        ),
        repo_root=tmp_path / "repo",
        output_root=output,
        expected_sha=SHA,
    )
    assert result["result"]["status_ladder"]["implemented"] == "NOT_EVIDENCED"
    assert result["result"]["status_ladder"]["test_passed"] == "NOT_EVIDENCED"
    state = json.loads((output / "actions/state-1/state.json").read_text())
    assert state["qualification_request_id"] == "qualification-1"
    assert (
        state["qualification_receipt_sha256"]
        == hashlib.sha256(
            (
                output / "qualification/qualification-1/qualification_receipt.json"
            ).read_bytes()
        ).hexdigest()
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"schema_version": "historical"}, "CHILD_CONTRACT_BINDING_INVALID"),
        ({"input_digest": "c" * 64}, "CHILD_CONTRACT_BINDING_INVALID"),
        ({"release_authorized": True}, "RELEASE_AUTHORITY_ESCALATION"),
        ({"transactions_sent": False}, "TRANSACTION_EFFECT_DETECTED"),
    ],
)
def test_child_contract_rejects_hash_valid_wrong_owner_or_effect(
    tmp_path, mutation, reason
):
    output = tmp_path / "out"
    child = child_receipt(output)
    run = output / "qualification/qualification-1"
    path = run / "qualification_receipt.json"
    path.write_text(json.dumps({**child, **mutation}))
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=reason):
        a._qualification_receipt(output, "qualification-1", SHA)


def test_qualification_execution_checks_persisted_child_and_replay(
    tmp_path, monkeypatch
):
    from src import qualification_report as owner

    output = tmp_path / "out"
    persisted = child_receipt(output, request_id="job-1")
    monkeypatch.setattr(
        owner,
        "qualify_and_report",
        lambda **kwargs: {
            **persisted,
            "reused": True,
        },
    )
    assert (
        a._execute_qualification(request(), tmp_path / "repo", output, SHA, 30)[
            "status"
        ]
        == "INSPECTED"
    )
    monkeypatch.setattr(
        owner,
        "qualify_and_report",
        lambda **kwargs: {
            **persisted,
            "blockers": ["different"],
        },
    )
    with pytest.raises(ValueError, match="CHILD_RETURNED_RECEIPT_MISMATCH"):
        a._execute_qualification(request(), tmp_path / "repo", output, SHA, 30)


def test_output_root_cannot_be_inside_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "_check_source", lambda repo, expected: {"git_sha": SHA})
    with pytest.raises(ValueError, match="OUTPUT_MUST_BE_OUTSIDE_CHECKOUT"):
        a.execute_request(
            request(),
            repo_root=tmp_path,
            output_root=tmp_path / "receipts",
            expected_sha=SHA,
        )
