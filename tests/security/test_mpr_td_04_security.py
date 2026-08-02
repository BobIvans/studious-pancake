from __future__ import annotations

from pathlib import Path
import sys
import zipfile

import pytest

from src.security import (
    ArchiveLimits,
    ArchiveSecurityError,
    FilesystemSecurityError,
    InputLimits,
    InputSecurityError,
    NetworkSecurityError,
    SubprocessPolicy,
    UrlPolicy,
    atomic_write_bytes,
    decode_bounded_json_object,
    resolve_owned_path,
    run_allowlisted,
    validate_url,
    validate_zip,
)


def test_bounded_json_rejects_duplicates_non_finite_and_large_integer() -> None:
    limits = InputLimits(max_bytes=256, max_integer_digits=4)
    assert decode_bounded_json_object(b'{"ok":1}', limits=limits) == {"ok": 1}
    with pytest.raises(InputSecurityError):
        decode_bounded_json_object(b'{"x":1,"x":2}', limits=limits)
    with pytest.raises(InputSecurityError):
        decode_bounded_json_object(b'{"x":NaN}', limits=limits)
    with pytest.raises(InputSecurityError):
        decode_bounded_json_object(b'{"x":12345}', limits=limits)


def test_owned_path_and_atomic_write_reject_traversal_and_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(FilesystemSecurityError):
        resolve_owned_path(root, "../escape")

    target = atomic_write_bytes(root, "safe/state.json", b"{}", max_bytes=8)
    assert target.read_bytes() == b"{}"

    symlink = root / "link"
    symlink.symlink_to(tmp_path)
    with pytest.raises(FilesystemSecurityError):
        resolve_owned_path(root, "link/file")


def test_zip_validation_rejects_traversal(tmp_path: Path) -> None:
    safe = tmp_path / "safe.zip"
    with zipfile.ZipFile(safe, "w") as archive:
        archive.writestr("safe/data.txt", "ok")
    assert validate_zip(str(safe), limits=ArchiveLimits()) == ("safe/data.txt",)

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(ArchiveSecurityError):
        validate_zip(str(unsafe), limits=ArchiveLimits())


def test_url_policy_rejects_credentials_local_and_private_destinations() -> None:
    policy = UrlPolicy(frozenset({"api.example.com"}))
    assert validate_url(
        "https://api.example.com/v1", policy=policy
    ).startswith("https://")
    with pytest.raises(NetworkSecurityError):
        validate_url("https://user:pass@api.example.com/v1", policy=policy)
    with pytest.raises(NetworkSecurityError):
        validate_url("https://localhost/v1", policy=UrlPolicy(frozenset({"localhost"})))
    with pytest.raises(NetworkSecurityError):
        validate_url("https://127.0.0.1/v1", policy=UrlPolicy(frozenset({"127.0.0.1"})))


def test_subprocess_uses_argument_vector_and_sanitized_environment(
    tmp_path: Path,
) -> None:
    executable = Path(sys.executable).resolve()
    policy = SubprocessPolicy(
        executable=executable,
        allowed_argument_prefixes=("-c", "print"),
        working_directory=tmp_path,
        environment_allowlist=frozenset(),
        timeout_seconds=5,
        max_output_bytes=1024,
    )
    result = run_allowlisted(policy, ("-c", "print('ok')"), environment={"SECRET": "x"})
    assert result.returncode == 0
    assert result.stdout.strip() == b"ok"
