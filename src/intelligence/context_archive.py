"""Portable ZIP64 snapshots; verify without unsafe extraction."""

from pathlib import Path, PurePosixPath
import os
import tempfile
import zipfile
from .common import digest, load_json, save_json
from .repo_snapshot import verify_snapshot_roundtrip


def build_portable_archive(
    snapshot: str | Path, destination: str | Path, *, max_bytes: int = 512 * 1024 * 1024
) -> dict:
    root, out = Path(snapshot), Path(destination)
    proof = verify_snapshot_roundtrip(root)
    files = [root / "manifest.json"] + sorted((root / "blobs").glob("*"))
    if sum(p.stat().st_size for p in files) > max_bytes:
        raise ValueError("archive resource budget exceeded")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=out.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(
            temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for path in files:
                info = zipfile.ZipInfo(
                    path.relative_to(root).as_posix(), (1980, 1, 1, 0, 0, 0)
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        verify_portable_archive(temporary, max_bytes=max_bytes)
        os.replace(temporary, out)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {**proof, "archive_bytes": out.stat().st_size}


def verify_portable_archive(path: str | Path, *, max_bytes=512 * 1024 * 1024) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or sum(i.file_size for i in archive.infolist()) > max_bytes
        ):
            raise ValueError("invalid archive accounting")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError("unsafe archive member")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                if name != "manifest.json" and not (
                    name.startswith("blobs/") and len(PurePosixPath(name).parts) == 2
                ):
                    raise ValueError("unexpected archive member")
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
            return verify_snapshot_roundtrip(root)
