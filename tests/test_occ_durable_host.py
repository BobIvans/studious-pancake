from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess

import pytest

from scripts import run_occ_native_host as host
from src.occ_durable_library import OCCDurableError, OCCDurableLibrary, digest


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
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


def request(version: str, source_commit: str) -> dict[str, object]:
    return {
        "schema_version": host.SCHEMA,
        "job_id": "occ-audit-1",
        "action_id": "qualification.audit",
        "namespace": "local",
        "source_id": "chat-export",
        "context_version_sha256": version,
        "source_commit": source_commit,
        "release_id": "occ-test",
        "repeat": 2,
    }


def fake_delegate(calls: list[object]):
    def run(raw: object, root: Path, output_root: Path):
        calls.append(raw)
        task = dict(raw)
        task_dir = output_root / task["task_id"]
        task_dir.mkdir(parents=True, exist_ok=True)
        receipt = {
            "schema_version": "qualification-task-receipt.v1",
            "request": task,
            "status": "CHECKED_BLOCKED",
            "missing_artifacts": ["external-evidence"],
            "invalid_artifacts": [],
            "open_debt_items": [],
        }
        receipt["receipt_sha256"] = "a" * 64
        (task_dir / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return {"replayed": False, "receipt": receipt}

    return run


def test_library_is_append_only_and_duplicate_sync_is_noop(tmp_path: Path) -> None:
    library = OCCDurableLibrary(tmp_path / "content.sqlite3")
    first = library.sync(
        namespace="local",
        source_id="chat",
        content="one",
        allowed_namespaces={"local"},
    )
    duplicate = library.sync(
        namespace="local",
        source_id="chat",
        content="one",
        allowed_namespaces={"local"},
    )
    second = library.sync(
        namespace="local",
        source_id="chat",
        content="two",
        allowed_namespaces={"local"},
    )
    assert duplicate["duplicate"] is True
    assert duplicate["event_seq"] == first["event_seq"] == 1
    assert second["event_seq"] == 2
    assert (
        library.latest(
            namespace="local", source_id="chat", allowed_namespaces={"local"}
        ).version_sha256
        == second["version_sha256"]
    )
    assert (
        library.get_version(
            namespace="local",
            source_id="chat",
            version_sha256=first["version_sha256"],
            allowed_namespaces={"local"},
        ).version_sha256
        == first["version_sha256"]
    )
    assert (
        len(
            library.history(
                namespace="local", source_id="chat", allowed_namespaces={"local"}
            )
        )
        == 2
    )


def test_namespace_is_denied_before_content_lookup(tmp_path: Path) -> None:
    library = OCCDurableLibrary(tmp_path / "content.sqlite3")
    library.sync(
        namespace="private",
        source_id="chat",
        content="secret-ish source text",
        allowed_namespaces={"private"},
    )
    with pytest.raises(OCCDurableError, match="SOURCE_NAMESPACE_DENIED"):
        library.latest(
            namespace="private", source_id="chat", allowed_namespaces={"public"}
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"action_id": "trade.live"},
        {"shell": "echo hacked"},
        {"job_id": "../escape"},
        {"context_version_sha256": "main"},
        {"repeat": True},
        {"repeat": 10},
    ],
)
def test_host_contract_rejects_unregistered_or_ambiguous_input(changes) -> None:
    raw = request("a" * 64, "b" * 40) | changes
    with pytest.raises(host.OCCNativeHostError):
        host.validate_request(raw)


def test_host_pins_context_and_replays_without_second_dispatch(
    checkout: Path, tmp_path: Path
) -> None:
    library_path = tmp_path / "content.sqlite3"
    library = OCCDurableLibrary(library_path)
    synced = library.sync(
        namespace="local",
        source_id="chat-export",
        content="bounded context",
        allowed_namespaces={"local"},
    )
    source_commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    raw = request(synced["version_sha256"], source_commit)
    calls: list[object] = []
    kwargs = {
        "root": checkout,
        "output_root": tmp_path / "out",
        "context_db": library_path,
        "allowed_namespaces": {"local"},
        "delegate": fake_delegate(calls),
    }
    first = host.execute_host_request(raw, **kwargs)
    second = host.execute_host_request(raw, **kwargs)
    assert len(calls) == 1
    assert first["receipt"] == second["receipt"]
    assert second["replayed"] is True
    assert first["receipt"]["context"]["version_sha256"] == synced["version_sha256"]
    assert first["receipt"]["live_authorized"] is False
    assert first["receipt"]["next_action"] == "RESOLVE_BLOCKERS_AND_USE_NEW_JOB_ID"


def test_new_dispatch_rejects_stale_context_but_historical_receipt_replays(
    checkout: Path, tmp_path: Path
) -> None:
    library_path = tmp_path / "content.sqlite3"
    library = OCCDurableLibrary(library_path)
    first = library.sync(
        namespace="local",
        source_id="chat-export",
        content="v1",
        allowed_namespaces={"local"},
    )
    commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    raw = request(first["version_sha256"], commit)
    calls: list[object] = []
    kwargs = {
        "root": checkout,
        "output_root": tmp_path / "out",
        "context_db": library_path,
        "allowed_namespaces": {"local"},
        "delegate": fake_delegate(calls),
    }
    host.execute_host_request(raw, **kwargs)
    library.sync(
        namespace="local",
        source_id="chat-export",
        content="v2",
        allowed_namespaces={"local"},
    )
    assert host.execute_host_request(raw, **kwargs)["replayed"] is True
    fresh = raw | {"job_id": "occ-audit-2"}
    with pytest.raises(OCCDurableError, match="STALE_CONTEXT_VERSION"):
        host.execute_host_request(fresh, **kwargs)


def test_stop_cancels_before_delegate(checkout: Path, tmp_path: Path) -> None:
    library_path = tmp_path / "content.sqlite3"
    synced = OCCDurableLibrary(library_path).sync(
        namespace="local",
        source_id="chat-export",
        content="context",
        allowed_namespaces={"local"},
    )
    commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = tmp_path / "out"
    stop = output / "occ-audit-1" / "STOP"
    stop.parent.mkdir(parents=True)
    stop.write_text("stop")
    calls: list[object] = []
    result = host.execute_host_request(
        request(synced["version_sha256"], commit),
        root=checkout,
        output_root=output,
        context_db=library_path,
        allowed_namespaces={"local"},
        delegate=fake_delegate(calls),
    )
    assert calls == []
    assert result["receipt"]["job_state"] == "CANCELLED_BEFORE_DISPATCH"


def test_unknown_incomplete_job_requires_reconciliation(
    checkout: Path, tmp_path: Path
) -> None:
    library_path = tmp_path / "content.sqlite3"
    synced = OCCDurableLibrary(library_path).sync(
        namespace="local",
        source_id="chat-export",
        content="context",
        allowed_namespaces={"local"},
    )
    commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = tmp_path / "out"
    (output / "occ-audit-1").mkdir(parents=True)
    with pytest.raises(host.OCCNativeHostError, match="NEEDS_RECONCILIATION"):
        host.execute_host_request(
            request(synced["version_sha256"], commit),
            root=checkout,
            output_root=output,
            context_db=library_path,
            allowed_namespaces={"local"},
            delegate=fake_delegate([]),
        )


def test_tampered_host_receipt_is_rejected(checkout: Path, tmp_path: Path) -> None:
    library_path = tmp_path / "content.sqlite3"
    synced = OCCDurableLibrary(library_path).sync(
        namespace="local",
        source_id="chat-export",
        content="context",
        allowed_namespaces={"local"},
    )
    commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    raw = request(synced["version_sha256"], commit)
    out = tmp_path / "out"
    kwargs = {
        "root": checkout,
        "output_root": out,
        "context_db": library_path,
        "allowed_namespaces": {"local"},
        "delegate": fake_delegate([]),
    }
    host.execute_host_request(raw, **kwargs)
    path = out / "occ-audit-1" / "occ_host_receipt.json"
    receipt = json.loads(path.read_text())
    receipt["live_authorized"] = True
    path.write_text(json.dumps(receipt))
    with pytest.raises(host.OCCNativeHostError, match="RECEIPT_DIGEST_MISMATCH"):
        host.execute_host_request(raw, **kwargs)


def test_native_frame_roundtrip_and_truncation() -> None:
    payload = request("a" * 64, "b" * 40)
    buffer = io.BytesIO()
    host.write_native_message(buffer, payload)
    buffer.seek(0)
    assert host.read_native_message(buffer) == payload
    with pytest.raises(host.OCCNativeHostError, match="TRUNCATED"):
        host.read_native_message(io.BytesIO(b"\x05\x00\x00\x00{}"))
    assert digest(payload)
