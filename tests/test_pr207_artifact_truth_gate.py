from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from src.pr207_artifact_truth_gate import (
    PR207ArtifactTruthError,
    SCHEMA_VERSION,
    inspect_sender_free_wheel_artifact,
    validate_release_set_digests,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def build_wheel(
    tmp_path: Path,
    *,
    files: dict[str, str] | None = None,
    entrypoint_target: str = "src.cli_pr189:main",
    include_record: bool = True,
    include_entrypoints: bool = True,
    incomplete_record: bool = False,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    wheel_path = tmp_path / "flashloan_bot-0.0.0-py3-none-any.whl"
    package_files = {
        "src/cli_pr189.py": "def main():\n    return 0\n",
        "src/production_surface.py": "SCHEMA = 'test'\n",
        "flashloan_bot-0.0.0.dist-info/WHEEL": "Wheel-Version: 1.0\n",
    }
    if include_entrypoints:
        package_files[
            "flashloan_bot-0.0.0.dist-info/entry_points.txt"
        ] = f"[console_scripts]\nflashloan-bot = {entrypoint_target}\n"
    if files:
        package_files.update(files)

    names = sorted(package_files)
    record_names = list(names)
    record_names.append("flashloan_bot-0.0.0.dist-info/RECORD")
    if incomplete_record:
        record_names = record_names[:-2] + record_names[-1:]
    record_text = "".join(f"{name},,\n" for name in record_names)

    with zipfile.ZipFile(wheel_path, "w") as archive:
        for name in names:
            archive.writestr(name, package_files[name])
        if include_record:
            archive.writestr("flashloan_bot-0.0.0.dist-info/RECORD", record_text)
    return wheel_path


def test_pr207_inspects_real_wheel_bytes_and_entrypoint(tmp_path: Path) -> None:
    wheel = build_wheel(tmp_path)

    report = inspect_sender_free_wheel_artifact(
        wheel,
        expected_entrypoints={"flashloan-bot": "src.cli_pr189:main"},
    )

    assert report.schema_version == SCHEMA_VERSION
    assert report.ready_sender_free is True
    assert report.python_module_count == 2
    assert report.blocked_members == ()
    assert report.reason_codes == ()
    assert ("flashloan-bot", "src.cli_pr189:main") in report.entrypoints
    assert len(report.wheel_sha256) == 64
    assert report.to_dict()["ready_sender_free"] is True


def test_pr207_rejects_sender_live_or_signer_namespaces_in_sender_free_wheel(
    tmp_path: Path,
) -> None:
    wheel = build_wheel(
        tmp_path,
        files={
            "src/submission/pr202_isolated_signer_settlement.py": "VALUE = 1\n",
            "src/live_boundary/permit.py": "VALUE = 1\n",
            "src/jito_status.py": "VALUE = 1\n",
        },
    )

    report = inspect_sender_free_wheel_artifact(wheel)

    assert report.ready_sender_free is False
    assert "PR207_SENDER_FREE_WHEEL_CONTAINS_FORBIDDEN_SURFACE" in report.reason_codes
    assert "src/submission/pr202_isolated_signer_settlement.py" in report.blocked_members
    assert "src/live_boundary/permit.py" in report.blocked_members
    assert "src/jito_status.py" in report.blocked_members


def test_pr207_does_not_trust_fake_entrypoint_claims(tmp_path: Path) -> None:
    wheel = build_wheel(tmp_path, entrypoint_target="src.other:main")

    report = inspect_sender_free_wheel_artifact(
        wheel,
        expected_entrypoints={"flashloan-bot": "src.cli_pr189:main"},
    )

    assert report.ready_sender_free is False
    assert "PR207_ENTRYPOINT_TARGET_MISMATCH" in report.reason_codes


def test_pr207_recomputes_wheel_digest_and_rejects_expected_placeholder(
    tmp_path: Path,
) -> None:
    wheel = build_wheel(tmp_path)

    with pytest.raises(PR207ArtifactTruthError, match="PR207_PLACEHOLDER"):
        inspect_sender_free_wheel_artifact(wheel, expected_wheel_sha256="0" * 64)

    with pytest.raises(PR207ArtifactTruthError, match="PR207_WHEEL_DIGEST_MISMATCH"):
        inspect_sender_free_wheel_artifact(wheel, expected_wheel_sha256=HASH_A)


def test_pr207_rejects_missing_or_incomplete_wheel_metadata(tmp_path: Path) -> None:
    missing_record = build_wheel(tmp_path / "a", include_record=False)
    incomplete_record = build_wheel(tmp_path / "b", incomplete_record=True)
    missing_entrypoints = build_wheel(tmp_path / "c", include_entrypoints=False)

    assert "PR207_WHEEL_RECORD_NOT_UNIQUE" in inspect_sender_free_wheel_artifact(
        missing_record
    ).reason_codes
    assert "PR207_WHEEL_RECORD_INCOMPLETE" in inspect_sender_free_wheel_artifact(
        incomplete_record
    ).reason_codes
    assert "PR207_WHEEL_REQUIRED_METADATA_MISSING" in inspect_sender_free_wheel_artifact(
        missing_entrypoints
    ).reason_codes


def test_pr207_artifact_path_must_be_a_real_wheel(tmp_path: Path) -> None:
    text_file = tmp_path / "artifact.txt"
    text_file.write_text("not a wheel", encoding="utf-8")

    with pytest.raises(PR207ArtifactTruthError, match="PR207_ARTIFACT_MUST_BE_WHEEL"):
        inspect_sender_free_wheel_artifact(text_file)
    with pytest.raises(PR207ArtifactTruthError, match="PR207_WHEEL_ARTIFACT_NOT_FOUND"):
        inspect_sender_free_wheel_artifact(tmp_path / "missing.whl")


def test_pr207_release_set_requires_real_distinct_digests() -> None:
    report = validate_release_set_digests(
        main_wheel_sha256=HASH_A,
        signer_wheel_sha256=HASH_B,
        ipc_schema_sha256=HASH_C,
        policy_bundle_sha256=HASH_D,
    )

    assert report.ready is True
    assert report.reason_codes == ()

    bad = validate_release_set_digests(
        main_wheel_sha256=HASH_A,
        signer_wheel_sha256=HASH_A,
        ipc_schema_sha256="0" * 64,
        policy_bundle_sha256=HASH_D,
    )

    assert bad.ready is False
    assert "PR207_MAIN_AND_SIGNER_WHEELS_MUST_BE_DISTINCT" in bad.reason_codes
    assert "PR207_PLACEHOLDER_IPC_SCHEMA_SHA256" in bad.reason_codes
