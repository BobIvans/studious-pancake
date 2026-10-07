"""The real runner retains governed evidence and denies missing source reviews."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.qualification_campaign.identity import CampaignManifest, digest
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.solana_parallel_radar import din_discovery as runner
from src.strategy.exact_cpmm_capacity import WSOL_MINT
from tests.native_cpmm_fixtures import address

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def pin(tmp_path):
    p = tmp_path / "docs.txt"
    p.write_bytes(b"reviewed fixture contract")
    return {
        "dexscreener": {
            "path": str(p),
            "url": "https://docs.dexscreener.com/api/reference",
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "checked_at": datetime.now(UTC).isoformat(),
        }
    }


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (
            200,
            [
                {
                    "chainId": "solana",
                    "pairAddress": address(77),
                    "baseToken": {"address": WSOL_MINT},
                    "quoteToken": {"address": USDC},
                    "dexId": "raydium",
                }
            ],
            1,
        ),
        (429, {"error": "quota"}, 0),
        (200, {"changed": "schema"}, 0),
    ],
)
def test_capture_preserves_real_owner_envelopes_and_only_admits_reviewed_sources(
    tmp_path, monkeypatch, status, payload, expected
):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json=payload, headers={"Retry-After": "60"} if status == 429 else {}
        )

    @asynccontextmanager
    async def transport(hosts, *, policy):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as client:
            yield HttpxJsonTransport(
                client=client, allowed_hosts=frozenset(hosts), policy=policy
            )

    def manifest(root, *, main_sha, configuration, sources):
        return CampaignManifest(
            "a" * 40,
            main_sha,
            "b" * 64,
            tuple((k, digest(v)) for k, v in configuration.items()),
            tuple((k, digest(v)) for k, v in sources.items()),
        )

    monkeypatch.setattr(runner, "campaign_transport", transport)
    monkeypatch.setattr(runner.CampaignManifest, "create", manifest)
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "capture"
    result = asyncio.run(
        runner.capture(root, output, mints=(WSOL_MINT, USDC), pins=pin(tmp_path))
    )
    assert len(calls) == 1 and len(result["blocked_sources"]) == 3
    assert result["deduplicated_candidates"] == expected
    assert (
        result["exact_status"]
        == result["paper_status"]
        == result["production_status"]
        == "BLOCKED"
    )
    assert not result["sign_enabled"] and not result["send_enabled"]
    receipt = result["receipts"][0]
    assert receipt.get("http_status") == status
    if status == 429:
        assert (
            receipt["quality_state"] == "rate-limited"
            and receipt["retry_after"] == "60"
        )
    export = json.loads((output / "retained-evidence.json").read_text())
    raw = next(e for e in export["expanded_rows"] if e["kind"] == "source_observation")
    assert raw["response_hash"] == receipt["response_hash"]
    replay = runner.replay(output, tmp_path / "replay")
    assert replay["replay_identical"] and replay["network_reads"] == 0
    exported = output / "retained-evidence.json"
    exported.write_bytes(exported.read_bytes() + b" ")
    with pytest.raises(ValueError, match="HASH_OR_SIZE"):
        runner.replay(output, tmp_path / "tampered-replay")
    if status == 200 and expected:
        assert result["candidate_receipts"] == 1


def test_no_review_and_docs_tampering_cannot_create_live_source(tmp_path):
    sources, blocked = runner.reviewed_sources((WSOL_MINT, USDC), {})
    assert (
        not sources
        and len(blocked) == 4
        and all(r["physical_calls"] == 0 for r in blocked)
    )
    pins = pin(tmp_path)
    Path(pins["dexscreener"]["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="HASH_OR_SIZE"):
        runner.reviewed_sources((WSOL_MINT, USDC), pins)
