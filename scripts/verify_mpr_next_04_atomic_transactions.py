"""Fail‑closed verifier for MPR‑NEXT‑04 atomic transaction boundary.

Ensures that economic authority methods wrap attempt creation,
capital reservation, fee/rent/tip reservation and event/outbox
persistence in one atomic SQLite transaction (`BEGIN IMMEDIATE`).

Current implementation: stub that always raises.
"""

import sys

def main() -> None:  # pragma: no cover
    raise SystemExit("MPR‑NEXT‑04 verifier stub — implementation pending; branch stays fail‑closed")

if __name__ == "__main__":
    main()
