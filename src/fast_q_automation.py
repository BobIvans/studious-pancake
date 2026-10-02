"""Deterministic FAST-Q2/Q3/Q4 orchestration over existing qualification owners."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

REQUEST_SCHEMA = "fast-q2.action-request.v1"
LEGACY_REQUEST_SCHEMA = "occ.qualification-action.v1"
RECEIPT_SCHEMA = "fast-q2.action-receipt.v1"
REPAIR_TASK_SCHEMA = "fast-q3.repair-task.v1"
STATE_SCHEMA = "fast-q4.receipt-state.v1"
ADAPTER_SCHEMA = "fast-q5.external-adapter-contract.v1"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_OUTPUT = 128 * 1024
MAX_TIMEOUT_SECONDS = 120

ACTION_IDS = frozenset(
    {
        "qualify_and_report",
        "inspect_current_blocker",
        "prepare_repair_task",
        "run_focused_validation",
        "update_receipt_state",
        "ingest_local_content",
        "search_local_corpus",
        "transcribe_local_audio",
    }
)
EXTERNAL_ACTIONS = frozenset(
    {"ingest_local_content", "search_local_corpus", "transcribe_local_audio"}
)
ACTION_REGISTRY: Mapping[str, Mapping[str, Any]] = {
    "qualify_and_report": {
        "evidence_kind": "installed_offline_inspection",
        "external_only": False,
    },
    "inspect_current_blocker": {
        "evidence_kind": "qualification_receipt_read",
        "external_only": False,
    },
    "prepare_repair_task": {
        "evidence_kind": "bounded_repair_task",
        "external_only": False,
    },
    "run_focused_validation": {
        "evidence_kind": "fixed_validation_commands",
        "external_only": False,
    },
    "update_receipt_state": {
        "evidence_kind": "receipt_derived_state",
        "external_only": False,
    },
    "ingest_local_content": {
        "evidence_kind": "external_adapter_contract",
        "external_only": True,
    },
    "search_local_corpus": {
        "evidence_kind": "external_adapter_contract",
        "external_only": True,
    },
    "transcribe_local_audio": {
        "evidence_kind": "external_adapter_contract",
        "external_only": True,
    },
}

REQUEST_FIELDS = {
    "schema_version",
    "request_id",
    "idempotency_key",
    "action",
    "text",
    "inputs",
    "proposal",
}
LEGACY_FIELDS = {"schema_version", "request_id", "text"}
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
EXACT_TEXT_ROUTES = {
    "проверь готовность бота": "qualify_and_report",
    "check bot readiness": "qualify_and_report",
    "покажи текущий блокер": "inspect_current_blocker",
    "inspect current blocker": "inspect_current_blocker",
    "подготовь задачу исправления": "prepare_repair_task",
    "prepare repair task": "prepare_repair_task",
    "запусти точечную проверку": "run_focused_validation",
    "run focused validation": "run_focused_validation",
    "обнови состояние по квитанции": "update_receipt_state",
    "update receipt state": "update_receipt_state",
    "подготовь импорт локального контента": "ingest_local_content",
    "prepare local content ingest": "ingest_local_content",
    "подготовь поиск по локальному корпусу": "search_local_corpus",
    "prepare local corpus search": "search_local_corpus",
    "подготовь локальную транскрибацию": "transcribe_local_audio",
    "prepare local audio transcription": "transcribe_local_audio",
}
_FORBIDDEN_TEXT = (
    "live trading",
    "live trade",
    "send transaction",
    "sign transaction",
    "private key",
    "seed phrase",
    "реальная торгов",
    "лайв торгов",
    "отправ транзак",
    "подпис транзак",
    "приватн ключ",
)
_NEGATION_TEXT = ("do not ", "don't ", "not ", "without ", "не ", "без ")
_SECRET_KEYS = (
    "api_key",
    "private_key",
    "secret",
    "password",
    "token",
    "credential",
    "cookie",
    "seed",
    "mnemonic",
)

FIXED_VALIDATIONS: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "fast_q_automation": (
        (sys.executable, "scripts/verify_fast_q_automation.py"),
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_fast_q_automation.py",
            "tests/test_fast_q1_qualification_report.py",
            "--disable-socket",
            "--allow-unix-socket",
        ),
    ),
    "fast_q1_v3": (
        (sys.executable, "scripts/verify_fast_q1_v3.py"),
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_fast_q1_qualification_report.py",
            "--disable-socket",
            "--allow-unix-socket",
        ),
    ),
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("JSON_PATH_INVALID")
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise ValueError("JSON_TOO_LARGE")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("NON_FINITE_JSON_NUMBER")
        ),
    )


def _identifier(value: Any, reason: str) -> str:
    if not isinstance(value, str) or IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(reason)
    return value


def _safe_json(value: Any) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        raise ValueError("FLOAT_INPUT_FORBIDDEN")
    if isinstance(value, list):
        for item in value:
            _safe_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("NON_STRING_INPUT_KEY")
            lowered = key.casefold()
            if any(secret in lowered for secret in _SECRET_KEYS):
                raise ValueError("SECRET_BEARING_INPUT_FORBIDDEN")
            _safe_json(item)
        return
    raise ValueError("UNSUPPORTED_JSON_VALUE")


def route_request(request: Mapping[str, Any]) -> str:
    explicit = request.get("action")
    text = request.get("text")
    routed: str | None = None
    if text is not None:
        if not isinstance(text, str) or not text.strip() or len(text) > 512:
            raise ValueError("REQUEST_TEXT_INVALID")
        normalized = " ".join(text.casefold().split())
        if any(item in normalized for item in _FORBIDDEN_TEXT):
            raise ValueError("LIVE_OR_UNSAFE_REQUEST_REJECTED")
        if any(item in normalized for item in _NEGATION_TEXT):
            raise ValueError("NEGATED_REQUEST_REJECTED")
        routed = EXACT_TEXT_ROUTES.get(normalized)
        if routed is None:
            raise ValueError("AMBIGUOUS_OR_UNKNOWN_REQUEST")
    if explicit is None:
        if routed is None:
            raise ValueError("ACTION_REQUIRED")
        return routed
    if not isinstance(explicit, str) or explicit not in ACTION_IDS:
        raise ValueError("ACTION_UNKNOWN")
    if routed is not None and routed != explicit:
        raise ValueError("ACTION_TEXT_CONFLICT")
    return explicit


def _validate_inputs(action: str, inputs: Mapping[str, Any]) -> None:
    if action == "qualify_and_report" or action in EXTERNAL_ACTIONS:
        expected: set[str] = set()
    elif action in {"inspect_current_blocker", "prepare_repair_task"}:
        expected = {"qualification_request_id"}
        _identifier(inputs.get("qualification_request_id"), "CHILD_REQUEST_ID_INVALID")
    elif action == "run_focused_validation":
        expected = {"validation_set"}
        if inputs.get("validation_set") not in FIXED_VALIDATIONS:
            raise ValueError("VALIDATION_SET_UNKNOWN")
    elif action == "update_receipt_state":
        expected = {"source_idempotency_key", "qualification_request_id"}
        _identifier(
            inputs.get("source_idempotency_key"), "SOURCE_IDEMPOTENCY_KEY_INVALID"
        )
        _identifier(inputs.get("qualification_request_id"), "CHILD_REQUEST_ID_INVALID")
    else:
        raise ValueError("ACTION_UNKNOWN")
    if set(inputs) != expected:
        raise ValueError("ACTION_INPUT_FIELDS_INVALID")


def validate_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("REQUEST_OBJECT_REQUIRED")
    if raw.get("schema_version") == LEGACY_REQUEST_SCHEMA:
        if set(raw) != LEGACY_FIELDS:
            raise ValueError("LEGACY_REQUEST_FIELDS_INVALID")
        request_id = _identifier(raw.get("request_id"), "REQUEST_ID_INVALID")
        raw = {
            "schema_version": REQUEST_SCHEMA,
            "request_id": request_id,
            "idempotency_key": request_id,
            "action": None,
            "text": raw.get("text"),
            "inputs": {},
            "proposal": None,
        }
    if set(raw) != REQUEST_FIELDS or raw.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("REQUEST_SCHEMA_OR_FIELDS_INVALID")
    request_id = _identifier(raw.get("request_id"), "REQUEST_ID_INVALID")
    idempotency_key = _identifier(
        raw.get("idempotency_key"), "IDEMPOTENCY_KEY_INVALID"
    )
    inputs = raw.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("REQUEST_INPUTS_INVALID")
    _safe_json(inputs)
    proposal = raw.get("proposal")
    if proposal is not None:
        if not isinstance(proposal, dict) or set(proposal) != {"source", "action"}:
            raise ValueError("PROPOSAL_INVALID")
        if proposal.get("source") not in {"model", "laya", "operator"}:
            raise ValueError("PROPOSAL_SOURCE_INVALID")
        if not isinstance(proposal.get("action"), str):
            raise ValueError("PROPOSAL_ACTION_INVALID")
    value = {
        "schema_version": REQUEST_SCHEMA,
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "action": raw.get("action"),
        "text": raw.get("text"),
        "inputs": dict(inputs),
        "proposal": dict(proposal) if isinstance(proposal, dict) else None,
    }
    value["action"] = route_request(value)
    _validate_inputs(str(value["action"]), value["inputs"])
    return value


def load_request(path: Path) -> dict[str, Any]:
    return validate_request(_read_json(path))


def _safe_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    names = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "LANG")
    env = {name: source[name] for name in names if name in source}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PAPER_TRADING_ONLY": "true",
            "LIVE_TRADING_ENABLED": "false",
        }
    )
    return env


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=_safe_environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("SOURCE_IDENTITY_UNAVAILABLE")
    return completed.stdout.strip()


def _check_source(repo: Path, expected_sha: str) -> dict[str, Any]:
    if SHA_RE.fullmatch(expected_sha) is None:
        raise ValueError("EXPECTED_SHA_INVALID")
    top = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if top != repo.resolve():
        raise ValueError("REPO_ROOT_MISMATCH")
    actual = _git(repo, "rev-parse", "HEAD")
    if actual != expected_sha:
        raise ValueError("STALE_SOURCE_SHA")
    if _git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("SOURCE_TREE_DIRTY")
    return {"git_sha": actual}


def _write_json(path: Path, value: object) -> None:
    text = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _verified_action_receipt(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("RECEIPT_SCHEMA_INVALID")
    claimed = payload.get("receipt_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    if claimed != _digest(unsigned):
        raise ValueError("RECEIPT_DIGEST_MISMATCH")
    return payload


def _qualification_receipt(
    output_root: Path, request_id: str, expected_sha: str
) -> dict[str, Any]:
    run = output_root / "qualification" / request_id
    receipt_path = run / "qualification_receipt.json"
    manifest_path = run / "run_manifest.json"
    receipt = _read_json(receipt_path)
    manifest = _read_json(manifest_path)
    if not isinstance(receipt, dict) or not isinstance(manifest, dict):
        raise ValueError("CHILD_RECEIPT_INVALID")
    if receipt.get("git_sha") != expected_sha:
        raise ValueError("CHILD_RECEIPT_STALE_SHA")
    if receipt.get("request_id") != request_id:
        raise ValueError("CHILD_RECEIPT_ID_MISMATCH")
    if manifest.get("state") != "COMPLETE":
        raise ValueError("CHILD_RUN_INCOMPLETE")
    actual_digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    if manifest.get("receipt_sha256") != actual_digest:
        raise ValueError("CHILD_RECEIPT_DIGEST_MISMATCH")
    if receipt.get("qualified") is not False:
        raise ValueError("QUALIFICATION_AUTHORITY_ESCALATION")
    if receipt.get("live_authorized") is not False:
        raise ValueError("LIVE_AUTHORITY_ESCALATION")
    if receipt.get("transactions_sent") != 0:
        raise ValueError("TRANSACTION_EFFECT_DETECTED")
    blockers = receipt.get("blockers")
    if not isinstance(blockers, list) or not all(
        isinstance(item, str) for item in blockers
    ):
        raise ValueError("CHILD_BLOCKERS_INVALID")
    return receipt


def _proposal_status(request: Mapping[str, Any]) -> dict[str, Any]:
    proposal = request.get("proposal")
    if not isinstance(proposal, Mapping):
        return {"present": False, "advisory_only": True, "matched": None}
    proposed = proposal.get("action")
    return {
        "present": True,
        "source": proposal.get("source"),
        "proposed_action": proposed,
        "recognized": proposed in ACTION_IDS,
        "matched": proposed == request["action"],
        "advisory_only": True,
    }


def _execute_qualification(
    request: Mapping[str, Any],
    repo: Path,
    output_root: Path,
    expected_sha: str,
    timeout: int,
) -> dict[str, Any]:
    from src.qualification_report import qualify_and_report

    child = qualify_and_report(
        repo_root=repo,
        output_root=output_root / "qualification",
        request_id=str(request["request_id"]),
        expected_sha=expected_sha,
        profile="offline_sender_free",
        timeout_seconds=timeout,
    )
    if child.get("git_sha") != expected_sha:
        raise ValueError("CHILD_RECEIPT_STALE_SHA")
    if child.get("live_authorized") is not False or child.get("transactions_sent") != 0:
        raise ValueError("CHILD_EFFECT_BOUNDARY_INVALID")
    receipt_path = (
        output_root
        / "qualification"
        / str(request["request_id"])
        / "qualification_receipt.json"
    )
    blockers = list(child.get("blockers", ()))
    return {
        "status": "INSPECTED",
        "domain_verdict": child.get("domain_verdict"),
        "sender_free_pass": bool(child.get("sender_free_pass")),
        "blockers": blockers,
        "first_blocker": blockers[0] if blockers else None,
        "child_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "next_action": (
            "inspect_current_blocker" if blockers else "review_sender_free_evidence"
        ),
        "limitations": [
            "installed inspection is not qualification or live authorization"
        ],
    }


def _inspect_blocker(
    request: Mapping[str, Any], output_root: Path, expected_sha: str
) -> dict[str, Any]:
    child_id = str(request["inputs"]["qualification_request_id"])
    child = _qualification_receipt(output_root, child_id, expected_sha)
    blockers = list(child["blockers"])
    first = blockers[0] if blockers else None
    return {
        "status": "BLOCKED" if first else "NO_CURRENT_BLOCKER",
        "first_blocker": first,
        "blocker_count": len(blockers),
        "next_action": (
            "prepare_repair_task" if first else "review_sender_free_evidence"
        ),
        "limitations": [],
    }


def _owner_for(blocker: str) -> dict[str, Any] | None:
    if blocker == "paper-shadow:blocked_missing_wallet_public_key":
        return {
            "owner_files": ["src/runtime_discovery_coordinator.py"],
            "owner_symbols": ["RuntimeDiscoveryCoordinator.run_cycle"],
            "focused_tests": [
                "tests/test_pr056_runtime_discovery.py",
                "tests/test_pr076_paper_shadow_exit_semantics.py",
            ],
            "patch_allowed": False,
            "stop_reason": "EXTERNAL_OPERATOR_INPUT_REQUIRED",
            "required_external_evidence": [
                "operator-provided public wallet address through canonical configuration"
            ],
        }
    generic = (
        ("status:", ["src/capabilities.py"]),
        ("capabilities:", ["src/capabilities.py"]),
        ("doctor:", ["src/config/doctor.py"]),
        ("admission:", ["src/automation_cli_pr189.py", "src/cli.py"]),
        (
            "paper-shadow:",
            ["src/paper_shadow/runner.py", "src/runtime_discovery_coordinator.py"],
        ),
    )
    for prefix, files in generic:
        if blocker.startswith(prefix):
            return {
                "owner_files": files,
                "owner_symbols": [],
                "focused_tests": [],
                "patch_allowed": False,
                "stop_reason": "OWNER_REVIEW_REQUIRED",
                "required_external_evidence": [],
            }
    return None


def _prepare_repair(
    request: Mapping[str, Any], output_root: Path, expected_sha: str
) -> dict[str, Any]:
    child_id = str(request["inputs"]["qualification_request_id"])
    child = _qualification_receipt(output_root, child_id, expected_sha)
    blockers = list(child["blockers"])
    if not blockers:
        return {
            "status": "NO_CURRENT_BLOCKER",
            "repair_task": None,
            "next_action": "review_sender_free_evidence",
            "limitations": ["no blocker to repair"],
        }
    blocker = blockers[0]
    owner = _owner_for(blocker)
    if owner is None:
        return {
            "status": "STOP_OWNER_UNRESOLVED",
            "repair_task": {
                "schema_version": REPAIR_TASK_SCHEMA,
                "source_commit": expected_sha,
                "first_blocker": blocker,
                "owner_files": [],
                "patch_allowed": False,
                "automatic_patch_performed": False,
                "stop_reason": "OWNER_UNRESOLVED",
            },
            "next_action": "resolve_owner_from_current_source",
            "limitations": ["owner unresolved; no patch attempted"],
        }
    task = {
        "schema_version": REPAIR_TASK_SCHEMA,
        "source_commit": expected_sha,
        "qualification_request_id": child_id,
        "first_blocker": blocker,
        **owner,
        "isolated_worktree_required": True,
        "max_changed_files": 3,
        "max_runtime_blockers_per_iteration": 1,
        "automatic_patch_performed": False,
        "disable_safety_gate_allowed": False,
        "synthetic_success_allowed": False,
        "live_or_sender_change_allowed": False,
    }
    return {
        "status": "REPAIR_TASK_PREPARED",
        "repair_task": task,
        "next_action": (
            "supply_required_external_evidence"
            if task["required_external_evidence"]
            else "review_bounded_patch"
        ),
        "limitations": ["repair task does not grant patch or merge authority"],
    }


def _run_command(argv: Sequence[str], repo: Path, timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        list(argv),
        cwd=repo,
        env=_safe_environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    stdout = completed.stdout[:MAX_OUTPUT]
    stderr = completed.stderr[:MAX_OUTPUT]
    return {
        "argv": [Path(argv[0]).name, *argv[1:]],
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_truncated": len(completed.stdout) > len(stdout),
        "stderr_truncated": len(completed.stderr) > len(stderr),
    }


def _run_validation(
    request: Mapping[str, Any], repo: Path, timeout: int
) -> dict[str, Any]:
    name = str(request["inputs"]["validation_set"])
    records = [_run_command(argv, repo, timeout) for argv in FIXED_VALIDATIONS[name]]
    passed = all(record["exit_code"] == 0 for record in records)
    return {
        "status": "TEST_PASSED" if passed else "TEST_FAILED",
        "validation_set": name,
        "tests": records,
        "next_action": "update_receipt_state" if passed else "fix_validation_failure",
        "limitations": [] if passed else ["validation failed; no success promoted"],
    }


def _update_state(
    request: Mapping[str, Any],
    claim: Path,
    output_root: Path,
    expected_sha: str,
) -> dict[str, Any]:
    source_key = str(request["inputs"]["source_idempotency_key"])
    child_id = str(request["inputs"]["qualification_request_id"])
    source = _verified_action_receipt(
        output_root / "actions" / source_key / "receipt.json"
    )
    child = _qualification_receipt(output_root, child_id, expected_sha)
    source_status = str(source["status"])
    state = {
        "schema_version": STATE_SCHEMA,
        "source_commit": expected_sha,
        "derived_from_receipt_sha256": source["receipt_sha256"],
        "status_ladder": {
            "planned": "CONFIRMED",
            "implemented": "CONFIRMED",
            "test_passed": (
                "CONFIRMED"
                if source.get("action") == "run_focused_validation"
                and source_status == "TEST_PASSED"
                else "NOT_EVIDENCED"
            ),
            "inspected": "CONFIRMED",
            "qualified": (
                "CONFIRMED" if child.get("qualified") is True else "NOT_QUALIFIED"
            ),
            "live_authorized": (
                "CONFIRMED"
                if child.get("live_authorized") is True
                else "NOT_AUTHORIZED"
            ),
        },
        "current_first_blocker": (child.get("blockers") or [None])[0],
        "transactions_sent": 0,
        "market_run_performed": False,
        "paid_api_fallback": False,
        "next_action": child.get("next_action"),
        "limitations": [
            "state is receipt-derived and does not infer qualification from tests"
        ],
    }
    state_path = claim / "state.json"
    _write_json(state_path, state)
    summary_path = claim / "STATUS_RU.txt"
    summary_path.write_text(
        "FAST-Q automation state\n"
        + "\n".join(
            f"{key}={value}" for key, value in state["status_ladder"].items()
        )
        + f"\ntransactions_sent=0\nfirst_blocker={state['current_first_blocker']}\n"
        + f"next_action={state['next_action']}\n",
        encoding="utf-8",
    )
    return {
        "status": "STATE_UPDATED",
        "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "status_ladder": state["status_ladder"],
        "next_action": state["next_action"],
        "limitations": state["limitations"],
    }


def _external_adapter(action: str) -> dict[str, Any]:
    operation = {
        "ingest_local_content": "ingest",
        "search_local_corpus": "search",
        "transcribe_local_audio": "transcribe",
    }[action]
    return {
        "status": "EXTERNAL_ADAPTER_REQUIRED",
        "adapter_contract": {
            "schema_version": ADAPTER_SCHEMA,
            "operation": operation,
            "core_execution_performed": False,
            "operator_configured_roots_required": True,
            "model_supplied_paths_allowed": False,
            "paid_api_fallback": False,
            "default_retrieval": "sqlite_fts" if operation == "search" else None,
            "heavy_dependencies_in_core": False,
            "optional_challengers": [
                "faster-whisper",
                "Docling",
                "Muse",
                "Qwen",
                "GLiNER",
                "embeddings",
            ],
        },
        "next_action": "execute_in_external_occ_or_worker_boundary",
        "limitations": ["core does not execute optional external adapters"],
    }


def _dispatch(
    request: Mapping[str, Any],
    repo: Path,
    output_root: Path,
    claim: Path,
    expected_sha: str,
    timeout: int,
) -> dict[str, Any]:
    action = str(request["action"])
    if action == "qualify_and_report":
        return _execute_qualification(request, repo, output_root, expected_sha, timeout)
    if action == "inspect_current_blocker":
        return _inspect_blocker(request, output_root, expected_sha)
    if action == "prepare_repair_task":
        return _prepare_repair(request, output_root, expected_sha)
    if action == "run_focused_validation":
        return _run_validation(request, repo, timeout)
    if action == "update_receipt_state":
        return _update_state(request, claim, output_root, expected_sha)
    if action in EXTERNAL_ACTIONS:
        return _external_adapter(action)
    raise ValueError("ACTION_UNKNOWN")


def execute_request(
    raw_request: object,
    *,
    repo_root: Path,
    output_root: Path,
    expected_sha: str,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    request = validate_request(raw_request)
    if (
        type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("TIMEOUT_INVALID")
    repo = repo_root.resolve()
    output = output_root.resolve()
    if output == repo or repo in output.parents:
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_CHECKOUT")
    source = _check_source(repo, expected_sha)
    output.mkdir(parents=True, exist_ok=True)
    actions = output / "actions"
    actions.mkdir(exist_ok=True)
    claim = actions / str(request["idempotency_key"])
    request_digest = _digest({"request": request, "source_commit": expected_sha})
    receipt_path = claim / "receipt.json"
    try:
        claim.mkdir()
    except FileExistsError:
        if claim.is_symlink() or not receipt_path.is_file():
            raise ValueError("ACTION_INCOMPLETE_OR_CONCURRENT") from None
        receipt = _verified_action_receipt(receipt_path)
        if (
            receipt.get("request_digest") != request_digest
            or receipt.get("source_commit") != expected_sha
        ):
            raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
        return {**receipt, "reused": True}

    started = _now()
    result = _dispatch(
        request, repo, output, claim, expected_sha, timeout_seconds
    )
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "request_id": request["request_id"],
        "idempotency_key": request["idempotency_key"],
        "request_digest": request_digest,
        "action": request["action"],
        "source_commit": source["git_sha"],
        "started_at": started,
        "ended_at": _now(),
        "status": result.get("status", "COMPLETE"),
        "evidence_kind": ACTION_REGISTRY[str(request["action"])]["evidence_kind"],
        "proposal": _proposal_status(request),
        "result": result,
        "output_sha256": _digest(result),
        "limitations": list(result.get("limitations", ())),
        "next_action": result.get("next_action"),
        "qualified": False,
        "live_authorized": False,
        "market_run_performed": False,
        "transactions_sent": 0,
        "paid_api_fallback": False,
    }
    receipt["receipt_sha256"] = _digest(receipt)
    _write_json(receipt_path, receipt)
    return {**receipt, "reused": False}


__all__ = [
    "ACTION_IDS",
    "ACTION_REGISTRY",
    "ADAPTER_SCHEMA",
    "EXACT_TEXT_ROUTES",
    "FIXED_VALIDATIONS",
    "LEGACY_REQUEST_SCHEMA",
    "RECEIPT_SCHEMA",
    "REPAIR_TASK_SCHEMA",
    "REQUEST_SCHEMA",
    "STATE_SCHEMA",
    "execute_request",
    "load_request",
    "route_request",
    "validate_request",
]
