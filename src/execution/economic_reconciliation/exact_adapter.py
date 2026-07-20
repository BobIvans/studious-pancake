"""Adapter from the merged PR-036 exact-simulation evidence to PR-037."""

from __future__ import annotations

from src.execution.exact_simulation import FinalizedSimulation

from .models import (
    AssetKey,
    AssetQuantity,
    FeeEvidence,
    MarginfiRepaymentObservation,
    NativeObservation,
    ReconciliationEvidence,
    TokenObservation,
)

MICRO_LAMPORTS_PER_LAMPORT = 1_000_000


def evidence_from_exact_simulation(
    finalized: FinalizedSimulation,
    *,
    settlement_asset: AssetKey,
    native: tuple[NativeObservation, ...],
    tokens: tuple[TokenObservation, ...],
    marginfi: MarginfiRepaymentObservation | None,
    decoded_account_hashes: tuple[str, ...],
    required_accounts: tuple[str, ...] = (),
    tip_lamports: int = 0,
    protocol_fees: tuple[AssetQuantity, ...] = (),
) -> ReconciliationEvidence:
    """Bind decoded account state to the exact final PR-036 simulation.

    The caller must hash each raw RPC account object with the same canonical JSON
    algorithm used by PR-036, in monitored-account order. A mismatch is rejected
    before any economic interpretation.
    """

    report = finalized.report
    final = report.final
    if finalized.compiled.message_hash != report.message_hash:
        raise ValueError("compiled message hash does not match exact simulation")
    if decoded_account_hashes != final.returned_account_hashes:
        raise ValueError("decoded account snapshots do not match PR-036 hashes")
    if report.fee_context_slot < report.min_context_slot:
        raise ValueError("fee context slot is below minContextSlot")
    if tip_lamports < 0:
        raise ValueError("tip_lamports must be non-negative")

    unit_price = report.final_compute_unit_price or 0
    priority_micro = report.final_compute_unit_limit * unit_price
    priority_fee = (
        priority_micro + MICRO_LAMPORTS_PER_LAMPORT - 1
    ) // MICRO_LAMPORTS_PER_LAMPORT
    if priority_fee > report.final_fee_lamports:
        raise ValueError("derived priority fee exceeds final fee quote")
    base_fee = report.final_fee_lamports - priority_fee

    return ReconciliationEvidence(
        expected_message_hash=finalized.compiled.message_hash,
        simulated_message_hash=report.message_hash,
        simulation_slot=final.slot,
        snapshot_slot=final.slot,
        min_context_slot=report.min_context_slot,
        simulation_succeeded=True,
        response_hash=final.response_hash,
        logs_hash=final.logs_hash,
        settlement_asset=settlement_asset,
        native=native,
        tokens=tokens,
        fees=FeeEvidence(base_fee, priority_fee, tip_lamports, protocol_fees),
        marginfi=marginfi,
        required_accounts=required_accounts or report.monitored_accounts,
    )


__all__ = ["evidence_from_exact_simulation"]
