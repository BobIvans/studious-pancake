#!/usr/bin/env python3
"""Verify the offline sui-market-wave2 source-dossier bundle without network access.

Checks (zero network):
1. Every REQUIRED file exists.
2. SOURCE_MANIFEST.json internal completeness per source entry.
3. SHA-256 of every declared dossier file matches the manifest (CRLF-normalized).
4. Every typed blocker is a typed string (MISSING_PIN / BLOCKED_MISSING_PIN /
   EXTERNAL_CONFORMANCE_MISSING).
5. Sui package/object ID format (0x + 64 hex); known-good official snapshots
   (DeepBook V3 Published.toml mainnet IDs, Cetus CLMM mainnet IDs).
6. Safety invariants: no capacity claims, no enablement, domain isolation kept.
Exit 0 = bundle OK; exit 1 = FAIL lines on stderr.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "SOURCE_MANIFEST.json"

REQUIRED = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "CETUS_CLMM_POOL_WAVE2.md",
    "AFTERMATH_ROUTER_WAVE2.md",
    "FLOWX_AGGREGATOR_WAVE2.md",
    "DEEPBOOK_V3_FLASH_WAVE2.md",
    "SUI_PTB_ATOMICITY_WAVE2.md",
    "OVERLAP_NOTES.md",
    "verify_offline_bundle.py",
)

REQUIRED_SOURCE_FIELDS = (
    "provider",
    "chain",
    "canonical_urls",
    "retrieved_at_utc",
    "snapshot_status",
    "interface_surface",
    "flash_loan_semantics",
    "fee_semantics",
    "license_status",
    "status",
    "dossier_file",
    "content_sha256",
)

ALLOWED_STATUS = {"PINNED_CURRENT", "PARTIAL_PIN", "MISSING_PIN", "BLOCKED"}
BLOCKER_RE = re.compile(
    r"^(MISSING_PIN|BLOCKED_MISSING_PIN|MISSING_DEPLOYED_ABI|BLOCKED_LICENSE_GRANT|"
    r"EXTERNAL_CONFORMANCE_MISSING):"
)
SUI_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

DEEPBOOK_MAINNET_PUBLISHED = (
    "0xbca0cefe720330e7bb4f2283438b68de6a0e656688db4ac90d61e71fe6151fe8"
)
DEEPBOOK_MAINNET_ORIGINAL = (
    "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809"
)
CETUS_CLMM_PACKAGE = "0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb"
CETUS_POOLS_REGISTRY = (
    "0xf699e7f2276f5c9a75944b37a0c5b5d9ddfd2471bf6242483b03ab2887d198d0"
)

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def sha256_file(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    for name in REQUIRED:
        if not (BASE / name).is_file():
            fail("missing required file " + name)
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        fail(f"malformed SOURCE_MANIFEST.json: {exc}")
        return report()
    sources = manifest.get("sources") or {}
    if not sources:
        fail("manifest has no sources")

    def ids_ok(container: object, field_path: str) -> None:
        mapping = container or {}
        for key, value in dict(mapping).items():
            if value == "MISSING_PIN":
                continue
            if isinstance(value, int):
                continue
            if "chain_id" in key:
                continue  # Sui chain-id is a short hex string, not an object id
            if not (isinstance(value, str) and SUI_ID_RE.match(value)):
                fail(f"{field_path}.{key}: not a 64-hex Sui id ({value!r})")

    for sid, entry in sources.items():
        for field in REQUIRED_SOURCE_FIELDS:
            value = entry.get(field)
            if value is None or value == "" or value == []:
                fail(f"{sid}: missing manifest field {field}")
        urls = entry.get("canonical_urls") or []
        if not all(str(u).startswith("https://") for u in urls):
            fail(f"{sid}: non-https canonical url")
        sha = entry.get("content_sha256")
        if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha or "")):
            fail(f"{sid}: malformed content_sha256")
        else:
            path = BASE / str(entry.get("dossier_file") or "")
            if not path.is_file():
                fail(f"{sid}: dossier file missing {entry.get('dossier_file')}")
            elif sha256_file(path) != sha:
                fail(f"{sid}: content_sha256 mismatch for {path.name}")
        status = entry.get("status")
        if status not in ALLOWED_STATUS:
            fail(f"{sid}: status {status!r} not in {sorted(ALLOWED_STATUS)}")
        blockers = entry.get("typed_blockers") or []
        if not isinstance(blockers, list):
            fail(f"{sid}: typed_blockers must be a list")
        for b in blockers:
            if not isinstance(b, str) or not BLOCKER_RE.match(b):
                fail(f"{sid}: untyped blocker {b!r}")
        ids_ok(entry.get("pool_identity_pins"), f"{sid}.pool_identity_pins")

    deepbook = sources.get("deepbook_v3_flash") or {}
    pins = deepbook.get("pool_identity_pins") or {}
    if pins.get("mainnet_published_at") != DEEPBOOK_MAINNET_PUBLISHED:
        fail("deepbook: mainnet published-at pin drifted")
    if pins.get("mainnet_original_id") != DEEPBOOK_MAINNET_ORIGINAL:
        fail("deepbook: mainnet original-id pin drifted")
    if int(pins.get("mainnet_version", 0)) != 9:
        fail("deepbook: mainnet version pin must stay 9")

    cetus = sources.get("cetus_clmm_pool") or {}
    cpins = cetus.get("pool_identity_pins") or {}
    if cpins.get("clmm_pool_package_id") != CETUS_CLMM_PACKAGE:
        fail("cetus: clmm package pin drifted")
    if cpins.get("pools_registry_object") != CETUS_POOLS_REGISTRY:
        fail("cetus: pools registry object pin drifted")

    db_text = (BASE / "DEEPBOOK_V3_FLASH_WAVE2.md").read_text(encoding="utf-8")
    for needle in (
        "borrow_flashloan_base",
        "return_flashloan_base",
        "FlashLoan",
        "EIncorrectQuantityReturned",
        "The entire PTB reverts",
        "Snippets are not evidence",
        "UNKNOWN",
    ):
        if needle not in db_text:
            fail("deepbook dossier missing wave content: " + needle)

    ptb_text = (BASE / "SUI_PTB_ATOMICITY_WAVE2.md").read_text(encoding="utf-8")
    for needle in (
        "atomically at the end of the transaction",
        "entire block fails",
        "1,024",
        "prog-txn-blocks",
        "UNKNOWN is not zero",
        "hot potato",
    ):
        if needle not in ptb_text:
            fail("ptb dossier missing wave content: " + needle)

    safety = manifest.get("safety") or {}
    if safety.get("sign_enabled") is not False or safety.get("send_enabled") is not False:
        fail("safety: sign/send must remain disabled")
    if safety.get("provider_enabled_by_this_wave") is not False:
        fail("safety: wave must not enable any provider")
    if not str(safety.get("live_node_calls") or "").startswith("NONE"):
        fail("safety: no live node calls allowed in this lane")
    if "UNKNOWN" not in str(safety.get("capacity_claims")):
        fail("safety: capacity claims must remain UNKNOWN-typed")

    overlap = (BASE / "OVERLAP_NOTES.md").read_text(encoding="utf-8")
    for needle in ("PR #621", "SOURCE_LEDGER.json", "R02-CAP-C", "domain isolation"):
        if needle not in overlap:
            fail("overlap notes missing reference: " + needle)
    readme = (BASE / "README.md").read_text(encoding="utf-8")
    for needle in ("PR #621", "evm-financing-wave2-2026-11-14", "PINNED_CURRENT"):
        if needle not in readme:
            fail("README missing reference: " + needle)
    return report()


def report() -> int:
    if failures:
        for f in failures:
            print("FAIL: " + f, file=sys.stderr)
        print(f"FAILED with {len(failures)} problem(s).", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["sources"]
    n_blockers = sum(len(e.get("typed_blockers") or []) for e in sources.values())
    pinned = sum(1 for e in sources.values() if e.get("status") == "PINNED_CURRENT")
    partial = sum(1 for e in sources.values() if e.get("status") == "PARTIAL_PIN")
    print(
        f"PASS: {len(sources)} Sui market sources ({pinned} PINNED_CURRENT, "
        f"{partial} PARTIAL_PIN), {n_blockers} typed blockers, all content hashes "
        "verified. Zero network calls. No live capacity or enablement implied."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
