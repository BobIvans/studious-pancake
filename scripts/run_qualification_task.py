#!/usr/bin/env python3
"""JSON transport for the existing offline MPR-2611 qualification audit.

This is an adapter, not a campaign runner or a new qualification authority.
Receipts are historical: reuse a task ID to replay, or choose a new ID to audit
changed evidence. No model, network client, signer, or shell command is loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "qualification-task.v1"
RECEIPT_SCHEMA = "qualification-task-receipt.v1"
FIELDS = {
    "schema_version",
    "task_id",
    "action",
    "source_commit",
    "release_id",
    "repeat",
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_request(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        raise ValueError("REQUEST_FIELDS_INVALID")
    if raw["schema_version"] != SCHEMA or raw["action"] != "qualification.audit":
        raise ValueError("ACTION_OR_SCHEMA_UNSUPPORTED")
    for field in ("task_id", "release_id"):
        if not isinstance(raw[field], str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", raw[field]
        ):
            raise ValueError("REQUEST_IDENTIFIER_INVALID")
    if not isinstance(raw["source_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", raw["source_commit"]
    ):
        raise ValueError("SOURCE_COMMIT_INVALID")
    if type(raw["repeat"]) is not int or not 2 <= raw["repeat"] <= 5:
        raise ValueError("REPEAT_OUT_OF_BOUNDS")
    return dict(raw)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def read_json(path: Path) -> Any:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("JSON_TOO_LARGE")
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()


def _check_source(root: Path, request: Mapping[str, Any]) -> None:
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("PROJECT_ROOT_NOT_REPOSITORY_ROOT")
    if _git(root, "rev-parse", "HEAD") != request["source_commit"]:
        raise ValueError("SOURCE_COMMIT_MISMATCH")
    if _git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("SOURCE_TREE_DIRTY")


def _run_existing(root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    if root != ROOT:
        raise ValueError("PROJECT_ROOT_MUST_MATCH_ADAPTER_CHECKOUT")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.run_mpr2611_clean_qualification import run_repeated

    return run_repeated(
        root,
        release_id=request["release_id"],
        source_commit=request["source_commit"],
        repeat=request["repeat"],
    )


def execute_task(raw: object, *, root: Path, output_root: Path) -> dict[str, Any]:
    request = validate_request(raw)
    root = root.resolve()
    output_root = output_root.resolve()
    if output_root == root or root in output_root.parents:
        raise ValueError("RECEIPTS_MUST_BE_OUTSIDE_CHECKOUT")
    _check_source(root, request)
    output_root.mkdir(parents=True, exist_ok=True)
    task_dir = output_root / request["task_id"]
    receipt_path = task_dir / "receipt.json"
    # mkdir is the atomic claim. A failed/crashed claim is kept for inspection;
    # another delivery must not silently redo work with an unknown outcome.
    try:
        task_dir.mkdir()
    except FileExistsError:
        if task_dir.is_symlink() or not receipt_path.is_file():
            raise ValueError("TASK_INCOMPLETE_OR_CONCURRENT") from None
        receipt = read_json(receipt_path)
        if not isinstance(receipt, dict) or receipt.get("request") != request:
            raise ValueError("TASK_ID_CONFLICT")
        claimed_digest = receipt.get("receipt_sha256")
        unsigned = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if claimed_digest != digest(unsigned):
            raise ValueError("RECEIPT_DIGEST_MISMATCH")
        return {"replayed": True, "receipt": receipt}
    payload = _run_existing(root, request)
    _check_source(root, request)
    if payload.get("verified") is not True:
        raise ValueError("QUALIFICATION_AUDIT_UNSTABLE")
    passed = payload.get("production_qualification_passed")
    if type(passed) is not bool:
        raise ValueError("QUALIFICATION_RESULT_INVALID")
    if (
        payload.get("live_enabled") is not False
        or payload.get("release_claim_allowed") is not False
    ):
        raise ValueError("QUALIFICATION_EFFECT_BOUNDARY_INVALID")
    snapshot = payload["snapshot"]
    if (
        snapshot["source_commit"] != request["source_commit"]
        or snapshot["release_id"] != request["release_id"]
    ):
        raise ValueError("QUALIFICATION_IDENTITY_MISMATCH")
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "request": request,
        "request_sha256": digest(request),
        "status": "CHECKED_REVIEW_ELIGIBLE" if passed else "CHECKED_BLOCKED",
        "audit_only": True,
        "campaign_executed": False,
        "live_enabled": False,
        "release_claim_allowed": False,
        "missing_artifacts": snapshot["missing_artifacts"],
        "invalid_artifacts": snapshot["invalid_artifacts"],
        "open_debt_items": snapshot["open_debt_items"],
        "qualification": payload,
    }
    receipt["receipt_sha256"] = digest(receipt)
    temporary = task_dir / "receipt.tmp"
    temporary.write_bytes(canonical(receipt) + b"\n")
    temporary.replace(receipt_path)
    return {"replayed": False, "receipt": receipt}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = execute_task(
            read_json(args.request), root=ROOT, output_root=args.output_root
        )
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        # Report the error class only for unexpected OS failures; do not leak
        # arbitrary captured process output or local credential paths.
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "ERROR", "reason": reason}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 3 if result["receipt"]["status"] == "CHECKED_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
