from __future__ import annotations

import pytest

from src.simulation_cpi_pr137 import (
    ATA_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    PR137CallGraphError,
    PR137ExpectedRouteGraph,
    PR137InstructionObservation,
    PR137RouteProgramIdentity,
    PR137SimulationCallGraphEvidence,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    assert_pr137_simulation_cpi_call_graph,
    evaluate_pr137_simulation_cpi_call_graph,
)

HASH = "a" * 64
JUPITER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_PROGRAM = "RVKd61ztZW9TmniWu3q6W6c7SHDSehnnGsR1C7YcMEU"
ORCA_PROGRAM = "whirLbMiicVdio4qvUfM5KAg6CtMEXtVfEQH2yDTLQv"
UNKNOWN_PROGRAM = "Bad111111111111111111111111111111111111111"


def _expected() -> PR137ExpectedRouteGraph:
    return PR137ExpectedRouteGraph(
        top_level_program_ids=(COMPUTE_BUDGET_PROGRAM_ID, JUPITER_PROGRAM),
        route_programs=(
            PR137RouteProgramIdentity(
                route_segment_id="leg-a",
                label="Raydium",
                program_id=RAYDIUM_PROGRAM,
                deployment_attestation_sha256=HASH,
                expected_cpi_families=("swap", "token"),
            ),
            PR137RouteProgramIdentity(
                route_segment_id="leg-b",
                label="Orca",
                program_id=ORCA_PROGRAM,
                deployment_attestation_sha256=HASH,
                expected_cpi_families=("swap", "token"),
            ),
        ),
    )


def _evidence(
    *extra: PR137InstructionObservation,
    inner_instructions_requested: bool = True,
    inner_instructions_present: bool = True,
    loaded_addresses_present: bool = True,
    return_data_preserved: bool = True,
    account_keys_preserved: bool = True,
    logs_truncated: bool = False,
    expected_call_graph_sha256: str | None = None,
) -> PR137SimulationCallGraphEvidence:
    observations = (
        PR137InstructionObservation(
            program_id=COMPUTE_BUDGET_PROGRAM_ID,
            instruction_path=(0,),
            source="top_level",
            semantic_family="compute-budget",
        ),
        PR137InstructionObservation(
            program_id=JUPITER_PROGRAM,
            instruction_path=(1,),
            source="top_level",
            semantic_family="aggregator",
        ),
        PR137InstructionObservation(
            program_id=RAYDIUM_PROGRAM,
            instruction_path=(1, 0),
            source="inner",
            route_segment_id="leg-a",
            semantic_family="swap",
        ),
        PR137InstructionObservation(
            program_id=TOKEN_PROGRAM_ID,
            instruction_path=(1, 1),
            source="inner",
            semantic_family="token-transfer",
            transfer_checked=True,
        ),
        PR137InstructionObservation(
            program_id=ORCA_PROGRAM,
            instruction_path=(1, 2),
            source="inner",
            route_segment_id="leg-b",
            semantic_family="swap",
        ),
        PR137InstructionObservation(
            program_id=ATA_PROGRAM_ID,
            instruction_path=(1, 3),
            source="inner",
            semantic_family="ata-idempotent",
            transfer_checked=True,
        ),
        *extra,
    )
    return PR137SimulationCallGraphEvidence(
        inner_instructions_requested=inner_instructions_requested,
        inner_instructions_present=inner_instructions_present,
        loaded_addresses_present=loaded_addresses_present,
        return_data_preserved=return_data_preserved,
        account_keys_preserved=account_keys_preserved,
        logs_truncated=logs_truncated,
        observations=observations,
        expected_call_graph_sha256=expected_call_graph_sha256,
    )


def test_pr137_complete_call_graph_is_review_ready() -> None:
    result = assert_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(),
    )

    assert result.review_ready is True
    assert result.execution_allowed is False
    assert result.blockers == ()
    assert result.state.value == "simulation-cpi-call-graph-review-ready"
    assert RAYDIUM_PROGRAM in result.observed_program_ids
    assert ORCA_PROGRAM in result.expected_route_program_ids


def test_pr137_top_level_only_cannot_pass_without_inner_instructions() -> None:
    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(inner_instructions_present=False),
    )

    assert result.review_ready is False
    assert "INNER_INSTRUCTIONS_MISSING" in result.blockers


def test_pr137_rejects_unknown_cpi_program() -> None:
    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(
            PR137InstructionObservation(
                program_id=UNKNOWN_PROGRAM,
                instruction_path=(1, 9),
                source="inner",
                semantic_family="unknown-helper",
            )
        ),
    )

    assert result.review_ready is False
    assert f"UNEXPECTED_PROGRAM:{UNKNOWN_PROGRAM}" in result.blockers


def test_pr137_route_label_without_program_attestation_is_invalid() -> None:
    with pytest.raises(PR137CallGraphError):
        PR137RouteProgramIdentity(
            route_segment_id="leg-a",
            label="Raydium",
            program_id="",
            deployment_attestation_sha256=HASH,
        )

    with pytest.raises(PR137CallGraphError):
        PR137RouteProgramIdentity(
            route_segment_id="leg-a",
            label="Raydium",
            program_id=RAYDIUM_PROGRAM,
            deployment_attestation_sha256="not-a-hash",
        )


def test_pr137_missing_planned_route_program_blocks() -> None:
    observations = tuple(
        item for item in _evidence().observations if item.program_id != ORCA_PROGRAM
    )
    evidence = PR137SimulationCallGraphEvidence(
        inner_instructions_requested=True,
        inner_instructions_present=True,
        loaded_addresses_present=True,
        return_data_preserved=True,
        account_keys_preserved=True,
        logs_truncated=False,
        observations=observations,
    )

    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=evidence,
    )

    assert result.review_ready is False
    assert "ROUTE_SEGMENT_PROGRAM_MISSING:leg-b" in result.blockers


def test_pr137_indeterminate_simulation_metadata_fails_closed() -> None:
    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(
            loaded_addresses_present=False,
            return_data_preserved=False,
            account_keys_preserved=False,
            logs_truncated=True,
        ),
    )

    assert result.review_ready is False
    assert "LOADED_ADDRESSES_MISSING" in result.blockers
    assert "RETURN_DATA_NOT_PRESERVED" in result.blockers
    assert "ACCOUNT_KEYS_NOT_PRESERVED" in result.blockers
    assert "SIMULATION_LOGS_TRUNCATED" in result.blockers


def test_pr137_call_graph_hash_is_part_of_permit_evidence() -> None:
    evidence = _evidence()
    expected_hash = evidence.call_graph_sha256

    ok = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(expected_call_graph_sha256=expected_hash),
    )
    bad = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(expected_call_graph_sha256="b" * 64),
    )

    assert ok.review_ready is True
    assert bad.review_ready is False
    assert "CALL_GRAPH_HASH_MISMATCH" in bad.blockers


def test_pr137_system_transfer_requires_semantic_check() -> None:
    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(
            PR137InstructionObservation(
                program_id=SYSTEM_PROGRAM_ID,
                instruction_path=(1, 4),
                source="inner",
                semantic_family="system-transfer",
                transfer_checked=False,
            )
        ),
    )

    assert result.review_ready is False
    assert "SYSTEM_TRANSFER_WITHOUT_SEMANTIC_CHECK" in result.blockers


def test_pr137_token_2022_hook_requires_extension_policy() -> None:
    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=_expected(),
        evidence=_evidence(
            PR137InstructionObservation(
                program_id=TOKEN_2022_PROGRAM_ID,
                instruction_path=(1, 5),
                source="inner",
                semantic_family="token-2022-transfer",
                transfer_checked=False,
            )
        ),
    )

    assert result.review_ready is False
    assert "TOKEN_2022_TRANSFER_WITHOUT_EXTENSION_POLICY" in result.blockers
