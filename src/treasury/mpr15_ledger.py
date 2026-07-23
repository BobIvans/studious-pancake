"""One-time treasury authorization and durable exactly-once ledger for MPR-15."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import os
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence

from .mpr15_common import (
    AssetAmount, AssetIdentity, LedgerEntryKind, MPR15_SCHEMA, RiskWindowKind,
    SIGNATURE_ALGORITHM, TreasuryAccountingError, TreasuryScope,
    _ALLOWED_STAGE_TRANSITIONS, _canonical_json, _ensure_mapping,
    _require_int, _require_pubkey, _require_same_asset, _require_sha256,
    _require_text, _trusted_key,
    _verify_hmac, domain_hash, sign_hmac_payload,
)
from .mpr15_risk import (
    AccountingStage, DurableRiskState, RiskLedgerEntry, RiskWindow,
    materialize_latest_movements,
)

@dataclass(frozen=True, slots=True, init=False)
class TreasuryAuthorization:
    authorization_hash: str
    request_hash: str
    approver_key_id: str
    policy_hash: str
    scope: TreasuryScope
    issued_at_ns: int
    expires_at_ns: int
    nonce: str
    signature: str
    signature_algorithm: str

    @classmethod
    def issue(
        cls,
        *,
        request_hash: str,
        approver_key_id: str,
        policy_hash: str,
        scope: TreasuryScope,
        issued_at_ns: int,
        expires_at_ns: int,
        nonce: str,
        signing_key: bytes,
    ) -> TreasuryAuthorization:
        _require_sha256(request_hash, "authorization request_hash")
        _require_text(approver_key_id, "approver_key_id")
        _require_sha256(policy_hash, "authorization policy_hash")
        _require_int(issued_at_ns, "issued_at_ns", lower=0)
        _require_int(expires_at_ns, "expires_at_ns", lower=0)
        if expires_at_ns <= issued_at_ns:
            raise TreasuryAccountingError("authorization must expire after issue time")
        _require_sha256(nonce, "authorization nonce")
        payload = {
            "request_hash": request_hash,
            "approver_key_id": approver_key_id,
            "policy_hash": policy_hash,
            "scope": scope.value,
            "issued_at_ns": issued_at_ns,
            "expires_at_ns": expires_at_ns,
            "nonce": nonce,
        }
        authorization_hash = domain_hash("mpr15/treasury-authorization", payload)
        signature = sign_hmac_payload(
            key=signing_key,
            domain="mpr15/treasury-authorization-signature",
            payload_hash=authorization_hash,
        )
        instance = object.__new__(cls)
        object.__setattr__(instance, "authorization_hash", authorization_hash)
        object.__setattr__(instance, "request_hash", request_hash)
        object.__setattr__(instance, "approver_key_id", approver_key_id)
        object.__setattr__(instance, "policy_hash", policy_hash)
        object.__setattr__(instance, "scope", scope)
        object.__setattr__(instance, "issued_at_ns", issued_at_ns)
        object.__setattr__(instance, "expires_at_ns", expires_at_ns)
        object.__setattr__(instance, "nonce", nonce)
        object.__setattr__(instance, "signature", signature)
        object.__setattr__(instance, "signature_algorithm", SIGNATURE_ALGORITHM)
        return instance

    def verify(
        self,
        *,
        now_ns: int,
        expected_request_hash: str,
        expected_policy_hash: str,
        expected_scope: TreasuryScope,
        trusted_keys: Mapping[str, bytes],
    ) -> None:
        _require_int(now_ns, "trusted authorization time", lower=0)
        if now_ns < self.issued_at_ns:
            raise TreasuryAccountingError("treasury authorization is not active yet")
        if now_ns > self.expires_at_ns:
            raise TreasuryAccountingError("treasury authorization expired")
        if self.request_hash != expected_request_hash:
            raise TreasuryAccountingError("authorization is bound to another request")
        if self.policy_hash != expected_policy_hash:
            raise TreasuryAccountingError("authorization policy hash mismatch")
        if self.scope is not expected_scope:
            raise TreasuryAccountingError("treasury authorization scope mismatch")
        payload = {
            "request_hash": self.request_hash,
            "approver_key_id": self.approver_key_id,
            "policy_hash": self.policy_hash,
            "scope": self.scope.value,
            "issued_at_ns": self.issued_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "nonce": self.nonce,
        }
        expected_hash = domain_hash("mpr15/treasury-authorization", payload)
        if not hmac.compare_digest(expected_hash, self.authorization_hash):
            raise TreasuryAccountingError("treasury authorization hash mismatch")
        key = _trusted_key(trusted_keys, self.approver_key_id)
        _verify_hmac(
            key=key,
            domain="mpr15/treasury-authorization-signature",
            payload_hash=self.authorization_hash,
            signature=self.signature,
        )


@dataclass(frozen=True, slots=True)
class FundingSweepRequest:
    request_id: str
    source_wallet: str
    destination_wallet: str
    amount: AssetAmount
    scope: TreasuryScope
    destination_policy_hash: str
    simulated_message_hash: str
    isolated_signer_required: bool
    authorization: TreasuryAuthorization | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.request_id, "request_id")
        _require_pubkey(self.source_wallet, "source_wallet")
        _require_pubkey(self.destination_wallet, "destination_wallet")
        _require_sha256(self.destination_policy_hash, "destination_policy_hash")
        _require_sha256(self.simulated_message_hash, "simulated_message_hash")
        self.amount.require_non_negative("funding_sweep_amount")
        if self.amount.base_units == 0:
            raise TreasuryAccountingError("funding/sweep amount must be positive")

    @property
    def request_hash(self) -> str:
        return domain_hash(
            "mpr15/funding-sweep-request",
            {
                "request_id": self.request_id,
                "source_wallet": self.source_wallet,
                "destination_wallet": self.destination_wallet,
                "amount": self.amount.to_json(),
                "scope": self.scope.value,
                "destination_policy_hash": self.destination_policy_hash,
                "simulated_message_hash": self.simulated_message_hash,
                "isolated_signer_required": self.isolated_signer_required,
            },
        )

    def validate_and_consume(
        self,
        *,
        now_ns: int,
        policy_hash: str,
        destination_allowlisted: bool,
        trusted_approver_keys: Mapping[str, bytes],
        ledger: DurableTreasuryLedger,
    ) -> str:
        _require_sha256(policy_hash, "policy_hash")
        if not destination_allowlisted:
            raise TreasuryAccountingError(
                "funding/sweep destination is not allowlisted"
            )
        if not self.isolated_signer_required:
            raise TreasuryAccountingError("funding/sweep requires isolated signer")
        if self.authorization is None:
            raise TreasuryAccountingError("treasury authorization is required")
        self.authorization.verify(
            now_ns=now_ns,
            expected_request_hash=self.request_hash,
            expected_policy_hash=policy_hash,
            expected_scope=self.scope,
            trusted_keys=trusted_approver_keys,
        )
        return ledger.consume_authorization(
            authorization=self.authorization,
            request_hash=self.request_hash,
            consumed_at_ns=now_ns,
        )


class DurableTreasuryLedger:
    """SQLite append-only authority for ledger events and one-time approvals."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path), isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_events (
                event_id TEXT PRIMARY KEY,
                movement_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                stage_rank INTEGER NOT NULL,
                recorded_at_ns INTEGER NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                movement_fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                CHECK(stage_rank IN (10,20,30,40,50,60))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ledger_movement_stage_unique
                ON ledger_events(movement_id, stage_rank);
            CREATE INDEX IF NOT EXISTS ledger_movement_order
                ON ledger_events(movement_id, stage_rank, recorded_at_ns);

            CREATE TABLE IF NOT EXISTS authorization_consumptions (
                authorization_hash TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL UNIQUE,
                consumed_at_ns INTEGER NOT NULL,
                consumption_hash TEXT NOT NULL UNIQUE
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> DurableTreasuryLedger:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def append_event(self, entry: RiskLedgerEntry) -> str:
        payload_json = _canonical_json(entry.to_json())
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT event_hash FROM ledger_events WHERE idempotency_key = ?",
                (entry.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["event_hash"] != entry.event_hash:
                    raise TreasuryAccountingError(
                        "idempotency key reused with different ledger event"
                    )
                self._connection.execute("COMMIT")
                return entry.event_hash

            current_row = self._connection.execute(
                """
                SELECT payload_json FROM ledger_events
                WHERE movement_id = ?
                ORDER BY stage_rank DESC LIMIT 1
                """,
                (entry.movement_id,),
            ).fetchone()
            if current_row is not None:
                current_payload = json.loads(current_row["payload_json"])
                current = RiskLedgerEntry.from_json(
                    _ensure_mapping(current_payload, "stored ledger event")
                )
                if current.movement_fingerprint != entry.movement_fingerprint:
                    raise TreasuryAccountingError(
                        "economic movement changed during stage transition"
                    )
                if entry.stage == current.stage:
                    self._connection.execute("COMMIT")
                    return current.event_hash
                expected = _ALLOWED_STAGE_TRANSITIONS.get(current.stage)
                if expected is None or entry.stage != expected:
                    raise TreasuryAccountingError("illegal accounting stage transition")

            self._connection.execute(
                """
                INSERT INTO ledger_events(
                    event_id, movement_id, idempotency_key, stage_rank,
                    recorded_at_ns, event_hash, movement_fingerprint, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.event_id,
                    entry.movement_id,
                    entry.idempotency_key,
                    int(entry.stage),
                    entry.recorded_at_ns,
                    entry.event_hash,
                    entry.movement_fingerprint,
                    payload_json,
                ),
            )
            self._connection.execute("COMMIT")
            return entry.event_hash
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def consume_authorization(
        self,
        *,
        authorization: TreasuryAuthorization,
        request_hash: str,
        consumed_at_ns: int,
    ) -> str:
        _require_sha256(request_hash, "consumed request_hash")
        _require_int(consumed_at_ns, "consumed_at_ns", lower=0)
        consumption_hash = domain_hash(
            "mpr15/authorization-consumption",
            {
                "authorization_hash": authorization.authorization_hash,
                "request_hash": request_hash,
                "consumed_at_ns": consumed_at_ns,
            },
        )
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                """
                SELECT request_hash, consumption_hash
                FROM authorization_consumptions
                WHERE authorization_hash = ? OR request_hash = ?
                """,
                (authorization.authorization_hash, request_hash),
            ).fetchone()
            if existing is not None:
                raise TreasuryAccountingError("treasury authorization already consumed")
            self._connection.execute(
                """
                INSERT INTO authorization_consumptions(
                    authorization_hash, request_hash, consumed_at_ns, consumption_hash
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    authorization.authorization_hash,
                    request_hash,
                    consumed_at_ns,
                    consumption_hash,
                ),
            )
            self._connection.execute("COMMIT")
            return consumption_hash
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def events(self) -> tuple[RiskLedgerEntry, ...]:
        rows = self._connection.execute(
            "SELECT payload_json FROM ledger_events ORDER BY recorded_at_ns, event_id"
        ).fetchall()
        return tuple(
            RiskLedgerEntry.from_json(
                _ensure_mapping(json.loads(row["payload_json"]), "stored ledger event")
            )
            for row in rows
        )

    def replay_risk_state(
        self,
        *,
        windows: Sequence[RiskWindow],
        asset: AssetIdentity,
        previous_checkpoint_hash: str | None = None,
    ) -> DurableRiskState:
        return DurableRiskState.from_entries(
            entries=self.events(),
            windows=windows,
            asset=asset,
            previous_checkpoint_hash=previous_checkpoint_hash,
        )


@dataclass(frozen=True, slots=True, init=False)
class DailyTreasuryReport:
    window: RiskWindow
    opening_finalized_balance: AssetAmount
    funding: AssetAmount
    withdrawals: AssetAmount
    realized_pnl: AssetAmount
    fees: AssetAmount
    rent_locked: AssetAmount
    rent_refunded: AssetAmount
    ending_finalized_balance: AssetAmount
    unresolved_exposure: AssetAmount
    tolerance_base_units: int
    unresolved_exposure_threshold_base_units: int
    ledger_hash: str

    @classmethod
    def from_ledger(
        cls,
        *,
        window: RiskWindow,
        opening_finalized_balance: AssetAmount,
        ending_finalized_balance: AssetAmount,
        entries: Sequence[RiskLedgerEntry],
        tolerance_base_units: int = 0,
        unresolved_exposure_threshold_base_units: int = 0,
    ) -> DailyTreasuryReport:
        if window.kind is not RiskWindowKind.UTC_DAY:
            raise TreasuryAccountingError("daily treasury report requires UTC day")
        _require_same_asset(opening_finalized_balance, ending_finalized_balance)
        opening_finalized_balance.require_non_negative("opening_finalized_balance")
        ending_finalized_balance.require_non_negative("ending_finalized_balance")
        _require_int(tolerance_base_units, "tolerance_base_units", lower=0)
        _require_int(
            unresolved_exposure_threshold_base_units,
            "unresolved_exposure_threshold_base_units",
            lower=0,
        )
        asset = opening_finalized_balance.asset
        latest = materialize_latest_movements(entries)
        totals = {kind: 0 for kind in LedgerEntryKind}
        included: list[RiskLedgerEntry] = []
        for entry in latest.values():
            if entry.asset != asset or entry.stage < AccountingStage.FINALIZED:
                continue
            if not window.contains(entry.occurred_at_ns):
                continue
            totals[entry.kind] += entry.amount_delta_base_units
            included.append(entry)
        fee_total = sum(
            totals[kind]
            for kind in (
                LedgerEntryKind.FEE,
                LedgerEntryKind.TIP,
                LedgerEntryKind.TRANSFER_FEE,
                LedgerEntryKind.FAILED_ATTEMPT_CHARGE,
                LedgerEntryKind.PROVIDER_SPEND,
            )
        )
        instance = object.__new__(cls)
        object.__setattr__(instance, "window", window)
        object.__setattr__(
            instance, "opening_finalized_balance", opening_finalized_balance
        )
        object.__setattr__(
            instance,
            "funding",
            AssetAmount(asset, totals[LedgerEntryKind.FUNDING]),
        )
        object.__setattr__(
            instance,
            "withdrawals",
            AssetAmount(asset, totals[LedgerEntryKind.WITHDRAWAL]),
        )
        object.__setattr__(
            instance,
            "realized_pnl",
            AssetAmount(asset, totals[LedgerEntryKind.REALIZED_PNL]),
        )
        object.__setattr__(instance, "fees", AssetAmount(asset, fee_total))
        object.__setattr__(
            instance,
            "rent_locked",
            AssetAmount(asset, totals[LedgerEntryKind.RENT_LOCKED]),
        )
        object.__setattr__(
            instance,
            "rent_refunded",
            AssetAmount(asset, totals[LedgerEntryKind.RENT_REFUNDED]),
        )
        object.__setattr__(
            instance, "ending_finalized_balance", ending_finalized_balance
        )
        object.__setattr__(
            instance,
            "unresolved_exposure",
            AssetAmount(asset, totals[LedgerEntryKind.UNRESOLVED_MAX_LOSS]),
        )
        object.__setattr__(instance, "tolerance_base_units", tolerance_base_units)
        object.__setattr__(
            instance,
            "unresolved_exposure_threshold_base_units",
            unresolved_exposure_threshold_base_units,
        )
        object.__setattr__(
            instance,
            "ledger_hash",
            domain_hash(
                "mpr15/daily-ledger-projection",
                [
                    entry.to_json()
                    for entry in sorted(
                        included, key=lambda item: item.movement_id
                    )
                ],
            ),
        )
        return instance

    @property
    def expected_ending_balance(self) -> AssetAmount:
        return (
            self.opening_finalized_balance
            + self.funding
            - self.withdrawals
            + self.realized_pnl
            - self.fees
            - self.rent_locked
            + self.rent_refunded
        )

    @property
    def ledger_to_chain_variance_base_units(self) -> int:
        return abs(
            self.ending_finalized_balance.base_units
            - self.expected_ending_balance.base_units
        )

    @property
    def hard_latch_required(self) -> bool:
        return (
            self.ledger_to_chain_variance_base_units > self.tolerance_base_units
            or self.unresolved_exposure.base_units
            > self.unresolved_exposure_threshold_base_units
        )

    def assert_balanced(self) -> None:
        if self.ledger_to_chain_variance_base_units > self.tolerance_base_units:
            raise TreasuryAccountingError("ledger-to-chain variance exceeds tolerance")
        if (
            self.unresolved_exposure.base_units
            > self.unresolved_exposure_threshold_base_units
        ):
            raise TreasuryAccountingError("unresolved exposure requires hard latch")
