from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts import run_qualification_task as adapter


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "test",
        ],
        check=True,
        capture_output=True,
    )
    return root


def request(root):
    return {
        "schema_version": "qualification-task.v1",
        "task_id": "audit-1",
        "action": "qualification.audit",
        "source_commit": adapter._git(root, "rev-parse", "HEAD"),
        "release_id": "test-release",
        "repeat": 2,
    }


def blocked_payload(req):
    return {
        "verified": True,
        "production_qualification_passed": False,
        "live_enabled": False,
        "release_claim_allowed": False,
        "snapshot": {
            "source_commit": req["source_commit"],
            "release_id": req["release_id"],
            "missing_artifacts": ["shadow_campaign_report_digest"],
            "invalid_artifacts": [],
            "open_debt_items": ["provider.external-evidence"],
        },
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "trade.live"},
        {"shell": "echo hacked"},
        {"task_id": "../escape"},
        {"source_commit": "main"},
        {"repeat": True},
        {"repeat": 1000},
        {"repeat": 1},
    ],
)
def test_untrusted_model_requests_rejected(checkout, changes):
    req = request(checkout) | changes
    with pytest.raises(ValueError):
        adapter.validate_request(req)


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "request.json"
    path.write_text('{"action":"qualification.audit","action":"trade.live"}')
    with pytest.raises(ValueError, match="DUPLICATE"):
        adapter.read_json(path)


def test_stale_or_dirty_checkout_cannot_be_audited(checkout, tmp_path):
    req = request(checkout)
    with pytest.raises(ValueError, match="SOURCE_COMMIT_MISMATCH"):
        adapter.execute_task(
            req | {"source_commit": "a" * 40},
            root=checkout,
            output_root=tmp_path / "out",
        )
    (checkout / "unexpected.py").write_text("raise RuntimeError('modified')")
    with pytest.raises(ValueError, match="SOURCE_TREE_DIRTY"):
        adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")


def test_blocked_audit_keeps_blockers_and_replays_without_execution(
    checkout, tmp_path, monkeypatch
):
    req = request(checkout)
    calls = []

    def run(root, supplied):
        calls.append(supplied)
        return blocked_payload(supplied)

    monkeypatch.setattr(adapter, "_run_existing", run)
    first = adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")
    second = adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")
    assert len(calls) == 1
    assert first["receipt"] == second["receipt"]
    assert second["replayed"] is True
    assert first["receipt"]["status"] == "CHECKED_BLOCKED"
    assert first["receipt"]["campaign_executed"] is False
    assert first["receipt"]["missing_artifacts"] == ["shadow_campaign_report_digest"]
    with pytest.raises(ValueError, match="TASK_ID_CONFLICT"):
        adapter.execute_task(
            req | {"release_id": "different"},
            root=checkout,
            output_root=tmp_path / "out",
        )


def test_tampered_receipt_is_rejected(checkout, tmp_path, monkeypatch):
    req = request(checkout)
    monkeypatch.setattr(
        adapter, "_run_existing", lambda root, req: blocked_payload(req)
    )
    adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")
    path = tmp_path / "out/audit-1/receipt.json"
    receipt = json.loads(path.read_text())
    receipt["status"] = "CHECKED_REVIEW_ELIGIBLE"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="RECEIPT_DIGEST_MISMATCH"):
        adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")


@pytest.mark.parametrize(
    "field,value",
    [
        ("verified", False),
        ("live_enabled", True),
        ("release_claim_allowed", True),
        ("production_qualification_passed", "true"),
    ],
)
def test_invalid_result_leaves_claim_and_never_retries(
    checkout, tmp_path, monkeypatch, field, value
):
    req = request(checkout)
    monkeypatch.setattr(
        adapter,
        "_run_existing",
        lambda root, req: blocked_payload(req) | {field: value},
    )
    with pytest.raises(ValueError):
        adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")
    with pytest.raises(ValueError, match="TASK_INCOMPLETE_OR_CONCURRENT"):
        adapter.execute_task(req, root=checkout, output_root=tmp_path / "out")


def test_output_cannot_modify_checkout(checkout):
    with pytest.raises(ValueError, match="OUTSIDE_CHECKOUT"):
        adapter.execute_task(
            request(checkout), root=checkout, output_root=checkout / "receipts"
        )
