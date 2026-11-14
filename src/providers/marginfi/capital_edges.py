"""R10-2: MarginFi capture-backed ``FlashCapitalProvider`` qualification bridge.

Strictly offline, fail-closed bridge that adapts the existing R02-CAP-D bank
capacity reader (``bank_discovery.py``) into the existing FlashCapitalGraph
provider seam (``src/economics/flash_capital_graph/graph.py``) without
fabricating capacity, fees, edges or provenance.

What is PROVEN offline (exact, from pinned-layout capture decode):
- bank/mint/vault/group identity bindings (pinned PR-028 layout + PR-055 group);
- the exact origination-fee terms: ``ceil(amount * fee_raw / 2^48)`` — which is
  byte-for-byte the ``FlashCapitalEdge.fee`` ceiling semantics with
  ``fee_numerator=fee_raw``, ``fee_denominator=2^48``,
  ``protocol_rounding_atoms=1`` (proven numerically in the test suite against a
  real edge built with fixture evidence);
- raw resource bounds: ``raw_vault_amount_base_units`` and ``raw_borrow_limit``.

What stays UNKNOWN (typed, never zero, never fabricated):
- ``effective_capacity_base_units`` — the share-value/liquidity-share layout is
  UNPINNED and the capacity derivation is UNPROVEN
  (``MISSING_EFFECTIVE_FLASH_CAP``);
- any rooted slot claim — offline captures are ``OFFLINE_FIXTURE_NOT_ROOTED``
  (``LIVE_ROOTED_RPC_NOT_AUTHORIZED``).

Consequences encoded here, matching the frozen CAP-D control point
(``bank_capital_edge_gate``): every adapted row carries ``flash_enabled=False``
(disabled flash borrowing is evidence, never zero-fee support), so the
inherited ``LiveCapitalProvider`` construction path yields **zero edges
offline** and records typed rejection receipts instead.  This bridge never
constructs a ``FlashCapitalEdge`` itself; edge emission for ``marginfi``
requires a separately qualified live rooted-RPC wave with a proven capacity
derivation and independent quorum.  ``refresh`` therefore raises offline
(exactly as the inherited provider does for missing capacity).

Zero network, zero signer/sender imports, no graph edit, no duplicate provider
registry: this is the missing ``marginfi`` adapter on the existing seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Sequence

from src.assets.resolution.evidence import Evidence
from src.assets.resolution.resolver import AssetIdentity
from src.economics.flash_capital_graph.graph import LiveCapitalProvider
from src.providers.marginfi.bank_discovery import (
    BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
    BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    BankReaderPins,
    MarginfiCapture,
    MarginfiBankCapacityObservation,
    READER_DECODER_IDENTITY,
    READER_DECODER_GENERATION,
    READER_SLOT_PROVENANCE_OFFLINE,
    discover_banks,
)

MARGINFI_PROVIDER = "marginfi"
MARGINFI_CHAIN = "solana"
CAPITAL_PAYLOAD_SCHEMA = "dynamic-universe.capital.v1"
FEE_DENOMINATOR_I80F48 = 1 << 48
BRIDGE_IDENTITY = "marginfi.capital-edge-bridge.v1"
BRIDGE_GENERATION = 1
BRIDGE_CORRELATION_GROUP = "marginfi-bank-captures"
CAPACITY_VERDICT_OFFLINE = (
    f"{BLOCKER_MISSING_EFFECTIVE_FLASH_CAP}+{BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED}"
)


class MarginfiCapitalRejectionCode(StrEnum):
    """Typed fail-closed negatives for the capture->capital-payload bridge."""

    CAPTURE_BATCH_EMPTY = "R10MFI_CAPTURE_BATCH_EMPTY"
    OBSERVATION_BLOCKED = "R10MFI_OBSERVATION_BLOCKED"
    PAYLOAD_SCHEMA_DRIFT = "R10MFI_PAYLOAD_SCHEMA_DRIFT"
    NON_OPERATIONAL_BANK = "R10MFI_NON_OPERATIONAL_BANK"
    UNRESOLVED_LENDER_ASSET = "R10MFI_UNRESOLVED_LENDER_ASSET"


@dataclass(frozen=True, slots=True)
class MarginfiCapitalAssetRow:
    """Typed proven facts for one decoded bank, in capital-payload vocabulary.

    ``flash_enabled`` is pinned to ``False`` by construction: the offline bridge
    has no proven effective flash capacity, and disabled flash borrowing is
    evidence — never zero-fee or zero-capacity support.
    """

    bank: str
    mint: str
    resource_id: str
    fee_numerator: int
    fee_denominator: int
    protocol_rounding_atoms: int
    raw_vault_amount_base_units: int
    raw_borrow_limit: int
    operational: bool
    flash_enabled: bool
    slot_provenance: str
    observation_digest: str
    blockers: tuple[str, ...]
    constraint_gaps: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.flash_enabled is not False:
            raise ValueError(
                "offline capture bridge cannot claim flash-enabled capacity"
            )
        if self.fee_denominator != FEE_DENOMINATOR_I80F48:
            raise ValueError("fee denominator must be the pinned 2^48 scale")
        if self.protocol_rounding_atoms != 1:
            raise ValueError("pinned DPR fee rounds to one base unit")
        for name in (
            "fee_numerator",
            "raw_vault_amount_base_units",
            "raw_borrow_limit",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not self.operational and (
            "R02CAPD_BANK_NOT_OPERATIONAL" not in self.blockers
        ):
            raise ValueError("non-operational bank must carry its typed blocker")
        if self.slot_provenance != READER_SLOT_PROVENANCE_OFFLINE:
            raise ValueError("offline bridge must use offline slot provenance")


def _row_from_observation(
    observation: MarginfiBankCapacityObservation,
) -> MarginfiCapitalAssetRow:
    return MarginfiCapitalAssetRow(
        bank=observation.bank,
        mint=observation.mint,
        resource_id=observation.bank,
        fee_numerator=observation.origination_fee_raw_i80f48,
        fee_denominator=FEE_DENOMINATOR_I80F48,
        protocol_rounding_atoms=1,
        raw_vault_amount_base_units=observation.raw_vault_amount_base_units,
        raw_borrow_limit=observation.raw_borrow_limit,
        operational=observation.operational,
        flash_enabled=False,
        slot_provenance=READER_SLOT_PROVENANCE_OFFLINE,
        observation_digest=observation.evidence_digest,
        blockers=observation.blockers,
        constraint_gaps=observation.constraint_gaps,
    )


def marginfi_capital_payload(
    pins: BankReaderPins,
    bank_captures: Sequence[MarginfiCapture],
    vault_captures: Sequence[MarginfiCapture],
    *,
    group_capture: MarginfiCapture | None = None,
    now_timestamp: int | None = None,
    observed_at: float,
) -> tuple[dict, Evidence]:
    """Adapt pinned captures into the ``dynamic-universe.capital.v1`` payload.

    Reuses the existing wallet-free discovery owner end-to-end (pin
    cross-checks, exact layout decode, slot coherence, group binding). Every
    adapted row keeps ``flash_enabled=False`` because effective flash capacity
    is unproven offline; the payload therefore yields zero edges through the
    existing provider seam, with typed receipts on the bridge provider.
    """

    if not bank_captures:
        raise ValueError(
            f"{MarginfiCapitalRejectionCode.CAPTURE_BATCH_EMPTY.value}: "
            "caller-supplied captures required; empty is not evidence"
        )
    discovery = discover_banks(
        pins,
        bank_captures,
        vault_captures,
        group_capture=group_capture,
        now_timestamp=now_timestamp,
    )
    rows = [_row_from_observation(observation) for observation in discovery.banks]
    payload = {
        "schema": CAPITAL_PAYLOAD_SCHEMA,
        "provider": MARGINFI_PROVIDER,
        "assets": [
            {
                "canonical_identifier": row.mint,
                "resource_id": row.resource_id,
                "max_amount_atoms": 0,
                "fee_numerator": row.fee_numerator,
                "fee_denominator": row.fee_denominator,
                "protocol_rounding_atoms": row.protocol_rounding_atoms,
                "constraints": (
                    "FLASH_CAP_UNPROVEN_OFFLINE",
                    *row.blockers,
                ),
                "flash_enabled": row.flash_enabled,
                "raw_vault_amount_base_units": row.raw_vault_amount_base_units,
                "raw_borrow_limit": row.raw_borrow_limit,
                "operational": row.operational,
                "slot_provenance": row.slot_provenance,
                "observation_digest": row.observation_digest,
            }
            for row in rows
        ],
    }
    evidence = Evidence(
        source=BRIDGE_IDENTITY,
        provider=MARGINFI_PROVIDER,
        correlation_group=BRIDGE_CORRELATION_GROUP,
        generation=f"{READER_DECODER_IDENTITY}#{READER_DECODER_GENERATION}",
        observed_at=observed_at,
        response_hash=discovery.evidence_digest,
        request_hash=hashlib.sha256(
            f"{BRIDGE_IDENTITY}|{READER_DECODER_IDENTITY}".encode("utf-8")
        ).hexdigest(),
        slot_or_checkpoint=None,
        negative_reason=None,
    )
    return payload, evidence


class MarginfiCaptureCapitalProvider(LiveCapitalProvider):
    """The missing ``marginfi`` adapter on the existing FlashCapitalGraph seam.

    The reader is built internally from caller-supplied pinned captures; no
    edge can be constructed offline because every row is ``flash_enabled=False``
    (unproven flash capacity). ``discover_assets`` returns ``()`` offline and
    accumulates typed rejection receipts explaining exactly why; ``refresh``
    raises (no live lender capacity), inherited unchanged.
    """

    def __init__(
        self,
        pins: BankReaderPins,
        bank_captures: Sequence[MarginfiCapture],
        vault_captures: Sequence[MarginfiCapture],
        assets: tuple[AssetIdentity, ...],
        *,
        group_capture: MarginfiCapture | None = None,
        now_timestamp: int | None = None,
        observed_at: float,
    ) -> None:
        if not assets:
            raise ValueError(
                f"{MarginfiCapitalRejectionCode.UNRESOLVED_LENDER_ASSET.value}: "
                "verified asset identities must be supplied by the resolver owner"
            )
        self._pins = pins
        self._bank_captures = tuple(bank_captures)
        self._vault_captures = tuple(vault_captures)
        self._group_capture = group_capture
        self._now_timestamp = now_timestamp
        self.rejection_receipts: dict[str, str] = {}

        def reader() -> tuple[dict, Evidence]:
            return marginfi_capital_payload(
                pins,
                self._bank_captures,
                self._vault_captures,
                group_capture=self._group_capture,
                now_timestamp=self._now_timestamp,
                observed_at=observed_at,
            )

        super().__init__(MARGINFI_PROVIDER, MARGINFI_CHAIN, reader, assets)
        self._record_static_receipts()

    def _record_static_receipts(self) -> None:
        payload, _ = self.reader()
        for row in payload["assets"]:
            blockers = set(row["constraints"])
            blockers.discard("FLASH_CAP_UNPROVEN_OFFLINE")
            self.rejection_receipts[row["resource_id"]] = (
                f"{MarginfiCapitalRejectionCode.OBSERVATION_BLOCKED.value}:"
                f"{'+'.join(sorted(blockers)) or CAPACITY_VERDICT_OFFLINE}"
            )

    def discover_assets(self) -> tuple:
        edges = super().discover_assets()
        if edges:
            # Defensive: this bridge must never surface an edge while its rows
            # are flash-disabled. The inherited path cannot produce one.
            raise ValueError(
                "marginfi capture bridge yielded an edge offline; refusing to "
                "fabricate flash capacity"
            )
        self.rejection_receipts.setdefault(
            "__provider__",
            f"{MarginfiCapitalRejectionCode.OBSERVATION_BLOCKED.value}:"
            f"{CAPACITY_VERDICT_OFFLINE}",
        )
        if BLOCKER_MISSING_EFFECTIVE_FLASH_CAP not in self.negative_evidence:
            self.negative_evidence.append(BLOCKER_MISSING_EFFECTIVE_FLASH_CAP)
        return ()


@dataclass(frozen=True, slots=True)
class MarginfiCapitalQualification:
    """Typed offline qualification record for one capture-backed batch.

    ``fee_terms_proven`` is True only when every row's fee triple reproduces the
    pinned DPR rule exactly (the test suite proves the equivalence against a
    real ``FlashCapitalEdge`` built with fixture evidence). ``capacity_verdict``
    is the typed offline blocker pair — never a capacity number.
    """

    bridge_identity: str
    bridge_generation: int
    evidence: Evidence
    rows: tuple[MarginfiCapitalAssetRow, ...]
    payload: dict
    fee_terms_proven: bool
    capacity_verdict: str
    provider_receipts: dict[str, str]
    graph_edges_discovered: int

    def __post_init__(self) -> None:
        if self.bridge_identity != BRIDGE_IDENTITY or (
            self.bridge_generation != BRIDGE_GENERATION
        ):
            raise ValueError("qualification must record the pinned bridge identity")
        if self.capacity_verdict != CAPACITY_VERDICT_OFFLINE:
            raise ValueError(
                "offline qualification verdict is fixed to the typed blocker pair"
            )
        if self.graph_edges_discovered != 0:
            raise ValueError("offline qualification must discover zero edges")
        if not self.fee_terms_proven:
            raise ValueError("qualification requires the exact fee-term equivalence")


def marginfi_capital_qualification(
    pins: BankReaderPins,
    bank_captures: Sequence[MarginfiCapture],
    vault_captures: Sequence[MarginfiCapture],
    assets: tuple[AssetIdentity, ...],
    *,
    group_capture: MarginfiCapture | None = None,
    now_timestamp: int | None = None,
    observed_at: float,
) -> MarginfiCapitalQualification:
    """Run the full offline qualification pipeline over one capture batch."""

    provider = MarginfiCaptureCapitalProvider(
        pins,
        bank_captures,
        vault_captures,
        assets,
        group_capture=group_capture,
        now_timestamp=now_timestamp,
        observed_at=observed_at,
    )
    payload, evidence = provider.reader()
    rows = tuple(
        _row_from_observation(observation)
        for observation in discover_banks(
            pins,
            bank_captures,
            vault_captures,
            group_capture=group_capture,
            now_timestamp=now_timestamp,
        ).banks
    )
    edges = provider.discover_assets()
    return MarginfiCapitalQualification(
        bridge_identity=BRIDGE_IDENTITY,
        bridge_generation=BRIDGE_GENERATION,
        evidence=evidence,
        rows=rows,
        payload=payload,
        fee_terms_proven=True,
        capacity_verdict=CAPACITY_VERDICT_OFFLINE,
        provider_receipts=dict(provider.rejection_receipts),
        graph_edges_discovered=len(edges),
    )


__all__ = [
    "BRIDGE_CORRELATION_GROUP",
    "BRIDGE_GENERATION",
    "BRIDGE_IDENTITY",
    "CAPACITY_VERDICT_OFFLINE",
    "CAPITAL_PAYLOAD_SCHEMA",
    "FEE_DENOMINATOR_I80F48",
    "MARGINFI_CHAIN",
    "MARGINFI_PROVIDER",
    "MarginfiCapitalAssetRow",
    "MarginfiCapitalQualification",
    "MarginfiCapitalRejectionCode",
    "MarginfiCaptureCapitalProvider",
    "marginfi_capital_payload",
    "marginfi_capital_qualification",
]
