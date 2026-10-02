#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys


def verify(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "pr189.command-result.v1":
        raise SystemExit("FAST_Q1_SMOKE_RESULT_SCHEMA_MISMATCH")
    if payload.get("command") != "qualify-and-report":
        raise SystemExit("FAST_Q1_SMOKE_COMMAND_MISMATCH")
    if payload.get("command_mode") != "inspect":
        raise SystemExit("FAST_Q1_SMOKE_MODE_MISMATCH")
    details = payload.get("details")
    if not isinstance(details, dict):
        raise SystemExit("FAST_Q1_SMOKE_DETAILS_REQUIRED")
    for key in ("qualified", "release_authorized", "live_authorized"):
        if details.get(key) is not False:
            raise SystemExit(f"FAST_Q1_SMOKE_UNSAFE_FLAG:{key}")
    if details.get("transactions_sent") != 0:
        raise SystemExit("FAST_Q1_SMOKE_TRANSACTIONS_SENT")
    run = Path(str(details.get("run_directory", "")))
    for name in (
        "baseline.json",
        "run_manifest.json",
        "qualification_receipt.json",
        "BLOCKERS_RU.txt",
    ):
        if not (run / name).is_file():
            raise SystemExit(f"FAST_Q1_SMOKE_ARTIFACT_MISSING:{name}")
    print(
        json.dumps(
            {
                "schema": "fast-q1-v3.smoke-verification.v1",
                "ok": True,
                "domain_verdict": details.get("domain_verdict"),
                "sender_free_pass": details.get("sender_free_pass"),
                "blockers": details.get("blockers", []),
                "transactions_sent": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_fast_q1_smoke.py RESULT_JSON")
    verify(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
