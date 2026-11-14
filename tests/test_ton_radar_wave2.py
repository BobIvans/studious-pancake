"""Wave-2 additive contracts: typed pin states, no new adapter, frozen semantics.

Mirrors docs/integrations/offline/ton-wave2-2026-11-14/SOURCE_MANIFEST.json.
Zero network; no existing wave-1 test is modified or duplicated here.
"""

from pathlib import Path
import json

from src.discovery.dynamic_universe import ton_radar

WAVE2_DIR = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "integrations"
    / "offline"
    / "ton-wave2-2026-11-14"
)
ALLOWED_PIN_STATES = {
    "PINNED_CURRENT",
    "PINNED_STALE",
    "MISSING_PIN",
    "BLOCKED_MISSING_PIN",
    "BLOCKED_LIVE_CAPTURE_NOT_AUTHORIZED",
}


def wave2_manifest():
    return json.loads((WAVE2_DIR / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))


def test_pin_state_registry_matches_wave2_manifest_statuses():
    manifest = wave2_manifest()
    manifest_sources = {
        "ston.fi": manifest["sources"]["stonfi_dex_rest"],
        "omniston": manifest["sources"]["omniston"],
        "tonco": manifest["sources"]["tonco"],
        "toncenter": manifest["sources"]["toncenter"],
        "tonapi": manifest["sources"]["tonapi"],
    }
    assert set(ton_radar.TON_SOURCE_PIN_STATES) == set(manifest_sources)
    for source, payload in manifest_sources.items():
        assert ton_radar.TON_SOURCE_PIN_STATES[source] == payload["status"]


def test_tonco_stays_missing_pin_with_no_adapter():
    assert ton_radar.TON_SOURCE_PIN_STATES["tonco"] == "MISSING_PIN"
    # No Tonco adapter may exist while the GraphQL schema is unpinned.
    assert not any("Tonco" in name for name in dir(ton_radar))
    assert "tonco" not in ton_radar._REPLAY_SOURCES
    assert "toncenter" not in ton_radar._REPLAY_SOURCES
    assert "tonapi" not in ton_radar._REPLAY_SOURCES


def test_registry_values_stay_in_typed_vocabulary():
    assert all(
        state in ALLOWED_PIN_STATES
        for state in ton_radar.TON_SOURCE_PIN_STATES.values()
    )


def test_wave2_bundle_files_and_hashes_are_intact():
    manifest = wave2_manifest()
    for name in (
        "README.md",
        "REPORT.md",
        "TONCO_DISCOVERY_SURFACE.md",
        "OMNISTON_V1BETA8_VERIFY.md",
        "STONFI_SCHEMA_VERIFY_WAVE2.md",
        "TON_STATE_PROVIDERS_WAVE2.md",
        "TON_ATOMICITY_RESEARCH.md",
        "verify_offline_bundle.py",
    ):
        assert (WAVE2_DIR / name).is_file()
    for key in ("toncenter_v2_openapi_json", "opentonapi_openapi_yml"):
        pinned = manifest["vendor_reference_manifest"][key]
        mirror = WAVE2_DIR / pinned["mirrored_at"]
        assert mirror.is_file(), mirror
        raw = mirror.read_bytes()
        assert len(raw) == pinned["bytes"]
        import hashlib

        assert hashlib.sha256(raw).hexdigest() == pinned["sha256"]


def test_atomicity_note_records_typed_negative_baseline():
    note = (WAVE2_DIR / "TON_ATOMICITY_RESEARCH.md").read_text(encoding="utf-8")
    assert "ATOMICITY_RESEARCH" in note
    assert "MISSING_PIN" in note
    assert "https://docs.ton.org/from-ethereum" in note
    # The frozen research-only consequence must be restated in the note.
    assert "TON_ASYNC_MULTI_CONTRACT" in note
    assert ton_radar.TON_EXECUTION_CLASS == "TON_ASYNC_MULTI_CONTRACT"
    assert ton_radar.TON_NATIVE_ASSET == "ton:native"


def test_no_wave2_source_enabled_for_replay_or_enrichment():
    # The wave-2 verification adds no decode path: replay registration and the
    # route normalizer surface are exactly the wave-1 set.
    assert set(ton_radar._REPLAY_SOURCES) == {
        "ston.fi",
        "omniston",
        "dedust.io",
        "swap.coffee",
    }
    assert ton_radar._ENDPOINTS == ("assets", "pools", "stats")
