"""Pure desired-state planner with duplicate, adoption, and deletion guards."""

from __future__ import annotations

import hashlib
from typing import Iterable

from .models import (
    DesiredResource,
    DesiredState,
    OperationKind,
    PlanOperation,
    RemoteInventory,
    RemoteResource,
    SealedPlan,
)


def _operation_id(kind: OperationKind, key: str, desired_hash: str) -> str:
    raw = f"{kind.value}\0{key}\0{desired_hash}".encode()
    return hashlib.sha256(raw).hexdigest()


def _matching_resources(
    desired: DesiredResource,
    inventory: RemoteInventory,
) -> tuple[RemoteResource, ...]:
    by_bound_id = tuple(
        item
        for item in inventory.resources
        if desired.provider_resource_id is not None
        and item.provider_resource_id == desired.provider_resource_id
    )
    if by_bound_id:
        return by_bound_id
    return tuple(
        item
        for item in inventory.resources
        if item.provider == desired.key.provider
        and item.kind == desired.key.kind
        and item.local_key == desired.key.stable_id
    )


def build_plan(
    desired_state: DesiredState,
    inventory: RemoteInventory,
) -> SealedPlan:
    operations: list[PlanOperation] = []
    desired_keys = {item.key.stable_id for item in desired_state.resources}
    matched_remote_ids: set[str] = set()

    for desired in desired_state.resources:
        key = desired.key.stable_id
        matches = _matching_resources(desired, inventory)
        if len(matches) > 1:
            kind = OperationKind.MANUAL_DUPLICATE_RESOLUTION_REQUIRED
            operations.append(
                PlanOperation(
                    operation_id=_operation_id(kind, key, desired.specification_sha256),
                    kind=kind,
                    resource_key=key,
                    provider=desired.key.provider,
                    resource_kind=desired.key.kind,
                    desired_specification=desired.specification,
                    provider_resource_id=None,
                    expected_remote_fingerprint=None,
                    destructive=False,
                    reason="multiple remotely managed resources match one local key",
                )
            )
            continue
        if not matches:
            same_shape = tuple(
                item
                for item in inventory.resources
                if item.provider == desired.key.provider
                and item.kind == desired.key.kind
                and item.specification == desired.specification
            )
            if same_shape:
                kind = OperationKind.MANUAL_ADOPTION_REQUIRED
                operations.append(
                    PlanOperation(
                        operation_id=_operation_id(
                            kind, key, desired.specification_sha256
                        ),
                        kind=kind,
                        resource_key=key,
                        provider=desired.key.provider,
                        resource_kind=desired.key.kind,
                        desired_specification=desired.specification,
                        provider_resource_id=None,
                        expected_remote_fingerprint=None,
                        destructive=False,
                        reason="matching unowned resource requires explicit adoption",
                    )
                )
            else:
                kind = OperationKind.CREATE
                operations.append(
                    PlanOperation(
                        operation_id=_operation_id(
                            kind, key, desired.specification_sha256
                        ),
                        kind=kind,
                        resource_key=key,
                        provider=desired.key.provider,
                        resource_kind=desired.key.kind,
                        desired_specification=desired.specification,
                        provider_resource_id=None,
                        expected_remote_fingerprint=None,
                        destructive=False,
                        reason="managed resource is absent",
                    )
                )
            continue

        remote = matches[0]
        matched_remote_ids.add(remote.provider_resource_id)
        if remote.specification == desired.specification:
            kind = OperationKind.NOOP
            reason = "remote resource already converged"
        else:
            kind = OperationKind.UPDATE
            reason = "remote specification differs from desired state"
        operations.append(
            PlanOperation(
                operation_id=_operation_id(kind, key, desired.specification_sha256),
                kind=kind,
                resource_key=key,
                provider=desired.key.provider,
                resource_kind=desired.key.kind,
                desired_specification=desired.specification,
                provider_resource_id=remote.provider_resource_id,
                expected_remote_fingerprint=remote.fingerprint,
                destructive=kind is OperationKind.UPDATE,
                reason=reason,
            )
        )

    for remote in inventory.resources:
        if (
            remote.provider_resource_id in matched_remote_ids
            or remote.local_key is None
        ):
            continue
        if remote.local_key in desired_keys:
            continue
        kind = OperationKind.DELETE
        operations.append(
            PlanOperation(
                operation_id=_operation_id(kind, remote.local_key, remote.fingerprint),
                kind=kind,
                resource_key=remote.local_key,
                provider=remote.provider,
                resource_kind=remote.kind,
                desired_specification=None,
                provider_resource_id=remote.provider_resource_id,
                expected_remote_fingerprint=remote.fingerprint,
                destructive=True,
                reason="managed remote resource is absent from desired state",
            )
        )

    return SealedPlan.seal(
        desired_state_sha256=desired_state.fingerprint,
        inventory_sha256=inventory.fingerprint,
        inventory_complete=inventory.complete,
        operations=operations,
    )


def executable_operations(plan: SealedPlan) -> Iterable[PlanOperation]:
    return (
        item
        for item in plan.operations
        if item.kind
        in {OperationKind.CREATE, OperationKind.UPDATE, OperationKind.DELETE}
    )
