"""Aggregate data-plane dependencies into fail-closed readiness evidence."""

from __future__ import annotations

from .common import DataPlaneReason, ReadinessState, non_negative_int
from .oracle import OracleDecision
from .readiness import ReadinessReport
from .rpc import RpcConsistencyDecision


class DataPlaneReadinessAggregator:
    def evaluate(
        self,
        *,
        rpc: RpcConsistencyDecision,
        websocket: ReadinessReport,
        oracle: OracleDecision,
        detector_inflight: int,
        detector_limit: int,
    ) -> ReadinessReport:
        non_negative_int(detector_inflight, "detector_inflight")
        if detector_limit <= 0:
            raise ValueError("detector_limit must be positive")
        reasons: list[str] = []
        if not rpc.accepted:
            reasons.append(rpc.reason.value)
        if not websocket.ready:
            reasons.extend(websocket.reasons or (DataPlaneReason.DEGRADED.value,))
        if not oracle.accepted:
            reasons.append(oracle.reason.value)
        if detector_inflight >= detector_limit:
            reasons.append(DataPlaneReason.BACKPRESSURE.value)
        state = ReadinessState.NOT_READY if reasons else ReadinessState.READY
        return ReadinessReport.build(
            state,
            reasons,
            {
                "rpc_evidence_hash": rpc.evidence_hash,
                "websocket_evidence_hash": websocket.evidence_hash,
                "oracle_evidence_hash": oracle.evidence_hash,
                "detector_inflight": detector_inflight,
                "detector_limit": detector_limit,
            },
        )
