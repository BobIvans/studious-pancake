from pathlib import Path

from src.qualification_pr176 import DependencyClosure
from src.qualification_pr186 import (
    ArtifactIdentity,
    InterpreterIdentity,
    ProfileExecutionResult,
    QualificationRun,
    create_signed_verdict,
    source_tree_identity,
    verify_signed_verdict,
)


def _closure() -> DependencyClosure:
    return DependencyClosure(
        lock_hashes={"requirements.txt": "a" * 64},
        required_packages=("pytest",),
        declared_packages=("pytest",),
        undeclared_packages=(),
        present_packages=("pytest",),
        missing_packages=(),
        installed_versions={"pytest": "9.0.2"},
        importable_packages=("pytest",),
        non_importable_packages=(),
        global_site_packages=False,
        interpreter_executable="/venv/bin/python",
    )


def _interpreter() -> InterpreterIdentity:
    return InterpreterIdentity(
        executable="/venv/bin/python",
        version="3.13.5",
        implementation="cpython",
        prefix="/venv",
        base_prefix="/usr",
        isolated_environment=True,
        global_site_packages_enabled=False,
        sys_path=("/venv/site-packages",),
        site_packages=("/venv/site-packages",),
        identity_hash="b" * 64,
    )


def _run(tmp_path: Path) -> QualificationRun:
    source_file = tmp_path / "src" / "example.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    wheel = tmp_path / "flashloan_bot.whl"
    wheel.write_bytes(b"wheel")
    profile = ProfileExecutionResult(
        name="core",
        command=("/venv/bin/python", "-m", "pytest"),
        started_at="2026-07-22T00:00:00Z",
        finished_at="2026-07-22T00:00:01Z",
        duration_ns=1_000_000_000,
        exit_code=0,
        stdout_sha256="c" * 64,
        stderr_sha256="d" * 64,
        stdout_bytes=10,
        stderr_bytes=0,
    )
    return QualificationRun(
        run_id="run-1",
        plan_hash="e" * 64,
        source=source_tree_identity(tmp_path),
        interpreter=_interpreter(),
        dependency_closure=_closure(),
        wheel=ArtifactIdentity.from_path(wheel),
        wheelhouse_manifest_hash="f" * 64,
        profiles=(profile,),
        selected_profiles=("core",),
        started_at="2026-07-22T00:00:00Z",
        finished_at="2026-07-22T00:00:01Z",
        environment_id="b" * 64,
        network_disabled_after_bootstrap=True,
        source_import_leakage_detected=False,
    )


def test_source_tree_digest_changes_when_production_source_changes(tmp_path: Path):
    source = tmp_path / "src" / "cli.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    first = source_tree_identity(tmp_path)

    source.write_text("VALUE = 2\n", encoding="utf-8")
    second = source_tree_identity(tmp_path)

    assert first.digest != second.digest


def test_only_signed_executed_verdict_can_allow_release(tmp_path: Path):
    run = _run(tmp_path)
    key = b"qualification-key-material-32-bytes-minimum"
    verdict = create_signed_verdict(
        run,
        repeated_clean_run_match=True,
        signer_key_id="ci-release-key-1",
        signing_key=key,
        issued_at="2026-07-22T00:00:02Z",
    )

    assert verdict.qualified is True
    assert verdict.release_claim_allowed is False
    assert verify_signed_verdict(verdict, key) is True
    assert (
        verify_signed_verdict(verdict, b"different-key-material-32-bytes-long") is False
    )


def test_missing_repeated_clean_run_blocks_release_claim(tmp_path: Path):
    run = _run(tmp_path)
    verdict = create_signed_verdict(
        run,
        repeated_clean_run_match=False,
        signer_key_id="ci-release-key-1",
        signing_key=b"qualification-key-material-32-bytes-minimum",
    )

    assert verdict.qualified is False
    assert verdict.release_claim_allowed is False
    assert "repeated_clean_run_mismatch" in verdict.reason_codes


def test_missing_installed_dependency_blocks_verdict(tmp_path: Path):
    run = _run(tmp_path)
    incomplete = DependencyClosure(
        lock_hashes=run.dependency_closure.lock_hashes,
        required_packages=("pytest", "solders"),
        declared_packages=("pytest", "solders"),
        undeclared_packages=(),
        present_packages=("pytest",),
        missing_packages=("solders",),
        installed_versions={"pytest": "9.0.2"},
        importable_packages=("pytest",),
        non_importable_packages=("solders",),
        global_site_packages=False,
        interpreter_executable="/venv/bin/python",
    )
    blocked = QualificationRun(
        run_id=run.run_id,
        plan_hash=run.plan_hash,
        source=run.source,
        interpreter=run.interpreter,
        dependency_closure=incomplete,
        wheel=run.wheel,
        wheelhouse_manifest_hash=run.wheelhouse_manifest_hash,
        profiles=run.profiles,
        selected_profiles=run.selected_profiles,
        started_at=run.started_at,
        finished_at=run.finished_at,
        environment_id=run.environment_id,
        network_disabled_after_bootstrap=True,
        source_import_leakage_detected=False,
    )
    verdict = create_signed_verdict(
        blocked,
        repeated_clean_run_match=True,
        signer_key_id="ci-release-key-1",
        signing_key=b"qualification-key-material-32-bytes-minimum",
    )

    assert verdict.qualified is False
    assert "installed_dependency_closure_incomplete" in verdict.reason_codes
