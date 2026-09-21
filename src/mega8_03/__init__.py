"""MEGA8-03 offline Solana-worker and research-intelligence contracts.

The package is deliberately signer-free and does not own submission, capital,
release, or live-trading authority.  Child modules PR-186..PR-208 expose the
NF-493..NF-584 roadmap contracts while reusing existing canonical runtime owners.
"""

MEGA8_03_SCHEMA = "mega8-03.offline.v1"

__all__ = ["MEGA8_03_SCHEMA"]
