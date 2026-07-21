from __future__ import annotations

import ast
from pathlib import Path

from src.execution.canonical_domain import (
    DomainRole,
    canonical_qualified_names,
    canonical_symbol,
    quarantined_qualified_names,
    validate_canonical_execution_domain,
)
from src.execution.economic_reconciliation.models import ReconciliationReport
from src.execution.models import SimulationReport
from src.submission.permit_bound import Sender

ROOT = Path(__file__).resolve().parents[2]


SCANNED_MODULES = {
    "src/execution/models.py": "src.execution.models",
    "src/execution/shadow.py": "src.execution.shadow",
    "src/execution/economic_reconciliation/models.py": (
        "src.execution.economic_reconciliation.models"
    ),
    "src/live_canary/models.py": "src.live_canary.models",
    "src/execution/live_control.py": "src.execution.live_control",
    "src/execution/senders/rpc_sender.py": "src.execution.senders.rpc_sender",
    "src/execution/senders/jito_single_sender.py": (
        "src.execution.senders.jito_single_sender"
    ),
    "src/execution/senders/jito_bundle_sender.py": (
        "src.execution.senders.jito_bundle_sender"
    ),
}

WATCHED_BOUNDARY_NAMES = frozenset(
    {
        "SimulationReport",
        "ReconciliationReport",
        "ReconciliationResult",
        "ExecutionReceipt",
        "LiveSubmissionPermit",
        "PermitBoundSender",
        "Sender",
        "RpcTransactionSender",
        "JitoSingleTransactionSender",
        "JitoBundleSender",
    }
)


def _class_definitions(path: str, module: str) -> set[str]:
    source_path = ROOT / path
    if not source_path.exists():
        return set()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    return {
        f"{module}.{node.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name in WATCHED_BOUNDARY_NAMES
    }


def _relative_shadow_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 1
            and node.module == "shadow"
        ):
            imports.update(alias.name for alias in node.names)
    return imports


def test_pr071_has_exactly_one_canonical_owner_per_execution_role() -> None:
    validate_canonical_execution_domain()

    assert (
        canonical_symbol(DomainRole.SIMULATION_REPORT).qualified_name
        == "src.execution.models.SimulationReport"
    )
    assert canonical_symbol(DomainRole.SIMULATION_REPORT).resolve() is SimulationReport

    assert (
        canonical_symbol(DomainRole.RECONCILIATION_REPORT).qualified_name
        == "src.execution.economic_reconciliation.models.ReconciliationReport"
    )
    assert (
        canonical_symbol(DomainRole.RECONCILIATION_REPORT).resolve()
        is ReconciliationReport
    )

    assert (
        canonical_symbol(DomainRole.EXECUTION_RECEIPT).qualified_name
        == "src.execution.canonical_domain.ExecutionReceipt"
    )
    assert canonical_symbol(DomainRole.EXECUTION_RECEIPT).resolve().__name__ == (
        "ExecutionReceipt"
    )

    assert (
        canonical_symbol(DomainRole.SENDER_PROTOCOL).qualified_name
        == "src.submission.permit_bound.Sender"
    )
    assert canonical_symbol(DomainRole.SENDER_PROTOCOL).resolve() is Sender


def test_pr071_legacy_duplicate_boundaries_are_explicitly_quarantined() -> None:
    defined = set().union(
        *(_class_definitions(path, module) for path, module in SCANNED_MODULES.items())
    )
    canonical = canonical_qualified_names()
    quarantined = quarantined_qualified_names()

    assert "src.execution.models.SimulationReport" in defined
    assert "src.execution.shadow.SimulationReport" in defined
    assert "src.execution.shadow.ReconciliationResult" in defined
    assert "src.live_canary.models.ReconciliationResult" in defined
    assert "src.execution.live_control.LiveSubmissionPermit" in defined
    assert "src.execution.live_control.PermitBoundSender" in defined
    assert "src.execution.senders.rpc_sender.RpcTransactionSender" in defined
    assert (
        "src.execution.senders.jito_single_sender.JitoSingleTransactionSender"
        in defined
    )
    assert "src.execution.senders.jito_bundle_sender.JitoBundleSender" in defined

    non_canonical = defined - canonical
    assert non_canonical <= quarantined
    assert canonical.isdisjoint(quarantined)


def test_pr071_transaction_simulator_uses_canonical_report_model() -> None:
    source = (ROOT / "src/execution/transaction_simulator.py").read_text(
        encoding="utf-8"
    )
    shadow_imports = _relative_shadow_imports(source)

    assert "from .models import (" in source
    assert "    SimulationReport," in source
    assert "CanonicalSimulator" in shadow_imports
    assert "SimulationReport" not in shadow_imports


def test_pr071_public_canonical_sender_stack_uses_one_sender_protocol() -> None:
    source = (ROOT / "src/submission/canonical_sender.py").read_text(encoding="utf-8")

    assert "    Sender," in source
    assert "sender: Sender" in source
    assert "build_canonical_submission_stack" in source
    assert "transport_fallback_allowed: bool = False" in source
    assert "duplicate_submission_allowed: bool = False" in source


def test_pr071_live_control_sender_is_quarantined_not_canonical() -> None:
    source = (ROOT / "src/execution/live_control.py").read_text(encoding="utf-8")

    assert "class PermitBoundSender" in source
    assert (
        "src.execution.live_control.PermitBoundSender" in quarantined_qualified_names()
    )
    assert (
        "src.execution.live_control.PermitBoundSender"
        not in canonical_qualified_names()
    )
    assert "class Sender" not in source
