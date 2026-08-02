from __future__ import annotations

from pathlib import Path

from src.external_resources.engine import apply_plan
from src.external_resources.ledger import MutationLedger
from src.external_resources.models import (
    DESIRED_STATE_SCHEMA,
    DesiredState,
    OperationKind,
    RemoteInventory,
    RemoteResource,
)
from src.external_resources.planner import build_plan
from src.external_resources.providers import InMemoryProvider


def _desired(specification: dict[str, object] | None = None) -> DesiredState:
    return DesiredState.from_raw(
        {
            "schema_version": DESIRED_STATE_SCHEMA,
            "resources": [
                {
                    "key": {
                        "provider": "helius",
                        "kind": "webhook",
                        "environment": "test",
                        "name": "primary",
                    },
                    "release_id": "release-1",
                    "owner": "operations",
                    "approval_generation": "approval-1",
                    "specification": specification
                    or {
                        "webhookURL": "https://example.invalid/webhook",
                        "webhookType": "enhanced",
                        "accountAddresses": ["address-a"],
                    },
                }
            ],
        }
    )


def test_create_apply_readback_and_sealed_plan_replay(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    plan = build_plan(_desired(), provider.discover())
    ledger = MutationLedger(tmp_path / "mutations.sqlite3")

    first = apply_plan(plan, provider=provider, ledger=ledger)
    replay = apply_plan(plan, provider=provider, ledger=ledger)

    assert first.applied is True
    assert replay.applied is True
    assert first.operations == replay.operations
    assert len(provider.discover().resources) == 1
    assert ledger.status()["intents"] == {"terminal": 1}


def test_inventory_change_conflicts_before_side_effect(tmp_path: Path) -> None:
    planned_provider = InMemoryProvider()
    plan = build_plan(_desired(), planned_provider.discover())
    changed_provider = InMemoryProvider(
        (
            RemoteResource(
                provider="helius",
                kind="webhook",
                provider_resource_id="unrelated",
                specification={"webhookURL": "https://other.invalid"},
                local_key=None,
            ),
        )
    )

    result = apply_plan(
        plan,
        provider=changed_provider,
        ledger=MutationLedger(tmp_path / "changed.sqlite3"),
    )

    assert result.applied is False
    assert "REMOTE_INVENTORY_CHANGED" in result.blockers
    assert len(changed_provider.discover().resources) == 1


def test_incomplete_inventory_blocks_destructive_plan(tmp_path: Path) -> None:
    remote = RemoteResource(
        provider="helius",
        kind="webhook",
        provider_resource_id="managed-1",
        specification={"webhookURL": "https://old.invalid"},
        local_key="helius/webhook/test/obsolete",
    )
    inventory = RemoteInventory(
        resources=(remote,), complete=False, page_count=1
    )
    empty = DesiredState(resources=())
    plan = build_plan(empty, inventory)
    provider = InMemoryProvider((remote,), complete=False)

    assert plan.operations[0].kind is OperationKind.DELETE
    result = apply_plan(
        plan,
        provider=provider,
        ledger=MutationLedger(tmp_path / "incomplete.sqlite3"),
    )
    assert result.applied is False
    assert "REMOTE_INVENTORY_INCOMPLETE" in result.blockers
    assert "DESTRUCTIVE_APPLY_REQUIRES_COMPLETE_PLANNED_INVENTORY" in result.blockers


def test_matching_unowned_resource_requires_explicit_adoption() -> None:
    desired = _desired()
    remote = RemoteResource(
        provider="helius",
        kind="webhook",
        provider_resource_id="unowned-1",
        specification=desired.resources[0].specification,
        local_key=None,
    )
    inventory = RemoteInventory(resources=(remote,), complete=True, page_count=1)

    plan = build_plan(desired, inventory)

    assert plan.operations[0].kind is OperationKind.MANUAL_ADOPTION_REQUIRED
