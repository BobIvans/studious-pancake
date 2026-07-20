from __future__ import annotations

import json
import pathlib

from .conformance import ensure_pr049_default_conformance
from .models import OrderbookReject, OrderbookRejectCode, VenueKind, VenueProgramSpec

DEFAULT_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docs"
    / "registry"
    / "orderbook_venues.json"
)


class VenueRegistry:
    def __init__(self, specs: tuple[VenueProgramSpec, ...]):
        self.specs = {spec.venue_kind: spec for spec in specs}
        self.by_program = {spec.program_id: spec for spec in specs}

    @classmethod
    def load(cls, path: pathlib.Path = DEFAULT_REGISTRY_PATH):
        raw = json.loads(path.read_text(encoding="utf-8"))
        specs: list[VenueProgramSpec] = []
        for item in raw["venues"]:
            specs.append(
                VenueProgramSpec(
                    VenueKind(item["venue_kind"]),
                    item["cluster"],
                    item["program_id"],
                    item["source"],
                    item["pinned_version"],
                    item["artifact_sha256"],
                    item["expected_owner"],
                    bytes.fromhex(item["layout_discriminator_hex"]),
                    int(item["min_data_len"]),
                    int(item["max_data_len"]),
                    tuple(item["supported_token_programs"]),
                    bool(item["enabled_shadow"]),
                    bool(item["enabled_live"]),
                    item["status"],
                    item["checked_at"],
                    tuple(item["markets"]),
                )
            )
        expected = raw.get("registry_digest")
        reg = cls(tuple(specs))
        if path == DEFAULT_REGISTRY_PATH:
            ensure_pr049_default_conformance(tuple(specs))
        if expected and expected != reg.digest():
            raise OrderbookReject(
                OrderbookRejectCode.VENUE_IDL_VERSION_MISMATCH,
                "registry digest mismatch",
            )
        return reg

    def digest(self):
        import hashlib

        return hashlib.sha256(
            "".join(spec.verify_digest() for spec in self.specs.values()).encode()
        ).hexdigest()

    def require_supported(
        self, venue_kind: VenueKind, market: str
    ) -> VenueProgramSpec:
        spec = self.specs.get(venue_kind)
        if not spec:
            raise OrderbookReject(OrderbookRejectCode.UNKNOWN_VENUE_OR_POOL, "unknown venue")
        if not spec.enabled_shadow or market not in spec.markets:
            raise OrderbookReject(
                OrderbookRejectCode.MARKET_UNSUPPORTED,
                "market unsupported",
                {"market": market, "status": spec.status},
            )
        if spec.enabled_live:
            raise OrderbookReject(
                OrderbookRejectCode.MARKET_UNSUPPORTED,
                "live must remain disabled",
            )
        return spec
