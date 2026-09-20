"""Read-only capital and program/token admission for AGG-02.

The existing DurableCapitalCoordinator remains the sole reservation authority.
This module only turns public balance evidence into an observation envelope used
by discovery/qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.economics.durable_reservations import WalletBalanceSnapshot

from .contracts import Agg02Error


@dataclass(frozen=True, slots=True)
class BudgetEnvelope:
    wallet_pubkey: str | None
    observed_native_lamports: int | None
    active_reserved_lamports: int
    native_fee_floor_lamports: int
    peak_rent_lamports: int
    free_native_lamports: int | None
    effect_allowed: bool
    reason: str


def observe_budget_envelope(
    *,
    snapshot: WalletBalanceSnapshot | None,
    active_reserved_lamports: int,
    native_fee_floor_lamports: int,
    peak_rent_lamports: int,
    now_ns: int,
    max_snapshot_age_ns: int,
    expected_genesis: str | None = None,
) -> BudgetEnvelope:
    for value in (
        active_reserved_lamports,
        native_fee_floor_lamports,
        peak_rent_lamports,
        now_ns,
        max_snapshot_age_ns,
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Agg02Error("AGG02_INVALID_CAPITAL_INTEGER")
    if snapshot is None:
        return BudgetEnvelope(
            None,
            None,
            active_reserved_lamports,
            native_fee_floor_lamports,
            peak_rent_lamports,
            None,
            False,
            "unknown_balance",
        )
    if expected_genesis is not None and snapshot.cluster_genesis != expected_genesis:
        return BudgetEnvelope(
            snapshot.wallet_pubkey,
            snapshot.native_lamports,
            active_reserved_lamports,
            native_fee_floor_lamports,
            peak_rent_lamports,
            None,
            False,
            "genesis_mismatch",
        )
    if snapshot.captured_at_ns is None:
        return BudgetEnvelope(
            snapshot.wallet_pubkey,
            snapshot.native_lamports,
            active_reserved_lamports,
            native_fee_floor_lamports,
            peak_rent_lamports,
            None,
            False,
            "snapshot_time_unknown",
        )
    age = now_ns - snapshot.captured_at_ns
    if age < 0 or age > max_snapshot_age_ns:
        return BudgetEnvelope(
            snapshot.wallet_pubkey,
            snapshot.native_lamports,
            active_reserved_lamports,
            native_fee_floor_lamports,
            peak_rent_lamports,
            None,
            False,
            "stale_balance",
        )
    free = max(0, snapshot.native_lamports - active_reserved_lamports)
    required = native_fee_floor_lamports + peak_rent_lamports
    return BudgetEnvelope(
        snapshot.wallet_pubkey,
        snapshot.native_lamports,
        active_reserved_lamports,
        native_fee_floor_lamports,
        peak_rent_lamports,
        free,
        free >= required,
        "ok" if free >= required else "insufficient_native_budget",
    )


@dataclass(frozen=True, slots=True)
class ProgramTokenObservation:
    program_id: str
    program_hash: str
    mint_id: str
    mint_owner_program: str
    extensions: tuple[str, ...] = ()
    destinations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InteractionAdmission:
    accepted: bool
    reason: str


def admit_program_token_interaction(
    observation: ProgramTokenObservation,
    *,
    allowed_program_hashes: dict[str, str],
    allowed_token_programs: Iterable[str],
    allowed_extensions: Iterable[str],
    allowed_destinations: Iterable[str],
) -> InteractionAdmission:
    expected_hash = allowed_program_hashes.get(observation.program_id)
    if expected_hash is None:
        return InteractionAdmission(False, "unknown_program")
    if expected_hash != observation.program_hash:
        return InteractionAdmission(False, "program_hash_drift")
    if observation.mint_owner_program not in set(allowed_token_programs):
        return InteractionAdmission(False, "token_program_not_allowed")
    extension_set = set(observation.extensions)
    if extension_set - set(allowed_extensions):
        return InteractionAdmission(False, "unknown_token_extension")
    destination_set = set(observation.destinations)
    if destination_set - set(allowed_destinations):
        return InteractionAdmission(False, "destination_not_allowed")
    return InteractionAdmission(True, "ok")
