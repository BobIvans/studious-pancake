"""Installed external-resource plan/apply/status/reconcile command."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

from .engine import ProviderConflict, apply_plan
from .helius import HeliusManagementError, HeliusWebhookProvider
from .ledger import MutationConflict, MutationLedger
from .models import (
    DesiredState,
    ExternalResourceError,
    RemoteInventory,
    SealedPlan,
)
from .planner import build_plan
from .providers import InMemoryProvider

EXIT_ERROR = 2
EXIT_BLOCKED = 3
EXIT_CONFLICT = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flashloan-external-resources")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--desired", required=True)
    plan.add_argument("--inventory", required=True)
    plan.add_argument("--output", required=True)

    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--state-db", required=True)
    apply.add_argument("--provider", choices=("memory", "helius"), required=True)
    apply.add_argument("--inventory")
    apply.add_argument("--helius-api-key-file")
    apply.add_argument("--confirm-remote-mutation", action="store_true")

    status = commands.add_parser("status")
    status.add_argument("--state-db", required=True)

    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--desired", required=True)
    reconcile.add_argument("--inventory", required=True)
    reconcile.add_argument("--output", required=True)
    return parser


def _read_json(path: str) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ExternalResourceError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def _read_owner_only_text(path: str) -> str:
    source = Path(path)
    info = source.stat()
    if not source.is_file() or source.is_symlink():
        raise ExternalResourceError("credential path must be a regular file")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ExternalResourceError("credential file must be owner-only")
    value = source.read_text(encoding="utf-8").strip()
    if not value or len(value) > 4096:
        raise ExternalResourceError("credential file has invalid size")
    return value


def _bindings_for_helius(ledger: MutationLedger) -> dict[str, str]:
    return {
        str(item["provider_resource_id"]): str(item["resource_key"])
        for item in ledger.bindings()
        if item["provider"] == "helius" and item["resource_kind"] == "webhook"
    }


def _plan(desired_path: str, inventory_path: str, output: str) -> dict[str, Any]:
    desired = DesiredState.from_raw(_read_json(desired_path))
    inventory = RemoteInventory.from_raw(_read_json(inventory_path))
    plan = build_plan(desired, inventory)
    _write_json(output, plan.to_dict())
    return plan.to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command in {"plan", "reconcile"}:
            payload = _plan(args.desired, args.inventory, args.output)
            print(json.dumps(payload, sort_keys=True))
            manual = any(
                item["kind"].startswith("manual_") for item in payload["operations"]
            )
            return EXIT_BLOCKED if manual else 0

        ledger = MutationLedger(args.state_db)
        if args.command == "status":
            print(json.dumps(ledger.status(), sort_keys=True))
            return 0

        plan = SealedPlan.from_raw(_read_json(args.plan))
        if args.provider == "memory":
            if not args.inventory:
                raise ExternalResourceError("memory provider requires --inventory")
            inventory = RemoteInventory.from_raw(_read_json(args.inventory))
            provider = InMemoryProvider(
                inventory.resources, complete=inventory.complete
            )
        else:
            if not args.confirm_remote_mutation:
                raise ExternalResourceError(
                    "Helius apply requires --confirm-remote-mutation"
                )
            if not args.helius_api_key_file:
                raise ExternalResourceError(
                    "Helius apply requires --helius-api-key-file"
                )
            provider = HeliusWebhookProvider(
                api_key=_read_owner_only_text(args.helius_api_key_file),
                bindings=_bindings_for_helius(ledger),
            )
        result = apply_plan(plan, provider=provider, ledger=ledger)
        print(json.dumps(result.to_dict(), sort_keys=True))
        return 0 if result.applied else EXIT_BLOCKED
    except (MutationConflict, ProviderConflict) as exc:
        print(f"EXTERNAL_RESOURCE_CONFLICT:{type(exc).__name__}", file=sys.stderr)
        return EXIT_CONFLICT
    except (
        ExternalResourceError,
        HeliusManagementError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(f"EXTERNAL_RESOURCE_ERROR:{type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
