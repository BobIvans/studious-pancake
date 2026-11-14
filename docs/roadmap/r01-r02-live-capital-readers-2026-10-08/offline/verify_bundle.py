#!/usr/bin/env python3
"""No-network validator for the self-contained R-01/R-02 research handoff.

This validates reference integrity, NOT live provider correctness or ABI conformance.
Use: python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "offline"


def fail(msg: str) -> None:
    raise SystemExit("R02 OFFLINE CHECK FAILED: " + msg)


def read(name: str) -> dict:
    path = ROOT / name
    if not path.is_file():
        fail("missing " + name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"malformed {name}: {exc}")


def main() -> None:
    catalog = read("PROVIDER_CATALOG.json")
    ledger = read("offline/SOURCE_LEDGER.json")
    contracts = read("offline/CONTRACT_FACTS.json")
    ids = [x["id"] for x in catalog.get("entries", [])]
    if len(ids) < 25 or len(ids) != len(set(ids)):
        fail("provider catalog must have >=25 distinct ids")
    if set(ids) != {x["id"] for x in ledger.get("entries", [])}:
        fail("catalog and source ledger provider ids differ")
    if any(x.get("enabled") is not False or x.get("live_capacity_verified") is not False for x in catalog["entries"]):
        fail("all catalog providers must remain disabled, with no live-capacity claims")
    if catalog.get("default_policy", {}).get("sign_enabled") is not False:
        fail("sign_enabled must remain false")
    if catalog.get("default_policy", {}).get("send_enabled") is not False:
        fail("send_enabled must remain false")
    if ledger.get("execution_authority") != "NONE" or ledger.get("live_chain_capacity_verified") is not False:
        fail("source ledger must carry no live or execution authority")
    mandatory = {"jupiter_lend", "kamino", "navi", "project0", "deepbook", "scallop",
                 "morpho_blue", "euler_evk", "uniswap_v2_flash_swap", "uniswap_v3"}
    if not mandatory.issubset(set(ids)):
        fail("missing core researched providers")
    if not mandatory.issubset({x["id"] for x in contracts.get("entries", [])}):
        fail("missing core offline signature references")
    for x in ledger["entries"]:
        if not x.get("official_url", "").startswith("https://"):
            fail("missing primary official URL for " + x.get("id", "?"))
        if x.get("live_state_checked") or x.get("upstream_full_docs_vendored"):
            fail("no positive online or full copyrighted mirror claim allowed")
        sha = x.get("pinned_repo_sha")
        if sha is not None and not re.fullmatch(r"[0-9a-f]{40}", sha):
            fail("malformed upstream pin for " + x["id"])
    for x in contracts["entries"]:
        if not x.get("known_signatures") or not x.get("fail_closed_if"):
            fail("missing contract signature/negative for " + x.get("id", "?"))
    for path in [
        "README.md", "MASTER_CONTEXT.md", "R01_BRANCH_RECONCILIATION.md",
        "PROVIDER_SELECTION.md", "R02_ARCHITECTURE.md", "R02_TESTS_AND_EXIT_GATES.md",
        "CODEX_START_HERE.md", "offline/README.md",
        "offline/SOLANA_PROTOCOL_DOSSIERS.md",
        "offline/SUI_PROTOCOL_DOSSIERS.md", "offline/EVM_PROTOCOL_DOSSIERS.md",
        "offline/PROVIDER_ECONOMICS_AND_SELECTOR.md",
        "offline/GAPS_AND_STOP_CONDITIONS.md",
    ]:
        p = ROOT / path
        if not p.is_file() or p.stat().st_size < 250:
            fail("missing or empty required local documentation " + path)
    _verify_evm_wave_2026_11_14(ledger)
    print(f"PASS: {len(ids)} disabled candidate records, {len(contracts['entries'])} offline signatures, "
          f"{len(ledger.get('source_pins', []))} upstream commit pins. Zero network calls. "
          "No live capacity or full upstream ABI certification implied.")


def _require_iso_utc(value: object, what: str) -> None:
    if not isinstance(value, str):
        fail(what + " must be an ISO-8601 UTC string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(what + " is not a parseable ISO-8601 timestamp: " + value)


def _verify_evm_wave_2026_11_14(ledger: dict) -> None:
    """Zero-network checks for the R-07 stream L wave (Morpho Blue + Aave V3 pins)."""
    if ledger.get("last_wave") != "2026-11-14":
        fail("source ledger last_wave must stay 2026-11-14")
    if ledger.get("evm_domain_isolated_from_solana_sui") is not True:
        fail("EVM domain isolation flag must remain true")
    if ledger.get("cross_chain_atomicity_assumed") is not False:
        fail("cross_chain_atomicity_assumed must remain false")
    if ledger.get("provider_enabled_by_this_wave") is not False:
        fail("the wave must not enable any provider")
    pins = {p.get("repo"): p for p in ledger.get("source_pins", [])}
    wave_pins = {
        "morpho-org/sdks": "56f1ed62827a7aab39d979c0143d1fbf970c37ca",
        "morpho-org/morpho-blue-deployment": "3c9ac96cf5c7352ff01739a15d6057198e76d70e",
        "aave/aave-v3-origin": "5c2eb37f39959dd491ba97fdc2af94bb4ee88f41",
        "aave/aave-v3-core": "782f51917056a53a2c228701058a6c3fb233684a",
        "bgd-labs/aave-address-book": "b8c801a413c4b934afaf7976d2ddc5fbada6dce6",
    }
    for repo, sha in wave_pins.items():
        if repo not in pins or pins[repo].get("sha") != sha:
            fail("missing or drifted wave pin for " + repo)
    entries = {e.get("id"): e for e in ledger["entries"]}

    morpho = entries.get("morpho_blue")
    if not morpho or morpho.get("dossier_version") != "2026-11-14":
        fail("morpho_blue entry must carry the 2026-11-14 dossier version")
    _require_iso_utc(morpho.get("retrieved_utc"), "morpho_blue retrieved_utc")
    if morpho.get("pinned_repo_sha") != "339a885801972740eb27f51da110a4675b839d42":
        fail("morpho_blue primary pin drifted")
    if morpho.get("license_spdx") != "GPL-2.0":
        fail("morpho_blue license pin must stay GPL-2.0")
    morpho_pins = morpho.get("deployment_pins", {})
    morpho_canonical = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
    expected_morpho = {
        "1": morpho_canonical,
        "8453": morpho_canonical,
        "10": "0xce95AfbB8EA029495c66020883F87aaE8864AF92",
        "42161": "0x6c247b1F6182318877311737BaC0844bAa518F5e",
        "137": "0x1bF0c2541F820E775182832f06c0B7Fc27A25f67",
        "56": "0x01b0Bd309AA75547f7a37Ad7B1219A898E67a83a",
    }
    if morpho_pins != expected_morpho:
        fail("morpho_blue deployment pins drifted from the official snapshot")
    if any(
        morpho_pins[c] == morpho_canonical
        for c in ("10", "42161", "137", "56")
    ):
        fail("non-canonical chains must not be collapsed onto the Ethereum/Base singleton address")

    aave = entries.get("aave_v3")
    if not aave or aave.get("dossier_version") != "2026-11-14":
        fail("aave_v3 entry must carry the 2026-11-14 dossier version")
    _require_iso_utc(aave.get("retrieved_utc"), "aave_v3 retrieved_utc")
    if aave.get("pinned_repo_sha") != "5c2eb37f39959dd491ba97fdc2af94bb4ee88f41":
        fail("aave_v3 primary pin drifted")
    if aave.get("license_spdx") != "BSL-1.1" or "2027-03-06" not in (aave.get("license_note") or ""):
        fail("aave_v3 must keep the BSL-1.1 -> MIT 2027-03-06 license fact")
    if not any(b.startswith("BLOCKED_LICENSE_GRANT") for b in aave.get("typed_blockers", [])):
        fail("aave_v3 must keep the typed license blocker")
    aave_pins = aave.get("deployment_pins", {})
    aave_eth_pool = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
    if aave_pins.get("1") != aave_eth_pool:
        fail("aave_v3 Ethereum Core Pool pin drifted")
    for chain in ("10", "42161", "43114", "137"):
        if aave_pins.get(chain) != "0x794a61358D6845594F94dc1DB02A252b5b4814aD":
            fail("aave_v3 deterministic Pool pin drifted for chain " + chain)
    if aave_pins.get("8453") != "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5":
        fail("aave_v3 Base Pool pin drifted")
    if "aptos" in {k.lower() for k in aave_pins}:
        fail("Aptos Move-VM deployment must not enter the EVM deployment pin table")

    for entry in (morpho, aave):
        if entry.get("live_state_checked") or entry.get("readiness") != "OFFLINE_BEHAVIOR_REFERENCE_ONLY":
            fail("wave entries must stay offline-reference-only with no live state claim")
        if not entry.get("typed_blockers"):
            fail("wave entries must carry typed blockers")
        for addr in list(entry.get("deployment_pins", {}).values()):
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", addr):
                fail("malformed deployment pin address in " + entry["id"])

    dossier = (ROOT / "offline" / "EVM_PROTOCOL_DOSSIERS.md").read_text(encoding="utf-8")
    for needle in [
        morpho_canonical,
        aave_eth_pool,
        "onMorphoFlashLoan",
        "executeOperation",
        "RAW_OFFICIAL_SNAPSHOT",
        "BLOCKED_MISSING_PIN",
        "BLOCKED_LICENSE_GRANT",
        "morpho_blue@2026-11-14",
        "aave_v3@2026-11-14",
        "EVM remains a separately isolated research domain",
        "Local/fork simulation",
    ]:
        if needle not in dossier:
            fail("EVM dossier missing wave content: " + needle)
    if "0x" + "B" * 4 + "bbBBb9cC5e90e3b3Af64d3fC7f14AA5D88f" in dossier:
        fail("dossier must not contain the known-incorrect Morpho Blue address variant")


if __name__ == "__main__":
    main()
