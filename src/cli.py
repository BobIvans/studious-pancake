"""Installed CLI for the supported fail-closed runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import signal
import sys
from dataclasses import asdict
from typing import Any, Sequence

from src.application import ConfigurationError, build_application
from src.capabilities import CapabilityContractError, CapabilityMatrix
from src.config.doctor import run_config_doctor
from src.config.runtime import (
    ConfigurationLoadError,
    RuntimeConfig,
    load_runtime_config,
)
from src.container_runtime import run_safe_idle
from src.paper_shadow import (
    PaperShadowRunStatus,
    PaperShadowRuntimeDependencies,
    build_paper_shadow_runtime,
)
from src.paper_shadow.a1_vertical_preflight import evaluate_paper_vertical_a1
from src.paper_shadow.runner import PaperShadowRunSummary

logger = logging.getLogger(__name__)

EXIT_CONFIGURATION_ERROR = 2
EXIT_NO_EXECUTABLE_STRATEGIES = 3
EXIT_MODE_UNAVAILABLE = 4
EXIT_PAPER_SHADOW_BLOCKED = 5
EXIT_PAPER_SHADOW_FAILED = 6
EXIT_PAPER_SHADOW_DEGRADED = 7

PAPER_SHADOW_SUCCESS_STATUSES = frozenset(
    {PaperShadowRunStatus.HEALTHY_IDLE, PaperShadowRunStatus.PAPER_OUTCOME}
)

LauncherConfig = RuntimeConfig


def load_configuration(
    path: str | None = None,
    *,
    cli_overrides: dict[str, Any] | None = None,
) -> RuntimeConfig:
    """Load the canonical immutable PR-026 configuration."""
    return load_runtime_config(path, cli_overrides=cli_overrides)


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
    parser.add_argument(
        "--config-file",
        default=None,
        help="optional typed YAML override; environment and CLI values take precedence",
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

    paper_parser = subparsers.add_parser(
        "paper-shadow",
        help="run one fail-closed PR-089 paper/shadow pass and record durable evidence",
    )
    paper_parser.add_argument(
        "--journal-path",
        default=None,
        help=(
            "JSONL journal path; defaults to FLASHLOAN_PAPER_SHADOW_JOURNAL "
            "or .runtime/paper-shadow-journal.jsonl"
        ),
    )
    paper_parser.add_argument("--json", action="store_true", dest="as_json")

    vertical_parser = subparsers.add_parser(
        "paper-vertical-preflight",
        help=(
            "inspect the MEGA-PR A1 canonical sender-free paper-vertical "
            "dependency seam"
        ),
    )
    vertical_parser.add_argument("--json", action="store_true", dest="as_json")

    container_parser = subparsers.add_parser(
        "container",
        help="run a fail-closed, network-free container supervisor until signalled",
    )
    container_parser.add_argument(
        "--state-file",
        default=None,
        help=(
            "override the liveness state path used by the temporary PR-025 "
            "healthcheck"
        ),
    )

    config_parser = subparsers.add_parser(
        "config", help="inspect or validate the immutable PR-026 configuration"
    )
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    dump_parser = config_commands.add_parser(
        "dump", help="print a redacted normalized configuration"
    )
    dump_parser.add_argument("--json", action="store_true", dest="as_json")
    doctor_parser = config_commands.add_parser(
        "doctor", help="validate config, registry, secrets and optional RPC identity"
    )
    doctor_parser.add_argument("--online", action="store_true")
    doctor_parser.add_argument("--check-secrets", action="store_true")
    doctor_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _status_payload(
    matrix: CapabilityMatrix, app: Any, config: RuntimeConfig
) -> dict[str, Any]:
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
        "configuration": {
            "schema_version": config.schema_version,
            "fingerprint": config.fingerprint(),
            "mode": config.runtime.mode.value,
            "cluster": config.cluster.name,
            "rpc_configured": config.cluster.rpc_http_url is not None,
            "jupiter_enabled": config.providers.jupiter.enabled,
            "jito_enabled": config.providers.jito.enabled,
            "marginfi_enabled": config.providers.marginfi.enabled,
        },
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


def _paper_shadow_journal_path(override: str | None = None) -> Path:
    configured = override or os.environ.get("FLASHLOAN_PAPER_SHADOW_JOURNAL")
    return (
        Path(configured) if configured else Path(".runtime/paper-shadow-journal.jsonl")
    )


def _paper_shadow_display_reason(
    payload: dict[str, Any],
    *,
    pr023_compat_reason: bool,
) -> str:
    reason = str(payload["terminal_reason"])
    if pr023_compat_reason and reason == "blocked_missing_wallet_public_key":
        return "blocked_no_discovery_composition"
    return reason


def _print_paper_shadow_summary(
    payload: dict[str, Any],
    *,
    as_json: bool,
    pr023_compat_reason: bool = False,
) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    display_reason = _paper_shadow_display_reason(
        payload,
        pr023_compat_reason=pr023_compat_reason,
    )
    readiness = payload.get("readiness", {})
    dependencies = tuple(readiness.get("dependency_reasons", ()))
    dependency_suffix = (
        f" dependencies={','.join(dependencies)}" if dependencies else ""
    )
    print(
        "PAPER_SHADOW_RUNNER: "
        f"status={payload['status']} "
        f"reason={display_reason} "
        f"ready={readiness.get('ready_for_next_cycle', False)} "
        f"journal={payload['journal_path']} "
        f"events={payload['events_written']}"
        f"{dependency_suffix}"
    )


def _paper_shadow_exit_code(summary: PaperShadowRunSummary) -> int:
    if summary.status in PAPER_SHADOW_SUCCESS_STATUSES:
        return 0
    if summary.status is PaperShadowRunStatus.BLOCKED:
        return EXIT_PAPER_SHADOW_BLOCKED
    if summary.status is PaperShadowRunStatus.DEGRADED:
        return EXIT_PAPER_SHADOW_DEGRADED
    return EXIT_PAPER_SHADOW_FAILED


def _run_paper_shadow_once(
    config: RuntimeConfig,
    *,
    journal_path: str | None = None,
    as_json: bool = False,
    pr023_compat_reason: bool = False,
) -> int:
    runtime = build_paper_shadow_runtime(
        config,
        journal_path=_paper_shadow_journal_path(journal_path),
    )
    summary = asyncio.run(runtime.run_once())
    _print_paper_shadow_summary(
        summary.to_dict(),
        as_json=as_json,
        pr023_compat_reason=pr023_compat_reason,
    )
    return _paper_shadow_exit_code(summary)


def _run_paper_vertical_preflight(
    config: RuntimeConfig,
    *,
    as_json: bool = False,
) -> int:
    report = evaluate_paper_vertical_a1(config, PaperShadowRuntimeDependencies())
    payload = report.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        missing = ",".join(payload["missing_surfaces"])
        invalid = ",".join(payload["invalid_surfaces"])
        print(
            "PAPER_VERTICAL_PREFLIGHT: "
            f"state={payload['state']} "
            f"reason={payload['reason_code']} "
            f"ready={payload['ready']} "
            f"missing={missing or '-'} "
            f"invalid={invalid or '-'} "
            "live=false signer=false sender=false"
        )
    return 0 if report.ready else EXIT_PAPER_SHADOW_BLOCKED


def _run_requested_mode(
    mode: str, matrix: CapabilityMatrix, app: Any, config: RuntimeConfig
) -> int:
    status = _status_payload(matrix, app, config)
    if mode == "live":
        print(
            "LIVE_MODE_UNAVAILABLE: live submission is hard-denied by the PR-023 "
            "product contract.",
            file=sys.stderr,
        )
        return EXIT_MODE_UNAVAILABLE
    if mode == "paper":
        return _run_paper_shadow_once(
            config,
            as_json=False,
            pr023_compat_reason=True,
        )
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
        cli_overrides: dict[str, Any] = {}
        if args.command == "run" and args.mode != "live":
            cli_overrides["runtime.mode"] = args.mode
        config = load_configuration(
            args.config_file, cli_overrides=cli_overrides or None
        )
        if config.validation.verify_rpc_at_startup:
            startup_report = run_config_doctor(
                config, online=True, check_secrets=True, environ=os.environ
            )
            if not startup_report.ok:
                errors = "; ".join(
                    item.message
                    for item in startup_report.diagnostics
                    if item.severity == "error"
                )
                raise ConfigurationLoadError(
                    f"startup configuration attestation failed: {errors}"
                )
        matrix = CapabilityMatrix.load_default()
        app = build_application(config, matrix)
        if args.command == "status":
            payload = _status_payload(matrix, app, config)
            _print_status(payload, as_json=args.as_json)
            return (
                0 if payload["capability_contract_valid"] else EXIT_CONFIGURATION_ERROR
            )
        if args.command == "capabilities":
            _print_capabilities(matrix, as_json=args.as_json)
            return 0
        if args.command == "paper-shadow":
            return _run_paper_shadow_once(
                config,
                journal_path=args.journal_path,
                as_json=args.as_json,
            )
        if args.command == "paper-vertical-preflight":
            return _run_paper_vertical_preflight(config, as_json=args.as_json)
        if args.command == "run":
            return _run_requested_mode(args.mode, matrix, app, config)
        if args.command == "container":
            return asyncio.run(run_safe_idle(matrix, app, state_file=args.state_file))
        if args.command == "config" and args.config_command == "dump":
            payload = config.redacted_dict()
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.command == "config" and args.config_command == "doctor":
            report = run_config_doctor(
                config,
                online=args.online,
                check_secrets=args.check_secrets,
                environ=os.environ,
            )
            if args.as_json:
                print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            else:
                print(f"Configuration fingerprint: {report.config_fingerprint}")
                for diagnostic in report.diagnostics:
                    print(
                        f"[{diagnostic.severity.upper()}] "
                        f"{diagnostic.code}: {diagnostic.message}"
                    )
            return 0 if report.ok else EXIT_CONFIGURATION_ERROR
        _parser().print_help()
        return EXIT_CONFIGURATION_ERROR
    except (
        CapabilityContractError,
        ConfigurationError,
        ConfigurationLoadError,
    ) as exc:
        print(f"CONFIGURATION_ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
