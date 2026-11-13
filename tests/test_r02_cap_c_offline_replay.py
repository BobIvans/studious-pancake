"""R02-CAP-C: offline replay, pinned-source cross-check and graph-port demotion.

Replays the pinned offline SDK pack verifier, cross-checks module constants
against the pinned NAVI bridge facts JSON and the vendor blob manifest, keeps
``getAllFlashLoanAssets`` output demoted to discovery-only in the data model,
and proves the existing FlashCapitalGraph port yields zero edges from
discovery-only reader evidence. Zero network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.assets.resolution.evidence import Evidence, digest
from src.assets.resolution.resolver import AssetIdentity
from src.economics.flash_capital_graph.graph import NaviCapitalProvider
from src.multichain.sui import (
    NAVI_BRIDGE_FACTS_BLOB,
    NAVI_LENDING_SDK_PACKAGE,
    NAVI_LENDING_SDK_VERSION,
    NAVI_UPSTREAM_COMMIT,
    NAVI_VENDOR_BLOB_SHA,
    NaviCapacityEvidenceState,
    NaviCapacityRejectionCode,
    NaviSuiReadTransport,
    parse_flashloan_api_discovery_rows,
)

from tests.test_r02_cap_c_reader import (
    CAPTURE_CHECKPOINT,
    OFFLINE_ROOT,
    REVIEWED_COIN_TYPE,
    SYNTHETIC_PACKAGE,
    SYNTHETIC_POOL_ID,
    Fixture,
)

CANONICAL_SUI_COIN = "0x" + "0" * 63 + "2::sui::SUI"
READER_GENERATION = "r02capc-gen1"


def test_pinned_offline_reference_integrity_passes() -> None:
    spec = importlib.util.spec_from_file_location(
        "r02_cap_c_verify_offline", OFFLINE_ROOT / "verify_offline.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.validate()
    assert result["status"] == "OFFLINE_REFERENCE_INTEGRITY_PASS"
    assert result["jupiter_bytes"] == 192
    assert result["live_readers_qualified"] == 0
    assert result["execution_authority"] == "NONE"
    assert result["network_requests"] == 0


def test_module_constants_match_pinned_bridge_facts_json() -> None:
    facts = json.loads(
        (OFFLINE_ROOT / "navi_sdk_bridge_facts.json").read_text(encoding="utf-8")
    )
    assert facts["source_pin"] == (
        "naviprotocol/naviprotocol-monorepo@" + NAVI_UPSTREAM_COMMIT
    )
    assert facts["sdk"] == NAVI_LENDING_SDK_PACKAGE
    assert facts["version"] == NAVI_LENDING_SDK_VERSION
    assert facts["execution_authority"] == "NONE"
    assert facts["account_creation"] == "not in flashloanPTB helper"
    assert "DISCOVERY not proof" in facts["safety"]
    assert "gRPC/GraphQL only" in facts["source_current_sui_transport"]
    # Pinned helper behavior: v1 -> flash_loan_with_ctx, v2 -> _v2 (+0x05),
    # repay via flash_repay_with_ctx; getAllFlashLoanAssets is off-chain.
    helper = facts["helper_behavior"]
    assert "flash_loan_with_ctx" in helper["builder"]
    assert "flash_loan_with_ctx_v2" in helper["builder"]
    assert "0x05 SuiSystemState" in helper["builder"]
    assert "flash_repay_with_ctx" in helper["repay"]
    assert "OPEN API" in helper["discover"]
    for vendored in facts["offline_vendor_files"]:
        assert "offline/" + vendored in NAVI_VENDOR_BLOB_SHA


def test_vendor_blob_hashes_match_pinned_manifest() -> None:
    manifest = json.loads(
        (OFFLINE_ROOT / "VENDOR_MANIFEST.json").read_text(encoding="utf-8")
    )
    navi_entries = {
        entry["local_path"]: entry["upstream_git_blob_sha"]
        for entry in manifest["entries"]
        if "/navi/" in entry["local_path"]
    }
    assert navi_entries == NAVI_VENDOR_BLOB_SHA
    # The bridge facts JSON itself is pinned by git blob hash (LF bytes).
    raw = (OFFLINE_ROOT / "navi_sdk_bridge_facts.json").read_bytes()
    computed = hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    assert computed == NAVI_BRIDGE_FACTS_BLOB


def test_get_all_flash_loan_assets_stays_discovery_only() -> None:
    rows = parse_flashloan_api_discovery_rows(Fixture.discovery_rows())
    assert rows[0].evidence_state is (
        NaviCapacityEvidenceState.DISCOVERY_ONLY_OFFCHAIN_API
    )
    with pytest.raises(Exception, match="NAVI_API_ONLY_NOT_ONCHAIN"):
        rows[0].capital_rows({CANONICAL_SUI_COIN: 9})
    observation = Fixture.observation(api_discovery_rows=Fixture.discovery_rows())
    assert NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value in (
        observation.constraint_gaps
    )
    assert observation.status == "BLOCKED_LIVE_STATE"
    assert NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value in (
        observation.blockers
    )


def test_offline_observation_replays_without_promotion() -> None:
    obs = Fixture.observation()
    record = obs.evidence_record()
    restored = json.loads(json.dumps(record))
    assert restored["evidence_sha256"] == obs.evidence_digest
    assert restored["status"] == "BLOCKED_LIVE_STATE"
    assert restored["observation"]["effective_capacity_units"] is None
    assert restored["observation"]["sign_enabled"] is False
    assert restored["observation"]["send_enabled"] is False
    assert restored["observation"]["execution_authority"] == "NONE"
    assert restored["observation"]["evidence_state"] == "OFFLINE_FIXTURE_NOT_ROOTED"
    assert restored["observation"]["transport"] == (
        NaviSuiReadTransport.OFFLINE_FIXTURE_CAPTURE.value
    )
    assert set(restored["observation"]["blockers"]) == {
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED",
    }


def test_reader_module_has_no_transport_or_signer_imports() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/multichain/sui.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "import httpx",
        "import aiohttp",
        "import requests",
        "import urllib",
        "import socket",
        "import subprocess",
        "import websockets",
        "import grpc",
        "SuiJsonRpcClient",
        "JsonRpcClient",
        "solders.keypair",
        "Keypair",
    )
    for token in forbidden:
        assert token not in source, f"forbidden transport/signer token: {token}"


def _discovery_reader_payload() -> dict:
    return {
        "schema": "dynamic-universe.capital.v1",
        "provider": "navi",
        "assets": [
            {
                "canonical_identifier": CANONICAL_SUI_COIN,
                "resource_id": SYNTHETIC_POOL_ID,
                "flash_enabled": False,
                "max_amount_atoms": 0,
                "fee_numerator": 0,
                "fee_denominator": 1,
                "protocol_rounding_atoms": 0,
                "constraints": (),
            }
        ],
    }


def _evidence(*, negative_reason: str | None) -> Evidence:
    payload = _discovery_reader_payload()
    return Evidence(
        source="r02-cap-c-offline-fixture",
        provider="navi",
        correlation_group="r02-cap-c",
        generation=READER_GENERATION,
        observed_at=1760000000.0,
        response_hash=digest(payload),
        request_hash=digest({"request": "navi-pool-capture-offline"}),
        slot_or_checkpoint=None if negative_reason else CAPTURE_CHECKPOINT,
        negative_reason=negative_reason,
    )


def _navi_asset_identity() -> AssetIdentity:
    return AssetIdentity(
        asset_id="sui-sui",
        chain="sui",
        canonical_identifier=CANONICAL_SUI_COIN,
        symbol="SUI",
        decimals=9,
        program_or_package=SYNTHETIC_PACKAGE,
        economic_underlying="sui-native",
        representation_kind="native",
        resolver_generation=READER_GENERATION,
        evidence_refs=("r02capc-offline-fixture",),
        identity_generation=READER_GENERATION,
    )


def test_graph_port_yields_no_edges_from_discovery_only_reader() -> None:
    provider = NaviCapitalProvider(
        lambda: (
            _discovery_reader_payload(),
            _evidence(
                negative_reason=NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value
            ),
        ),
        (_navi_asset_identity(),),
    )
    assert provider.discover_assets() == ()
    assert provider.negative_evidence == [
        NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value
    ]
    with pytest.raises(ValueError, match="no live lender capacity"):
        provider.refresh("sui-sui", 1)


def test_graph_port_skips_non_flash_discovery_rows_without_negatives() -> None:
    # flash_enabled False is evidence, never zero-fee support: the frozen
    # graph owner skips such rows and no positive edge can materialize from
    # a discovery-only reader payload.
    provider = NaviCapitalProvider(
        lambda: (_discovery_reader_payload(), _evidence(negative_reason=None)),
        (_navi_asset_identity(),),
    )
    assert provider.discover_assets() == ()
    assert provider.negative_evidence == []
    with pytest.raises(ValueError, match="no live lender capacity"):
        provider.refresh("sui-sui", 1)


def test_reviewed_coin_type_is_pinned_by_reader_fixture() -> None:
    assert REVIEWED_COIN_TYPE == "0x2::sui::SUI"
