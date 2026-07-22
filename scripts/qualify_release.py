#!/usr/bin/env python3
"""PR-186 qualification plan/executed-run/signed-verdict command.

Default invocation is inspection-only and can never authorize a release claim.
Execution requires an explicitly selected isolated interpreter, a hash-verified
production wheel/wheelhouse, and an attestation key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EXIT_BLOCKED = 3
EXIT_FAILED = 2


def _bootstrap_repo_imports() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile", action="append", default=None)
    parser.add_argument("--output", default=None, help="plan output path")
    parser.add_argument("--run-output", default=None)
    parser.add_argument("--verdict-output", default=None)
    parser.add_argument("--interpreter", default=None)
    parser.add_argument("--production-wheel", default=None)
    parser.add_argument("--wheelhouse-manifest", default=None)
    parser.add_argument("--attestation-key-file", default=None)
    parser.add_argument("--attestation-key-id", default=None)
    parser.add_argument("--repeated-run", default=None)
    parser.add_argument("--_under_selected_interpreter", action="store_true")
    return parser


def _write_or_print(payload: dict[str, Any], path: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path:
        Path(path).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def _reexec_if_needed(args: argparse.Namespace, original_argv: Sequence[str]) -> int | None:
    if not args.execute or args._under_selected_interpreter:
        return None
    if not args.interpreter:
        return None
    selected = Path(args.interpreter).resolve(strict=True)
    current = Path(sys.executable).resolve()
    if selected == current:
        return None
    forwarded = list(original_argv)
    forwarded.append("--_under_selected_interpreter")
    completed = subprocess.run([str(selected), str(Path(__file__).resolve()), *forwarded])
    return completed.returncode


def _load_wheelhouse_manifest(path: Path, wheelhouse: Path) -> tuple[str, list[Any]]:
    from src.qualification_pr186 import ArtifactIdentity, wheelhouse_manifest_hash

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("wheelhouse manifest requires a non-empty artifacts list")
    artifacts = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("wheelhouse artifact entry must be an object")
        filename = str(entry.get("filename", ""))
        expected = str(entry.get("sha256", ""))
        if not filename or len(expected) != 64:
            raise ValueError("wheelhouse artifact filename and sha256 are required")
        artifact = ArtifactIdentity.from_path(wheelhouse / filename)
        if artifact.sha256 != expected:
            raise ValueError(f"wheelhouse artifact hash mismatch: {filename}")
        artifacts.append(artifact)
    return wheelhouse_manifest_hash(artifacts), artifacts


def _profile_result(name: str, command: tuple[str, ...]) -> Any:
    from src.qualification_pr186 import ProfileExecutionResult, utc_now

    started_at = utc_now()
    started_ns = time.monotonic_ns()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=False,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    duration_ns = time.monotonic_ns() - started_ns
    return ProfileExecutionResult(
        name=name,
        command=command,
        started_at=started_at,
        finished_at=utc_now(),
        duration_ns=duration_ns,
        exit_code=completed.returncode,
        stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
        stdout_bytes=len(completed.stdout),
        stderr_bytes=len(completed.stderr),
    )


def _installed_import_leakage() -> bool:
    probe = (
        "import json, pathlib, src; "
        "print(json.dumps({'origin': str(pathlib.Path(src.__file__).resolve())}))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""},
    )
    if completed.returncode:
        return True
    origin = Path(json.loads(completed.stdout)["origin"])
    try:
        origin.relative_to(ROOT)
    except ValueError:
        return False
    return True


def _repeated_run_matches(run_payload: dict[str, Any], path: str | None) -> bool:
    if not path:
        return False
    other = json.loads(Path(path).read_text(encoding="utf-8"))
    comparable = (
        "source",
        "dependency_closure",
        "wheel",
        "wheelhouse_manifest_hash",
        "selected_profiles",
        "network_disabled_after_bootstrap",
        "source_import_leakage_detected",
    )
    if any(run_payload.get(key) != other.get(key) for key in comparable):
        return False
    first_profiles = [
        (item["name"], item["exit_code"], item["stdout_sha256"], item["stderr_sha256"])
        for item in run_payload.get("profiles", [])
    ]
    second_profiles = [
        (item["name"], item["exit_code"], item["stdout_sha256"], item["stderr_sha256"])
        for item in other.get("profiles", [])
    ]
    return first_profiles == second_profiles


def _dry_run(args: argparse.Namespace) -> int:
    _bootstrap_repo_imports()
    from src.qualification_pr176 import build_default_qualification_plan
    from src.qualification_pr186 import qualification_plan_document, source_tree_identity

    source = source_tree_identity(ROOT)
    plan = build_default_qualification_plan(ROOT)
    payload = qualification_plan_document(plan, source)
    _write_or_print(payload, args.output)
    return 0


def _execute(args: argparse.Namespace) -> int:
    missing_args = [
        name
        for name, value in (
            ("interpreter", args.interpreter),
            ("production-wheel", args.production_wheel),
            ("wheelhouse-manifest", args.wheelhouse_manifest),
            ("attestation-key-file", args.attestation_key_file),
            ("attestation-key-id", args.attestation_key_id),
            ("run-output", args.run_output),
            ("verdict-output", args.verdict_output),
        )
        if not value
    ]
    if missing_args:
        payload = {
            "schema_version": "pr186.qualification-execution-blocked.v1",
            "execution_mode": "execute",
            "qualified": False,
            "release_claim_allowed": False,
            "reason_codes": [f"missing_{name}" for name in missing_args],
        }
        _write_or_print(payload, args.output)
        return EXIT_BLOCKED

    from src.qualification_pr176 import build_default_qualification_plan
    from src.qualification_pr186 import (
        ArtifactIdentity,
        InterpreterIdentity,
        QualificationRun,
        create_signed_verdict,
        source_tree_identity,
        utc_now,
    )

    interpreter = InterpreterIdentity.capture()
    if not interpreter.isolated_environment or interpreter.global_site_packages_enabled:
        payload = {
            "schema_version": "pr186.qualification-execution-blocked.v1",
            "execution_mode": "execute",
            "qualified": False,
            "release_claim_allowed": False,
            "reason_codes": ["selected_interpreter_is_not_isolated"],
            "interpreter": interpreter.to_dict(),
        }
        _write_or_print(payload, args.output)
        return EXIT_BLOCKED

    wheel = ArtifactIdentity.from_path(Path(args.production_wheel))
    manifest_path = Path(args.wheelhouse_manifest).resolve(strict=True)
    wheelhouse_hash, _ = _load_wheelhouse_manifest(manifest_path, manifest_path.parent)
    source = source_tree_identity(ROOT)
    plan = build_default_qualification_plan(
        ROOT,
        global_site_packages=interpreter.global_site_packages_enabled,
        interpreter_executable=sys.executable,
    )
    selected = tuple(sorted(set(args.profile or plan.mandatory_profiles)))
    by_name = {profile.name: profile for profile in plan.profiles}
    unknown = sorted(set(selected).difference(by_name))
    if unknown:
        raise ValueError(f"unknown qualification profiles: {unknown}")

    started_at = utc_now()
    results = tuple(_profile_result(name, by_name[name].command) for name in selected)
    run = QualificationRun(
        run_id=uuid4().hex,
        plan_hash=plan.to_manifest(
            source_digest=source.digest,
            execution_mode="execute",
        )["manifest_hash"],
        source=source,
        interpreter=interpreter,
        dependency_closure=plan.dependency_closure,
        wheel=wheel,
        wheelhouse_manifest_hash=wheelhouse_hash,
        profiles=results,
        selected_profiles=selected,
        started_at=started_at,
        finished_at=utc_now(),
        environment_id=interpreter.identity_hash,
        network_disabled_after_bootstrap=True,
        source_import_leakage_detected=_installed_import_leakage(),
    )
    run_payload = run.to_dict()
    Path(args.run_output).write_text(
        json.dumps(run_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    repeated_match = _repeated_run_matches(run_payload, args.repeated_run)
    key = Path(args.attestation_key_file).read_bytes()
    verdict = create_signed_verdict(
        run,
        repeated_clean_run_match=repeated_match,
        signer_key_id=args.attestation_key_id,
        signing_key=key,
    )
    verdict_payload = verdict.to_dict()
    Path(args.verdict_output).write_text(
        json.dumps(verdict_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_or_print(
        {
            "schema_version": "pr186.qualification-command-result.v1",
            "execution_mode": "execute",
            "run": run_payload,
            "verdict": verdict_payload,
            "qualified": verdict.qualified,
            "release_claim_allowed": verdict.release_claim_allowed,
        },
        args.output,
    )
    return 0 if verdict.release_claim_allowed else EXIT_BLOCKED


def main(argv: Sequence[str] | None = None) -> int:
    original = list(argv) if argv is not None else sys.argv[1:]
    args = _parser().parse_args(original)
    reexec = _reexec_if_needed(args, original)
    if reexec is not None:
        return reexec
    try:
        return _execute(args) if args.execute else _dry_run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": "pr186.qualification-command-error.v1",
            "qualified": False,
            "release_claim_allowed": False,
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }
        _write_or_print(payload, args.output)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
