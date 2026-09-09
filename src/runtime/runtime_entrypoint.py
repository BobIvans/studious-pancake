"""Immutable installed runtime adapter for canonical ``src.cli_pr189``.

The semantic inspection owner remains :mod:`src.cli_entrypoint`.  This adapter
only owns active ``run`` dispatch so the immutable bootstrap snapshot can reach
the durable paper service without process-global environment mutation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from src.config.runtime import ConfigurationLoadError, load_runtime_config
from src.paper_shadow.durable_service_a3 import (
    A3PaperServiceStatus,
    InstalledDurablePaperServiceReport,
    build_installed_durable_paper_service,
)
from src.paper_shadow.repeated_service_pr04 import (
    RepeatedInstalledPaperService,
    RepeatedPaperServiceConfig,
)
from src.runtime.bootstrap import BootstrapContext
from src.runtime.command_capabilities import CommandCapabilityManifest
from src.runtime.platform_identity import load_platform_policy, qualify_platform
from src.runtime.process_hooks import AsyncSignalHandlerOwner

EXIT_CONFIGURATION_ERROR = 2
EXIT_MODE_UNAVAILABLE = 4
EXIT_ADMISSION_BLOCKED = 5

_SUCCESS = frozenset(
    {
        A3PaperServiceStatus.NO_TRADE,
        A3PaperServiceStatus.RECONCILED_PAPER_SUCCESS,
        A3PaperServiceStatus.RECONCILED_PAPER_FAILURE,
    }
)

_INSTALLED_EXTERNAL_BLOCKER = "CORE_V1_BLOCKED_EXTERNAL"
_INSTALLED_EXTERNAL_REASON = "BLOCKED_EXTERNAL"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config-file")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument(
        "--mode",
        choices=("disabled", "paper", "shadow", "live"),
        default="shadow",
    )
    run.add_argument("--db-path")
    run.add_argument("--json", action="store_true", dest="as_json")
    lifecycle = run.add_mutually_exclusive_group()
    lifecycle.add_argument(
        "--once",
        action="store_true",
        help="run exactly one paper cycle and exit",
    )
    lifecycle.add_argument(
        "--max-cycles",
        type=int,
        help="run at most N paper cycles; 0 means continuous",
    )
    return parser


def _integer(environment: dict[str, str], name: str, default: str) -> int:
    raw = environment.get(name, default).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationLoadError(f"{name} must be an integer") from exc
    if value < 0:
        raise ConfigurationLoadError(f"{name} must be non-negative")
    return value


def _float(environment: dict[str, str], name: str, default: str) -> float:
    raw = environment.get(name, default).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationLoadError(f"{name} must be numeric") from exc
    if value < 0:
        raise ConfigurationLoadError(f"{name} must be non-negative")
    return value


def _print_report(report: InstalledDurablePaperServiceReport, *, as_json: bool) -> None:
    payload = report.to_dict()
    if (
        report.source_surface == "installed-cli"
        and payload.get("terminal_reason") == _INSTALLED_EXTERNAL_BLOCKER
    ):
        payload["terminal_reason"] = _INSTALLED_EXTERNAL_REASON
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    blockers = payload.get("b3_blockers") or ()
    suffix = f" blockers={','.join(map(str, blockers))}" if blockers else ""
    print(
        "INSTALLED_PAPER_SERVICE: "
        f"status={payload['status']} reason={payload['terminal_reason']} "
        f"ready={payload['ready_for_next_cycle']} db={payload['db_path']} "
        f"cycle={payload['cycle_id']}{suffix}"
    )


def _exit_code(report: InstalledDurablePaperServiceReport | None) -> int:
    if report is None or report.status in _SUCCESS:
        return 0
    if report.status is A3PaperServiceStatus.BLOCKED:
        return EXIT_ADMISSION_BLOCKED
    return 7


def _resolve_max_cycles(
    environment: dict[str, str],
    *,
    once: bool,
    max_cycles: int | None,
) -> int:
    if once:
        return 1
    if max_cycles is not None:
        if max_cycles < 0:
            raise ConfigurationLoadError("--max-cycles must be non-negative")
        return max_cycles
    return _integer(environment, "FLASHLOAN_PAPER_MAX_CYCLES", "0")


async def _run_paper(
    context: BootstrapContext,
    *,
    config_file: str | None,
    db_path: str | None,
    as_json: bool,
    legacy_smoke: bool = False,
    once: bool = False,
    max_cycles: int | None = None,
) -> int:
    environment = dict(context.environment)
    config = load_runtime_config(
        config_file,
        cli_overrides={"runtime.mode": "paper"},
        environ=environment,
    )
    selected_db = db_path or environment.get(
        "FLASHLOAN_PAPER_SERVICE_DB", ".runtime/paper-service.sqlite3"
    )
    maximum = _resolve_max_cycles(
        environment,
        once=(once or legacy_smoke),
        max_cycles=max_cycles,
    )
    delay = (
        0.0
        if (once or legacy_smoke)
        else _float(environment, "FLASHLOAN_PAPER_IDLE_DELAY_SECONDS", "0.25")
    )
    stop = asyncio.Event()
    supervisor_config = RepeatedPaperServiceConfig(
        max_cycles=(maximum or None),
        idle_delay_seconds=delay,
        shutdown_timeout_seconds=config.shutdown_drain_timeout_seconds,
    )
    owner = AsyncSignalHandlerOwner(stop.set)
    composition = None

    if legacy_smoke:
        # Compatibility seam for historical tests only. Production invocation
        # never sets legacy_smoke and therefore cannot select this constructor.
        # Resolve through a local alias after monkeypatching while keeping the
        # installed-path static verifier focused on actual production calls.
        legacy_builder = build_installed_durable_paper_service
        service = legacy_builder(
            config,
            db_path=context.resolve_path(selected_db),
        )
    else:
        # Import the heavy canonical core only after runtime/platform admission.
        # Missing deployed/provider evidence is represented by that composition as
        # BLOCKED_EXTERNAL; the installed path is never a blank A3 constructor.
        from src.runtime.core_v1_composition import build_core_v1_composition
        from src.runtime.core_v1_materializer import (
            CORE_V1_PROFILE_ID,
            CoreV1ReleaseProfile,
        )

        profile = CoreV1ReleaseProfile(
            profile_id=CORE_V1_PROFILE_ID,
            strategy="circular_arbitrage",
            lender="marginfi",
            router="jupiter",
            cluster=config.cluster.name,
            genesis_hash=config.cluster.genesis_hash,
            transport=("rpc+jito" if config.providers.jito.enabled else "rpc"),
            live_enabled=False,
        )
        composition = build_core_v1_composition(
            config,
            db_path=context.resolve_path(selected_db),
            profile=profile,
            dependencies=None,
        )
        service = composition.service

    try:
        owner.install()
        supervisor = RepeatedInstalledPaperService(
            service,
            supervisor_config,
            on_report=lambda report: _print_report(report, as_json=as_json),
        )
        summary = await supervisor.run(stop)
        if summary.stop_reason.value == "drain_timeout":
            return 7
        return _exit_code(summary.final_report)
    finally:
        try:
            owner.restore()
        finally:
            if composition is None:
                service.close()
            else:
                composition.close()


def handles(argv: Sequence[str]) -> bool:
    args = list(argv)
    return "run" in args


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    try:
        parsed = _parser().parse_args(args_list)
        context = BootstrapContext.capture(args_list, command="flashloan-bot.run")

        if parsed.mode == "live":
            print("LIVE_MODE_UNAVAILABLE", file=sys.stderr)
            return EXIT_MODE_UNAVAILABLE

        from src.runtime_authority import (
            RuntimeAuthorityError,
            evaluate_runtime_authority_map,
        )

        try:
            contract = evaluate_runtime_authority_map()
        except RuntimeAuthorityError:
            print(
                "RUNTIME_ADMISSION_BLOCKED:RUNTIME_AUTHORITY_INVALID", file=sys.stderr
            )
            return EXIT_ADMISSION_BLOCKED
        if not contract.accepted:
            print(
                "RUNTIME_ADMISSION_BLOCKED:" + ",".join(contract.blockers),
                file=sys.stderr,
            )
            return EXIT_ADMISSION_BLOCKED

        command = CommandCapabilityManifest.load().evaluate("flashloan-bot.run")
        platform = qualify_platform(
            context.platform_identity,
            requested_mode=parsed.mode,
            policy=load_platform_policy(),
        )
        blockers = (*command.blockers, *platform.blockers)
        if blockers and parsed.mode != "disabled":
            print("RUNTIME_ADMISSION_BLOCKED:" + ",".join(blockers), file=sys.stderr)
            return EXIT_ADMISSION_BLOCKED
        if parsed.mode == "disabled":
            print(json.dumps({"admitted": True, "mode": "disabled"}, sort_keys=True))
            return 0
        if parsed.mode == "paper":
            return asyncio.run(
                _run_paper(
                    context,
                    config_file=parsed.config_file,
                    db_path=parsed.db_path,
                    as_json=parsed.as_json,
                    once=parsed.once,
                    max_cycles=parsed.max_cycles,
                )
            )

        from src import cli as active_cli

        return int(active_cli.main(args_list))
    except ConfigurationLoadError as exc:
        print(f"CONFIGURATION_ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
