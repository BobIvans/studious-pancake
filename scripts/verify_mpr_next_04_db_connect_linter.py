"""Fail‑closed verifier for MPR‑NEXT‑04.

This script fails unless every *active* runtime Python module
imports its database connection through the approved
`durable_economic_authority.db_factory()` helper.

Current implementation: stub that always raises.
"""

import sys

def main() -> None:  # pragma: no cover
    raise SystemExit("MPR‑NEXT‑04 verifier stub — implementation pending; branch stays fail‑closed")

if __name__ == "__main__":
    main()
