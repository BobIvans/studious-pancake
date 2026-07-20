"""State validation and MarginFi repayment proof for PR-037."""

from __future__ import annotations

import re

from src.config.chain_registry import TOKEN_2022_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS
from src.domain.money import NATIVE_SOL_MINT

from .models import (
    AccountLifecycle,
    AssetKey,
    MARGINFI_ACCOUNT_IN_FLASHLOAN,
    NATIVE_SOL_ASSET,
    NativeObservation,
    ReconciliationEvidence,
    ReconciliationReason,
    RejectedEvidence,
    RepaymentProof,
    TokenObservation,
    TokenState,
    TokenValidationPolicy,
)

_HASH = re.compile(r"[0-9a-f]{64}")


class StateValidator:
    def __init__(self, policy: TokenValidationPolicy):
        self.policy = policy

    def envelope(self, evidence: ReconciliationEvidence) -> None:
        hashes = (
            evidence.expected_message_hash,
            evidence.simulated_message_hash,
            evidence.response_hash,
            evidence.logs_hash,
        )
        if any(not _HASH.fullmatch(value) for value in hashes):
            raise RejectedEvidence(
                ReconciliationReason.EVIDENCE_HASH_INVALID,
                "hash must be lower-case SHA-256",
            )
        if evidence.expected_message_hash != evidence.simulated_message_hash:
            raise RejectedEvidence(
                ReconciliationReason.MESSAGE_HASH_MISMATCH,
                "simulation used another message",
            )
        if not evidence.simulation_succeeded:
            raise RejectedEvidence(
                ReconciliationReason.SIMULATION_FAILED, "simulation did not succeed"
            )
        if (
            evidence.simulation_slot <= 0
            or evidence.snapshot_slot != evidence.simulation_slot
            or evidence.simulation_slot < evidence.min_context_slot
        ):
            raise RejectedEvidence(
                ReconciliationReason.SLOT_MISMATCH,
                "snapshots are not from the accepted slot",
            )
        self.asset(evidence.settlement_asset)

    def native_delta(self, observation: NativeObservation, slot: int) -> int:
        self._lifecycle(
            observation.lifecycle,
            observation.pre is not None,
            observation.post is not None,
        )
        if observation.pre and (
            observation.pre.address != observation.address
            or observation.pre.slot != slot
        ):
            raise RejectedEvidence(
                ReconciliationReason.ACCOUNT_IDENTITY_MISMATCH, observation.address
            )
        if observation.post and (
            observation.post.address != observation.address
            or observation.post.slot != slot
        ):
            raise RejectedEvidence(
                ReconciliationReason.ACCOUNT_IDENTITY_MISMATCH, observation.address
            )
        if (
            observation.pre
            and observation.post
            and observation.pre.owner != observation.post.owner
        ):
            raise RejectedEvidence(
                ReconciliationReason.ACCOUNT_OWNER_CHANGED, observation.address
            )
        return (observation.post.lamports if observation.post else 0) - (
            observation.pre.lamports if observation.pre else 0
        )

    def token_delta(
        self, observation: TokenObservation, slot: int
    ) -> tuple[int, int, int]:
        self.asset(observation.asset)
        self._lifecycle(
            observation.lifecycle,
            observation.pre is not None,
            observation.post is not None,
        )
        for state in (observation.pre, observation.post):
            if state is None:
                continue
            if state.address != observation.address or state.slot != slot:
                raise RejectedEvidence(
                    ReconciliationReason.ACCOUNT_IDENTITY_MISMATCH, observation.address
                )
            if (
                state.program_owner != observation.asset.token_program
                or state.authority != observation.authority
                or state.asset != observation.asset
            ):
                raise RejectedEvidence(
                    ReconciliationReason.TOKEN_METADATA_MISMATCH, observation.address
                )
            self.extensions(state)
        if (
            observation.pre
            and observation.post
            and observation.pre.program_owner != observation.post.program_owner
        ):
            raise RejectedEvidence(
                ReconciliationReason.ACCOUNT_OWNER_CHANGED, observation.address
            )
        locked = (
            observation.post.account_lamports
            if observation.lifecycle is AccountLifecycle.CREATED and observation.post
            else 0
        )
        refunded = (
            observation.pre.account_lamports
            if observation.lifecycle is AccountLifecycle.CLOSED and observation.pre
            else 0
        )
        delta = (observation.post.amount if observation.post else 0) - (
            observation.pre.amount if observation.pre else 0
        )
        return delta, locked, refunded

    def repayment(self, evidence: ReconciliationEvidence) -> RepaymentProof:
        item = evidence.marginfi
        if item is None:
            return RepaymentProof(
                False, 0, 0, 0, 0, ReconciliationReason.MARGINFI_EVIDENCE_MISSING
            )
        if (
            item.slot != evidence.snapshot_slot
            or item.asset != evidence.settlement_asset
        ):
            return RepaymentProof(
                False,
                item.borrowed,
                item.required_repayment,
                0,
                0,
                ReconciliationReason.MARGINFI_STATE_INVALID,
            )
        owners = (
            item.margin_owner_before,
            item.margin_owner_after,
            item.bank_owner_before,
            item.bank_owner_after,
        )
        if any(owner != item.program_id for owner in owners):
            return RepaymentProof(
                False,
                item.borrowed,
                item.required_repayment,
                0,
                0,
                ReconciliationReason.MARGINFI_OWNER_MISMATCH,
            )
        if item.borrowed <= 0 or item.required_repayment < item.borrowed:
            return RepaymentProof(
                False,
                item.borrowed,
                item.required_repayment,
                0,
                0,
                ReconciliationReason.MARGINFI_STATE_INVALID,
            )
        if (
            item.liability_before != 0
            or item.liability_after != 0
            or item.flags_before & MARGINFI_ACCOUNT_IN_FLASHLOAN
            or item.flags_after & MARGINFI_ACCOUNT_IN_FLASHLOAN
        ):
            return RepaymentProof(
                False,
                item.borrowed,
                item.required_repayment,
                0,
                0,
                ReconciliationReason.REPAYMENT_NOT_PROVEN,
            )
        expected_after = item.vault_before - item.borrowed + item.required_repayment
        vault_return = item.vault_after - (item.vault_before - item.borrowed)
        protocol_fee = item.required_repayment - item.borrowed
        if expected_after < 0 or item.vault_after != expected_after:
            return RepaymentProof(
                False,
                item.borrowed,
                item.required_repayment,
                max(0, vault_return),
                protocol_fee,
                ReconciliationReason.MARGINFI_VAULT_MISMATCH,
            )
        return RepaymentProof(
            True, item.borrowed, item.required_repayment, vault_return, protocol_fee
        )

    def asset(self, asset: AssetKey) -> None:
        if asset.is_native:
            return
        if asset.mint == NATIVE_SOL_MINT or asset.token_program not in (
            TOKEN_PROGRAM_ADDRESS,
            TOKEN_2022_PROGRAM_ADDRESS,
        ):
            raise RejectedEvidence(
                ReconciliationReason.TOKEN_PROGRAM_UNSUPPORTED, asset.stable_id()
            )

    def extensions(self, state: TokenState) -> None:
        if state.asset.token_program == TOKEN_PROGRAM_ADDRESS and state.extensions:
            raise RejectedEvidence(
                ReconciliationReason.TOKEN_EXTENSION_UNSUPPORTED, state.address
            )
        unknown = set(state.extensions) - self.policy.token_2022_extensions
        if unknown:
            raise RejectedEvidence(
                ReconciliationReason.TOKEN_EXTENSION_UNSUPPORTED, str(sorted(unknown))
            )

    @staticmethod
    def unique(items):
        result = {}
        for item in items:
            if item.address in result:
                raise RejectedEvidence(
                    ReconciliationReason.DUPLICATE_ACCOUNT, item.address
                )
            result[item.address] = item
        return result

    @staticmethod
    def _lifecycle(lifecycle: AccountLifecycle, has_pre: bool, has_post: bool) -> None:
        expected = {
            AccountLifecycle.STABLE: (True, True),
            AccountLifecycle.CREATED: (False, True),
            AccountLifecycle.CLOSED: (True, False),
        }[lifecycle]
        if (has_pre, has_post) != expected:
            raise RejectedEvidence(
                ReconciliationReason.ACCOUNT_STATE_MISSING, lifecycle.value
            )
