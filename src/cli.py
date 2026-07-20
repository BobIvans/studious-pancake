"""Installed CLI for the supported fail-closed runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from src.application import ConfigurationError, build_application
from src.capabilities import CapabilityContractError, CapabilityMatrix
from src.container_runtime import run_safe_idle
from src.strategy.interfaces import StrategyMode

logger = logging.getLogger(__name__)

EXIT_CONFIGURATION_ERROR = 2
EXIT_NO_EXECUTABLE_STRATEGIES = 3
EXIT_MODE_UNAVAILABLE = 4


@dataclass(slots=True)
class LauncherConfig:
    """Temporary launcher defaults pending the unified configuration PR."""

    strategy_modes: dict[str, str] = field(
        default_factory=lambda: {
            "lst_depeg": StrategyMode.DISABLED.value,
            "lst_unstake": StrategyMode.DISABLED.value,
            "circular_arbitrage": StrategyMode.DISABLED.value,
        }
    )
    opportunity_queue_size: int = 1024
    shutdown_drain_timeout_seconds: float = 0.25


def load_configuration() -> LauncherConfig:
    """Return fail-closed defaults for the only supported entrypoint.

    PR-023 intentionally does not activate strategies from legacy environment
    flags. A typed file/env/CLI configuration model belongs to PR-026.
    """
    return LauncherConfig()


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - platform fallback
            signal.signal(sig, lambda *_: stop_event.set())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashloan-bot",
        description="Inspect or run the supported fail-closed arbitrage runtime.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="start the supported runtime")
    run_parser.add_argument(
        "--mode",
        choices=("disabled", "paper", "shadow", "live"),
        default="shadow",
        help="requested product mode; unavailable modes fail closed",
    )

    status_parser = subparsers.add_parser(
        "status", help="show runtime, strategy, and capability status"
    )
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    capabilities_parser = subparsers.add_parser(
        "capabilities", help="print the machine-readable capability matrix"
    )
    capabilities_parser.add_argument("--json", action="store_true", dest="as_json")

    container_parser = subparsers.add_parser(
        "container",
        help="run a fail-closed, network-free container supervisor until signalled",
    )
    container_parser.add_argument(
        "--state-file",
        default=None,
        help="override the liveness state path used by the temporary PR-025 healthcheck",
    )
    return parser


def _status_payload(matrix: CapabilityMatrix, app: Any) -> dict[str, Any]:
    errors = list(app.capability_errors())
    executable = [entry.name for entry in app.executable_strategies()]
    return {
        "schema_version": "pr023.runtime-status.v1",
        "product_state": matrix.product_state,
        "supported_entrypoint": matrix.supported_entrypoint,
        "default_command": matrix.default_command,
        "capability_contract_valid": not errors,
        "capability_contract_errors": errors,
        "executable_strategies": executable,
        "diagnostic": (
            "READY_FOR_DECLARED_MODE" if executable else "NO_EXECUTABLE_STRATEGIES"
        ),
        "strategies": [asdict(entry) for entry in app.manifest()],
        "runtime_modes": matrix.runtime_modes,
    }


def _print_status(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Product state: {payload['product_state']}")
    print(f"Supported entrypoint: {payload['supported_entrypoint']}")
    print(f"Diagnostic: {payload['diagnostic']}")
    if payload["capability_contract_errors"]:
        print("Capability contract errors:")
        for error in payload["capability_contract_errors"]:
            print(f"  - {error}")
    print("Strategies:")
    for strategy in payload["strategies"]:
        quarantine = " quarantined" if strategy["quarantined"] else ""
        print(
            f"  - {strategy['name']}: mode={strategy['effective_mode']} "
            f"capability={strategy['capability']}{quarantine}; "
            f"reason={strategy['reason']}"
        )


def _print_capabilities(matrix: CapabilityMatrix, *, as_json: bool) -> None:
    payload = matrix.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Capability schema: {matrix.schema_version}")
    print(f"Product state: {matrix.product_state}")
    print(f"Supported entrypoint: {matrix.supported_entrypoint}")
    for component in matrix.components:
        quarantine = " quarantined" if component.quarantined else ""
        active = "active" if component.active_in_supported_entrypoint else "inactive"
        print(
            f"  - {component.id}: {component.capability.value}, {active}{quarantine}; "
            f"modes={','.join(component.allowed_modes)}"
        )


async def _run_application(app: Any) -> int:
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    try:
        await app.run()
        await stop_event.wait()
    finally:
        if app._started:  # supported launcher owns this application instance
            await app.stop()
    return 0


def _run_requested_mode(mode: str, matrix: CapabilityMatrix, app: Any) -> int:
    status = _status_payload(matrix, app)
    if mode == "live":
        print(
            "LIVE_MODE_UNAVAILABLE: live submission is hard-denied by the PR-023 "
            "product contract.",
            file=sys.stderr,
        )
        return EXIT_MODE_UNAVAILABLE
    if mode == "paper":
        print(
            "PAPER_MODE_UNAVAILABLE: the legacy paper trader is quarantined; "
            "the canonical paper runner is scheduled for PR-038.",
            file=sys.stderr,
        )
        return EXIT_MODE_UNAVAILABLE
    if mode == "disabled":
        _print_status(status, as_json=False)
        return 0
    if status["capability_contract_errors"]:
        _print_status(status, as_json=False)
        return EXIT_CONFIGURATION_ERROR
    if not status["executable_strategies"]:
        print(
            "NO_EXECUTABLE_STRATEGIES: no strategy is both enabled and declared "
            "shadow-ready/live-ready in config/capabilities.json.",
            file=sys.stderr,
        )
        _print_status(status, as_json=False)
        return EXIT_NO_EXECUTABLE_STRATEGIES
    return asyncio.run(_run_application(app))


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list:
        args_list = ["run", "--mode", "shadow"]
    args = _parser().parse_args(args_list)
    try:
        matrix = CapabilityMatrix.load_default()
        app = build_application(load_configuration(), matrix)
        if args.command == "status":
            payload = _status_payload(matrix, app)
            _print_status(payload, as_json=args.as_json)
            return (
                0 if payload["capability_contract_valid"] else EXIT_CONFIGURATION_ERROR
            )
        if args.command == "capabilities":
            _print_capabilities(matrix, as_json=args.as_json)
            return 0
        if args.command == "run":
            return _run_requested_mode(args.mode, matrix, app)
        if args.command == "container":
            return asyncio.run(run_safe_idle(matrix, app, state_file=args.state_file))
        _parser().print_help()
        return EXIT_CONFIGURATION_ERROR
    except (CapabilityContractError, ConfigurationError) as exc:
        print(f"CONFIGURATION_ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
