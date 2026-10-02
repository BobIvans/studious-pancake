from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import occ_memory_qualification_bridge as bridge


def request(text="Проверь готовность бота"):
    return {
        "schema_version": "occ.qualification-action.v1",
        "request_id": "rnd-inspection-20261002-001",
        "action_id": "qualify_and_report",
        "text": text,
    }


def profile(root: Path, output: Path):
    return {
        "schema_version": "studious-pancake.occ-qualification-profile.v1",
        "repo_root": str(root),
        "output_root": str(output),
        "expected_bot_sha": "a" * 40,
        "timeout_seconds": 30,
        "occ_repository": "BobIvans/scaling-chrome-extensions",
        "occ_base_sha": "b" * 40,
        "occ_head_sha": "c" * 40,
        "source_refs": [
            {
                "source_id": "chat:qualification-goal",
                "version": "2026-10-02",
                "sha256": "d" * 64,
            }
        ],
    }


def blocked_inner(req_id: str):
    return {
        "request_id": req_id,
        "git_sha": "a" * 40,
        "execution_status": "COMPLETE",
        "domain_verdict": "BLOCKED",
        "blockers": ["admission:RUNTIME_ADMISSION_BLOCKED"],
        "qualified": False,
        "release_authorized": False,
        "live_authorized": False,
        "transactions_sent": 0,
    }


def test_native_occ_request_is_admitted():
    assert bridge.validate_request(request())["action_id"] == "qualify_and_report"


@pytest.mark.parametrize(
    "change",
    [
        {"shell": "echo hacked"},
        {"repo_root": "/tmp/other"},
        {"expected_sha": "a" * 40},
        {"action_id": "trade.live"},
        {"text": "Не проверяй готовность бота"},
    ],
)
def test_source_or_model_cannot_expand_execution_authority(change):
    raw = request() | change
    with pytest.raises(ValueError):
        bridge.validate_request(raw)


def test_profile_source_refs_are_metadata_only(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "out"
    validated = bridge.validate_operator_profile(profile(root, output))
    assert validated["source_refs"][0]["source_id"] == "chat:qualification-goal"
    assert "text" not in validated["source_refs"][0]


def test_blocked_result_projects_source_linked_receipt_and_replays(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "out"
    calls = []

    def invoke(**kwargs):
        calls.append(kwargs)
        return blocked_inner(kwargs["request_id"])

    first = bridge.execute_request(
        request(), profile(root, output), adapter_root=root, invoke=invoke
    )
    second = bridge.execute_request(
        request(), profile(root, output), adapter_root=root, invoke=invoke
    )

    assert len(calls) == 1
    assert first["replayed"] is False
    assert second["replayed"] is True
    receipt = first["receipt"]
    assert receipt["domain_verdict"] == "BLOCKED"
    assert receipt["next_blocker"] == "admission:RUNTIME_ADMISSION_BLOCKED"
    assert receipt["source_refs"][0]["sha256"] == "d" * 64
    assert receipt["bot"]["inspector_owner"] == bridge.INSPECTOR_OWNER
    assert receipt["qualified"] is False
    assert receipt["live_authorized"] is False
    assert receipt["transactions_sent"] == 0
    assert "text" not in calls[0]
    assert "source_refs" not in calls[0]


def test_changed_payload_under_same_request_id_is_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "out"

    bridge.execute_request(
        request(),
        profile(root, output),
        adapter_root=root,
        invoke=lambda **kwargs: blocked_inner(kwargs["request_id"]),
    )
    with pytest.raises(ValueError, match="REQUEST_ID_INPUT_CONFLICT"):
        bridge.execute_request(
            request("Check bot readiness"),
            profile(root, output),
            adapter_root=root,
            invoke=lambda **kwargs: blocked_inner(kwargs["request_id"]),
        )


def test_interrupted_execution_requires_reconciliation_and_is_not_retried(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "out"
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        bridge.execute_request(
            request(), profile(root, output), adapter_root=root, invoke=fail
        )
    with pytest.raises(ValueError, match="RECONCILE"):
        bridge.execute_request(
            request(), profile(root, output), adapter_root=root, invoke=fail
        )
    assert len(calls) == 1


def test_tampered_receipt_is_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "out"
    bridge.execute_request(
        request(),
        profile(root, output),
        adapter_root=root,
        invoke=lambda **kwargs: blocked_inner(kwargs["request_id"]),
    )
    path = (
        output / "occ_memory_qualification" / request()["request_id"] / "receipt.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["domain_verdict"] = "PAPER_PASS"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="INTEGRITY"):
        bridge.execute_request(
            request(),
            profile(root, output),
            adapter_root=root,
            invoke=lambda **kwargs: blocked_inner(kwargs["request_id"]),
        )


def test_output_inside_checkout_is_rejected(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ValueError, match="OUTSIDE_CHECKOUT"):
        bridge.execute_request(
            request(),
            profile(root, root / "receipts"),
            adapter_root=root,
            invoke=lambda **kwargs: blocked_inner(kwargs["request_id"]),
        )
