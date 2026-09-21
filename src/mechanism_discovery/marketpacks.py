"""PR-355 default-off MarketPack registry; adapters do not grant execution rights."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .evidence_native_core import EvidenceNativeError, record

MARKETPACKS: Mapping[str, Mapping[str, str]] = {
    "MP-N01": {"name": "Boros Funding IRS", "mode": "read_only_replay"},
    "MP-N02": {"name": "Hybrid Liquidity Shape", "mode": "fork_and_replay_only"},
    "MP-N03": {"name": "M0 Programmable Cash", "mode": "read_only_shadow"},
    "MP-N04": {"name": "Ethena Synthetic Dollar", "mode": "research_only"},
    "MP-N05": {"name": "Tokenized Credit/RWA", "mode": "research_only"},
    "MP-N06": {"name": "Aave V4 Hub/Spoke", "mode": "fork_read_only"},
    "MP-N07": {"name": "Research Resources", "mode": "testnet_or_zero_cost_mock"},
    "MP-N08": {"name": "Proof-Carrying Research", "mode": "offline_only"},
    "MP-N09": {"name": "Incident Corpus", "mode": "offline_only"},
}


@dataclass(frozen=True, slots=True)
class MarketPackSpec:
    pack_id: str
    name: str
    mode: str
    state: str = "DISABLED"
    live_enabled: bool = False
    signer_access: bool = False
    submission_access: bool = False

    def __post_init__(self) -> None:
        row = MARKETPACKS.get(self.pack_id)
        if row is None or row["name"] != self.name or row["mode"] != self.mode:
            raise EvidenceNativeError("MARKETPACK_REGISTRY_MISMATCH")
        if self.state != "DISABLED" or self.live_enabled or self.signer_access or self.submission_access:
            raise EvidenceNativeError("MARKETPACK_EFFECT_BOUNDARY_UNSAFE")


def register_marketpack(pack_id: str) -> MarketPackSpec:
    row = MARKETPACKS.get(pack_id)
    if row is None:
        raise EvidenceNativeError("MARKETPACK_UNKNOWN")
    return MarketPackSpec(pack_id=pack_id, name=row["name"], mode=row["mode"])


def marketpack_receipt(pack_id: str):
    spec = register_marketpack(pack_id)
    return record(
        "marketpack_receipt",
        {
            "pack_id": spec.pack_id,
            "name": spec.name,
            "mode": spec.mode,
            "state": spec.state,
            "qualified": False,
            "authorized_live": False,
        },
    )
