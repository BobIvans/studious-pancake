"""FAST-Q1: bounded installed inspections; receipts never grant release authority.

Only fixed, offline console commands are admitted. Model output is never argv.
This first slice diagnoses qualification blockers; it does not run a market soak.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata, util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
from typing import Any

SCHEMA = "fast-q1.qualification-receipt.v1"
MAX_OUTPUT = 1024 * 1024
STEPS = (
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


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _environment() -> dict[str, str]:
    # No inherited wallet/API keys, Python import overrides or runtime flags.
    names = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in names if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def inspect_baseline(repo: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args],
            env=_environment(),
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()

    baseline: dict[str, Any] = {
        "schema_version": "fast-q1.baseline.v1",
        "repository_root": str(repo),
        "git_sha": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "package_installed": False,
        "installed_source_matches": False,
    }
    try:
        dist = metadata.distribution("studious-pancake-flashloan-bot")
        entries = [e for e in dist.entry_points if e.name == "flashloan-bot"]
        baseline["package_version"] = dist.version
        baseline["console_target"] = entries[0].value if len(entries) == 1 else None
        baseline["package_installed"] = True
        spec = util.find_spec("src.cli_entrypoint")
        if spec is not None and spec.origin is not None:
            installed_root = Path(spec.origin).parent
            names = (
                "cli_pr189.py",
                "cli_entrypoint.py",
                "automation_cli_pr189.py",
                "qualification_report.py",
            )
            hashes = {
                name: _digest((installed_root / name).read_bytes()) for name in names
            }
            baseline["installed_source_sha256"] = hashes
            baseline["installed_source_matches"] = all(
                hashes[name] == _digest((repo / "src" / name).read_bytes())
                for name in names
            )
    except (metadata.PackageNotFoundError, ImportError, OSError):
        pass
    config = repo / "config" / "capabilities.json"
    baseline["capabilities_sha256"] = _digest(config.read_bytes())
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


def _capture(argv: list[str], repo: Path, timeout: int) -> dict[str, Any]:
    started = _now()
    try:
        process = subprocess.Popen(
            argv,
            cwd=repo,
            env=_environment(),
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
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}

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
    error = None
    try:
        process.wait(timeout=timeout)
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


def _validate(step: str, payload: dict[str, Any]) -> bool:
    if step == "status":
        return (
            payload.get("live_available") is False
            and payload.get("signer_loaded") is False
            and payload.get("sender_loaded") is False
            and payload.get("capability_contract_valid") is True
        )
    if step == "capabilities":
        modes = payload.get("runtime_modes")
        live = modes.get("live") if isinstance(modes, dict) else None
        return isinstance(live, dict) and live.get("available") is False
    if step == "doctor":
        return payload.get("ok") is True
    return payload.get("admitted") is True


def qualify_and_report(
    *,
    repo_root: Path,
    output_root: Path,
    request_id: str,
    expected_sha: str,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
        raise ValueError("REQUEST_ID_INVALID")
    if not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
        raise ValueError("EXPECTED_SHA_INVALID")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError("TIMEOUT_INVALID")
    repo = repo_root.resolve(strict=True)
    absolute_output = output_root.absolute()
    if any(path.is_symlink() for path in (absolute_output, *absolute_output.parents)):
        raise ValueError("OUTPUT_SYMLINK_BLOCKED")
    output = absolute_output.resolve()
    if output == repo or output.is_relative_to(repo):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_CHECKOUT")
    output.mkdir(parents=True, exist_ok=True)
    run = output / request_id
    baseline = inspect_baseline(repo)
    inputs = {
        "baseline": baseline,
        "expected_sha": expected_sha,
        "timeout_seconds": timeout_seconds,
        "profile": "offline-inspection",
    }
    input_digest = _digest(json.dumps(inputs, sort_keys=True).encode())
    try:
        run.mkdir()
    except FileExistsError:
        if run.is_symlink():
            raise ValueError("RUN_SYMLINK_BLOCKED")
        manifest_path = run / "run_manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("RUN_INCOMPLETE_RECONCILE_BEFORE_RETRY")
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            raise ValueError("RUN_MANIFEST_INVALID")
        if previous.get("input_digest") != input_digest:
            raise ValueError("REQUEST_ID_INPUT_CONFLICT")
        receipt_path = run / "qualification_receipt.json"
        if previous.get("state") != "COMPLETE" or not receipt_path.is_file():
            raise ValueError("RUN_INCOMPLETE_RECONCILE_BEFORE_RETRY")
        if receipt_path.is_symlink():
            raise ValueError("ARTIFACT_PATH_INVALID")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for name, digest in previous.get("artifact_sha256", {}).items():
            if Path(name).name != name or (run / name).is_symlink():
                raise ValueError("ARTIFACT_PATH_INVALID")
            if _digest((run / name).read_bytes()) != digest:
                raise ValueError("ARTIFACT_INTEGRITY_FAILED")
        if _digest(receipt_path.read_bytes()) != previous.get("receipt_sha256"):
            raise ValueError("RECEIPT_INTEGRITY_FAILED")
        return {**receipt, "reused": True}
    manifest: dict[str, Any] = {
        "schema_version": "fast-q1.run-manifest.v1",
        "input_digest": input_digest,
        "state": "RUNNING",
        "started_at": _now(),
        "artifact_sha256": {},
    }
    _write(run / "run_manifest.json", manifest)
    _write(run / "baseline.json", baseline)
    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    if baseline["git_sha"] != expected_sha:
        blockers.append("BASE_SHA_CHANGED")
    if baseline["dirty"]:
        blockers.append("CHECKOUT_DIRTY")
    if not baseline["package_installed"]:
        blockers.append("INSTALLED_PACKAGE_UNAVAILABLE")
    if baseline.get("console_target") != "src.cli_pr189:main":
        blockers.append("INSTALLED_ENTRYPOINT_MISMATCH")
    if not baseline["installed_source_matches"]:
        blockers.append("INSTALLED_SOURCE_MISMATCH")
    script = Path(sys.executable).parent / (
        "flashloan-bot.exe" if os.name == "nt" else "flashloan-bot"
    )
    if not script.is_file():
        blockers.append("INSTALLED_CONSOLE_SCRIPT_UNAVAILABLE")
    if not blockers:
        for name, args, schema in STEPS:
            capture = _capture([str(script), *args], repo, timeout_seconds)
            files: dict[str, str] = {}
            for stream in ("stdout", "stderr"):
                filename = f"{name}.{stream}.txt"
                raw = capture.pop(stream)
                (run / filename).write_bytes(raw)
                files[filename] = _digest(raw)
            manifest["artifact_sha256"].update(files)
            record = {
                "step": name,
                "argv": [str(script), *args],
                **capture,
                "raw_sha256": files,
                "payload": None,
            }
            reason = capture["error"]
            try:
                payload = json.loads((run / f"{name}.stdout.txt").read_bytes())
                if (
                    not isinstance(payload, dict)
                    or payload.get("schema_version") != schema
                ):
                    reason = reason or "RESPONSE_SCHEMA_INVALID"
                else:
                    record["payload"] = payload
                    if not _validate(name, payload):
                        reason = reason or "DOMAIN_BLOCKED"
            except (ValueError, UnicodeError):
                reason = reason or "RESPONSE_JSON_INVALID"
            if capture["exit_code"] != 0:
                reason = reason or "COMMAND_EXIT_NONZERO"
            record["reason_code"] = reason
            if reason:
                blockers.append(f"{name}:{reason}")
            records.append(record)
    if inspect_baseline(repo) != baseline:
        blockers.append("BASELINE_CHANGED_DURING_RUN")
    blockers = list(dict.fromkeys(blockers))
    receipt = {
        "schema_version": SCHEMA,
        "request_id": request_id,
        "input_digest": input_digest,
        "run_directory": str(run),
        "git_sha": baseline["git_sha"],
        "execution_status": "COMPLETE",
        "domain_verdict": "BLOCKED" if blockers else "INSPECTED",
        "qualified": False,
        "live_authorized": False,
        "market_run_performed": False,
        "transactions_sent": 0,
        "profile": "offline-inspection",
        "reused": False,
        "blockers": blockers,
        "steps": records,
        "next_action": "resolve_blocker" if blockers else "admit_sender_free_campaign",
    }
    _write(run / "qualification_receipt.json", receipt)
    (run / "BLOCKERS_RU.txt").write_text(
        "Результат: "
        + receipt["domain_verdict"]
        + "\n"
        + "Допуск стратегии не выдан. Рыночный запуск не выполнен.\n"
        + "\n".join(blockers)
        + "\n",
        encoding="utf-8",
    )
    for name in ("baseline.json", "BLOCKERS_RU.txt"):
        manifest["artifact_sha256"][name] = _digest((run / name).read_bytes())
    manifest.update(
        {
            "state": "COMPLETE",
            "ended_at": _now(),
            "receipt_sha256": _digest(
                (run / "qualification_receipt.json").read_bytes()
            ),
        }
    )
    _write(run / "run_manifest.json", manifest)
    return receipt
