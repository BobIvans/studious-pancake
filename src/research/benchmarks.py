"""RND-02/RND-03 reproducible frontier benchmarks for AGG-14."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from .common import (
    ResearchFailure,
    ResearchOutcome,
    hash_json,
    require_id,
    require_nonnegative,
    require_positive,
    require_sha256,
    require_text,
)


class BenchmarkClass(StrEnum):
    CPU = "cpu"
    CLASSICAL = "classical"
    QUANTUM_SIMULATOR = "quantum-simulator"
    QUANTUM_HARDWARE = "quantum-hardware"
    QUANTUM_INSPIRED = "quantum-inspired"
    GPU = "gpu"
    FPGA = "fpga"
    ASIC = "asic"
    FEDERATED = "federated"
    ZK = "zk"


@dataclass(frozen=True, slots=True)
class BenchmarkMeasurement:
    measurement_id: str
    backend: BenchmarkClass
    problem_sha256: str
    dataset_sha256: str
    result_sha256: str
    feasible: bool
    preparation_us: int
    transfer_us: int
    queue_us: int
    compute_us: int
    verification_us: int
    cost_microunits: int
    memory_peak_bytes: int
    compute_budget_units: int

    def __post_init__(self) -> None:
        require_id(self.measurement_id, "measurement_id")
        require_sha256(self.problem_sha256, "problem_sha256")
        require_sha256(self.dataset_sha256, "dataset_sha256")
        require_sha256(self.result_sha256, "result_sha256")
        for field_name in (
            "preparation_us",
            "transfer_us",
            "queue_us",
            "compute_us",
            "verification_us",
            "cost_microunits",
            "memory_peak_bytes",
        ):
            require_nonnegative(getattr(self, field_name), field_name)
        require_positive(self.compute_budget_units, "compute_budget_units")

    @property
    def end_to_end_us(self) -> int:
        return (
            self.preparation_us
            + self.transfer_us
            + self.queue_us
            + self.compute_us
            + self.verification_us
        )

    @property
    def identity_sha256(self) -> str:
        return hash_json("agg14/benchmark-measurement/v1", asdict(self))


@dataclass(frozen=True, slots=True)
class ComparativeBenchmark:
    experiment_id: str
    baseline: BenchmarkMeasurement
    challenger: BenchmarkMeasurement
    outcome: ResearchOutcome
    comparable: bool
    exact_result_equivalent: bool
    latency_delta_us: int
    cost_delta_microunits: int
    notes: str = ""

    def __post_init__(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        if self.comparable:
            if self.baseline.problem_sha256 != self.challenger.problem_sha256:
                raise ValueError("comparable benchmark must use identical problem")
            if self.baseline.dataset_sha256 != self.challenger.dataset_sha256:
                raise ValueError("comparable benchmark must use identical dataset")
            if self.baseline.compute_budget_units != self.challenger.compute_budget_units:
                raise ValueError("comparable benchmark must use equal compute budget")

    @property
    def reproducible_sha256(self) -> str:
        return hash_json("agg14/comparative-benchmark/v1", asdict(self))


def compare_measurements(
    *,
    experiment_id: str,
    baseline: BenchmarkMeasurement,
    challenger: BenchmarkMeasurement,
    require_exact_result: bool = True,
) -> ComparativeBenchmark:
    comparable = (
        baseline.problem_sha256 == challenger.problem_sha256
        and baseline.dataset_sha256 == challenger.dataset_sha256
        and baseline.compute_budget_units == challenger.compute_budget_units
    )
    exact = baseline.result_sha256 == challenger.result_sha256
    if not comparable:
        outcome = ResearchOutcome.BLOCKED
    elif not challenger.feasible or (require_exact_result and not exact):
        outcome = ResearchOutcome.NEGATIVE
    elif challenger.end_to_end_us < baseline.end_to_end_us:
        outcome = ResearchOutcome.POSITIVE
    else:
        outcome = ResearchOutcome.NEGATIVE
    return ComparativeBenchmark(
        experiment_id=experiment_id,
        baseline=baseline,
        challenger=challenger,
        outcome=outcome,
        comparable=comparable,
        exact_result_equivalent=exact,
        latency_delta_us=challenger.end_to_end_us - baseline.end_to_end_us,
        cost_delta_microunits=challenger.cost_microunits - baseline.cost_microunits,
    )


@dataclass(frozen=True, slots=True)
class QuboBenchmark:
    benchmark: ComparativeBenchmark
    formulation_sha256: str
    penalty_sha256: str
    decoded_feasible: bool
    exact_economics_rechecked: bool
    quantum_advantage_claimed: bool = False

    def __post_init__(self) -> None:
        require_sha256(self.formulation_sha256, "formulation_sha256")
        require_sha256(self.penalty_sha256, "penalty_sha256")
        if self.benchmark.baseline.backend not in {
            BenchmarkClass.CPU,
            BenchmarkClass.CLASSICAL,
        }:
            raise ValueError("QUBO benchmark requires classical baseline")
        if not self.decoded_feasible or not self.exact_economics_rechecked:
            if self.benchmark.outcome is ResearchOutcome.POSITIVE:
                raise ValueError("infeasible/unverified QUBO result cannot be positive")
        if self.quantum_advantage_claimed:
            raise ValueError("AGG-14 does not infer quantum advantage from one benchmark")


@dataclass(frozen=True, slots=True)
class QuantumModelExperiment:
    experiment_id: str
    classical: BenchmarkMeasurement
    candidate: BenchmarkMeasurement
    split_sha256: str
    measured_metric_name: str
    classical_metric_ppm: int
    candidate_metric_ppm: int
    hardware_result: bool
    paper_result_imported: bool = False

    def __post_init__(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        require_sha256(self.split_sha256, "split_sha256")
        require_text(self.measured_metric_name, "measured_metric_name")
        require_nonnegative(self.classical_metric_ppm, "classical_metric_ppm")
        require_nonnegative(self.candidate_metric_ppm, "candidate_metric_ppm")
        if self.classical.dataset_sha256 != self.candidate.dataset_sha256:
            raise ValueError("model experiment must use same holdout dataset")
        if self.paper_result_imported:
            raise ValueError("paper accuracy cannot be used as measured local result")


@dataclass(frozen=True, slots=True)
class AccelerationBenchmark:
    benchmark: ComparativeBenchmark
    kernel_sha256: str
    integer_vectors_sha256: str
    hardware_purchased_by_workflow: bool = False

    def __post_init__(self) -> None:
        require_sha256(self.kernel_sha256, "kernel_sha256")
        require_sha256(self.integer_vectors_sha256, "integer_vectors_sha256")
        if self.hardware_purchased_by_workflow:
            raise ValueError("research workflow cannot purchase hardware")
        if not self.benchmark.exact_result_equivalent:
            raise ValueError("accelerator must preserve exact result vectors")


__all__ = [
    "AccelerationBenchmark",
    "BenchmarkClass",
    "BenchmarkMeasurement",
    "ComparativeBenchmark",
    "QuboBenchmark",
    "QuantumModelExperiment",
    "compare_measurements",
]
