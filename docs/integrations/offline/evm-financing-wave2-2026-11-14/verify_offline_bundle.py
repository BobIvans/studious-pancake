#!/usr/bin/env python3
"""Verify the offline evm-financing-wave2 source-dossier bundle without network access.

Checks (zero network):
1. Every REQUIRED file exists.
2. SOURCE_MANIFEST.json internal completeness per source entry (provider, chain,
   canonical_urls, retrieved_at_utc, snapshot_status, interface_surface,
   flash_loan_semantics, fee_fields, license_status, status, dossier_file,
   content_sha256).
3. SHA-256 of every declared dossier file matches the manifest (CRLF-normalized).
4. Every typed blocker is a typed string (MISSING_PIN / BLOCKED_MISSING_PIN /
   MISSING_DEPLOYED_ABI / BLOCKED_LICENSE_GRANT / EXTERNAL_CONFORMANCE_MISSING).
5. Deployment pin address format; known-good official snapshots (Aave Pool addresses
   inherited from wave-1 #618, Fluid Liquidity address, Spark registry rows).
6. Safety invariants: no capacity claims, no enablement, domain isolation kept.
Exit 0 = bundle OK; exit 1 = FAIL lines on stderr.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "SOURCE_MANIFEST.json"

REQUIRED = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "AAVE_V3_FLASHLOAN_SIMPLE_WAVE2.md",
    "FLUID_LIQUIDITY_WAVE2.md",
    "EULER_EVK_FLASH_WAVE2.md",
    "SPARK_LEND_PSM3_WAVE2.md",
    "EVM_CALLBACK_ATOMICITY_WAVE2.md",
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
    "fee_fields",
    "license_status",
    "status",
    "dossier_file",
    "content_sha256",
)

ALLOWED_STATUS = {"PINNED_CURRENT", "PARTIAL_PIN", "MISSING_PIN", "BLOCKED"}
BLOCKER_RE = re.compile(
    r"^(MISSING_PIN|BLOCKED_MISSING_PIN|MISSING_DEPLOYED_ABI|BLOCKED_LICENSE_GRANT|"
    r"EXTERNAL_CONFORMANCE_MISSING)( \([^)]*\))?::?.+"
)
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

WAVE1_AAVE_POOL_ETH = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
WAVE1_AAVE_POOL_OP_ARB = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
WAVE1_AAVE_POOL_BASE = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
FLUID_LIQUIDITY = "0x52Aa899454998Be5b000Ad077a46Bbe360F4e497"
SPARK_POOL = "0xC13e21B648A5Ee794902342038FF3aDAB66BE987"

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
        manifest = dict(__import__("json").loads(MANIFEST.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        fail(f"malformed SOURCE_MANIFEST.json: {exc}")
        return report()
    sources = manifest.get("sources") or {}
    if not sources:
        fail("manifest has no sources")

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

    aave = sources.get("aave_v3_flashloansimple") or {}
    sem = str(aave.get("flash_loan_semantics") or "")
    if "never waived" not in sem.lower() or "amount+premium" not in sem.replace(" ", ""):
        fail("aave: flash_loan_semantics must keep the never-waived + amount+premium facts")
    fluid = sources.get("fluid_liquidity") or {}
    pins = fluid.get("deployment_pins") or {}
    for chain in ("1", "42161", "8453"):
        if pins.get(chain) != FLUID_LIQUIDITY:
            fail(f"fluid: deployment pin drifted for chain {chain}")
    if pins.get("10") != "MISSING_PIN":
        fail("fluid: OP Mainnet pin must stay MISSING_PIN")
    spark = sources.get("spark_lend") or {}
    spark_pins = spark.get("deployment_pins") or {}
    if spark_pins.get("1_POOL") != SPARK_POOL:
        fail("spark: Pool registry pin drifted")

    aave_text = (BASE / "AAVE_V3_FLASHLOAN_SIMPLE_WAVE2.md").read_text(encoding="utf-8")
    for needle in (
        WAVE1_AAVE_POOL_ETH,
        WAVE1_AAVE_POOL_OP_ARB,
        WAVE1_AAVE_POOL_BASE,
        "executeOperation",
        "IFlashLoanSimpleReceiver",
        "FLASHLOAN_PREMIUM_TOTAL",
        "MISSING_DEPLOYED_ABI",
        "BLOCKED_LICENSE_GRANT",
        "NOT a capacity proof",
    ):
        if needle not in aave_text:
            fail("aave dossier missing wave content: " + needle)

    safety = manifest.get("safety") or {}
    if safety.get("sign_enabled") is not False or safety.get("send_enabled") is not False:
        fail("safety: sign/send must remain disabled")
    if safety.get("provider_enabled_by_this_wave") is not False:
        fail("safety: wave must not enable any provider")
    if not str(safety.get("live_rpc_calls") or "").startswith("NONE"):
        fail("safety: no live RPC calls allowed in this lane")
    if "UNKNOWN" not in str(safety.get("capacity_claims")):
        fail("safety: capacity claims must remain UNKNOWN-typed")

    overlap = (BASE / "OVERLAP_NOTES.md").read_text(encoding="utf-8")
    for needle in ("PR #618", "PR #621", "underlying_capital_resource_id"):
        if needle not in overlap:
            fail("overlap notes missing reference: " + needle)
    if "cross_chain" in overlap and "isolation flag stays true" not in overlap:
        fail("overlap notes must keep the isolation statement")
    readme = (BASE / "README.md").read_text(encoding="utf-8")
    for needle in ("PR #618", "sui-market-wave2-2026-11-14", "PINNED_CURRENT"):
        if needle not in readme:
            fail("README missing reference: " + needle)
    return report()


def report() -> int:
    if failures:
        for f in failures:
            print("FAIL: " + f, file=sys.stderr)
        print(f"FAILED with {len(failures)} problem(s).", file=sys.stderr)
        return 1
    manifest = dict(__import__("json").loads(MANIFEST.read_text(encoding="utf-8")))
    sources = manifest["sources"]
    n_blockers = sum(len(e.get("typed_blockers") or []) for e in sources.values())
    print(
        f"PASS: {len(sources)} EVM financing sources "
        f"({sum(1 for e in sources.values() if e.get('status') == 'PINNED_CURRENT')} PINNED_CURRENT, "
        f"{sum(1 for e in sources.values() if e.get('status') == 'PARTIAL_PIN')} PARTIAL_PIN), "
        f"{n_blockers} typed blockers, all content hashes verified. Zero network calls. "
        "No live capacity or enablement implied."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
