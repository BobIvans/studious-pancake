"""PR-176 / PROOF-01: replayable solver certificates."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from .core import Mega802Error, stable_hash


@dataclass(frozen=True, slots=True)
class SolverCertificate:
    certificate_id: str
    selected_id: str
    constraint_hash: str
    objective_hash: str
    rejected: tuple[tuple[str, str], ...]


def build_solver_certificate(
    *, selected_id: str, constraints: Mapping[str, int | str | bool],
    objectives: Mapping[str, int], rejected: Mapping[str, str],
) -> SolverCertificate:
    constraint_hash = stable_hash(dict(sorted(constraints.items())))
    objective_hash = stable_hash(dict(sorted(objectives.items())))
    rejected_rows = tuple(sorted(rejected.items()))
    certificate_id = stable_hash(
        {"selected": selected_id, "constraints": constraint_hash,
         "objectives": objective_hash, "rejected": rejected_rows}
    )
    return SolverCertificate(
        certificate_id, selected_id, constraint_hash, objective_hash, rejected_rows
    )


def trace_constraint_bindings(
    constraints: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (key, stable_hash(value)) for key, value in sorted(constraints.items())
    )


def explain_candidate_rejection(
    candidate_id: str, reasons: Sequence[str]
) -> tuple[str, tuple[str, ...]]:
    rows = tuple(sorted(set(reasons)))
    if not rows:
        raise Mega802Error("REJECTION_REASON_REQUIRED")
    return candidate_id, rows


def verify_certificate_replay(
    certificate: SolverCertificate, *,
    selected_id: str, constraints: Mapping[str, int | str | bool],
    objectives: Mapping[str, int], rejected: Mapping[str, str],
) -> bool:
    replay = build_solver_certificate(
        selected_id=selected_id, constraints=constraints,
        objectives=objectives, rejected=rejected,
    )
    if replay.certificate_id != certificate.certificate_id:
        raise Mega802Error("CERTIFICATE_REPLAY_MISMATCH")
    return True
