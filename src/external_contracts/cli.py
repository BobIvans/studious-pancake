"""CLI for external contract validation, drift, and read-only conformance."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from src.external_contracts.conformance import run_read_only_conformance
from src.external_contracts.drift import detect_drift
from src.external_contracts.provider_protocol_b1 import (
    b1_exit_code,
    evaluate_b1_provider_protocol_readiness,
)
from src.external_contracts.registry import (
    ExternalContractError,
    ExternalContractRegistry,
)
from src.external_contracts.updater import propose_artifact_rotation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flashloan-contracts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="load registry and verify all required pins")
    commands.add_parser("status", help="print registry and promotion states")
    commands.add_parser("drift", help="print deterministic artifact drift report")

    proposal = commands.add_parser("propose", help="create a review-only pin proposal")
    proposal.add_argument("--contract", required=True)
    proposal.add_argument("--artifact", required=True)
    proposal.add_argument("--candidate", required=True)

    conformance = commands.add_parser(
        "conformance", help="run opt-in read-only API conformance probes"
    )
    conformance.add_argument("--enable-online", action="store_true")
    conformance.add_argument("--contract", default=None)

    readiness = commands.add_parser(
        "provider-readiness",
        help="print MEGA-PR B1 provider/protocol readiness for paper runtime",
    )
    readiness.add_argument("--enable-online", action="store_true")
    readiness.add_argument("--provider", action="append", default=None)
    readiness.add_argument("--require-ready", action="store_true")
    return parser


def _conformance_verified(results: list[dict[str, Any]]) -> bool:
    return bool(results) and all(item["verified"] for item in results)


def _conformance_exit_code(
    results: list[dict[str, Any]],
    *,
    online_requested: bool = False,
) -> int:
    failed_states = {"failed-request", "failed-assertion"}
    incomplete_states = {"skipped-missing-env", "skipped-no-probe"}
    if any(item["state"] in failed_states for item in results):
        return 2
    if online_requested and any(item["state"] in incomplete_states for item in results):
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        registry = ExternalContractRegistry.load_default()
        if args.command == "validate":
            print(
                json.dumps(
                    {"ok": True, **registry.status_payload()},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "status":
            print(json.dumps(registry.status_payload(), indent=2, sort_keys=True))
            return 0
        if args.command == "drift":
            report = detect_drift(registry)
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0 if report.ok else 2
        if args.command == "propose":
            proposal = propose_artifact_rotation(
                registry, args.contract, args.artifact, args.candidate
            )
            print(json.dumps(proposal, indent=2, sort_keys=True))
            return 0
        if args.command == "conformance":
            contracts = (
                (registry.get(args.contract),) if args.contract else registry.contracts
            )
            results = [
                run_read_only_conformance(
                    contract, enable_online=args.enable_online
                ).to_dict()
                for contract in contracts
            ]
            payload = {
                "schema_version": "pr070.conformance-report.v1",
                "online_enabled": args.enable_online,
                "verified": _conformance_verified(results),
                "results": results,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return _conformance_exit_code(
                results,
                online_requested=args.enable_online,
            )
        if args.command == "provider-readiness":
            report = evaluate_b1_provider_protocol_readiness(
                registry,
                providers=(
                    tuple(args.provider)
                    if args.provider
                    else ("jupiter", "marginfi", "jito")
                ),
                enable_online=args.enable_online,
            )
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return b1_exit_code(report, require_ready=args.require_ready)
    except (ExternalContractError, OSError, ValueError) as exc:
        print(f"EXTERNAL_CONTRACT_ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
