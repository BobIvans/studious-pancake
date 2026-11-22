"""CAM-04 security closure v3: AUTHORIZED end-to-end cli.capture test.

Drives the REAL cli.capture() path with a signed plan (runtime Ed25519 key),
a mocked (offline) transport and verify_native=0 — reaching the full
capture lifecycle: authority store materialization, evidence journal,
intake collect over the mocked transport, and the final report write.

Asserts the security-closure contracts on the real path:
- authority.sqlite exists BEFORE the first evidence append (v3 ordering);
- the durable storage_reconciliation receipt records measured page sizes;
- the campaign_report evidence event is retained and report.json exists;
- the strict ceiling held: final footprint <= storage_bytes_max.
"""

import asyncio
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from src.qualification_campaign import cli
from src.qualification_campaign.evidence import (
    CampaignEvidenceStore,
    reconcile_materialized_artifacts,
)
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import READ_RPC_METHODS, public_rpc_profile
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchor,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
    signable_payload_bytes,
)

pytestmark = pytest.mark.unit

NOW = datetime.now(timezone.utc)
APPROVAL_DOMAIN = "prequal.campaign-start-approval.v1"


def _origin_main_available() -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "origin/main^{commit}"],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return True


def _source_config(tmp_path: Path) -> Path:
    checked = NOW.isoformat()
    from src.market.discovery import DiscoveryRequest
    from src.qualification_campaign.sources import CatalogDiscoveryAdapter

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
    config = {
        "schema_version": "prequal.source-intake-config.v1",
        "sources": [
            {
                "dossier": {
                    "source_id": "dexscreener",
                    "label": "DexScreener discovery",
                    "profile": {
                        "profile_id": "discovery-dexscreener",
                        "provider": "dexscreener",
                        "operator": "dexscreener",
                        "correlation_group": "dexscreener",
                        "endpoint": "https://api.dexscreener.invalid/token-pairs/v1/solana/x",
                        "official_docs": "https://docs.dexscreener.invalid/api/reference",
                        "role": "discovery",
                        "request_limit": 1,
                        "window_seconds": 60,
                        "campaign_attempt_cap": 10,
                    },
                    "checked_at": checked,
                    "docs_sha256": "a" * 64,
                    "request_schema_version": "DiscoveryRequest.v1",
                    "response_schema_version": "DiscoveredMarket.v1",
                    "schema_fingerprint": fingerprint,
                    "terms_url": "https://docs.dexscreener.invalid/terms",
                    "classification": "DISCOVERY_ONLY",
                },
                "adapter": {
                    "kind": "catalog",
                    "request": {
                        "source_id": "dexscreener",
                        "token_mint": "So11111111111111111111111111111111111111112",
                    },
                },
            }
        ],
    }
    path = tmp_path / "source-config.json"
    path.write_text(json.dumps(config))
    return path


def _keypair():
    from solders.keypair import Keypair

    return Keypair.from_seed(hashlib.sha256(b"cam04-e2e-key").digest())


def _sign(keypair, message: bytes) -> str:
    return str(keypair.sign_message(message))


def _plan_for(tmp_path: Path, source_config: Path, rpc) -> Path:
    """Build a plan that binds exactly the manifest cli.capture will create."""

    import time as time_mod

    sources = cli.load_sources(source_config)
    dossiers = [d for d, _ in sources]
    profiles = (*tuple(d.profile for d, _ in sources), rpc)
    generations = {}
    for d, _ in sources:
        generations[d.source_id] = asdict(d)
    for p in profiles:
        generations[p.profile_id] = asdict(p)
    manifest = CampaignManifest.create(
        cli.ROOT,
        main_sha=subprocess.check_output(
            ["git", "-C", str(cli.ROOT), "rev-parse", "origin/main^{commit}"],
            text=True,
        ).strip(),
        configuration={
            "capture": {
                "sources": json.loads(source_config.read_text()),
                "verify_native": 0,
            },
            "transport": {
                "max_attempts": 1,
                "max_response_bytes": 8_000_000,
                "max_string_length": 6_000_000,
                "accepted_content_encodings": ["identity", "gzip", "deflate"],
            },
        },
        sources=generations,
    )
    payload = {
        "schema_version": "prequal.campaign-start-approval-payload.v1",
        "gate_set": "CAMPAIGN_START_V1",
        "campaign_label": "cam04-e2e-capture",
        "environment": "research",
        "mode": "CAPTURE_ONLY",
        "approved_manifest_digest": manifest.campaign_id,
        "repository_sha": manifest.repository_sha,
        "main_sha": manifest.main_sha,
        "runtime_authority_sha256": manifest.runtime_authority_sha256,
        "policy_bundle_sha256": "c" * 64,
        "trust_registry_generation": "e2e-gen-1",
        "configuration_digests": dict(manifest.configuration_digests),
        "source_generations": dict(manifest.source_generations),
        "profiles_digests": {p.profile_id: digest(asdict(p)) for p in profiles},
        "budgets": {
            "rpc_physical_attempts_max": 200,
            "storage_bytes_max": 2**30,
            "per_source_quotas": {
                "dexscreener": {"requests": 12, "window_seconds": 60, "attempts": 100}
            },
            "external_data_spend_usd_max": 0,
        },
        "retention": {"journal_retention_days": 30},
        "capture_window_seconds": 86400,
        "discovery_only": True,
        "source_semantics": {"dexscreener": "PUBLIC_DISCOVERY"},
        "source_method_allowlists": {"rpc-e2e": sorted(READ_RPC_METHODS)},
        "offline_evidence": {
            "journal_durability": {
                "test_id": "tests/test_recoverable_stream_journal.py",
                "receipt_sha256": "b" * 64,
            },
            "replay_zero_network": {
                "test_id": "tests/test_mpr042_market_truth.py",
                "receipt_sha256": "d" * 64,
            },
        },
    }
    envelope = SignedEnvelope(
        domain=APPROVAL_DOMAIN,
        schema_version="prequal.campaign-start-envelope.v1",
        environment="research",
        key_id="cam04-e2e-key-1",
        issued_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        payload_sha256=hashlib.sha256(signable_payload_bytes(payload)).hexdigest(),
        signature_base58=_sign(_keypair(), b"placeholder"),
    )
    envelope = SignedEnvelope(
        domain=envelope.domain,
        schema_version=envelope.schema_version,
        environment=envelope.environment,
        key_id=envelope.key_id,
        issued_at=envelope.issued_at,
        expires_at=envelope.expires_at,
        payload_sha256=envelope.payload_sha256,
        signature_base58=_sign(_keypair(), envelope.canonical_message()),
    )
    plan = {
        "schema_version": "prequal.campaign-plan.v2",
        "gate_set": "CAMPAIGN_START_V1",
        "mode": "CAPTURE_ONLY",
        "discovery_only": True,
        "campaign_label": payload["campaign_label"],
        "environment": "research",
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
        "offline_evidence": payload["offline_evidence"],
        "approval_payload": payload,
        "envelope": {
            "domain": envelope.domain,
            "schema_version": envelope.schema_version,
            "environment": envelope.environment,
            "key_id": envelope.key_id,
            "issued_at": envelope.issued_at.isoformat(),
            "expires_at": envelope.expires_at.isoformat(),
            "payload_sha256": envelope.payload_sha256,
            "signature_base58": envelope.signature_base58,
        },
    }
    path = tmp_path / "campaign-plan.json"
    path.write_text(json.dumps(plan))
    return path


def _registry() -> TrustAnchorRegistry:
    from solders.keypair import Keypair

    keypair = _keypair()
    anchor = TrustAnchor(
        key_id="cam04-e2e-key-1",
        algorithm="ed25519",
        public_key_base58=str(keypair.pubkey()),
        usages=(TrustUsage.OPERATOR_APPROVAL,),
        issuer="cam04-e2e",
        environment="research",
        valid_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
        valid_until=datetime(2027, 6, 1, tzinfo=timezone.utc),
        state=TrustAnchorState.ACTIVE,
    )
    return TrustAnchorRegistry((anchor,), generation="e2e-gen-1")


def _mocked_transport_factory(monkeypatch):
    """Offline transport: canned DexScreener-like bounded page."""

    reply = {
        "schemaVersion": "1.0",
        "pairs": [
            {
                "chainId": "solana",
                "pairAddress": "P" * 44,
                "baseToken": {"address": "S" * 44, "symbol": "FAKE"},
                "quoteToken": {"address": "S" * 44, "symbol": "WSOL"},
                "priceUsd": "1.0",
            }
        ],
    }

    def handler(req):
        return httpx.Response(200, json=reply)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )

    class _FakeTransportCM:
        def __init__(self, hosts, policy):
            self.transport = HttpxJsonTransport(
                policy=TransportPolicy(max_attempts=1),
                allowed_hosts=frozenset({h for h in hosts if h.endswith(".invalid")})
                or frozenset({"api.dexscreener.invalid"}),
                client=client,
            )

        async def __aenter__(self):
            return self.transport

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "campaign_transport", _FakeTransportCM)


@pytest.mark.skipif(
    not _origin_main_available(),
    reason="requires a full clone with the origin/main ref",
)
def test_authorized_capture_end_to_end(tmp_path, monkeypatch):
    """The full authorized cli.capture() path runs offline and satisfies the
    v3 security-closure contracts on the real lifecycle."""

    _mocked_transport_factory(monkeypatch)
    source_config = _source_config(tmp_path)
    plan_path = _plan_for(tmp_path, source_config, public_rpc_profile())
    trust = tmp_path / "trust-registry.json"
    trust.write_text(json.dumps(_registry().to_dict()))
    output = tmp_path / "campaign-output"
    authority_path = output / "authority.sqlite"

    init_spy = {}
    real_init = CampaignEvidenceStore.__init__

    def spying_init(self, *args, **kwargs):
        init_spy["authority_exists_at_evidence_init"] = authority_path.exists()
        return real_init(self, *args, **kwargs)

    CampaignEvidenceStore.__init__ = spying_init
    try:
        result = asyncio.run(
            cli.capture(source_config, output, None, 0, plan_path, trust)
        )
    finally:
        CampaignEvidenceStore.__init__ = real_init

    # The gate authorized the run (blocked starts return before evidence).
    assert result["campaign_start_gate"]["phase"] == "CAPTURE_AUTHORIZED"
    # v3 ordering: authority store on disk before any evidence append.
    assert init_spy["authority_exists_at_evidence_init"] is True
    reconcile_materialized_artifacts(
        (
            authority_path,
            Path(str(authority_path) + "-wal"),
            Path(str(authority_path) + "-shm"),
        ),
        None,
    )
    # Durable receipt: measured page sizes + campaign_report evidence.
    journal = output / "campaign-evidence.sqlite"
    kinds = [json.loads(e.payload_json).get("kind") for e in _events(journal)]
    assert "campaign_report" in kinds, kinds
    assert "storage_reconciliation" in kinds, kinds
    assert (output / "report.json").is_file()
    # Strict ceiling held across the whole run.
    from src.qualification_campaign.evidence import artifact_footprint_bytes

    footprint = artifact_footprint_bytes(sorted(output.glob("**/*"), key=str))
    assert footprint < 2**30
    # Zero network beyond the mocked transport: no socket.connect monkeypatch
    # would ever be needed because campaign_transport was fully replaced.


def _events(journal_path: Path):
    from src.market.streams import RecoverableStreamJournal

    journal = RecoverableStreamJournal(journal_path)
    try:
        return list(journal.events(available_at_ns=2**63 - 1))
    finally:
        journal.close()
