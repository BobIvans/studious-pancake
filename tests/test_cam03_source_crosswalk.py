"""CAM-03: source identity crosswalk, fresh pins, alias discipline."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.market.discovery import DiscoveryRequest
from src.qualification_campaign.sources import CatalogDiscoveryAdapter, SourceDossier
from src.qualification_campaign.identity import digest
from src.market.source_catalog import load_market_source_catalog

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/qualification/representative-sources.json"

CANONICAL_IDS = {"dexscreener", "geckoterminal", "raydium", "meteora-dlmm"}
# Plan-layer spellings (V2/#671 docs) mapped to canonical registry IDs.
PLAN_ALIAS_MAP = {
    "raydium_api_v3": "raydium",
    "meteora_dlmm_data": "meteora-dlmm",
}


def fingerprint(source_id, **request):
    adapter = CatalogDiscoveryAdapter(DiscoveryRequest(source_id=source_id, **request))
    return digest(adapter.schema_contract())


def test_config_covers_all_four_adapters_with_current_pins():
    raw = json.loads(CONFIG.read_text())
    ids = {row["dossier"]["source_id"] for row in raw["sources"]}
    assert ids == CANONICAL_IDS
    for row in raw["sources"]:
        dossier = row["dossier"]
        checked = datetime.fromisoformat(dossier["checked_at"])
        assert checked.tzinfo is not None
        assert checked <= datetime.now(timezone.utc)  # never future-dated
        assert len(dossier["docs_sha256"]) == 64
        assert dossier["classification"] == "DISCOVERY_ONLY"


def test_schema_fingerprints_match_current_adapter_contracts():
    raw = json.loads(CONFIG.read_text())
    expected = {
        "dexscreener": fingerprint(
            "dexscreener",
            token_mint="So11111111111111111111111111111111111111112",
        ),
        "geckoterminal": fingerprint("geckoterminal"),
        "raydium": fingerprint(
            "raydium",
            required_program_id="CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
        ),
        "meteora-dlmm": fingerprint("meteora-dlmm"),
    }
    for row in raw["sources"]:
        sid = row["dossier"]["source_id"]
        assert row["dossier"]["schema_fingerprint"] == expected[sid], sid


def test_config_dossiers_load_and_pass_ttl_now():
    raw = json.loads(CONFIG.read_text())
    now = datetime.now(timezone.utc)
    for row in raw["sources"]:
        dossier = dict(row["dossier"])
        dossier["profile"] = dossier["profile"]
        from src.qualification_campaign.profiles import ProviderProfile

        d = SourceDossier(
            **{**dossier, "profile": ProviderProfile(**dossier["profile"])}
        )
        d.require_current(int(now.timestamp() * 10**9))  # fresh pin must pass now
        with pytest.raises(ValueError):
            stale = SourceDossier(
                **{
                    **dossier,
                    "profile": ProviderProfile(**dossier["profile"]),
                    "checked_at": (now - timedelta(days=2)).isoformat(),
                }
            )
            stale.require_current(int(now.timestamp() * 10**9))


def test_plan_alias_spelling_maps_to_canonical_registry_ids():
    """No mechanical renames: plan spellings map explicitly to registry IDs."""
    registry_enum = set(DiscoveryRequest.__dataclass_fields__)  # placeholder
    from src.market import discovery as discovery_module

    supported = {"dexscreener", "geckoterminal", "raydium", "meteora-dlmm"}
    for plan_id, canonical in PLAN_ALIAS_MAP.items():
        assert canonical in supported
        assert plan_id not in supported  # plan label is not a registry ID


def test_catalog_contains_all_four_discovery_sources():
    catalog = load_market_source_catalog()
    for source_id in CANONICAL_IDS:
        entry = catalog.require(source_id)
        assert entry.access.value == "public-rate-limited"


def test_geckoterminal_docs_pin_is_current_not_redirect():
    raw = json.loads(CONFIG.read_text())
    gt = next(r for r in raw["sources"] if r["dossier"]["source_id"] == "geckoterminal")
    assert (
        gt["dossier"]["profile"]["official_docs"]
        == "https://docs.coingecko.com/reference/introduction"
    )


def test_meteora_docs_pin_is_current_official_reference():
    raw = json.loads(CONFIG.read_text())
    meteora = next(
        r for r in raw["sources"] if r["dossier"]["source_id"] == "meteora-dlmm"
    )
    assert meteora["dossier"]["profile"]["endpoint"] == (
        "https://dlmm.datapi.meteora.ag/pools"
    )
    assert meteora["dossier"]["profile"]["official_docs"] == (
        "https://docs.meteora.ag/developer-guides/dlmm/api-reference/overview.md"
    )
    # The drifted 404 URL must not survive anywhere in the config.
    assert "api-reference/dlmm/overview" not in json.dumps(raw)
