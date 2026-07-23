"""Compatibility import surface for PR-202 live-boundary evidence."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_impl: Any = import_module("src.live_boundary.pr202_isolated_signer_settlement")

AckStatus = _impl.AckStatus
IsolatedSignerBoundaryEvidence = _impl.IsolatedSignerBoundaryEvidence
PermitConsumption = _impl.PermitConsumption
PermitUseRequest = _impl.PermitUseRequest
PR202EvidenceError = _impl.PR202EvidenceError
ReviewedPermit = _impl.ReviewedPermit
SettlementEvidence = _impl.SettlementEvidence
SettlementStatus = _impl.SettlementStatus
SQLitePermitAuthority = _impl.SQLitePermitAuthority
SubmissionIntent = _impl.SubmissionIntent
TransportAck = _impl.TransportAck
TransportKind = _impl.TransportKind
pr202_readiness_report = _impl.pr202_readiness_report

__all__ = [
    "AckStatus",
    "IsolatedSignerBoundaryEvidence",
    "PermitConsumption",
    "PermitUseRequest",
    "PR202EvidenceError",
    "ReviewedPermit",
    "SettlementEvidence",
    "SettlementStatus",
    "SQLitePermitAuthority",
    "SubmissionIntent",
    "TransportAck",
    "TransportKind",
    "pr202_readiness_report",
]
