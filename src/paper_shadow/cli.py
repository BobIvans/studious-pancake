"""Installed shadow-soak command. Fixture mode is CI-only and fail-closed."""

from __future__ import annotations
import argparse, json, time
from pathlib import Path
from .service import DataLineage, SoakLedger, fixture_bindings, verify_soak


def _seconds(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        return float(value[:-1]) * units[value[-1]]
    except (ValueError, KeyError):
        raise argparse.ArgumentTypeError("duration must end in s, m, or h")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="flashloan-bot shadow-soak")
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    run.add_argument("--duration", required=True, type=_seconds)
    run.add_argument("--fixture-mode", action="store_true")
    run.add_argument("--output", default=".runtime/shadow-soak/latest")
    run.add_argument("--json", action="store_true")
    report = sub.add_parser("report")
    report.add_argument("--from", dest="source", required=True)
    report.add_argument("--minimum-hours", type=int, default=72)
    report.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.action == "report":
        payload = verify_soak(Path(a.source), minimum_hours=a.minimum_hours)
    else:
        if not a.fixture_mode:
            payload = {
                "status": "BLOCKED",
                "blockers": ["credentialed_provider_not_configured"],
                "promotion_eligible": False,
                "signer_available": False,
                "submission_available": False,
            }
        else:
            ledger = SoakLedger(Path(a.output))
            started = time.monotonic()
            n = 0
            while n == 0 or time.monotonic() - started < a.duration:
                ledger.append(
                    lineage=DataLineage.SYNTHETIC_FIXTURE, bindings=fixture_bindings(n)
                )
                n += 1
                time.sleep(min(0.1, a.duration))
            ledger.close()
            payload = verify_soak(Path(a.output))
            payload["fixture_mode"] = True
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload.get("verified", payload.get("status") != "BLOCKED") else 2
