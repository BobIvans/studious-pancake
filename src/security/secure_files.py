"""Single-open regular-file reads and copies for security-sensitive material."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile


class SecureFileError(ValueError):
    """A file could not be consumed through the reviewed single-open boundary."""


@dataclass(frozen=True, slots=True)
class SecureFileIdentity:
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SecureFileResult:
    data: bytes
    sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SecureCopyResult:
    sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int


def _open_regular(
    path: Path,
    *,
    max_bytes: int,
    owner_only: bool,
) -> tuple[int, os.stat_result]:
    if max_bytes <= 0:
        raise SecureFileError("secure file size limit must be positive")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SecureFileError("secure file is unreadable or unsafe") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecureFileError("secure file must be regular")
        if metadata.st_nlink != 1:
            raise SecureFileError("secure file must have exactly one link")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise SecureFileError("secure file has the wrong owner")
        if owner_only and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SecureFileError("secure file must be owner-only")
        if metadata.st_size < 0 or metadata.st_size > max_bytes:
            raise SecureFileError("secure file exceeds the size limit")
        return descriptor, metadata
    except Exception:
        os.close(descriptor)
        raise


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def inspect_secure_regular_file(
    path: str | os.PathLike[str],
    *,
    max_bytes: int,
    owner_only: bool = False,
) -> SecureFileIdentity:
    descriptor, metadata = _open_regular(
        Path(path), max_bytes=max_bytes, owner_only=owner_only
    )
    try:
        return SecureFileIdentity(
            size_bytes=metadata.st_size,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mtime_ns=metadata.st_mtime_ns,
        )
    finally:
        os.close(descriptor)


def read_secure_regular_file(
    path: str | os.PathLike[str],
    *,
    max_bytes: int,
    owner_only: bool = False,
) -> SecureFileResult:
    descriptor, before = _open_regular(
        Path(path), max_bytes=max_bytes, owner_only=owner_only
    )
    try:
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if _identity(before) != _identity(after) or len(data) != before.st_size:
            raise SecureFileError("secure file changed during read")
        if len(data) > max_bytes:
            raise SecureFileError("secure file exceeds the size limit")
        return SecureFileResult(
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            device=before.st_dev,
            inode=before.st_ino,
            mtime_ns=before.st_mtime_ns,
        )
    finally:
        os.close(descriptor)


def copy_secure_regular_file(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    *,
    max_bytes: int,
    source_owner_only: bool = False,
) -> SecureCopyResult:
    source_path = Path(source)
    target_path = Path(target)
    descriptor, before = _open_regular(
        source_path,
        max_bytes=max_bytes,
        owner_only=source_owner_only,
    )
    target_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    output_fd, temporary = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    digest = hashlib.sha256()
    size = 0
    try:
        os.fchmod(output_fd, 0o600)
        with os.fdopen(output_fd, "wb", closefd=True) as output:
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise SecureFileError("secure file exceeds the size limit")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(descriptor)
        if _identity(before) != _identity(after) or size != before.st_size:
            raise SecureFileError("secure file changed during copy")
        os.replace(temporary, target_path)
        os.chmod(target_path, 0o600)
        _fsync_directory(target_path.parent)
        return SecureCopyResult(
            sha256=digest.hexdigest(),
            size_bytes=size,
            device=before.st_dev,
            inode=before.st_ino,
            mtime_ns=before.st_mtime_ns,
        )
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "SecureCopyResult",
    "SecureFileError",
    "SecureFileIdentity",
    "SecureFileResult",
    "copy_secure_regular_file",
    "inspect_secure_regular_file",
    "read_secure_regular_file",
]
