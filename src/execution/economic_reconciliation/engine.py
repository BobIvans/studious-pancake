"""PR-037 economic reconciliation engine.

The engine consumes exact pre/post state. It never parses logs to infer repayment.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from .models import (
    AssetBreakdown,
    AssetKey,
    NATIVE_SOL_ASSET,
    ReconciliationEvidence,
    ReconciliationReason,
    ReconciliationReport,
    ReconciliationStatus,
    RejectedEvidence,
    RepaymentProof,
    TokenValidationPolicy,
)
from .state import StateValidator


class EconomicReconciler:
    def __init__(self, policy: TokenValidationPolicy | None = None):
        self.validator = StateValidator(policy or TokenValidationPolicy())

    def reconcile(self, evidence: ReconciliationEvidence) -> ReconciliationReport:
        repayment = RepaymentProof(False, 0, 0, 0, 0)
        try:
            self.validator.envelope(evidence)
            native = self.validator.unique(evidence.native)
            tokens = self.validator.unique(evidence.tokens)
            missing = sorted(
                set(evidence.required_accounts) - (set(native) | set(tokens))
            )
            if missing:
                raise RejectedEvidence(
                    ReconciliationReason.REQUIRED_ACCOUNT_MISSING, str(missing)
                )

            deltas: dict[AssetKey, int] = defaultdict(int)
            rent_locked = 0
            rent_refunded = 0
            for observation in native.values():
                delta = self.validator.native_delta(observation, evidence.snapshot_slot)
                if observation.include_in_wallet_delta:
                    deltas[NATIVE_SOL_ASSET] += delta
            for observation in tokens.values():
                delta, locked, refunded = self.validator.token_delta(
                    observation, evidence.snapshot_slot
                )
                if observation.include_in_wallet_delta:
                    deltas[observation.asset] += delta
                rent_locked += locked
                rent_refunded += refunded

            for fee in evidence.fees.protocol_fees:
                self.validator.asset(fee.asset)
            repayment = self.validator.repayment(evidence)
            if not repayment.proven:
                return self._report(
                    evidence,
                    ReconciliationStatus.REPAYMENT_FAILED,
                    repayment.reason or ReconciliationReason.REPAYMENT_NOT_PROVEN,
                    False,
                    {},
                    repayment,
                    "MarginFi repayment invariant was not proven from state",
                )
            if evidence.settlement_asset not in deltas:
                raise RejectedEvidence(
                    ReconciliationReason.SETTLEMENT_ASSET_MISSING,
                    "settlement asset not observed",
                )

            breakdowns = self._breakdowns(
                evidence, deltas, rent_locked, rent_refunded, repayment
            )
            for item in breakdowns:
                recomposed = (
                    item.gross
                    - item.protocol_fee
                    - item.network_fee
                    - item.priority_fee
                    - item.tip
                    - item.rent_locked
                    + item.rent_refunded
                )
                if recomposed != item.net:
                    raise RejectedEvidence(
                        ReconciliationReason.DECOMPOSITION_MISMATCH,
                        item.asset.stable_id(),
                    )

            settlement_net = deltas[evidence.settlement_asset]
            if settlement_net >= 0:
                status = ReconciliationStatus.PROVEN_PROFIT
                reason = ReconciliationReason.RECONCILED_PROFIT
            else:
                status = ReconciliationStatus.PROVEN_LOSS
                reason = ReconciliationReason.RECONCILED_LOSS
            return self._report(
                evidence, status, reason, True, deltas, repayment, "", breakdowns
            )
        except RejectedEvidence as exc:
            return self._report(
                evidence,
                ReconciliationStatus.INDETERMINATE,
                exc.reason,
                False,
                {},
                repayment,
                exc.diagnostic,
            )
        except ValueError as exc:
            return self._report(
                evidence,
                ReconciliationStatus.INDETERMINATE,
                ReconciliationReason.ACCOUNT_STATE_MISSING,
                False,
                {},
                repayment,
                str(exc),
            )

    def _breakdowns(
        self,
        evidence: ReconciliationEvidence,
        deltas: dict[AssetKey, int],
        rent_locked: int,
        rent_refunded: int,
        repayment: RepaymentProof,
    ) -> tuple[AssetBreakdown, ...]:
        protocol: dict[AssetKey, int] = defaultdict(int)
        for fee in evidence.fees.protocol_fees:
            protocol[fee.asset] += fee.base_units
        if repayment.protocol_fee:
            protocol[evidence.settlement_asset] += repayment.protocol_fee
        assets = set(deltas) | set(protocol) | {NATIVE_SOL_ASSET}
        result = []
        for asset in sorted(assets):
            net = deltas.get(asset, 0)
            network = evidence.fees.base_network_fee_lamports if asset.is_native else 0
            priority = evidence.fees.priority_fee_lamports if asset.is_native else 0
            tip = evidence.fees.tip_lamports if asset.is_native else 0
            locked = rent_locked if asset.is_native else 0
            refunded = rent_refunded if asset.is_native else 0
            protocol_fee = protocol.get(asset, 0)
            gross = net + protocol_fee + network + priority + tip + locked - refunded
            result.append(
                AssetBreakdown(
                    asset,
                    gross,
                    protocol_fee,
                    network,
                    priority,
                    tip,
                    locked,
                    refunded,
                    net,
                )
            )
        return tuple(result)

    def _report(
        self,
        evidence: ReconciliationEvidence,
        status: ReconciliationStatus,
        reason: ReconciliationReason,
        complete: bool,
        deltas: dict[AssetKey, int],
        repayment: RepaymentProof,
        diagnostic: str,
        breakdowns: tuple[AssetBreakdown, ...] = (),
    ) -> ReconciliationReport:
        settlement_net = deltas.get(evidence.settlement_asset) if complete else None
        payload = {
            "status": status.value,
            "reason": reason.value,
            "complete": complete,
            "message_hash": evidence.simulated_message_hash,
            "slot": evidence.simulation_slot,
            "settlement_asset": evidence.settlement_asset.stable_id(),
            "settlement_net": settlement_net,
            "response_hash": evidence.response_hash,
            "logs_hash": evidence.logs_hash,
            "repayment": {
                "proven": repayment.proven,
                "borrowed": repayment.borrowed,
                "required": repayment.required,
                "vault_return": repayment.vault_return,
                "protocol_fee": repayment.protocol_fee,
            },
            "breakdowns": [
                {
                    "asset": item.asset.stable_id(),
                    "gross": item.gross,
                    "protocol_fee": item.protocol_fee,
                    "network_fee": item.network_fee,
                    "priority_fee": item.priority_fee,
                    "tip": item.tip,
                    "rent_locked": item.rent_locked,
                    "rent_refunded": item.rent_refunded,
                    "net": item.net,
                }
                for item in breakdowns
            ],
            "diagnostic": diagnostic,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ReconciliationReport(
            status,
            reason,
            complete,
            evidence.simulated_message_hash,
            evidence.simulation_slot,
            evidence.settlement_asset,
            settlement_net,
            breakdowns,
            repayment,
            evidence.response_hash,
            evidence.logs_hash,
            digest,
            diagnostic,
        )
