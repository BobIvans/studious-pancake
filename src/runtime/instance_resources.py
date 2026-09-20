"""Instance-scoped local resource manifests and transactional ownership.

This is the MPR-RP-03 authority for same-host resources.  It deliberately does
not replace durable database writer fencing or distributed leader election.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile
from typing import Any, Iterable

INSTANCE_SCHEMA = "mpr-rp-03.runtime-instance.v1"
MANIFEST_SCHEMA = "mpr-rp-03.local-resource-manifest.v1"
_LEGAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class LocalResourceCollision(RuntimeError):
    """A local resource is already owned or cannot be acquired transactionally."""


def _validate_part(field: str, value: str) -> str:
    normalized = str(value).strip()
    if not _LEGAL.fullmatch(normalized):
        raise ValueError(f"{field} contains unsupported namespace characters")
    return normalized


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeInstanceIdentity:
    environment: str
    release_id: str
    deployment_id: str
    instance_id: str
    generation: int
    schema_version: str = INSTANCE_SCHEMA

    def __post_init__(self) -> None:
        for field in ("environment", "release_id", "deployment_id", "instance_id"):
            object.__setattr__(self, field, _validate_part(field, getattr(self, field)))
        if isinstance(self.generation, bool) or self.generation < 1:
            raise ValueError("generation must be a positive integer")

    @property
    def namespace_parts(self) -> tuple[str, ...]:
        return (
            self.environment,
            self.release_id,
            self.deployment_id,
            self.instance_id,
            f"g{self.generation}",
        )

    @property
    def stable_key(self) -> str:
        return "/".join(self.namespace_parts)

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(asdict(self))

    def namespace_root(self, base: str | os.PathLike[str]) -> Path:
        return Path(base).resolve().joinpath(*self.namespace_parts)

    def deterministic_port(self, base_port: int, *, span: int = 1000) -> int:
        if not (1 <= base_port <= 65535):
            raise ValueError("base_port must be a TCP port")
        if span < 1 or base_port + span - 1 > 65535:
            raise ValueError("port span exceeds the TCP range")
        legacy_default = (
            self.environment == "development"
            and self.deployment_id == "default"
            and self.instance_id == "primary"
            and self.generation == 1
        )
        if legacy_default:
            return base_port
        offset = int(self.fingerprint[:8], 16) % span
        return base_port + offset


@dataclass(frozen=True, slots=True)
class LocalResourceManifest:
    identity: RuntimeInstanceIdentity
    state_path: Path
    key_path: Path
    database_path: Path | None
    log_path: Path | None
    evidence_path: Path | None
    temp_path: Path
    management_host: str
    management_port: int
    unix_sockets: tuple[Path, ...]
    owner_uid: int | None
    owner_gid: int | None
    lock_path: Path
    manifest_path: Path
    schema_version: str = MANIFEST_SCHEMA

    @classmethod
    def derive(
        cls,
        identity: RuntimeInstanceIdentity,
        *,
        base_root: str | os.PathLike[str] | None = None,
        management_host: str = "127.0.0.1",
        management_port: int = 8080,
        state_path: str | os.PathLike[str] | None = None,
        database_path: str | os.PathLike[str] | None = None,
        log_path: str | os.PathLike[str] | None = None,
        evidence_path: str | os.PathLike[str] | None = None,
        unix_sockets: Iterable[str | os.PathLike[str]] = (),
    ) -> "LocalResourceManifest":
        root = identity.namespace_root(
            base_root or (Path(tempfile.gettempdir()) / "flashloan-bot")
        )
        root = root.resolve()

        def resolved(value: str | os.PathLike[str] | None, default: str) -> Path:
            path = Path(value) if value is not None else root / default
            return path.resolve() if path.is_absolute() else (root / path).resolve()

        return cls(
            identity=identity,
            state_path=resolved(state_path, "runtime-state.json"),
            key_path=resolved(None, ".runtime-state.key"),
            database_path=(
                resolved(database_path, "runtime.sqlite3")
                if database_path
                else None
            ),
            log_path=(resolved(log_path, "runtime.log") if log_path else None),
            evidence_path=(
                resolved(evidence_path, "evidence.jsonl")
                if evidence_path
                else None
            ),
            temp_path=resolved(None, "tmp"),
            management_host=str(management_host),
            management_port=int(management_port),
            unix_sockets=tuple(
                resolved(value, f"socket-{index}")
                for index, value in enumerate(unix_sockets)
            ),
            owner_uid=(os.getuid() if hasattr(os, "getuid") else None),
            owner_gid=(os.getgid() if hasattr(os, "getgid") else None),
            lock_path=(root / ".instance.lock").resolve(),
            manifest_path=(root / "local-resource-manifest.json").resolve(),
        )

    @property
    def root(self) -> Path:
        return self.manifest_path.parent

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": asdict(self.identity),
            "identity_sha256": self.identity.fingerprint,
            "state_path": str(self.state_path),
            "key_path": str(self.key_path),
            "database_path": str(self.database_path) if self.database_path else None,
            "log_path": str(self.log_path) if self.log_path else None,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "temp_path": str(self.temp_path),
            "management_endpoint": {
                "host": self.management_host,
                "port": self.management_port,
            },
            "unix_sockets": [str(item) for item in self.unix_sockets],
            "owner_uid": self.owner_uid,
            "owner_gid": self.owner_gid,
            "lock_path": str(self.lock_path),
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.to_dict())


class LocalResourceLease:
    """All-or-nothing same-host lease with inode/token-bound cleanup."""

    def __init__(self, manifest: LocalResourceManifest) -> None:
        self.manifest = manifest
        self.cleanup_token = secrets.token_hex(24)
        self._lock_fd: int | None = None
        self._lock_inode: int | None = None
        self._reserved_socket: socket.socket | None = None
        self._acquired = False

    def _lock_payload(self) -> bytes:
        return json.dumps(
            {
                "schema_version": MANIFEST_SCHEMA,
                "identity_sha256": self.manifest.identity.fingerprint,
                "manifest_sha256": self.manifest.fingerprint,
                "cleanup_token": self.cleanup_token,
                "pid": os.getpid(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def acquire(self, *, reserve_socket: bool = False) -> "LocalResourceLease":
        if self._acquired:
            return self
        created_root = not self.manifest.root.exists()
        try:
            self.manifest.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.manifest.temp_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            self._lock_fd = os.open(self.manifest.lock_path, flags, 0o600)
            os.write(self._lock_fd, self._lock_payload())
            os.fsync(self._lock_fd)
            self._lock_inode = os.fstat(self._lock_fd).st_ino
            if reserve_socket:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                sock.bind(
                    (self.manifest.management_host, self.manifest.management_port)
                )
                sock.listen(1)
                self._reserved_socket = sock
            temporary = self.manifest.manifest_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        **self.manifest.to_dict(),
                        "manifest_sha256": self.manifest.fingerprint,
                        "cleanup_token_sha256": hashlib.sha256(
                            self.cleanup_token.encode("ascii")
                        ).hexdigest(),
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.manifest.manifest_path)
            self._acquired = True
            return self
        except FileExistsError as exc:
            raise LocalResourceCollision(
                f"local instance namespace is already owned: {self.manifest.root}"
            ) from exc
        except OSError as exc:
            self._rollback(created_root=created_root)
            raise LocalResourceCollision(
                f"local resource acquisition failed: {exc}"
            ) from exc
        except Exception:
            self._rollback(created_root=created_root)
            raise

    def release_reserved_socket(self) -> None:
        if self._reserved_socket is not None:
            self._reserved_socket.close()
            self._reserved_socket = None

    def _owns_lock(self) -> bool:
        if self._lock_inode is None:
            return False
        try:
            current = self.manifest.lock_path.stat()
            payload = json.loads(self.manifest.lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return False
        return (
            current.st_ino == self._lock_inode
            and payload.get("cleanup_token") == self.cleanup_token
            and payload.get("identity_sha256") == self.manifest.identity.fingerprint
        )

    def _rollback(self, *, created_root: bool = False) -> None:
        self.release_reserved_socket()
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if self._owns_lock():
            self.manifest.lock_path.unlink(missing_ok=True)
            self.manifest.manifest_path.unlink(missing_ok=True)
        if created_root:
            try:
                self.manifest.temp_path.rmdir()
                self.manifest.root.rmdir()
            except OSError:
                pass

    def release(self) -> None:
        if not self._acquired and self._lock_fd is None:
            return
        owns = self._owns_lock()
        self.release_reserved_socket()
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if not owns:
            raise LocalResourceCollision(
                "refusing cleanup because the namespace lock changed ownership"
            )
        self.manifest.manifest_path.unlink(missing_ok=True)
        self.manifest.lock_path.unlink(missing_ok=True)
        self._acquired = False

    def __enter__(self) -> "LocalResourceLease":
        return self.acquire()

    def __exit__(self, *_: object) -> None:
        self.release()
