from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from .store import ObservabilityStore

TERMINAL_EVENT_TYPES = frozenset(
    {
        "attempt_terminal",
        "balance_reconciled",
        "reconciliation_completed",
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline deterministic PR-017/PR-132 event replay"
    )
    parser.add_argument("--db", required=False, help="SQLite observability database")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--event-id")
    group.add_argument("--opportunity-id")
    group.add_argument("--attempt-id")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--what-if", help="named non-authoritative parameter set")
    return parser


def replay_event_rows(rows: list[Any], *, verify: bool = False) -> dict[str, object]:
    previous_sequence = -1
    divergences: list[dict[str, object]] = []
    timeline: list[dict[str, object]] = []
    terminal_seen = False

    for row in rows:
        if row["sequence_no"] <= previous_sequence:
            divergences.append(
                {
                    "code": "ORDERING_DIVERGENCE",
                    "event_id": row["event_id"],
                }
            )
        previous_sequence = row["sequence_no"]

        payload = json.loads(row["payload_json"])
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        if verify and digest != row["payload_digest"]:
            divergences.append(
                {
                    "code": "PAYLOAD_DIGEST_DIVERGENCE",
                    "event_id": row["event_id"],
                }
            )

        if verify and terminal_seen and row["event_type"] not in TERMINAL_EVENT_TYPES:
            divergences.append(
                {
                    "code": "TERMINAL_STATE_REGRESSION",
                    "event_id": row["event_id"],
                }
            )
        if row["event_type"] in TERMINAL_EVENT_TYPES:
            terminal_seen = True

        timeline.append(
            {
                "event_id": row["event_id"],
                "sequence_no": row["sequence_no"],
                "event_type": row["event_type"],
                "reason_code": row["reason_code"],
                "outcome": row["outcome"],
                "stage": row["stage"],
                "config_checksum": row["config_checksum"],
                "contract_fixture_version": row["contract_fixture_version"],
                "payload_digest": row["payload_digest"],
            }
        )

    decision_replay_hash = hashlib.sha256(
        json.dumps(
            timeline,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "network_free": True,
        "timeline": timeline,
        "divergences": divergences,
        "decision_replay_hash": decision_replay_hash,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.db:
        return 0

    store = ObservabilityStore(args.db)
    if args.event_id:
        row = store.db.execute(
            "SELECT * FROM event_log WHERE event_id=?",
            (args.event_id,),
        ).fetchone()
        rows = [row] if row else []
    elif args.attempt_id:
        rows = store.events_for(attempt_id=args.attempt_id)
    elif args.opportunity_id:
        rows = store.events_for(opportunity_id=args.opportunity_id)
    else:
        print("selector required", file=sys.stderr)
        return 2

    if not rows:
        print("no matching event stream", file=sys.stderr)
        return 3

    output = replay_event_rows(rows, verify=args.verify)
    output["what_if"] = args.what_if or None
    if args.format == "json":
        print(json.dumps(output, sort_keys=True))
    else:
        print("# Offline replay\n")
        for event in output["timeline"]:
            print(
                f"{event['sequence_no']}: {event['event_type']} "
                f"outcome={event['outcome']} reason={event['reason_code']} "
                f"digest={event['payload_digest']}"
            )
        if output["divergences"]:
            print("DIVERGENCES: " + json.dumps(output["divergences"]))
        print(f"decision_replay_hash={output['decision_replay_hash']}")
    return 4 if output["divergences"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
