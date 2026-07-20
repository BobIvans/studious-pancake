"""PR-023 QUARANTINE: fixture-only orderbook provider package."""

__runtime_capability__ = "fixture-only"
__quarantined__ = True

from .adapters import OpenBookV2VenueAdapter, PhoenixLegacyVenueAdapter
from .conformance import (
    OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
    OFFICIAL_PHOENIX_SOURCE_REPOSITORY,
    OFFICIAL_PHOENIX_VERIFY_COMMAND,
    PHOENIX_COMMON_CRATE,
)
from .lifecycle import VenueAccountLifecycleService
from .models import *
from .planner import OrderbookAmmCandidate, OrderbookAmmPlanner, PlannedOrderbookAmm
from .pr066_phoenix import (
    PhoenixPromotionDecision,
    PhoenixPromotionEvidence,
    PhoenixPromotionGate,
    evaluate_phoenix_shadow_promotion,
    require_phoenix_shadow_promotion,
)
from .quote import OrderbookQuoteEngine
from .registry import VenueRegistry
