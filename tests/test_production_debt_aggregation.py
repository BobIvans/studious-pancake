from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.production_debt import (
    DebtStatus,
    ProductionDebtError,
    ProductionDebtInventory,
    evaluate_production_debt,
)

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_aggregates_debt_into_three_large_batches() -> None:
    inventory = ProductionDebtInventory.load_default()

    assert inventory.schema_version == "production-readiness.debt-inventory.v1"
    assert len(inventory.batches) == 3
    assert len(inventory.items) >= 30
    assert {batch.id for batch in inventory.batches} == {
        "batch-runtime-execution-unification",
        "batch-external-contract-conformance",
        "batch-operational-evidence-canary",
    }
    assert all(batch.item_ids for batch in inventory.batches)


def test_default_report_is_fail_closed_and_observes_real_repo_debt() -> None:
    report = evaluate_production_debt(repo_root=ROOT)

    assert report.consistency_errors == ()
    assert report.production_ready is False
    assert report.paper_ready is False
    assert report.live_ready is False
    assert report.observed["product_state"] == "not-production-ready"
    assert report.observed["live_mode_available"] is False
    assert report.observed["source_wheel_parity"] is False
    assert report.observed["kamino_supported_combinations"] == 0

    blockers = {item["id"]: item for item in report.blockers}
    assert "packaging.source-wheel-parity" in blockers
    assert "lending.kamino-supported-combinations" in blockers
    assert "runtime.live-entrypoint" in blockers
    assert blockers["packaging.source-wheel-parity"]["severity"] == "P0"


def test_external_review_manifest_pins_solana_helius_and_kamino() -> None:
    report = evaluate_production_debt(repo_root=ROOT)
    contracts = report.observed["external_contracts"]

    for contract_id in (
        "solana.v0-rpc-settlement",
        "helius.webhook-auth-delivery",
        "kamino.klend-mainnet-source-identity",
    ):
        contract = contracts[contract_id]
        assert contract["source"] == "production-external-review-manifest"
        assert contract["execution_allowed"] is False
        assert contract["promotion_state"] == "review-only-execution-blocked"


def test_re_reviewed_contracts_preserve_execution_denial() -> None:
    report = evaluate_production_debt(repo_root=ROOT)
    contracts = report.observed["external_contracts"]

    for contract_id in (
        "jupiter.swap-v2-build",
        "jito.low-latency-json-rpc",
        "marginfi.v2-mainnet-source-identity",
    ):
        assert contracts[contract_id]["execution_allowed"] is False
        assert contracts[contract_id]["source"] == (
            "production-external-review-manifest"
        )


def test_audit_script_is_source_checkout_safe_and_machine_readable() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/production_debt_audit.py",
            "--check",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "production-readiness.debt-report.v1"
    assert payload["production_ready"] is False
    assert payload["consistency_errors"] == []
    assert len(payload["batches"]) == 3


def test_require_ready_remains_blocked() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/production_debt_audit.py", "--require-ready"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 3
    assert "production_ready=False" in completed.stdout


def test_inventory_rejects_cross_batch_or_missing_evidence() -> None:
    inventory = ProductionDebtInventory.load_default()
    payload = {
        "schema_version": inventory.schema_version,
        "reviewed_at": inventory.reviewed_at,
        "batches": [
            {
                "id": "batch-a",
                "title": "A",
                "objective": "A",
                "item_ids": ["item-a"],
            }
        ],
        "items": [
            {
                "id": "item-a",
                "batch": "batch-b",
                "severity": "P0",
                "status": DebtStatus.IMPLEMENTATION_PENDING.value,
                "title": "Broken",
                "surface": "test",
                "blocks_paper": True,
                "blocks_live": True,
                "required_actions": ["act"],
                "evidence_refs": [],
            }
        ],
    }

    with pytest.raises(ProductionDebtError):
        ProductionDebtInventory.from_payload(payload)


def test_external_review_manifest_hashes_match_snapshots() -> None:
    import hashlib

    resource_root = ROOT / "src" / "resources"
    manifest = json.loads(
        (resource_root / "production_external_contracts.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["schema_version"] == (
        "production-readiness.external-review-manifest.v1"
    )
    assert len(manifest["contracts"]) == 6
    for contract in manifest["contracts"]:
        snapshot = resource_root / contract["snapshot_path"]
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == (
            contract["snapshot_sha256"]
        )
        assert contract["execution_allowed"] is False


def test_review_snapshots_encode_external_safety_constraints() -> None:
    resources = ROOT / "src" / "resources" / "contracts"
    solana = json.loads(
        (resources / "solana" / "solana_rpc_v0_settlement_review_2026-07-22.json")
        .read_text(encoding="utf-8")
    )
    jito = json.loads(
        (resources / "submission" / "jito_low_latency_review_2026-07-22.json")
        .read_text(encoding="utf-8")
    )
    helius = json.loads(
        (resources / "ingest" / "helius_webhook_auth_review_2026-07-22.json")
        .read_text(encoding="utf-8")
    )

    assert solana["reviewed_contract_facts"][
        "v0_requires_max_supported_transaction_version"
    ]
    assert solana["reviewed_contract_facts"][
        "send_transaction_is_submission_not_confirmation"
    ]
    assert jito["reviewed_contract_facts"]["max_transactions_per_bundle"] == 5
    assert jito["reviewed_contract_facts"]["bundle_id_is_landing_proof"] is False
    assert helius["reviewed_contract_facts"]["delivery_header"] == "Authorization"
