"""Pre-extraction archive validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import stat
import tarfile
import zipfile


class ArchiveSecurityError(ValueError):
    """An archive member or expansion budget is unsafe."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_members: int = 10_000
    max_member_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_expansion_ratio: int = 100


def _validate_name(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArchiveSecurityError("archive member path is unsafe")
    if ":" in path.parts[0]:
        raise ArchiveSecurityError("archive drive paths are forbidden")
    if any(ord(char) < 32 for char in normalized):
        raise ArchiveSecurityError("archive member contains control characters")
    return path


def validate_zip(path: str, *, limits: ArchiveLimits) -> tuple[str, ...]:
    names: set[str] = set()
    total = 0
    compressed = 0
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > limits.max_members:
            raise ArchiveSecurityError("archive member count exceeds limit")
        for entry in entries:
            normalized = _validate_name(entry.filename).as_posix()
            if normalized in names:
                raise ArchiveSecurityError("duplicate archive member name")
            names.add(normalized)
            mode = entry.external_attr >> 16
            if (
                stat.S_ISLNK(mode)
                or stat.S_ISCHR(mode)
                or stat.S_ISBLK(mode)
                or stat.S_ISFIFO(mode)
            ):
                raise ArchiveSecurityError(
                    "archive links and special files are forbidden"
                )
            if entry.file_size > limits.max_member_bytes:
                raise ArchiveSecurityError("archive member exceeds size limit")
            total += entry.file_size
            compressed += max(1, entry.compress_size)
            if total > limits.max_total_bytes:
                raise ArchiveSecurityError("archive expansion exceeds total limit")
        if total > compressed * limits.max_expansion_ratio:
            raise ArchiveSecurityError("archive expansion ratio exceeds limit")
    return tuple(sorted(names))


def validate_tar(path: str, *, limits: ArchiveLimits) -> tuple[str, ...]:
    names: set[str] = set()
    total = 0
    with tarfile.open(path, mode="r:*") as archive:
        entries = archive.getmembers()
        if len(entries) > limits.max_members:
            raise ArchiveSecurityError("archive member count exceeds limit")
        for entry in entries:
            normalized = _validate_name(entry.name).as_posix()
            if normalized in names:
                raise ArchiveSecurityError("duplicate archive member name")
            names.add(normalized)
            if (
                entry.issym()
                or entry.islnk()
                or entry.ischr()
                or entry.isblk()
                or entry.isfifo()
            ):
                raise ArchiveSecurityError(
                    "archive links and special files are forbidden"
                )
            if entry.size > limits.max_member_bytes:
                raise ArchiveSecurityError("archive member exceeds size limit")
            total += entry.size
            if total > limits.max_total_bytes:
                raise ArchiveSecurityError("archive expansion exceeds total limit")
    return tuple(sorted(names))
