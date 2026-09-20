"""Canonical desired state, remote inventory, and sealed mutation plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence

DESIRED_STATE_SCHEMA = "mpr-rp-04.external-desired-state.v1"
INVENTORY_SCHEMA = "mpr-rp-04.external-inventory.v1"
PLAN_SCHEMA = "mpr-rp-04.external-plan.v1"


class ExternalResourceError(ValueError):
    """External resource state or plan is malformed or unsafe."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _require_text(value: Any, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise ExternalResourceError(f"{field} is required")
    return text


@dataclass(frozen=True, slots=True)
class ResourceKey:
    provider: str
    kind: str
    environment: str
    name: str

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "ResourceKey":
        return cls(
            provider=_require_text(raw.get("provider"), "provider"),
            kind=_require_text(raw.get("kind"), "kind"),
            environment=_require_text(raw.get("environment"), "environment"),
            name=_require_text(raw.get("name"), "name"),
        )

    @property
    def stable_id(self) -> str:
        return "/".join((self.provider, self.kind, self.environment, self.name))


@dataclass(frozen=True, slots=True)
class DesiredResource:
    key: ResourceKey
    release_id: str
    owner: str
    approval_generation: str
    specification: Mapping[str, Any]
    provider_resource_id: str | None = None
    allow_delete: bool = False

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "DesiredResource":
        specification = raw.get("specification")
        if not isinstance(specification, Mapping):
            raise ExternalResourceError("resource specification must be an object")
        provider_resource_id = raw.get("provider_resource_id")
        return cls(
            key=ResourceKey.from_raw(raw.get("key", {})),
            release_id=_require_text(raw.get("release_id"), "release_id"),
            owner=_require_text(raw.get("owner"), "owner"),
            approval_generation=_require_text(
                raw.get("approval_generation"), "approval_generation"
            ),
            specification=dict(specification),
            provider_resource_id=(
                _require_text(provider_resource_id, "provider_resource_id")
                if provider_resource_id is not None
                else None
            ),
            allow_delete=bool(raw.get("allow_delete", False)),
        )

    @property
    def specification_sha256(self) -> str:
        return canonical_sha256(self.specification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": asdict(self.key),
            "release_id": self.release_id,
            "owner": self.owner,
            "approval_generation": self.approval_generation,
            "specification": dict(self.specification),
            "specification_sha256": self.specification_sha256,
            "provider_resource_id": self.provider_resource_id,
            "allow_delete": self.allow_delete,
        }


@dataclass(frozen=True, slots=True)
class DesiredState:
    resources: tuple[DesiredResource, ...]
    schema_version: str = DESIRED_STATE_SCHEMA

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "DesiredState":
        if raw.get("schema_version") != DESIRED_STATE_SCHEMA:
            raise ExternalResourceError("desired-state schema mismatch")
        values = raw.get("resources")
        if not isinstance(values, list):
            raise ExternalResourceError("desired-state resources must be a list")
        resources = tuple(DesiredResource.from_raw(item) for item in values)
        keys = [item.key.stable_id for item in resources]
        if len(keys) != len(set(keys)):
            raise ExternalResourceError("duplicate desired resource key")
        return cls(resources=resources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "resources": [item.to_dict() for item in self.resources],
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class RemoteResource:
    provider: str
    kind: str
    provider_resource_id: str
    specification: Mapping[str, Any]
    local_key: str | None = None

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(
            {
                "provider": self.provider,
                "kind": self.kind,
                "provider_resource_id": self.provider_resource_id,
                "specification": dict(self.specification),
                "local_key": self.local_key,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "kind": self.kind,
            "provider_resource_id": self.provider_resource_id,
            "specification": dict(self.specification),
            "local_key": self.local_key,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class RemoteInventory:
    resources: tuple[RemoteResource, ...]
    complete: bool
    page_count: int
    provider_generation: str | None = None
    schema_version: str = INVENTORY_SCHEMA

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "RemoteInventory":
        if raw.get("schema_version") != INVENTORY_SCHEMA:
            raise ExternalResourceError("inventory schema mismatch")
        values = raw.get("resources")
        if not isinstance(values, list):
            raise ExternalResourceError("inventory resources must be a list")
        resources = tuple(
            RemoteResource(
                provider=_require_text(item.get("provider"), "provider"),
                kind=_require_text(item.get("kind"), "kind"),
                provider_resource_id=_require_text(
                    item.get("provider_resource_id"), "provider_resource_id"
                ),
                specification=(
                    dict(item["specification"])
                    if isinstance(item.get("specification"), Mapping)
                    else {}
                ),
                local_key=(
                    str(item["local_key"])
                    if item.get("local_key") is not None
                    else None
                ),
            )
            for item in values
        )
        return cls(
            resources=resources,
            complete=bool(raw.get("complete", False)),
            page_count=int(raw.get("page_count", 0)),
            provider_generation=(
                str(raw["provider_generation"])
                if raw.get("provider_generation") is not None
                else None
            ),
        )

    def __post_init__(self) -> None:
        ids = [item.provider_resource_id for item in self.resources]
        if len(ids) != len(set(ids)):
            raise ExternalResourceError(
                "remote inventory contains duplicate provider ids"
            )
        if self.page_count < 1:
            raise ExternalResourceError("inventory page_count must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "complete": self.complete,
            "page_count": self.page_count,
            "provider_generation": self.provider_generation,
            "resources": [item.to_dict() for item in self.resources],
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())


class OperationKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"
    MANUAL_ADOPTION_REQUIRED = "manual_adoption_required"
    MANUAL_DUPLICATE_RESOLUTION_REQUIRED = "manual_duplicate_resolution_required"


@dataclass(frozen=True, slots=True)
class PlanOperation:
    operation_id: str
    kind: OperationKind
    resource_key: str
    provider: str
    resource_kind: str
    desired_specification: Mapping[str, Any] | None
    provider_resource_id: str | None
    expected_remote_fingerprint: str | None
    destructive: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        if self.desired_specification is not None:
            value["desired_specification"] = dict(self.desired_specification)
        return value


@dataclass(frozen=True, slots=True)
class SealedPlan:
    desired_state_sha256: str
    inventory_sha256: str
    inventory_complete: bool
    operations: tuple[PlanOperation, ...]
    plan_sha256: str
    schema_version: str = PLAN_SCHEMA

    @classmethod
    def seal(
        cls,
        *,
        desired_state_sha256: str,
        inventory_sha256: str,
        inventory_complete: bool,
        operations: Sequence[PlanOperation],
    ) -> "SealedPlan":
        payload = {
            "schema_version": PLAN_SCHEMA,
            "desired_state_sha256": desired_state_sha256,
            "inventory_sha256": inventory_sha256,
            "inventory_complete": inventory_complete,
            "operations": [item.to_dict() for item in operations],
        }
        return cls(
            desired_state_sha256=desired_state_sha256,
            inventory_sha256=inventory_sha256,
            inventory_complete=inventory_complete,
            operations=tuple(operations),
            plan_sha256=canonical_sha256(payload),
        )

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "SealedPlan":
        if raw.get("schema_version") != PLAN_SCHEMA:
            raise ExternalResourceError("plan schema mismatch")
        operations_raw = raw.get("operations")
        if not isinstance(operations_raw, list):
            raise ExternalResourceError("plan operations must be a list")
        operations = tuple(
            PlanOperation(
                operation_id=_require_text(item.get("operation_id"), "operation_id"),
                kind=OperationKind(str(item.get("kind"))),
                resource_key=_require_text(item.get("resource_key"), "resource_key"),
                provider=_require_text(item.get("provider"), "provider"),
                resource_kind=_require_text(item.get("resource_kind"), "resource_kind"),
                desired_specification=(
                    dict(item["desired_specification"])
                    if isinstance(item.get("desired_specification"), Mapping)
                    else None
                ),
                provider_resource_id=(
                    str(item["provider_resource_id"])
                    if item.get("provider_resource_id") is not None
                    else None
                ),
                expected_remote_fingerprint=(
                    str(item["expected_remote_fingerprint"])
                    if item.get("expected_remote_fingerprint") is not None
                    else None
                ),
                destructive=bool(item.get("destructive", False)),
                reason=_require_text(item.get("reason"), "reason"),
            )
            for item in operations_raw
        )
        candidate = cls.seal(
            desired_state_sha256=_require_text(
                raw.get("desired_state_sha256"), "desired_state_sha256"
            ),
            inventory_sha256=_require_text(
                raw.get("inventory_sha256"), "inventory_sha256"
            ),
            inventory_complete=bool(raw.get("inventory_complete", False)),
            operations=operations,
        )
        if candidate.plan_sha256 != raw.get("plan_sha256"):
            raise ExternalResourceError("sealed plan digest mismatch")
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "desired_state_sha256": self.desired_state_sha256,
            "inventory_sha256": self.inventory_sha256,
            "inventory_complete": self.inventory_complete,
            "operations": [item.to_dict() for item in self.operations],
            "plan_sha256": self.plan_sha256,
        }
