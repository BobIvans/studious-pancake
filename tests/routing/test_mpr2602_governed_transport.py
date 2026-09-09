from dataclasses import replace
import asyncio
import json
from pathlib import Path
import httpx
import pytest
from src.provider_governance import (
    ProviderGovernance,
    ProviderEntitlement,
    ProviderOperation,
    ProviderGovernanceError,
)
from src.routing.registry import ProviderRegistry, DiscoveryPlane
from src.routing.clients import JupiterRouterAdapter
from src.routing.models import QuoteRequest
from src.routing.transport import HttpxJsonTransport, TransportPolicy


def manifest():
    return ProviderEntitlement(
        provider_id="jupiter_router",
        generation="reviewed-g1",
        allowed_operations=frozenset({ProviderOperation.DISCOVERY}),
        window_seconds=60,
        request_limit=10,
        cost_unit_limit=10,
        spend_limit_micros=0,
        max_concurrency=1,
        source_ref="offline-reviewed-fixture",
        allowed_endpoints=(JupiterRouterAdapter.endpoint,),
        allowed_http_methods=frozenset({"GET"}),
        allowed_query_parameters=frozenset(
            {"inputMint", "outputMint", "amount", "taker", "slippageBps"}
        ),
        credential_ref="test-jupiter",
        credential_generation="credential-g1",
    )


def quote_request():
    return QuoteRequest(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        amount_base_units=1000000,
        user_wallet="11111111111111111111111111111111",
        slippage_bps=50,
        input_decimals=9,
        output_decimals=6,
    )


@pytest.mark.asyncio
async def test_missing_reviewed_manifest_startup_safe_transport_zero():
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: calls.append(r)), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"api.jup.ag"})
        )
        adapter = JupiterRouterAdapter(
            api_key="synthetic-test-key", transport=transport
        )
        registry = ProviderRegistry((adapter,))
        assert registry.startup_report()[0]["state"] == "disabled_missing_entitlement"
        batch = await DiscoveryPlane(registry).discover(quote_request())
        assert "manifest_missing" in batch.failures[0].detail
        assert calls == []


def test_env_cannot_mint_or_increase_entitlements():
    adapter = JupiterRouterAdapter(api_key="synthetic-test-key")
    with pytest.raises(ProviderGovernanceError, match="overrides"):
        ProviderGovernance.from_adapters(
            (adapter,),
            {"PROVIDER_JUPITER_ROUTER_REQUEST_LIMIT": "999999"},
            reviewed_entitlements={"jupiter_router": manifest()},
        )


@pytest.mark.asyncio
async def test_actual_discovery_transport_retries_charge_three_attempts():
    calls = []
    payload = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/routing/pr030_provider_responses.json"
        ).read_text()
    )["jupiter"]

    async def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client,
            allowed_hosts=frozenset({"api.jup.ag"}),
            policy=TransportPolicy(max_attempts=3, backoff_base_seconds=0),
        )
        adapter = JupiterRouterAdapter(
            api_key="synthetic-test-key", transport=transport
        )
        governance = ProviderGovernance.from_adapters(
            (adapter,), reviewed_entitlements={"jupiter_router": manifest()}
        )
        registry = ProviderRegistry(
            (adapter,),
            governance=governance,
            credential_bindings={"jupiter_router": ("test-jupiter", "credential-g1")},
        )
        batch = await DiscoveryPlane(registry).discover(quote_request())
        assert not batch.failures
        assert len(batch.quotes) == 1
        state = await governance.authority.snapshot("jupiter_router")
        assert state["committed_requests"] == 3
        assert state["active_leases"] == 0
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_actual_retry_after_rotation_has_no_second_effect():
    calls = []
    governance = None

    async def handler(request):
        calls.append(request)
        governance.authority.replace_entitlement(
            replace(manifest(), generation="reviewed-g2")
        )
        return httpx.Response(503, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client,
            allowed_hosts=frozenset({"api.jup.ag"}),
            policy=TransportPolicy(max_attempts=3, backoff_base_seconds=0),
        )
        adapter = JupiterRouterAdapter(
            api_key="synthetic-test-key", transport=transport
        )
        governance = ProviderGovernance.from_adapters(
            (adapter,), reviewed_entitlements={"jupiter_router": manifest()}
        )
        batch = await DiscoveryPlane(
            ProviderRegistry(
                (adapter,),
                governance=governance,
                credential_bindings={
                    "jupiter_router": ("test-jupiter", "credential-g1")
                },
            )
        ).discover(quote_request())
        assert "generation_mismatch" in batch.failures[0].detail
        assert len(calls) == 1
        assert (await governance.authority.snapshot("jupiter_router"))[
            "committed_requests"
        ] == 1


@pytest.mark.asyncio
async def test_late_callback_uses_original_generation():
    governance = ProviderGovernance({"jupiter_router": manifest()})
    await governance.record_failure("jupiter_router", "auth", generation="reviewed-g1")
    governance.authority.replace_entitlement(
        replace(manifest(), generation="reviewed-g2")
    )
    await governance.record_success(
        "jupiter_router", ProviderOperation.HEALTH_PROBE, generation="reviewed-g1"
    )
    state = await governance.snapshot("jupiter_router")
    assert state["dependency_mode"] == "disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    ["endpoint", "http_method", "credential", "missing_scope", "query_secret"],
)
async def test_physical_scope_mismatch_has_zero_effects(mismatch, caplog):
    from src.provider_governance import AdmissionRequest, ProviderAdmissionError

    calls = []
    configured = manifest()
    endpoint = JupiterRouterAdapter.endpoint
    method = "GET"
    credentials = ("test-jupiter", "credential-g1")
    params = None
    if mismatch == "endpoint":
        endpoint += "/unreviewed"
    if mismatch == "http_method":
        method = "POST"
    if mismatch == "credential":
        credentials = ("test-jupiter", "credential-g2")
    if mismatch == "missing_scope":
        configured = replace(configured, allowed_endpoints=())
    if mismatch == "query_secret":
        configured = replace(
            configured, allowed_query_parameters=frozenset({"api-key"})
        )
        params = {"api-key": "never-log-this-secret"}
    governance = ProviderGovernance({"jupiter_router": configured})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: calls.append(r)), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"api.jup.ag"})
        )
        governance.bind_transport(transport)
        admission = AdmissionRequest(
            work_id="negative",
            provider_id="jupiter_router",
            operation=ProviderOperation.DISCOVERY,
            request_fingerprint="logical",
            fairness_key="test",
            deadline_at=governance.clock() + 1,
            expected_generation=configured.generation,
        )
        with pytest.raises(ProviderAdmissionError, match="physical_scope_denied"):
            await governance.execute_physical(
                admission,
                lambda: transport.request(method, endpoint, params=params),
                credential_ref=credentials[0],
                credential_generation=credentials[1],
            )
    assert calls == []
    assert "never-log-this-secret" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rpc_method,reviewed,permitted",
    [
        ("getSlot", True, True),
        ("simulateTransaction", True, True),
        ("sendTransaction", True, False),
        ("sendRawTransaction", True, False),
        ("requestAirdrop", True, False),
        ("getTransaction", False, False),
    ],
)
async def test_sender_free_rpc_subset(rpc_method, reviewed, permitted):
    from src.provider_governance import AdmissionRequest, ProviderAdmissionError

    calls = []
    rpc = replace(
        manifest(),
        allowed_endpoints=("https://rpc.example/",),
        allowed_http_methods=frozenset({"POST"}),
        allowed_rpc_methods=frozenset({rpc_method if reviewed else "getSlot"}),
    )
    governance = ProviderGovernance({"jupiter_router": rpc})

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"rpc.example"})
        )
        governance.bind_transport(transport)
        admission = AdmissionRequest(
            work_id="rpc",
            provider_id="jupiter_router",
            operation=ProviderOperation.DISCOVERY,
            request_fingerprint="logical",
            fairness_key="test",
            deadline_at=governance.clock() + 1,
            expected_generation=rpc.generation,
        )

        async def operation():
            return await transport.request(
                "POST",
                "https://rpc.example/",
                json_body={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": rpc_method,
                    "params": [],
                },
            )

        if permitted:
            await governance.execute_physical(
                admission,
                operation,
                credential_ref="test-jupiter",
                credential_generation="credential-g1",
            )
        else:
            with pytest.raises(ProviderAdmissionError):
                await governance.execute_physical(
                    admission,
                    operation,
                    credential_ref="test-jupiter",
                    credential_generation="credential-g1",
                )
    assert len(calls) == int(permitted)


@pytest.mark.asyncio
async def test_repeated_cancel_retains_physical_cleanup_for_supervisor():
    from src.provider_governance import AdmissionRequest

    entered = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    governance = ProviderGovernance({"jupiter_router": manifest()})
    original = governance.authority.mark_unknown

    async def delayed_unknown(lease):
        cleanup_entered.set()
        await release_cleanup.wait()
        await original(lease)

    governance.authority.mark_unknown = delayed_unknown

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"api.jup.ag"})
        )
        governance.bind_transport(transport)
        admission = AdmissionRequest(
            work_id="cancel",
            provider_id="jupiter_router",
            operation=ProviderOperation.DISCOVERY,
            request_fingerprint="logical",
            fairness_key="test",
            deadline_at=governance.clock() + 10,
            expected_generation=manifest().generation,
        )
        task = asyncio.create_task(
            governance.execute_physical(
                admission,
                lambda: transport.request("GET", JupiterRouterAdapter.endpoint),
                credential_ref="test-jupiter",
                credential_generation="credential-g1",
            )
        )
        await entered.wait()
        task.cancel()
        await cleanup_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not await governance.scheduler.drain_cleanup(0)
        release_cleanup.set()
        assert await governance.scheduler.drain_cleanup(1)
        state = await governance.authority.snapshot("jupiter_router")
        assert state["active_leases"] == 1
        assert state["committed_requests"] == 0
