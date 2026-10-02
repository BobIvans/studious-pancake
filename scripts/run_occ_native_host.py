#!/usr/bin/env python3
"""Strict OCC native-host transport over the existing qualification task owner.

The host accepts one registered audit action, pins it to a durable context
version, and delegates execution to ``scripts.run_qualification_task``.  It is
not a second queue, scheduler, shell, signer, or live-execution authority.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any, Callable, Collection, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.occ_durable_library import (
    OCCDurableError,
    OCCDurableLibrary,
    canonical_json,
    digest,
)

SCHEMA = "occ.native-host-request.v1"
RECEIPT_SCHEMA = "occ.native-host-receipt.v1"
MAX_NATIVE_MESSAGE = 1024 * 1024
FIELDS = {
    "schema_version",
    "job_id",
    "action_id",
    "namespace",
    "source_id",
    "context_version_sha256",
    "source_commit",
    "release_id",
    "repeat",
}
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


class OCCNativeHostError(ValueError):
    """Raised when the host request or durable receipt is invalid."""


Delegate = Callable[[object, Path, Path], Mapping[str, Any]]


def _identifier(field: str, value: object) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise OCCNativeHostError(f"{field.upper()}_INVALID")
    return value


def validate_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        raise OCCNativeHostError("REQUEST_FIELDS_INVALID")
    if raw["schema_version"] != SCHEMA:
        raise OCCNativeHostError("REQUEST_SCHEMA_UNSUPPORTED")
    if raw["action_id"] != "qualification.audit":
        raise OCCNativeHostError("ACTION_UNREGISTERED")
    for field in ("job_id", "namespace", "source_id", "release_id"):
        _identifier(field, raw[field])
    if (
        not isinstance(raw["context_version_sha256"], str)
        or _SHA256_RE.fullmatch(raw["context_version_sha256"]) is None
    ):
        raise OCCNativeHostError("CONTEXT_VERSION_INVALID")
    if (
        not isinstance(raw["source_commit"], str)
        or _COMMIT_RE.fullmatch(raw["source_commit"]) is None
    ):
        raise OCCNativeHostError("SOURCE_COMMIT_INVALID")
    if type(raw["repeat"]) is not int or not 2 <= raw["repeat"] <= 5:
        raise OCCNativeHostError("REPEAT_OUT_OF_BOUNDS")
    return dict(raw)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OCCNativeHostError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_NATIVE_MESSAGE:
        raise OCCNativeHostError("JSON_TOO_LARGE")
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )


def read_native_message(stream: Any) -> Any:
    header = stream.read(4)
    if len(header) != 4:
        raise OCCNativeHostError("NATIVE_FRAME_HEADER_INVALID")
    (length,) = struct.unpack("<I", header)
    if length <= 0 or length > MAX_NATIVE_MESSAGE:
        raise OCCNativeHostError("NATIVE_FRAME_SIZE_INVALID")
    payload = stream.read(length)
    if len(payload) != length:
        raise OCCNativeHostError("NATIVE_FRAME_TRUNCATED")
    return json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)


def write_native_message(stream: Any, value: object) -> None:
    raw = canonical_json(value).encode("utf-8")
    if len(raw) > MAX_NATIVE_MESSAGE:
        raise OCCNativeHostError("NATIVE_RESPONSE_TOO_LARGE")
    stream.write(struct.pack("<I", len(raw)))
    stream.write(raw)
    stream.flush()


def _default_delegate(raw: object, root: Path, output_root: Path) -> Mapping[str, Any]:
    from scripts import run_qualification_task as adapter

    return adapter.execute_task(raw, root=root, output_root=output_root)


def _atomic_write(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_host_receipt(path: Path, request: Mapping[str, Any]) -> Mapping[str, Any]:
    receipt = read_json(path)
    if not isinstance(receipt, dict) or receipt.get("host_request") != request:
        raise OCCNativeHostError("JOB_ID_CONFLICT")
    claimed = receipt.get("receipt_sha256")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if claimed != digest(unsigned):
        raise OCCNativeHostError("RECEIPT_DIGEST_MISMATCH")
    return receipt


def _context_view(version: Any) -> Mapping[str, Any]:
    return {
        "namespace": version.namespace,
        "source_id": version.source_id,
        "version_sha256": version.version_sha256,
        "content_sha256": version.content_sha256,
        "byte_length": version.byte_length,
        "first_seen_event_seq": version.first_seen_event_seq,
    }


def execute_host_request(
    raw: object,
    *,
    root: Path,
    output_root: Path,
    context_db: Path,
    allowed_namespaces: Collection[str],
    delegate: Delegate | None = None,
) -> Mapping[str, Any]:
    request = validate_request(raw)
    root = root.resolve()
    output_root = output_root.resolve()
    context_db = context_db.resolve()
    if output_root == root or root in output_root.parents:
        raise OCCNativeHostError("RECEIPTS_MUST_BE_OUTSIDE_CHECKOUT")
    if context_db == root or root in context_db.parents:
        raise OCCNativeHostError("CONTEXT_DB_MUST_BE_OUTSIDE_CHECKOUT")

    library = OCCDurableLibrary(context_db)
    job_dir = output_root / request["job_id"]
    host_receipt_path = job_dir / "occ_host_receipt.json"
    delegated_receipt_path = job_dir / "receipt.json"

    if host_receipt_path.is_file():
        library.get_version(
            namespace=request["namespace"],
            source_id=request["source_id"],
            version_sha256=request["context_version_sha256"],
            allowed_namespaces=allowed_namespaces,
        )
        return {
            "replayed": True,
            "receipt": _load_host_receipt(host_receipt_path, request),
        }

    stop_path = job_dir / "STOP"
    if stop_path.is_file():
        version = library.get_version(
            namespace=request["namespace"],
            source_id=request["source_id"],
            version_sha256=request["context_version_sha256"],
            allowed_namespaces=allowed_namespaces,
        )
        job_dir.mkdir(parents=True, exist_ok=True)
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA,
            "host_request": request,
            "host_request_sha256": digest(request),
            "context": _context_view(version),
            "delegated_owner": "scripts.run_qualification_task",
            "delegated_receipt_sha256": None,
            "job_state": "CANCELLED_BEFORE_DISPATCH",
            "local_test_verdict": "NOT_RUN",
            "ci_evidence": {"kind": "EXTERNAL_EXACT_HEAD", "verdict": "NOT_RUN"},
            "blocker": "OPERATOR_STOP_PRESENT",
            "next_action": "CREATE_NEW_JOB_ID_AFTER_REVIEW",
            "live_authorized": False,
            "release_authorized": False,
        }
        receipt["receipt_sha256"] = digest(receipt)
        _atomic_write(host_receipt_path, receipt)
        return {"replayed": False, "receipt": receipt}

    if delegated_receipt_path.is_file():
        version = library.get_version(
            namespace=request["namespace"],
            source_id=request["source_id"],
            version_sha256=request["context_version_sha256"],
            allowed_namespaces=allowed_namespaces,
        )
    elif job_dir.exists():
        raise OCCNativeHostError("NEEDS_RECONCILIATION")
    else:
        version = library.verify_current_version(
            namespace=request["namespace"],
            source_id=request["source_id"],
            version_sha256=request["context_version_sha256"],
            allowed_namespaces=allowed_namespaces,
        )

    task = {
        "schema_version": "qualification-task.v1",
        "task_id": request["job_id"],
        "action": "qualification.audit",
        "source_commit": request["source_commit"],
        "release_id": request["release_id"],
        "repeat": request["repeat"],
    }
    runner = _default_delegate if delegate is None else delegate
    try:
        delegated = runner(task, root, output_root)
    except ValueError as exc:
        if str(exc) == "TASK_INCOMPLETE_OR_CONCURRENT":
            raise OCCNativeHostError("NEEDS_RECONCILIATION") from None
        raise

    if not isinstance(delegated, Mapping) or not isinstance(
        delegated.get("receipt"), Mapping
    ):
        raise OCCNativeHostError("DELEGATED_RESULT_INVALID")
    inner = delegated["receipt"]
    inner_digest = inner.get("receipt_sha256")
    if not isinstance(inner_digest, str) or _SHA256_RE.fullmatch(inner_digest) is None:
        raise OCCNativeHostError("DELEGATED_RECEIPT_INVALID")
    status = inner.get("status")
    if status not in {"CHECKED_BLOCKED", "CHECKED_REVIEW_ELIGIBLE"}:
        raise OCCNativeHostError("DELEGATED_STATUS_INVALID")

    blockers = tuple(
        str(value)
        for key in ("missing_artifacts", "invalid_artifacts", "open_debt_items")
        for value in inner.get(key, ())
    )
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "host_request": request,
        "host_request_sha256": digest(request),
        "context": _context_view(version),
        "delegated_owner": "scripts.run_qualification_task",
        "delegated_receipt_sha256": inner_digest,
        "job_state": status,
        "local_test_verdict": (
            "PASS" if status == "CHECKED_REVIEW_ELIGIBLE" else "BLOCKED"
        ),
        "ci_evidence": {"kind": "EXTERNAL_EXACT_HEAD", "verdict": "NOT_EMBEDDED"},
        "blocker": blockers[0] if blockers else None,
        "next_action": (
            "RUN_EXACT_HEAD_CI_AND_REVIEW"
            if status == "CHECKED_REVIEW_ELIGIBLE"
            else "RESOLVE_BLOCKERS_AND_USE_NEW_JOB_ID"
        ),
        "live_authorized": False,
        "release_authorized": False,
    }
    receipt["receipt_sha256"] = digest(receipt)
    if not job_dir.is_dir():
        raise OCCNativeHostError("DELEGATED_RECEIPT_DIRECTORY_MISSING")
    if host_receipt_path.exists():
        existing = _load_host_receipt(host_receipt_path, request)
        if existing != receipt:
            raise OCCNativeHostError("HOST_RECEIPT_CONFLICT")
    else:
        _atomic_write(host_receipt_path, receipt)
    return {"replayed": bool(delegated.get("replayed")), "receipt": receipt}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", type=Path)
    mode.add_argument("--native", action="store_true")
    parser.add_argument("--context-db", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--allow-namespace", action="append", required=True)
    args = parser.parse_args(argv)

    try:
        raw = (
            read_native_message(sys.stdin.buffer)
            if args.native
            else read_json(args.request)
        )
        result = execute_host_request(
            raw,
            root=ROOT,
            output_root=args.output_root,
            context_db=args.context_db,
            allowed_namespaces=frozenset(args.allow_namespace),
        )
    except (OCCDurableError, OCCNativeHostError, ValueError, OSError, KeyError) as exc:
        payload = {"status": "ERROR", "reason": str(exc)}
        if args.native:
            write_native_message(sys.stdout.buffer, payload)
        else:
            print(canonical_json(payload))
        return 2

    if args.native:
        write_native_message(sys.stdout.buffer, result)
    else:
        print(canonical_json(result))
    return 3 if result["receipt"]["job_state"] == "CHECKED_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
