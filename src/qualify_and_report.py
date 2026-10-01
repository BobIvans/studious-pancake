"""Bounded evidence collector for the installed, sender-free CLI.

This is a consumer of existing command authorities, not a runtime or release
gate. It never invents dependencies, loads credentials, or promotes a release.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sysconfig
import tempfile
import time
from typing import Any, Mapping

SCHEMA_VERSION = "fast-q1.qualification-report.v1"
DISTRIBUTION = "studious-pancake-flashloan-bot"
MAX_OUTPUT_BYTES = 2_000_000


@dataclass(frozen=True)
class Step:
    name: str
    args: tuple[str, ...]
    schema: str


PREFLIGHT_STEPS = (
    Step("status", ("status", "--json"), "mpr-close-01.dependency-light-status.v1"),
    Step("capabilities", ("capabilities", "--json"), "pr023.capabilities.v1"),
    Step("config-doctor", ("config", "doctor", "--json"), "pr026.config-doctor.v1"),
    Step(
        "runtime-admission",
        (
            "runtime-admission",
            "--command",
            "flashloan-bot.run",
            "--mode",
            "paper",
            "--json",
        ),
        "mpr-rp-01.runtime-admission-bundle.v1",
    ),
    Step("paper-vertical", ("paper-vertical", "check"), "pr189.command-result.v1"),
)


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Use packaged defaults, with no inherited config, wallet, API or proxy keys.

    This environment is not an OS sandbox. Only the fixed offline command plan
    is allowed; arbitrary YAML and online flags are deliberately unsupported.
    """
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "TZ",
    }
    selected = {key: value for key, value in environ.items() if key.upper() in allowed}
    selected.update(
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        PYTHONNOUSERSITE="1",
        FLASHLOAN_RUNTIME_MODE="disabled",
        FLASHLOAN_VERIFY_RPC_AT_STARTUP="false",
        FLASHLOAN_JUPITER_ENABLED="false",
        FLASHLOAN_JITO_ENABLED="false",
        FLASHLOAN_MARGINFI_ENABLED="false",
    )
    return selected


def installed_identity() -> tuple[Path | None, dict[str, Any]]:
    """Find the canonical console script in this interpreter's installation."""
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None, {"available": False, "reason_code": "DISTRIBUTION_NOT_INSTALLED"}
    matching = any(
        ep.group == "console_scripts"
        and ep.name == "flashloan-bot"
        and ep.value == "src.cli_pr189:main"
        for ep in dist.entry_points
    )
    executable = Path(sysconfig.get_path("scripts")) / (
        "flashloan-bot.exe" if os.name == "nt" else "flashloan-bot"
    )
    record = dist.read_text("RECORD")
    identity = {
        "available": matching and executable.is_file(),
        "distribution": DISTRIBUTION,
        "version": dist.version,
        "entrypoint": "src.cli_pr189:main",
        "record_sha256": (
            hashlib.sha256(record.encode()).hexdigest() if record else None
        ),
        "source_equivalence_verified": False,
    }
    return (executable if identity["available"] else None), identity


def source_identity(root: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    """Record source identity separately from the installed artifact identity."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            env=dict(environ),
            capture_output=True,
            timeout=10,
            check=False,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            env=dict(environ),
            capture_output=True,
            timeout=10,
            check=False,
        )
        sha = head.stdout.decode("ascii").strip()
        if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            return {"available": False, "reason_code": "SOURCE_IDENTITY_UNAVAILABLE"}
        return {
            "available": True,
            "commit": sha,
            "worktree_dirty": bool(dirty.stdout) if dirty.returncode == 0 else None,
        }
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return {"available": False, "reason_code": "SOURCE_IDENTITY_UNAVAILABLE"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _semantic_reasons(step: Step, payload: dict[str, Any]) -> list[str]:
    if payload.get("schema_version") != step.schema:
        raise ValueError("schema mismatch")
    if step.name == "status":
        if payload.get("capability_contract_valid") is not True:
            return ["CAPABILITY_CONTRACT_INVALID"]
        if (
            payload.get("live_available") is not False
            or payload.get("live_enabled") is not False
        ):
            return ["LIVE_DENIAL_UNPROVEN"]
        return []
    if step.name == "capabilities":
        live = payload.get("runtime_modes", {}).get("live", {})
        return [] if live.get("available") is False else ["LIVE_DENIAL_UNPROVEN"]
    if step.name == "config-doctor":
        if payload.get("ok") is True:
            return []
        return [
            str(d.get("code", "CONFIG_DOCTOR_BLOCKED"))
            for d in payload.get("diagnostics", [])
            if isinstance(d, dict) and d.get("severity") == "error"
        ] or ["CONFIG_DOCTOR_BLOCKED"]
    if step.name == "runtime-admission":
        if (
            payload.get("admitted") is True
            and payload.get("platform", {}).get("admitted") is True
            and payload.get("command", {}).get("admitted") is True
        ):
            return []
        reasons = list(payload.get("platform", {}).get("blockers", []))
        reasons.extend(payload.get("command", {}).get("blockers", []))
        return [str(item) for item in reasons] or ["RUNTIME_ADMISSION_BLOCKED"]
    if step.name == "paper-vertical":
        if (
            payload.get("command") != "paper-vertical"
            or payload.get("command_mode") != "check"
        ):
            raise ValueError("wrong command contract")
        if (
            payload.get("ready") is True
            and payload.get("check_passed") is True
            and payload.get("verdict") == "passed"
            and payload.get("exit_code") == 0
        ):
            safety = payload.get("details", {}).get("safety", {})
            if any(
                safety.get(key) is not False
                for key in (
                    "live_enabled",
                    "signer_reachable",
                    "sender_reachable",
                    "private_key_loading",
                    "network_io_performed",
                )
            ):
                return ["PAPER_VERTICAL_SAFETY_UNPROVEN"]
            return []
        return [str(item) for item in payload.get("reason_codes", [])] or [
            "PAPER_VERTICAL_BLOCKED"
        ]
    if step.name == "paper-shadow":
        if (
            payload.get("status") in {"healthy_idle", "paper_outcome"}
            and payload.get("readiness", {}).get("ready_for_next_cycle") is True
        ):
            return []
        return [str(payload.get("terminal_reason") or "PAPER_SHADOW_NOT_READY")]
    raise ValueError("unknown fixed step")


def execute_step(
    executable: Path | None,
    step: Step,
    *,
    cwd: Path,
    environ: Mapping[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "step": step.name,
        "argv": ["flashloan-bot", *step.args],
        "state": "error",
        "exit_code": None,
        "reason_codes": [],
        "timeout_seconds": timeout_seconds,
        "payload": None,
    }
    if executable is None:
        receipt["reason_codes"] = ["INSTALLED_ENTRYPOINT_UNAVAILABLE"]
        return receipt
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [str(executable), *step.args],
            cwd=cwd,
            env=dict(environ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        receipt.update(
            exit_code=completed.returncode,
            stdout_bytes=len(completed.stdout),
            stderr_bytes=len(completed.stderr),
            stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
        )
        # Do not persist stderr/tracebacks: only size and digest. Parse the entire
        # stdout, rather than guessing a JSON fragment from mixed log output.
        if len(completed.stdout) + len(completed.stderr) > MAX_OUTPUT_BYTES:
            raise ValueError("output limit exceeded")
        payload = json.loads(
            completed.stdout.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        reasons = _semantic_reasons(step, payload)
        receipt["payload"] = payload
        if (
            step.name == "paper-vertical"
            and payload.get("exit_code") != completed.returncode
        ):
            raise ValueError("exit contract mismatch")
        if completed.returncode != 0 and not reasons:
            receipt["reason_codes"] = ["EXIT_CODE_CONTRADICTS_READY_PAYLOAD"]
        else:
            receipt["state"] = "blocked" if reasons else "passed"
            receipt["reason_codes"] = reasons
    except subprocess.TimeoutExpired:
        receipt["reason_codes"] = ["COMMAND_TIMEOUT"]
    except OSError as exc:
        receipt["reason_codes"] = ["COMMAND_UNAVAILABLE"]
        receipt["error_type"] = type(exc).__name__
    except (ValueError, UnicodeError, AttributeError, TypeError) as exc:
        receipt["payload"] = None
        receipt["reason_codes"] = ["INVALID_COMMAND_EVIDENCE"]
        receipt["error_type"] = type(exc).__name__
    receipt["duration_seconds"] = round(time.monotonic() - started, 3)
    return receipt


def _write_json(path: Path, payload: object) -> str:
    raw = (
        json.dumps(
            payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def collect_report(
    *,
    output_dir: Path,
    project_root: Path,
    timeout_seconds: int = 30,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not 1 <= timeout_seconds <= 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="qualification-", dir=output_dir))
    child_env = child_environment(os.environ if environ is None else environ)
    executable, installation = installed_identity()
    receipts = [
        execute_step(
            executable,
            step,
            cwd=run_dir,
            environ=child_env,
            timeout_seconds=timeout_seconds,
        )
        for step in PREFLIGHT_STEPS
    ]
    paper = Step(
        "paper-shadow",
        (
            "paper-shadow",
            "--journal-path",
            str(run_dir / "paper-shadow.jsonl"),
            "--json",
        ),
        "pr076.paper-shadow-summary.v1",
    )
    if all(item["state"] == "passed" for item in receipts):
        receipts.append(
            execute_step(
                executable,
                paper,
                cwd=run_dir,
                environ=child_env,
                timeout_seconds=timeout_seconds,
            )
        )
    else:
        receipts.append(
            {
                "step": paper.name,
                "argv": ["flashloan-bot", *paper.args],
                "state": "skipped",
                "exit_code": None,
                "payload": None,
                "reason_codes": ["PREFLIGHT_NOT_PASSED"],
            }
        )
    blockers = [
        {"step": r["step"], "state": r["state"], "reason_codes": r["reason_codes"]}
        for r in receipts
        if r["state"] in {"blocked", "error"}
    ]
    state = (
        "error"
        if any(r["state"] == "error" for r in receipts)
        else ("blocked" if blockers else "paper-check-passed")
    )
    files = []
    for index, receipt in enumerate(receipts, 1):
        filename = f"{index:02d}_{receipt['step']}.json"
        files.append(
            {"path": filename, "sha256": _write_json(run_dir / filename, receipt)}
        )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "paper_check_passed": state == "paper-check-passed",
        "exit_code": 2 if state == "error" else (3 if blockers else 0),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "source": source_identity(project_root.resolve(), child_env),
        "installation": installation,
        "profile": "offline-defaults-providers-disabled-no-inherited-config",
        "run_dir": str(run_dir),
        "receipts": receipts,
        "receipt_files": files,
        "production_qualification_passed": False,
        "release_claim_allowed": False,
        "live_enabled": False,
        "laya_inference_performed": False,
    }
    _write_json(run_dir / "qualification_report.json", report)
    first = report["first_blocker"]
    description = (
        f"{first['step']}: {', '.join(first['reason_codes'])}" if first else "нет"
    )
    (run_dir / "summary_ru.txt").write_text(
        f"Состояние проверки: {state}\nПервый блокер: {description}\n"
        f"Проверено команд: {sum(r['state'] != 'skipped' for r in receipts)}\n"
        "Профиль: локальные настройки по умолчанию, без унаследованного YAML и ключей.\n"
        "Это отчёт проверки paper-пути; production qualification и разрешение релиза не выданы.\n"
        "Laya не запускалась. Последующие исправления следует привязать к причине и receipt.\n",
        encoding="utf-8",
    )
    return report


def run_cli(*, output_dir: str, project_root: str, timeout_seconds: int) -> int:
    try:
        report = collect_report(
            output_dir=Path(output_dir),
            project_root=Path(project_root),
            timeout_seconds=timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "state": "error",
                    "exit_code": 2,
                    "reason_codes": ["REPORT_INPUT_OR_WRITE_ERROR"],
                    "error_type": type(exc).__name__,
                }
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return int(report["exit_code"])
