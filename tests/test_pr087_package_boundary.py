from __future__ import annotations

from scripts.package_smoke import _forbidden_wheel_members


def test_pr087_detects_quarantined_runtime_wheel_members() -> None:
    names = {
        "src/legacy_arb_bot.py",
        "src/ingest/helius_webhook_handler.py",
        "src/execution/senders/rpc_sender.py",
        "src/execution/live_control.py",
        "src/execution/shadow.py",
        "src/cli.py",
    }

    assert _forbidden_wheel_members(names) == [
        "src/execution/live_control.py",
        "src/execution/senders/rpc_sender.py",
        "src/execution/shadow.py",
        "src/ingest/helius_webhook_handler.py",
        "src/legacy_arb_bot.py",
    ]


def test_pr087_keeps_supported_runtime_members_installable() -> None:
    names = {
        "arb_bot.py",
        "src/cli.py",
        "src/container_runtime.py",
        "src/resources/capabilities.json",
    }

    assert _forbidden_wheel_members(names) == []
