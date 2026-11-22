"""OCA-W2: deterministic OperationEpisode projection (read-only over canonical owners)."""

from .projection import SCHEMA, build_operation_episodes

__all__ = ["SCHEMA", "build_operation_episodes"]
