"""Owned-root path validation and atomic writes."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile


class FilesystemSecurityError(ValueError):
    """A path escapes or violates an owned filesystem root policy."""


def _reject_component(component: str) -> None:
    if component in {"", ".", ".."}:
        raise FilesystemSecurityError(
            "empty, current, and parent path components are forbidden"
        )
    if any(ord(char) < 32 for char in component):
        raise FilesystemSecurityError("control characters are forbidden in paths")


def resolve_owned_path(
    root: str | os.PathLike[str], relative: str | os.PathLike[str]
) -> Path:
    """Resolve a relative path beneath an owned root without symlink traversal."""

    root_path = Path(root)
    if not root_path.is_absolute():
        raise FilesystemSecurityError("owned root must be absolute")
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise FilesystemSecurityError("untrusted path must be relative")
    for part in relative_path.parts:
        _reject_component(part)

    current = root_path
    root_stat = os.lstat(current)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise FilesystemSecurityError("owned root must be a real directory")
    for part in relative_path.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode):
                raise FilesystemSecurityError("symlink traversal is forbidden")
            if not stat.S_ISREG(metadata.st_mode) and not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise FilesystemSecurityError(
                    "special filesystem objects are forbidden"
                )
    resolved_root = root_path.resolve(strict=True)
    candidate = resolved_root.joinpath(*relative_path.parts)
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise FilesystemSecurityError("path escapes owned root")
    return candidate


def atomic_write_bytes(
    root: str | os.PathLike[str],
    relative: str | os.PathLike[str],
    data: bytes,
    *,
    max_bytes: int,
    mode: int = 0o600,
) -> Path:
    """Write bounded bytes atomically beneath an owned root."""

    if len(data) > max_bytes:
        raise FilesystemSecurityError("write exceeds byte limit")
    target = resolve_owned_path(root, relative)
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        os.chmod(target, mode)
        directory_fd = os.open(
            target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return target
    except (OSError, FilesystemSecurityError):
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
