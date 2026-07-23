"""PR-189 shared inspection/check command for readiness and evidence surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.cli_contract_pr189 import (
    CommandMode,
    CommandResult,
    CommandVerdict,
    error_result,
    result,
)


def _mode(value: str) -> CommandMode:
    return CommandMode(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashloan-checks",
        description="Run versioned PR-189 inspection or enforcing checks.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    paper = commands.add_parser("paper-vertical")
    paper.add_argument("mode", choices=("inspect", "check"))
    paper.add_argument("--config-file", default=None)

    debt = commands.add_parser("production-debt")
    debt.add_argument("mode", choices=("inspect", "check"))

    provider = commands.add_parser("provider-readiness")
    provider.add_argument("mode", choices=("inspect", "check"))
    provider.add_argument("--enable-online", action="store_true")
    provider.add_argument("--provider", action="append", default=None)

    soak = commands.add_parser("release-soak")
    soak.add_argument("mode", choices=("inspect", "check"))
    soak.add_argument("--manifest", required=True)

    qualification = commands.add_parser("qualification-verdict")
    qualification.add_argument("mode", choices=("inspect", "check"))
    qualification.add_argument("--verdict", required=True)
    qualification.add_argument("--attestation-key-file", required=True)

    return parser


def _reason_codes_from_blockers(blockers: Any) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(blockers, Mapping):
        blockers = tuple(blockers.values())
    if not isinstance(blockers, (list, tuple)):
        blockers = (blockers,)
    for blocker in blockers:
        if isinstance(blocker, str):
            values.append(blocker)
        elif isinstance(blocker, Mapping):
            value = (
                blocker.get("reason_code")
                or blocker.get("id")
                or blocker.get("code")
            )
            values.append(str(value or "PR189_BLOCKED"))
        else:
            value = (
                getattr(blocker, "reason_code", None)
                or getattr(blocker, "id", None)
            )
            values.append(str(value or "PR189_BLOCKED"))
    return tuple(dict.fromkeys(values))


def _dependency_unavailable_result(
    *,
    command: str,
    mode: CommandMode,
    exc: ImportError,
) -> CommandResult:
    missing = getattr(exc, "name", None) or type(exc).__name__
    return result(
        command=command,
        mode=mode,
        ready=False,
        verdict=CommandVerdict.UNAVAILABLE,
        reason_codes=("PR189_DEPENDENCY_UNAVAILABLE",),
        details={"error_type": type(exc).__name__, "dependency": str(missing)},
    )


def evaluate_paper_vertical(
    mode: CommandMode,
    config_file: str | None,
) -> CommandResult:
    from src.cli import load_configuration
    from src.paper_shadow import PaperShadowRuntimeDependencies
    from src.paper_shadow.a1_vertical_preflight import evaluate_paper_vertical_a1

    config = load_configuration(config_file)
    report = evaluate_paper_vertical_a1(config, PaperShadowRuntimeDependencies())
    payload = report.to_dict()
    ready = bool(payload["ready"])
    reasons = () if ready else (str(payload["reason_code"]),)
    return result(
        command="paper-vertical",
        mode=mode,
        ready=ready,
        reason_codes=reasons,
        details=payload,
    )


def evaluate_production_debt_command(mode: CommandMode) -> CommandResult:
    from src.production_debt import evaluate_production_debt

    report = evaluate_production_debt()
    payload = report.to_dict()
    consistency = tuple(str(item) for item in payload.get("consistency_errors", ()))
    if consistency:
        return result(
            command="production-debt",
            mode=mode,
            ready=False,
            verdict=CommandVerdict.ERROR,
            reason_codes=tuple(f"CONSISTENCY_ERROR:{item}" for item in consistency),
            details=payload,
        )
    ready = bool(payload.get("production_ready", False))
    reasons = () if ready else _reason_codes_from_blockers(payload.get("blockers", ()))
    return result(
        command="production-debt",
        mode=mode,
        ready=ready,
        reason_codes=reasons or ("PRODUCTION_READINESS_BLOCKED",),
        details=payload,
    )


def evaluate_provider_readiness(
    mode: CommandMode,
    *,
    providers: Sequence[str] | None,
    enable_online: bool,
) -> CommandResult:
    from src.external_contracts.provider_protocol_b1 import (
        DEFAULT_B1_PROVIDERS,
        evaluate_b1_provider_protocol_readiness,
    )
    from src.external_contracts.registry import ExternalContractRegistry

    report = evaluate_b1_provider_protocol_readiness(
        ExternalContractRegistry.load_default(),
        providers=tuple(providers or DEFAULT_B1_PROVIDERS),
        enable_online=enable_online,
    )
    payload = report.to_dict()
    reasons: list[str] = []
    for provider in payload["providers"]:
        reasons.extend(
            f"{provider['provider']}:{blocker}" for blocker in provider["blockers"]
        )
    return result(
        command="provider-readiness",
        mode=mode,
        ready=bool(report.paper_vertical_ready),
        reason_codes=tuple(reasons),
        details=payload,
    )


def evaluate_release_soak(mode: CommandMode, manifest: str) -> CommandResult:
    from src.release_soak_artifacts_d2 import (
        bundle_from_manifest,
        render_bundle_json,
    )

    manifest_path = Path(manifest)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = bundle_from_manifest(data, base_dir=manifest_path.parent)
    payload = json.loads(render_bundle_json(bundle))
    blockers = tuple(str(item) for item in bundle.blockers())
    return result(
        command="release-soak",
        mode=mode,
        ready=not blockers,
        reason_codes=blockers,
        details=payload,
    )


def evaluate_qualification_verdict(
    mode: CommandMode,
    verdict_path: str,
    key_path: str,
) -> CommandResult:
    from src.qualification_pr186 import (
        PR186_VERDICT_SCHEMA,
        QualificationVerdict,
        verify_signed_verdict,
    )

    payload = json.loads(Path(verdict_path).read_text(encoding="utf-8"))
    required = {
        "run_hash",
        "source_digest",
        "wheel_sha256",
        "qualified",
        "reason_codes",
        "repeated_clean_run_match",
        "signer_key_id",
        "signature_algorithm",
        "signature",
        "issued_at",
    }
    missing = sorted(required.difference(payload))
    if missing:
        return result(
            command="qualification-verdict",
            mode=mode,
            ready=False,
            verdict=CommandVerdict.ERROR,
            reason_codes=tuple(f"MISSING_FIELD:{item}" for item in missing),
            details={"schema_version": payload.get("schema_version")},
        )
    if payload.get("schema_version") != PR186_VERDICT_SCHEMA:
        return result(
            command="qualification-verdict",
            mode=mode,
            ready=False,
            verdict=CommandVerdict.ERROR,
            reason_codes=("QUALIFICATION_VERDICT_SCHEMA_MISMATCH",),
            details={"schema_version": payload.get("schema_version")},
        )
    verdict = QualificationVerdict(
        run_hash=str(payload["run_hash"]),
        source_digest=str(payload["source_digest"]),
        wheel_sha256=str(payload["wheel_sha256"]),
        qualified=bool(payload["qualified"]),
        reason_codes=tuple(map(str, payload["reason_codes"])),
        repeated_clean_run_match=bool(payload["repeated_clean_run_match"]),
        signer_key_id=str(payload["signer_key_id"]),
        signature_algorithm=str(payload["signature_algorithm"]),
        signature=str(payload["signature"]),
        issued_at=str(payload["issued_at"]),
    )
    signature_valid = verify_signed_verdict(verdict, Path(key_path).read_bytes())
    ready = bool(verdict.release_claim_allowed and signature_valid)
    reasons = list(verdict.reason_codes)
    if not signature_valid:
        reasons.append("QUALIFICATION_VERDICT_SIGNATURE_INVALID")
    if not verdict.qualified:
        reasons.append("QUALIFICATION_NOT_EXECUTED_READY")
    return result(
        command="qualification-verdict",
        mode=mode,
        ready=ready,
        reason_codes=tuple(reasons),
        details={
            "schema_version": verdict.schema_version,
            "qualified": verdict.qualified,
            "release_claim_allowed": verdict.release_claim_allowed,
            "signature_valid": signature_valid,
            "run_hash": verdict.run_hash,
            "source_digest": verdict.source_digest,
            "wheel_sha256": verdict.wheel_sha256,
            "signer_key_id": verdict.signer_key_id,
            "issued_at": verdict.issued_at,
        },
    )


def _evaluate(args: argparse.Namespace) -> CommandResult:
    mode = _mode(args.mode)
    if args.command == "paper-vertical":
        return evaluate_paper_vertical(mode, args.config_file)
    if args.command == "production-debt":
        return evaluate_production_debt_command(mode)
    if args.command == "provider-readiness":
        return evaluate_provider_readiness(
            mode,
            providers=args.provider,
            enable_online=args.enable_online,
        )
    if args.command == "release-soak":
        return evaluate_release_soak(mode, args.manifest)
    if args.command == "qualification-verdict":
        return evaluate_qualification_verdict(
            mode,
            args.verdict,
            args.attestation_key_file,
        )
    raise ValueError("unsupported PR-189 command")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    mode = _mode(args.mode)
    try:
        command_result = _evaluate(args)
    except ImportError as exc:
        command_result = _dependency_unavailable_result(
            command=str(args.command),
            mode=mode,
            exc=exc,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        command_result = error_result(
            command=str(args.command),
            mode=mode,
            reason_code="PR189_COMMAND_INPUT_OR_RUNTIME_ERROR",
            error_type=type(exc).__name__,
        )
    print(json.dumps(command_result.to_dict(), indent=2, sort_keys=True))
    return command_result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
