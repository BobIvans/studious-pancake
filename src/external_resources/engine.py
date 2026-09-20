"""Idempotent plan application with durable intent and independent readback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .ledger import MutationLedger
from .models import (
    OperationKind,
    PlanOperation,
    RemoteInventory,
    RemoteResource,
    SealedPlan,
)


class ProviderConflict(RuntimeError):
    """Remote generation or fingerprint changed since plan creation."""


class ExternalResourceProvider(Protocol):
    def discover(self) -> RemoteInventory: ...

    def create(
        self,
        operation: PlanOperation,
        *,
        idempotency_key: str,
    ) -> RemoteResource: ...

    def update(
        self,
        operation: PlanOperation,
        *,
        idempotency_key: str,
    ) -> RemoteResource: ...

    def delete(
        self,
        operation: PlanOperation,
        *,
        idempotency_key: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ApplyResult:
    plan_sha256: str
    applied: bool
    blockers: tuple[str, ...]
    operations: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mpr-rp-04.apply-result.v1",
            "plan_sha256": self.plan_sha256,
            "applied": self.applied,
            "blockers": list(self.blockers),
            "operations": [dict(item) for item in self.operations],
        }


def _remote_by_id(
    inventory: RemoteInventory, provider_id: str
) -> RemoteResource | None:
    return next(
        (
            item
            for item in inventory.resources
            if item.provider_resource_id == provider_id
        ),
        None,
    )


def _preflight(plan: SealedPlan, current: RemoteInventory) -> tuple[str, ...]:
    blockers: list[str] = []
    if not current.complete:
        blockers.append("REMOTE_INVENTORY_INCOMPLETE")
    if current.fingerprint != plan.inventory_sha256:
        blockers.append("REMOTE_INVENTORY_CHANGED")
    for operation in plan.operations:
        if operation.kind in {
            OperationKind.MANUAL_ADOPTION_REQUIRED,
            OperationKind.MANUAL_DUPLICATE_RESOLUTION_REQUIRED,
        }:
            blockers.append(f"{operation.kind.value.upper()}:{operation.resource_key}")
        if operation.destructive and not plan.inventory_complete:
            blockers.append("DESTRUCTIVE_APPLY_REQUIRES_COMPLETE_PLANNED_INVENTORY")
    return tuple(dict.fromkeys(blockers))


def apply_plan(
    plan: SealedPlan,
    *,
    provider: ExternalResourceProvider,
    ledger: MutationLedger,
) -> ApplyResult:
    ledger.persist_plan(plan)

    # A sealed plan that already reached terminal state is an idempotent replay.
    # Do not compare its historical inventory fingerprint with the necessarily
    # changed post-apply inventory before returning the durable readback.
    replayed: list[Mapping[str, object]] = []
    replay_complete = True
    for operation in plan.operations:
        if operation.kind is OperationKind.NOOP:
            replayed.append(
                {
                    "operation_id": operation.operation_id,
                    "state": "noop",
                    "resource_key": operation.resource_key,
                }
            )
            continue
        if operation.kind not in {
            OperationKind.CREATE,
            OperationKind.UPDATE,
            OperationKind.DELETE,
        }:
            replay_complete = False
            break
        terminal = ledger.terminal_result(operation.operation_id)
        if terminal is None:
            replay_complete = False
            break
        replayed.append(terminal)
    if replay_complete:
        return ApplyResult(
            plan_sha256=plan.plan_sha256,
            applied=True,
            blockers=(),
            operations=tuple(replayed),
        )

    current = provider.discover()
    blockers = _preflight(plan, current)
    if blockers:
        return ApplyResult(
            plan_sha256=plan.plan_sha256,
            applied=False,
            blockers=blockers,
            operations=(),
        )

    results: list[Mapping[str, object]] = []
    for operation in plan.operations:
        if operation.kind is OperationKind.NOOP:
            results.append(
                {
                    "operation_id": operation.operation_id,
                    "state": "noop",
                    "resource_key": operation.resource_key,
                }
            )
            continue
        if operation.kind not in {
            OperationKind.CREATE,
            OperationKind.UPDATE,
            OperationKind.DELETE,
        }:
            continue
        replay = ledger.persist_intent(plan, operation)
        if replay is not None:
            results.append(replay)
            continue

        before = provider.discover()
        if operation.provider_resource_id is not None:
            remote = _remote_by_id(before, operation.provider_resource_id)
            if remote is None:
                raise ProviderConflict("planned remote resource disappeared")
            if remote.fingerprint != operation.expected_remote_fingerprint:
                raise ProviderConflict("remote fingerprint changed before mutation")

        if operation.kind is OperationKind.CREATE:
            changed = provider.create(operation, idempotency_key=operation.operation_id)
            provider_id = changed.provider_resource_id
        elif operation.kind is OperationKind.UPDATE:
            changed = provider.update(operation, idempotency_key=operation.operation_id)
            provider_id = changed.provider_resource_id
        else:
            provider.delete(operation, idempotency_key=operation.operation_id)
            changed = None
            provider_id = operation.provider_resource_id

        after = provider.discover()
        if operation.kind is OperationKind.DELETE:
            if provider_id and _remote_by_id(after, provider_id) is not None:
                raise ProviderConflict("delete readback still contains resource")
            payload: Mapping[str, object] = {
                "operation_id": operation.operation_id,
                "state": "deleted",
                "resource_key": operation.resource_key,
                "provider_resource_id": provider_id,
            }
            ledger.record_terminal(operation, payload)
            ledger.remove_binding(operation.resource_key)
        else:
            readback = _remote_by_id(after, provider_id)
            if readback is None:
                raise ProviderConflict("mutation readback did not find resource")
            if readback.specification != operation.desired_specification:
                raise ProviderConflict("mutation readback did not converge")
            payload = {
                "operation_id": operation.operation_id,
                "state": "converged",
                "resource_key": operation.resource_key,
                "provider_resource_id": provider_id,
                "remote_fingerprint": readback.fingerprint,
            }
            ledger.record_terminal(
                operation,
                payload,
                provider_resource_id=provider_id,
                remote_fingerprint=readback.fingerprint,
            )
        results.append(payload)

    return ApplyResult(
        plan_sha256=plan.plan_sha256,
        applied=True,
        blockers=(),
        operations=tuple(results),
    )
