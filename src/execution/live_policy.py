"""Typed PR-190 live-risk policy ingestion and identity.

The live control plane consumes this model instead of an unvalidated dictionary.
The model remains mapping-compatible for the existing gate code while every load
and assignment is validated against an explicit schema.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from src.config.canonical import canonical_digest
from src.config.strict_yaml import load_strict_yaml

SCHEMA_VERSION = "pr018.live-risk.v1"
_SECRET_REF_PATTERN = re.compile(r"^(env|file|keychain):(.+)$")
_SecretScheme = Literal["env", "file", "keychain"]


class LivePolicyError(ValueError):
    """Raised when a live policy is ambiguous or violates its typed contract."""


class PolicyModel(BaseModel):
    """Strict model with a compatibility mapping surface for existing gates."""

    model_config = ConfigDict(extra="forbid", strict=False, validate_assignment=True)

    def __getitem__(self, key: str) -> Any:
        if key not in type(self).model_fields:
            raise KeyError(key)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in type(self).model_fields:
            raise KeyError(key)
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> tuple[str, ...]:
        return tuple(type(self).model_fields)

    def items(self) -> tuple[tuple[str, Any], ...]:
        return tuple((key, getattr(self, key)) for key in self.keys())

    def values(self) -> tuple[Any, ...]:
        return tuple(getattr(self, key) for key in self.keys())


class SecretIdentityReference(PolicyModel):
    scheme: _SecretScheme
    locator: StrictStr = Field(min_length=1, max_length=4096)
    version: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    usage_scope: StrictStr = Field(
        default="live-runtime", min_length=1, max_length=256
    )

    @classmethod
    def parse(cls, value: Any) -> "SecretIdentityReference":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            match = _SECRET_REF_PATTERN.fullmatch(value.strip())
            if not match:
                raise LivePolicyError(
                    "secret reference must use env:, file:, or keychain:; "
                    "inline values are forbidden"
                )
            scheme, locator = match.groups()
            if scheme == "file" and not locator.startswith("/"):
                raise LivePolicyError(
                    "file secret references must use absolute paths"
                )
            return cls(scheme=cast(_SecretScheme, scheme), locator=locator)
        if isinstance(value, Mapping):
            return cls.model_validate(dict(value))
        raise LivePolicyError("secret reference must be a string or typed mapping")

    def safe_display(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "locator": "<redacted>",
            "version": self.version,
            "usage_scope": self.usage_scope,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "locator": self.locator,
            "version": self.version,
            "usage_scope": self.usage_scope,
        }

    def runtime_reference(self) -> str:
        return f"{self.scheme}:{self.locator}"


class ClusterPolicy(PolicyModel):
    name: StrictStr = Field(min_length=1, max_length=128)
    genesis_hash: StrictStr = Field(min_length=16, max_length=128)
    commitment: Literal["processed", "confirmed", "finalized"]
    rpc_endpoint_identities: tuple[StrictStr, ...] = Field(min_length=1)


class WalletPolicy(PolicyModel):
    public_key: StrictStr = Field(min_length=32, max_length=128)
    signer_reference: SecretIdentityReference
    observed_lamports: StrictInt = Field(ge=0)

    @field_validator("signer_reference", mode="before")
    @classmethod
    def _parse_reference(cls, value: Any) -> SecretIdentityReference:
        return SecretIdentityReference.parse(value)


class PerAttemptPolicy(PolicyModel):
    max_net_native_debit_lamports: StrictInt = Field(gt=0)
    rent_policy_ref: StrictStr = Field(min_length=1, max_length=256)
    tip_policy_ref: StrictStr = Field(min_length=1, max_length=256)


class CanaryPolicy(PolicyModel):
    max_principal_by_asset: dict[StrictStr, StrictInt] = Field(min_length=1)
    max_landed_count_per_window: StrictInt = Field(ge=1, le=1)
    window_seconds: StrictInt = Field(gt=0)
    route_profile: StrictStr = Field(min_length=1, max_length=256)

    @field_validator("max_principal_by_asset")
    @classmethod
    def _positive_principal(cls, value: dict[str, int]) -> dict[str, int]:
        if any(amount <= 0 for amount in value.values()):
            raise ValueError("canary principal limits must be positive integers")
        return value


class LossLimitsPolicy(PolicyModel):
    settlement_asset: StrictStr = Field(min_length=1, max_length=64)
    per_trade_lamports: StrictInt = Field(gt=0)
    daily_lamports: StrictInt = Field(gt=0)


class AllowlistsPolicy(PolicyModel):
    program_ids: tuple[StrictStr, ...] = Field(min_length=1)
    markets: tuple[StrictStr, ...] = Field(min_length=1)
    mints: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("program_ids", "markets", "mints")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowlist entries must be unique")
        return value


class ProviderPolicy(PolicyModel):
    role: Literal["execution", "discovery"]
    capability: Literal["composable_instructions", "quote_only"]
    required_for_live: StrictBool
    registry_hash: StrictStr = Field(min_length=1, max_length=256)
    auth_reference: SecretIdentityReference | None = None
    endpoint_identity: StrictStr | None = Field(
        default=None, min_length=1, max_length=512
    )

    @field_validator("auth_reference", mode="before")
    @classmethod
    def _parse_auth_reference(
        cls, value: Any
    ) -> SecretIdentityReference | None:
        if value is None:
            return None
        return SecretIdentityReference.parse(value)


class TipPolicy(PolicyModel):
    exactly_one_tip: StrictBool


class FreshnessPolicy(PolicyModel):
    max_evidence_age_seconds: StrictInt = Field(gt=0)
    max_slot_skew: StrictInt = Field(ge=0)


class ShadowEvidencePolicy(PolicyModel):
    required_versions: tuple[StrictStr, ...] = Field(min_length=1)


class DivergencePolicy(PolicyModel):
    asset: StrictStr = Field(min_length=1, max_length=64)
    tolerance_lamports: StrictInt = Field(ge=0)
    window_seconds: StrictInt = Field(gt=0)


class ControlPlanePolicy(PolicyModel):
    sqlite_path: StrictStr = Field(min_length=1, max_length=4096)
    kill_switch_path: StrictStr = Field(min_length=1, max_length=4096)
    report_retention_days: StrictInt = Field(gt=0)
    redact_secrets: StrictBool


class LiveRiskPolicy(PolicyModel):
    schema_version: Literal["pr018.live-risk.v1"]
    live_enabled: StrictBool
    cluster: ClusterPolicy
    wallet: WalletPolicy
    protected_reserve_lamports: StrictInt = Field(gt=0)
    per_attempt: PerAttemptPolicy
    max_outstanding_attempts: StrictInt = Field(ge=1, le=1)
    canary: CanaryPolicy
    loss_limits: LossLimitsPolicy
    allowlists: AllowlistsPolicy
    providers: dict[StrictStr, ProviderPolicy] = Field(min_length=1)
    submission_modes: tuple[Literal["rpc", "jito"], ...] = Field(min_length=1)
    tip_policy: TipPolicy
    freshness: FreshnessPolicy
    shadow_evidence: ShadowEvidencePolicy
    divergence_policy: DivergencePolicy
    automatic_latches: tuple[StrictStr, ...] = Field(min_length=1)
    control_plane: ControlPlanePolicy
    permit_ttl_seconds: StrictInt = Field(gt=0, le=3600)

    @field_validator("providers")
    @classmethod
    def _providers_are_named(
        cls, value: dict[str, ProviderPolicy]
    ) -> dict[str, ProviderPolicy]:
        if any(not name.strip() for name in value):
            raise ValueError("provider names cannot be blank")
        return value

    @model_validator(mode="after")
    def _live_invariants(self) -> "LiveRiskPolicy":
        execution = [p for p in self.providers.values() if p.role == "execution"]
        if not execution:
            raise ValueError("at least one execution provider is required")
        if not any(p.required_for_live for p in execution):
            raise ValueError("one execution provider must be required_for_live")
        if self.loss_limits.per_trade_lamports > self.loss_limits.daily_lamports:
            raise ValueError("per-trade loss limit cannot exceed daily loss limit")
        return self

    def safe_display(self) -> dict[str, Any]:
        def safe(value: Any) -> Any:
            if isinstance(value, SecretIdentityReference):
                return value.safe_display()
            if isinstance(value, BaseModel):
                return {
                    name: safe(getattr(value, name))
                    for name in type(value).model_fields
                }
            if isinstance(value, Mapping):
                return {str(key): safe(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [safe(item) for item in value]
            return value

        return safe(self)

    def identity_payload(self) -> dict[str, Any]:
        def identity(value: Any) -> Any:
            if isinstance(value, SecretIdentityReference):
                return value.identity_payload()
            if isinstance(value, BaseModel):
                return {
                    name: identity(getattr(value, name))
                    for name in type(value).model_fields
                }
            if isinstance(value, Mapping):
                return {str(key): identity(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [identity(item) for item in value]
            return value

        return identity(self)

    def runtime_materialization(self) -> dict[str, Any]:
        def materialize(value: Any) -> Any:
            if isinstance(value, SecretIdentityReference):
                return value.runtime_reference()
            if isinstance(value, BaseModel):
                return {
                    name: materialize(getattr(value, name))
                    for name in type(value).model_fields
                }
            if isinstance(value, Mapping):
                return {str(key): materialize(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [materialize(item) for item in value]
            return value

        return materialize(self)

    def identity_hash(self) -> str:
        return canonical_digest(
            self.identity_payload(),
            domain="flashloan.live-risk-policy",
            schema_version=self.schema_version,
            environment=self.cluster.name,
        )


def ensure_live_policy(
    policy: LiveRiskPolicy | Mapping[str, Any],
) -> LiveRiskPolicy:
    if isinstance(policy, LiveRiskPolicy):
        return policy
    try:
        return LiveRiskPolicy.model_validate(dict(policy))
    except Exception as exc:
        raise LivePolicyError(str(exc)) from exc


def load_live_policy(path: str | Path) -> LiveRiskPolicy:
    try:
        payload = load_strict_yaml(path)
        return LiveRiskPolicy.model_validate(payload)
    except Exception as exc:
        if isinstance(exc, LivePolicyError):
            raise
        raise LivePolicyError(str(exc)) from exc


def canonical_policy_hash(
    policy: LiveRiskPolicy | Mapping[str, Any],
) -> str:
    return ensure_live_policy(policy).identity_hash()


__all__ = [
    "LivePolicyError",
    "LiveRiskPolicy",
    "PolicyModel",
    "SCHEMA_VERSION",
    "SecretIdentityReference",
    "canonical_policy_hash",
    "ensure_live_policy",
    "load_live_policy",
]
