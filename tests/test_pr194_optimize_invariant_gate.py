from __future__ import annotations

from pathlib import Path

from scripts.pr194_optimize_invariant_gate_lib import (
    EVIDENCE_SCHEMA,
    build_evidence,
    scan_source_text,
)


def test_pr194_optimize_gate_detects_assert_runtime_invariant() -> None:
    violations = scan_source_text(
        "src/security_control.py",
        (
            "def validate(value):\n"
            "    assert value > 0, 'must be positive'\n"
            "    return value\n"
        ),
    )

    assert len(violations) == 1
    assert violations[0].path == "src/security_control.py"
    assert violations[0].line == 2
    assert violations[0].reason == "assert_removed_by_python_optimize_mode"


def test_pr194_optimize_gate_ignores_test_asserts() -> None:
    violations = scan_source_text(
        "tests/test_security_control.py",
        "def test_value():\n    assert 1 == 1\n",
    )

    assert violations == ()


def test_pr194_optimize_gate_emits_deterministic_evidence(tmp_path: Path) -> None:
    source = tmp_path / "src"
    scripts = tmp_path / "scripts"
    source.mkdir()
    scripts.mkdir()
    (tmp_path / "arb_bot.py").write_text(
        "def main():\n    return 0\n",
        encoding="utf-8",
    )
    (source / "production_surface.py").write_text(
        "def validate():\n    if False:\n        raise RuntimeError('blocked')\n",
        encoding="utf-8",
    )
    (scripts / "package_smoke.py").write_text(
        "def main():\n    return 0\n",
        encoding="utf-8",
    )
    (scripts / "verify_repo.py").write_text(
        "def main():\n    return 0\n",
        encoding="utf-8",
    )

    evidence = build_evidence(tmp_path)

    assert evidence["schema_version"] == EVIDENCE_SCHEMA
    assert evidence["ready"] is True
    assert evidence["violation_count"] == 0
    assert evidence["safety_boundary"] == {
        "live_trading_enabled": False,
        "sender_free": True,
        "network_calls": False,
        "signer_or_private_key_access": False,
    }


def test_pr194_optimize_gate_fails_closed_on_missing_path(tmp_path: Path) -> None:
    evidence = build_evidence(tmp_path, paths=("src/missing_control.py",))

    assert evidence["ready"] is False
    assert evidence["violations"] == [
        {
            "path": "src/missing_control.py",
            "line": 0,
            "column": 0,
            "reason": "production_critical_path_missing",
        }
    ]
