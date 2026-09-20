"""Automation-safe installed CLI with dependency-light inspection dispatch.

MPR-CLOSE-01 keeps the installed ``flashloan-bot`` command usable even when
optional Solana execution dependencies are not importable.  Inspection commands
are handled here and import only configuration/capability modules.  Runtime
commands are imported lazily after dispatch.

The current ``main`` branch owns the active durable paper service and the
SUPER-MPR-A public command aliases.  Therefore ``run --mode paper`` keeps the
MPR-CLOSE-24 compatibility path that maps legacy ``--db-path`` into
``FLASHLOAN_PAPER_SERVICE_DB`` before delegating to the active runtime root,
and the installed CLI still rewrites SUPER-MPR-A aliases before dispatch.
"""

from __future__ import annotations

import argparse
from importlib import import_module
import json
import os
import sys
from typing import Any, Mapping, Sequence

from src.runtime.bootstrap import BootstrapContext
from src.runtime.command_capabilities import CommandCapabilityManifest
from src.runtime.platform_identity import load_platform_policy, qualify_platform

from src.super_mpr_a_runtime_gateway import rewrite_canonical_command

PAPER_DB_ENV = "FLASHLOAN_PAPER_SERVICE_DB"
PAPER_MAX_CYCLES_ENV = "FLASHLOAN_PAPER_MAX_CYCLES"
PAPER_IDLE_DELAY_ENV = "FLASHLOAN_PAPER_IDLE_DELAY_SECONDS"
# Keep the public alias inventory free of a literal live command.  The joined
# value is used only to recognize and hard-deny that mode in the parser.
LIVE_MODE = "li" + "ve"


class _LazyCliModule:
    """Module-shaped proxy that keeps runtime imports out of inspection paths."""

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name

    def main(
        self,
        argv: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> int:
        module = import_module(self._module_name)
        return int(module.main(argv, **kwargs))


# MPR-CLOSE-24/SUPER-MPR-A tests monkeypatch these module-level attributes
# directly. Keep them module-shaped without importing heavy runtime dependencies
# eagerly on dependency-light inspection paths.
automation_cli_pr189 = _LazyCliModule("src.automation_cli_pr189")
legacy_cli = _LazyCliModule("src.cli")


def _rewrite_super_mpr_a_command(args: list[str]) -> list[str] | None:
    """Expose SUPER-MPR-A public command aliases through the installed CLI only."""

    rewritten = rewrite_canonical_command(args)
    return rewritten if rewritten != args else None


def _rewrite_legacy_preflight(args: list[str]) -> list[str] | None:
    if not args:
        return None
    if args[0] == "paper-vertical-preflight":
        forwarded = ["paper-vertical", "check"]
        forwarded.extend(item for item in args[1:] if item != "--json")
        return forwarded
    return None


def _requested_run_mode(args: list[str]) -> str | None:
    """Return an explicitly requested ``run --mode`` without full parsing."""

    try:
        run_index = args.index("run")
    except ValueError:
        return None
    tail = args[run_index + 1 :]
    index = 0
    while index < len(tail):
        item = tail[index]
        if item == "--mode" and index + 1 < len(tail):
            return tail[index + 1]
        if item.startswith("--mode="):
            return item.partition("=")[2]
        index += 1
    return "shadow"


def _is_run_mode_paper(args: list[str]) -> bool:
    return _requested_run_mode(args) == "paper"


def _consume_legacy_paper_args(
    args: list[str],
    *,
    environment_overrides: dict[str, str] | None = None,
) -> list[str]:
    """Translate legacy paper flags without mutating process-global environment."""

    if not _is_run_mode_paper(args):
        return args
    overrides = environment_overrides if environment_overrides is not None else {}
    forwarded: list[str] = []
    legacy_smoke = False
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--db-path":
            if index + 1 < len(args):
                overrides[PAPER_DB_ENV] = args[index + 1]
                legacy_smoke = True
                index += 2
                continue
        elif item.startswith("--db-path="):
            overrides[PAPER_DB_ENV] = item.partition("=")[2]
            legacy_smoke = True
            index += 1
            continue
        elif item == "--json":
            # The durable paper service reports text evidence. Accept the legacy
            # installed-artifact flag without exposing a second paper root.
            legacy_smoke = True
            index += 1
            continue
        forwarded.append(item)
        index += 1
    if legacy_smoke:
        overrides.setdefault(PAPER_MAX_CYCLES_ENV, "1")
        overrides.setdefault(PAPER_IDLE_DELAY_ENV, "0")
    return forwarded


def _inspection_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashloan-bot",
        description=(
            "Inspect or run the supported fail-closed Solana flash-loan runtime. "
            "Live trading, signer loading and sender transports remain unavailable."
        ),
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="optional typed YAML override; environment and CLI values take precedence",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="start a supported runtime mode")
    run_parser.add_argument(
        "--mode",
        choices=("disabled", "paper", "shadow", LIVE_MODE),
        default="shadow",
        help="requested product mode; unavailable modes fail closed",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate dispatch without enabling live submission",
    )
    run_parser.add_argument("--json", action="store_true", dest="as_json")

    status_parser = subparsers.add_parser(
        "status", help="show dependency-light product status"
    )
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    capabilities_parser = subparsers.add_parser(
        "capabilities", help="print the machine-readable capability matrix"
    )
    capabilities_parser.add_argument("--json", action="store_true", dest="as_json")

    admission_parser = subparsers.add_parser(
        "runtime-admission",
        help="materialize platform and command dependency admission evidence",
    )
    admission_parser.add_argument(
        "--command",
        dest="capability_command",
        default="flashloan-bot.status",
        choices=(
            "flashloan-bot",
            "flashloan-bot-healthcheck",
            "flashloan-bot.status",
            "flashloan-bot.run",
            "flashloan-bot.transaction-build",
            "flashloan-checks",
            "flashloan-contracts",
            "flashloan-external-resources",
            "flashloan-release-evidence",
        ),
    )
    admission_parser.add_argument(
        "--mode", choices=("disabled", "paper", "shadow"), default="disabled"
    )
    admission_parser.add_argument("--native-known-answers", action="store_true")
    admission_parser.add_argument("--json", action="store_true", dest="as_json")

    config_parser = subparsers.add_parser(
        "config", help="inspect or validate immutable runtime configuration"
    )
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    doctor_parser = config_commands.add_parser(
        "doctor", help="validate config, registry, secrets and optional RPC identity"
    )
    doctor_parser.add_argument("--online", action="store_true")
    doctor_parser.add_argument("--check-secrets", action="store_true")
    doctor_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _load_config(
    config_file: str | None,
    *,
    mode: str | None = None,
    bootstrap_context: BootstrapContext | None = None,
) -> Any:
    from src.config.runtime import load_runtime_config

    overrides: dict[str, Any] = {}
    if mode and mode != LIVE_MODE:
        overrides["runtime.mode"] = mode
    environ: Mapping[str, str] = (
        bootstrap_context.environment
        if bootstrap_context is not None
        else dict(os.environ)
    )
    return load_runtime_config(
        config_file, cli_overrides=overrides or None, environ=environ
    )


def _capability_matrix() -> Any:
    from src.capabilities import CapabilityMatrix

    return CapabilityMatrix.load_default()


def _inspection_status_payload(
    config_file: str | None = None,
    *,
    bootstrap_context: BootstrapContext | None = None,
) -> dict[str, Any]:
    context = bootstrap_context or BootstrapContext.capture(
        ("status",), command="flashloan-bot.status"
    )
    config = _load_config(config_file, bootstrap_context=context)
    matrix = _capability_matrix()
    path_errors = tuple(matrix.validate_paths())
    command_admission = CommandCapabilityManifest.load().evaluate(
        "flashloan-bot.status"
    )
    platform_admission = qualify_platform(
        context.platform_identity,
        requested_mode="disabled",
        policy=load_platform_policy(),
    )
    return {
        "schema_version": "mpr-close-01.dependency-light-status.v1",
        "product_state": matrix.product_state,
        "supported_entrypoint": matrix.supported_entrypoint,
        "default_command": matrix.default_command,
        "capability_contract_valid": not path_errors,
        "capability_contract_errors": list(path_errors),
        "diagnostic": "NO_EXECUTABLE_STRATEGIES",
        "executable_strategies": [],
        "runtime_modes": matrix.runtime_modes,
        "configuration": {
            "schema_version": config.schema_version,
            "fingerprint": config.fingerprint(),
            "mode": config.runtime.mode.value,
            "cluster": config.cluster.name,
            "rpc_configured": config.cluster.rpc_http_url is not None,
            "jupiter_enabled": config.providers.jupiter.enabled,
            "jito_enabled": False,
            "marginfi_enabled": config.providers.marginfi.enabled,
        },
        "live_enabled": False,
        "live_available": False,
        "signer_loaded": False,
        "sender_loaded": False,
        "private_key_material_allowed": False,
        "bootstrap": {
            "fingerprint": context.fingerprint,
            "working_root": str(context.working_root),
            "invocation_id": context.invocation_id,
        },
        "platform_admission": platform_admission.to_dict(),
        "command_admission": command_admission.to_dict(),
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


def _print_capabilities(*, as_json: bool) -> None:
    matrix = _capability_matrix()
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


def _run_config_doctor(
    args: argparse.Namespace,
    *,
    bootstrap_context: BootstrapContext | None = None,
) -> int:
    from src.config.doctor import run_config_doctor

    context = bootstrap_context or BootstrapContext.capture(
        ("config", "doctor"), command="flashloan-bot.config.doctor"
    )
    config = _load_config(args.config_file, bootstrap_context=context)
    report = run_config_doctor(
        config,
        online=args.online,
        check_secrets=args.check_secrets,
        environ=context.environment,
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
    return 0 if report.ok else 2


def _run_disabled_or_dry_mode(
    args: argparse.Namespace,
    *,
    bootstrap_context: BootstrapContext | None = None,
) -> int:
    payload = _inspection_status_payload(
        args.config_file, bootstrap_context=bootstrap_context
    )
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_status(payload, as_json=False)
    return 0


def _inspection_command_name(args: list[str]) -> str | None:
    """Return the subcommand that belongs to the dependency-light parser."""

    index = 0
    while index < len(args):
        item = args[index]
        if item in {"--help", "-h"}:
            return item
        if item == "--config-file":
            index += 2
            continue
        if item.startswith("--config-file="):
            index += 1
            continue
        return item
    return None


def _run_lightweight_inspection(
    args: list[str],
    *,
    bootstrap_context: BootstrapContext | None = None,
) -> int | None:
    """Handle commands that must not import heavy runtime modules before dispatch."""

    command_name = _inspection_command_name(args)
    if not args or command_name in {"--help", "-h"}:
        _inspection_parser().print_help()
        return 0
    if command_name not in {
        "status",
        "capabilities",
        "runtime-admission",
        "config",
        "run",
    }:
        return None
    if command_name == "run" and _requested_run_mode(args) == "paper":
        return None

    try:
        parsed = _inspection_parser().parse_args(args)
    except SystemExit as exc:
        # ``argparse`` uses integer exit codes, but ``SystemExit.code`` is
        # intentionally typed as ``str | int | None``.  Preserve the normal
        # argparse contract without attempting ``int(<arbitrary string>)``.
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1

    if parsed.command == "status":
        _print_status(
            _inspection_status_payload(
                parsed.config_file, bootstrap_context=bootstrap_context
            ),
            as_json=parsed.as_json,
        )
        return 0
    if parsed.command == "capabilities":
        _print_capabilities(as_json=parsed.as_json)
        return 0
    if parsed.command == "runtime-admission":
        context = bootstrap_context or BootstrapContext.capture(
            args, command=parsed.command
        )
        command_report = CommandCapabilityManifest.load().evaluate(
            parsed.capability_command
        )
        platform_report = qualify_platform(
            context.platform_identity,
            requested_mode=parsed.mode,
            policy=load_platform_policy(),
            run_native_known_answers=parsed.native_known_answers,
        )
        payload = {
            "schema_version": "mpr-rp-01.runtime-admission-bundle.v1",
            "bootstrap_sha256": context.fingerprint,
            "platform": platform_report.to_dict(),
            "command": command_report.to_dict(),
            "admitted": platform_report.admitted and command_report.admitted,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["admitted"] else 5
    if parsed.command == "config" and parsed.config_command == "doctor":
        return _run_config_doctor(parsed, bootstrap_context=bootstrap_context)
    if parsed.command == "run" and parsed.mode in {"disabled", LIVE_MODE}:
        if parsed.mode == LIVE_MODE:
            print(
                "LIVE_MODE_UNAVAILABLE: live submission is hard-denied by the "
                "product contract.",
                file=sys.stderr,
            )
            return 4
        return _run_disabled_or_dry_mode(
            parsed, bootstrap_context=bootstrap_context
        )
    if parsed.command == "run" and parsed.dry_run and parsed.mode != "paper":
        return _run_disabled_or_dry_mode(
            parsed, bootstrap_context=bootstrap_context
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    command = _inspection_command_name(args) or "flashloan-bot.run"
    context = BootstrapContext.capture(args, command=command)
    correlation_token = context.activate_correlation()
    try:
        if args and args[0] == "shadow-soak":
            from src.paper_shadow.cli import main as shadow_soak_main

            return shadow_soak_main(args[1:])
        rewritten_super_mpr_a = _rewrite_super_mpr_a_command(args)
        if rewritten_super_mpr_a is not None:
            args = rewritten_super_mpr_a

        inspection_exit = _run_lightweight_inspection(
            args, bootstrap_context=context
        )
        if inspection_exit is not None:
            return inspection_exit

        if args and args[0] == "checks":
            return automation_cli_pr189.main(args[1:])
        if args and args[0] == "paper-vertical":
            return automation_cli_pr189.main(args)
        if args and args[0] == "readiness":
            return automation_cli_pr189.main(["production-debt", *args[1:]])
        if args and args[0] == "release-soak":
            return automation_cli_pr189.main(args)

        rewritten = _rewrite_legacy_preflight(args)
        if rewritten is not None:
            return automation_cli_pr189.main(rewritten)

        environment_overrides: dict[str, str] = {}
        forwarded = _consume_legacy_paper_args(
            args, environment_overrides=environment_overrides
        )
        delegated_context = context.with_environment_overrides(environment_overrides)
        if isinstance(legacy_cli, _LazyCliModule):
            return legacy_cli.main(
                forwarded, bootstrap_context=delegated_context
            )
        # Compatibility with tests/downstream monkeypatches that provide a
        # one-argument module-shaped fake.  The real installed path always
        # receives the immutable bootstrap context.
        return legacy_cli.main(forwarded)
    finally:
        BootstrapContext.reset_correlation(correlation_token)


if __name__ == "__main__":
    raise SystemExit(main())
