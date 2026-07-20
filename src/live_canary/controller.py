"""Fail-closed limited-live controller for roadmap PR-046."""

from __future__ import annotations

from threading import RLock
from typing import Any

from src.evidence.shadow_soak import PromotionEvidenceBundle

from .models import (
    AdmissionDecision,
    AdmissionReason,
    ArmingReceipt,
    CanaryCandidate,
    CanaryControlError,
    CanaryEvent,
    CanaryMode,
    CanaryPolicy,
    CanaryReport,
    LatchCode,
    OPERATOR_ACKNOWLEDGEMENT,
    OperatorAcknowledgement,
    OperatorIdentity,
    OutstandingSubmission,
    REPORT_SCHEMA_VERSION,
    ReconciliationResult,
    ReconciliationStatus,
    ReviewedShadowEvidence,
    RuntimeSafetySnapshot,
    sha256_json,
)


class LimitedLiveCanaryController:
    """Single in-process authority for PR-046 canary admission.

    It never signs or submits.  A future sender may consume only an allowed
    decision that has been reserved here and remains bound to one message hash.
    """

    def __init__(self, policy: CanaryPolicy | None = None) -> None:
        self.policy = policy or CanaryPolicy()
        self._mode = CanaryMode.SHADOW
        self._review: ReviewedShadowEvidence | None = None
        self._acknowledgement: OperatorAcknowledgement | None = None
        self._arming: ArmingReceipt | None = None
        self._outstanding: OutstandingSubmission | None = None
        self._latches: dict[LatchCode, str] = {}
        self._events: list[CanaryEvent] = []
        self._decisions: dict[str, AdmissionDecision] = {}
        self._daily_realized_pnl_lamports = 0
        self._consecutive_failures = 0
        self._lock = RLock()

    @property
    def mode(self) -> CanaryMode:
        return self._mode

    @property
    def outstanding(self) -> OutstandingSubmission | None:
        return self._outstanding

    @property
    def active_latches(self) -> tuple[LatchCode, ...]:
        return tuple(sorted(self._latches, key=lambda item: item.value))

    def _require_human(self, operator: OperatorIdentity) -> None:
        if not operator.is_human:
            raise CanaryControlError("only a human operator may control limited live")

    def _event(self, kind: str, observed_at_ms: int, **evidence: Any) -> None:
        self._events.append(
            CanaryEvent(
                sequence=len(self._events) + 1,
                kind=kind,
                observed_at_ms=observed_at_ms,
                evidence=evidence,
            )
        )

    def _latch(self, code: LatchCode, observed_at_ms: int, **details: Any) -> None:
        if code in self._latches:
            return
        self._latches[code] = sha256_json(details)
        self._arming = None
        self._event(
            "latch_activated",
            observed_at_ms,
            latch=code.value,
            evidence_hash=self._latches[code],
        )

    def review_shadow_evidence(
        self,
        bundle: PromotionEvidenceBundle,
        *,
        reviewer: OperatorIdentity,
        review_reference: str,
        reviewed_at_ms: int,
    ) -> ReviewedShadowEvidence:
        with self._lock:
            self._require_human(reviewer)
            if not bundle.passed:
                raise CanaryControlError("PR-039 evidence has blocking reasons")
            if not bundle.human_review_required or bundle.live_enabled:
                raise CanaryControlError(
                    "PR-039 bundle has invalid promotion semantics"
                )
            if not review_reference.strip():
                raise CanaryControlError("human review reference is required")
            review = ReviewedShadowEvidence(
                evidence_hash=bundle.evidence_hash,
                schema_version=bundle.schema_version,
                corpus_id=bundle.corpus_id,
                reviewer_id=reviewer.actor_id,
                review_reference=review_reference.strip(),
                reviewed_at_ms=reviewed_at_ms,
            )
            self._review = review
            self._acknowledgement = None
            self._arming = None
            self._event(
                "shadow_evidence_reviewed",
                reviewed_at_ms,
                reviewer_id=reviewer.actor_id,
                evidence_hash=review.evidence_hash,
                review_reference=review.review_reference,
            )
            return review

    def acknowledge_policy(
        self,
        *,
        operator: OperatorIdentity,
        policy_hash: str,
        evidence_hash: str,
        acknowledgement: str,
        acknowledged_at_ms: int,
    ) -> OperatorAcknowledgement:
        with self._lock:
            self._require_human(operator)
            if self._review is None:
                raise CanaryControlError("human-reviewed PR-039 evidence is required")
            if policy_hash != self.policy.policy_hash:
                raise CanaryControlError(
                    "operator acknowledged a different policy hash"
                )
            if evidence_hash != self._review.evidence_hash:
                raise CanaryControlError("operator acknowledged different evidence")
            if acknowledgement != OPERATOR_ACKNOWLEDGEMENT:
                raise CanaryControlError(
                    "exact limited-live acknowledgement is required"
                )
            expires_at_ms = (
                acknowledged_at_ms + self.policy.operator_confirmation_ttl_ms
            )
            acknowledgement_id = sha256_json(
                {
                    "operator_id": operator.actor_id,
                    "policy_hash": policy_hash,
                    "evidence_hash": evidence_hash,
                    "acknowledged_at_ms": acknowledged_at_ms,
                }
            )
            record = OperatorAcknowledgement(
                acknowledgement_id=acknowledgement_id,
                operator_id=operator.actor_id,
                policy_hash=policy_hash,
                evidence_hash=evidence_hash,
                acknowledged_at_ms=acknowledged_at_ms,
                expires_at_ms=expires_at_ms,
            )
            self._acknowledgement = record
            self._arming = None
            self._event(
                "policy_acknowledged",
                acknowledged_at_ms,
                operator_id=operator.actor_id,
                acknowledgement_id=acknowledgement_id,
            )
            return record

    def arm(
        self,
        *,
        operator: OperatorIdentity,
        acknowledgement_id: str,
        armed_at_ms: int,
    ) -> ArmingReceipt:
        with self._lock:
            self._require_human(operator)
            if (
                not self.policy.enabled
                or self.policy.mode is not CanaryMode.LIMITED_LIVE
            ):
                raise CanaryControlError("policy is not configured for limited live")
            if self._review is None or self._acknowledgement is None:
                raise CanaryControlError("review and acknowledgement are required")
            ack = self._acknowledgement
            if ack.acknowledgement_id != acknowledgement_id:
                raise CanaryControlError("acknowledgement identity mismatch")
            if ack.operator_id != operator.actor_id:
                raise CanaryControlError(
                    "arming operator must match acknowledging operator"
                )
            if armed_at_ms > ack.expires_at_ms:
                raise CanaryControlError("operator acknowledgement expired")
            if self._latches or self._outstanding is not None:
                raise CanaryControlError(
                    "active latch or outstanding submission blocks arming"
                )
            expires_at_ms = armed_at_ms + self.policy.operator_confirmation_ttl_ms
            arming_id = sha256_json(
                {
                    "acknowledgement_id": acknowledgement_id,
                    "armed_at_ms": armed_at_ms,
                    "policy_hash": self.policy.policy_hash,
                }
            )
            receipt = ArmingReceipt(
                arming_id=arming_id,
                operator_id=operator.actor_id,
                policy_hash=self.policy.policy_hash,
                evidence_hash=self._review.evidence_hash,
                armed_at_ms=armed_at_ms,
                expires_at_ms=expires_at_ms,
            )
            self._arming = receipt
            self._mode = CanaryMode.LIMITED_LIVE
            self._event("canary_armed", armed_at_ms, arming_id=arming_id)
            return receipt

    def rollback_to_shadow(
        self, *, operator: OperatorIdentity, reason: str, observed_at_ms: int
    ) -> None:
        with self._lock:
            self._require_human(operator)
            if not reason.strip():
                raise CanaryControlError("rollback reason is required")
            self._mode = CanaryMode.SHADOW
            self._arming = None
            self._acknowledgement = None
            self._event(
                "rollback_to_shadow",
                observed_at_ms,
                operator_id=operator.actor_id,
                reason=reason.strip(),
            )

    def manual_kill(
        self, *, operator: OperatorIdentity, reason: str, observed_at_ms: int
    ) -> None:
        with self._lock:
            self._require_human(operator)
            if not reason.strip():
                raise CanaryControlError("manual kill reason is required")
            self._latch(
                LatchCode.MANUAL_KILL_SWITCH,
                observed_at_ms,
                operator_id=operator.actor_id,
                reason=reason.strip(),
            )
            self._mode = CanaryMode.SHADOW

    def clear_latches(
        self, *, operator: OperatorIdentity, reason: str, observed_at_ms: int
    ) -> None:
        with self._lock:
            self._require_human(operator)
            if self._mode is not CanaryMode.SHADOW or self._outstanding is not None:
                raise CanaryControlError(
                    "latches clear only in shadow with no outstanding attempt"
                )
            if not reason.strip():
                raise CanaryControlError("latch-clear reason is required")
            cleared = tuple(code.value for code in self.active_latches)
            self._latches.clear()
            self._event(
                "latches_cleared",
                observed_at_ms,
                operator_id=operator.actor_id,
                cleared=cleared,
                reason=reason.strip(),
            )

    def _apply_snapshot_latches(self, snapshot: RuntimeSafetySnapshot) -> None:
        if not self.policy.enabled:
            return
        if (
            snapshot.daily_realized_pnl_lamports
            <= -self.policy.maximum_daily_loss_lamports
        ):
            self._latch(
                LatchCode.DAILY_LOSS_LIMIT,
                snapshot.now_ms,
                daily_realized_pnl_lamports=snapshot.daily_realized_pnl_lamports,
            )
        if snapshot.consecutive_failures >= self.policy.maximum_consecutive_failures:
            self._latch(
                LatchCode.CONSECUTIVE_FAILURE_LIMIT,
                snapshot.now_ms,
                consecutive_failures=snapshot.consecutive_failures,
            )
        age_ms = snapshot.now_ms - snapshot.data_observed_at_ms
        if age_ms < 0 or age_ms > self.policy.maximum_data_age_ms:
            self._latch(LatchCode.STALE_DATA, snapshot.now_ms, data_age_ms=age_ms)
        divergence = abs(snapshot.rpc_primary_slot - snapshot.rpc_secondary_slot)
        if divergence > self.policy.maximum_rpc_slot_divergence:
            self._latch(
                LatchCode.RPC_DIVERGENCE,
                snapshot.now_ms,
                slot_divergence=divergence,
            )
        if snapshot.reconciliation_ambiguous:
            self._latch(
                LatchCode.RECONCILIATION_AMBIGUITY,
                snapshot.now_ms,
                source="runtime_snapshot",
            )

    def evaluate(
        self, candidate: CanaryCandidate, snapshot: RuntimeSafetySnapshot
    ) -> AdmissionDecision:
        with self._lock:
            self._apply_snapshot_latches(snapshot)
            reasons: list[AdmissionReason] = []
            if not self.policy.enabled:
                reasons.append(AdmissionReason.POLICY_DISABLED)
            if self._mode is not CanaryMode.LIMITED_LIVE:
                reasons.append(AdmissionReason.SHADOW_MODE)
            if self._review is None:
                reasons.append(AdmissionReason.HUMAN_REVIEW_MISSING)
            if self._acknowledgement is None:
                reasons.append(AdmissionReason.OPERATOR_ACK_MISSING)
            if self._arming is None:
                reasons.append(AdmissionReason.CANARY_NOT_ARMED)
            elif snapshot.now_ms > self._arming.expires_at_ms:
                self._arming = None
                self._mode = CanaryMode.SHADOW
                reasons.extend(
                    (AdmissionReason.ARM_EXPIRED, AdmissionReason.SHADOW_MODE)
                )
            if self._latches:
                reasons.append(AdmissionReason.ACTIVE_LATCH)
            if self._outstanding is not None:
                reasons.append(AdmissionReason.OUTSTANDING_SUBMISSION)
            if candidate.pair not in self.policy.allowlisted_pairs:
                reasons.append(AdmissionReason.PAIR_NOT_ALLOWLISTED)
            if candidate.provider not in self.policy.allowlisted_providers:
                reasons.append(AdmissionReason.PROVIDER_NOT_ALLOWLISTED)
            if not set(candidate.program_ids).issubset(
                self.policy.allowlisted_program_ids
            ):
                reasons.append(AdmissionReason.PROGRAM_NOT_ALLOWLISTED)
            if candidate.principal_base_units > self.policy.max_principal_base_units:
                reasons.append(AdmissionReason.PRINCIPAL_CAP_EXCEEDED)
            if candidate.wallet_spend_lamports > self.policy.max_wallet_spend_lamports:
                reasons.append(AdmissionReason.WALLET_SPEND_CAP_EXCEEDED)
            remaining = (
                snapshot.wallet_balance_lamports - candidate.wallet_spend_lamports
            )
            if remaining < self.policy.minimum_wallet_reserve_lamports:
                self._latch(
                    LatchCode.LOW_BALANCE,
                    snapshot.now_ms,
                    wallet_balance_lamports=snapshot.wallet_balance_lamports,
                    remaining_lamports=remaining,
                )
                reasons.extend(
                    (
                        AdmissionReason.WALLET_RESERVE_BREACH,
                        AdmissionReason.ACTIVE_LATCH,
                    )
                )
            candidate_age = snapshot.now_ms - candidate.observed_at_ms
            if candidate_age < 0 or candidate_age > self.policy.maximum_data_age_ms:
                self._latch(
                    LatchCode.STALE_DATA,
                    snapshot.now_ms,
                    candidate_age_ms=candidate_age,
                )
                reasons.extend(
                    (AdmissionReason.DATA_STALE, AdmissionReason.ACTIVE_LATCH)
                )
            divergence = abs(snapshot.rpc_primary_slot - snapshot.rpc_secondary_slot)
            if divergence > self.policy.maximum_rpc_slot_divergence:
                reasons.append(AdmissionReason.RPC_DIVERGENCE)
            unique_reasons = tuple(dict.fromkeys(reasons))
            decision_id = sha256_json(
                {
                    "attempt_id": candidate.attempt_id,
                    "candidate_hash": candidate.candidate_hash,
                    "policy_hash": self.policy.policy_hash,
                    "evaluated_at_ms": snapshot.now_ms,
                    "reasons": [reason.value for reason in unique_reasons],
                }
            )
            decision = AdmissionDecision(
                decision_id=decision_id,
                allowed=not unique_reasons,
                reasons=unique_reasons,
                attempt_id=candidate.attempt_id,
                candidate_hash=candidate.candidate_hash,
                policy_hash=self.policy.policy_hash,
                evidence_hash=self._review.evidence_hash if self._review else None,
                evaluated_at_ms=snapshot.now_ms,
            )
            self._decisions[decision_id] = decision
            self._event(
                "admission_evaluated",
                snapshot.now_ms,
                attempt_id=candidate.attempt_id,
                decision_id=decision_id,
                allowed=decision.allowed,
                reasons=tuple(reason.value for reason in unique_reasons),
            )
            return decision

    def reserve_submission(
        self,
        decision: AdmissionDecision,
        candidate: CanaryCandidate,
        *,
        reserved_at_ms: int,
    ) -> OutstandingSubmission:
        with self._lock:
            stored = self._decisions.get(decision.decision_id)
            if stored != decision or not decision.allowed:
                raise CanaryControlError(
                    "only a current allowed decision may be reserved"
                )
            if decision.policy_hash != self.policy.policy_hash:
                raise CanaryControlError("decision policy hash is stale")
            if decision.candidate_hash != candidate.candidate_hash:
                raise CanaryControlError("decision/candidate identity mismatch")
            if self._outstanding is not None or self._latches:
                raise CanaryControlError(
                    "outstanding submission or latch blocks reserve"
                )
            outstanding = OutstandingSubmission(
                attempt_id=candidate.attempt_id,
                message_hash=candidate.message_hash,
                candidate_hash=candidate.candidate_hash,
                reserved_at_ms=reserved_at_ms,
            )
            self._outstanding = outstanding
            self._event(
                "submission_reserved",
                reserved_at_ms,
                attempt_id=candidate.attempt_id,
                message_hash=candidate.message_hash,
            )
            return outstanding

    def record_reconciliation(self, result: ReconciliationResult) -> CanaryReport:
        with self._lock:
            outstanding = self._outstanding
            if (
                outstanding is None
                or outstanding.attempt_id != result.attempt_id
                or outstanding.message_hash != result.message_hash
            ):
                self._latch(
                    LatchCode.RECONCILIATION_AMBIGUITY,
                    result.observed_at_ms,
                    attempt_id=result.attempt_id,
                    source="identity_mismatch",
                )
                raise CanaryControlError(
                    "reconciliation does not match outstanding submission"
                )
            self._event(
                "reconciliation_observed",
                result.observed_at_ms,
                attempt_id=result.attempt_id,
                status=result.status.value,
                reconciliation_hash=result.reconciliation_hash,
            )
            if result.status is ReconciliationStatus.INDETERMINATE:
                self._latch(
                    LatchCode.RECONCILIATION_AMBIGUITY,
                    result.observed_at_ms,
                    attempt_id=result.attempt_id,
                    reconciliation_hash=result.reconciliation_hash,
                )
                return self.report()
            self._outstanding = None
            self._daily_realized_pnl_lamports += result.realized_pnl_lamports
            if result.status is ReconciliationStatus.FAILURE:
                self._consecutive_failures += 1
            else:
                self._consecutive_failures = 0
            if (
                self._daily_realized_pnl_lamports
                <= -self.policy.maximum_daily_loss_lamports
            ):
                self._latch(
                    LatchCode.DAILY_LOSS_LIMIT,
                    result.observed_at_ms,
                    daily_realized_pnl_lamports=self._daily_realized_pnl_lamports,
                )
            if self._consecutive_failures >= self.policy.maximum_consecutive_failures:
                self._latch(
                    LatchCode.CONSECUTIVE_FAILURE_LIMIT,
                    result.observed_at_ms,
                    consecutive_failures=self._consecutive_failures,
                )
            return self.report()

    def report(self) -> CanaryReport:
        with self._lock:
            event_digest = sha256_json([event.event_hash for event in self._events])
            return CanaryReport(
                schema_version=REPORT_SCHEMA_VERSION,
                policy_hash=self.policy.policy_hash,
                evidence_hash=self._review.evidence_hash if self._review else None,
                mode=self._mode,
                armed=self._arming is not None,
                armed_until_ms=self._arming.expires_at_ms if self._arming else None,
                outstanding_attempt_id=(
                    self._outstanding.attempt_id if self._outstanding else None
                ),
                active_latches=self.active_latches,
                daily_realized_pnl_lamports=self._daily_realized_pnl_lamports,
                consecutive_failures=self._consecutive_failures,
                event_count=len(self._events),
                event_digest=event_digest,
                ai_authority=False,
            )
