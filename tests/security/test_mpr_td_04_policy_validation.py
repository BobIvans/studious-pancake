from __future__ import annotations

import json
from pathlib import Path

import scripts.verify_mpr_td_04_upgrade_security as verifier


def _write(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_policy_tree(root: Path) -> None:
    _write(
        root,
        "src/resources/release_upgrade_policy.json",
        {
            "schema_id": "release-upgrade-policy.v1",
            "sender_free": True,
            "live_enabled": False,
            "required_identity_fields": ["source_sha"],
            "handoff_phases": [
                "preflight",
                "admission_stopped",
                "drained",
                "backed_up",
                "migrated",
                "activated",
                "verified",
                "resumed",
            ],
            "requirements": {
                "immutable_previous_artifact": True,
                "verified_backup": True,
                "generation_fencing": True,
                "expand_contract_migrations": True,
                "stale_worker_denial": True,
                "sender_free": True,
            },
        },
    )
    _write(
        root,
        "src/resources/filesystem_root_registry.json",
        {
            "schema_id": "filesystem-root-registry.v1",
            "roots": [
                {
                    "root_id": "state",
                    "owner": "persistence",
                    "path_source": "env:STATE",
                    "default_path": "/state",
                    "read": True,
                    "write": True,
                    "symlinks": "deny",
                    "special_files": "deny",
                    "maximum_file_bytes": 1,
                    "security_classification": "durable-state",
                }
            ],
        },
    )
    test_path = root / "tests/security/test_fixture.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_fixture(): pass\n", encoding="utf-8")
    _write(
        root,
        "config/mpr_td_04_attack_surface_manifest.json",
        {
            "schema_id": "attack-surface-manifest.v1",
            "sender_free": True,
            "surfaces": [
                {
                    "surface_id": "fixture",
                    "owner": "security",
                    "module": "src.security",
                    "callable": "fixture",
                    "input_origin": "fixture",
                    "trust_level": "untrusted",
                    "max_bytes": 1,
                    "max_depth": 1,
                    "max_nodes": 1,
                    "failure_reason_code": "SECURITY_FAILURE",
                    "tests": ["tests/security/test_fixture.py"],
                }
            ],
        },
    )
    _write(
        root,
        "config/subprocess_allowlist.json",
        {
            "schema_id": "mpr-td-04.subprocess-allowlist.v1",
            "production_entries": [],
            "policy": {
                "shell": False,
                "inherit_environment": False,
                "untrusted_executable": False,
                "unbounded_output": False,
                "secret_arguments": False,
            },
        },
    )


def test_security_policy_validation_rejects_malformed_json(
    monkeypatch, tmp_path: Path
) -> None:
    _valid_policy_tree(tmp_path)
    (tmp_path / "config/mpr_td_04_attack_surface_manifest.json").write_text(
        "{not-json", encoding="utf-8"
    )
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    errors: list[str] = []
    verifier._validate_policy_artifacts(errors)
    assert any("invalid JSON policy" in error for error in errors)


def test_security_policy_validation_rejects_fail_open_subprocess_policy(
    monkeypatch, tmp_path: Path
) -> None:
    _valid_policy_tree(tmp_path)
    path = tmp_path / "config/subprocess_allowlist.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["policy"]["shell"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    errors: list[str] = []
    verifier._validate_policy_artifacts(errors)
    assert "subprocess policy is incomplete or fail-open" in errors
