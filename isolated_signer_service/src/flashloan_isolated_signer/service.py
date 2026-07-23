"""Status-only process entrypoint for the isolated signer foundation."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from .models import (
    COMPILE_TIME_SUBMISSION_ENABLED,
    REQUIRED_ROADMAP_PRS,
    SCHEMA_VERSION,
)


def status_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "roadmap_pr": "PR-08",
        "foundation_present": True,
        "compile_time_submission_enabled": COMPILE_TIME_SUBMISSION_ENABLED,
        "private_key_loader_present": False,
        "network_transport_implementation_present": False,
        "environment_activation_supported": False,
        "roadmap_prerequisites_required": list(REQUIRED_ROADMAP_PRS),
        "economic_success_classification_present": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flashloan-isolated-signer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.command != "status":
        parser.error("unsupported command")
    payload = status_payload()
    if args.as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
