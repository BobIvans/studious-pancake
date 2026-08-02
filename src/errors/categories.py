from enum import StrEnum
class FailureCategory(StrEnum):
 CONFIGURATION='configuration'; CONTRACT='contract'; PROVIDER_TRANSIENT='provider_transient'; PROVIDER_PERMANENT='provider_permanent'; STALE_DATA='stale_data'; DEADLINE='deadline'; OVERLOAD='overload'; PERSISTENCE_CONFLICT='persistence_conflict'; ECONOMIC_REJECTION='economic_rejection'; SECURITY='security'; SUBMISSION_AMBIGUITY='submission_ambiguity'; INTERNAL_INVARIANT='internal_invariant'
class RetryClass(StrEnum):
 NEVER='never'; BOUNDED_SAFE_READ='bounded_safe_read'; IDEMPOTENT='idempotent'; RECONCILE_ONLY='reconcile_only'
class Ambiguity(StrEnum): NONE='none'; POSSIBLE_EFFECT='possible_effect'; QUARANTINED='quarantined'; RECONCILED='reconciled'
class ResultState(StrEnum): SUCCESS='success'; REJECTED='rejected'; FAILED='failed'; AMBIGUOUS='ambiguous'; CANCELLED='cancelled'; TIMED_OUT='timed_out'; OVERLOADED='overloaded'
