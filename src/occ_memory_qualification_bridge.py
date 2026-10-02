"""Fail-closed OCC memory-to-qualification bridge for studious-pancake.

The bridge accepts only a typed OCC action envelope and a separately reviewed
operator profile. It never lets command/source text choose repository paths,
output paths, SHAs, timeouts, shell commands, credentials, or live permissions.
Execution is delegated to the existing FAST-Q1 v3 ``qualify_and_report`` owner.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

REQUEST_SCHEMA = "occ.qualification-action.v1"
PROFILE_SCHEMA = "studious-pancake.occ-qualification-profile.v1"
RECEIPT_SCHEMA = "studious-pancake.occ-memory-qualification-receipt.v1"
MANIFEST_SCHEMA = "studious-pancake.occ-memory-qualification-manifest.v1"
ACTION_ID = "qualify_and_report"
OCC_REPOSITORY = "BobIvans/scaling-chrome-extensions"
INSPECTOR_OWNER = "FAST-Q1-v3:src.qualification_report.qualify_and_report"
INNER_PROFILE = "offline_sender_free"
MAX_SOURCE_REFS = 32
MAX_TIMEOUT_SECONDS = 120

_REQUEST_FIELDS = {"schema_version", "request_id", "action_id", "text"}
_PROFILE_FIELDS = {
    "schema_version",
    "repo_root",
    "output_root",
    "expected_bot_sha",
    "timeout_seconds",
    "occ_repository",
    "occ_base_sha",
    "occ_head_sha",
    "source_refs",
}
_SOURCE_REF_FIELDS = {"source_id", "version", "sha256"}
_ALLOWED_TEXT = {
    "проверь готовность бота",
    "проверь квалификацию бота",
    "check bot readiness",
    "qualify and report",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    temporary.replace(path)


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("JSON_FILE_INVALID")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("JSON_TOO_LARGE")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("NON_FINITE_JSON_NUMBER")
        ),
    )


def validate_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != _REQUEST_FIELDS:
        raise ValueError("REQUEST_FIELDS_INVALID")
    if raw.get("schema_version") != REQUEST_SCHEMA or raw.get("action_id") != ACTION_ID:
        raise ValueError("ACTION_OR_SCHEMA_UNSUPPORTED")
    request_id = raw.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", request_id
    ):
        raise ValueError("REQUEST_ID_INVALID")
    text = raw.get("text")
    if not isinstance(text, str) or not 1 <= len(text) <= 256:
        raise ValueError("COMMAND_TEXT_INVALID")
    normalized = " ".join(text.strip().split()).casefold()
    if normalized not in _ALLOWED_TEXT:
        raise ValueError("COMMAND_INTENT_NOT_ADMITTED")
    return dict(raw)


def _validate_source_ref(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != _SOURCE_REF_FIELDS:
        raise ValueError("SOURCE_REF_FIELDS_INVALID")
    source_id = raw.get("source_id")
    version = raw.get("version")
    sha256 = raw.get("sha256")
    for value in (source_id, version):
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            raise ValueError("SOURCE_REF_IDENTIFIER_INVALID")
        if any(ord(char) < 32 for char in value):
            raise ValueError("SOURCE_REF_IDENTIFIER_INVALID")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("SOURCE_REF_SHA256_INVALID")
    return {"source_id": source_id, "version": version, "sha256": sha256}


def validate_operator_profile(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != _PROFILE_FIELDS:
        raise ValueError("OPERATOR_PROFILE_FIELDS_INVALID")
    if raw.get("schema_version") != PROFILE_SCHEMA:
        raise ValueError("OPERATOR_PROFILE_SCHEMA_UNSUPPORTED")
    if raw.get("occ_repository") != OCC_REPOSITORY:
        raise ValueError("OCC_REPOSITORY_UNSUPPORTED")
    for field in ("repo_root", "output_root"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise ValueError("OPERATOR_PATH_INVALID")
    for field in ("expected_bot_sha", "occ_base_sha", "occ_head_sha"):
        if not isinstance(raw.get(field), str) or not re.fullmatch(
            r"[0-9a-f]{40}", raw[field]
        ):
            raise ValueError("OPERATOR_SHA_INVALID")
    timeout = raw.get("timeout_seconds")
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise ValueError("TIMEOUT_INVALID")
    refs = raw.get("source_refs")
    if not isinstance(refs, list) or len(refs) > MAX_SOURCE_REFS:
        raise ValueError("SOURCE_REFS_INVALID")
    normalized_refs = [_validate_source_ref(item) for item in refs]
    if len({digest(item) for item in normalized_refs}) != len(normalized_refs):
        raise ValueError("SOURCE_REFS_DUPLICATE")
    return {**raw, "source_refs": normalized_refs}


def _validate_paths(
    profile: Mapping[str, Any], *, adapter_root: Path
) -> tuple[Path, Path]:
    root = Path(str(profile["repo_root"])).resolve(strict=True)
    expected_root = adapter_root.resolve(strict=True)
    if root != expected_root:
        raise ValueError("PROJECT_ROOT_MUST_MATCH_ADAPTER_CHECKOUT")

    raw_output = Path(str(profile["output_root"])).absolute()
    if any(path.is_symlink() for path in (raw_output, *raw_output.parents)):
        raise ValueError("OUTPUT_SYMLINK_BLOCKED")
    output = raw_output.resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_CHECKOUT")
    return root, output


def _invoke_qualifier(
    *,
    repo_root: Path,
    output_root: Path,
    request_id: str,
    expected_sha: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    from src.qualification_report import qualify_and_report

    return qualify_and_report(
        repo_root=repo_root,
        output_root=output_root,
        request_id=request_id,
        expected_sha=expected_sha,
        profile=INNER_PROFILE,
        timeout_seconds=timeout_seconds,
    )


def _verify_replay(
    *,
    run_dir: Path,
    manifest: Mapping[str, Any],
    request_sha256: str,
    operator_profile_sha256: str,
) -> dict[str, Any]:
    if manifest.get("request_sha256") != request_sha256 or manifest.get(
        "operator_profile_sha256"
    ) != operator_profile_sha256:
        raise ValueError("REQUEST_ID_INPUT_CONFLICT")
    if manifest.get("state") != "COMPLETE":
        raise ValueError("BRIDGE_INCOMPLETE_RECONCILE_BEFORE_RETRY")
    receipt_path = run_dir / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("BRIDGE_RECEIPT_MISSING")
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict):
        raise ValueError("BRIDGE_RECEIPT_INVALID")
    claimed = receipt.get("receipt_sha256")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if claimed != digest(unsigned) or claimed != manifest.get("receipt_sha256"):
        raise ValueError("BRIDGE_RECEIPT_INTEGRITY_FAILED")
    return receipt


def execute_request(
    raw_request: object,
    raw_operator_profile: object,
    *,
    adapter_root: Path,
    invoke: Callable[..., dict[str, Any]] = _invoke_qualifier,
) -> dict[str, Any]:
    request = validate_request(raw_request)
    profile = validate_operator_profile(raw_operator_profile)
    repo_root, output_root = _validate_paths(profile, adapter_root=adapter_root)
    output_root.mkdir(parents=True, exist_ok=True)

    bridge_root = output_root / "occ_memory_qualification"
    bridge_root.mkdir(exist_ok=True)
    run_dir = bridge_root / request["request_id"]
    request_sha256 = digest(request)
    profile_sha256 = digest(profile)

    try:
        run_dir.mkdir()
    except FileExistsError:
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise ValueError("BRIDGE_RUN_PATH_INVALID") from None
        manifest_path = run_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("BRIDGE_INCOMPLETE_RECONCILE_BEFORE_RETRY") from None
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("BRIDGE_MANIFEST_INVALID") from None
        receipt = _verify_replay(
            run_dir=run_dir,
            manifest=manifest,
            request_sha256=request_sha256,
            operator_profile_sha256=profile_sha256,
        )
        return {"replayed": True, "receipt": receipt}

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request_sha256,
        "operator_profile_sha256": profile_sha256,
        "state": "RUNNING",
        "inspector_owner": INSPECTOR_OWNER,
        "external_effects_permitted": False,
        "started_at": _now(),
        "updated_at": _now(),
    }
    _write_json(run_dir / "manifest.json", manifest)

    inner_output = output_root / "fast_q1_runs"
    try:
        inner = invoke(
            repo_root=repo_root,
            output_root=inner_output,
            request_id=request["request_id"],
            expected_sha=profile["expected_bot_sha"],
            timeout_seconds=profile["timeout_seconds"],
        )
    except Exception:
        manifest["state"] = "RECONCILIATION_REQUIRED"
        manifest["updated_at"] = _now()
        _write_json(run_dir / "manifest.json", manifest)
        raise

    if not isinstance(inner, dict):
        raise ValueError("QUALIFIER_RECEIPT_INVALID")
    if inner.get("request_id") != request["request_id"]:
        raise ValueError("QUALIFIER_REQUEST_ID_MISMATCH")
    if inner.get("git_sha") != profile["expected_bot_sha"]:
        raise ValueError("QUALIFIER_SOURCE_SHA_MISMATCH")
    for field in ("qualified", "release_authorized", "live_authorized"):
        if inner.get(field) is not False:
            raise ValueError("QUALIFIER_AUTHORITY_BOUNDARY_INVALID")
    if inner.get("transactions_sent") != 0:
        raise ValueError("QUALIFIER_TRANSACTION_BOUNDARY_INVALID")
    blockers = inner.get("blockers")
    if not isinstance(blockers, list) or not all(
        isinstance(item, str) for item in blockers
    ):
        raise ValueError("QUALIFIER_BLOCKERS_INVALID")
    domain_verdict = inner.get("domain_verdict")
    if domain_verdict not in {"BLOCKED", "PAPER_PASS"}:
        raise ValueError("QUALIFIER_DOMAIN_VERDICT_INVALID")

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "request_id": request["request_id"],
        "action_id": ACTION_ID,
        "command_text_sha256": hashlib.sha256(
            request["text"].encode("utf-8")
        ).hexdigest(),
        "source_refs": profile["source_refs"],
        "occ": {
            "repository": profile["occ_repository"],
            "base_sha": profile["occ_base_sha"],
            "head_sha": profile["occ_head_sha"],
        },
        "bot": {
            "expected_sha": profile["expected_bot_sha"],
            "observed_sha": inner["git_sha"],
            "inspector_owner": INSPECTOR_OWNER,
            "profile": INNER_PROFILE,
        },
        "execution_status": inner.get("execution_status"),
        "domain_verdict": domain_verdict,
        "reason_codes": blockers,
        "qualified": False,
        "release_authorized": False,
        "live_authorized": False,
        "transactions_sent": 0,
        "inner_receipt_sha256": digest(inner),
        "inner_receipt_relpath": (
            f"fast_q1_runs/{request['request_id']}/qualification_receipt.json"
        ),
        "limitations": [
            "source content is DATA_ONLY and is not executable input",
            "offline sender-free inspection only",
            "PAPER_PASS is not production qualification",
            "live authorization remains separate",
        ],
        "next_blocker": blockers[0] if blockers else None,
        "created_at": _now(),
    }
    receipt["receipt_sha256"] = digest(receipt)
    _write_json(run_dir / "receipt.json", receipt)

    manifest["state"] = "COMPLETE"
    manifest["receipt_sha256"] = receipt["receipt_sha256"]
    manifest["updated_at"] = _now()
    manifest["ended_at"] = _now()
    _write_json(run_dir / "manifest.json", manifest)
    return {"replayed": False, "receipt": receipt}


__all__ = [
    "ACTION_ID",
    "INSPECTOR_OWNER",
    "MANIFEST_SCHEMA",
    "OCC_REPOSITORY",
    "PROFILE_SCHEMA",
    "RECEIPT_SCHEMA",
    "REQUEST_SCHEMA",
    "execute_request",
    "read_json",
    "validate_operator_profile",
    "validate_request",
]
