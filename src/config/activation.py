"""Atomic, generation-bound configuration activation for PR-190."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from src.config.canonical import canonical_digest, canonical_json_bytes, to_json_value

try:  # pragma: no cover - Windows fallback remains fail-closed per process.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


class ConfigActivationError(RuntimeError):
    pass


class FrozenActivationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)


class ConfigSourceEntry(FrozenActivationModel):
    source_type: Literal[
        "packaged-defaults",
        "config-file",
        "environment-binding",
        "cli-override",
        "secret-reference",
        "approved-overlay",
    ]
    identity: StrictStr = Field(min_length=1, max_length=4096)
    value_path: StrictStr = Field(min_length=1, max_length=1024)
    content_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    secret: StrictBool = False


class ConfigSourceManifest(FrozenActivationModel):
    schema_version: Literal["pr190.config-source-manifest.v1"] = (
        "pr190.config-source-manifest.v1"
    )
    sources: tuple[ConfigSourceEntry, ...]

    def identity_hash(self, *, environment: str) -> str:
        return canonical_digest(
            self,
            domain="flashloan.config-source-manifest",
            schema_version=self.schema_version,
            environment=environment,
        )


class ConfigChange(FrozenActivationModel):
    path: StrictStr
    before_hash: StrictStr | None = None
    after_hash: StrictStr | None = None
    impact: Literal["operational", "security", "financial", "identity"]


class EffectiveConfigDiff(FrozenActivationModel):
    schema_version: Literal["pr190.effective-config-diff.v1"] = (
        "pr190.effective-config-diff.v1"
    )
    previous_identity: StrictStr | None
    proposed_identity: StrictStr
    changes: tuple[ConfigChange, ...]
    restart_required: StrictBool
    revalidation_required: StrictBool


class ConfigGenerationRecord(FrozenActivationModel):
    schema_version: Literal["pr190.config-generation.v1"] = (
        "pr190.config-generation.v1"
    )
    generation: StrictInt = Field(ge=1)
    previous_generation: StrictInt | None = Field(default=None, ge=1)
    policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    release_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    approvals: tuple[StrictStr, ...] = Field(min_length=1)
    created_at: StrictInt = Field(ge=0)
    expires_at: StrictInt = Field(gt=0)
    signature_algorithm: Literal["hmac-sha256"] = "hmac-sha256"
    signature: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    def unsigned_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="python")
        payload.pop("signature")
        return payload


class ConfigActivationStore:
    """Filesystem CAS store for one immutable active configuration generation."""

    CURRENT_NAME = "active-config-generation.json"

    def __init__(self, root: str | Path, *, signing_key: bytes, environment: str):
        if len(signing_key) < 32:
            raise ConfigActivationError(
                "activation signing key must contain at least 32 bytes"
            )
        if not environment:
            raise ConfigActivationError("activation environment is required")
        self.root = Path(root)
        self.signing_key = bytes(signing_key)
        self.environment = environment
        self.current_path = self.root / self.CURRENT_NAME
        self.lock_path = self.root / ".activation.lock"

    def _signature(self, unsigned_payload: Mapping[str, Any]) -> str:
        blob = canonical_json_bytes(
            unsigned_payload,
            domain="flashloan.config-generation-signature",
            schema_version="pr190.config-generation.v1",
            environment=self.environment,
        )
        return hmac.new(self.signing_key, blob, hashlib.sha256).hexdigest()

    def verify(self, record: ConfigGenerationRecord, *, now: int | None = None) -> None:
        expected = self._signature(record.unsigned_payload())
        if not hmac.compare_digest(expected, record.signature):
            raise ConfigActivationError("config generation signature mismatch")
        selected_now = int(time.time()) if now is None else now
        if record.expires_at <= selected_now:
            raise ConfigActivationError("config generation is expired")

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ConfigActivationError("activation root cannot be a symlink")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | nofollow, 0o600)
        try:
            os.fchmod(fd, 0o600)
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _strict_json(raw: str) -> dict[str, Any]:
        def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ConfigActivationError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        try:
            value = json.loads(raw, object_pairs_hook=pairs_hook)
        except (json.JSONDecodeError, ConfigActivationError) as exc:
            raise ConfigActivationError("invalid activation record JSON") from exc
        if not isinstance(value, dict):
            raise ConfigActivationError("activation record must be a JSON object")
        return value

    def load_current(self, *, now: int | None = None) -> ConfigGenerationRecord | None:
        if not self.current_path.exists():
            return None
        if self.current_path.is_symlink():
            raise ConfigActivationError("active generation cannot be a symlink")
        try:
            raw = self.current_path.read_text(encoding="utf-8")
            record = ConfigGenerationRecord.model_validate(self._strict_json(raw))
        except OSError as exc:
            raise ConfigActivationError(
                f"cannot read active generation: {exc}"
            ) from exc
        self.verify(record, now=now)
        return record

    def activate(
        self,
        *,
        reviewed_previous_generation: int | None,
        policy_hash: str,
        release_hash: str,
        source_manifest: ConfigSourceManifest,
        approvals: Iterable[str],
        expires_at: int,
        now: int | None = None,
    ) -> ConfigGenerationRecord:
        selected_now = int(time.time()) if now is None else now
        approval_tuple = tuple(sorted(set(approvals)))
        if not approval_tuple:
            raise ConfigActivationError("at least one approval is required")
        if expires_at <= selected_now:
            raise ConfigActivationError("activation expiry must be in the future")

        with self._locked():
            current = self.load_current(now=selected_now)
            actual_previous = None if current is None else current.generation
            if reviewed_previous_generation != actual_previous:
                raise ConfigActivationError(
                    "stale config approval: reviewed previous generation does not "
                    "match active generation"
                )
            generation = 1 if current is None else current.generation + 1
            unsigned = {
                "schema_version": "pr190.config-generation.v1",
                "generation": generation,
                "previous_generation": actual_previous,
                "policy_hash": policy_hash,
                "release_hash": release_hash,
                "source_manifest_hash": source_manifest.identity_hash(
                    environment=self.environment
                ),
                "approvals": approval_tuple,
                "created_at": selected_now,
                "expires_at": expires_at,
                "signature_algorithm": "hmac-sha256",
            }
            record = ConfigGenerationRecord(
                **unsigned,
                signature=self._signature(unsigned),
            )
            self._atomic_write(record)
            return record

    def _atomic_write(self, record: ConfigGenerationRecord) -> None:
        payload = json.dumps(
            to_json_value(record),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".generation-", dir=self.root)
        tmp_path = Path(tmp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.current_path.is_symlink():
                raise ConfigActivationError(
                    "active generation cannot be replaced through symlink"
                )
            os.replace(tmp_path, self.current_path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


def _impact_for_path(path: str) -> str:
    lowered = path.lower()
    if any(
        token in lowered
        for token in ("secret", "signer", "auth", "wallet", "endpoint")
    ):
        return "identity"
    if any(
        token in lowered
        for token in ("loss", "lamport", "principal", "fee", "reserve")
    ):
        return "financial"
    if any(
        token in lowered
        for token in ("allowlist", "provider", "live_enabled", "mode")
    ):
        return "security"
    return "operational"


def effective_config_diff(
    previous: Any | None,
    proposed: Any,
    *,
    previous_identity: str | None,
    proposed_identity: str,
) -> EffectiveConfigDiff:
    before = {} if previous is None else to_json_value(previous)
    after = to_json_value(proposed)
    changes: list[ConfigChange] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                walk(
                    left.get(key),
                    right.get(key),
                    f"{path}.{key}" if path else key,
                )
            return
        if left == right:
            return
        before_hash = (
            None
            if left is None
            else hashlib.sha256(
                json.dumps(
                    left,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
        )
        after_hash = (
            None
            if right is None
            else hashlib.sha256(
                json.dumps(
                    right,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
        )
        changes.append(
            ConfigChange(
                path=path,
                before_hash=before_hash,
                after_hash=after_hash,
                impact=_impact_for_path(path),
            )
        )

    walk(before, after, "")
    return EffectiveConfigDiff(
        previous_identity=previous_identity,
        proposed_identity=proposed_identity,
        changes=tuple(changes),
        restart_required=bool(changes),
        revalidation_required=any(
            change.impact in {"security", "financial", "identity"}
            for change in changes
        ),
    )


__all__ = [
    "ConfigActivationError",
    "ConfigActivationStore",
    "ConfigChange",
    "ConfigGenerationRecord",
    "ConfigSourceEntry",
    "ConfigSourceManifest",
    "EffectiveConfigDiff",
    "effective_config_diff",
]
