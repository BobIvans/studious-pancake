"""CAM-01: capture() must fail closed BEFORE any transport object exists."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.qualification_campaign import cli

pytestmark = pytest.mark.unit


def _fresh_source_config(tmp_path: Path) -> Path:
    checked = datetime.now(timezone.utc).isoformat()
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
                    "schema_fingerprint": "b" * 64,
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


def _unapproved_plan(tmp_path: Path) -> Path:
    plan = {
        "schema_version": "prequal.campaign-plan.v2",
        "gate_set": "CAMPAIGN_START_V1",
        "mode": "CAPTURE_ONLY",
        "discovery_only": True,
        "campaign_label": "20261121-market-capture-001",
        "environment": "research",
        "approved_manifest_digest": "0" * 64,
        "repository_sha": "1" * 40,
        "main_sha": "2" * 40,
        "runtime_authority_sha256": "0" * 64,
        "policy_bundle_sha256": "0" * 64,
        "trust_registry_generation": "test-gen-1",
        "configuration_digests": {"capture": "0" * 64},
        "source_generations": {"dexscreener": "0" * 64},
        "profiles_digests": {"rpc-primary": "0" * 64},
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
        "source_semantics": {"dexscreener": "PUBLIC_DISCOVERY"},
        "source_method_allowlists": {"rpc-primary": ["getSlot"]},
        "offline_evidence": {
            "journal_durability": {"test_id": "t", "receipt_sha256": "c" * 64},
            "replay_zero_network": {"test_id": "t", "receipt_sha256": "d" * 64},
        },
        "approval_payload": {"placeholder": True},
        "envelope": {"placeholder": True},
    }
    path = tmp_path / "campaign-plan.json"
    path.write_text(json.dumps(plan))
    return path


def test_capture_blocked_before_transport_constructed(tmp_path, monkeypatch):
    calls = []

    def _forbidden_transport(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("transport must not be constructed for a blocked start")

    monkeypatch.setattr(cli, "campaign_transport", _forbidden_transport)
    output = tmp_path / "campaign-output"
    result = asyncio.run(
        cli.capture(
            _fresh_source_config(tmp_path),
            output,
            None,
            1,
            _unapproved_plan(tmp_path),
            None,
        )
    )
    assert calls == []
    assert result["campaign_readiness"]["status"] == "BLOCKED"
    assert result["physical_network_attempts"] == 0
    assert result["qualification_verdict"] == "BLOCKED"
    assert result["production_promotion"] is False
    receipt = output / "campaign-start-blocked.json"
    assert receipt.exists()
    parsed = json.loads(receipt.read_text())
    assert parsed["campaign_start_gate"]["phase"] == "BLOCKED"
    assert parsed["physical_network_attempts"] == 0
    assert parsed["blockers"]
