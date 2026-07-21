from __future__ import annotations

from pathlib import Path

from scripts.package_boundary import (
    FORBIDDEN_PRODUCTION_WHEEL_PATHS,
    FORBIDDEN_PRODUCTION_WHEEL_PREFIXES,
    forbidden_wheel_members,
    prune_quarantined_runtime_members,
)


def _touch(root: Path, member: str) -> Path:
    path = root.joinpath(*member.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# generated test member\n", encoding="utf-8")
    return path


def test_pr100_forbidden_wheel_manifest_covers_known_quarantine_members() -> None:
    names = {
        *FORBIDDEN_PRODUCTION_WHEEL_PATHS,
        "src/ingest/helius_webhook_handler.py",
        "src/execution/senders/rpc_sender.py",
        "src/cli.py",
    }

    assert forbidden_wheel_members(names) == [
        "src/execution/live_control.py",
        "src/execution/senders/rpc_sender.py",
        "src/execution/shadow.py",
        "src/ingest/helius_webhook_handler.py",
        "src/legacy_arb_bot.py",
    ]


def test_pr100_build_hook_prunes_quarantined_members_only(tmp_path: Path) -> None:
    supported = _touch(tmp_path, "src/cli.py")
    for member in FORBIDDEN_PRODUCTION_WHEEL_PATHS:
        _touch(tmp_path, member)
    for prefix in FORBIDDEN_PRODUCTION_WHEEL_PREFIXES:
        _touch(tmp_path, f"{prefix}legacy_member.py")

    removed = prune_quarantined_runtime_members(tmp_path)

    assert supported.is_file()
    assert "src/ingest/" in removed
    assert "src/execution/senders/" in removed
    for member in FORBIDDEN_PRODUCTION_WHEEL_PATHS:
        assert member in removed
        assert not tmp_path.joinpath(*member.split("/")).exists()
    for prefix in FORBIDDEN_PRODUCTION_WHEEL_PREFIXES:
        assert not tmp_path.joinpath(*prefix.rstrip("/").split("/")).exists()
