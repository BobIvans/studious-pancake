"""Immutable process bootstrap snapshot and invocation-local correlation context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
import hashlib
import json
import locale
from types import MappingProxyType
import os
from pathlib import Path
import secrets
import time
from typing import Any, Iterable, Mapping, Sequence

from src.runtime.platform_identity import PlatformIdentity, capture_platform_identity

BOOTSTRAP_SCHEMA = "mpr-rp-02.bootstrap-context.v1"
_CORRELATION_ID: ContextVar[str | None] = ContextVar(
    "flashloan_correlation_id", default=None
)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _selected_environment(
    environ: Mapping[str, str],
    *,
    explicit_names: Iterable[str] = (),
) -> Mapping[str, str]:
    explicit = set(explicit_names)
    selected = {
        key: value
        for key, value in environ.items()
        if key.startswith("FLASHLOAN_")
        or key in explicit
        or key in {"LANG", "LC_ALL", "TZ", "PYTHONHASHSEED", "PYTHONUTF8"}
    }
    return MappingProxyType(dict(sorted(selected.items())))


@dataclass(frozen=True, slots=True)
class BootstrapContext:
    schema_version: str
    argv: tuple[str, ...]
    command: str
    working_root: Path
    environment: Mapping[str, str]
    config_generation: str
    release_generation: str
    policy_generation: str
    invocation_id: str
    run_id: str
    correlation_id: str
    process_id: int
    process_started_unix_ns: int
    locale_name: str
    timezone_name: str
    event_loop_policy: str
    platform_identity: PlatformIdentity

    @classmethod
    def capture(
        cls,
        argv: Sequence[str],
        *,
        command: str,
        environ: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        explicit_environment_names: Iterable[str] = (),
        invocation_id: str | None = None,
    ) -> "BootstrapContext":
        source_env = dict(os.environ if environ is None else environ)
        environment = _selected_environment(
            source_env, explicit_names=explicit_environment_names
        )
        root = Path(cwd or os.getcwd()).resolve()
        platform_identity = capture_platform_identity(environ=environment)
        generated = invocation_id or secrets.token_hex(16)
        return cls(
            schema_version=BOOTSTRAP_SCHEMA,
            argv=tuple(map(str, argv)),
            command=command,
            working_root=root,
            environment=environment,
            config_generation=environment.get("FLASHLOAN_CONFIG_GENERATION", "unknown"),
            release_generation=environment.get(
                "FLASHLOAN_RELEASE_ID", "development"
            ),
            policy_generation=environment.get(
                "FLASHLOAN_POLICY_GENERATION", "unknown"
            ),
            invocation_id=generated,
            run_id=environment.get("FLASHLOAN_RUN_ID", generated),
            correlation_id=environment.get("FLASHLOAN_CORRELATION_ID", generated),
            process_id=os.getpid(),
            process_started_unix_ns=time.time_ns(),
            locale_name=locale.setlocale(locale.LC_CTYPE),
            timezone_name=environment.get("TZ", time.tzname[0] if time.tzname else ""),
            event_loop_policy=platform_identity.event_loop_policy,
            platform_identity=platform_identity,
        )

    def with_environment_overrides(
        self, overrides: Mapping[str, str]
    ) -> "BootstrapContext":
        merged = dict(self.environment)
        merged.update({str(key): str(value) for key, value in overrides.items()})
        return replace(self, environment=MappingProxyType(dict(sorted(merged.items()))))

    def resolve_path(self, value: str | os.PathLike[str]) -> Path:
        path = Path(value)
        return (
            path.resolve()
            if path.is_absolute()
            else (self.working_root / path).resolve()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "argv": list(self.argv),
            "command": self.command,
            "working_root": str(self.working_root),
            "environment": dict(self.environment),
            "config_generation": self.config_generation,
            "release_generation": self.release_generation,
            "policy_generation": self.policy_generation,
            "invocation_id": self.invocation_id,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "process_id": self.process_id,
            "process_started_unix_ns": self.process_started_unix_ns,
            "locale_name": self.locale_name,
            "timezone_name": self.timezone_name,
            "event_loop_policy": self.event_loop_policy,
            "platform_identity_sha256": self.platform_identity.fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(self.to_dict())

    def activate_correlation(self) -> Token[str | None]:
        """Propagate a non-authoritative correlation value to nested diagnostics."""

        return _CORRELATION_ID.set(self.correlation_id)

    @staticmethod
    def reset_correlation(token: Token[str | None]) -> None:
        _CORRELATION_ID.reset(token)


def current_correlation_id() -> str | None:
    return _CORRELATION_ID.get()
