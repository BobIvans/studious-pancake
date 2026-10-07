"""Read-only TON evidence, bounds, aliasing and offline replay contracts."""

import base64
import binascii
from datetime import UTC, datetime
import json

import pytest

from src.discovery.dynamic_universe.ton_radar import (
    StonRadarIngestor,
    TonDiscoveryEnvelope,
    TonSchemaError,
    canonical_ton_address,
    normalize_ston_payload,
    replay_ton_journal,
)
from src.routing.transport import SanitizedTransportError

ASSET_A = "0:" + "11" * 32
ASSET_B = "0:" + "22" * 32
POOL = "0:" + "33" * 32
FIXED_TIME = datetime(2026, 10, 7, tzinfo=UTC)


def fixtures():
    return {
        "assets": {
            "asset_list": [
                {
                    "contract_address": ASSET_A,
                    "meta": {"symbol": "USD", "decimals": "6"},
                },
                {
                    "contract_address": ASSET_B,
                    "meta": {"symbol": "USD", "decimals": "9"},
                },
            ]
        },
        "pools": {
            "pool_list": [
                {"address": POOL, "token0_address": ASSET_A, "token1_address": ASSET_B}
            ]
        },
        "stats": {"stats": {"total_tvl_usd": "1000"}},
    }


class FixtureTransport:
    def __init__(self, responses=None):
        self.responses = fixtures() if responses is None else responses
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        response = self.responses[url.rsplit("/", 1)[-1]]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            return response
        return 200, {}, response


def ingestor(transport, **kwargs):
    return StonRadarIngestor(
        transport,
        campaign_generation="sha:config:campaign-01",
        clock=lambda: FIXED_TIME,
        **kwargs,
    )


async def test_ston_whole_universe_is_research_only_and_replays(tmp_path):
    journal = tmp_path / "ton" / "evidence.jsonl"
    transport = FixtureTransport()
    envelopes = await ingestor(transport, journal_path=journal).poll()
    assert len(transport.calls) == len(envelopes) == 3
    assert replay_ton_journal(journal) == envelopes
    for envelope in envelopes:
        assert envelope.campaign_generation == "sha:config:campaign-01"
        assert envelope.observed_at == FIXED_TIME.isoformat()
        assert not envelope.negative_evidence
        assert envelope.executable is False
        assert envelope.execution_class == "TON_ASYNC_MULTI_CONTRACT"
        for record in envelope.records:
            assert record["verification_state"] == "DISCOVERY_ONLY"
            assert not record["identifier_verified"]
            assert not record["state_verified"]
            assert not record["executable"]
    # Ticker collision remains two unverified address candidates.
    assert len(envelopes[0].records) == 2
    assert {record["symbol"] for record in envelopes[0].records} == {"USD"}
    assert "decimals" not in envelopes[0].records[0]


async def test_budget_rotates_and_empty_budget_does_no_network():
    transport = FixtureTransport()
    radar = ingestor(transport)
    assert await radar.poll(budget=0) == ()
    results = [await radar.poll(budget=1) for _ in range(4)]
    assert [row[0].resource for row in results] == [
        "assets",
        "pools",
        "stats",
        "assets",
    ]
    assert len(transport.calls) == 4
    with pytest.raises(ValueError):
        await radar.poll(budget=5)
    with pytest.raises(ValueError):
        await radar.poll(cursor=-1)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ((429, {"retry-after": "30"}, {"error": "busy"}), "RATE_LIMIT"),
        (TimeoutError("secret URL must not be logged"), "TIMEOUT"),
        (SanitizedTransportError("limited", status_code=429), "RATE_LIMIT"),
        (SanitizedTransportError("transport error", retryable=True), "TRANSPORT_ERROR"),
        ((503, {}, {"error": "down"}), "HTTP_ERROR"),
        (RuntimeError("credentials=do-not-persist"), "PROVIDER_ERROR"),
    ],
)
async def test_blind_windows_are_durable_negative_evidence(tmp_path, response, reason):
    journal = tmp_path / "evidence.jsonl"
    radar = ingestor(FixtureTransport({"assets": response}), journal_path=journal)
    envelope = (await radar.poll(budget=1))[0]
    assert envelope.negative_evidence == (reason,)
    assert envelope.records == ()
    assert replay_ton_journal(journal) == (envelope,)
    assert "do-not-persist" not in journal.read_text()
    if isinstance(response, tuple) and response[0] == 429:
        assert envelope.retry_after == "30"


async def test_schema_drift_fails_entire_batch_and_preserves_raw(tmp_path):
    payload = fixtures()["assets"]
    payload["asset_list"].append({"symbol": "fake-without-address"})
    journal = tmp_path / "evidence.jsonl"
    envelope = (
        await ingestor(
            FixtureTransport({"assets": payload}), journal_path=journal
        ).poll(budget=1)
    )[0]
    assert envelope.records == ()
    assert envelope.negative_evidence[0] == "SCHEMA_ERROR"
    assert json.loads(envelope.payload_json) == payload
    assert replay_ton_journal(journal) == (envelope,)


async def test_record_overflow_does_not_emit_a_partial_universe():
    envelope = (await ingestor(FixtureTransport(), max_records=1).poll(budget=1))[0]
    assert envelope.records == ()
    assert envelope.negative_evidence == (
        "SCHEMA_ERROR",
        "provider record budget exceeded",
    )


def test_duplicate_market_dedup_and_conflicting_order_fail_closed():
    payload = fixtures()["pools"]
    payload["pool_list"] *= 2
    assert len(normalize_ston_payload("pools", payload)) == 1
    payload["pool_list"][1] = {
        "address": POOL,
        "token0_address": ASSET_B,
        "token1_address": ASSET_A,
    }
    with pytest.raises(TonSchemaError, match="disagrees"):
        normalize_ston_payload("pools", payload)


class FixtureOmniston:
    def __init__(self):
        self.calls = []

    async def discover_routes(self, markets, *, max_routes):
        self.calls.append((markets, max_routes))
        return {
            "routes": [
                {
                    "pool_addresses": [POOL],
                    "input_asset": ASSET_A,
                    "output_asset": ASSET_B,
                }
            ]
        }


async def test_optional_omniston_budget_and_shared_pool_alias(tmp_path):
    omniston = FixtureOmniston()
    journal = tmp_path / "ton.jsonl"
    radar = ingestor(FixtureTransport(), omniston=omniston, journal_path=journal)
    assert len(await radar.poll(budget=3)) == 3
    assert omniston.calls == []
    envelopes = await radar.poll(budget=4)
    assert len(envelopes) == 4
    assert len(omniston.calls) == 1
    assert (
        envelopes[1].records[0]["correlation_group"]
        == envelopes[3].records[0]["correlation_group"]
    )
    assert envelopes[3].source == "omniston"
    assert envelopes[3].records[0]["underlying_resources"] == [f"ton:pool:{POOL}"]
    assert len(replay_ton_journal(journal)) == 7


def test_omniston_without_pool_identity_is_not_an_independent_confirmation():
    with pytest.raises(TonSchemaError, match="underlying pool"):
        normalize_ston_payload(
            "routes", {"routes": [{"input_asset": ASSET_A, "output_asset": ASSET_B}]}
        )


def test_friendly_address_crc16_canonicalization_and_testnet_rejection():
    body = bytes([0x11, 0]) + bytes.fromhex("11" * 32)
    friendly = base64.urlsafe_b64encode(
        body + binascii.crc_hqx(body, 0).to_bytes(2, "big")
    ).decode()
    assert canonical_ton_address(friendly) == ASSET_A
    with pytest.raises(TonSchemaError, match="checksum"):
        canonical_ton_address(friendly[:-1] + ("B" if friendly[-1] == "A" else "A"))
    testnet = bytes([0x91]) + body[1:]
    friendly_testnet = base64.urlsafe_b64encode(
        testnet + binascii.crc_hqx(testnet, 0).to_bytes(2, "big")
    ).decode()
    with pytest.raises(TonSchemaError, match="network"):
        canonical_ton_address(friendly_testnet)


async def test_immutable_payload_and_replay_tamper_detection(tmp_path):
    journal = tmp_path / "ton.jsonl"
    envelope = (
        await ingestor(FixtureTransport(), journal_path=journal).poll(budget=1)
    )[0]
    record = envelope.records[0]
    record["executable"] = True
    assert envelope.records[0]["executable"] is False
    serialized = envelope.to_dict()
    serialized["payload_json"] = "{}"
    with pytest.raises(ValueError, match="hash mismatch"):
        TonDiscoveryEnvelope.from_dict(serialized)
    serialized = envelope.to_dict()
    serialized["executable"] = True
    with pytest.raises(ValueError, match="research-only"):
        TonDiscoveryEnvelope.from_dict(serialized)
    serialized = envelope.to_dict()
    altered_records = list(envelope.records)
    altered_records[0]["executable"] = True
    serialized["records_json"] = json.dumps(altered_records)
    journal.write_text(json.dumps(serialized) + "\n")
    with pytest.raises(ValueError, match="research-only"):
        replay_ton_journal(journal)


async def test_non_finite_provider_metadata_is_negative_not_replayable():
    payload = fixtures()["assets"]
    payload["asset_list"][0]["meta"]["price"] = float("nan")
    envelope = (await ingestor(FixtureTransport({"assets": payload})).poll(budget=1))[0]
    assert envelope.records == ()
    assert envelope.negative_evidence[0] == "SCHEMA_ERROR"
    assert envelope.payload_json == "null"
