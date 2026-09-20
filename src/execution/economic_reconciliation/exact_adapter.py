"""Adapter from the merged PR-036 exact-simulation evidence to PR-037."""

from __future__ import annotations

from typing import Mapping, Any
from src.execution.state_evidence_pr115 import (
    PR115DecodePolicy,
    build_pr115_proof_from_report,
)
from .mega_pr02_proof import (
    RawAccountBinding,
    RawSimulationStateProof,
    decoded_observation_hash,
    decoded_marginfi_hash,
)

from src.execution.exact_simulation import FinalizedSimulation

from .models import (
    AssetKey,
    AssetQuantity,
    FeeEvidence,
    MarginfiRepaymentObservation,
    NativeObservation,
    ReconciliationEvidence,
    TokenObservation,
    NativeState,
    TokenState,
)

MICRO_LAMPORTS_PER_LAMPORT = 1_000_000


def evidence_from_raw_simulation(
    finalized: FinalizedSimulation,
    *,
    pre_state_accounts: tuple[Mapping[str, Any] | None, ...],
    pre_state_slot: int,
    policy: PR115DecodePolicy,
    settlement_asset: AssetKey,
    assets: tuple[AssetKey, ...],
    payer: str,
    principal: int,
) -> tuple[ReconciliationEvidence, RawSimulationStateProof, str]:
    """Decode finalizer-owned accounts; no caller profit or repayment accepted.

    The current reconciler requires one coherent state-pair slot. Refuse a
    looser capture instead of relabelling pre-state as final simulation state.
    This adapter uses the explicit convention that raw payer delta includes fees.
    External qualification must prove that convention for the selected backend.
    """
    report = finalized.report
    finalized.validate_submission(
        permit_message_hash=report.message_hash,
        submission_message_hash=report.message_hash,
        serialized_submission_message=finalized.compiled.serialized_message,
    )
    if pre_state_slot != report.final.slot:
        raise ValueError("INDETERMINATE_STATE_PAIR")
    if policy.marginfi is None or policy.marginfi.principal != principal:
        raise ValueError("planner principal is not bound to decoder context")
    if policy.marginfi.authority != payer:
        raise ValueError("decoder authority differs from compiled payer")
    proof = build_pr115_proof_from_report(
        report,
        pre_state_accounts=pre_state_accounts,
        pre_state_slot=pre_state_slot,
        policy=policy,
    )
    repayment = proof.marginfi_repayment
    if repayment is None:
        raise ValueError("raw MarginFi repayment state missing")
    asset_map = {(a.mint, a.token_program): a for a in assets}
    if len(asset_map) != len(assets):
        raise ValueError("duplicate approved asset")
    expected_asset = AssetKey(
        repayment.mint, repayment.token_program, repayment.mint_decimals
    )
    if (
        expected_asset != settlement_asset
        or asset_map.get((expected_asset.mint, expected_asset.token_program))
        != expected_asset
    ):
        raise ValueError("raw bank asset differs from approved settlement asset")
    posts = report.final.returned_accounts
    if posts is None:
        raise ValueError("raw simulation missing")

    def required_accounts(values):
        result: dict[str, Mapping[str, Any]] = {}
        for address, account in zip(report.monitored_accounts, values):
            if account is None:
                raise ValueError("raw account missing without approved lifecycle")
            result[address] = account
        return result

    post_by_address = required_accounts(posts)
    pre_by_address = required_accounts(pre_state_accounts)
    native = tuple(
        NativeObservation(
            item.address,
            NativeState(
                item.address,
                str(pre_by_address[item.address]["owner"]),
                item.pre_lamports,
                pre_state_slot,
            ),
            NativeState(
                item.address,
                str(post_by_address[item.address]["owner"]),
                item.post_lamports,
                report.final.slot,
            ),
            include_in_wallet_delta=item.address == payer,
        )
        for item in proof.native_deltas
    )
    tokens = []
    for item in proof.token_deltas:
        before, after = pre_by_address[item.address], post_by_address[item.address]
        asset = asset_map.get((item.mint, str(after["owner"])))
        if asset is None:
            raise ValueError("decoded token is outside approved asset registry")
        tokens.append(
            TokenObservation(
                item.address,
                item.authority,
                asset,
                TokenState(
                    item.address,
                    str(before["owner"]),
                    item.authority,
                    asset,
                    item.pre_amount,
                    before["lamports"],
                    pre_state_slot,
                ),
                TokenState(
                    item.address,
                    str(after["owner"]),
                    item.authority,
                    asset,
                    item.post_amount,
                    after["lamports"],
                    report.final.slot,
                ),
                include_in_wallet_delta=item.authority == payer
                and item.address != repayment.vault,
            )
        )
    marginfi = MarginfiRepaymentObservation(
        repayment.program_id,
        repayment.margin_account,
        repayment.bank,
        repayment.vault,
        expected_asset,
        report.final.slot,
        repayment.program_id,
        repayment.program_id,
        repayment.program_id,
        repayment.program_id,
        repayment.pre_flags,
        repayment.post_flags,
        repayment.pre_target_liability_shares,
        repayment.post_target_liability_shares,
        principal,
        principal + repayment.conservative_fee_amount,
        repayment.pre_vault_amount,
        repayment.post_vault_amount,
    )
    evidence = evidence_from_exact_simulation(
        finalized,
        settlement_asset=settlement_asset,
        native=native,
        tokens=tuple(tokens),
        marginfi=marginfi,
        decoded_account_hashes=report.final.returned_account_hashes,
        required_accounts=tuple(item.address for item in native)
        + tuple(item.address for item in tokens),
    )
    decoded_hashes = {item.address: decoded_observation_hash(item) for item in native}
    decoded_hashes.update(
        {item.address: decoded_observation_hash(item) for item in tokens}
    )
    for address in (repayment.margin_account, repayment.bank):
        decoded_hashes[address] = decoded_marginfi_hash(marginfi)
    raw = RawSimulationStateProof(
        report.message_hash,
        report.final.response_hash,
        report.final.logs_hash,
        report.final.slot,
        tuple(
            RawAccountBinding(
                address,
                str(post_by_address[address]["owner"]),
                report.final.slot,
                digest,
                decoded_hashes.get(address, proof.raw_evidence_hash),
            )
            for address, account, digest in zip(
                report.monitored_accounts, posts, report.final.returned_account_hashes
            )
        ),
    )
    return evidence, raw, proof.raw_evidence_hash


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
