#!/usr/bin/env python3
"""Verify MPR-SYS-01 rooted runtime truth and consumer convergence."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.chain_registry import (  # noqa: E402
    ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    ChainRegistry,
)
from src.kernel import domain_sha256  # noqa: E402
from src.rooted_truth import (  # noqa: E402
    AddressLookupTableState,
    BlockhashLease,
    DeployedIdentityRegistry,
    ForkContext,
    MintSnapshot,
    OracleSnapshot,
    PoolSnapshot,
    ROOTED_TRUTH_EVIDENCE_SCHEMA_ID,
    RootedRuntimeTruth,
    RootedTruthError,
    RuntimeTruthPolicy,
    build_admission,
)

GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
_FALSE_LITERALS = frozenset(
    {
        "TokenzQdBNbLqP5VEhdkAS6EPFJmNchboJLH2e2UrfW",
        "TokenzQdBNbLqP5VEhdkAS6EPw1N1qEHxZC6kzNRQdB",
        "TokenzQdY73Y67cyxEWKrvMpkFea8GZ4SXifknFxQ",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA4knL",
    }
)
_ALLOWED_NEGATIVE_FIXTURE = Path("src/pr196_protocol_account_conformance_v3.py")
def _digest(label: str) -> str:
    return domain_sha256(domain="mpr-sys-01-fixture", schema_id="fixture.v1", payload=label.encode())


def _build_truth() -> RootedRuntimeTruth:
    policy = RuntimeTruthPolicy.load_default()
    registry = DeployedIdentityRegistry.from_chain_registry(
        ChainRegistry.load_default(),
        cluster="mainnet-beta",
        genesis_hash=GENESIS,
        external_blockers=tuple(
            f"ROOTED_DEPLOYMENT_EVIDENCE_MISSING:{name}"
            for name in policy.external_required_programs
        ),
    )
    fork = ForkContext(
        cluster="mainnet-beta",
        genesis_hash=GENESIS,
        provider_id="offline-independent-quorum-fixture",
        context_slot=100,
        root_slot=100,
        block_height=90,
        commitment="finalized",
        feature_set_sha256=_digest("features"),
        registry_generation=registry.generation,
        observed_monotonic_ns=1,
        observed_at_utc="2026-08-02T00:00:00Z",
    )
    blockhash = BlockhashLease(
        blockhash=GENESIS,
        last_valid_block_height=150,
        observed_block_height=90,
        context_slot=100,
        registry_generation=registry.generation,
        evidence_sha256=_digest("blockhash"),
    )
    alt = AddressLookupTableState(
        table_address=ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
        owner_program_id=ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
        authority=None,
        deactivation_slot=None,
        last_extended_slot=90,
        ordered_addresses=(SYSTEM_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS),
        account_sha256=_digest("alt"),
        context_slot=100,
        root_slot=100,
        registry_generation=registry.generation,
    )
    mint = MintSnapshot(
        mint=NATIVE_SOL_MINT_ADDRESS,
        token_program_id=TOKEN_PROGRAM_ADDRESS,
        decimals=9,
        mint_authority=None,
        freeze_authority=None,
        permanent_delegate=None,
        transfer_hook_program=None,
        extensions=(),
        transfer_fee_bps=0,
        witheld_amount=0,
        account_length=82,
        rent_lamports=1,
        context_slot=100,
        root_slot=100,
        registry_generation=registry.generation,
        evidence_sha256=_digest("mint"),
        expires_at_slot=120,
     )
    oracle = OracleSnapshot(
        oracle_id="offline-oracle-fixture",
        price_atomic=1_000_000,
        confidence_bps=10,
        divergence_bps=20,
        observed_slot=100,
        root_slot=100,
        source_ids=("independent-a", "independent-b"),
        evidence_sha256=_digest("oracle"),
    )
    pool = PoolSnapshot(
        pool_id=TOKEN_PROGRAM_ADDRESS,
        program_id=SYSTEM_PROGRAM_ADDRESS,
        vault_owners=(TOKEN_PROGRAM_ADDRESS, SYSTEM_PROGRAM_ADDRESS),
        fee_bps=10,
        oracle_id="offline-oracle-fixture",
        context_slot=100,
        root_slot=100,
        registry_generation=registry.generation,
        evidence_sha256=_digest("pool"),
        expires_at_slot=120,
    )
    admission = build_admission(
        mint=mint,
        oracle=oracle,
        pool=pool,
        policy=policy,
        registry=registry,
        current_root_slot=100,
    )
    return RootedRuntimeTruth(registry, fork, blockhash, (alt,), admission)


def _scan_false_literals() -> tuple[list[str], list[str]]:
    unexpected: list[str] = []
    negative_fixture: list[str] = []
    for path in sorted((ROOT / "src").rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".json", ".yaml", ".yml"}:
            continue
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8", errors="replace")
        for literal in _FALSE_LITERALS:
            if literal not in text:
                continue
            finding = f"{relative}:{literal}"
            if relative == _ALLOWED_NEGATIVE_FIXTURE:
                negative_fixture.append(finding)
            else:
                unexpected.append(finding)
    return unexpected, negative_fixture


def _verify_consumers() -> list[str]:
    errors: list[str] = []
    manifest = json.loads(
        (ROOT / "config/mpr_sys_01_identity_consumers.json").read_text(
            encoding="utf-8"
        )
    )
    if manifest.get("canonical_owner") != "src.config.chain_registry":
        errors.append("identity consumer manifest has the wrong canonical owner")
    for module in manifest.get("migrated_consumers", []):
        path = ROOT / (str(module).replace(".", "/") + ".py")
        if not path.is_file():
            errors.append(f"migrated consumer is missing: {module}")
            continue
        text = path.read_text(encoding="utf-8")
        if "src.config.chain_registry" not in text:
            errors.append(f"consumer does not import canonical chain registry: {module}")
        if any(literal in text for literal in _FALSE_LITERALS):
            errors.append(f"consumer still contains a false protocol literal: {module}")
    return errors


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    truth = _build_truth()
    message_sha256 = _digest("message")
    binding = truth.bind_candidate(
        candidate_id="offline-candidate",
        message_sha256=message_sha256,
        required_program_ids=(SYSTEM_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS),
        expected_alt_digests=tuple(item.digest for item in truth.alts),
        current_root_slot=100,
        current_block_height=100,
        rpc_reports_blockhash_valid=True,
    )

    negative_results: dict[str, bool] = {}
    try:
        truth.bind_candidate(
            candidate_id="expired-blockhash",
            message_sha256=message_sha256,
            required_program_ids=(SYSTEM_PROGRAM_ADDRESS,),
            expected_alt_digests=tuple(item.digest for item in truth.alts),
            current_root_slot=100,
            current_block_height=151,
            rpc_reports_blockhash_valid=True,
        )
    except RootedTruthError:
        negative_results["expired_blockhash_rejected"] = True
    else:
        negative_results["expired_blockhash_rejected"] = False
        errors.append("expired blockhash was accepted")

    try:
        mixed = replace(truth.fork, registry_generation="0" * 64)
        RootedRuntimeTruth(
            truth.registry,
            mixed,
            truth.blockhash,
            truth.alts,
            truth.admission,
        )
    except RootedTruthError:
        negative_results["mixed_generation_rejected"] = True
    else:
        negative_results["mixed_generation_rejected"] = False
        errors.append("mixed registry generation was accepted")

    try:
        changed_alt = replace(truth.alts[0], deactivation_slot=100)
        RootedRuntimeTruth(
            truth.registry,
            truth.fork,
            truth.blockhash,
            (changed_alt,),
            truth.admission,
        ).bind_candidate(
            candidate_id="deactivated-alt",
            message_sha256=message_sha256,
            required_program_ids=(SYSTEM_PROGRAM_ADDRESS,),
            expected_alt_digests=(changed_alt.digest,),
            current_root_slot=100,
            current_block_height=100,
            rpc_reports_blockhash_valid=True,
        )
    except RootedTruthError:
        negative_results["deactivated_alt_rejected"] = True
    else:
        negative_results["deactivated_alt_rejected"] = False
        errors.append("deactivated ALT was accepted")

    policy = RuntimeTruthPolicy.load_default()
    token_2022 = replace(
        truth.admission.mint,
        token_program_id=TOKEN_2022_PROGRAM_ADDRESS,
        extensions=("transfer_hook",),
        transfer_hook_program=SYSTEM_PROGRAM_ADDRESS,
    )
    token_2022_admission = build_admission(
        mint=token_2022,
        oracle=truth.admission.oracle,
        pool=truth.admission.pool,
        policy=policy,
        registry=truth.registry,
        current_root_slot=100,
    )
    negative_results["token_2022_default_deny"] = not token_2022_admission.mint_decision.admitted
    if token_2022_admission.mint_decision.admitted:
        errors.append("unsupported Token-2022 mint was admitted")

    unexpected_false, negative_fixture = _scan_false_literals()
    if unexpected_false:
        errors.append(f"unexpected false protocol literals: {unexpected_false!r}")
    errors.extend(_verify_consumers())

    chain_registry = ChainRegistry.load_default()
    packaged_registry = json.loads(
        (ROOT / "src/resources/chain_registry.json").read_text(encoding="utf-8")
    )
    source_registry = json.loads(
        (ROOT / "config/chain_registry.json").read_text(encoding="utf-8")
    )
    if source_registry != packaged_registry:
        errors.append("source and packaged chain registries differ")
    for entry_id, expected in (
        ("token_2022_program", TOKEN_2022_PROGRAM_ADDRESS),
        ("associated_token_program", ASSOCIATED_TOKEN_PROGRAM_ADDRESS),
        ("address_lookup_table_program", ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS),
    ):
        if chain_registry.entry(entry_id).address != expected:
            errors.append(f"canonical chain registry mismatch: {entry_id}")

    schema_registry_path = ROOT / "src/resources/schema_registry.json"
    if schema_registry_path.is_file():
        schemas = {
            item.get("schema_id")
            for item in json.loads(schema_registry_path.read_text(encoding="utf-8"))[
                "schemas"
            ]
        }
        for required in (
            "mpr-sys-01.rooted-runtime-truth.v1",
            ROOTED_TRUTH_EVIDENCE_SCHEMA_ID,
            "mpr-sys-01.rooted-runtime-policy.v1",
        ):
            if required not in schemas:
                errors.append(f"schema is not registered: {required}")

    external_blockers = list(truth.registry.external_blockers)
    static_contract_passed = not errors
    return {
        "schema_version": ROOTED_TRUTH_EVIDENCE_SCHEMA_ID,
        "accepted": static_contract_passed,
        "static_contract_passed": static_contract_passed,
        "production_admission_ready": False,
        "sender_free": True,
        "live_enabled": False,
        "registry_generation": truth.registry.generation,
        "fork_context_sha256": truth.fork.digest,
        "blockhash_lease_sha256": truth.blockhash.digest,
        "admission_generation": truth.admission.generation,
        "rooted_truth_sha256": truth.digest,
        "candidate_binding": {
            "candidate_id": binding.candidate_id,
            "message_sha256": binding.message_sha256,
            "registry_generation": binding.registry_generation,
            "fork_context_sha2556": binding.fork_context_sha256,
            "blockhash_lease_sha256": binding.blockhash_lease_sha256,
            "alt_sha256s": list(binding.alt_sha256s),
            "admission_generation": binding.admission_generation,
            "rooted_truth_sha256": binding.rooted_truth_sha256,
        },
        "negative_results": negative_results,
        "unexpected_false_literal_count": len(unexpected_false),
        "explicit_negative_fixture_occurrences": negative_fixture,
        "external_evidence_complete": False,
        "external_blockers": external_blockers,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--require-external",
        action="store_true",
        help="Fail when rooted credentialed/deployment evidence remains unavailable.",
    )
    args = parser.parse_args()
    evidence = build_evidence()
    if args.as_json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print("MPR-SYS-01 rooted truth:", "PASS" if evidence["accepted"] else "FAIL")
    if not evidence["accepted"]:
        return 1
    if args.require_external and evidence["external_blockers"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
