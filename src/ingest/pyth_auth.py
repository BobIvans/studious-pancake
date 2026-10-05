"""Fail-closed Hermes authentication for legacy/read-only Pyth consumers."""

from __future__ import annotations

import os
from typing import Mapping

from src.config.runtime import SecretReference
from src.config.secret_resolver import SecretResolutionError

PYTH_API_KEY_REFERENCE_ENV = "FLASHLOAN_PYTH_API_KEY_REFERENCE"


class PythHermesAuthError(RuntimeError):
    """Raised before network I/O when Hermes authentication is unavailable."""


def resolve_pyth_api_key(
    *,
    api_key: str | None = None,
    api_key_reference: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve a Hermes API key without accepting an inline env secret by default.

    `api_key` exists for dependency injection/tests. Product/runtime configuration
    should provide `FLASHLOAN_PYTH_API_KEY_REFERENCE=env:PYTH_API_KEY` or an
    owner-only absolute `file:` reference.
    """

    if api_key is not None:
        value = api_key.strip()
        if not value:
            raise PythHermesAuthError("Pyth Hermes API key is empty")
        return value

    active_env = os.environ if environ is None else environ
    raw_reference = (
        api_key_reference
        if api_key_reference is not None
        else active_env.get(PYTH_API_KEY_REFERENCE_ENV, "")
    )
    raw_reference = raw_reference.strip()
    if not raw_reference:
        raise PythHermesAuthError(
            f"Pyth Hermes requires an API key reference in {PYTH_API_KEY_REFERENCE_ENV}"
        )
    try:
        reference = SecretReference.parse(raw_reference)
        assert reference is not None
        value = reference.resolve_from_environment(active_env).strip()
    except (ValueError, SecretResolutionError) as exc:
        raise PythHermesAuthError(
            "Pyth Hermes API key reference could not be resolved"
        ) from exc
    if not value:
        raise PythHermesAuthError("Pyth Hermes API key resolved to an empty value")
    return value


def pyth_bearer_headers(
    *,
    api_key: str | None = None,
    api_key_reference: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    key = resolve_pyth_api_key(
        api_key=api_key,
        api_key_reference=api_key_reference,
        environ=environ,
    )
    return {"Authorization": f"Bearer {key}"}
