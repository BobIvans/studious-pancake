import asyncio
import copy
from dataclasses import asdict, replace
import json
import time

import httpx
import pytest

from tests.native_cpmm_fixtures import synthetic_capture
from src.durability import UnifiedLifecycleAuthority
from src.market.native_cpmm_capture import GovernedNativeCpmmCollector
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.rpc import NativeRootedSnapshotProvider


def profiles():
    return (
        ProviderProfile(
            "rpc-a",
            "a",
            "operator-a",
            "backend-a",
            "https://rpc-a.test",
            "https://docs.test/a",
        ),
        ProviderProfile(
            "rpc-b",
            "b",
            "operator-b",
            "backend-b",
            "https://rpc-b.test",
            "https://docs.test/b",
        ),
    )


def manifest(ps):
    return CampaignManifest(
        "a" * 40,
        "b" * 40,
        "c" * 64,
        (("capture", "d" * 64),),
        tuple((p.profile_id, p.generation) for p in ps),
    )


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "single",
        "operator",
        "provider",
        "correlation",
        "smoke",
        "conflict",
        "rate-limit",
        "timeout",
        "root-lag",
        "genesis",
    ],
)
def test_native_quorum_uses_real_collector_and_preserves_negative_evidence(
    tmp_path, fault
):
    async def run():
        ps = profiles()
        if fault == "single":
            ps = ps[:1]
        elif fault in ("operator", "provider", "correlation"):
            field = {
                "operator": "operator",
                "provider": "provider",
                "correlation": "correlation_group",
            }[fault]
            ps = (ps[0], replace(ps[1], **{field: getattr(ps[0], field)}))
        elif fault == "smoke":
            ps = (replace(ps[0], smoke_only=True), ps[1])
        fixture = synthetic_capture()
        raw = {a["address"]: a["value"] for a in fixture["accounts"]}
        calls = []

        def handler(req):
            body = json.loads(req.content)
            calls.append((req.url.host, body["method"]))
            b = req.url.host == "rpc-b.test"
            if b and fault == "rate-limit":
                return httpx.Response(
                    429, headers={"retry-after": "8"}, json={"error": "quota"}
                )
            if b and fault == "timeout":
                raise httpx.ReadTimeout(
                    "sensitive endpoint must not appear", request=req
                )
            method = body["method"]
            if method == "getGenesisHash":
                result = "wrong" if b and fault == "genesis" else MAINNET_GENESIS
            elif method == "getMultipleAccounts":
                result = {
                    "context": {"slot": 100},
                    "value": [copy.deepcopy(raw[a]) for a in body["params"][0]],
                }
                if b and fault == "conflict" and len(body["params"][0]) > 5:
                    # Balance evidence is part of exact bytes, even if the decoder ignores this increment.
                    result["value"][0]["lamports"] += 1
            elif method == "getBlock":
                result = fixture["block"]
            elif method == "getVersion":
                result = {"solana-core": "3.1.0", "feature-set": 123}
            elif method == "getSlot":
                result = (
                    99
                    if b
                    and fault == "root-lag"
                    and body["params"][0]["commitment"] == "finalized"
                    else 100
                )
            else:
                raise AssertionError(method)
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            trust_env=False,
            follow_redirects=False,
        )
        transport = HttpxJsonTransport(
            policy=TransportPolicy(max_attempts=1, max_string_length=900_000),
            allowed_hosts=frozenset(p.hostname for p in ps),
            client=client,
        )
        store = UnifiedLifecycleAuthority(
            tmp_path / "authority.sqlite",
            release_digest="c" * 64,
            policy_bundle_hash="d" * 64,
        )
        gov = ProviderGovernance(
            {
                p.profile_id: p.entitlement(
                    expires_at_epoch_seconds=int(time.time()) + 600
                )
                for p in ps
            },
            store=store,
        )
        journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
        evidence = CampaignEvidenceStore(
            journal, manifest(ps), wall_ns=lambda: 1002 * 10**9
        )
        collectors = [
            GovernedNativeCpmmCollector(
                gov,
                transport,
                profile=p,
                evidence_store=evidence,
                wall_ns=lambda: 1002 * 10**9,
            )
            for p in ps
        ]
        provider = NativeRootedSnapshotProvider(
            collectors,
            evidence,
            monotonic_ms=lambda: 10_000,
            wall_ns=lambda: 1002 * 10**9,
        )
        injected = GovernedNativeCpmmCollector(
            gov, transport, profile=ps[0], snapshot_provider=provider
        )
        payload = await injected.collect(tuple(fixture["pool_ids"]))
        assert payload["rpc_quorum"]["accepted"] is (fault == "none")
        assert payload["campaign_manifest_hash"] == manifest(ps).campaign_id
        if fault == "single":
            assert payload["rpc_quorum"]["reason"] == "BLOCKED_SINGLE_SOURCE"
        events = evidence.replay()
        assert any(e["kind"] == "rooted_snapshot_bundle" for e in events)
        if fault == "rate-limit":
            receipt = next(e for e in events if e.get("http_status") == 429)
            assert receipt["quality_state"] == "rate-limited"
            assert receipt["raw_response"] == {"error": "quota"}
            assert receipt["retry_after"] == "8"
        if fault == "timeout":
            assert any(e.get("error") for e in events)
        before = evidence.head
        journal.close()
        reopened = RecoverableStreamJournal(tmp_path / "events.sqlite")
        assert CampaignEvidenceStore(reopened, manifest(ps)).head == before
        assert CampaignEvidenceStore(reopened, manifest(ps)).replay() == events
        reopened.close()
        store.close()
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())


def test_profile_endpoint_and_generation_checks():
    p = profiles()[0]
    assert replace(p, endpoint="https://rpc-new.test").generation != p.generation
    with pytest.raises(ValueError):
        replace(p, endpoint="https://rpc.test/?api-key=secret")
    with pytest.raises(ValueError):
        replace(p, request_limit=0)


def test_attempt_cap_survives_restart_and_campaigns_cannot_mix(tmp_path):
    p = replace(profiles()[0], campaign_attempt_cap=1)
    m = manifest((p,))
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    evidence = CampaignEvidenceStore(journal, m)
    evidence.claim_attempt(p)
    journal.close()
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    reopened = CampaignEvidenceStore(journal, m)
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        reopened.claim_attempt(p)
    with pytest.raises(ValueError, match="GENERATION_MISMATCH"):
        CampaignEvidenceStore(journal, replace(m, repository_sha="f" * 40))
    journal.close()


def test_active_mainnet_identity_uses_full_rpc_hash():
    from src.config.chain_registry import ChainRegistry, decode_base58
    from src.config.runtime import ClusterConfig

    assert len(decode_base58(MAINNET_GENESIS)) == 32
    assert (
        ChainRegistry.load_default().canonical_genesis_hashes["mainnet-beta"]
        == MAINNET_GENESIS
    )
    assert ClusterConfig().genesis_hash == MAINNET_GENESIS


def test_large_evidence_blob_is_durable_hash_verified_and_bounded(tmp_path):
    p = profiles()[0]
    m = manifest((p,))
    path = tmp_path / "events.sqlite"
    journal = RecoverableStreamJournal(path)
    evidence = CampaignEvidenceStore(journal, m)
    raw = {"kind": "raw-native-test", "data": "a" * 900_000}
    evidence.append(p.profile_id, raw, observed_at_ns=time.time_ns())
    assert evidence.replay()[-1]["data"] == raw["data"]
    head = evidence.head
    journal.close()
    journal = RecoverableStreamJournal(path)
    evidence = CampaignEvidenceStore(journal, m)
    assert evidence.head == head
    assert evidence.replay()[-1]["data"] == raw["data"]
    blob = next(evidence.blob_dir.glob("*.json"))
    blob.write_text(blob.read_text().replace("aaa", "aab", 1))
    with pytest.raises(ValueError, match="BLOB_HASH_MISMATCH"):
        evidence.replay()
    journal.close()
