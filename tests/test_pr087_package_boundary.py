from __future__ import annotations

from pathlib import Path

from scripts.package_smoke import _forbidden_wheel_members
from src.capabilities import CapabilityMatrix


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


def test_pr087_installed_package_allows_quarantined_paths_to_be_absent(
    tmp_path: Path,
) -> None:
    capability_file = Path("config/capabilities.json")
    matrix = CapabilityMatrix.load(capability_file, root=tmp_path)
    installed_matrix = CapabilityMatrix(
        schema_version=matrix.schema_version,
        product_state=matrix.product_state,
        supported_entrypoint=matrix.supported_entrypoint,
        default_command=matrix.default_command,
        runtime_modes=matrix.runtime_modes,
        components=matrix.components,
        source_path=matrix.source_path,
        root_path=tmp_path,
        installed_package=True,
    )

    assert not any(
        error.startswith("missing component path: execution.legacy_")
        for error in installed_matrix.validate_paths()
    )
