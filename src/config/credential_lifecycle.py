"""PR-183 credential lifecycle and secure secret delivery primitives."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import errno
import hashlib
import os
from pathlib import Path
import stat
import time
from typing import Callable, Iterator, Mapping, TypeVar

MAX_FILE_SECRET_BYTES = 8192
_ResultT = TypeVar("_ResultT")


class SecretLifecycleError(ValueError):
    """Raised when a credential or secret lease violates policy."""


class CredentialState(StrEnum):
    CREATED = "created"
    STAGED = "staged"
    VALIDATED = "validated"
    ACTIVE = "active"
    RETIRING = "retiring"
    REVOKED = "revoked"
    DESTROYED = "destroyed"


_TRANSITIONS = {
    CredentialState.CREATED: {CredentialState.STAGED, CredentialState.REVOKED},
    CredentialState.STAGED: {CredentialState.VALIDATED, CredentialState.REVOKED},
    CredentialState.VALIDATED: {CredentialState.ACTIVE, CredentialState.REVOKED},
    CredentialState.ACTIVE: {CredentialState.RETIRING, CredentialState.REVOKED},
    CredentialState.RETIRING: {CredentialState.ACTIVE, CredentialState.REVOKED},
    CredentialState.REVOKED: {CredentialState.DESTROYED},
    CredentialState.DESTROYED: set(),
}


@dataclass(slots=True)
class CredentialRecord:
    secret_id: str
    version: str
    backend: str
    usage_scope: str
    consumer_id: str
    issued_at_ns: int
    expires_at_ns: int
    state: CredentialState = CredentialState.CREATED
    supersedes_version: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.secret_id,
                self.version,
                self.backend,
                self.usage_scope,
                self.consumer_id,
            )
        ):
            raise SecretLifecycleError("credential metadata fields are required")
        if self.expires_at_ns <= self.issued_at_ns:
            raise SecretLifecycleError("credential expiry must follow issuance")


class CredentialLifecycleRegistry:
    """Metadata-only rotation/revocation authority; never stores secret values."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], CredentialRecord] = {}

    def register(self, record: CredentialRecord) -> None:
        key = (record.secret_id, record.version)
        if key in self._records:
            raise SecretLifecycleError("credential version already registered")
        self._records[key] = record

    def transition(
        self, secret_id: str, version: str, state: CredentialState
    ) -> CredentialRecord:
        record = self._records[(secret_id, version)]
        if state not in _TRANSITIONS[record.state]:
            raise SecretLifecycleError(
                f"invalid credential transition: {record.state.value}->{state.value}"
            )
        record.state = state
        return record

    def revoke(self, secret_id: str, version: str) -> CredentialRecord:
        record = self._records[(secret_id, version)]
        if record.state is CredentialState.DESTROYED:
            raise SecretLifecycleError("destroyed credential cannot be revoked")
        record.state = CredentialState.REVOKED
        return record

    def is_usable(self, secret_id: str, version: str, *, now_ns: int) -> bool:
        record = self._records.get((secret_id, version))
        return bool(
            record
            and record.state in {CredentialState.ACTIVE, CredentialState.RETIRING}
            and record.issued_at_ns <= now_ns < record.expires_at_ns
        )


@dataclass(frozen=True, slots=True)
class SecretResolutionPolicy:
    production: bool = False
    allow_environment: bool = True
    approved_file_roots: tuple[Path, ...] = ()
    consumer_id: str = "development-runtime"
    usage_scope: str = "development"
    lease_ttl_seconds: int = 300
    version: str | None = None
    max_uses: int | None = None

    def __post_init__(self) -> None:
        if self.production and self.allow_environment:
            raise SecretLifecycleError("production policy must deny env secrets")
        if self.lease_ttl_seconds <= 0:
            raise SecretLifecycleError("lease TTL must be positive")
        if self.max_uses is not None and self.max_uses <= 0:
            raise SecretLifecycleError("max_uses must be positive")
        roots = tuple(root.resolve() for root in self.approved_file_roots)
        object.__setattr__(self, "approved_file_roots", roots)

    @classmethod
    def production_default(
        cls,
        *,
        consumer_id: str,
        usage_scope: str,
        approved_file_roots: tuple[Path, ...] = (),
        lease_ttl_seconds: int = 300,
        max_uses: int | None = None,
    ) -> "SecretResolutionPolicy":
        return cls(
            production=True,
            allow_environment=False,
            approved_file_roots=approved_file_roots,
            consumer_id=consumer_id,
            usage_scope=usage_scope,
            lease_ttl_seconds=lease_ttl_seconds,
            max_uses=max_uses,
        )


@dataclass(slots=True)
class SecretLease:
    secret_id: str
    version: str
    backend: str
    issued_at_ns: int
    expires_at_ns: int
    usage_scope: str
    consumer_id: str
    revoked: bool = False
    use_count: int = 0
    max_uses: int | None = None

    def usable(self, now_ns: int) -> bool:
        return (
            not self.revoked
            and now_ns < self.expires_at_ns
            and (self.max_uses is None or self.use_count < self.max_uses)
        )


class SecretHandle:
    """Redacted short-lived handle with scoped bytes and explicit zeroization."""

    __slots__ = ("_value", "source_scheme", "lease", "_clock_ns", "_closed")

    def __init__(
        self,
        value: str,
        *,
        source_scheme: str,
        lease: SecretLease | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not value:
            raise SecretLifecycleError("resolved secret must be non-empty")
        self._value = bytearray(value.encode("utf-8"))
        self.source_scheme = source_scheme
        now_ns = clock_ns()
        self.lease = lease or SecretLease(
            secret_id=hashlib.sha256(
                f"pr183.secret-id.v1\0{source_scheme}\0legacy".encode()
            ).hexdigest(),
            version="legacy",
            backend=source_scheme,
            issued_at_ns=now_ns,
            expires_at_ns=now_ns + 300 * 1_000_000_000,
            usage_scope="legacy",
            consumer_id="legacy-runtime",
        )
        self._clock_ns = clock_ns
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _authorize_use(self) -> None:
        if self._closed or not self.lease.usable(self._clock_ns()):
            raise SecretLifecycleError("secret lease is expired, revoked, or exhausted")
        self.lease.use_count += 1

    @contextmanager
    def borrow_bytes(self) -> Iterator[memoryview]:
        """Borrow a read-only view without creating an immutable plaintext string."""

        self._authorize_use()
        view = memoryview(self._value).toreadonly()
        try:
            yield view
        finally:
            view.release()

    def use_bytes(
        self,
        consumer: Callable[[memoryview], _ResultT],
        *,
        close_after: bool = False,
    ) -> _ResultT:
        """Run a scoped consumer and optionally revoke immediately afterwards."""

        try:
            with self.borrow_bytes() as view:
                return consumer(view)
        finally:
            if close_after:
                self.close()

    def reveal(self) -> str:
        """Compatibility API; prefer ``borrow_bytes`` or ``use_bytes`` in runtime code."""

        with self.borrow_bytes() as view:
            return view.tobytes().decode("utf-8")

    def revoke(self) -> None:
        self.lease.revoked = True
        for index in range(len(self._value)):
            self._value[index] = 0
        self._closed = True

    close = revoke

    def __enter__(self) -> "SecretHandle":
        if self._closed:
            raise SecretLifecycleError("secret handle is closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "SecretHandle("
            f"source_scheme={self.source_scheme!r}, "
            f"version={self.lease.version!r}, value='<redacted>')"
        )

    def __str__(self) -> str:
        return "<redacted secret>"


def make_handle(
    value: str,
    *,
    scheme: str,
    locator: str,
    policy: SecretResolutionPolicy,
    version: str,
    clock_ns: Callable[[], int],
) -> SecretHandle:
    issued = clock_ns()
    lease = SecretLease(
        secret_id=hashlib.sha256(
            f"pr183.secret-id.v1\0{scheme}\0{locator}".encode()
        ).hexdigest(),
        version=version,
        backend=scheme,
        issued_at_ns=issued,
        expires_at_ns=issued + policy.lease_ttl_seconds * 1_000_000_000,
        usage_scope=policy.usage_scope,
        consumer_id=policy.consumer_id,
        max_uses=policy.max_uses,
    )
    return SecretHandle(
        value,
        source_scheme=scheme,
        lease=lease,
        clock_ns=clock_ns,
    )


def resolve_env_value(
    locator: str,
    *,
    environ: Mapping[str, str],
    policy: SecretResolutionPolicy,
    clock_ns: Callable[[], int],
) -> SecretHandle:
    if not policy.allow_environment:
        raise SecretLifecycleError("environment secrets forbidden by active policy")
    value = environ.get(locator)
    if not value:
        raise SecretLifecycleError(f"missing environment secret reference: {locator}")
    return make_handle(
        value,
        scheme="env",
        locator=locator,
        policy=policy,
        version=policy.version or "environment-current",
        clock_ns=clock_ns,
    )


def resolve_file_value(
    locator: str,
    *,
    policy: SecretResolutionPolicy,
    clock_ns: Callable[[], int],
) -> SecretHandle:
    path = Path(locator)
    if not path.is_absolute():
        raise SecretLifecycleError("file secret path must be absolute")
    if policy.approved_file_roots and not any(
        _within(path.parent.resolve(), root) for root in policy.approved_file_roots
    ):
        raise SecretLifecycleError("file secret is outside approved roots")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SecretLifecycleError("file secret must not be a symlink") from exc
        raise SecretLifecycleError("file secret is unreadable or unsafe") from exc
    try:
        metadata = os.fstat(descriptor)
        _validate_metadata(metadata)
        raw = _read_bounded(descriptor, metadata.st_size)
        final = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (final.st_dev, final.st_ino):
            raise SecretLifecycleError("opened file identity changed during read")
    finally:
        os.close(descriptor)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretLifecycleError("file secret must be UTF-8") from exc
    value = _validate_text(text)
    version_source = (
        f"{metadata.st_dev}:{metadata.st_ino}:"
        f"{metadata.st_mtime_ns}:{metadata.st_size}"
    )
    version = policy.version or hashlib.sha256(version_source.encode()).hexdigest()
    return make_handle(
        value,
        scheme="file",
        locator=locator,
        policy=policy,
        version=version,
        clock_ns=clock_ns,
    )


def _validate_metadata(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise SecretLifecycleError("file secret must be a regular file")
    if os.name == "posix" and hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise SecretLifecycleError("file secret must be owned by this user")
    if stat.S_IMODE(metadata.st_mode) & (stat.S_IRWXG | stat.S_IRWXO):
        raise SecretLifecycleError("file secret grants group/other permissions")
    if metadata.st_nlink != 1:
        raise SecretLifecycleError("file secret must have exactly one link")
    if not 0 < metadata.st_size <= MAX_FILE_SECRET_BYTES:
        raise SecretLifecycleError("file secret has invalid size")


def _read_bounded(descriptor: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_FILE_SECRET_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 4096))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) != expected_size or len(raw) > MAX_FILE_SECRET_BYTES:
        raise SecretLifecycleError("file secret changed size during read")
    return raw


def _validate_text(raw: str) -> str:
    value = raw.rstrip("\n")
    if "\n" in value:
        raise SecretLifecycleError("file secret must contain exactly one line")
    if value != value.strip() or not value:
        raise SecretLifecycleError("file secret has whitespace or is empty")
    return value


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
