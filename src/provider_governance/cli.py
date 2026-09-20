"""Validate external connection references offline; never read credentials."""

from __future__ import annotations
import argparse
import json
from src.provider_governance.profile import (
    load_connection_profile,
    ConnectionProfileError,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile")
    args = parser.parse_args(argv)
    try:
        profile = load_connection_profile(args.profile)
    except ConnectionProfileError as exc:
        print(json.dumps({"valid": False, "reason": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "profile_sha256": profile.profile_sha256,
                "reviewed_outbound_profiles": len(profile.entitlements),
                "statuses": dict(profile.statuses),
                "network_effects": 0,
                "secrets_loaded": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
