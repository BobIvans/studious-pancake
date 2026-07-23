from __future__ import annotations

import copy
import pytest

from src.mpr214_architecture_retirement_gate import (
    REQUIRED_FINDINGS,
    SCHEMA_VERSION,
    assert_mpr214_ready,
    validate_mpr214_architecture_retirement,
)


GOOD_HASH = "1" * 64


def good_evidence() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "finding_coverage": sorted(REQUIRED_FINDINGS),
        "module_inventory": {
            "generated_from_installed_artifact": True,
            "total_src_modules": 4,
            "reachable_modules": 2,
            "items": [
                {
                    "path": "src/domain/lifecycle.py",
                    "owner": "architecture",
                    "disposition": "promoted",
                    "reachable_from_installed_entrypoint": True,
                },
                {
                    "path": "src/domain/commitment.py",
                    "owner": "architecture",
                    "disposition": "library",
                    "reachable_from_installed_entrypoint": True,
                },
                {
                    "path": "src/legacy_arb_bot.py",
                    "owner": "archive",
                    "disposition": "archive",
                    "reachable_from_installed_entrypoint": False,
                    "retirement_deadline": "2026-08-31",
                },
                {
                    "path": "src/old/pr195_lifecycle.py",
                    "owner": "archive",
                    "disposition": "delete",
                    "reachable_from_installed_entrypoint": False,
                    "retirement_deadline": "2026-08-31",
                },
            ],
        },
        "production_import_graph": {
            "generated_from_installed_entrypoints": True,
            "unknown_runtime_modules": [],
            "cycles": [],
            "import_time_global_mutations": [],
            "new_pr_numbered_runtime_filenames": [],
            "pr_numbered_runtime_modules": ["src.compat.pr195_lifecycle"],
            "compatibility_shim_deadline_required": True,
        },
        "stable_domain_migration": {
            "new_runtime_pr_numbered_filenames_allowed": False,
            "promoted_domain_modules": ["src.domain.lifecycle", "src.domain.commitment"],
            "compatibility_shims": [
                {
                    "module": "src.compat.pr195_lifecycle",
                    "target": "src.domain.lifecycle",
                    "expires_on": "2026-08-31",
                }
            ],
        },
        "schema_registry": {
            "generated_from_installed_artifact": True,
            "unregistered_schema_ids": [],
            "entries": [
                {
                    "schema_id": "domain.lifecycle.v1",
                    "status": "current",
                    "owner": "architecture",
                    "compatibility": {"reads": ["domain.lifecycle.v1"], "writes": "domain.lifecycle.v1"},
                },
                {
                    "schema_id": "pr195.lifecycle.v1",
                    "status": "superseded",
                    "owner": "archive",
                    "compatibility": {"superseded_by": "domain.lifecycle.v1"},
                },
            ],
        },
        "domain_vocabulary": {
            "canonical_commitment_type": "ChainCommitment",
            "local_commitment_enums_removed": True,
            "canonical_lifecycle_state_type": "LifecycleState",
            "missing_exhaustive_mappings": [],
        },
        "durability_public_api": {
            "public_lifecycle_protocol": "LifecycleStore",
            "production_implementation": "SQLiteLifecycleStore",
            "historical_store_exports": [],
            "composition_root_can_import_historical_stores": False,
        },
        "legacy_retirement": {
            "legacy_arb_bot_disposition": "archive",
            "legacy_arb_bot_reachable": False,
            "mega_class_budget_enforced": True,
            "unowned_mega_classes": [],
        },
        "reachability_manifest": {
            "generated_from_installed_artifact": True,
            "unknown_runtime_modules": 0,
            "artifact_sha256": GOOD_HASH,
            "trace_hash": "2" * 64,
        },
        "capabilities": {
            "live_execution_allowed": False,
            "signer_allowed": False,
            "sender_allowed": False,
        },
    }


def codes(report):
    return {violation.code for violation in report.violations}


def test_happy_path_ready_and_live_disabled():
    report = validate_mpr214_architecture_retirement(good_evidence())

    assert report.ready is True
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert len(report.evidence_hash) == 64
    assert_mpr214_ready(good_evidence())


def test_requires_complete_finding_coverage():
    evidence = good_evidence()
    evidence["finding_coverage"].remove("F-275")

    report = validate_mpr214_architecture_retirement(evidence)

    assert report.ready is False
    assert "FINDING_COVERAGE" in codes(report)


def test_rejects_inventory_not_from_installed_artifact():
    evidence = good_evidence()
    evidence["module_inventory"]["generated_from_installed_artifact"] = False

    report = validate_mpr214_architecture_retirement(evidence)

    assert "MODULE_INVENTORY_SOURCE" in codes(report)


def test_rejects_reachable_archived_module():
    evidence = good_evidence()
    evidence["module_inventory"]["items"][2]["reachable_from_installed_entrypoint"] = True

    report = validate_mpr214_architecture_retirement(evidence)

    assert "REACHABLE_DISPOSITION" in codes(report)


def test_rejects_import_cycles_and_import_time_mutation():
    evidence = good_evidence()
    evidence["production_import_graph"]["cycles"] = [["src.a", "src.b"]]
    evidence["production_import_graph"]["import_time_global_mutations"] = ["src.providers.helius"]

    report = validate_mpr214_architecture_retirement(evidence)

    assert "IMPORT_CYCLE" in codes(report)
    assert "IMPORT_TIME_MUTATION" in codes(report)


def test_rejects_new_pr_numbered_runtime_filename_policy():
    evidence = good_evidence()
    evidence["stable_domain_migration"]["new_runtime_pr_numbered_filenames_allowed"] = True

    report = validate_mpr214_architecture_retirement(evidence)

    assert "PR_NUMBERED_FILENAME_POLICY" in codes(report)


def test_rejects_unregistered_schema_ids_and_duplicate_schema():
    evidence = good_evidence()
    evidence["schema_registry"]["unregistered_schema_ids"] = ["random.schema.v1"]
    evidence["schema_registry"]["entries"].append(copy.deepcopy(evidence["schema_registry"]["entries"][0]))

    report = validate_mpr214_architecture_retirement(evidence)

    assert "UNREGISTERED_SCHEMA" in codes(report)
    assert "SCHEMA_ID_UNIQUE" in codes(report)


def test_rejects_local_commitment_enums_and_missing_mappings():
    evidence = good_evidence()
    evidence["domain_vocabulary"]["local_commitment_enums_removed"] = False
    evidence["domain_vocabulary"]["missing_exhaustive_mappings"] = ["ProviderCommitment.processed"]

    report = validate_mpr214_architecture_retirement(evidence)

    assert "LOCAL_COMMITMENT_ENUMS" in codes(report)
    assert "EXHAUSTIVE_MAPPING" in codes(report)


def test_rejects_historical_lifecycle_exports():
    evidence = good_evidence()
    evidence["durability_public_api"]["historical_store_exports"] = ["LegacyDurableLifecycleStore"]

    report = validate_mpr214_architecture_retirement(evidence)

    assert "HISTORICAL_STORE_EXPORTS" in codes(report)


def test_rejects_legacy_reachable_and_unowned_mega_class():
    evidence = good_evidence()
    evidence["legacy_retirement"]["legacy_arb_bot_reachable"] = True
    evidence["legacy_retirement"]["unowned_mega_classes"] = ["JupiterTxBuilder"]

    report = validate_mpr214_architecture_retirement(evidence)

    assert "LEGACY_REACHABLE" in codes(report)
    assert "UNOWNED_MEGA_CLASS" in codes(report)


def test_rejects_placeholder_reachability_hash():
    evidence = good_evidence()
    evidence["reachability_manifest"]["artifact_sha256"] = "0" * 64

    report = validate_mpr214_architecture_retirement(evidence)

    assert "ARTIFACT_DIGEST" in codes(report)


def test_rejects_live_signer_sender_enablement():
    evidence = good_evidence()
    evidence["capabilities"]["live_execution_allowed"] = True
    evidence["capabilities"]["signer_allowed"] = True
    evidence["capabilities"]["sender_allowed"] = True

    report = validate_mpr214_architecture_retirement(evidence)

    assert {"LIVE_ENABLED", "SIGNER_ENABLED", "SENDER_ENABLED"} <= codes(report)


def test_assert_ready_raises_with_stable_reason():
    evidence = good_evidence()
    evidence["schema_version"] = "old"

    with pytest.raises(ValueError, match="SCHEMA_VERSION"):
        assert_mpr214_ready(evidence)
