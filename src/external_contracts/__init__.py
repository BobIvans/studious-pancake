"""Pinned external contract provenance and fail-closed admission."""

from src.external_contracts.admission import (
    RuntimeAdmissionReport,
    evaluate_runtime_admission,
)
from src.external_contracts.drift import DriftReport, detect_drift
from src.external_contracts.registry import (
    ExternalContractError,
    ExternalContractRegistry,
)

__all__ = [
    "DriftReport",
    "ExternalContractError",
    "ExternalContractRegistry",
    "RuntimeAdmissionReport",
    "detect_drift",
    "evaluate_runtime_admission",
]
