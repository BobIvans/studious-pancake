"""PR-066 Phoenix-first promotion evidence boundary.

This module intentionally does not enable OpenBook v2 or live trading.  It gives
operators and CI a deterministic way to decide whether a Phoenix market can move
from the PR-049 fail-closed registry into shadow-only consideration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .conformance import (
    OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
    OFFICIAL_PHOENIX_SOURCE_REPOSITORY,
    OFFICIAL_PHOENIX_VERIFY_COMMAND,
)
from .models import OrderbookReject, OrderbookRejectCode, VenueKind, VenueProgramSpec


class PhoenixPromotionGate(StrEnum):
    OFFICIAL_PROGRAM_ID = "official-program-id"
    VERIFIED_BUILD = "verified-build"
    MARKET_OWNER = "market-owner"
    MARKET_LAYOUT = "market-layout"
    GOLDEN_RPC_ACCOUNT = "golden-rpc-account"
    LOT_AND_FEE_MATH = "lot-and-fee-math"
    IOC_POSTCONDITIONS = "ioc-postconditions"
    SHADOW_SOAK = "shadow-soak"


_REQUIRED_GATES: tuple[PhoenixPromotionGate, ...] = tuple(PhoenixPromotionGate)


@dataclass(frozen=True, slots=True)
class PhoenixPromotionEvidence:
    market: str
    program_id: str
    source_repository: str
    verify_command: str
    market_owner: str
    layout_sha256: str
    golden_account_sha256: str
    lot_fee_vector_sha256: str
    ioc_postcondition_sha256: str
    shadow_soak_evidence_sha256: str
    gates: Mapping[PhoenixPromotionGate, bool]

    @property
    def missing_gates(self) -> tuple[PhoenixPromotionGate, ...]:
        return tuple(gate for gate in _REQUIRED_GATES if not self.gates.get(gate, False))

    @property
    def promotion_ready(self) -> bool:
        return not self.missing_gates


@dataclass(frozen=True, slots=True)
class PhoenixPromotionDecision:
    market: str
    shadow_allowed: bool
    live_allowed: bool
    missing_gates: tuple[str, ...]
    diagnostics: Mapping[str, object]


def evaluate_phoenix_shadow_promotion(
    spec: VenueProgramSpec,
    evidence: PhoenixPromotionEvidence,
) -> PhoenixPromotionDecision:
    """Return a fail-closed Phoenix shadow-promotion decision.

    The decision is deliberately narrower than execution readiness: even a fully
    satisfied Phoenix shadow-promotion manifest cannot enable live execution and
    cannot promote OpenBook v2.
    """

    _ensure_phoenix_only(spec)
    missing: list[PhoenixPromotionGate] = list(evidence.missing_gates)

    if evidence.program_id != OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID:
        missing.append(PhoenixPromotionGate.OFFICIAL_PROGRAM_ID)
    if spec.program_id != OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID:
        missing.append(PhoenixPromotionGate.OFFICIAL_PROGRAM_ID)
    if evidence.market_owner != OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID:
        missing.append(PhoenixPromotionGate.MARKET_OWNER)
    if spec.expected_owner != OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID:
        missing.append(PhoenixPromotionGate.MARKET_OWNER)
    if evidence.source_repository != OFFICIAL_PHOENIX_SOURCE_REPOSITORY:
        missing.append(PhoenixPromotionGate.VERIFIED_BUILD)
    if OFFICIAL_PHOENIX_VERIFY_COMMAND not in evidence.verify_command:
        missing.append(PhoenixPromotionGate.VERIFIED_BUILD)
    if not _is_sha256(evidence.layout_sha256):
        missing.append(PhoenixPromotionGate.MARKET_LAYOUT)
    if not _is_sha256(evidence.golden_account_sha256):
        missing.append(PhoenixPromotionGate.GOLDEN_RPC_ACCOUNT)
    if not _is_sha256(evidence.lot_fee_vector_sha256):
        missing.append(PhoenixPromotionGate.LOT_AND_FEE_MATH)
    if not _is_sha256(evidence.ioc_postcondition_sha256):
        missing.append(PhoenixPromotionGate.IOC_POSTCONDITIONS)
    if not _is_sha256(evidence.shadow_soak_evidence_sha256):
        missing.append(PhoenixPromotionGate.SHADOW_SOAK)

    unique_missing = tuple(dict.fromkeys(gate.value for gate in missing))
    market_allowlisted = evidence.market in spec.markets
    shadow_allowed = (
        not unique_missing
        and spec.enabled_shadow
        and market_allowlisted
        and not spec.enabled_live
    )

    return PhoenixPromotionDecision(
        market=evidence.market,
        shadow_allowed=shadow_allowed,
        live_allowed=False,
        missing_gates=unique_missing,
        diagnostics={
            "venue_kind": spec.venue_kind.value,
            "program_id": spec.program_id,
            "expected_owner": spec.expected_owner,
            "market_allowlisted": market_allowlisted,
            "spec_shadow_enabled": spec.enabled_shadow,
            "spec_live_enabled": spec.enabled_live,
            "openbook_scope": "separate-follow-up",
        },
    )


def require_phoenix_shadow_promotion(
    spec: VenueProgramSpec,
    evidence: PhoenixPromotionEvidence,
) -> PhoenixPromotionDecision:
    decision = evaluate_phoenix_shadow_promotion(spec, evidence)
    if not decision.shadow_allowed:
        raise OrderbookReject(
            OrderbookRejectCode.MARKET_UNSUPPORTED,
            "Phoenix shadow promotion evidence is incomplete",
            {
                "market": decision.market,
                "missing_gates": decision.missing_gates,
                **dict(decision.diagnostics),
            },
        )
    return decision


def _ensure_phoenix_only(spec: VenueProgramSpec) -> None:
    if spec.venue_kind is VenueKind.OPENBOOK_V2:
        raise OrderbookReject(
            OrderbookRejectCode.MARKET_UNSUPPORTED,
            "OpenBook v2 is outside PR-066 Phoenix-first scope",
            {"venue_kind": spec.venue_kind.value},
        )
    if spec.venue_kind is not VenueKind.PHOENIX_LEGACY_SPOT:
        raise OrderbookReject(
            OrderbookRejectCode.UNKNOWN_VENUE_OR_POOL,
            "PR-066 only evaluates Phoenix legacy spot",
            {"venue_kind": spec.venue_kind.value},
        )


def _is_sha256(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)
