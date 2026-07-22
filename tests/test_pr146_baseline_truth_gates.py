from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_shadow_soak_evidence_import_is_collection_safe() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import src.shadow_soak.evidence"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_release_gate_package_reexports_remain_lazy() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.release_gate import ReleaseGate, EvidenceKind; "
            "print(ReleaseGate.__name__); print(EvidenceKind.__name__)",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ReleaseGate" in completed.stdout
    assert "EvidenceKind" in completed.stdout


def test_security_gate_script_self_bootstraps_source_checkout_imports(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "security_supply_chain_policy.json").write_text(
        json.dumps({"schema_version": "pr043.security-supply-chain-policy.v1"}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/security_gate.py"),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "security gate passed" in completed.stdout
