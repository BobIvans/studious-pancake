from __future__ import annotations

import pytest

from src.baseline.security_truth import (
    BaselineManifest,
    BaselineTruthError,
    BaselineTruthReport,
    FindingSeverity,
    GateCommand,
    GateKind,
    ImportEdge,
    assert_baseline_green,
    default_pr152_manifest,
    detect_import_cycles,
    domain_hash,
    extract_import_edges,
    scan_python_source,
)


def test_pr152_default_manifest_contains_required_aggregate_gates() -> None:
    manifest = default_pr152_manifest()

    assert set(manifest.gates) >= {
        "compileall",
        "quality-gate",
        "security-gate",
        "pytest-offline",
        "package-smoke",
    }
    assert manifest.optimized_mode_required is True
    assert manifest.package_smoke_required is True
    assert len(manifest.manifest_hash) == 64


def test_pr152_manifest_rejects_missing_security_gate() -> None:
    gates = {
        "compileall": GateCommand(
            "compileall",
            GateKind.IMPORT,
            ("python", "-m", "compileall", "src"),
            description="compile",
        ),
        "quality-gate": GateCommand(
            "quality-gate",
            GateKind.FORMAT,
            ("python", "scripts/quality_gate.py"),
            description="quality",
        ),
        "pytest-offline": GateCommand(
            "pytest-offline",
            GateKind.TEST,
            ("python", "-m", "pytest", "-q"),
            description="tests",
        ),
        "package-smoke": GateCommand(
            "package-smoke",
            GateKind.PACKAGE,
            ("python", "scripts/package_smoke.py"),
            description="package",
        ),
    }

    with pytest.raises(BaselineTruthError, match="security-gate"):
        BaselineManifest(gates=gates)


def test_pr152_scanner_finds_active_signing_submission_and_asserts() -> None:
    text = """
from solders.keypair import Keypair
from src.ingest.tx_builder import validate_cb_ordering

def recover(client):
    assert client is not None
    return client.sendTransaction({"skipPreflight": true})
"""

    findings = scan_python_source("scripts/emergency_recover.py", text)
    codes = {finding.code for finding in findings}

    assert "direct-keypair-import" in codes
    assert "quarantined-import" in codes
    assert "assert-validation" in codes
    assert "direct-rpc-submission" in codes
    assert "skip-preflight" in codes


def test_pr152_scanner_marks_broad_except_as_warning() -> None:
    findings = scan_python_source(
        "src/security/parser_invariants.py",
        """
def validate(value):
    try:
        return int(value)
    except Exception:
        return None
""",
    )

    assert findings[0].code == "broad-except"
    assert findings[0].severity is FindingSeverity.WARNING


def test_pr152_inactive_quarantine_source_is_not_scanned() -> None:
    findings = scan_python_source(
        "src/legacy_arb_bot.py",
        "from solders.keypair import Keypair\n",
        active_source=False,
    )

    assert findings == ()


def test_pr152_import_edge_extraction_is_static_and_safe() -> None:
    edges = extract_import_edges(
        "src.shadow_soak.evidence",
        "from src.release_gate import limited_canary\nimport src.security.parser_invariants\n",
    )

    assert edges == (
        ImportEdge("src.shadow_soak.evidence", "src.release_gate"),
        ImportEdge("src.shadow_soak.evidence", "src.security.parser_invariants"),
    )


def test_pr152_detect_import_cycles_is_deterministic() -> None:
    edges = (
        ImportEdge("b", "c"),
        ImportEdge("c", "a"),
        ImportEdge("a", "b"),
    )

    assert detect_import_cycles(edges) == (("a", "b", "c", "a"),)


def test_pr152_report_blocks_until_source_wheel_and_optimized_imports_are_proven() -> None:
    manifest = default_pr152_manifest()
    report = BaselineTruthReport(
        manifest=manifest,
        findings=(),
        import_cycles=(),
        optimized_mode_import_ok=True,
        source_checkout_import_ok=True,
        installed_wheel_import_ok=False,
    )

    assert report.green is False
    assert "installed-wheel-import-not-proven" in report.blocking_reasons
    with pytest.raises(BaselineTruthError, match="installed-wheel-import-not-proven"):
        assert_baseline_green(report)


def test_pr152_green_report_serializes_with_stable_hash() -> None:
    manifest = default_pr152_manifest()
    report = BaselineTruthReport(
        manifest=manifest,
        findings=(),
        import_cycles=(),
        optimized_mode_import_ok=True,
        source_checkout_import_ok=True,
        installed_wheel_import_ok=True,
    )

    payload = report.to_dict()

    assert report.green is True
    assert payload["green"] is True
    assert payload["manifest_hash"] == manifest.manifest_hash
    assert domain_hash("unit-test", {"report": payload}) == domain_hash(
        "unit-test", {"report": payload}
    )
