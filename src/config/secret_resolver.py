"""Secret reference resolver with PR-183 secure delivery and leases."""

from __future__ import annotations

import os
import time
from typing import Callable, Mapping, Protocol

from src.config.credential_lifecycle import (
    CredentialLifecycleRegistry,
    CredentialRecord,
    CredentialState,
    MAX_FILE_SECRET_BYTES,
    SecretHandle,
    SecretLease,
    SecretLifecycleError,
    SecretResolutionPolicy,
    resolve_env_value,
    resolve_file_value,
)

SecretResolutionError = SecretLifecycleError


class SecretReferenceLike(Protocol):
    scheme: str
    locator: str


def resolve_secret_reference(
    reference: SecretReferenceLike,
    *,
    environ: Mapping[str, str] | None = None,
    policy: SecretResolutionPolicy | None = None,
    clock_ns: Callable[[], int] = time.time_ns,
) -> SecretHandle:
    """Resolve a reference under an immutable policy; development stays compatible."""

    scheme = getattr(reference, "scheme", None)
    locator = getattr(reference, "locator", None)
    if not isinstance(scheme, str) or not isinstance(locator, str) or not locator:
        raise SecretResolutionError("secret reference must expose scheme and locator")
    active_policy = policy or SecretResolutionPolicy()
    if scheme == "env":
        active_env = os.environ if environ is None else environ
        return resolve_env_value(
            locator,
            environ=active_env,
            policy=active_policy,
            clock_ns=clock_ns,
        )
    if scheme == "file":
        return resolve_file_value(
            locator,
            policy=active_policy,
            clock_ns=clock_ns,
        )
    if scheme == "keychain":
        raise SecretResolutionError(
            "keychain secret references are not supported by this runtime"
        )
    raise SecretResolutionError(f"unsupported secret reference scheme: {scheme}")


__all__ = [
    "CredentialLifecycleRegistry",
    "CredentialRecord",
    "CredentialState",
    "MAX_FILE_SECRET_BYTES",
    "SecretHandle",
    "SecretLease",
    "SecretResolutionError",
    "SecretResolutionPolicy",
    "resolve_secret_reference",
]
