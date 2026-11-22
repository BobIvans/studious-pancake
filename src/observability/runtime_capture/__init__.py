"""OCA-W10: runtime event capture for supported paper/shadow routes."""

from .capture import (
    PRODUCER_CODE_VERSION,
    CaptureReceipt,
    RuntimeCaptureAdapter,
    SCHEMA,
    default_vertical_adapter,
)
from .coverage import COVERAGE_SCHEMA, coverage_matrix
from .vertical import VERTICAL_STAGES, run_vertical

__all__ = [
    "COVERAGE_SCHEMA",
    "CaptureReceipt",
    "PRODUCER_CODE_VERSION",
    "RuntimeCaptureAdapter",
    "SCHEMA",
    "VERTICAL_STAGES",
    "coverage_matrix",
    "default_vertical_adapter",
    "run_vertical",
]
