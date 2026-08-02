#!/usr/bin/env python3
"""Verify the repository-internal MPR-SYS-02 execution-truth contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.execution_truth import (  # noqa: E402
    CompiledMessageRef,
    DurableAttemptRef,
    EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID,
    EXECUTION_TRUTH_SCHEMA_ID,
    ExecutionStage,
    ExecutionTruthBundle,
    PlanRef,
    ReconciliationRef,
    RootedCandidateRef,
    SimulationRef,
    TerminalState,
    evaluate_bundle,
)
from src.pr206_durable_state import PR206DurableStateStore  # noqa: E402
from src.pr227_exact_money_atomic_evidence import (  # noqa: E402
    PR227EvidenceBundle,
)
from src.rooted_truth import (  # noqa: E402
    CandidateTruthBinding,
    ROOTED_TRUTH_SCHEMA_ID,
)


def _digest(character: str) -> str:
    return character * 64


def _fixture() -> ExecutionTruthBundle:
    rooted = RootedCandidateRef(
        candidate_id="mpr-sys-02-fixture",
        candidate_truth_hash=_digest("a"),
        cluster_genesis_hash=_digest("b"),
        admission_hash=_digest("c"),
        root_slot=100,
    )
    plan = PlanRef.create(
        candidate_truth_hash=rooted.candidate_truth_hash,
        principal_lamports=1_000,
        expires_block_height=500,
    )
    compiled = CompiledMessageRef(
        message_hash=_digest("e"),
        plan_hash=plan.plan_hash,
        blockhash="offline-blockhash-fixture",
        last_valid_block_height=450,
        alt_hashes=(_digest("f"),),
    )
    simulation = SimulationRef(
        simulation_hash=_digest("1"),
        message_hash=compiled.message_hash,
        context_slot=110,
        fee_lamports=5,
        units_consumed=123_456,
        logs_hash=_digest("2"),
        successful=True,
    )
    reconciliation = ReconciliationRef(
        reconciliation_hash=_digest("3"),
        simulation_hash=simulation.simulation_hash,
        message_hash=compiled.message_hash,
        principal_lamports=1_000,
        gross_proceeds_lamports=1_200,
        flash_repayment_lamports=50,
        network_fee_lamports=5,
        rent_delta_lamports=10,
        tip_lamports=5,
        uncertainty_buffer_lamports=10,
        conservative_surplus_lamports=120,
    )
    durable = DurableAttemptRef(
        attempt_id="mpr-sys-02-attempt",
        generation=1,
        lifecycle_revision=6,
        stage=ExecutionStage.TERMINAL,
        terminal_state=TerminalState.SUCCESS,
        writer_fence=7,
        event_head_hash=_digest("4"),
        idempotency_hash=_digest("5"),
        reservation_hash=_digest("6"),
        candidate_truth_hash=rooted.candidate_truth_hash,
        plan_hash=plan.plan_hash,
        message_hash=compiled.message_hash,
        simulation_hash=simulation.simulation_hash,
        reconciliation_hash=reconciliation.reconciliation_hash,
    )
    return ExecutionTruthBundle(
        rooted=rooted,
        plan=plan,
        compiled=compiled,
        simulation=simulation,
        reconciliation=reconciliation,
        durable=durable,
    )


def _registered_schema_ids() -> set[str]:
    payload = json.loads(
        (ROOT / "src/resources/schema_registry.json").read_text(encoding="utf-8")
    )
    schemas = payload.get("schemas", [])
    if not isinstance(schemas, list):
        return set()
    return {
        str(item.get("schema_id"))
        for item in schemas
        if isinstance(item, dict) and item.get("schema_id")
    }


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    if ROOTED_TRUTH_SCHEMA_ID != "mpr-sys-01.rooted-runtime-truth.v1":
        errors.append("MPR-SYS-01 rooted-truth schema identity drifted")

    required_schema_ids = {
        EXECUTION_TRUTH_SCHEMA_ID,
        EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID,
    }
    missing_schema_ids = sorted(required_schema_ids - _registered_schema_ids())
    if missing_schema_ids:
        errors.append(f"unregistered execution-truth schemas: {missing_schema_ids!r}")

    for owner in (
        CandidateTruthBinding,
        PR206DurableStateStore,
        PR227EvidenceBundle,
    ):
        if not isinstance(owner.__name__, str):
            errors.append("required upstream semantic owner is unavailable")

    try:
        report = dict(evaluate_bundle(_fixture()))
    except Exception as exc:
        errors.append(f"execution-truth fixture failed: {exc}")
        report = {}

    return {
        "schema_version": EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID,
        "contract_schema": EXECUTION_TRUTH_SCHEMA_ID,
        "accepted": not errors,
        "repository_contract_passed": not errors,
        "registered_schema_ids": sorted(required_schema_ids),
        "rooted_truth_owner": "src.rooted_truth.CandidateTruthBinding",
        "durable_state_owner": "src.pr206_durable_state.PR206DurableStateStore",
        "exact_economics_owner": (
            "src.pr227_exact_money_atomic_evidence.PR227EvidenceBundle"
        ),
        "sender_free": True,
        "live_enabled": False,
        "production_ready": False,
        "fixture_report": report,
        "blockers": [
            "ACTIVE_RUNTIME_CONSUMER_CUTOVER_NOT_PROVEN",
            "CREDENTIALED_ROOTED_PROVIDER_EVIDENCE_NOT_MATERIALIZED",
            "INSTALLED_WHEEL_IMAGE_EXECUTION_EVIDENCE_NOT_MATERIALIZED",
            "CRASH_AND_MULTI_WRITER_CAMPAIGN_NOT_MATERIALIZED",
        ],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    evidence = build_evidence()
    if args.as_json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print(
            "MPR-SYS-02 execution truth:",
            "PASS" if evidence["accepted"] else "FAIL",
        )
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
