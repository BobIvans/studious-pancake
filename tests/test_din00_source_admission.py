"""DIN-00 uses existing QPR admission, journal and operator budgets."""

import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import (
    ProviderGovernance,
    AdmissionRequest,
    ProviderOperation,
    ProviderAdmissionError,
)
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.sources import (
    SourceIntakePlane,
    source_admission_status,
)
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from tests.test_qpr03_source_intake import dossier, NewSourceAdapter


@pytest.mark.parametrize("value", [None, "", "Bearer ", "Basic invalid"])
def test_missing_or_invalid_binding_is_replayable_and_has_zero_physical_calls(
    tmp_path, value
):
    async def run():
        d = dossier()
        d = replace(
            d,
            profile=replace(
                d.profile,
                auth_header="Authorization",
                credential_ref="REVIEWED_API_KEY",
            ),
        )
        calls = []

        async def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"rows": []})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as client:
            transport = HttpxJsonTransport(
                client=client,
                allowed_hosts=frozenset({"new.test"}),
                policy=TransportPolicy(max_attempts=1),
            )
            gov = ProviderGovernance(
                {
                    d.profile.profile_id: d.profile.entitlement(
                        expires_at_epoch_seconds=2000
                    )
                },
                clock=lambda: 1002,
                wall_clock=lambda: 1002,
            )
            m = CampaignManifest(
                "a" * 40,
                "b" * 40,
                "c" * 64,
                (("capture", "d" * 64),),
                (
                    (d.source_id, d.generation),
                    (d.profile.profile_id, d.profile.generation),
                ),
            )
            journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
            try:
                evidence = CampaignEvidenceStore(
                    journal, m, wall_ns=lambda: 1002 * 10**9
                )
                headers = (
                    {}
                    if value is None
                    else {d.profile.profile_id: {"Authorization": value}}
                )
                plane = SourceIntakePlane(
                    load_market_source_catalog().with_intake(d.catalog_entry()),
                    gov,
                    transport,
                    evidence,
                    wall_ns=lambda: 1002 * 10**9,
                    credential_headers=headers,
                )
                records, receipt = await plane.collect(d, NewSourceAdapter())
                assert not records and not calls
                assert "CREDENTIAL" in receipt["failure_reason"]
                assert (
                    next(
                        e
                        for e in evidence.replay()
                        if e["kind"] == "source_observation"
                    )["failure_reason"]
                    == receipt["failure_reason"]
                )
                status = source_admission_status(d, headers, now_ns=1002 * 10**9)
                assert (
                    status["status"] == "BLOCKED"
                    and status["credential_ref"] == "REVIEWED_API_KEY"
                )
                assert "Basic invalid" not in json.dumps(status)
            finally:
                journal.close()

    asyncio.run(run())


def test_provider_aliases_share_one_real_operator_physical_budget():
    async def run():
        a = ProviderProfile(
            "a",
            "provider-alias-a",
            "one-operator",
            "same-dependency",
            "https://rpc.test",
            "https://docs.test",
            request_limit=1,
        )
        b = replace(
            a,
            profile_id="b",
            provider="provider-alias-b",
            credential_ref="second-key-ref",
        )
        assert (
            a.entitlement(expires_at_epoch_seconds=2000).quota_pool_ref
            == b.entitlement(expires_at_epoch_seconds=2000).quota_pool_ref
        )
        calls = []

        async def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"result": 1})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as client:
            transport = HttpxJsonTransport(
                client=client,
                allowed_hosts=frozenset({"rpc.test"}),
                policy=TransportPolicy(max_attempts=1),
            )
            gov = ProviderGovernance(
                {
                    p.profile_id: p.entitlement(expires_at_epoch_seconds=2000)
                    for p in (a, b)
                },
                clock=lambda: 1002,
                wall_clock=lambda: 1002,
            )
            gov.bind_transport(transport)

            async def call(p):
                return await gov.execute_physical(
                    AdmissionRequest(
                        work_id=p.profile_id,
                        provider_id=p.profile_id,
                        operation=ProviderOperation.BACKFILL,
                        request_fingerprint=digest(p.profile_id),
                        fairness_key="din00",
                        deadline_at=1010,
                        expected_generation=p.generation,
                    ),
                    lambda: transport.request(
                        "POST",
                        p.endpoint,
                        json_body={"jsonrpc": "2.0", "method": "getSlot"},
                    ),
                    credential_ref=p.credential_ref,
                    credential_generation=p.credential_generation,
                )

            await call(a)
            with pytest.raises(ProviderAdmissionError):
                await call(b)
            assert len(calls) == 1

    asyncio.run(run())
