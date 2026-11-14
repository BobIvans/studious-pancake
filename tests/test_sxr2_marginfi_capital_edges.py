"""R10-2: MarginFi capture-backed FlashCapitalProvider qualification tests.

Offline only: synthetic pinned-layout captures via the established CAP-D
fixture helpers. The suite proves (a) the exact fee-term equivalence between
the pinned DPR origination-fee rule and ``FlashCapitalEdge.fee`` semantics,
(b) that the capture bridge yields ZERO edges offline with typed rejection
receipts (unknown capacity is never fabricated), and (c) that the existing
FlashCapitalGraph baseline is preserved. Fixtures here prove construction
semantics; they are never live evidence.
"""

from __future__ import annotations

import pytest

from src.assets.resolution.evidence import Evidence, EvidenceStore
from src.economics.flash_capital_graph.graph import FlashCapitalEdge, FlashCapitalGraph
from src.providers.marginfi.bank_discovery import (
    BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
    BLOCKER_GROUP_PAUSED,
    MarginfiCapture,
    compute_origination_fee,
)
from src.providers.marginfi.capital_edges import (
    BRIDGE_IDENTITY,
    CAPITAL_PAYLOAD_SCHEMA,
    FEE_DENOMINATOR_I80F48,
    MARGINFI_PROVIDER,
    MarginfiCapitalAssetRow,
    MarginfiCaptureCapitalProvider,
    MarginfiCapitalRejectionCode,
    marginfi_capital_payload,
    marginfi_capital_qualification,
)
from tests.test_dynamic_asset_resolution import evidence as registry_evidence
from tests.test_dynamic_relations import asset
from tests.test_r02_cap_d_reader import (
    Fixture,
    PROGRAM_ID,
    _group_bytes,
    _pk,
)

NOW = 1_764_000_000
OBSERVED_AT = 101.0


def real_edge_with_bridge_fee_terms(fee_raw: int) -> FlashCapitalEdge:
    """A real FlashCapitalEdge carrying the bridge's exact fee triple.

    Fixture evidence and a fixture-large capacity bound; used ONLY to prove the
    fee-semantics equivalence, never to claim live capacity.
    """

    return FlashCapitalEdge(
        "solana",
        MARGINFI_PROVIDER,
        asset().asset_id,
        asset().canonical_identifier,
        "bank-fixture",
        2**63,
        fee_raw,
        FEE_DENOMINATOR_I80F48,
        1,
        "LOCAL_ATOMIC_CANDIDATE",
        (),
        registry_evidence("lender", 10),
        ("proof",),
    )


def test_fee_terms_reproduce_pinned_dpr_rule_exactly() -> None:
    fee_raw = 1 << 46  # same fixture fee scale as the CAP-D reader fixtures
    edge = real_edge_with_bridge_fee_terms(fee_raw)
    amounts = (1, 2, 3, 4, 5, 1 << 20, 12_345_679, 1 << 40, (1 << 62) - 1)
    for amount in amounts:
        assert edge.fee(amount) == compute_origination_fee(amount, fee_raw)
    with pytest.raises(ValueError):
        edge.fee(2**63 + 1)


def test_payload_rows_are_flash_disabled_with_typed_blockers() -> None:
    fx = Fixture()
    payload, evidence = marginfi_capital_payload(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        observed_at=OBSERVED_AT,
    )
    assert payload["schema"] == CAPITAL_PAYLOAD_SCHEMA
    assert payload["provider"] == MARGINFI_PROVIDER
    assert len(payload["assets"]) == 1
    row = payload["assets"][0]
    assert row["flash_enabled"] is False
    assert row["resource_id"] == str(fx.bank)
    assert row["fee_denominator"] == FEE_DENOMINATOR_I80F48
    assert row["protocol_rounding_atoms"] == 1
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in row["constraints"]
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in row["constraints"]
    assert "FLASH_CAP_UNPROVEN_OFFLINE" in row["constraints"]
    assert evidence.slot_or_checkpoint is None
    assert evidence.negative_reason is None
    assert evidence.source == BRIDGE_IDENTITY


def test_provider_discovers_zero_edges_and_records_receipts() -> None:
    fx = Fixture()
    provider = MarginfiCaptureCapitalProvider(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        (asset(),),
        observed_at=OBSERVED_AT,
    )
    assert provider.discover_assets() == ()
    receipt = provider.rejection_receipts[str(fx.bank)]
    assert receipt.startswith(MarginfiCapitalRejectionCode.OBSERVATION_BLOCKED.value)
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in receipt
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in receipt
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in provider.negative_evidence
    # Idempotent discovery must not duplicate receipts or fabricate edges.
    assert provider.discover_assets() == ()
    assert provider.negative_evidence == [BLOCKER_MISSING_EFFECTIVE_FLASH_CAP]


def test_provider_refresh_raises_offline() -> None:
    fx = Fixture()
    provider = MarginfiCaptureCapitalProvider(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        (asset(),),
        observed_at=OBSERVED_AT,
    )
    with pytest.raises(ValueError):
        provider.refresh(asset().asset_id, 100)


def test_qualification_record_pins_zero_edges_and_verdict() -> None:
    fx = Fixture()
    qualification = marginfi_capital_qualification(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        (asset(),),
        observed_at=OBSERVED_AT,
    )
    assert qualification.graph_edges_discovered == 0
    assert qualification.fee_terms_proven is True
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in qualification.capacity_verdict
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in qualification.capacity_verdict
    assert len(qualification.rows) == 1
    row = qualification.rows[0]
    assert row.flash_enabled is False
    assert row.fee_numerator == fx.observation.origination_fee_raw_i80f48
    assert row.raw_vault_amount_base_units == fx.observation.raw_vault_amount_base_units
    assert qualification.evidence.response_hash


def test_empty_capture_batch_fails_closed() -> None:
    fx = Fixture()
    with pytest.raises(ValueError, match="R10MFI_CAPTURE_BATCH_EMPTY"):
        marginfi_capital_payload(fx.pins, [], [], observed_at=OBSERVED_AT)
    with pytest.raises(ValueError, match="R10MFI_CAPTURE_BATCH_EMPTY"):
        MarginfiCaptureCapitalProvider(
            fx.pins, [], [], (asset(),), observed_at=OBSERVED_AT
        )


def test_graph_baseline_preserved_zero_edges_observed(tmp_path) -> None:
    fx = Fixture()
    graph = FlashCapitalGraph("campaign", EvidenceStore(tmp_path))
    provider = MarginfiCaptureCapitalProvider(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        (asset(),),
        observed_at=OBSERVED_AT,
    )
    for edge in provider.discover_assets():  # pragma: no cover - never executes
        graph.observe(edge, now=NOW)
    assert graph.edges == {}


def test_row_validation_forbids_flash_enabled_and_wrong_fee_scale() -> None:
    blockers = (
        BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
        BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    )
    base = dict(
        bank="B" * 43,
        mint="M" * 43,
        resource_id="R" * 43,
        fee_numerator=1 << 46,
        fee_denominator=FEE_DENOMINATOR_I80F48,
        protocol_rounding_atoms=1,
        raw_vault_amount_base_units=10,
        raw_borrow_limit=100,
        operational=True,
        slot_provenance="OFFLINE_FIXTURE_NOT_ROOTED",
        observation_digest="a" * 64,
        blockers=blockers,
        constraint_gaps=("GAP",),
    )
    with pytest.raises(ValueError, match="flash-enabled"):
        MarginfiCapitalAssetRow(flash_enabled=True, **base)
    with pytest.raises(ValueError, match=r"2\^48"):
        MarginfiCapitalAssetRow(
            flash_enabled=False, **{**base, "fee_denominator": 10_000}
        )
    with pytest.raises(ValueError, match="one base unit"):
        MarginfiCapitalAssetRow(
            flash_enabled=False, **{**base, "protocol_rounding_atoms": 2}
        )


def test_inherited_schema_drift_yields_typed_negative() -> None:
    fx = Fixture()
    provider = MarginfiCaptureCapitalProvider(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        (asset(),),
        observed_at=OBSERVED_AT,
    )
    drifted_evidence = Evidence(
        BRIDGE_IDENTITY,
        MARGINFI_PROVIDER,
        "marginfi-bank-captures",
        "campaign",
        OBSERVED_AT,
        "b" * 64,
        "c" * 64,
    )
    provider.reader = lambda: (  # type: ignore[method-assign]
        {"schema": "drifted", "provider": MARGINFI_PROVIDER, "assets": []},
        drifted_evidence,
    )
    assert provider.discover_assets() == ()
    assert "capital_schema_drift" in provider.negative_evidence


def test_group_pause_blockers_flow_into_receipts() -> None:
    fx = Fixture()
    paused_capture = MarginfiCapture(
        address="4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8",
        owner=PROGRAM_ID,
        data=_group_bytes(
            admin=_pk(5),
            paused=True,
            pause_start=NOW,
            cache_updated=NOW,
        ),
    )
    provider = MarginfiCaptureCapitalProvider(
        fx.pins,
        [fx.bank_capture],
        [fx.vault_capture],
        (asset(),),
        group_capture=paused_capture,
        now_timestamp=NOW,
        observed_at=OBSERVED_AT,
    )
    assert provider.discover_assets() == ()
    receipt = provider.rejection_receipts[str(fx.bank)]
    assert BLOCKER_GROUP_PAUSED in receipt
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in receipt
