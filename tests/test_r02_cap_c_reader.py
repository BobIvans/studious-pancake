"""R02-CAP-C: NAVI Sui read-only pool capacity reader — offline positives and
fail-closed negatives.

All fixtures are redacted synthetic object/checkpoint captures built from the
pinned offline semantics (naviprotocol/naviprotocol-monorepo@40d971c8
@naviprotocol/lending@2.0.12). They are never live evidence: every positive
decode is typed BLOCKED_LIVE_STATE with UNKNOWN effective capacity (never
zero), and discovery rows stay DISCOVERY_ONLY_OFFCHAIN_API. Zero network.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction
import json
from pathlib import Path

import pytest

from src.multichain.core import MultiChainError
from src.multichain.sui import (
    NAVI_FLASH_ENTRY_V1,
    NAVI_FLASH_ENTRY_V2,
    NAVI_FLASH_REPAY_ENTRY,
    NAVI_LENDING_SDK_PACKAGE,
    NAVI_LENDING_SDK_VERSION,
    NAVI_READER_DECODER_GENERATION,
    NAVI_READER_EXECUTION_AUTHORITY,
    NAVI_UPSTREAM_COMMIT,
    NAVI_VENDOR_BLOB_SHA,
    NaviCapacityEvidenceState,
    NaviCapacityRejectionCode,
    NaviCapacityDerivation,
    NaviFlashloanApiDiscoveryRow,
    NaviMarketConfigCapture,
    NaviObjectCapture,
    NaviPoolCapacityObservation,
    NaviSuiCheckpointBinding,
    NaviSuiReadTransport,
    SuiObjectKind,
    decode_navi_coin_metadata,
    navi_capital_edge_gate,
    navi_flash_ptb_shape,
    observe_navi_pool_capacity,
    parse_flashloan_api_discovery_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_ROOT = REPO_ROOT / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline"
PINNED_BRIDGE_FACTS = OFFLINE_ROOT / "navi_sdk_bridge_facts.json"
PINNED_VENDOR_MANIFEST = OFFLINE_ROOT / "VENDOR_MANIFEST.json"

# Redacted synthetic identities (ASCII prefixes, zero padding). These are not
# live NAVI addresses and must never be interpreted as such.
SYNTHETIC_PACKAGE = "0x4e415649" + "00" * 28
SYNTHETIC_POOL_ID = "0x504f4f4c" + "00" * 28
SYNTHETIC_STORAGE_ID = "0x53544f52" + "00" * 28
SYNTHETIC_FLASH_CONFIG_ID = "0x464c4346" + "00" * 28
SYNTHETIC_METADATA_ID = "4d455441" + "00" * 28
REVIEWED_COIN_TYPE = "0x2::sui::SUI"
CAPTURE_CHECKPOINT = 900000001
CAPTURE_EPOCH = 900
CAPTURE_CHECKPOINT_DIGEST = "synthetic-offline-capture-not-rooted"


def _bcs_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    assert len(encoded) < 128
    return bytes((len(encoded),)) + encoded


def _coin_metadata_bytes(
    *,
    decimals: int = 9,
    name: str = "Sui",
    symbol: str = "SUI",
    description: str = "Sui",
    trailing: bytes = b"",
    option_flag: bytes = b"\x00",
) -> bytes:
    return (
        bytes.fromhex(SYNTHETIC_METADATA_ID)
        + bytes((decimals,))
        + _bcs_string(name)
        + _bcs_string(symbol)
        + _bcs_string(description)
        + option_flag
        + trailing
    )


class Fixture:
    """Deterministic offline capture set (redacted synthetic identities)."""

    config_version = 2

    @staticmethod
    def binding() -> NaviSuiCheckpointBinding:
        return NaviSuiCheckpointBinding(
            chain_key="sui-mainnet",
            checkpoint=CAPTURE_CHECKPOINT,
            digest=CAPTURE_CHECKPOINT_DIGEST,
            epoch=CAPTURE_EPOCH,
        )

    @staticmethod
    def pool_capture(**overrides: object) -> NaviObjectCapture:
        values: dict[str, object] = {
            "object_id": SYNTHETIC_POOL_ID,
            "version": 1234,
            "digest": "pool-object-digest-binding",
            "type_tag": (f"{SYNTHETIC_PACKAGE}::pool::Pool<{REVIEWED_COIN_TYPE}>"),
            "owner_kind": SuiObjectKind.SHARED,
            "checkpoint": CAPTURE_CHECKPOINT,
            "epoch": CAPTURE_EPOCH,
            "fields_raw": (
                ("available_balance", "1000000000"),
                ("borrowed_amount", "100000000"),
            ),
        }
        values.update(overrides)
        return NaviObjectCapture(**values)  # type: ignore[arg-type]

    @staticmethod
    def market_config(
        **overrides: object,
    ) -> NaviMarketConfigCapture:
        storage = NaviObjectCapture(
            object_id=SYNTHETIC_STORAGE_ID,
            version=10,
            digest="storage-object-digest-binding",
            type_tag=f"{SYNTHETIC_PACKAGE}::storage::Storage",
            owner_kind=SuiObjectKind.SHARED,
            checkpoint=CAPTURE_CHECKPOINT,
            epoch=CAPTURE_EPOCH,
        )
        flashloan_config = NaviObjectCapture(
            object_id=SYNTHETIC_FLASH_CONFIG_ID,
            version=10,
            digest="flash-config-object-digest-binding",
            type_tag=f"{SYNTHETIC_PACKAGE}::flashloan::Config",
            owner_kind=SuiObjectKind.SHARED,
            checkpoint=CAPTURE_CHECKPOINT,
            epoch=CAPTURE_EPOCH,
        )
        values: dict[str, object] = {
            "package": SYNTHETIC_PACKAGE,
            "version": Fixture.config_version,
            "storage": storage,
            "flashloan_config": flashloan_config,
        }
        values.update(overrides)
        return NaviMarketConfigCapture(**values)  # type: ignore[arg-type]

    @staticmethod
    def observation(**overrides: object) -> NaviPoolCapacityObservation:
        values: dict[str, object] = {
            "checkpoint_binding": Fixture.binding(),
            "market_config": Fixture.market_config(),
            "pool_capture": Fixture.pool_capture(),
            "reviewed_coin_type": REVIEWED_COIN_TYPE,
            "coin_metadata_bytes": _coin_metadata_bytes(),
            "coin_metadata_type_tag": (
                f"0x2::coin::CoinMetadata<{REVIEWED_COIN_TYPE}>"
            ),
            "coin_metadata_owner_kind": SuiObjectKind.IMMUTABLE,
        }
        values.update(overrides)
        return observe_navi_pool_capacity(**values)  # type: ignore[arg-type]

    @staticmethod
    def discovery_rows() -> list[dict]:
        return [
            {
                "coinType": REVIEWED_COIN_TYPE,
                "max": "1000000000000",
                "min": "1",
                "flashloanFee": "0",
                "assetId": 0,
                "poolId": SYNTHETIC_POOL_ID,
            }
        ]


def test_reader_pins_navi_source_and_vendor_blobs() -> None:
    facts = json.loads(PINNED_BRIDGE_FACTS.read_text(encoding="utf-8"))
    assert (
        facts["source_pin"]
        == f"naviprotocol/naviprotocol-monorepo@{NAVI_UPSTREAM_COMMIT}"
    )
    assert facts["sdk"] == NAVI_LENDING_SDK_PACKAGE
    assert facts["version"] == NAVI_LENDING_SDK_VERSION
    manifest = json.loads(PINNED_VENDOR_MANIFEST.read_text(encoding="utf-8"))
    navi_entries = {
        entry["local_path"]: entry["upstream_git_blob_sha"]
        for entry in manifest["entries"]
        if "/navi/" in entry["local_path"]
    }
    assert NAVI_VENDOR_BLOB_SHA == navi_entries
    for vendored in facts["offline_vendor_files"]:
        assert "offline/" + vendored in NAVI_VENDOR_BLOB_SHA


def test_pool_capacity_observation_decodes_fixture_state() -> None:
    obs = Fixture.observation()
    assert obs.package_id == SYNTHETIC_PACKAGE
    assert obs.package_version == 2
    assert obs.coin_type == ("0x" + "0" * 63 + "2::sui::SUI")
    assert obs.coin_decimals == 9
    assert obs.pool_capture.version == 1234
    assert len(obs.object_bindings) == 3
    assert obs.checkpoint_binding.checkpoint == CAPTURE_CHECKPOINT
    assert obs.evidence_state is NaviCapacityEvidenceState.OFFLINE_FIXTURE_NOT_ROOTED
    assert obs.transport is NaviSuiReadTransport.OFFLINE_FIXTURE_CAPTURE
    assert obs.raw_pool_resource_fields == (
        ("available_balance", "1000000000"),
        ("borrowed_amount", "100000000"),
    )
    assert obs.raw_resource_semantics == "UNAUDITED_SEMANTICS_NOT_CAPACITY"
    assert obs.status == "BLOCKED_LIVE_STATE"
    assert set(obs.blockers) == {
        NaviCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
        NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value,
    }
    assert NaviCapacityRejectionCode.POOL_MOVE_LAYOUT_UNPINNED.value in (
        obs.constraint_gaps
    )
    assert "CHAIN_CHECKPOINT_IS_NOT_NAVI_POOL_STATE" in obs.constraint_gaps
    assert obs.effective_capacity_units is None
    assert obs.capacity_derivation is NaviCapacityDerivation.UNPROVEN
    assert obs.execution_authority == NAVI_READER_EXECUTION_AUTHORITY == "NONE"
    assert obs.sign_enabled is False
    assert obs.send_enabled is False
    assert obs.decoder_generation == NAVI_READER_DECODER_GENERATION


def test_decimals_are_proven_from_coin_metadata_object_state() -> None:
    metadata = decode_navi_coin_metadata(
        _coin_metadata_bytes(),
        type_tag=f"0x2::coin::CoinMetadata<{REVIEWED_COIN_TYPE}>",
        owner_kind=SuiObjectKind.IMMUTABLE,
        expected_coin_type=REVIEWED_COIN_TYPE,
    )
    assert metadata.decimals == 9
    assert metadata.symbol == "SUI"
    assert metadata.name == "Sui"
    assert metadata.icon_url is None
    assert metadata.coin_type == "0x" + "0" * 63 + "2::sui::SUI"


def test_missing_coin_metadata_leaves_decimals_unknown_not_zero() -> None:
    obs = Fixture.observation(
        coin_metadata_bytes=None,
        coin_metadata_type_tag=None,
        coin_metadata_owner_kind=None,
    )
    assert obs.coin_decimals is None
    assert obs.coin_metadata is None
    assert NaviCapacityRejectionCode.COIN_DECIMALS_UNPROVEN.value in (
        obs.constraint_gaps
    )
    assert obs.effective_capacity_units is None


def test_object_version_binding_required() -> None:
    with pytest.raises(MultiChainError) as exc:
        Fixture.pool_capture(version=0)
    assert (
        exc.value.code == NaviCapacityRejectionCode.OBJECT_VERSION_BINDING_MISSING.value
    )
    with pytest.raises(MultiChainError) as exc:
        Fixture.pool_capture(digest="")
    assert exc.value.code == NaviCapacityRejectionCode.OBJECT_DIGEST_REQUIRED.value


def test_wrong_package_id_fails_closed() -> None:
    wrong_package = "0x" + "bada55" + "00" * 29
    pool = Fixture.pool_capture(
        type_tag=f"{wrong_package}::pool::Pool<{REVIEWED_COIN_TYPE}>"
    )
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(pool_capture=pool)
    assert exc.value.code == NaviCapacityRejectionCode.PACKAGE_ID_MISMATCH.value


def test_checkpoint_mismatch_fails_closed() -> None:
    stale_pool = Fixture.pool_capture(checkpoint=CAPTURE_CHECKPOINT + 1)
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(pool_capture=stale_pool)
    assert exc.value.code == NaviCapacityRejectionCode.CHECKPOINT_MISMATCH.value
    stale_epoch_config = Fixture.market_config(
        storage=NaviObjectCapture(
            object_id=SYNTHETIC_STORAGE_ID,
            version=10,
            digest="storage-object-digest-binding",
            type_tag=f"{SYNTHETIC_PACKAGE}::storage::Storage",
            owner_kind=SuiObjectKind.SHARED,
            checkpoint=CAPTURE_CHECKPOINT,
            epoch=CAPTURE_EPOCH + 1,
        )
    )
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(market_config=stale_epoch_config)
    assert exc.value.code == NaviCapacityRejectionCode.CHECKPOINT_MISMATCH.value


def test_unknown_or_mismatched_coin_type_fails_closed() -> None:
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(reviewed_coin_type="0x2::usdc::USDC")
    assert exc.value.code == NaviCapacityRejectionCode.COIN_TYPE_MISMATCH.value
    two_params = Fixture.pool_capture(
        type_tag=(
            f"{SYNTHETIC_PACKAGE}::pool::Pool<{REVIEWED_COIN_TYPE}, "
            f"{REVIEWED_COIN_TYPE}>"
        )
    )
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(pool_capture=two_params)
    assert exc.value.code == NaviCapacityRejectionCode.POOL_OBJECT_TYPE_MISMATCH.value
    no_params = Fixture.pool_capture(type_tag=f"{SYNTHETIC_PACKAGE}::pool::Pool")
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(pool_capture=no_params)
    assert exc.value.code == NaviCapacityRejectionCode.POOL_OBJECT_TYPE_MISMATCH.value


def test_coin_metadata_layout_fail_closed() -> None:
    metadata_tag = f"0x2::coin::CoinMetadata<{REVIEWED_COIN_TYPE}>"
    with pytest.raises(MultiChainError) as exc:
        decode_navi_coin_metadata(
            _coin_metadata_bytes()[:20],
            type_tag=metadata_tag,
            owner_kind=SuiObjectKind.IMMUTABLE,
            expected_coin_type=REVIEWED_COIN_TYPE,
        )
    assert (
        exc.value.code == NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value
    )
    with pytest.raises(MultiChainError) as exc:
        decode_navi_coin_metadata(
            _coin_metadata_bytes(),
            type_tag=f"0x2::coin::CoinMetadata<0x2::usdc::USDC>",
            owner_kind=SuiObjectKind.IMMUTABLE,
            expected_coin_type=REVIEWED_COIN_TYPE,
        )
    assert exc.value.code == NaviCapacityRejectionCode.COIN_TYPE_MISMATCH.value
    with pytest.raises(MultiChainError) as exc:
        decode_navi_coin_metadata(
            _coin_metadata_bytes(),
            type_tag=metadata_tag,
            owner_kind=SuiObjectKind.SHARED,
            expected_coin_type=REVIEWED_COIN_TYPE,
        )
    assert (
        exc.value.code == NaviCapacityRejectionCode.COIN_METADATA_OWNER_MISMATCH.value
    )
    with pytest.raises(MultiChainError) as exc:
        decode_navi_coin_metadata(
            _coin_metadata_bytes(trailing=b"\x2e"),
            type_tag=metadata_tag,
            owner_kind=SuiObjectKind.IMMUTABLE,
            expected_coin_type=REVIEWED_COIN_TYPE,
        )
    assert (
        exc.value.code == NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value
    )
    with pytest.raises(MultiChainError) as exc:
        decode_navi_coin_metadata(
            _coin_metadata_bytes(option_flag=b"\x07"),
            type_tag=metadata_tag,
            owner_kind=SuiObjectKind.IMMUTABLE,
            expected_coin_type=REVIEWED_COIN_TYPE,
        )
    assert (
        exc.value.code == NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value
    )


def test_coin_metadata_icon_url_option_is_decoded() -> None:
    metadata = decode_navi_coin_metadata(
        _coin_metadata_bytes(
            option_flag=b"\x01" + _bcs_string("https://sui.io/icon.svg")
        ),
        type_tag=f"0x2::coin::CoinMetadata<{REVIEWED_COIN_TYPE}>",
        owner_kind=SuiObjectKind.IMMUTABLE,
        expected_coin_type=REVIEWED_COIN_TYPE,
    )
    assert metadata.icon_url == "https://sui.io/icon.svg"


def test_jsonrpc_transport_forbidden() -> None:
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(transport=NaviSuiReadTransport.SUI_JSONRPC)
    assert exc.value.code == NaviCapacityRejectionCode.JSONRPC_TRANSPORT_FORBIDDEN.value


@pytest.mark.parametrize(
    "transport",
    [NaviSuiReadTransport.GOVERNED_GRPC, NaviSuiReadTransport.GOVERNED_GRAPHQL],
)
def test_governed_live_transport_is_typed_blocked_offline(
    transport: NaviSuiReadTransport,
) -> None:
    with pytest.raises(MultiChainError) as exc:
        Fixture.observation(transport=transport)
    assert (
        exc.value.code
        == NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value
    )
    assert exc.value.stage == "authorization"


def test_api_discovery_rows_are_demoted_in_the_data_model() -> None:
    rows = parse_flashloan_api_discovery_rows(Fixture.discovery_rows())
    assert len(rows) == 1
    assert rows[0].evidence_state is (
        NaviCapacityEvidenceState.DISCOVERY_ONLY_OFFCHAIN_API
    )
    assert rows[0].max_decimal == "1000000000000"
    assert rows[0].flashloan_fee == 0
    with pytest.raises(MultiChainError) as exc:
        rows[0].capital_rows({"0x" + "0" * 63 + "2::sui::SUI": 9})
    assert exc.value.code == NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value
    obs = Fixture.observation(api_discovery_rows=Fixture.discovery_rows())
    assert obs.api_discovery_rows[0].evidence_state is (
        NaviCapacityEvidenceState.DISCOVERY_ONLY_OFFCHAIN_API
    )
    assert NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value in (
        obs.constraint_gaps
    )


def test_api_discovery_float_inputs_fail_closed() -> None:
    floated_fee = Fixture.discovery_rows()
    floated_fee[0]["flashloanFee"] = 0.0
    with pytest.raises(MultiChainError) as exc:
        parse_flashloan_api_discovery_rows(floated_fee)
    assert (
        exc.value.code == NaviCapacityRejectionCode.API_DISCOVERY_FLOAT_PRECISION.value
    )
    floated_max = Fixture.discovery_rows()
    floated_max[0]["max"] = 1000000.5
    with pytest.raises(MultiChainError) as exc:
        parse_flashloan_api_discovery_rows(floated_max)
    assert (
        exc.value.code == NaviCapacityRejectionCode.API_DISCOVERY_FLOAT_PRECISION.value
    )
    exponent_max = Fixture.discovery_rows()
    exponent_max[0]["max"] = "1e9"
    with pytest.raises(MultiChainError) as exc:
        parse_flashloan_api_discovery_rows(exponent_max)
    assert (
        exc.value.code == NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value
    )


def test_api_discovery_row_schema_drift_fails_closed() -> None:
    bad_coin = Fixture.discovery_rows()
    bad_coin[0]["coinType"] = "SUI"
    with pytest.raises(MultiChainError):
        parse_flashloan_api_discovery_rows(bad_coin)
    missing = Fixture.discovery_rows()
    del missing[0]["assetId"]
    with pytest.raises(MultiChainError):
        parse_flashloan_api_discovery_rows(missing)
    bad_asset = Fixture.discovery_rows()
    bad_asset[0]["assetId"] = "0"
    with pytest.raises(MultiChainError):
        parse_flashloan_api_discovery_rows(bad_asset)
    bad_pool = Fixture.discovery_rows()
    bad_pool[0]["poolId"] = "0x1234"
    with pytest.raises(MultiChainError):
        parse_flashloan_api_discovery_rows(bad_pool)
    duplicate = Fixture.discovery_rows() * 2
    with pytest.raises(MultiChainError):
        parse_flashloan_api_discovery_rows(duplicate)


def test_api_discovery_rows_cannot_override_evidence_state() -> None:
    with pytest.raises(MultiChainError) as exc:
        NaviFlashloanApiDiscoveryRow(
            coin_type=REVIEWED_COIN_TYPE,
            max_decimal="1000",
            min_decimal="1",
            flashloan_fee=Fraction(0),
            asset_id=0,
            pool_id=SYNTHETIC_POOL_ID,
            evidence_state=NaviCapacityEvidenceState.ONCHAIN_OBJECT_STATE_PROVEN,
        )
    assert exc.value.code == NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value


def test_flash_ptb_shape_pins_v1_v2_entries_and_hot_potato_closure() -> None:
    v1 = navi_flash_ptb_shape(
        1, package_id=SYNTHETIC_PACKAGE, coin_type=REVIEWED_COIN_TYPE
    )
    assert v1[0].function == NAVI_FLASH_ENTRY_V1
    assert v1[0].arguments == ("flashloan_config", "pool", "amount:u64")
    v2 = navi_flash_ptb_shape(
        2, package_id=SYNTHETIC_PACKAGE, coin_type=REVIEWED_COIN_TYPE
    )
    assert v2[0].function == NAVI_FLASH_ENTRY_V2
    assert v2[0].arguments == (
        "flashloan_config",
        "pool",
        "amount:u64",
        "0x05",
    )
    repay = v2[1]
    assert repay.function == NAVI_FLASH_REPAY_ENTRY
    assert repay.arguments == ("0x06", "storage", "pool", "receipt", "coin")
    assert repay.consumes_hot_potato == ("receipt",)
    assert v2[0].produces_hot_potato == ("receipt",)
    with pytest.raises(MultiChainError) as exc:
        navi_flash_ptb_shape(
            3, package_id=SYNTHETIC_PACKAGE, coin_type=REVIEWED_COIN_TYPE
        )
    assert exc.value.code == NaviCapacityRejectionCode.PACKAGE_VERSION_UNKNOWN.value


def test_effective_capacity_cannot_be_fabricated() -> None:
    obs = Fixture.observation()
    with pytest.raises(MultiChainError) as exc:
        dataclasses.replace(obs, effective_capacity_units=1)
    assert exc.value.code == "SUI_CAPACITY_DERIVATION_FORBIDDEN"
    with pytest.raises(MultiChainError) as exc:
        dataclasses.replace(
            obs,
            capacity_derivation=NaviCapacityDerivation.UNPROVEN,
            effective_capacity_units=0,
        )
    assert exc.value.code == "SUI_CAPACITY_DERIVATION_FORBIDDEN"


def test_observation_rejects_missing_live_checkpoint_blocker() -> None:
    obs = Fixture.observation()
    with pytest.raises(MultiChainError) as exc:
        dataclasses.replace(
            obs,
            blockers=(NaviCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,),
        )
    assert exc.value.code == "SUI_LIVE_CHECKPOINT_BLOCKER_REQUIRED"


def test_observation_is_immutable_to_evidence_state_promotion() -> None:
    obs = Fixture.observation()
    with pytest.raises(MultiChainError) as exc:
        dataclasses.replace(
            obs, evidence_state=NaviCapacityEvidenceState.ONCHAIN_OBJECT_STATE_PROVEN
        )
    assert exc.value.code == "SUI_EVIDENCE_STATE_FORBIDDEN"
    with pytest.raises(MultiChainError) as exc:
        dataclasses.replace(obs, transport=NaviSuiReadTransport.GOVERNED_GRPC)
    assert exc.value.code == "SUI_TRANSPORT_NOT_OFFLINE"


def test_evidence_record_replays_and_binds_decoder_identity() -> None:
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
    tampered = dataclasses.replace(
        obs, decoder_generation=NAVI_READER_DECODER_GENERATION + 1
    )
    assert tampered.evidence_digest != obs.evidence_digest
    tampered = dataclasses.replace(obs, execution_authority="SOME")
    assert tampered.evidence_digest != obs.evidence_digest
    assert obs.execution_authority == "NONE"


def test_capital_edge_gate_never_emits_offline() -> None:
    gate = navi_capital_edge_gate(Fixture.observation())
    assert gate.edge is None
    assert (
        gate.blocker
        == NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value
    )
    assert gate.blockers == Fixture.observation().blockers
    assert "gRPC/GraphQL" in gate.note
    assert "independent quorum" in gate.note
