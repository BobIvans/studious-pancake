"""Fail‑closed verifier for MPR‑NEXT‑04 crash‑recovery durability.

Injects crash points between economic authority stages to
verify that restart leaves no double‑spend, no stranded
reservation and no lost terminal outcome.

Current implementation: stub that always raises.
"""

import sys

def main() -> None:  # pragma: no cover
    raise SystemExit("MPR‑NEXT‑04 verifier stub — implementation pending; branch stays fail‑closed")

if __name__ == "__main__":
    main()
