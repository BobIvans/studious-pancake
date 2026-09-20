from __future__ import annotations

import copy
import json

import pytest

from src import automation_cli_pr189

from src.release_gate.agg15_release_handoff import (
    AGG15_SCHEMA_VERSION,
    EXPECTED_EVOLUTION_STAGES,
    EXPECTED_NF_COUNT,
    Agg15AuditError,
    CoverageRecord,
    ImplementationStatus,
    OperationalStatus,
    ScopeDisposition,
    audit_coverage,
    evaluate_release_handoff,
)

COMMIT = "a" * 40


def _record(
    index: int,
    *,
    implementation: ImplementationStatus = ImplementationStatus.PLANNED,
    operational: OperationalStatus = OperationalStatus.UNQUALIFIED,
    disposition: ScopeDisposition = ScopeDisposition.REQUIRED,
) -> CoverageRecord:
    implemented = implementation in {
        ImplementationStatus.IMPLEMENTED_OFFLINE,
        ImplementationStatus.MERGED_CODE,
    }
    evidence = (f"evidence://NF-{index:03d}",) if implemented else ()
    tests = (f"tests://NF-{index:03d}",) if implemented else ()
    return CoverageRecord(
        nf_id=f"NF-{index:03d}",
        agg_id="AGG-15" if index >= 324 else "AGG-01",
        primary_owner="RELEASE-01" if index >= 324 else "QUAL-01",
        contract_ref=f"contract://NF-{index:03d}",
        implementation_status=implementation,
        operational_status=operational,
        scope_disposition=disposition,
        test_refs=tests,
        evidence_refs=evidence,
        merge_commit=(
            COMMIT if implementation is ImplementationStatus.MERGED_CODE else None
        ),
    )


def _coverage_payload(*, merged: bool) -> list[dict[str, object]]:
    status = (
        ImplementationStatus.MERGED_CODE
        if merged
        else ImplementationStatus.IMPLEMENTED_OFFLINE
    )
    operational = (
        OperationalStatus.EXTERNALLY_QUALIFIED_FOR_PROFILE
        if merged
        else OperationalStatus.UNQUALIFIED
    )
    rows = []
    for index in range(1, EXPECTED_NF_COUNT + 1):
        row = _record(
            index,
            implementation=status,
            operational=operational,
        )
        rows.append(
            {
                "nf_id": row.nf_id,
                "agg_id": row.agg_id,
                "primary_owner": row.primary_owner,
                "contract_ref": row.contract_ref,
                "implementation_status": row.implementation_status.value,
                "operational_status": row.operational_status.value,
                "scope_disposition": row.scope_disposition.value,
                "test_refs": list(row.test_refs),
                "evidence_refs": list(row.evidence_refs),
                "blocker_codes": [],
                "merge_commit": row.merge_commit,
            }
        )
    return rows


def _complete_manifest() -> dict[str, object]:
    return {
        "schema_version": AGG15_SCHEMA_VERSION,
        "release_id": "release-test",
        "source_commit": COMMIT,
        "coverage": _coverage_payload(merged=True),
        "selected_profiles": [
            {
                "profile_id": "core-marginfi-jupiter-v1",
                "release_generation": "generation-7",
                "implementation_status": "MERGED_CODE",
                "operational_status": "EXTERNALLY_QUALIFIED_FOR_PROFILE",
                "evidence_refs": ["evidence://profile"],
            }
        ],
        "integrated_campaign": {
            "release_generation": "generation-7",
            "lifecycle_owner": "UnifiedLifecycleAuthority",
            "capital_owner": "DurableCapitalCoordinator",
            "release_owner": "MPR2612DurableReleaseAuthority",
            "evidence": [
                {
                    "kind": "installed-wheel",
                    "generation": "generation-7",
                    "ref": "evidence://wheel",
                },
                {
                    "kind": "campaign",
                    "generation": "generation-7",
                    "ref": "evidence://campaign",
                },
            ],
            "stress_unknown_outcomes_checked": True,
            "shared_capacity_conflicts_checked": True,
            "live_enabled": False,
            "automatic_scale_up_allowed": False,
        },
        "operator_handoff": {
            "bootstrap_commands": ["flashloan-bot status"],
            "status_commands": ["flashloan-bot capabilities"],
            "stop_commands": ["operator-runbook://stop"],
            "recovery_commands": ["operator-runbook://recovery"],
            "remaining_scopes": ["frontier-research"],
            "secrets_embedded": False,
            "live_default": False,
        },
        "continuous_evolution": {
            "stages": list(EXPECTED_EVOLUTION_STAGES),
            "independent_promotion_required": True,
            "risk_authority_overridable": False,
            "auto_live": False,
        },
        "release_authority_receipt_ref": "evidence://mpr2612/receipt",
        "live_enabled": False,
        "automatic_scale_up_allowed": False,
    }


def test_coverage_requires_exactly_328_unique_nf_ids() -> None:
    rows = tuple(_record(index) for index in range(1, EXPECTED_NF_COUNT + 1))
    audit = audit_coverage(rows)

    assert audit.mapped_nf_count == 328
    assert audit.evidence_completed_nf_count == 0
    assert audit.structurally_complete is True
    assert audit.full_target_code_complete is False
    assert audit.required_incomplete_nf_ids[0] == "NF-001"
    assert audit.required_incomplete_nf_ids[-1] == "NF-328"


def test_duplicate_nf_id_is_rejected_instead_of_count_inflation() -> None:
    rows = [_record(index) for index in range(1, EXPECTED_NF_COUNT + 1)]
    rows.append(_record(328))

    with pytest.raises(Agg15AuditError, match="DUPLICATE_NF_ID"):
        audit_coverage(rows)


def test_implemented_claim_requires_tests_and_evidence() -> None:
    with pytest.raises(Agg15AuditError, match="IMPLEMENTATION_EVIDENCE_REQUIRED"):
        CoverageRecord(
            nf_id="NF-324",
            agg_id="AGG-15",
            primary_owner="RELEASE-01",
            contract_ref="contract://NF-324",
            implementation_status=ImplementationStatus.IMPLEMENTED_OFFLINE,
            operational_status=OperationalStatus.UNQUALIFIED,
            scope_disposition=ScopeDisposition.REQUIRED,
        )


def test_complete_manifest_is_handoff_ready_but_not_a_promotion_authority() -> None:
    report = evaluate_release_handoff(_complete_manifest())

    assert report.coverage.mapped_nf_count == 328
    assert report.coverage.evidence_completed_nf_count == 328
    assert report.scoped_release_handoff_ready is True
    assert report.full_target_handoff_ready is True
    assert report.eligible_for_canonical_release_review is True
    assert report.production_ready is False
    assert report.release_claim_allowed is False
    assert report.live_enabled is False
    assert report.automatic_scale_up_allowed is False
    assert report.blockers == ()


def test_campaign_generation_mixing_blocks_handoff() -> None:
    manifest = _complete_manifest()
    campaign = manifest["integrated_campaign"]
    assert isinstance(campaign, dict)
    evidence = campaign["evidence"]
    assert isinstance(evidence, list)
    assert isinstance(evidence[1], dict)
    evidence[1]["generation"] = "generation-8"

    report = evaluate_release_handoff(manifest)

    assert report.scoped_release_handoff_ready is False
    assert report.full_target_handoff_ready is False
    assert report.eligible_for_canonical_release_review is False
    assert "AGG15_CAMPAIGN_GENERATION_MIX" in report.blockers


def test_missing_canonical_receipt_does_not_fake_release_review() -> None:
    manifest = _complete_manifest()
    manifest.pop("release_authority_receipt_ref")

    report = evaluate_release_handoff(manifest)

    assert report.scoped_release_handoff_ready is True
    assert report.eligible_for_canonical_release_review is False
    assert "AGG15_CANONICAL_RELEASE_RECEIPT_REQUIRED" in report.blockers
    assert report.release_claim_allowed is False


def test_live_or_auto_scale_defaults_are_rejected() -> None:
    for field in ("live_enabled", "automatic_scale_up_allowed"):
        manifest = copy.deepcopy(_complete_manifest())
        manifest[field] = True
        with pytest.raises(Agg15AuditError):
            evaluate_release_handoff(manifest)


def test_research_disposition_does_not_become_fake_completion() -> None:
    rows = [_record(index) for index in range(1, EXPECTED_NF_COUNT + 1)]
    rows[-1] = _record(
        328,
        disposition=ScopeDisposition.RESEARCH,
    )

    audit = audit_coverage(rows)

    assert audit.structurally_complete is True
    assert audit.full_target_code_complete is False
    assert "NF-328" in audit.research_or_deferred_nf_ids
    assert audit.evidence_completed_nf_count == 0


def test_all_research_rows_cannot_masquerade_as_full_target_completion() -> None:
    rows = [
        _record(index, disposition=ScopeDisposition.RESEARCH)
        for index in range(1, EXPECTED_NF_COUNT + 1)
    ]

    audit = audit_coverage(rows)

    assert audit.structurally_complete is True
    assert audit.required_incomplete_nf_ids == ()
    assert audit.evidence_completed_nf_count == 0
    assert audit.full_target_code_complete is False


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("integrated_campaign", "stress_unknown_outcomes_checked"), "false"),
        (("integrated_campaign", "shared_capacity_conflicts_checked"), "false"),
        (("continuous_evolution", "independent_promotion_required"), "false"),
        (("operator_handoff", "live_default"), "false"),
        (("live_enabled",), "false"),
    ),
)
def test_manifest_safety_flags_require_json_booleans(
    path: tuple[str, ...],
    value: object,
) -> None:
    manifest = _complete_manifest()
    target: dict[str, object] = manifest
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(Agg15AuditError, match="BOOLEAN_REQUIRED"):
        evaluate_release_handoff(manifest)


def test_cli_reports_exact_blocker_instead_of_generic_runtime_error(
    tmp_path,
    capsys,
) -> None:
    manifest = _complete_manifest()
    manifest.pop("release_authority_receipt_ref")
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    exit_code = automation_cli_pr189.main(
        ["release-handoff", "inspect", "--manifest", str(path)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ready"] is False
    assert "AGG15_CANONICAL_RELEASE_RECEIPT_REQUIRED" in payload["reason_codes"]
    assert payload["reason_codes"] != ["PR189_COMMAND_INPUT_OR_RUNTIME_ERROR"]


def test_explicit_coverage_blocker_prevents_completion_and_is_propagated() -> None:
    manifest = _complete_manifest()
    first = manifest["coverage"][0]
    assert isinstance(first, dict)
    first["blocker_codes"] = ["AGG15_TEST_UNRESOLVED_BLOCKER"]

    report = evaluate_release_handoff(manifest)

    assert report.coverage.evidence_completed_nf_count == EXPECTED_NF_COUNT - 1
    assert report.full_target_handoff_ready is False
    assert "AGG15_TEST_UNRESOLVED_BLOCKER" in report.blockers
    assert report.eligible_for_canonical_release_review is False
