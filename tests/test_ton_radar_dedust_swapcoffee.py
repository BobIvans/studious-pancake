"""Offline schema-verified decode contracts for DeDust and swap.coffee TON radar.

All fixtures are redacted recorded-schema examples built from the pinned
dossiers (docs/integrations/offline/ton-wave1-2026-11-13/). Zero network.
"""

import base64
import binascii
from datetime import UTC, datetime
import json

import pytest

from src.discovery.dynamic_universe.ton_radar import (
    DedustRadarIngestor,
    SwapCoffeeRadarIngestor,
    TON_NATIVE_ASSET,
    TonSchemaError,
    normalize_dedust_payload,
    normalize_swap_coffee_payload,
    replay_ton_journal,
)
from src.routing.transport import SanitizedTransportError

FIXED_TIME = datetime(2026, 11, 14, tzinfo=UTC)
DEDUST_URL = "https://api.dedust.io/v2/pools"
SWAPCOFFEE_URL = "https://backend.swap.coffee/v1/pools"


def friendly(prefix: int, hex32: str) -> str:
    body = bytes([prefix, 0]) + bytes.fromhex(hex32)
    return (
        base64.urlsafe_b64encode(body + binascii.crc_hqx(body, 0).to_bytes(2, "big"))
        .decode()
        .rstrip("=")
    )


ASSET_A = friendly(0x51, "11" * 32)
ASSET_B = friendly(0x51, "22" * 32)
ASSET_C = friendly(0x51, "33" * 32)
POOL_1 = friendly(0x51, "44" * 32)
POOL_2 = friendly(0x51, "55" * 32)


def dedust_pools_fixture():
    return [
        {
            "address": POOL_1,
            "lt": "40826635000009",
            "totalSupply": "1682429759745607",
            "type": "volatile",
            "tradeFee": "1",
            "assets": [
                {
                    "type": "jetton",
                    "address": ASSET_A,
                    "metadata": {"symbol": "AAA", "decimals": "9"},
                },
                {
                    "type": "jetton",
                    "address": ASSET_B,
                    "metadata": {"symbol": "BBB", "decimals": "6"},
                },
            ],
            "lastPrice": "3.3592561783648293975",
            "reserves": ["235087171534646", "79417613938744"],
            "stats": {"fees": ["1", "2"], "volume": ["10", "20"]},
        },
        {
            "address": POOL_2,
            "lt": "40826635000010",
            "totalSupply": "999",
            "type": "volatile",
            "tradeFee": "1",
            "assets": [
                {"type": "native"},
                {
                    "type": "jetton",
                    "address": ASSET_C,
                    "metadata": {"symbol": "CCC", "decimals": "9"},
                },
            ],
            "lastPrice": "5",
            "reserves": ["1000000000", "42"],
            "stats": {"fees": ["0"], "volume": ["0"]},
        },
    ]


def swapcoffee_page_fixture():
    return {
        "total_count": 2,
        "pools": [
            {
                "pool": {
                    "dex": "stonfi",
                    "address": POOL_1,
                    "type": "public",
                    "amm_type": "constant_product",
                    "tokens": [
                        {
                            "address": {"blockchain": "ton", "address": ASSET_A},
                            "metadata": {
                                "symbol": "AAA",
                                "decimals": 9,
                                "listed": True,
                                "verification": "whitelisted",
                            },
                        },
                        {
                            "address": {"blockchain": "ton", "address": ASSET_B},
                            "metadata": {
                                "symbol": "BBB",
                                "decimals": 6,
                                "listed": True,
                                "verification": "community",
                            },
                        },
                    ],
                    "reserves": [235087171534646.0, 79417613938744.0],
                    "fees": {"average_gas": "0.05", "input": "0.5", "output": "0.5"},
                },
                "info": {
                    "address": POOL_1,
                    "tvl_usd": 1234.5,
                    "volume_usd": 567.8,
                    "fee_usd": 1.2,
                    "apr": 0.1,
                    "lp_apr": 0.08,
                    "boost_apr": 0.0,
                },
            },
            {
                "pool": {
                    # A Tonco candidate arrives through the aggregator; the dex
                    # label is metadata, not a chain identity or confirmation.
                    "dex": "tonco",
                    "address": POOL_2,
                    "type": "public",
                    "amm_type": "concentrated_v3",
                    "tokens": [
                        {
                            "address": {"blockchain": "ton", "address": ASSET_A},
                            "metadata": {
                                "symbol": "AAA",
                                "decimals": 9,
                                "listed": True,
                                "verification": "whitelisted",
                            },
                        },
                        {
                            "address": {"blockchain": "ton", "address": ASSET_C},
                            "metadata": {
                                "symbol": "CCC",
                                "decimals": 9,
                                "listed": False,
                                "verification": "unknown",
                            },
                        },
                    ],
                    "reserves": [1.0, 2.0],
                    "fees": {"average_gas": "0.1"},
                },
                "info": {
                    "address": POOL_2,
                    "tvl_usd": 10.0,
                    "volume_usd": 0.0,
                    "fee_usd": 0.0,
                    "apr": 0.0,
                    "lp_apr": 0.0,
                    "boost_apr": 0.0,
                },
            },
        ],
    }


class FixtureTransport:
    def __init__(self, responses=None, policy=None):
        self.responses = {} if responses is None else responses
        self.calls = []
        if policy is not None:
            self.policy = policy

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            return response
        return 200, {}, response


def dedust_ingestor(transport, **kwargs):
    return DedustRadarIngestor(
        transport,
        campaign_generation="sha:config:campaign-01",
        clock=lambda: FIXED_TIME,
        **kwargs,
    )


def swapcoffee_ingestor(transport, **kwargs):
    return SwapCoffeeRadarIngestor(
        transport,
        campaign_generation="sha:config:campaign-01",
        clock=lambda: FIXED_TIME,
        **kwargs,
    )


async def test_dedust_whole_universe_decodes_and_replays(tmp_path):
    journal = tmp_path / "dedust" / "evidence.jsonl"
    transport = FixtureTransport({DEDUST_URL: dedust_pools_fixture()})
    envelopes = await dedust_ingestor(transport, journal_path=journal).poll()
    assert len(transport.calls) == len(envelopes) == 1
    assert transport.calls[0] == ("GET", DEDUST_URL, {})
    assert replay_ton_journal(journal) == envelopes
    envelope = envelopes[0]
    assert (envelope.source, envelope.resource) == ("dedust.io", "pools")
    assert envelope.source_url == DEDUST_URL
    assert not envelope.negative_evidence
    assert envelope.executable is False
    assert envelope.execution_class == "TON_ASYNC_MULTI_CONTRACT"
    records = envelope.records
    assert len(records) == 2
    native_pool = next(
        record for record in records if record["market_id"] == f"0:{'55' * 32}"
    )
    assert native_pool["asset_a"] == TON_NATIVE_ASSET
    assert native_pool["asset_b"] == f"0:{'33' * 32}"
    assert native_pool["venue"] == "dedust"
    assert native_pool["correlation_group"] == f"ton:pool:{native_pool['market_id']}"
    assert native_pool["provider_metadata"]["reserves"] == ["1000000000", "42"]
    assert "reserves" not in native_pool  # provider values never become identities
    for record in records:
        assert record["verification_state"] == "DISCOVERY_ONLY"
        assert not record["state_verified"]


async def test_dedust_budget_bounds_and_empty_budget_does_no_network():
    transport = FixtureTransport({DEDUST_URL: dedust_pools_fixture()})
    radar = dedust_ingestor(transport)
    assert await radar.poll(budget=0) == ()
    with pytest.raises(ValueError, match="zero or one"):
        await radar.poll(budget=2)
    assert transport.calls == []


async def test_dedust_documented_400_empty_object_is_negative_not_empty_universe(
    tmp_path,
):
    journal = tmp_path / "evidence.jsonl"
    transport = FixtureTransport({DEDUST_URL: {}})
    envelope = (await dedust_ingestor(transport, journal_path=journal).poll())[0]
    assert envelope.negative_evidence == ("SCHEMA_ERROR", "missing pool array")
    assert envelope.records == ()
    assert json.loads(envelope.payload_json) == {}
    assert replay_ton_journal(journal) == (envelope,)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ((429, {"retry-after": "7"}, {"error": "busy"}), "RATE_LIMIT"),
        (TimeoutError("must not be persisted"), "TIMEOUT"),
        (SanitizedTransportError("limited", status_code=429), "RATE_LIMIT"),
        ((503, {}, {"error": "down"}), "HTTP_ERROR"),
        (RuntimeError("credentials=do-not-persist"), "PROVIDER_ERROR"),
    ],
)
async def test_dedust_blind_windows_are_durable_negative_evidence(
    tmp_path, response, reason
):
    journal = tmp_path / "evidence.jsonl"
    radar = dedust_ingestor(
        FixtureTransport({DEDUST_URL: response}), journal_path=journal
    )
    envelope = (await radar.poll())[0]
    assert envelope.negative_evidence == (reason,)
    assert envelope.records == ()
    assert replay_ton_journal(journal) == (envelope,)
    assert "do-not-persist" not in journal.read_text()
    if isinstance(response, tuple) and response[0] == 429:
        assert envelope.retry_after == "7"


async def test_dedust_truncated_row_fails_closed_and_preserves_raw(tmp_path):
    payload = dedust_pools_fixture()
    payload.append({"lt": "123", "reserves": ["1", "2"]})  # truncated record
    journal = tmp_path / "evidence.jsonl"
    envelope = (
        await dedust_ingestor(
            FixtureTransport({DEDUST_URL: payload}), journal_path=journal
        ).poll()
    )[0]
    assert envelope.records == ()
    assert envelope.negative_evidence[0] == "SCHEMA_ERROR"
    assert json.loads(envelope.payload_json) == payload
    assert replay_ton_journal(journal) == (envelope,)


async def test_dedust_oversized_page_fails_closed():
    envelope = (
        await dedust_ingestor(
            FixtureTransport({DEDUST_URL: dedust_pools_fixture()}), max_records=1
        ).poll()
    )[0]
    assert envelope.records == ()
    assert envelope.negative_evidence == (
        "SCHEMA_ERROR",
        "provider record budget exceeded",
    )


def test_dedust_conflicting_duplicate_and_bad_reserves_fail_closed():
    payload = dedust_pools_fixture()
    payload[1] = {**payload[1], "address": POOL_1, "type": "stable"}
    with pytest.raises(TonSchemaError, match="disagrees"):
        normalize_dedust_payload(payload)
    payload = dedust_pools_fixture()
    payload[0]["reserves"] = ["1", "2", "3"]
    with pytest.raises(TonSchemaError, match="reserves"):
        normalize_dedust_payload(payload)


def test_dedust_unverified_asset_type_fails_closed():
    payload = dedust_pools_fixture()
    payload[0]["assets"][1] = {"type": "notarocket"}
    with pytest.raises(TonSchemaError, match="unverified asset type"):
        normalize_dedust_payload(payload)


async def test_failed_page_never_retires_a_market(tmp_path):
    transport = FixtureTransport({DEDUST_URL: (429, {"retry-after": "7"}, {})})
    radar = dedust_ingestor(transport, journal_path=tmp_path / "evidence.jsonl")
    assert (await radar.poll())[0].negative_evidence == ("RATE_LIMIT",)
    transport.responses = {DEDUST_URL: dedust_pools_fixture()}
    envelope = (await radar.poll())[0]
    assert not envelope.negative_evidence and len(envelope.records) == 2


async def test_swapcoffee_page_decodes_and_replays(tmp_path):
    journal = tmp_path / "swapcoffee" / "evidence.jsonl"
    transport = FixtureTransport({SWAPCOFFEE_URL: swapcoffee_page_fixture()})
    envelopes = await swapcoffee_ingestor(transport, journal_path=journal).poll()
    assert len(transport.calls) == len(envelopes) == 1
    method, url, kwargs = transport.calls[0]
    assert (method, url) == ("GET", SWAPCOFFEE_URL)
    assert kwargs["params"] == {
        "blockchains": "ton",
        "trusted": "false",
        "size": "100",
        "page": "1",
    }
    assert replay_ton_journal(journal) == envelopes
    envelope = envelopes[0]
    assert (envelope.source, envelope.resource) == ("swap.coffee", "pools")
    assert not envelope.negative_evidence
    records = envelope.records
    assert len(records) == 2
    tonco_record = next(
        record for record in records if record["provider_dex"] == "tonco"
    )
    assert tonco_record["asset_a"] == f"0:{'11' * 32}"
    assert tonco_record["asset_b"] == f"0:{'33' * 32}"
    assert tonco_record["verification_state"] == "DISCOVERY_ONLY"
    assert tonco_record["provider_metadata"]["dex"] == "tonco"
    ston_record = next(
        record for record in records if record["provider_dex"] == "stonfi"
    )
    assert ston_record["correlation_group"] == f"ton:pool:{ston_record['market_id']}"


async def test_swapcoffee_page_cursor_rotates_and_wraps():
    transport = FixtureTransport({SWAPCOFFEE_URL: swapcoffee_page_fixture()})
    radar = swapcoffee_ingestor(transport, max_pages=3)
    await radar.poll(budget=2)
    assert [call[2]["params"]["page"] for call in transport.calls] == ["1", "2"]
    await radar.poll(budget=2)
    assert [call[2]["params"]["page"] for call in transport.calls][2:] == ["3", "1"]
    await radar.poll(budget=0)
    assert len(transport.calls) == 4


async def test_swapcoffee_bounds_fail_closed():
    with pytest.raises(ValueError, match="page size"):
        swapcoffee_ingestor(FixtureTransport(), page_size=101)
    with pytest.raises(ValueError, match="page cursor"):
        swapcoffee_ingestor(FixtureTransport(), max_pages=25_001)
    with pytest.raises(ValueError, match="zero and four"):
        await swapcoffee_ingestor(FixtureTransport({SWAPCOFFEE_URL: []})).poll(budget=5)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ((429, {"retry-after": "60"}, {"error": "Too Many Requests"}), "RATE_LIMIT"),
        (SanitizedTransportError("limited", status_code=429), "RATE_LIMIT"),
        ((500, {}, {"error": "boom"}), "HTTP_ERROR"),
        (TimeoutError("must not be persisted"), "TIMEOUT"),
    ],
)
async def test_swapcoffee_blind_windows_are_durable_negative_evidence(
    tmp_path, response, reason
):
    journal = tmp_path / "evidence.jsonl"
    radar = swapcoffee_ingestor(
        FixtureTransport({SWAPCOFFEE_URL: response}), journal_path=journal
    )
    envelope = (await radar.poll())[0]
    assert envelope.negative_evidence == (reason,)
    assert envelope.records == ()
    assert replay_ton_journal(journal) == (envelope,)
    assert "do-not-persist" not in journal.read_text()


async def test_swapcoffee_error_object_and_drift_fail_closed(tmp_path):
    cases = [
        ({"error": "bad request"}, "missing pools array"),
        ({"total_count": 1, "pools": [{"pool": None, "info": {}}]}, "pool row lacks"),
        (
            {"total_count": 1, "pools": [{"pool": {}, "info": {}}]},
            "missing TON address",
        ),
        ({"pools": [], "total_count": -1}, "total_count"),
        (
            {
                "total_count": 1,
                "pools": [
                    {
                        "pool": {
                            "dex": "stonfi",
                            "address": POOL_1,
                            "tokens": [
                                {"address": {"blockchain": "sol", "address": "x"}},
                                {"address": {"blockchain": "ton", "address": ASSET_A}},
                            ],
                        },
                        "info": {},
                    }
                ],
            },
            "outside the TON universe",
        ),
    ]
    for payload, message in cases:
        envelope = (
            await swapcoffee_ingestor(
                FixtureTransport({SWAPCOFFEE_URL: payload}),
                journal_path=tmp_path / "evidence.jsonl",
            ).poll()
        )[0]
        assert envelope.records == ()
        assert envelope.negative_evidence[0] == "SCHEMA_ERROR"
        assert message in envelope.negative_evidence[1]


async def test_swapcoffee_oversized_page_and_cross_page_identity_conflict():
    envelope = (
        await swapcoffee_ingestor(
            FixtureTransport({SWAPCOFFEE_URL: swapcoffee_page_fixture()}),
            max_records=1,
        ).poll()
    )[0]
    assert envelope.negative_evidence == (
        "SCHEMA_ERROR",
        "provider record budget exceeded",
    )
    page = swapcoffee_page_fixture()
    conflict = json.loads(json.dumps(page))
    conflict["pools"][1]["pool"]["dex"] = "dedust"  # same address, other label
    conflict["pools"][1]["pool"]["address"] = POOL_1
    with pytest.raises(TonSchemaError, match="disagrees"):
        normalize_swap_coffee_payload(conflict)


async def test_nan_provider_value_is_typed_negative_not_replayable():
    payload = dedust_pools_fixture()
    payload[0]["reserves"] = [float("nan"), "2"]
    transport = FixtureTransport({DEDUST_URL: payload})
    envelope = (await dedust_ingestor(transport).poll())[0]
    assert envelope.records == ()
    assert envelope.negative_evidence == (
        "SCHEMA_ERROR",
        "non-replayable provider payload",
    )
    assert envelope.payload_json == "null"


async def test_unknown_replay_source_fails_closed(tmp_path):
    transport = FixtureTransport({DEDUST_URL: dedust_pools_fixture()})
    envelope = (await dedust_ingestor(transport).poll())[0]
    serialized = envelope.to_dict()
    serialized["source"] = "unknown-aggregator"
    (tmp_path / "journal.jsonl").write_text(json.dumps(serialized) + "\n")
    with pytest.raises(ValueError, match="unknown TON replay"):
        replay_ton_journal(tmp_path / "journal.jsonl")
