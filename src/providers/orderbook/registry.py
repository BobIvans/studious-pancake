from __future__ import annotations
import json, pathlib
from .models import *

DEFAULT_REGISTRY_PATH = pathlib.Path(__file__).resolve().parents[3] / "docs" / "registry" / "orderbook_venues.json"
class VenueRegistry:
    def __init__(self, specs: tuple[VenueProgramSpec,...]): self.specs={s.venue_kind:s for s in specs}; self.by_program={s.program_id:s for s in specs}
    @classmethod
    def load(cls, path: pathlib.Path = DEFAULT_REGISTRY_PATH):
        raw=json.loads(path.read_text()); specs=[]
        for item in raw["venues"]:
            specs.append(VenueProgramSpec(VenueKind(item["venue_kind"]), item["cluster"], item["program_id"], item["source"], item["pinned_version"], item["artifact_sha256"], item["expected_owner"], bytes.fromhex(item["layout_discriminator_hex"]), int(item["min_data_len"]), int(item["max_data_len"]), tuple(item["supported_token_programs"]), bool(item["enabled_shadow"]), bool(item["enabled_live"]), item["status"], item["checked_at"], tuple(item["markets"])))
        expected=raw.get("registry_digest")
        reg=cls(tuple(specs))
        if expected and expected != reg.digest(): raise OrderbookReject(OrderbookRejectCode.VENUE_IDL_VERSION_MISMATCH,"registry digest mismatch")
        return reg
    def digest(self):
        import hashlib
        return hashlib.sha256("".join(s.verify_digest() for s in self.specs.values()).encode()).hexdigest()
    def require_supported(self, venue_kind: VenueKind, market: str)->VenueProgramSpec:
        s=self.specs.get(venue_kind)
        if not s: raise OrderbookReject(OrderbookRejectCode.UNKNOWN_VENUE_OR_POOL,"unknown venue")
        if not s.enabled_shadow or market not in s.markets: raise OrderbookReject(OrderbookRejectCode.MARKET_UNSUPPORTED,"market unsupported", {"market":market,"status":s.status})
        if s.enabled_live: raise OrderbookReject(OrderbookRejectCode.MARKET_UNSUPPORTED,"live must remain disabled")
        return s
