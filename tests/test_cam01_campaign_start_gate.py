"""CAM-01/CAM-02: executable CAMPAIGN_START_V1 gate, fail-closed before transport."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from src.authorization_replay_pr201 import SQLiteAuthorizationReplayLedger
from src.qualification_campaign.campaign_start_gate import (
    APPROVAL_DOMAIN,
    GatePhase,
    evaluate_campaign_start_gate,
    external_envelope_consumption_key,
    load_campaign_plan,
    load_trust_registry,
)
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import (
    READ_RPC_METHODS,
    ProviderProfile,
)
from src.qualification_campaign.sources import CatalogDiscoveryAdapter, SourceDossier
from src.qualification_campaign.cli import blocked_start_report
from src.market.discovery import DiscoveryRequest
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchor,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
    signable_payload_bytes,
)

pytestmark = pytest.mark.unit

Environment = "research"
# 2026-11-22T06:00:00Z — inside the 2026-11-22 docs TTL and envelope validity.
NOW_NS = 1_795_327_200_000_000_000


def _ed25519_keypair():
    from solders.keypair import Keypair

    seed = hashlib.sha256(b"campaign-start-gate-test-key").digest()
    return Keypair.from_seed(seed)


def _sign_bytes(keypair, message: bytes) -> str:
    return str(keypair.sign_message(message))


def _manifest() -> CampaignManifest:
    return CampaignManifest(
        repository_sha="1" * 40,
        main_sha="2" * 40,
        runtime_authority_sha256=digest({"runtime": "authority"}),
        configuration_digests=(("capture", digest({"verify_native": 1})),),
        source_generations=(("dexscreener", digest({"dossier": "v1"})),),
    )


def _dossier() -> SourceDossier:
    profile = ProviderProfile(
        profile_id="discovery-dexscreener",
        provider="dexscreener",
        operator="dexscreener",
        correlation_group="dexscreener",
        endpoint="https://api.dexscreener.invalid/token-pairs/v1/solana/x",
        official_docs="https://docs.dexscreener.invalid/api/reference",
        role="discovery",
        request_limit=1,
        window_seconds=60,
        campaign_attempt_cap=10,
    )
    adapter = CatalogDiscoveryAdapter(
        DiscoveryRequest(
            source_id="dexscreener",
            token_mint="So11111111111111111111111111111111111111112",
        )
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            adapter.schema_contract(), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return SourceDossier(
        source_id="dexscreener",
        label="DexScreener discovery",
        profile=profile,
        checked_at="2026-11-22T00:00:00+00:00",
        docs_sha256="a" * 64,
        request_schema_version="DiscoveryRequest.v1",
        response_schema_version="DiscoveredMarket.v1",
        schema_fingerprint=fingerprint,
        terms_url="https://docs.dexscreener.invalid/terms",
        renewal_ttl_seconds=86400,
    )


def _rpc_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="rpc-primary",
        provider="rpc-primary",
        operator="operator-a",
        correlation_group="group-a",
        endpoint="https://primary.invalid/",
        official_docs="https://docs.invalid/rpc",
        request_limit=12,
        window_seconds=60,
        campaign_attempt_cap=50,
    )


def _plan_for(manifest: CampaignManifest, dossier: SourceDossier, rpc, keypair):
    from dataclasses import asdict

    adapter = CatalogDiscoveryAdapter(
        DiscoveryRequest(
            source_id="dexscreener",
            token_mint="So11111111111111111111111111111111111111112",
        )
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            adapter.schema_contract(), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    dossier = (
        dossier
        if dossier.schema_fingerprint == fingerprint
        else SourceDossier(
            **{
                **dossier.__dict__,
                "schema_fingerprint": fingerprint,
            }
        )
    )
    payload = {
        "schema_version": "prequal.campaign-start-approval-payload.v1",
        "gate_set": "CAMPAIGN_START_V1",
        "campaign_label": "20261121-market-capture-001",
        "environment": Environment,
        "mode": "CAPTURE_ONLY",
        "approved_manifest_digest": manifest.campaign_id,
        "repository_sha": manifest.repository_sha,
        "main_sha": manifest.main_sha,
        "runtime_authority_sha256": manifest.runtime_authority_sha256,
        "policy_bundle_sha256": "c" * 64,
        "trust_registry_generation": "test-gen-1",
        "configuration_digests": dict(manifest.configuration_digests),
        "source_generations": dict(manifest.source_generations),
        "profiles_digests": {
            p.profile_id: digest(asdict(p)) for p in (rpc, dossier.profile)
        },
        "budgets": {
            "rpc_physical_attempts_max": 200,
            "storage_bytes_max": 104857600,
            "per_source_quotas": {
                "dexscreener": {"requests": 12, "window_seconds": 60, "attempts": 100}
            },
            "external_data_spend_usd_max": 0,
        },
        "retention": {"journal_retention_days": 30},
        "capture_window_seconds": 86400,
        "discovery_only": True,
        "source_semantics": {"dexscreener": "PUBLIC_DISCOVERY"},
        "source_method_allowlists": {"rpc-primary": sorted(READ_RPC_METHODS)},
    }
    from datetime import datetime, timezone as tz

    envelope = SignedEnvelope(
        domain=APPROVAL_DOMAIN,
        schema_version="prequal.campaign-start-envelope.v1",
        environment=Environment,
        key_id="campaign-test-key-1",
        issued_at=datetime(2026, 11, 1, tzinfo=tz.utc),
        expires_at=datetime(2027, 1, 1, tzinfo=tz.utc),
        payload_sha256=hashlib.sha256(signable_payload_bytes(payload)).hexdigest(),
        signature_base58=_sign_bytes(keypair, b"placeholder"),
    )
    envelope = SignedEnvelope(
        domain=envelope.domain,
        schema_version=envelope.schema_version,
        environment=envelope.environment,
        key_id=envelope.key_id,
        issued_at=envelope.issued_at,
        expires_at=envelope.expires_at,
        payload_sha256=envelope.payload_sha256,
        signature_base58=_sign_bytes(keypair, envelope.canonical_message()),
    )
    envelope_dict = {
        "domain": envelope.domain,
        "schema_version": envelope.schema_version,
        "environment": envelope.environment,
        "key_id": envelope.key_id,
        "issued_at": envelope.issued_at.isoformat(),
        "expires_at": envelope.expires_at.isoformat(),
        "payload_sha256": envelope.payload_sha256,
        "signature_base58": envelope.signature_base58,
    }
    plan = {
        "schema_version": "prequal.campaign-plan.v2",
        "gate_set": "CAMPAIGN_START_V1",
        "mode": "CAPTURE_ONLY",
        "discovery_only": True,
        "campaign_label": payload["campaign_label"],
        "environment": Environment,
        "approved_manifest_digest": manifest.campaign_id,
        "repository_sha": manifest.repository_sha,
        "main_sha": manifest.main_sha,
        "runtime_authority_sha256": manifest.runtime_authority_sha256,
        "policy_bundle_sha256": payload["policy_bundle_sha256"],
        "trust_registry_generation": payload["trust_registry_generation"],
        "configuration_digests": payload["configuration_digests"],
        "source_generations": payload["source_generations"],
        "profiles_digests": payload["profiles_digests"],
        "budgets": payload["budgets"],
        "retention": payload["retention"],
        "capture_window_seconds": 86400,
        "source_semantics": payload["source_semantics"],
        "source_method_allowlists": payload["source_method_allowlists"],
        "offline_evidence": {
            "journal_durability": {
                "test_id": "tests/test_qpr02_data_plane.py",
                "receipt_sha256": "b" * 64,
            },
            "replay_zero_network": {
                "test_id": "tests/test_qpr03_source_intake.py",
                "receipt_sha256": "d" * 64,
            },
        },
        "approval_payload": payload,
        "envelope": envelope_dict,
    }
    return dossier, payload, plan


def _consistent(keypair):
    """Return (manifest, dossier, plan) whose generation digests all bind."""

    dossier = _dossier()
    manifest = CampaignManifest(
        repository_sha="1" * 40,
        main_sha="2" * 40,
        runtime_authority_sha256=digest({"runtime": "authority"}),
        configuration_digests=(("capture", digest({"verify_native": 1})),),
        source_generations=(("dexscreener", dossier.generation),),
    )
    _d, _payload, plan = _plan_for(manifest, dossier, _rpc_profile(), keypair)
    return manifest, dossier, plan


def _registry(keypair) -> TrustAnchorRegistry:
    from datetime import datetime, timezone

    anchor = TrustAnchor(
        key_id="campaign-test-key-1",
        algorithm="ed25519",
        public_key_base58=str(keypair.pubkey()),
        usages=(TrustUsage.OPERATOR_APPROVAL,),
        issuer="campaign-test",
        environment=Environment,
        valid_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
        valid_until=datetime(2027, 6, 1, tzinfo=timezone.utc),
        state=TrustAnchorState.ACTIVE,
    )
    return TrustAnchorRegistry((anchor,), generation="test-gen-1")


def _evaluate(tmp_path, manifest, dossier, plan, keypair, *, with_registry=True):
    ledger = SQLiteAuthorizationReplayLedger(tmp_path / "approval-ledger.sqlite")
    loaded = load_plan_from_raw(plan)
    return evaluate_campaign_start_gate(
        manifest=manifest,
        plan=loaded,
        dossiers=[dossier],
        adapters=[
            CatalogDiscoveryAdapter(
                DiscoveryRequest(
                    source_id="dexscreener",
                    token_mint="So11111111111111111111111111111111111111112",
                )
            )
        ],
        profiles=[rpc_profile_for(plan)],
        registry=_registry(keypair) if with_registry else None,
        ledger=ledger,
        now_ns=NOW_NS,
    )


def load_plan_from_raw(plan):
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        path = handle.name
    try:
        return load_campaign_plan(Path(path))
    finally:
        os.unlink(path)


def rpc_profile_for(plan):
    return _rpc_profile()


def test_positive_path_authorizes_capture_only(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    # Manifest generation digests must bind the runtime dossier/profile bytes.
    manifest = CampaignManifest(
        repository_sha=manifest.repository_sha,
        main_sha=manifest.main_sha,
        runtime_authority_sha256=manifest.runtime_authority_sha256,
        configuration_digests=manifest.configuration_digests,
        source_generations=(("dexscreener", dossier.generation),),
    )
    dossier, _payload, plan = _plan_for(manifest, dossier, _rpc_profile(), keypair)
    decision = _evaluate(tmp_path, manifest, dossier, plan, keypair)
    assert decision.phase is GatePhase.CAPTURE_AUTHORIZED
    assert not decision.blockers
    assert decision.approval_receipt is not None
    verdicts = {v.gate_id: v.status for v in decision.verdicts}
    assert verdicts["CS-06"] == "CS06_PENDING_CAPTURE"
    assert all(status == "PASS" for g, status in verdicts.items() if g != "CS-06")
    assert decision.to_dict()["physical_network_attempts"] == 0


def test_missing_trust_anchor_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest, dossier, plan = _consistent(keypair)
    decision = _evaluate(
        tmp_path, manifest, dossier, plan, keypair, with_registry=False
    )
    assert decision.phase is GatePhase.PREFLIGHT_PASS
    assert "OPERATOR_TRUST_ANCHOR_MISSING" in decision.blockers
    assert decision.approval_receipt is None


def test_wrong_manifest_digest_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    tampered = CampaignManifest(
        repository_sha=manifest.repository_sha,
        main_sha=manifest.main_sha,
        runtime_authority_sha256=manifest.runtime_authority_sha256,
        configuration_digests=manifest.configuration_digests,
        source_generations=(("dexscreener", digest({"other": "generation"})),),
    )
    decision = _evaluate(tmp_path, tampered, dossier, plan, keypair)
    assert decision.phase is GatePhase.BLOCKED
    assert "APPROVAL_MANIFEST_DIGEST_MISMATCH" in decision.blockers


def test_tampered_envelope_signature_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest, dossier, plan = _consistent(keypair)
    plan = {
        **plan,
        "envelope": {
            **plan["envelope"],
            "signature_base58": _sign_bytes(_ed25519_keypair(), b"unrelated"),
        },
    }
    decision = _evaluate(tmp_path, manifest, dossier, plan, keypair)
    assert decision.phase is GatePhase.PREFLIGHT_PASS
    assert "CRYPTOGRAPHIC_SIGNATURE_INVALID" in decision.blockers


def test_stale_approved_release_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    stale = CampaignManifest(
        repository_sha=manifest.repository_sha,
        main_sha="3" * 40,
        runtime_authority_sha256=manifest.runtime_authority_sha256,
        configuration_digests=manifest.configuration_digests,
        source_generations=manifest.source_generations,
    )
    decision = _evaluate(tmp_path, stale, dossier, plan, keypair)
    assert decision.phase is GatePhase.BLOCKED
    assert "APPROVED_MAIN_SHA_STALE" in decision.blockers


def test_same_envelope_reuse_is_idempotent_and_replay_visible(tmp_path):
    keypair = _ed25519_keypair()
    manifest, dossier, plan = _consistent(keypair)
    first = _evaluate(tmp_path, manifest, dossier, plan, keypair)
    assert first.authorized and first.approval_receipt["replayed"] is False
    # Presenting the SAME signed envelope again under the same durable
    # ledger returns the same idempotent receipt without a second
    # reservation; the receipt marks it as a replay.
    second = _evaluate(tmp_path, manifest, dossier, plan, keypair)
    assert second.authorized
    assert second.approval_receipt["replayed"] is True
    assert (
        second.approval_receipt["result_sha256"]
        == first.approval_receipt["result_sha256"]
    )


def test_same_envelope_with_different_manifest_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest, dossier, plan = _consistent(keypair)
    assert _evaluate(tmp_path, manifest, dossier, plan, keypair).authorized
    # The envelope's payload binds approved_manifest_digest; presenting it
    # for a different runtime manifest cannot pass CS-01.
    other = CampaignManifest(
        repository_sha=manifest.repository_sha,
        main_sha=manifest.main_sha,
        runtime_authority_sha256=digest({"runtime": "authority", "v": 2}),
        configuration_digests=manifest.configuration_digests,
        source_generations=manifest.source_generations,
    )
    # Re-present the ORIGINAL envelope (bound to the original manifest
    # digest) against a different runtime manifest.
    decision2 = _evaluate(tmp_path, other, dossier, plan, keypair)
    assert not decision2.authorized
    assert "APPROVAL_MANIFEST_DIGEST_MISMATCH" in decision2.blockers


def test_unbounded_budget_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    plan = {
        **plan,
        "budgets": {
            **plan["budgets"],
            "rpc_physical_attempts_max": 0,
        },
    }
    with pytest.raises(ValueError):
        load_plan_from_raw(plan)


def test_paid_spend_forbidden(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    plan = {
        **plan,
        "budgets": {**plan["budgets"], "external_data_spend_usd_max": 10},
        "approval_payload": {
            **plan["approval_payload"],
            "budgets": {**plan["budgets"], "external_data_spend_usd_max": 10},
        },
    }
    with pytest.raises(ValueError):
        load_plan_from_raw(plan)


def test_source_docs_stale_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    stale_dossier = SourceDossier(
        **{
            **_dossier().__dict__,
            "checked_at": "2026-10-06T00:00:00+00:00",
        }
    )
    manifest = CampaignManifest(
        repository_sha=manifest.repository_sha,
        main_sha=manifest.main_sha,
        runtime_authority_sha256=manifest.runtime_authority_sha256,
        configuration_digests=manifest.configuration_digests,
        source_generations=(("dexscreener", stale_dossier.generation),),
    )
    dossier, _payload, plan = _plan_for(
        manifest, stale_dossier, _rpc_profile(), keypair
    )
    decision = _evaluate(tmp_path, manifest, dossier, plan, keypair)
    assert decision.phase is GatePhase.BLOCKED
    assert "SOURCE_DOCS_STALE:dexscreener" in decision.blockers


def test_schema_fingerprint_drift_blocks(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier = SourceDossier(
        **{
            **_dossier().__dict__,
            "schema_fingerprint": "f" * 64,
        }
    )
    manifest = CampaignManifest(
        repository_sha=manifest.repository_sha,
        main_sha=manifest.main_sha,
        runtime_authority_sha256=manifest.runtime_authority_sha256,
        configuration_digests=manifest.configuration_digests,
        source_generations=(("dexscreener", dossier.generation),),
    )
    _d2, _payload, plan = _plan_for(manifest, dossier, _rpc_profile(), keypair)
    decision = _evaluate(tmp_path, manifest, dossier, plan, keypair)
    assert decision.phase is GatePhase.BLOCKED
    assert "SCHEMA_FINGERPRINT_MISMATCH:dexscreener" in decision.blockers


def test_blocked_start_report_is_typed_and_zero_network(tmp_path):
    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    decision = _evaluate(
        tmp_path, manifest, dossier, plan, keypair, with_registry=False
    )
    report = blocked_start_report(decision)
    assert report["campaign_readiness"]["status"] == "BLOCKED"
    assert report["physical_network_attempts"] == 0
    assert report["qualification_verdict"] == "BLOCKED"
    assert report["production_promotion"] is False


def test_consumption_key_is_stable_and_covers_signature(tmp_path):
    from datetime import datetime

    keypair = _ed25519_keypair()
    manifest = _manifest()
    dossier, _payload, plan = _plan_for(manifest, _dossier(), _rpc_profile(), keypair)
    envelope_fields = dict(plan["envelope"])

    envelope = SignedEnvelope(
        domain=envelope_fields["domain"],
        schema_version=envelope_fields["schema_version"],
        environment=envelope_fields["environment"],
        key_id=envelope_fields["key_id"],
        issued_at=datetime.fromisoformat(envelope_fields["issued_at"]),
        expires_at=datetime.fromisoformat(envelope_fields["expires_at"]),
        payload_sha256=envelope_fields["payload_sha256"],
        signature_base58=envelope_fields["signature_base58"],
    )
    key1 = external_envelope_consumption_key(envelope, envelope.payload_sha256)
    key2 = external_envelope_consumption_key(envelope, envelope.payload_sha256)
    assert key1 == key2
    altered = SignedEnvelope(
        **{
            **envelope_fields,
            "signature_base58": _sign_bytes(keypair, b"other"),
            "issued_at": datetime.fromisoformat(envelope_fields["issued_at"]),
            "expires_at": datetime.fromisoformat(envelope_fields["expires_at"]),
        }
    )
    assert external_envelope_consumption_key(altered, altered.payload_sha256) != key1


def test_load_trust_registry_rejects_garbage(tmp_path):
    bad = tmp_path / "registry.json"
    bad.write_text(json.dumps({"generation": "g", "anchors": []}))
    with pytest.raises(ValueError):
        load_trust_registry(bad)
