from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
import json
import time

import httpx
import pytest

from tests.native_cpmm_fixtures import (
    address,
    mutate_account,
    pub,
    put,
    rehash,
    synthetic_capture,
)
from src.durability import UnifiedLifecycleAuthority
from src.providers.raydium_cpmm_native import (
    CLOCK,
    NativeAccount,
    NativeCaptureError,
    canonical_json,
    decode_native_capture,
    pool_pointers,
)
from src.market.native_cpmm_capture import (
    RPC_PROVIDER,
    SOURCE,
    GovernedNativeCpmmCollector,
    partition_for,
    persist_capture,
    public_read_entitlements,
)
from src.market.observations import ObservationError
from src.market.streams import RecoverableStreamJournal
from src.paper_shadow.native_cpmm_qualification import replay_native_journal
from src.provider_governance import ProviderAdmissionError, ProviderGovernance
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.strategy.exact_cpmm_capacity import (
    MAINNET_GENESIS,
    RAYDIUM_CPMM_PROGRAM_ID,
    WSOL_MINT,
    QualifiedRaydiumCpmmAdapter,
    enumerate_exact_cpmm_routes,
)

pytestmark = pytest.mark.unit


def pointers(payload):
    entry = next(
        a for a in payload["accounts"] if a["address"] == payload["pool_ids"][0]
    )
    return pool_pointers(NativeAccount.from_rpc(entry["address"], entry["value"]))


def test_raw_decode_uses_net_reserves_and_existing_integer_owner():
    capture = decode_native_capture(synthetic_capture())
    state = capture.pools[0]
    assert {state.reserve_a, state.reserve_b} == {333, 9170}
    assert state.accrued_fees_a == (7, 13, 19)
    assert state.accrued_fees_b == (11, 17, 23)
    assert state.trade_fee_rate_ppm == 2500
    assert state.creator_fee_rate_ppm == 1000
    asset = next(a for a in (state.asset_a, state.asset_b) if a.mint == WSOL_MINT)
    small = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=asset, requested_input=10
    )
    large = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=asset, requested_input=100
    )
    assert large.expected_output != small.expected_output * 10
    assert capture.evidence_kind == "synthetic-fixture"


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "discriminator",
        "size",
        "missing",
        "vault-mint",
        "vault-owner",
        "frozen",
        "delegate",
        "mint-decimals",
        "token2022",
        "fee-counters",
        "paused",
        "not-open",
        "oracle",
        "clock",
        "root",
        "context",
        "hash",
        "genesis",
        "deployment",
        "rpc-claim",
        "native-backing",
    ],
)
def test_native_decoder_rejects_incomplete_or_unsupported_evidence(fault):
    payload = synthetic_capture()
    p = pointers(payload)
    changes = {
        "discriminator": (p.pool, lambda d: d.__setitem__(0, 0)),
        "size": (p.pool, lambda d: d.extend(b"x")),
        "vault-mint": (p.vaults[0], lambda d: pub(d, 0, address(99))),
        "frozen": (p.vaults[0], lambda d: d.__setitem__(108, 2)),
        "delegate": (p.vaults[0], lambda d: put(d, 72, 1, 4)),
        "mint-decimals": (p.mints[0], lambda d: d.__setitem__(44, 6)),
        "token2022": (p.pool, lambda d: pub(d, 232, address(99))),
        "fee-counters": (p.pool, lambda d: put(d, 341, 2**63)),
        "paused": (p.pool, lambda d: d.__setitem__(329, 4)),
        "not-open": (p.pool, lambda d: put(d, 373, 2000)),
        "oracle": (p.observation, lambda d: pub(d, 11, address(99))),
        "clock": (CLOCK, lambda d: put(d, 0, 101)),
        "deployment": (address(80), lambda d: put(d, 4, 101)),
    }
    if fault in changes:
        mutate_account(payload, *changes[fault])
    elif fault in {"owner", "vault-owner"}:
        target = p.pool if fault == "owner" else p.vaults[0]
        next(a for a in payload["accounts"] if a["address"] == target)["value"][
            "owner"
        ] = address(99)
        rehash(payload)
    elif fault == "missing":
        payload["accounts"] = [
            a for a in payload["accounts"] if a["address"] != p.vaults[0]
        ]
        rehash(payload)
    elif fault == "root":
        payload["block"]["parentSlot"] = 100
    elif fault == "context":
        payload["account_response_metadata"]["result"]["context"]["slot"] = 101
    elif fault == "hash":
        payload["account_response_hash"] = "b" * 64
    elif fault == "genesis":
        payload["genesis_hash"] = "other"
    elif fault == "rpc-claim":
        payload["evidence_kind"] = "captured-rpc"
    elif fault == "native-backing":
        target = p.vaults[p.mints.index(WSOL_MINT)]
        next(a for a in payload["accounts"] if a["address"] == target)["value"][
            "lamports"
        ] = 1
        rehash(payload)
    with pytest.raises((NativeCaptureError, ValueError)):
        decode_native_capture(payload)


@pytest.mark.parametrize("fourth", [False, True])
def test_restart_replay_amount_coupling_trace_identity_and_no_lookahead(
    tmp_path, fourth
):
    payload = synthetic_capture(fourth=fourth)
    partition = partition_for(tuple(payload["pool_ids"]))
    path = tmp_path / "raw.sqlite"
    journal = RecoverableStreamJournal(path)
    event = persist_capture(journal, payload)
    kwargs = dict(
        partition=partition,
        as_of_ns=payload["available_at_ns"],
        lower_amount=10,
        upper_amount=30,
        max_points=3,
    )
    before = replay_native_journal(journal, **kwargs)
    assert before["evidence_kind"] == "synthetic-fixture"
    assert before["topology_plans"] == 2
    assert all(
        len(set(r["markets"])) == len(r["markets"])
        for r in before["gross_shadow_candidates"]
    )
    assert all(
        r["hops"] == (4 if fourth else 3) for r in before["gross_shadow_candidates"]
    )
    assert before["gross_shadow_candidates"]
    for route in before["gross_shadow_candidates"]:
        for left, right in zip(route["legs"], route["legs"][1:]):
            assert left["output"] == right["input"]
            assert left["output_mint"] == right["input_mint"]
    assert before["qualification"]["overall"] == "BLOCKED"
    assert before["coverage"]["batch_complete"]
    assert before["traces"] and all(
        t["response_hash"] == payload["account_response_hash"] for t in before["traces"]
    )
    journal.close()
    journal = RecoverableStreamJournal(path)
    assert canonical_json(before) == canonical_json(
        replay_native_journal(journal, **kwargs)
    )
    with pytest.raises(ObservationError, match="repaired snapshot"):
        replay_native_journal(
            journal, **{**kwargs, "as_of_ns": payload["available_at_ns"] - 1}
        )
    with pytest.raises(NativeCaptureError, match="stale"):
        replay_native_journal(journal, **{**kwargs, "as_of_ns": 1200 * 10**9})
    # A later correction changes route evidence without altering historical replay.
    corrected = copy.deepcopy(payload)
    corrected["available_at_ns"] += 10**9
    corrected["observed_at_ns"] += 10**9
    p = pointers(corrected)
    mutate_account(corrected, p.vaults[0], lambda d: put(d, 64, 500))
    persist_capture(journal, corrected)
    assert canonical_json(before) == canonical_json(
        replay_native_journal(journal, **kwargs)
    )
    changed = replay_native_journal(
        journal, **{**kwargs, "as_of_ns": corrected["available_at_ns"]}
    )
    assert changed["capture_hash"] != before["capture_hash"]
    assert changed["journal_head"] != event.identity
    journal.close()


@pytest.mark.parametrize("global_barrier", [False, True])
def test_durable_gap_barrier_blocks_old_prefix_until_full_repair(
    tmp_path, global_barrier
):
    payload = synthetic_capture()
    journal = RecoverableStreamJournal(tmp_path / "raw.sqlite")
    event = persist_capture(journal, payload)
    barrier_at = event.available_at_ns + 1
    journal.block(
        source=SOURCE,
        partition="*" if global_barrier else event.partition,
        available_at_ns=barrier_at,
        reason="observed-gap",
    )
    journal.close()
    journal = RecoverableStreamJournal(tmp_path / "raw.sqlite")
    assert (
        journal.reconstruct_with_head(
            source=SOURCE,
            partition=event.partition,
            available_at_ns=event.available_at_ns,
        )[1]
        == event
    )
    with pytest.raises(ObservationError, match="barrier"):
        journal.reconstruct(
            source=SOURCE, partition=event.partition, available_at_ns=barrier_at
        )
    repair = copy.deepcopy(payload)
    repair["available_at_ns"] += 2
    persist_capture(journal, repair)
    assert (
        journal.reconstruct_with_head(
            source=SOURCE,
            partition=event.partition,
            available_at_ns=repair["available_at_ns"],
        )[1].cursor
        == repair["available_at_ns"]
    )
    journal.close()


def test_topology_limits_order_and_repeated_venue_rejection():
    states = decode_native_capture(synthetic_capture()).pools
    base = next(
        a for p in states for a in (p.asset_a, p.asset_b) if a.mint == WSOL_MINT
    )
    first = enumerate_exact_cpmm_routes(states, base)
    assert first == enumerate_exact_cpmm_routes(tuple(reversed(states)), base)
    assert (
        enumerate_exact_cpmm_routes(states, base, max_expansions=1).stop_reason
        == "expansion-limit"
    )
    assert (
        enumerate_exact_cpmm_routes(states, base, max_plans=1).stop_reason
        == "plan-limit"
    )
    with pytest.raises(ValueError, match="unique"):
        enumerate_exact_cpmm_routes((*states, states[0]), base)


def transport_with(handler, *, max_attempts=1):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
    )
    transport = HttpxJsonTransport(
        policy=TransportPolicy(max_attempts=max_attempts, max_string_length=900_000),
        allowed_hosts=frozenset({"api.mainnet-beta.solana.com"}),
        client=client,
    )
    return client, transport


def test_governed_collector_one_bank_root_receipts_and_physical_charges(tmp_path):
    async def run():
        fixture = synthetic_capture()
        raw = {a["address"]: a["value"] for a in fixture["accounts"]}
        calls = []

        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            method = body["method"]
            if method == "getGenesisHash":
                result = MAINNET_GENESIS
            elif method == "getMultipleAccounts":
                result = {
                    "context": {"slot": 100},
                    "value": [raw[a] for a in body["params"][0]],
                }
            else:
                assert method == "getBlock"
                result = fixture["block"]
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
            )

        store = UnifiedLifecycleAuthority(
            tmp_path / "authority.sqlite",
            release_digest="a" * 64,
            policy_bundle_hash="b" * 64,
        )
        manifests = public_read_entitlements(
            expires_at_epoch_seconds=int(time.time()) + 600
        )
        governance = ProviderGovernance(manifests, store=store)
        client, transport = transport_with(handler)
        collector = GovernedNativeCpmmCollector(
            governance, transport, wall_ns=lambda: 1002 * 10**9
        )
        payload = await collector.collect(tuple(fixture["pool_ids"]))
        assert len(calls) == 4
        assert calls[2]["params"][1]["minContextSlot"] == 100
        assert payload["evidence_kind"] == "captured-rpc"
        capture = decode_native_capture(payload)
        assert capture.slot == 100
        assert (await governance.snapshot(RPC_PROVIDER))["committed_requests"] == 4
        journal = RecoverableStreamJournal(tmp_path / "raw.sqlite")
        event = persist_capture(journal, payload)
        report = replay_native_journal(
            journal,
            partition=event.partition,
            as_of_ns=payload["available_at_ns"],
            lower_amount=10,
            upper_amount=30,
            max_points=3,
        )
        assert report["evidence_kind"] == "captured-rpc"
        # Mock RPC is still no proof that source matches an actual deployment.
        assert report["qualification"]["deployment_source_binding"] == "MISSING"
        journal.close()
        await transport.aclose()
        await client.aclose()
        store.close()

    asyncio.run(run())


def test_retry_is_charged_and_invalid_schema_cannot_publish():
    async def run():
        seen = []

        def handler(request):
            seen.append(request)
            if len(seen) == 1:
                return httpx.Response(503, json={})
            body = json.loads(request.content)
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -1}}
            )

        governance = ProviderGovernance(
            public_read_entitlements(expires_at_epoch_seconds=2000),
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        client, transport = transport_with(handler, max_attempts=2)
        collector = GovernedNativeCpmmCollector(governance, transport)
        with pytest.raises(NativeCaptureError, match="schema"):
            await collector.collect(tuple(synthetic_capture()["pool_ids"]))
        assert len(seen) == 2
        assert (await governance.snapshot(RPC_PROVIDER))["committed_requests"] == 2
        assert collector.receipts[-1]["error"] == "NativeCaptureError"
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())


def test_cancelled_physical_read_preserves_durable_quota_and_blocks_old_state(tmp_path):
    async def run():
        fixture = synthetic_capture()
        journal = RecoverableStreamJournal(tmp_path / "raw.sqlite")
        previous = persist_capture(journal, fixture)
        store = UnifiedLifecycleAuthority(
            tmp_path / "authority.sqlite",
            release_digest="a" * 64,
            policy_bundle_hash="b" * 64,
        )
        manifests = public_read_entitlements(
            expires_at_epoch_seconds=int(time.time()) + 600
        )
        governance = ProviderGovernance(manifests, store=store)

        async def handler(request):
            raise asyncio.CancelledError()

        client, transport = transport_with(handler)
        collector = GovernedNativeCpmmCollector(
            governance, transport, wall_ns=lambda: previous.available_at_ns + 1
        )
        with pytest.raises(asyncio.CancelledError):
            await collector.collect_into(journal, tuple(fixture["pool_ids"]))
        state = await governance.snapshot(RPC_PROVIDER)
        assert state["reserved_requests"] + state["committed_requests"] == 1
        await transport.aclose()
        await client.aclose()
        store.close()
        journal.close()
        # A new process cannot refill quota or resurrect the prior prefix.
        store = UnifiedLifecycleAuthority(
            tmp_path / "authority.sqlite",
            release_digest="a" * 64,
            policy_bundle_hash="b" * 64,
        )
        recovered = ProviderGovernance(manifests, store=store)
        state = await recovered.snapshot(RPC_PROVIDER)
        assert state["reserved_requests"] + state["committed_requests"] == 1
        journal = RecoverableStreamJournal(tmp_path / "raw.sqlite")
        with pytest.raises(ObservationError, match="barrier"):
            replay_native_journal(
                journal,
                partition=previous.partition,
                as_of_ns=previous.available_at_ns + 1,
            )
        journal.close()
        store.close()

    asyncio.run(run())


def test_expired_scope_and_effectful_rpc_are_rejected_before_io():
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})

        governance = ProviderGovernance(
            public_read_entitlements(expires_at_epoch_seconds=1001),
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        client, transport = transport_with(handler)
        collector = GovernedNativeCpmmCollector(governance, transport)
        with pytest.raises(NativeCaptureError, match="scope"):
            await collector._rpc("sendTransaction", [])
        with pytest.raises(ProviderAdmissionError):
            await collector.collect(tuple(synthetic_capture()["pool_ids"]))
        assert calls == []
        assert (await governance.snapshot(RPC_PROVIDER))["committed_requests"] == 0
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())


def test_pointer_drift_requires_new_complete_bank_before_root_lookup():
    async def run():
        fixture = synthetic_capture()
        raw = {a["address"]: a["value"] for a in fixture["accounts"]}
        changed = copy.deepcopy(fixture)
        mutate_account(
            changed, changed["pool_ids"][0], lambda d: pub(d, 72, address(99))
        )
        drifted = {a["address"]: a["value"] for a in changed["accounts"]}
        calls = []

        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            if body["method"] == "getGenesisHash":
                result = MAINNET_GENESIS
            else:
                assert body["method"] == "getMultipleAccounts"
                source = drifted if len(calls) == 3 else raw
                result = {
                    "context": {"slot": 100},
                    "value": [source[a] for a in body["params"][0]],
                }
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
            )

        governance = ProviderGovernance(
            public_read_entitlements(expires_at_epoch_seconds=2000),
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        client, transport = transport_with(handler)
        collector = GovernedNativeCpmmCollector(
            governance, transport, wall_ns=lambda: 1002 * 10**9
        )
        with pytest.raises(NativeCaptureError, match="pointers"):
            await collector.collect(tuple(fixture["pool_ids"]))
        assert len(calls) == 3
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())


def test_finalized_bank_conflict_is_a_durable_barrier(tmp_path):
    fixture = synthetic_capture()
    journal = RecoverableStreamJournal(tmp_path / "raw.sqlite")
    previous = persist_capture(journal, fixture)
    conflict = copy.deepcopy(fixture)
    conflict["available_at_ns"] += 1
    conflict["block"]["blockhash"] = address(12)
    with pytest.raises(NativeCaptureError, match="conflicted"):
        persist_capture(journal, conflict)
    assert len(journal.events(available_at_ns=conflict["available_at_ns"])) == 1
    with pytest.raises(ObservationError, match="barrier"):
        journal.reconstruct(
            source=SOURCE,
            partition=previous.partition,
            available_at_ns=conflict["available_at_ns"],
        )
    journal.close()
