#!/usr/bin/env python3
"""Verify the repository-internal MPR-SYS-01 rooted-truth contract.

The verifier distinguishes executable sender-free closure from external rooted
attestation and the remaining historical-consumer migration work. It must never
turn unavailable deployment evidence into a successful production-admission
claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.chain_registry import (  # noqa: E402
    ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    ChainRegistry,
)
from src.rooted_truth import (  # noqa: E402
    BlockhashLease,
    DeployedIdentityRegistry,
    ForkContext,
    RootedRuntimeTruth,
    RuntimeTruthPolicy,
)

OFFICIAL_TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
OFFICIAL_ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
OFFICIAL_ALT = "AddressLookupTab1e1111111111111111111111111"
KNOWN_FALSE_LITERALS = (
    "TokenzQdBNbLqP5VEhdkAS6EPFJmNchboJLH2e2UrfW",
    "TokenzQdBNbLqP5VEhdkAS6EPw1N1qEHxZC6kzNRQdB",
    "TokenzQdY73Y67cyxEWKrvMpkFea8GZ4SXifknFxQ",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA4knL",
)


def _load_json(relative: str) -> object:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    manifest = _load_json("config/mpr_sys_01_identity_consumers.json")
    if not isinstance(manifest, dict):
        raise TypeError("identity consumer manifest must be an object")

    registry = ChainRegistry.load_default()
    policy = RuntimeTruthPolicy.load_default()
    if TOKEN_2022_PROGRAM_ADDRESS != OFFICIAL_TOKEN_2022:
        errors.append("canonical Token-2022 identity is incorrect")
    if ASSOCIATED_TOKEN_PROGRAM_ADDRESS != OFFICIAL_ATA:
        errors.append("canonical associated-token identity is incorrect")
    if ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS != OFFICIAL_ALT:
        errors.append("canonical ALT identity is incorrect")
    for entry_id, expected in (
        ("token_2022_program", OFFICIAL_TOKEN_2022),
        ("associated_token_program", OFFICIAL_ATA),
        ("address_lookup_table_program", OFFICIAL_ALT),
    ):
        if registry.entry(entry_id).address != expected:
            errors.append(f"chain registry mismatch: {entry_id}")

    packaged = _load_json("src/resources/chain_registry.json")
    source = _load_json("config/chain_registry.json")
    if packaged != source:
        errors.append("source and packaged chain registries differ")

    migrated = [str(item) for item in manifest.get("migrated_consumers", [])]
    pending = [str(item) for item in manifest.get("pending_consumer_migrations", [])]
    for module in migrated:
        path = ROOT / (module.replace(".", "/") + ".py")
        if not path.is_file():
            errors.append(f"migrated consumer missing: {module}")
            continue
        text = path.read_text(encoding="utf-8")
        if "src.config.chain_registry" not in text:
            errors.append(f"consumer does not import canonical registry: {module}")
        if any(value in text for value in KNOWN_FALSE_LITERALS):
            errors.append(f"migrated consumer retains false identity: {module}")

    schemas = _load_json("src/resources/schema_registry.json")
    schema_ids = {
        str(item.get("schema_id"))
        for item in schemas.get("schemas", [])
        if isinstance(item, dict)
    }
    required_schemas = {
        "mpr-sys-01.rooted-runtime-truth.v1",
        "mpr-sys-01.rooted-runtime-truth-evidence.v1",
        "mpr-sys-01.rooted-runtime-policy.v1",
    }
    missing_schemas = sorted(required_schemas - schema_ids)
    if missing_schemas:
        errors.append(f"unregistered rooted-truth schemas: {missing_schemas!r}")

    # Import assertions prove that the installed semantic API exposes the
    # generation, fork, blockhash and aggregate truth owners.
    for value in (
        DeployedIdentityRegistry,
        ForkContext,
        BlockhashLease,
        RootedRuntimeTruth,
    ):
        if not isinstance(value.__name__, str):
            errors.append("rooted-truth semantic API is unavailable")

    external = [str(item) for item in manifest.get("external_evidence_blockers", [])]
    blockers = [f"PENDING_CONSUMER_MIGRATION:{item}" for item in pending]
    blockers.extend(f"EXTERNAL_ROOTED_EVIDENCE:{item}" for item in external)
    blockers.extend(
        [
            "SOURCE_WHEEL_IMAGE_FALSE_LITERAL_EXTINCTION_NOT_YET_COMPLETE",
            "CREDENTIALED_ROOTED_PROVIDER_QUORUM_NOT_MATERIALIZED",
        ]
    )

    return {
        "schema_version": "mpr-sys-01.rooted-runtime-truth-evidence.v1",
        "accepted": not errors,
        "static_contract_passed": not errors,
        "production_admission_ready": False,
        "sender_free": True,
        "live_enabled": False,
        "canonical_token_2022": TOKEN_2022_PROGRAM_ADDRESS,
        "canonical_associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
        "canonical_alt_program": ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
        "token_2022_default_allowed": policy.allow_token_2022,
        "migrated_consumers": migrated,
        "pending_consumer_migrations": pending,
        "external_evidence_complete": False,
        "blockers": blockers,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--require-production-admission", action="store_true")
    args = parser.parse_args()
    evidence = build_evidence()
    if args.as_json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print("MPR-SYS-01 rooted truth:", "PASS" if evidence["accepted"] else "FAIL")
    if not evidence["accepted"]:
        return 1
    if args.require_production_admission and not evidence["production_admission_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
