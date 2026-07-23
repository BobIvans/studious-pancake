"""MPR-01 installed artifact parity and sender-free paper surface checks.

This module is intentionally dependency-light: it can validate a collected command
surface manifest without importing the Solana runtime, provider adapters, signer,
or sender packages.  The companion ``scripts/verify_installed_artifact.py`` can
collect a source/installed command surface and feed it back through this
fail-closed evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "mpr-01.installed-artifact-parity.v1"
CANONICAL_ENTRYPOINT = "src.cli_pr189:main"

REQUIRED_COMMANDS: dict[str, tuple[str, ...]] = {
    "help": ("--help",),
    "status": ("status", "--json"),
    "capabilities": ("capabilities", "--json"),
    "config_doctor": ("config", "doctor", "--json"),
    "canonical_paper_cycle": (
        "run",
        "--mode",
        "paper",
        "--db-path",
        "{paper_db_path}",
        "--json",
    ),
}

EXPECTED_EXIT_CODES: dict[str, frozenset[int]] = {
    "help": frozenset({0}),
    "status": frozenset({0}),
    "capabilities": frozenset({0}),
    "config_doctor": frozenset({0}),
    "canonical_paper_cycle": frozenset({0}),
}

FORBIDDEN_TRUE_KEYS = frozenset(
    {
        "live_enabled",
        "live_available",
        "live_execution_allowed",
        "live_trading_enabled",
        "jito_enabled",
        "signer_loaded",
        "signer_allowed",
        "sender_loaded",
        "sender_allowed",
        "private_key_material_allowed",
    }
)

FORBIDDEN_TEXT_MARKERS = (
    "live=true",
    "signer=true",
    "sender=true",
    "LIVE_TRADING_ENABLED=true",
    "JITO_ENABLED=true",
)

MAX_CAPTURE_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class InstalledArtifactViolation:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class CommandObservation:
    name: str
    argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_text: str = ""
    stderr_text: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CommandObservation":
        return cls(
            name=str(payload.get("name", "")),
            argv=tuple(str(item) for item in payload.get("argv", ())),
            exit_code=_strict_int(payload.get("exit_code"), "exit_code"),
            stdout_sha256=str(payload.get("stdout_sha256", "")),
            stderr_sha256=str(payload.get("stderr_sha256", "")),
            stdout_text=str(payload.get("stdout_text", "")),
            stderr_text=str(payload.get("stderr_text", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_text": self.stdout_text,
            "stderr_text": self.stderr_text,
        }


@dataclass(frozen=True, slots=True)
class InstalledArtifactReport:
    ok: bool
    reason_code: str
    command_surface_digest: str
    evidence_digest: str
    violations: tuple[InstalledArtifactViolation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": self.ok,
            "reason_code": self.reason_code,
            "command_surface_digest": self.command_surface_digest,
            "evidence_digest": self.evidence_digest,
            "violations": [item.to_dict() for item in self.violations],
            "live_enabled": False,
            "signer_loaded": False,
            "sender_loaded": False,
        }


def evaluate_installed_artifact_evidence(
    evidence: Mapping[str, Any],
) -> InstalledArtifactReport:
    """Validate one source/installed command-surface parity evidence bundle.

    The evaluator is deliberately conservative.  It accepts only the MPR-01
    sender-free command set and fails closed on any live/signer/sender/Jito
    promotion claim.
    """

    violations: list[InstalledArtifactViolation] = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        violations.append(
            InstalledArtifactViolation(
                "MPR01_SCHEMA_VERSION",
                f"expected schema_version={SCHEMA_VERSION}",
            )
        )

    _validate_entrypoint_contract(evidence, violations)
    observations = _parse_observations(evidence, violations)
    _validate_required_commands(observations, violations)

    runtime_claims = evidence.get("runtime_claims", {})
    if isinstance(runtime_claims, Mapping):
        _scan_for_forbidden_true(runtime_claims, "runtime_claims", violations)
    else:
        violations.append(
            InstalledArtifactViolation(
                "MPR01_RUNTIME_CLAIMS_INVALID",
                "runtime_claims must be an object",
            )
        )

    command_surface_digest = _hash_json(
        {
            "schema_version": SCHEMA_VERSION,
            "commands": [item.to_dict() for item in observations],
        }
    )
    evidence_digest = _hash_json(
        {
            "schema_version": SCHEMA_VERSION,
            "entrypoint": evidence.get("entrypoint", {}),
            "runtime_claims": runtime_claims if isinstance(runtime_claims, Mapping) else {},
            "command_surface_digest": command_surface_digest,
        }
    )
    ok = not violations
    return InstalledArtifactReport(
        ok=ok,
        reason_code=(
            "mpr01_installed_artifact_parity_verified"
            if ok
            else "mpr01_installed_artifact_parity_blocked"
        ),
        command_surface_digest=command_surface_digest,
        evidence_digest=evidence_digest,
        violations=tuple(violations),
    )


def collect_source_checkout_evidence(
    project_root: Path,
    *,
    command: Sequence[str] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Collect the MPR-01 command surface from source or installed command.

    When ``command`` is omitted, the collector executes the source checkout via
    ``python -m src.cli_pr189``.  Passing ``["flashloan-bot"]`` collects the same
    contract through an installed console script.
    """

    root = project_root.resolve()
    base_command = tuple(command or (sys.executable, "-m", "src.cli_pr189"))
    pyproject = _read_pyproject(root)

    with tempfile.TemporaryDirectory(prefix="mpr01-paper-") as tmpdir:
        paper_db_path = str(Path(tmpdir) / "canonical-paper.sqlite3")
        observations = [
            _run_command(
                name=name,
                argv=_materialize_args(args, paper_db_path=paper_db_path),
                base_command=base_command,
                project_root=root,
                timeout_seconds=timeout_seconds,
            )
            for name, args in REQUIRED_COMMANDS.items()
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "collector": {
            "mode": "installed-command" if command else "source-checkout",
            "base_command": list(base_command),
            "python": sys.executable,
        },
        "entrypoint": {
            "flashloan-bot": pyproject.get("project", {})
            .get("scripts", {})
            .get("flashloan-bot"),
            "root_wrapper_target": _read_root_wrapper_target(root),
            "source_main_target": CANONICAL_ENTRYPOINT,
            "package_excludes": pyproject.get("tool", {})
            .get("setuptools", {})
            .get("packages", {})
            .get("find", {})
            .get("exclude", ()),
        },
        "runtime_claims": _derive_runtime_claims(observations),
        "command_observations": [item.to_dict() for item in observations],
    }


def _validate_entrypoint_contract(
    evidence: Mapping[str, Any],
    violations: list[InstalledArtifactViolation],
) -> None:
    entrypoint = evidence.get("entrypoint")
    if not isinstance(entrypoint, Mapping):
        violations.append(
            InstalledArtifactViolation(
                "MPR01_ENTRYPOINT_MISSING",
                "entrypoint contract is required",
            )
        )
        return

    for key in ("flashloan-bot", "root_wrapper_target", "source_main_target"):
        if entrypoint.get(key) != CANONICAL_ENTRYPOINT:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_ENTRYPOINT_DRIFT",
                    f"{key} must resolve to {CANONICAL_ENTRYPOINT}",
                )
            )

    excludes = tuple(str(item) for item in entrypoint.get("package_excludes", ()))
    if not any(item == "src.execution.senders*" for item in excludes):
        violations.append(
            InstalledArtifactViolation(
                "MPR01_SENDER_NAMESPACE_NOT_EXCLUDED",
                "sender namespace must remain excluded from the sender-free wheel",
            )
        )


def _parse_observations(
    evidence: Mapping[str, Any],
    violations: list[InstalledArtifactViolation],
) -> tuple[CommandObservation, ...]:
    raw = evidence.get("command_observations", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        violations.append(
            InstalledArtifactViolation(
                "MPR01_COMMAND_OBSERVATIONS_INVALID",
                "command_observations must be a sequence",
            )
        )
        return ()
    observations: list[CommandObservation] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_COMMAND_OBSERVATION_INVALID",
                    f"command_observations[{index}] must be an object",
                )
            )
            continue
        try:
            observations.append(CommandObservation.from_mapping(item))
        except (TypeError, ValueError) as exc:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_COMMAND_OBSERVATION_INVALID",
                    f"command_observations[{index}] is invalid: {exc}",
                )
            )
    return tuple(observations)


def _validate_required_commands(
    observations: tuple[CommandObservation, ...],
    violations: list[InstalledArtifactViolation],
) -> None:
    by_name: dict[str, CommandObservation] = {}
    for item in observations:
        if item.name in by_name:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_DUPLICATE_COMMAND",
                    f"duplicate observation for {item.name}",
                )
            )
            continue
        by_name[item.name] = item

    for name, expected_argv in REQUIRED_COMMANDS.items():
        observation = by_name.get(name)
        if observation is None:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_COMMAND_MISSING",
                    f"missing command observation {name}",
                )
            )
            continue

        normalized_expected = tuple(
            "{paper_db_path}" if item == "{paper_db_path}" else item
            for item in expected_argv
        )
        normalized_observed = tuple(
            "{paper_db_path}" if _looks_like_paper_db_path(item) else item
            for item in observation.argv
        )
        if normalized_observed != normalized_expected:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_COMMAND_ARGV_DRIFT",
                    f"{name} argv drifted: {observation.argv!r}",
                )
            )
        if observation.exit_code not in EXPECTED_EXIT_CODES[name]:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_COMMAND_EXIT_CODE",
                    f"{name} returned {observation.exit_code}",
                )
            )
        _validate_hash(observation.stdout_sha256, f"{name}.stdout_sha256", violations)
        _validate_hash(observation.stderr_sha256, f"{name}.stderr_sha256", violations)
        _validate_captured_text(observation, violations)


def _validate_captured_text(
    observation: CommandObservation,
    violations: list[InstalledArtifactViolation],
) -> None:
    combined = f"{observation.stdout_text}\n{observation.stderr_text}"
    lowered = combined.lower()
    for marker in FORBIDDEN_TEXT_MARKERS:
        if marker.lower() in lowered:
            violations.append(
                InstalledArtifactViolation(
                    "MPR01_FORBIDDEN_RUNTIME_SURFACE",
                    f"{observation.name} exposed {marker}",
                )
            )
    if observation.stdout_text:
        _scan_json_text(
            observation.stdout_text,
            f"command_observations.{observation.name}.stdout",
            violations,
        )
    if observation.stderr_text:
        _scan_json_text(
            observation.stderr_text,
            f"command_observations.{observation.name}.stderr",
            violations,
        )


def _scan_json_text(
    value: str,
    location: str,
    violations: list[InstalledArtifactViolation],
) -> None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return
    _scan_for_forbidden_true(decoded, location, violations)


def _scan_for_forbidden_true(
    value: Any,
    location: str,
    violations: list[InstalledArtifactViolation],
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            path = f"{location}.{key_text}"
            if key_text in FORBIDDEN_TRUE_KEYS and item is True:
                violations.append(
                    InstalledArtifactViolation(
                        "MPR01_FORBIDDEN_RUNTIME_SURFACE",
                        f"{path} must not be true in MPR-01",
                    )
                )
            _scan_for_forbidden_true(item, path, violations)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan_for_forbidden_true(item, f"{location}[{index}]", violations)


def _derive_runtime_claims(
    observations: Iterable[CommandObservation],
) -> dict[str, bool]:
    claims = {
        "live_enabled": False,
        "live_available": False,
        "live_execution_allowed": False,
        "jito_enabled": False,
        "signer_loaded": False,
        "signer_allowed": False,
        "sender_loaded": False,
        "sender_allowed": False,
        "private_key_material_allowed": False,
    }
    for observation in observations:
        if not observation.stdout_text.strip().startswith("{"):
            continue
        try:
            payload = json.loads(observation.stdout_text)
        except json.JSONDecodeError:
            continue
        for key in list(claims):
            if payload.get(key) is True:
                claims[key] = True
    return claims


def _run_command(
    *,
    name: str,
    argv: tuple[str, ...],
    base_command: tuple[str, ...],
    project_root: Path,
    timeout_seconds: float,
) -> CommandObservation:
    env = os.environ.copy()
    prior_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(project_root)
        if not prior_pythonpath
        else f"{project_root}{os.pathsep}{prior_pythonpath}"
    )
    completed = subprocess.run(
        [*base_command, *argv],
        cwd=project_root,
        env=env,
        check=False,
        timeout=timeout_seconds,
        text=True,
        capture_output=True,
    )
    stdout = _truncate(completed.stdout)
    stderr = _truncate(completed.stderr)
    return CommandObservation(
        name=name,
        argv=argv,
        exit_code=completed.returncode,
        stdout_sha256=_hash_bytes(completed.stdout.encode("utf-8", errors="replace")),
        stderr_sha256=_hash_bytes(completed.stderr.encode("utf-8", errors="replace")),
        stdout_text=stdout,
        stderr_text=stderr,
    )


def _materialize_args(
    args: Sequence[str],
    *,
    paper_db_path: str,
) -> tuple[str, ...]:
    return tuple(paper_db_path if item == "{paper_db_path}" else item for item in args)


def _looks_like_paper_db_path(value: str) -> bool:
    return value.endswith("canonical-paper.sqlite3") or value.endswith("paper.sqlite3")


def _read_pyproject(project_root: Path) -> dict[str, Any]:
    path = project_root / "pyproject.toml"
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _read_root_wrapper_target(project_root: Path) -> str | None:
    path = project_root / "arb_bot.py"
    if not path.exists():
        return None
    marker = 'CANONICAL_MAIN_TARGET = "'
    for line in path.read_text(encoding="utf-8").splitlines():
        if marker in line:
            return line.split(marker, 1)[1].split('"', 1)[0]
    return None


def _strict_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _validate_hash(
    value: str,
    location: str,
    violations: list[InstalledArtifactViolation],
) -> None:
    if not (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(ch in "0123456789abcdef" for ch in value)
    ):
        violations.append(
            InstalledArtifactViolation(
                "MPR01_HASH_INVALID",
                f"{location} must be lowercase sha256",
            )
        )


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _truncate(value: str) -> str:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value
    return value[:MAX_CAPTURE_CHARS] + "\n...[truncated]"
