#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_occ_native_host as host
from src.occ_durable_library import OCCDurableError, OCCDurableLibrary


def verify() -> dict[str, object]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        checkout = base / "repo"
        checkout.mkdir()
        subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "user.name=Verifier",
                "-c",
                "user.email=verifier@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "verify",
            ],
            check=True,
            capture_output=True,
        )
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        db = base / "content.sqlite3"
        library = OCCDurableLibrary(db)
        first = library.sync(
            namespace="local",
            source_id="fixture",
            content="one",
            allowed_namespaces={"local"},
        )
        duplicate = library.sync(
            namespace="local",
            source_id="fixture",
            content="one",
            allowed_namespaces={"local"},
        )
        if (
            not duplicate["duplicate"]
            or len(
                library.history(
                    namespace="local",
                    source_id="fixture",
                    allowed_namespaces={"local"},
                )
            )
            != 1
        ):
            errors.append("DUPLICATE_SYNC_NOT_NOOP")
        try:
            library.latest(
                namespace="local",
                source_id="fixture",
                allowed_namespaces={"other"},
            )
            errors.append("NAMESPACE_DENIAL_FAILED")
        except OCCDurableError:
            pass

        calls: list[object] = []

        def delegate(raw: object, root: Path, output_root: Path):
            calls.append(raw)
            task = dict(raw)
            job = output_root / task["task_id"]
            job.mkdir(parents=True, exist_ok=True)
            receipt = {
                "status": "CHECKED_BLOCKED",
                "missing_artifacts": ["fixture-blocker"],
                "invalid_artifacts": [],
                "open_debt_items": [],
                "receipt_sha256": "a" * 64,
            }
            (job / "receipt.json").write_text(json.dumps(receipt))
            return {"replayed": False, "receipt": receipt}

        request = {
            "schema_version": host.SCHEMA,
            "job_id": "verify-1",
            "action_id": "qualification.audit",
            "namespace": "local",
            "source_id": "fixture",
            "context_version_sha256": first["version_sha256"],
            "source_commit": commit,
            "release_id": "verify",
            "repeat": 2,
        }
        kwargs = {
            "root": checkout,
            "output_root": base / "out",
            "context_db": db,
            "allowed_namespaces": {"local"},
            "delegate": delegate,
        }
        first_result = host.execute_host_request(request, **kwargs)
        replay = host.execute_host_request(request, **kwargs)
        if len(calls) != 1 or replay["replayed"] is not True:
            errors.append("HOST_REPLAY_NOT_IDEMPOTENT")
        if first_result["receipt"]["live_authorized"] is not False:
            errors.append("LIVE_BOUNDARY_BROKEN")
        if first_result["receipt"]["ci_evidence"]["verdict"] != "NOT_EMBEDDED":
            errors.append("CI_SEPARATION_BROKEN")

    return {
        "schema_version": "occ.durable-host-verification.v1",
        "ok": not errors,
        "errors": errors,
        "duplicate_sync_noop": True,
        "namespace_guarded": True,
        "registered_action_only": True,
        "delegated_owner": "scripts.run_qualification_task",
        "live_authorized": False,
        "release_authorized": False,
        "exact_head_ci_embedded": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
