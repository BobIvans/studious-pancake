"""FAST-Q1 v3 bounded installed qualification runner.

This module is a consumer of existing installed command authorities. It maps one
reviewed action to a fixed argv plan, captures immutable evidence, and runs at
most one sender-free paper-shadow pass after all offline preflights succeed.

It never accepts model/chat text as argv, never invokes a shell, never loads
credentials, never grants live/release authority, and never retries an
incomplete run automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from importlib import metadata, util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import sysconfig
import threading
from typing import Any, Mapping, Sequence

SCHEMA = "fast-q1.qualification-receipt.v2"
MANIFEST_SCHEMA = "fast-q1.run-manifest.v2"
BASELINE_SCHEMA = "fast-q1.baseline.v2"
ACTION_ID = "qualify_and_report"
PROFILE = "offline_sender_free"
DISTRIBUTION = "studious-pancake-flashloan-bot"
MAX_OUTPUT = 1024 * 1024
MAX_TIMEOUT_SECONDS = 120

PREFLIGHT_STEPS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("status", ("status", "--json"), "mpr-close-01.dependency-light-status.v1"),
    ("capabilities", ("capabilities", "--json"), "pr023.capabilities.v1"),
    ("doctor", ("config", "doctor", "--json"), "pr026.config-doctor.v1"),
    (
        "admission",
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
)

PAPER_STEP = (
    "paper-shadow",
    ("paper-shadow", "--journal-path", "{journal}", "--json"),
    "pr076.paper-shadow-summary.v1",
)

_SAFE_ENV_NAMES = (
    "PATH",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "TZ",
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _strict_json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite JSON number")

    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique,
        parse_constant=reject_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def _write_json(path: Path, value: Any) -> None:
    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def _environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    env = {key: source[key] for key in _SAFE_ENV_NAMES if key in source}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "FLASHLOAN_RUNTIME_MODE": "paper",
            "FLASHLOAN_VERIFY_RPC_AT_STARTUP": "false",
            "FLASHLOAN_JUPITER_ENABLED": "false",
            "FLASHLOAN_HELIUS_ENABLED": "false",
            "FLASHLOAN_OPENOCEAN_ENABLED": "false",
            "FLASHLOAN_JITO_ENABLED": "false",
            "FLASHLOAN_MARGINFI_ENABLED": "false",
            "FLASHLOAN_KAMINO_ENABLED": "false",
            "LIVE_TRADING_ENABLED": "false",
            "PAPER_TRADING_ONLY": "true",
        }
    )
    return env


def _installed_scripts() -> tuple[Path | None, dict[str, Any]]:
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None, {
            "package_installed": False,
            "reason_code": "DISTRIBUTION_NOT_INSTALLED",
        }

    entrypoints = {
        entry.name: entry.value
        for entry in dist.entry_points
        if entry.group == "console_scripts"
    }
    scripts_dir = Path(sysconfig.get_path("scripts"))
    bot = scripts_dir / ("flashloan-bot.exe" if os.name == "nt" else "flashloan-bot")
    record = dist.read_text("RECORD")
    return (
        bot if bot.is_file() else None,
        {
            "package_installed": True,
            "distribution": DISTRIBUTION,
            "package_version": dist.version,
            "flashloan_bot_target": entrypoints.get("flashloan-bot"),
            "flashloan_checks_target": entrypoints.get("flashloan-checks"),
            "record_sha256": _digest(record.encode("utf-8")) if record else None,
        },
    )


def inspect_baseline(repo: Path) -> dict[str, Any]:
    env = _environment()

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError("SOURCE_IDENTITY_UNAVAILABLE")
        return completed.stdout.strip()

    bot, installation = _installed_scripts()
    baseline: dict[str, Any] = {
        "schema_version": BASELINE_SCHEMA,
        "repository_root": str(repo),
        "git_sha": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        **installation,
        "installed_source_matches": False,
        "installed_console_script": str(bot) if bot is not None else None,
    }

    try:
        spec = util.find_spec("src.cli_entrypoint")
        if spec is not None and spec.origin is not None:
            installed_root = Path(spec.origin).parent
            names = (
                "cli_pr189.py",
                "cli_entrypoint.py",
                "automation_cli_pr189.py",
                "qualification_report.py",
            )
            installed_hashes = {
                name: _digest((installed_root / name).read_bytes()) for name in names
            }
            source_hashes = {
                name: _digest((repo / "src" / name).read_bytes()) for name in names
            }
            baseline["installed_source_sha256"] = installed_hashes
            baseline["checkout_source_sha256"] = source_hashes
            baseline["installed_source_matches"] = installed_hashes == source_hashes
    except OSError:
        pass

    capabilities = repo / "config" / "capabilities.json"
    baseline["capabilities_sha256"] = _digest(capabilities.read_bytes())
    return baseline


def _kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            process.kill()
    except (OSError, subprocess.TimeoutExpired):
        process.kill()


def _capture(
    argv: Sequence[str],
    *,
    repo: Path,
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    started = _now()
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=repo,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        return {
            "exit_code": None,
            "error": type(exc).__name__,
            "stdout": b"",
            "stderr": b"",
            "started_at": started,
            "ended_at": _now(),
        }

    exceeded = threading.Event()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}

    def read(name: str) -> None:
        stream = getattr(process, name)
        assert stream is not None
        try:
            while chunk := stream.read(4096):
                remaining = MAX_OUTPUT - len(buffers[name])
                buffers[name].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    _kill(process)
                    break
        finally:
            stream.close()

    threads = [
        threading.Thread(target=read, args=(name,), daemon=True) for name in buffers
    ]
    for thread in threads:
        thread.start()

    error: str | None = None
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        error = "TIMEOUT"
        _kill(process)
        process.wait(timeout=5)
    finally:
        for thread in threads:
            thread.join(timeout=5)

    if any(thread.is_alive() for thread in threads):
        error = "CAPTURE_INCOMPLETE"
    if exceeded.is_set():
        error = "OUTPUT_LIMIT"

    return {
        "exit_code": process.returncode,
        "error": error,
        "stdout": bytes(buffers["stdout"]),
        "stderr": bytes(buffers["stderr"]),
        "started_at": started,
        "ended_at": _now(),
    }


def _semantic_reason(step: str, payload: Mapping[str, Any]) -> str | None:
    if step == "status":
        if payload.get("capability_contract_valid") is not True:
            return "CAPABILITY_CONTRACT_INVALID"
        if payload.get("live_available") is not False:
            return "LIVE_AVAILABLE"
        if payload.get("live_enabled") is not False:
            return "LIVE_ENABLED"
        return None
    if step == "capabilities":
        modes = payload.get("runtime_modes")
        live = modes.get("live") if isinstance(modes, Mapping) else None
        if not isinstance(live, Mapping) or live.get("available") is not False:
            return "LIVE_CAPABILITY_NOT_DENIED"
        return None
    if step == "doctor":
        return None if payload.get("ok") is True else "CONFIG_DOCTOR_BLOCKED"
    if step == "admission":
        if (
            payload.get("admitted") is True
            and isinstance(payload.get("platform"), Mapping)
            and payload["platform"].get("admitted") is True
            and isinstance(payload.get("command"), Mapping)
            and payload["command"].get("admitted") is True
        ):
            return None
        return "RUNTIME_ADMISSION_BLOCKED"
    if step == "paper-shadow":
        readiness = payload.get("readiness")
        ready = (
            isinstance(readiness, Mapping)
            and readiness.get("ready_for_next_cycle") is True
        )
        if payload.get("status") in {"healthy_idle", "paper_outcome"} and ready:
            return None
        reason = str(payload.get("terminal_reason") or "").strip()
        return reason or "PAPER_SHADOW_BLOCKED"
    raise ValueError("UNKNOWN_FIXED_STEP")


def _stop_requested(run: Path) -> bool:
    stop = run / "STOP"
    return stop.exists()


def _artifact_digest(run: Path, name: str) -> str:
    path = run / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("ARTIFACT_PATH_INVALID")
    return _digest(path.read_bytes())


def _verify_completed_run(run: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    receipt_path = run / "qualification_receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("RUN_INCOMPLETE_RECONCILE_BEFORE_RETRY")
    for name, expected in manifest.get("artifact_sha256", {}).items():
        if Path(name).name != name:
            raise ValueError("ARTIFACT_PATH_INVALID")
        if _artifact_digest(run, name) != expected:
            raise ValueError("ARTIFACT_INTEGRITY_FAILED")
    if _artifact_digest(run, "qualification_receipt.json") != manifest.get(
        "receipt_sha256"
    ):
        raise ValueError("RECEIPT_INTEGRITY_FAILED")
    payload = _strict_json(receipt_path.read_bytes())
    return {**payload, "reused": True}


def _checkpoint(
    run: Path,
    manifest: dict[str, Any],
    *,
    state: str,
    completed_steps: Sequence[str],
) -> None:
    manifest["state"] = state
    manifest["completed_steps"] = list(completed_steps)
    manifest["updated_at"] = _now()
    _write_json(run / "run_manifest.json", manifest)


def _run_step(
    *,
    run: Path,
    repo: Path,
    bot: Path,
    name: str,
    args: Sequence[str],
    schema: str,
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> tuple[dict[str, Any], str | None]:
    capture = _capture(
        [str(bot), *args],
        repo=repo,
        timeout_seconds=timeout_seconds,
        environment=environment,
    )
    raw_hashes: dict[str, str] = {}
    for stream in ("stdout", "stderr"):
        filename = f"{name}.{stream}.bin"
        raw = capture.pop(stream)
        (run / filename).write_bytes(raw)
        raw_hashes[filename] = _digest(raw)

    record = {
        "step": name,
        "argv": ["flashloan-bot", *args],
        **capture,
        "raw_sha256": raw_hashes,
        "payload": None,
        "reason_code": None,
    }

    reason = capture["error"]
    if reason is None:
        try:
            payload = _strict_json((run / f"{name}.stdout.bin").read_bytes())
            if payload.get("schema_version") != schema:
                reason = "RESPONSE_SCHEMA_INVALID"
            else:
                record["payload"] = payload
                reason = _semantic_reason(name, payload)
        except (UnicodeError, ValueError, TypeError, AttributeError):
            reason = "RESPONSE_JSON_INVALID"

    if capture["exit_code"] not in (0, None) and reason is None:
        reason = "COMMAND_EXIT_NONZERO"

    record["reason_code"] = reason
    _write_json(run / f"{name}.record.json", record)
    return record, reason


def qualify_and_report(
    *,
    repo_root: Path,
    output_root: Path,
    request_id: str,
    expected_sha: str,
    profile: str = PROFILE,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
        raise ValueError("REQUEST_ID_INVALID")
    if not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
        raise ValueError("EXPECTED_SHA_INVALID")
    if profile != PROFILE:
        raise ValueError("PROFILE_NOT_ALLOWED")
    if (
        type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("TIMEOUT_INVALID")

    repo = repo_root.resolve(strict=True)
    absolute_output = output_root.absolute()
    if any(path.is_symlink() for path in (absolute_output, *absolute_output.parents)):
        raise ValueError("OUTPUT_SYMLINK_BLOCKED")
    output = absolute_output.resolve()
    if output == repo or output.is_relative_to(repo):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_CHECKOUT")
    output.mkdir(parents=True, exist_ok=True)

    baseline = inspect_baseline(repo)
    inputs = {
        "action_id": ACTION_ID,
        "baseline": baseline,
        "expected_sha": expected_sha,
        "profile": profile,
        "timeout_seconds": timeout_seconds,
    }
    input_digest = _digest(
        json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    run = output / request_id

    try:
        run.mkdir()
    except FileExistsError:
        if run.is_symlink():
            raise ValueError("RUN_SYMLINK_BLOCKED")
        manifest_path = run / "run_manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("RUN_INCOMPLETE_RECONCILE_BEFORE_RETRY")
        previous = _strict_json(manifest_path.read_bytes())
        if previous.get("input_digest") != input_digest:
            raise ValueError("REQUEST_ID_INPUT_CONFLICT")
        if previous.get("state") != "COMPLETE":
            raise ValueError("RUN_INCOMPLETE_RECONCILE_BEFORE_RETRY")
        return _verify_completed_run(run, previous)

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "action_id": ACTION_ID,
        "input_digest": input_digest,
        "state": "RUNNING",
        "started_at": _now(),
        "updated_at": _now(),
        "completed_steps": [],
        "artifact_sha256": {},
        "external_effects_permitted": False,
    }
    _write_json(run / "run_manifest.json", manifest)
    _write_json(run / "baseline.json", baseline)
    manifest["artifact_sha256"]["baseline.json"] = _artifact_digest(
        run, "baseline.json"
    )

    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    completed_steps: list[str] = []

    if baseline["git_sha"] != expected_sha:
        blockers.append("BASE_SHA_CHANGED")
    if baseline["dirty"]:
        blockers.append("CHECKOUT_DIRTY")
    if baseline.get("package_installed") is not True:
        blockers.append("INSTALLED_PACKAGE_UNAVAILABLE")
    if baseline.get("flashloan_bot_target") != "src.cli_pr189:main":
        blockers.append("INSTALLED_BOT_ENTRYPOINT_MISMATCH")
    if baseline.get("flashloan_checks_target") != "src.automation_cli_pr189:main":
        blockers.append("INSTALLED_CHECKS_ENTRYPOINT_MISMATCH")
    if baseline.get("installed_source_matches") is not True:
        blockers.append("INSTALLED_SOURCE_MISMATCH")

    bot_raw = baseline.get("installed_console_script")
    bot = Path(bot_raw) if isinstance(bot_raw, str) else None
    if bot is None or not bot.is_file():
        blockers.append("INSTALLED_CONSOLE_SCRIPT_UNAVAILABLE")

    child_env = _environment()

    if not blockers and bot is not None:
        for name, args, schema in PREFLIGHT_STEPS:
            if _stop_requested(run):
                blockers.append("CANCELLED_BY_STOP_FILE")
                break
            record, reason = _run_step(
                run=run,
                repo=repo,
                bot=bot,
                name=name,
                args=args,
                schema=schema,
                timeout_seconds=timeout_seconds,
                environment=child_env,
            )
            records.append(record)
            completed_steps.append(name)
            for filename, digest_value in record["raw_sha256"].items():
                manifest["artifact_sha256"][filename] = digest_value
            record_name = f"{name}.record.json"
            manifest["artifact_sha256"][record_name] = _artifact_digest(
                run, record_name
            )
            _checkpoint(
                run,
                manifest,
                state="RUNNING",
                completed_steps=completed_steps,
            )
            if reason is not None:
                blockers.append(f"{name}:{reason}")
                break

    paper_shadow_performed = False
    if not blockers and bot is not None:
        if _stop_requested(run):
            blockers.append("CANCELLED_BY_STOP_FILE")
        else:
            name, args_template, schema = PAPER_STEP
            journal = run / "paper-shadow.jsonl"
            args = tuple(
                str(journal) if value == "{journal}" else value
                for value in args_template
            )
            record, reason = _run_step(
                run=run,
                repo=repo,
                bot=bot,
                name=name,
                args=args,
                schema=schema,
                timeout_seconds=timeout_seconds,
                environment=child_env,
            )
            paper_shadow_performed = True
            records.append(record)
            completed_steps.append(name)
            for filename, digest_value in record["raw_sha256"].items():
                manifest["artifact_sha256"][filename] = digest_value
            record_name = f"{name}.record.json"
            manifest["artifact_sha256"][record_name] = _artifact_digest(
                run, record_name
            )
            if journal.is_file() and not journal.is_symlink():
                manifest["artifact_sha256"][journal.name] = _digest(
                    journal.read_bytes()
                )
            _checkpoint(
                run,
                manifest,
                state="RUNNING",
                completed_steps=completed_steps,
            )
            if reason is not None:
                blockers.append(f"{name}:{reason}")

    try:
        final_baseline = inspect_baseline(repo)
    except (OSError, ValueError, subprocess.SubprocessError):
        final_baseline = None
    if final_baseline != baseline:
        blockers.append("BASELINE_CHANGED_DURING_RUN")

    blockers = list(dict.fromkeys(blockers))
    sender_free_pass = paper_shadow_performed and not blockers
    if "CANCELLED_BY_STOP_FILE" in blockers:
        execution_status = "CANCELLED"
    else:
        execution_status = "COMPLETE"

    receipt = {
        "schema_version": SCHEMA,
        "action_id": ACTION_ID,
        "request_id": request_id,
        "input_digest": input_digest,
        "run_directory": str(run),
        "git_sha": baseline["git_sha"],
        "package_version": baseline.get("package_version"),
        "execution_status": execution_status,
        "domain_verdict": "PAPER_PASS" if sender_free_pass else "BLOCKED",
        "sender_free_pass": sender_free_pass,
        "qualified": False,
        "release_authorized": False,
        "live_authorized": False,
        "paper_shadow_performed": paper_shadow_performed,
        "transactions_sent": 0,
        "profile": profile,
        "reused": False,
        "blockers": blockers,
        "steps": records,
        "next_action": (
            "review_sender_free_evidence"
            if sender_free_pass
            else "resolve_first_blocker"
        ),
    }
    _write_json(run / "qualification_receipt.json", receipt)

    blockers_text = "\n".join(blockers) if blockers else "нет"
    (run / "BLOCKERS_RU.txt").write_text(
        "FAST-Q1\n"
        f"execution_status={execution_status}\n"
        f"domain_verdict={receipt['domain_verdict']}\n"
        "qualified=false\n"
        "live_authorized=false\n"
        "transactions_sent=0\n"
        f"Блокеры:\n{blockers_text}\n",
        encoding="utf-8",
    )
    manifest["artifact_sha256"]["BLOCKERS_RU.txt"] = _artifact_digest(
        run, "BLOCKERS_RU.txt"
    )
    manifest["artifact_sha256"]["qualification_receipt.json"] = _artifact_digest(
        run, "qualification_receipt.json"
    )
    manifest["state"] = "COMPLETE"
    manifest["ended_at"] = _now()
    manifest["receipt_sha256"] = manifest["artifact_sha256"][
        "qualification_receipt.json"
    ]
    _write_json(run / "run_manifest.json", manifest)

    return receipt


__all__ = [
    "ACTION_ID",
    "BASELINE_SCHEMA",
    "MANIFEST_SCHEMA",
    "MAX_OUTPUT",
    "PAPER_STEP",
    "PREFLIGHT_STEPS",
    "PROFILE",
    "SCHEMA",
    "inspect_baseline",
    "qualify_and_report",
]
