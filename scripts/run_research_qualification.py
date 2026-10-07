#!/usr/bin/env python3
"""Pinned SCE research command; finite offline model replay, no trading."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.market_data_evolution.qualification_dataset import (
    canonical,
    digest,
    file_digest,
    unique_json,
)
from src.research.occ_qualification import (
    REQUEST_SCHEMA,
    RECEIPT_SCHEMA,
    fields,
    handler_catalog,
    run_campaign,
    validate_config,
)


def source_identity(expected: str) -> None:
    for argv, wanted in (
        (["rev-parse", "HEAD"], expected),
        (["status", "--porcelain", "--untracked-files=normal"], ""),
    ):
        p = subprocess.run(
            ["git", "-C", str(ROOT), *argv],
            capture_output=True,
            check=False,
            timeout=15,
        )
        if p.returncode or p.stdout.decode("utf-8").strip() != wanted:
            raise ValueError("RESEARCH_SOURCE_REVISION_OR_TREE_DRIFT")


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as output:
        output.write(canonical(value) + b"\n")
        output.flush()
        import os

        os.fsync(output.fileno())
    temporary.replace(path)


def execute_request(request: dict, *, verify_source=source_identity) -> dict:
    fields(
        request,
        {
            "schema",
            "run_id",
            "source_commit",
            "dataset",
            "dataset_sha256",
            "config",
            "config_sha256",
            "output_root",
        },
    )
    if (
        request["schema"] != REQUEST_SCHEMA
        or not isinstance(request["run_id"], str)
        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request["run_id"])
    ):
        raise ValueError("RESEARCH_REQUEST_ID_OR_SCHEMA")
    if not isinstance(request["source_commit"], str) or not re.fullmatch(
        r"[a-f0-9]{40}", request["source_commit"]
    ):
        raise ValueError("RESEARCH_SOURCE_SHA_REQUIRED")
    for name in ("dataset_sha256", "config_sha256"):
        if not isinstance(request[name], str) or not re.fullmatch(
            r"[a-f0-9]{64}", request[name]
        ):
            raise ValueError("RESEARCH_INPUT_SHA256_REQUIRED")
    paths = {}
    for name in ("dataset", "config", "output_root"):
        if not isinstance(request[name], str) or not Path(request[name]).is_absolute():
            raise ValueError("ABSOLUTE_OPERATOR_PATH_REQUIRED")
        p = Path(request[name])
        if any(item.is_symlink() for item in (p, *p.parents)):
            raise ValueError("RESEARCH_SYMLINK_PATH_BLOCKED")
        paths[name] = p.resolve()
    output = paths["output_root"]
    if (
        output == ROOT
        or output.is_relative_to(ROOT)
        or any(
            p == output or p.is_relative_to(output)
            for k, p in paths.items()
            if k != "output_root"
        )
    ):
        raise ValueError("RESEARCH_OUTPUT_BOUNDARY")
    verify_source(request["source_commit"])
    for name in ("dataset", "config"):
        if file_digest(paths[name]) != request[name + "_sha256"]:
            raise ValueError("RESEARCH_INPUT_DRIFT")
    if paths["config"].stat().st_size > 64 * 1024:
        raise ValueError("RESEARCH_CONFIG_FRAME_BUDGET")
    config = validate_config(unique_json(paths["config"].read_bytes()))
    output.mkdir(parents=True, exist_ok=True)
    run = output / request["run_id"]
    request_hash = digest(request)
    try:
        run.mkdir()
    except FileExistsError:
        if run.is_symlink():
            raise ValueError("RESEARCH_RUN_PATH_INVALID") from None
        manifest_path = run / "manifest.json"
        receipt_path = run / "receipt.json"
        if (
            manifest_path.is_symlink()
            or receipt_path.is_symlink()
            or not manifest_path.is_file()
            or not receipt_path.is_file()
        ):
            raise ValueError("RESEARCH_RECONCILIATION_REQUIRED") from None
        manifest = unique_json(manifest_path.read_bytes())
        receipt = unique_json(receipt_path.read_bytes())
        if (
            manifest.get("request_sha256") != request_hash
            or receipt.get("request_sha256") != request_hash
        ):
            raise ValueError("RESEARCH_RUN_INPUT_CONFLICT")
        unsigned = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if (
            manifest.get("state") != "COMPLETE"
            or digest(unsigned) != receipt.get("receipt_sha256")
            or manifest.get("receipt_sha256") != receipt["receipt_sha256"]
        ):
            raise ValueError("RESEARCH_RECONCILIATION_REQUIRED")
        if file_digest(run / "trials.jsonl") != receipt["trials_sha256"]:
            raise ValueError("RESEARCH_TRIAL_ARTIFACT_CHANGED")
        return {"replayed": True, "receipt": receipt}
    write_json(
        run / "manifest.json", {"state": "STARTED", "request_sha256": request_hash}
    )
    try:
        report = run_campaign(
            paths["dataset"],
            config,
            expected_dataset_digest=request["dataset_sha256"],
            trials_path=run / "trials.jsonl",
        )
        verify_source(request["source_commit"])
        for name in ("dataset", "config"):
            if file_digest(paths[name]) != request[name + "_sha256"]:
                raise ValueError("RESEARCH_INPUT_DRIFT")
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "run_id": request["run_id"],
            "request_sha256": request_hash,
            "source_commit": request["source_commit"],
            "dataset_sha256": request["dataset_sha256"],
            "config_sha256": request["config_sha256"],
            "mode": "REPLAY",
            "origin": "OFFLINE_FIXTURE",
            "campaign_executed": report["campaign_executed"],
            "domain_status": report["status"],
            "report": report,
            "trials_sha256": file_digest(run / "trials.jsonl"),
            "live_enabled": False,
            "transactions_sent": 0,
            "release_authorized": False,
        }
        receipt["receipt_sha256"] = digest(receipt)
        write_json(run / "receipt.json", receipt)
        write_json(
            run / "manifest.json",
            {
                "state": "COMPLETE",
                "request_sha256": request_hash,
                "receipt_sha256": receipt["receipt_sha256"],
            },
        )
        return {"replayed": False, "receipt": receipt}
    except BaseException:
        write_json(
            run / "manifest.json",
            {"state": "RECONCILIATION_REQUIRED", "request_sha256": request_hash},
        )
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--catalog", action="store_true")
    group.add_argument("--request", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.catalog:
            result = handler_catalog()
        else:
            if args.request.is_symlink() or args.request.stat().st_size > 64 * 1024:
                raise ValueError("RESEARCH_REQUEST_FRAME_BUDGET")
            result = execute_request(unique_json(args.request.read_bytes()))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                {
                    "state": "BLOCKED",
                    "reason": (
                        str(exc)
                        if isinstance(exc, ValueError)
                        and re.fullmatch(r"[A-Z_]{1,100}", str(exc))
                        else "RESEARCH_COMMAND_FAILED"
                    ),
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
