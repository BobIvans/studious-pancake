"""PR-049 orderbook venue conformance pins.

Only Phoenix legacy spot is admitted into the default mainnet registry in this
PR.  The venue remains fail-closed until an operator supplies official market
fixtures and verifies them against the pinned program/source.  OpenBook v2 and
all synthetic legacy fixtures stay test-only.
"""

from __future__ import annotations

from typing import Iterable

from .models import OrderbookReject, OrderbookRejectCode, VenueKind, VenueProgramSpec

OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID = "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY"
OFFICIAL_PHOENIX_SOURCE_REPOSITORY = "https://github.com/Ellipsis-Labs/phoenix-v1"
OFFICIAL_PHOENIX_VERIFY_COMMAND = (
    "solana-verify verify-from-repo -um --program-id "
    f"{OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID} {OFFICIAL_PHOENIX_SOURCE_REPOSITORY}"
)
PHOENIX_COMMON_CRATE = "phoenix-common==0.4.0"

_SYNTHETIC_PROGRAM_MARKERS = (
    "PhoenixLegacyProgramFromPinnedRegistry",
    "OpenBookV2ProgramFromPinnedIDL",
    "111111",
)
_UNVERIFIED_ARTIFACT_MARKERS = (
    "placeholder",
    "offline",
    "verification-required",
    "fixture",
    "synthetic",
)


def is_fixture_spec(spec: VenueProgramSpec) -> bool:
    """Return true only for explicit unit-test fixture registries."""

    source = spec.source.lower()
    status = spec.status.lower()
    return source.startswith("test:") or "fixture_only" in status or "test_fixture" in status


def ensure_pr049_default_conformance(specs: Iterable[VenueProgramSpec]) -> None:
    """Fail closed when the default orderbook registry contains fake active pins."""

    for spec in specs:
        if is_fixture_spec(spec):
            continue
        if spec.venue_kind is VenueKind.OPENBOOK_V2:
            if spec.enabled_shadow or spec.enabled_live or spec.markets:
                raise OrderbookReject(
                    OrderbookRejectCode.MARKET_UNSUPPORTED,
                    "OpenBook v2 is outside PR-049 default scope; keep it disabled",
                    {"venue_kind": spec.venue_kind.value, "status": spec.status},
                )
            continue
        if spec.venue_kind is not VenueKind.PHOENIX_LEGACY_SPOT:
            raise OrderbookReject(
                OrderbookRejectCode.UNKNOWN_VENUE_OR_POOL,
                "unsupported orderbook venue in default registry",
                {"venue_kind": spec.venue_kind.value},
            )
        _ensure_phoenix_default_pin(spec)


def _ensure_phoenix_default_pin(spec: VenueProgramSpec) -> None:
    if spec.program_id != OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID:
        raise OrderbookReject(
            OrderbookRejectCode.VENUE_PROGRAM_MISMATCH,
            "Phoenix default registry must pin the official mainnet program id",
            {"program_id": spec.program_id},
        )
    if spec.expected_owner != OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID:
        raise OrderbookReject(
            OrderbookRejectCode.VENUE_PROGRAM_MISMATCH,
            "Phoenix market owner must match the official mainnet program id",
            {"expected_owner": spec.expected_owner},
        )
    if spec.enabled_live:
        raise OrderbookReject(
            OrderbookRejectCode.MARKET_UNSUPPORTED,
            "PR-049 never enables live orderbook execution",
        )
    if spec.enabled_shadow and _artifact_requires_verification(spec.artifact_sha256):
        raise OrderbookReject(
            OrderbookRejectCode.VENUE_IDL_VERSION_MISMATCH,
            "Phoenix shadow mode requires an operator-verified artifact sha256",
            {"artifact_sha256": spec.artifact_sha256},
        )
    if any(marker in spec.program_id for marker in _SYNTHETIC_PROGRAM_MARKERS):
        raise OrderbookReject(
            OrderbookRejectCode.VENUE_PROGRAM_MISMATCH,
            "synthetic orderbook program id leaked into default registry",
            {"program_id": spec.program_id},
        )


def _artifact_requires_verification(value: str) -> bool:
    lowered = value.lower()
    if not lowered.startswith("sha256:"):
        return True
    return any(marker in lowered for marker in _UNVERIFIED_ARTIFACT_MARKERS)
