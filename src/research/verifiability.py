"""RND-03: federated-learning and verifiable-computation experiment records."""

from __future__ import annotations

from dataclasses import dataclass

from .common import (
    ResearchFailure,
    require_id,
    require_nonnegative,
    require_positive,
    require_sha256,
)


@dataclass(frozen=True, slots=True)
class FederatedExperiment:
    experiment_id: str
    dataset_sha256: str
    consent_sha256: str
    threat_model_sha256: str
    aggregator_sha256: str
    participant_count: int
    communication_bytes: int
    centralized_metric_ppm: int
    federated_metric_ppm: int
    malicious_update_bounded: bool
    raw_private_data_exfiltrated: bool = False

    def __post_init__(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        for field_name in (
            "dataset_sha256",
            "consent_sha256",
            "threat_model_sha256",
            "aggregator_sha256",
        ):
            require_sha256(getattr(self, field_name), field_name)
        require_positive(self.participant_count, "participant_count")
        require_nonnegative(self.communication_bytes, "communication_bytes")
        require_nonnegative(self.centralized_metric_ppm, "centralized_metric_ppm")
        require_nonnegative(self.federated_metric_ppm, "federated_metric_ppm")
        if self.raw_private_data_exfiltrated:
            raise ResearchFailure(
                "FEDERATED_RAW_DATA_EXFILTRATION",
                stage="federated-learning",
                description="raw private data crossed the declared boundary",
            )
        if not self.malicious_update_bounded:
            raise ResearchFailure(
                "FEDERATED_POISONING_BOUND_MISSING",
                stage="federated-learning",
                description="malicious participant updates are not bounded",
            )


@dataclass(frozen=True, slots=True)
class VerifiabilityPrototype:
    prototype_id: str
    statement_sha256: str
    circuit_sha256: str
    public_inputs_sha256: str
    verifier_sha256: str
    proof_sha256: str
    prover_us: int
    verifier_us: int
    proof_bytes: int
    prover_cost_microunits: int
    proves_source_data_truth: bool = False

    def __post_init__(self) -> None:
        require_id(self.prototype_id, "prototype_id")
        for field_name in (
            "statement_sha256",
            "circuit_sha256",
            "public_inputs_sha256",
            "verifier_sha256",
            "proof_sha256",
        ):
            require_sha256(getattr(self, field_name), field_name)
        for field_name in (
            "prover_us",
            "verifier_us",
            "proof_bytes",
            "prover_cost_microunits",
        ):
            require_nonnegative(getattr(self, field_name), field_name)
        if self.proves_source_data_truth:
            raise ValueError("valid computation proof cannot assert market input truth")


__all__ = ["FederatedExperiment", "VerifiabilityPrototype"]
