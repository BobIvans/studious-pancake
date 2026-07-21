"""Secret reference resolver for PR-120 runtime configuration.

The resolver turns structural secret references into short-lived handles without
including secret values in repr/log/display surfaces. It intentionally accepts a
loose reference object with ``scheme`` and ``locator`` attributes so the runtime
model can keep owning SecretReference without creating an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Mapping, Protocol

MAX_FILE_SECRET_BYTES = 8192


class SecretResolutionError(ValueError):
    """Raised when a secret reference cannot be resolved safely."""


class SecretReferenceLike(Protocol):
    """Minimal runtime-owned SecretReference shape consumed by the resolver."""

    scheme: str
    locator: str


@dataclass(frozen=True, slots=True)
class SecretHandle:
    """A redaction-safe resolved secret handle.

    Callers must explicitly reveal the value at the boundary that needs it. The
    object deliberately hides the value from repr/str and is not JSON-friendly.
    """

    _value: str
    source_scheme: str

    def __post_init__(self) -> None:
        if not isinstance(self._value, str) or self._value == "":
            raise SecretResolutionError("resolved secret value must be non-empty text")

    def reveal(self) -> str:
        """Return the contained secret value for the immediate consuming boundary."""

        return self._value

    def __repr__(self) -> str:
        return f"SecretHandle(source_scheme={self.source_scheme!r}, value='<redacted>')"

    def __str__(self) -> str:
        return "<redacted secret>"


def resolve_secret_reference(
    reference: SecretReferenceLike,
    *,
    environ: Mapping[str, str] | None = None,
) -> SecretHandle:
    """Resolve a typed secret reference or raise a fail-closed error.

    Supported schemes:
    - ``env:NAME`` reads a non-empty environment variable from the supplied env.
    - ``file:/absolute/path`` reads a single-line secret from a restrictive
      regular file owned by the current user.
    - ``keychain:...`` is explicitly unsupported in this runtime until a
      reviewed OS-specific adapter is wired; this is a hard error, never None.
    """

    scheme = getattr(reference, "scheme", None)
    locator = getattr(reference, "locator", None)
    if not isinstance(scheme, str) or not isinstance(locator, str) or not locator:
        raise SecretResolutionError("secret reference must expose scheme and locator")
    if scheme == "env":
        return _resolve_env(locator, environ=environ)
    if scheme == "file":
        return _resolve_file(locator)
    if scheme == "keychain":
        raise SecretResolutionError(
            "keychain secret references are not supported by this runtime"
        )
    raise SecretResolutionError(f"unsupported secret reference scheme: {scheme}")


def _resolve_env(locator: str, *, environ: Mapping[str, str] | None) -> SecretHandle:
    active_env = os.environ if environ is None else environ
    value = active_env.get(locator)
    if value is None or value == "":
        raise SecretResolutionError(f"missing environment secret reference: {locator}")
    return SecretHandle(value, source_scheme="env")


def _resolve_file(locator: str) -> SecretHandle:
    path = Path(locator)
    if not path.is_absolute():
        raise SecretResolutionError("file secret references must use an absolute path")
    try:
        link_stat = path.lstat()
    except OSError as exc:
        raise SecretResolutionError("file secret reference is unreadable") from exc
    if stat.S_ISLNK(link_stat.st_mode):
        raise SecretResolutionError("file secret reference must not be a symlink")
    if not stat.S_ISREG(link_stat.st_mode):
        raise SecretResolutionError("file secret reference must be a regular file")
    if os.name == "posix" and hasattr(os, "getuid"):
        if link_stat.st_uid != os.getuid():
            raise SecretResolutionError(
                "file secret reference must be owned by this user"
            )
    mode = stat.S_IMODE(link_stat.st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SecretResolutionError(
            "file secret reference must not grant group/other permissions"
        )
    if link_stat.st_size <= 0 or link_stat.st_size > MAX_FILE_SECRET_BYTES:
        raise SecretResolutionError("file secret reference has invalid size")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SecretResolutionError("file secret reference must be UTF-8 text") from exc
    except OSError as exc:
        raise SecretResolutionError("file secret reference is unreadable") from exc
    trimmed_newlines = raw.rstrip("\n")
    if "\n" in trimmed_newlines:
        raise SecretResolutionError(
            "file secret reference must contain exactly one line"
        )
    if trimmed_newlines != trimmed_newlines.strip():
        raise SecretResolutionError(
            "file secret reference must not contain surrounding whitespace"
        )
    if trimmed_newlines == "":
        raise SecretResolutionError("file secret reference must not be empty")
    return SecretHandle(trimmed_newlines, source_scheme="file")
