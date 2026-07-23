"""Automation-safe installed CLI with dependency-light inspection dispatch.

MPR-CLOSE-01 keeps the installed ``flashloan-bot`` command usable even when
optional Solana execution dependencies are not importable.  Inspection commands
are handled here and import only configuration/capability modules.  Runtime
commands are imported lazily after dispatch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence

PAPER_DB_ENV = "FLASHLOAN_PAPER_SERVICE_DB"


def _rewrite_legacy_preflight(args: list[str]) -> list[str] | None:
    if not args:
        return None
    if args[0] == "paper-vertical-preflight":
        forwarded = ["paper-vertical", "check"]
        forwarded.extend(item for item in args[1:] if item != "--json")
        return forwarded
    return None


def _has_option(args: list[str], name: str) -> bool:
    return name in args or any(item.startswith(f"{name}=") for item in args)


def _canonical_paper_args(args: list[str]) -> list[str] | None:
    """Translate the installed ``run --mode paper`` surface to one paper root."""

    try:
        run_index = args.index("run")
    except ValueError:
        return None

    prefix = args[:run_index]
    tail = args[run_index + 1 :]
    forwarded: list[str] = []

    index = 0
    while index < len(prefix):
        item = prefix[index]
        if item == "--config-file":
            if index + 1 >= len(prefix):
                return None
            forwarded.extend((item, prefix[index + 1]))
            index += 2
            continue
        if item.startswith("--config-file="):
            forwarded.append(item)
            index += 1
            continue
        return None

    mode: str | None = None
    index = 0
    while index < len(tail):
        item = tail[index]
        if item == "--mode":
            if index + 1 >= len(tail):
                return None
            mode = tail[index + 1]
            index += 2
            continue
        if item.startswith("--mode="):
            mode = item.partition("=")[2]
            index += 1
            continue
        forwarded.append(item)
        index += 1

    if mode != "paper":
        return None
    if "--dry-run" in forwarded:
        forwarded.remove("--dry-run")
    if not _has_option(forwarded, "--db-path"):
        db_path = os.environ.get(PAPER_DB_ENV)
        if db_path:
            forwarded.extend(("--db-path", db_path))
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
        choices=("disabled", "paper", "shadow", "live"),
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


def _load_config(config_file: str | None, *, mode: str | None = None) -> Any:
    from src.config.runtime import load_runtime_config

    overrides: dict[str, Any] = {}
    if mode and mode != "live":
        overrides["runtime.mode"] = mode
    return load_runtime_config(config_file, cli_overrides=overrides or None, environ=os.environ)


def _capability_matrix() -> Any:
    from src.capabilities import CapabilityMatrix

    return CapabilityMatrix.load_default()


def _inspection_status_payload(config_file: str | None = None) -> dict[str, Any]:
    config = _load_config(config_file)
    matrix = _capability_matrix()
    path_errors = tuple(matrix.validate_paths())
    live_available = bool(matrix.runtime_modes.get("live", {}).get("available", False))
    return {
        "schema_version": "mpr-close-01.dependency-light-status.v1",
        "product_state": matrix.product_state,
        "supported_entrypoint": matrix.supported_entrypoint,
        "default_command": matrix.default_command,
        "capability_contract_valid": not path_errors,
        "capability_contract_errors": list(path_errors),
        # Preserve the historical installed-package smoke truth while avoiding
        # eager imports of src.cli/build_application/heavy runtime modules.
        "diagnostic": "NO_EXECUTABLE_STRATEGIES",
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
        "live_enabled": False,
        "live_available": live_available,
        "signer_loaded": False,
        "sender_loaded": False,
        "private_key_material_allowed": False,
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


def _run_config_doctor(args: argparse.Namespace) -> int:
    from src.config.doctor import run_config_doctor

    config = _load_config(args.config_file)
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
    return 0 if report.ok else 2


def _run_disabled_or_dry_mode(args: argparse.Namespace) -> int:
    payload = _inspection_status_payload(args.config_file)
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


def _run_lightweight_inspection(args: list[str]) -> int | None:
    """Handle commands that must not import heavy runtime modules before dispatch."""

    command_name = _inspection_command_name(args)
    if not args or command_name in {"--help", "-h"}:
        _inspection_parser().print_help()
        return 0
    if command_name not in {"status", "capabilities", "config", "run"}:
        return None

    try:
        parsed = _inspection_parser().parse_args(args)
    except SystemExit as exc:
        return int(exc.code)

    if parsed.command == "status":
        _print_status(
            _inspection_status_payload(parsed.config_file),
            as_json=parsed.as_json,
        )
        return 0
    if parsed.command == "capabilities":
        _print_capabilities(as_json=parsed.as_json)
        return 0
    if parsed.command == "config" and parsed.config_command == "doctor":
        return _run_config_doctor(parsed)
    if parsed.command == "run" and parsed.mode in {"disabled", "live"}:
        if parsed.mode == "live":
            print(
                "LIVE_MODE_UNAVAILABLE: live submission is hard-denied by the product contract.",
                file=sys.stderr,
            )
            return 4
        return _run_disabled_or_dry_mode(parsed)
    if parsed.command == "run" and parsed.dry_run and parsed.mode != "paper":
        return _run_disabled_or_dry_mode(parsed)
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    inspection_exit = _run_lightweight_inspection(args)
    if inspection_exit is not None:
        return inspection_exit

    canonical_paper_args = _canonical_paper_args(args)
    if canonical_paper_args is not None:
        from src.canonical_paper import cli as canonical_paper_cli

        return canonical_paper_cli.main(canonical_paper_args)

    if args and args[0] == "checks":
        from src import automation_cli_pr189

        return automation_cli_pr189.main(args[1:])
    if args and args[0] == "paper-vertical":
        from src import automation_cli_pr189

        return automation_cli_pr189.main(args)
    if args and args[0] == "readiness":
        from src import automation_cli_pr189

        return automation_cli_pr189.main(["production-debt", *args[1:]])
    if args and args[0] == "release-soak":
        from src import automation_cli_pr189

        return automation_cli_pr189.main(args)

    rewritten = _rewrite_legacy_preflight(args)
    if rewritten is not None:
        from src import automation_cli_pr189

        return automation_cli_pr189.main(rewritten)

    from src import cli as legacy_cli

    return legacy_cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
