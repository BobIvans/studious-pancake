"""Static post-simulation decoder for the AGG-03 Jupiter Lend + Slumlord profile.

The decoder consumes only the exact simulator-owned post-state plus a same-slot
pre-state snapshot. It does not fetch network state, sign, submit, or trust
caller-supplied PnL. Deployment admission remains external evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.execution.economic_reconciliation.exact_adapter import (
    evidence_from_exact_simulation,
)
from src.execution.economic_reconciliation.models import (
    AssetKey,
    NativeObservation,
    NativeState,
    TokenObservation,
    TokenState,
)
from src.execution.financing_evidence import (
    FinancingRepaymentBundle,
    FinancingRepaymentEvidence,
    RepaymentDecision,
    validate_financing_repayment,
)
from src.execution.state_evidence_pr115 import (
    PR115DecodePolicy,
    PR115OpaqueMutableAccountBinding,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    build_pr115_proof_from_report,
    decode_pr115_account_data,
)
from src.lending.agg03_financing_ports import (
    JupiterLendFinancingPort,
    JupiterLendFinancingSnapshot,
    SlumlordFinancingPort,
    SlumlordFinancingSnapshot,
)
from src.lending.financing import FinancingEvidence, FinancingRole
from src.lending.financing_planner_adapter import FinancingPlannerSnapshot
from src.lending.jupiter_lend import (
    JUPITER_FLASHLOAN_ADMIN_PDA,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    decode_flashloan_admin_state,
)
from src.lending.slumlord import SLUMLORD_PDA, SLUMLORD_PROGRAM_ID, SlumlordReserveState
from src.paper_shadow.atomic_vertical import (
    AtomicVerticalCandidate,
    DecodedFinancingEconomics,
)
from src.execution.exact_simulation import FinalizedSimulation


DECODER_CLOSURE_PATHS = (
    "src/execution/agg03_financing_decoder.py",
    "src/execution/financing_evidence.py",
    "src/execution/state_evidence_pr115.py",
    "src/execution/economic_reconciliation/exact_adapter.py",
    "src/execution/economic_reconciliation/engine.py",
    "src/execution/economic_reconciliation/models.py",
    "src/execution/economic_reconciliation/state.py",
    "src/lending/agg03_financing_ports.py",
    "src/lending/financing.py",
    "src/lending/financing_planner_adapter.py",
    "src/lending/jupiter_lend.py",
    "src/lending/slumlord.py",
)


def decoder_artifact_sha256(root: str | Path | None = None) -> str:
    """Hash the deterministic installed decoder dependency closure."""

    base = (
        Path(root).resolve()
        if root is not None
        else Path(__file__).resolve().parents[2]
    )
    digest = hashlib.sha256()
    for relative in DECODER_CLOSURE_PATHS:
        path = base / relative
        raw = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "little"))
        digest.update(hashlib.sha256(raw).digest())
    return digest.hexdigest()


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def financing_pre_state_sha256(
    addresses: Sequence[str],
    values: Sequence[Mapping[str, Any] | None],
) -> str:
    """Commit to the complete ordered raw pre-state set used by the decoder."""

    normalized_addresses = tuple(str(address) for address in addresses)
    if len(normalized_addresses) != len(values):
        raise ValueError("FINANCING_ACCOUNT_SET_MISMATCH")
    return _hash(
        {
            "monitored_accounts": normalized_addresses,
            "accounts": tuple(values),
        }
    )


def require_financing_pre_state_commitment(
    expected_sha256: str | None,
    addresses: Sequence[str],
    values: Sequence[Mapping[str, Any] | None],
) -> None:
    if (
        expected_sha256 is None
        or financing_pre_state_sha256(addresses, values) != expected_sha256
    ):
        raise ValueError("FINANCING_PRE_STATE_HASH_MISMATCH")


def validate_financing_writable_coverage(
    monitored_accounts: Sequence[str],
    instructions: Sequence[Any],
) -> tuple[str, ...]:
    monitored = {str(address) for address in monitored_accounts}
    writable = {
        str(meta.pubkey)
        for instruction in instructions
        for meta in instruction.accounts
        if meta.is_writable
    }
    missing = tuple(sorted(writable.difference(monitored)))
    if missing:
        raise ValueError(
            "FINANCING_WRITABLE_ACCOUNT_NOT_MONITORED:" + ",".join(missing)
        )
    return tuple(sorted(writable))


def _account_map(
    addresses: Sequence[str],
    values: Sequence[Mapping[str, Any] | None],
) -> dict[str, Mapping[str, Any]]:
    if len(addresses) != len(values):
        raise ValueError("FINANCING_ACCOUNT_SET_MISMATCH")
    result: dict[str, Mapping[str, Any]] = {}
    for address, value in zip(addresses, values):
        if value is None:
            raise ValueError("FINANCING_ACCOUNT_MISSING")
        result[address] = value
    return result


def _owner(raw: Mapping[str, Any]) -> str:
    value = raw.get("owner")
    if not isinstance(value, str) or not value:
        raise ValueError("FINANCING_ACCOUNT_OWNER_MISSING")
    return value


def _lamports(raw: Mapping[str, Any]) -> int:
    value = raw.get("lamports")
    if type(value) is not int or value < 0:
        raise ValueError("FINANCING_ACCOUNT_LAMPORTS_INVALID")
    return value


def _token_amount(raw: Mapping[str, Any]) -> int:
    if _owner(raw) != SPL_TOKEN_PROGRAM_ID:
        raise ValueError("FINANCING_TOKEN_OWNER_MISMATCH")
    data = decode_pr115_account_data(raw.get("data"))
    if len(data) != 165 or data[108] != 1:
        raise ValueError("FINANCING_TOKEN_ACCOUNT_LAYOUT_INVALID")
    return int.from_bytes(data[64:72], "little")


@dataclass(frozen=True, slots=True)
class _ExactValidator:
    lender_id: str
    program_id: str
    deployment_generation: int
    decoder_identity: str

    def validate(self, evidence: FinancingRepaymentEvidence) -> bool:
        return (
            evidence.debt_before_base_units > 0
            and evidence.debt_after_base_units == 0
            and evidence.required_repayment_base_units
            >= evidence.debt_before_base_units
            and evidence.observed_repayment_base_units
            >= evidence.required_repayment_base_units
        )


class JupiterLendSlumlordRepaymentDecoder:
    """Decode the exact AGG-03 primary + rent obligations from simulator state."""

    def __init__(
        self,
        primary_evidence: FinancingEvidence,
        rent_evidence: FinancingEvidence,
    ) -> None:
        self.primary_evidence = primary_evidence
        self.rent_evidence = rent_evidence
        self.primary_port = JupiterLendFinancingPort(primary_evidence)
        self.rent_port = SlumlordFinancingPort(rent_evidence)
        self.lender_id = primary_evidence.lender_id
        self.program_id = primary_evidence.program_id
        self.deployment_generation = primary_evidence.deployment_generation
        self.auxiliary_identities = (
            (
                rent_evidence.lender_id,
                rent_evidence.program_id,
                rent_evidence.deployment_generation,
            ),
        )

    def decode(
        self,
        finalized: FinalizedSimulation,
        candidate: AtomicVerticalCandidate,
    ) -> DecodedFinancingEconomics:
        request = candidate.request
        primary_snapshot = request.financing_snapshot
        rent_snapshot = request.rent_financing_snapshot
        if type(primary_snapshot) is not FinancingPlannerSnapshot:
            raise ValueError("FINANCING_PRIMARY_PLANNER_SNAPSHOT_REQUIRED")
        if type(rent_snapshot) is not FinancingPlannerSnapshot:
            raise ValueError("FINANCING_RENT_PLANNER_SNAPSHOT_REQUIRED")
        if type(primary_snapshot.protocol_snapshot) is not JupiterLendFinancingSnapshot:
            raise ValueError("JUPITER_LEND_SNAPSHOT_REQUIRED")
        if type(rent_snapshot.protocol_snapshot) is not SlumlordFinancingSnapshot:
            raise ValueError("SLUMLORD_SNAPSHOT_REQUIRED")
        if candidate.attempt_id is None or candidate.attempt_generation is None:
            raise ValueError("FINANCING_ATTEMPT_IDENTITY_REQUIRED")

        report = finalized.report
        pre_values = candidate.financing_pre_state_accounts
        if pre_values is None or candidate.financing_pre_state_slot is None:
            raise ValueError("FINANCING_PRE_STATE_REQUIRED")
        if candidate.financing_pre_state_slot != report.final.slot:
            raise ValueError("FINANCING_SAME_SLOT_STATE_PAIR_REQUIRED")
        post_values = report.final.returned_accounts
        if post_values is None:
            raise ValueError("FINANCING_POST_STATE_REQUIRED")

        addresses = tuple(report.monitored_accounts)
        writable_accounts = set(
            validate_financing_writable_coverage(
                addresses,
                finalized.compiled.instructions,
            )
        )
        require_financing_pre_state_commitment(
            request.provider_account_snapshot_hash,
            addresses,
            pre_values,
        )
        pre = _account_map(addresses, pre_values)
        post = _account_map(addresses, post_values)

        primary_protocol = primary_snapshot.protocol_snapshot
        rent_protocol = rent_snapshot.protocol_snapshot
        admin_address = str(JUPITER_FLASHLOAN_ADMIN_PDA)
        rent_address = str(SLUMLORD_PDA)
        if admin_address not in pre or rent_address not in pre:
            raise ValueError("FINANCING_PROTOCOL_STATE_NOT_MONITORED")
        if (
            _owner(pre[admin_address])
            != str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID)
            or _owner(post[admin_address])
            != str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID)
        ):
            raise ValueError("JUPITER_LEND_ADMIN_OWNER_MISMATCH")
        if (
            _owner(pre[rent_address]) != str(SLUMLORD_PROGRAM_ID)
            or _owner(post[rent_address]) != str(SLUMLORD_PROGRAM_ID)
        ):
            raise ValueError("SLUMLORD_OWNER_MISMATCH")

        pre_admin = decode_flashloan_admin_state(
            decode_pr115_account_data(pre[admin_address].get("data"))
        )
        post_admin = decode_flashloan_admin_state(
            decode_pr115_account_data(post[admin_address].get("data"))
        )
        if (
            not pre_admin.status
            or not post_admin.status
            or pre_admin.is_flashloan_active
            or post_admin.is_flashloan_active
            or pre_admin.active_flashloan_amount != 0
            or post_admin.active_flashloan_amount != 0
            or pre_admin.flashloan_fee != 0
            or post_admin.flashloan_fee != 0
        ):
            raise ValueError("JUPITER_LEND_FLASHLOAN_STATE_NOT_CLOSED")
        if pre_admin != primary_protocol.admin_state:
            raise ValueError("JUPITER_LEND_PRE_STATE_DIFFERS_FROM_PLANNER_SNAPSHOT")

        reserve_address = str(
            primary_protocol.accounts.flashloan_token_reserves_liquidity
        )
        if reserve_address not in pre or reserve_address not in post:
            raise ValueError("JUPITER_LEND_RESERVE_NOT_MONITORED")
        reserve_before = _token_amount(pre[reserve_address])
        reserve_after = _token_amount(post[reserve_address])
        if reserve_before < request.borrow_amount:
            raise ValueError("JUPITER_LEND_RESERVE_BELOW_PRINCIPAL")
        primary_observed_repayment = reserve_after - (
            reserve_before - request.borrow_amount
        )
        if primary_observed_repayment < request.borrow_amount:
            raise ValueError("JUPITER_LEND_RESERVE_NOT_REPAID")

        pre_rent = SlumlordReserveState(
            address=SLUMLORD_PDA,
            owner=SLUMLORD_PROGRAM_ID,
            lamports=_lamports(pre[rent_address]),
            data=decode_pr115_account_data(pre[rent_address].get("data")),
            slot=report.final.slot,
        )
        post_rent = SlumlordReserveState(
            address=SLUMLORD_PDA,
            owner=SLUMLORD_PROGRAM_ID,
            lamports=_lamports(post[rent_address]),
            data=decode_pr115_account_data(post[rent_address].get("data")),
            slot=report.final.slot,
        )
        if pre_rent.loan_active or post_rent.loan_active:
            raise ValueError("SLUMLORD_RENT_OBLIGATION_NOT_CLOSED")
        if pre_rent.lamports < request.rent_borrow_amount:
            raise ValueError("SLUMLORD_RESERVE_BELOW_PRINCIPAL")
        rent_observed_repayment = post_rent.lamports - (
            pre_rent.lamports - request.rent_borrow_amount
        )
        if rent_observed_repayment < request.rent_borrow_amount:
            raise ValueError("SLUMLORD_RENT_OBLIGATION_NOT_CLOSED")
        if (
            pre_rent.lamports != rent_protocol.reserve.lamports
            or pre_rent.data != rent_protocol.reserve.data
            or pre_rent.owner != rent_protocol.reserve.owner
            or pre_rent.address != rent_protocol.reserve.address
        ):
            raise ValueError("SLUMLORD_PRE_STATE_DIFFERS_FROM_PLANNER_SNAPSHOT")

        primary_prepared = self.primary_port.prepare(
            snapshot=primary_protocol,
            amount=request.borrow_amount,
            destination_account=str(request.destination_token_account),
            repayment_source_account=str(request.repayment_source_token_account),
            minimum_terminal_balance=request.leg_b.other_amount_threshold,
            role=FinancingRole.PRIMARY,
        )
        rent_prepared = self.rent_port.prepare(
            snapshot=rent_protocol,
            amount=request.rent_borrow_amount,
            destination_account=str(request.payer),
            repayment_source_account=str(request.payer),
            minimum_terminal_balance=request.rent_borrow_amount,
            role=FinancingRole.RENT,
        )

        # Reconstruct exact Solders instruction order from the planner request
        # rather than accepting decoder-selected instructions. The atomic vertical
        # independently compares obligation digests against planner provenance.
        final_instructions = tuple(finalized.compiled.instructions)
        self.primary_port.finalize(primary_prepared, final_instructions)
        self.rent_port.finalize(rent_prepared, final_instructions)

        primary_raw = FinancingRepaymentEvidence(
            attempt_id=candidate.attempt_id,
            attempt_generation=candidate.attempt_generation,
            message_hash=finalized.compiled.message_hash,
            lender_id=self.primary_evidence.lender_id,
            program_id=self.primary_evidence.program_id,
            deployment_generation=self.primary_evidence.deployment_generation,
            decoder_identity=self.primary_evidence.decoder_identity,
            obligation_digest=primary_prepared.obligation.digest,
            source_evidence_sha256=self.primary_evidence.evidence_sha256,
            asset_id=primary_prepared.obligation.asset_id,
            debt_before_base_units=primary_prepared.obligation.principal_base_units,
            debt_after_base_units=0,
            required_repayment_base_units=(
                primary_prepared.obligation.required_repayment_base_units
            ),
            observed_repayment_base_units=primary_observed_repayment,
            role=FinancingRole.PRIMARY,
        )
        rent_raw = FinancingRepaymentEvidence(
            attempt_id=candidate.attempt_id,
            attempt_generation=candidate.attempt_generation,
            message_hash=finalized.compiled.message_hash,
            lender_id=self.rent_evidence.lender_id,
            program_id=self.rent_evidence.program_id,
            deployment_generation=self.rent_evidence.deployment_generation,
            decoder_identity=self.rent_evidence.decoder_identity,
            obligation_digest=rent_prepared.obligation.digest,
            source_evidence_sha256=self.rent_evidence.evidence_sha256,
            asset_id=rent_prepared.obligation.asset_id,
            debt_before_base_units=rent_prepared.obligation.principal_base_units,
            debt_after_base_units=0,
            required_repayment_base_units=(
                rent_prepared.obligation.required_repayment_base_units
            ),
            observed_repayment_base_units=rent_observed_repayment,
            role=FinancingRole.RENT,
        )
        primary_decision = validate_financing_repayment(
            primary_raw,
            (
                _ExactValidator(
                    self.primary_evidence.lender_id,
                    self.primary_evidence.program_id,
                    self.primary_evidence.deployment_generation,
                    self.primary_evidence.decoder_identity,
                ),
            ),
        )
        rent_decision = validate_financing_repayment(
            rent_raw,
            (
                _ExactValidator(
                    self.rent_evidence.lender_id,
                    self.rent_evidence.program_id,
                    self.rent_evidence.deployment_generation,
                    self.rent_evidence.decoder_identity,
                ),
            ),
        )
        bundle = FinancingRepaymentBundle(
            primary=primary_decision,
            auxiliary=(rent_decision,),
        )

        opaque: list[PR115OpaqueMutableAccountBinding] = []
        for address in addresses:
            owner = _owner(pre[address])
            if owner not in {SYSTEM_PROGRAM_ID, SPL_TOKEN_PROGRAM_ID}:
                opaque.append(PR115OpaqueMutableAccountBinding(address, owner))
        proof = build_pr115_proof_from_report(
            report,
            pre_state_accounts=pre_values,
            pre_state_slot=candidate.financing_pre_state_slot,
            policy=PR115DecodePolicy(
                allow_legacy_spl_token_accounts=True,
                allow_token_2022_accounts=False,
                opaque_mutable_accounts=tuple(opaque),
            ),
        )
        decoded_economic_accounts = {
            item.address for item in proof.native_deltas
        } | {item.address for item in proof.token_deltas}
        missing_economic = sorted(
            address
            for address in writable_accounts
            if _owner(pre[address]) in {SYSTEM_PROGRAM_ID, SPL_TOKEN_PROGRAM_ID}
            and address not in decoded_economic_accounts
        )
        if missing_economic:
            raise ValueError(
                "FINANCING_WRITABLE_ECONOMIC_ACCOUNT_NOT_DECODED:"
                + ",".join(missing_economic)
            )

        assets = {
            (asset.mint, asset.token_program): asset
            for asset in (*candidate.approved_assets, candidate.settlement_asset)
        }
        native = tuple(
            NativeObservation(
                item.address,
                NativeState(
                    item.address,
                    _owner(pre[item.address]),
                    item.pre_lamports,
                    report.final.slot,
                ),
                NativeState(
                    item.address,
                    _owner(post[item.address]),
                    item.post_lamports,
                    report.final.slot,
                ),
                include_in_wallet_delta=item.address == str(request.payer),
            )
            for item in proof.native_deltas
        )
        tokens: list[TokenObservation] = []
        for item in proof.token_deltas:
            owner = _owner(post[item.address])
            asset = assets.get((item.mint, owner))
            if asset is None:
                raise ValueError("FINANCING_TOKEN_OUTSIDE_APPROVED_ASSET_REGISTRY")
            tokens.append(
                TokenObservation(
                    item.address,
                    item.authority,
                    asset,
                    TokenState(
                        item.address,
                        _owner(pre[item.address]),
                        item.authority,
                        asset,
                        item.pre_amount,
                        _lamports(pre[item.address]),
                        report.final.slot,
                    ),
                    TokenState(
                        item.address,
                        owner,
                        item.authority,
                        asset,
                        item.post_amount,
                        _lamports(post[item.address]),
                        report.final.slot,
                    ),
                    include_in_wallet_delta=item.authority == str(request.payer),
                )
            )

        evidence = evidence_from_exact_simulation(
            finalized,
            settlement_asset=candidate.settlement_asset,
            native=native,
            tokens=tuple(tokens),
            marginfi=None,
            decoded_account_hashes=report.final.returned_account_hashes,
            required_accounts=tuple(item.address for item in native)
            + tuple(item.address for item in tokens),
            tip_lamports=candidate.tip_lamports,
            protocol_fees=candidate.protocol_fees,
            financing=bundle,
        )
        return DecodedFinancingEconomics(
            evidence=evidence,
            evidence_hash=_hash(
                {
                    "raw": proof.raw_evidence_hash,
                    "primary": primary_decision.evidence_digest,
                    "rent": rent_decision.evidence_digest,
                    "message": finalized.compiled.message_hash,
                }
            ),
        )


__all__ = [
    "financing_pre_state_sha256",
    "JupiterLendSlumlordRepaymentDecoder",
    "decoder_artifact_sha256",
]
