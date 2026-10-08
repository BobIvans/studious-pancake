#!/usr/bin/env python3
"""No-network validator for the self-contained R-01/R-02 research handoff.

This validates reference integrity, NOT live provider correctness or ABI conformance.
Use: python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
"""
from __future__ import annotations

import json
import re
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
    print(f"PASS: {len(ids)} disabled candidate records, {len(contracts['entries'])} offline signatures, "
          f"{len(ledger.get('source_pins', []))} upstream commit pins. Zero network calls. "
          "No live capacity or full upstream ABI certification implied.")


if __name__ == "__main__":
    main()
