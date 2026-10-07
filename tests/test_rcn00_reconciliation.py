"""Cross-generation seams must retain main safety and original QPR authority."""

from dataclasses import replace
import time

import pytest

from src.assets.resolution.evidence import EvidenceStore
from src.discovery.dynamic_universe.promotion import ExistingQPRReadiness
from src.durability import UnifiedLifecycleAuthority
from src.market.native_cpmm_capture import (
    GovernedNativeCpmmCollector,
    public_read_entitlements,
)
from src.market.streams import RecoverableStreamJournal
from src.providers.raydium_cpmm_native import NativeCaptureError
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import CampaignManifest
from src.qualification_campaign.profiles import public_rpc_profile
from src.routing.transport import HttpxJsonTransport


def test_dynamic_handoff_delegates_to_restored_qpr_without_manufacturing_pass(tmp_path):
    manifest = CampaignManifest(
        "a" * 40, "b" * 40, "c" * 64, (("capture", "d" * 64),), (("rpc", "e" * 64),)
    )
    journal = RecoverableStreamJournal(tmp_path / "campaign.sqlite")
    try:
        evidence = CampaignEvidenceStore(journal, manifest)
        store = EvidenceStore(tmp_path / "dynamic")
        readiness = ExistingQPRReadiness(evidence, store)()
        assert readiness.generation == manifest.campaign_id
        assert readiness.verdict == "BLOCKED"
        payload = store.replay(readiness.handoff_ref)["payload"]
        assert payload["stop_before"] == "QPR-04"
        assert payload["production_promotion"] is False
        assert payload["manifest"]["safety"]["signer_reachable"] is False
        assert payload["manifest"]["safety"]["sender_reachable"] is False
    finally:
        journal.close()


def test_endpoint_override_remains_smoke_only_and_explicit_profile_mismatch_blocks(
    tmp_path,
):
    endpoint = "https://reviewed-read.example"
    authority = UnifiedLifecycleAuthority(
        tmp_path / "authority.sqlite",
        release_digest="a" * 64,
        policy_bundle_hash="b" * 64,
    )
    try:
        governance = ProviderGovernance(
            public_read_entitlements(
                expires_at_epoch_seconds=int(time.time()) + 600, rpc_url=endpoint
            ),
            store=authority,
        )
        transport = HttpxJsonTransport(
            allowed_hosts=frozenset({"reviewed-read.example"})
        )
        collector = GovernedNativeCpmmCollector(governance, transport)
        assert collector.profile.endpoint == endpoint
        assert collector.profile.smoke_only
        with pytest.raises(NativeCaptureError, match="differs"):
            GovernedNativeCpmmCollector(
                governance,
                transport,
                profile=replace(public_rpc_profile(), smoke_only=False),
            )
        assert (
            "sendTransaction"
            not in governance.entitlement(
                collector.profile.profile_id
            ).allowed_rpc_methods
        )
    finally:
        authority.close()
