from __future__ import annotations

from pathlib import Path

from scripts.verify_source_hygiene import evaluate_source_hygiene
from scripts.verify_workflow_authority import evaluate_workflow_authority
from src.config.product_contract_pr195 import ProductContract


def test_source_hygiene_blocks_generated_artifacts(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "pkg" / "__pycache__" / "mod.cpython-313.pyc").write_bytes(b"x")
    report = evaluate_source_hygiene(tmp_path, strict=True)

    assert report.ok is False
    assert any(item.path.endswith("__pycache__") for item in report.violations)
    assert any(item.path.endswith(".pyc") for item in report.violations)


def test_workflow_authority_accepts_single_waived_release_gate(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "release-authority.yml").write_text(
        "name: Release authority\n"
        "jobs:\n"
        "  gate:\n"
        "    steps:\n"
        "      # mpr-close-01-waive-moving-action\n"
        "      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    (workflows / "legacy-pr-gate.yml").write_text(
        "name: Legacy PR gate\n"
        "jobs:\n"
        "  check:\n"
        "    steps:\n"
        "      - uses: actions/setup-python@v5\n",
        encoding="utf-8",
    )

    report = evaluate_workflow_authority(tmp_path, strict=True)

    assert report.ok is True
    assert report.authority_workflows == (".github/workflows/release-authority.yml",)
    assert report.legacy_workflows == (".github/workflows/legacy-pr-gate.yml",)


def test_active_jupiter_product_contract_uses_swap_v2_build() -> None:
    contract = ProductContract.load_default()
    jupiter = next(item for item in contract.endpoint_contracts if item.provider == "jupiter")

    assert "/swap/v2/build" in jupiter.paths
    assert "/price/v3" in jupiter.paths
    assert not any(path.startswith("/swap/v1") for path in jupiter.paths)
    assert "/price/v2" not in jupiter.paths
    assert contract.live_available is False
    assert contract.product_state == "not-production-ready"
