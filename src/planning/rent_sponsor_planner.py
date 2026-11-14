"""Stream J: route-level rent/fee sourcing planner over the existing Slumlord adapter.

This module plans, offline and sender-free, how each token account a route
needs obtains its rent-exempt lamports.  It never signs, sends, creates,
closes, or refunds anything on network; it emits an unsigned plan DTO
(account -> tier mapping, lamport flows, fee lines, instruction references)
for the existing planner/simulation owners to consume.

Strict 4-tier sourcing order per account:

1. ``REUSE_QUALIFIED_EXISTING`` -- a route-provided existing token account
   backed by qualification evidence (observed lamports >= its rent-exempt
   minimum).  Unknown is never coerced to qualified.
2. ``PROVIDER_SPONSORED`` -- provider rent/payer sponsorship (e.g. 0x rent
   sponsor, Titan payer) only when a sponsor profile is verified offline.
   Today NO sponsor is verified, so the tier exists but is INACTIVE; any
   claim without verified evidence is refused with a typed rejection.
3. ``SLUMLORD_EPHEMERAL`` -- ephemeral rent financing through the existing
   Slumlord adapter (read-only import of ``src.lending.slumlord``).  Only
   ELIGIBLE TEMPORARY accounts may use it: the account must be created and
   emptied inside the transaction, closed with its full lamports refunded to
   the repayment source, and the Slumlord loan repaid before the same-
   transaction CheckRepaid.  Slumlord is rent financing only: it is not
   trading capital and never a universal free-ATA primitive.
4. ``PERSISTENT_LOCAL_FUNDING`` -- ordinary persistent funding by the route
   payer for final output accounts that must remain open.

Fail-closed route economics: the route is rejected with typed reasons when
account/rent/fee/byte/CU arithmetic fails.  Network signature fees and
priority fees are always separately funded by the persistent payer -- never
"free" and never covered by Slumlord or a sponsor.

Rent arithmetic is pinned to the canonical Solana rent defaults
(lamports_per_byte_year = 3480, exemption threshold = 2.0 years, 128-byte
account overhead): ``minimum_balance(data_len) = (128 + data_len) * 3480 * 2``.
The checked-in offline dossier ``docs/integrations/offline/solana-p0/`` does
not currently pin rent sysvar amounts; these defaults are recorded here as
conservative offline planning constants and are asserted exactly by the
offline fixtures (890,880 for 0-byte system accounts, 2,039,280 for 165-byte
SPL token accounts).

All arithmetic is local simulation.  Zero network.  Zero signing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.lending.slumlord import (
    SLUMLORD_INSTRUCTIONS_BLOB,
    SLUMLORD_LIBRARY_BLOB,
    SLUMLORD_PDA,
    SLUMLORD_PROGRAM_ID,
    SLUMLORD_UPSTREAM_COMMIT,
    SLUMLORD_UPSTREAM_REPOSITORY,
    SlumlordAdapterError,
    SlumlordOrderCertificate,
    SlumlordPreparedRentLoan,
    SlumlordReserveState,
    prepare_rent_loan,
    validate_slumlord_order,
)
from src.lending.unsigned_builders.contract import (
    UNSIGNED_BUILDERS_CONTRACT_VERSION,
    canonical_hash,
)

RENT_SPONSOR_PLANNER_VERSION = "rent-sponsor-planner.v1"
RENT_SPONSOR_CONTRACT_VERSION = "rent-sponsor.v1"

# --- Pinned Solana rent defaults (see module docstring) ---------------------

LAMPORTS_PER_BYTE_YEAR = 3480
RENT_EXEMPTION_THRESHOLD_YEARS = 2.0
ACCOUNT_METADATA_OVERHEAD_BYTES = 128
RENT_EXEMPT_LAMPORTS_PER_BYTE = LAMPORTS_PER_BYTE_YEAR * int(
    RENT_EXEMPTION_THRESHOLD_YEARS
)

TOKEN_ACCOUNT_DATA_LEN = 165
SYSTEM_ACCOUNT_DATA_LEN = 0

# --- Pinned Solana packet / budget / fee constants ---------------------------

MAX_PACKET_BYTES = 1232
MAX_COMPUTE_UNITS = 1_400_000
LAMPORTS_PER_SIGNATURE = 5000

RENT_CONSTANT_PROVENANCE_NOTE = (
    "canonical Solana rent defaults (lamports_per_byte_year=3480, "
    "exemption_threshold=2.0 years, 128-byte overhead); not yet pinned in "
    "docs/integrations/offline/solana-p0/ and asserted exactly by offline "
    "rent-sponsor fixtures"
)

NOTE_SPONSOR_TIER_INACTIVE = (
    "no provider rent sponsor (0x rent sponsor / Titan payer) is verified "
    "offline; tier 2 is inactive until pinned evidence gates pass"
)
NOTE_FEES_NEVER_SPONSORED = (
    "network signature fee and priority fee are funded by the persistent "
    "payer only; rent financing never covers fees"
)


def rent_exempt_minimum_lamports(data_len: int) -> int:
    """Exact canonical Solana rent-exempt minimum for ``data_len`` payload bytes.

    Equivalent to ``Rent::minimum_balance`` with the canonical defaults:
    floor((128 + data_len) * 3480 * 2.0).  The product is integral, so the
    floor is an exact integer multiplication.
    """

    if type(data_len) is not int or data_len < 0:
        raise RentSponsorPlannerError(
            (
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message="data_len must be a non-negative integer",
                ),
            )
        )
    return (ACCOUNT_METADATA_OVERHEAD_BYTES + data_len) * RENT_EXEMPT_LAMPORTS_PER_BYTE


TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM = rent_exempt_minimum_lamports(
    TOKEN_ACCOUNT_DATA_LEN
)
SYSTEM_ACCOUNT_RENT_EXEMPT_MINIMUM = rent_exempt_minimum_lamports(
    SYSTEM_ACCOUNT_DATA_LEN
)


class RentSponsorTier(StrEnum):
    REUSE_QUALIFIED_EXISTING = "reuse_qualified_existing"
    PROVIDER_SPONSORED = "provider_sponsored"
    SLUMLORD_EPHEMERAL = "slumlord_ephemeral"
    PERSISTENT_LOCAL_FUNDING = "persistent_local_funding"


class RentSponsorPlanStatus(StrEnum):
    """Offline planning outcome. Never implies live execution readiness."""

    PLANNED_OFFLINE_UNQUALIFIED = "planned_offline_unqualified"
    BLOCKED_INPUT_REQUIRED = "blocked_input_required"
    BLOCKED_POLICY = "blocked_policy"
    BLOCKED_ECONOMICS = "blocked_economics"


class RentSponsorCapacityStatus(StrEnum):
    """Live-capital capacity status, strictly separate from plan status.

    Mirrors the R-03 unsigned-builders contract: deliberately contains no
    execution-ready member.  Downstream simulation/qualification owners must
    promote a plan independently.
    """

    NOT_EVALUATED = "not_evaluated"
    PENDING_DOWNSTREAM_SIMULATION = "pending_downstream_simulation"
    CAPACITY_UNQUALIFIED = "capacity_unqualified"


class RentSponsorRejectionCode(StrEnum):
    RSP_INVALID_INPUT = "RSP_INVALID_INPUT"
    RSP_REUSE_UNQUALIFIED = "RSP_REUSE_UNQUALIFIED"
    RSP_SPONSOR_UNVERIFIED = "RSP_SPONSOR_UNVERIFIED"
    RSP_TEMP_NOT_EMPTYABLE = "RSP_TEMP_NOT_EMPTYABLE"
    RSP_TEMP_ALREADY_EXISTS = "RSP_TEMP_ALREADY_EXISTS"
    RSP_TIER_REQUEST_INVALID = "RSP_TIER_REQUEST_INVALID"
    RSP_SLUMLORD_UNAVAILABLE = "RSP_SLUMLORD_UNAVAILABLE"
    RSP_SLUMLORD_CAPACITY = "RSP_SLUMLORD_CAPACITY"
    RSP_RENT_SHORTFALL = "RSP_RENT_SHORTFALL"
    RSP_REPAYMENT_UNCOVERED = "RSP_REPAYMENT_UNCOVERED"
    RSP_LIFECYCLE_ORDER_INVALID = "RSP_LIFECYCLE_ORDER_INVALID"
    RSP_LIFECYCLE_ARITHMETIC_MISMATCH = "RSP_LIFECYCLE_ARITHMETIC_MISMATCH"
    RSP_ROUTE_UNAFFORDABLE = "RSP_ROUTE_UNAFFORDABLE"
    RSP_CU_BUDGET_EXCEEDED = "RSP_CU_BUDGET_EXCEEDED"
    RSP_MESSAGE_BYTES_EXCEEDED = "RSP_MESSAGE_BYTES_EXCEEDED"


class LamportFlowKind(StrEnum):
    RENT_BORROW_IN = "rent_borrow_in"  # Slumlord reserve -> temp account
    RENT_REFUND = "rent_refund"  # temp account close -> repayment source
    SLUMLORD_REPAY_OUT = "slumlord_repay_out"  # repayment source -> reserve
    SPONSOR_RENT_FUNDING = "sponsor_rent_funding"  # verified sponsor -> account
    PERSISTENT_RENT_FUNDING = "persistent_rent_funding"  # payer -> final output


class FeeLineKind(StrEnum):
    SIGNATURE_FEE = "signature_fee"
    PRIORITY_FEE = "priority_fee"


_POLICY_BLOCKERS = frozenset(
    {
        RentSponsorRejectionCode.RSP_REUSE_UNQUALIFIED,
        RentSponsorRejectionCode.RSP_SPONSOR_UNVERIFIED,
        RentSponsorRejectionCode.RSP_TEMP_NOT_EMPTYABLE,
        RentSponsorRejectionCode.RSP_TEMP_ALREADY_EXISTS,
        RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,
        RentSponsorRejectionCode.RSP_SLUMLORD_UNAVAILABLE,
        RentSponsorRejectionCode.RSP_SLUMLORD_CAPACITY,
        RentSponsorRejectionCode.RSP_RENT_SHORTFALL,
        RentSponsorRejectionCode.RSP_REPAYMENT_UNCOVERED,
        RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
        RentSponsorRejectionCode.RSP_LIFECYCLE_ARITHMETIC_MISMATCH,
    }
)
_ECONOMICS_BLOCKERS = frozenset(
    {
        RentSponsorRejectionCode.RSP_ROUTE_UNAFFORDABLE,
        RentSponsorRejectionCode.RSP_CU_BUDGET_EXCEEDED,
        RentSponsorRejectionCode.RSP_MESSAGE_BYTES_EXCEEDED,
    }
)


class RentSponsorPlannerError(ValueError):
    """Fail-closed planner error carrying typed rejections."""

    def __init__(self, rejections: Sequence["RentSponsorRejection"]) -> None:
        normalized = tuple(rejections)
        if not normalized:
            normalized = (
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message="planner error without typed rejection",
                ),
            )
        rendered = "; ".join(
            f"{rejection.code.value}: {rejection.message}" for rejection in normalized
        )
        super().__init__(rendered)
        self.rejections = normalized


@dataclass(frozen=True, slots=True)
class RentSponsorRejection:
    code: RentSponsorRejectionCode
    message: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RentSponsorProvenance:
    planner_version: str
    slumlord_upstream_repository: str
    slumlord_upstream_commit: str
    slumlord_instructions_blob: str
    slumlord_library_blob: str
    unsigned_builders_contract_version: str
    rent_constant_note: str


RENT_SPONSOR_PROVENANCE = RentSponsorProvenance(
    planner_version=RENT_SPONSOR_PLANNER_VERSION,
    slumlord_upstream_repository=SLUMLORD_UPSTREAM_REPOSITORY,
    slumlord_upstream_commit=SLUMLORD_UPSTREAM_COMMIT,
    slumlord_instructions_blob=SLUMLORD_INSTRUCTIONS_BLOB,
    slumlord_library_blob=SLUMLORD_LIBRARY_BLOB,
    unsigned_builders_contract_version=UNSIGNED_BUILDERS_CONTRACT_VERSION,
    rent_constant_note=RENT_CONSTANT_PROVENANCE_NOTE,
)


# --- Evidence and request DTOs -----------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenAccountQualification:
    """Tier-1 evidence for an existing token account (evidence-flagged).

    ``qualified`` must be set by an evidence owner that observed the account
    at ``observed_slot`` through ``evidence_source``.  The planner never
    upgrades unknown state to qualified.
    """

    observed_lamports: int
    data_len: int
    owner_program: str
    observed_slot: int
    evidence_source: str
    qualified: bool = False

    def __post_init__(self) -> None:
        _require_non_negative_int(self.observed_lamports, "qualification.observed_lamports")
        _require_non_negative_int(self.data_len, "qualification.data_len")
        _require_non_negative_int(self.observed_slot, "qualification.observed_slot")
        _require_pubkey(self.owner_program, "qualification.owner_program")
        if not isinstance(self.evidence_source, str) or not self.evidence_source.strip():
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="qualification.evidence_source is required",
                    ),
                )
            )


@dataclass(frozen=True, slots=True)
class ProviderSponsorshipClaim:
    """A caller claim that a provider sponsor exists. Never trusted as evidence."""

    provider: str
    evidence_slot: int | None = None
    evidence_blob_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSponsorshipProfile:
    provider: str
    verified_offline: bool
    note: str


# No provider rent sponsor is verified today; tier 2 is inactive.
KNOWN_PROVIDER_SPONSORS: dict[str, ProviderSponsorshipProfile] = {
    "0x_sponsor": ProviderSponsorshipProfile(
        provider="0x_sponsor",
        verified_offline=False,
        note="0x rent sponsor: no pinned offline evidence; tier inactive",
    ),
    "titan_payer": ProviderSponsorshipProfile(
        provider="titan_payer",
        verified_offline=False,
        note="Titan payer: no pinned offline evidence; tier inactive",
    ),
}


@dataclass(frozen=True, slots=True)
class InstructionRef:
    """Unsigned route-body instruction reference (label + shape only)."""

    label: str
    program_id: str
    data_len: int
    account_pubkeys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="instruction ref label is required",
                    ),
                )
            )
        _require_pubkey(self.program_id, f"instruction ref {self.label} program_id")
        _require_non_negative_int(self.data_len, f"instruction ref {self.label} data_len")
        object.__setattr__(self, "account_pubkeys", tuple(self.account_pubkeys))
        for index, pubkey in enumerate(self.account_pubkeys):
            _require_pubkey(pubkey, f"instruction ref {self.label} account {index}")


@dataclass(frozen=True, slots=True)
class EphemeralLifecycleRefs:
    """Token lifecycle references required for Slumlord-eligible temp accounts.

    ``drains_to_zero`` and ``closes_in_transaction`` must be asserted by the
    route owner; the planner refuses temporary accounts without them.
    """

    create_ref: InstructionRef
    drain_ref: InstructionRef
    close_ref: InstructionRef
    close_refund_destination: str
    drains_to_zero: bool = False
    closes_in_transaction: bool = False
    declared_close_refund_lamports: int | None = None

    def __post_init__(self) -> None:
        _require_pubkey(
            self.close_refund_destination, "lifecycle.close_refund_destination"
        )
        if self.declared_close_refund_lamports is not None:
            _require_non_negative_int(
                self.declared_close_refund_lamports,
                "lifecycle.declared_close_refund_lamports",
            )


@dataclass(frozen=True, slots=True)
class RouteAccountRequest:
    """One token account the route needs, with its tier eligibility inputs."""

    address: str
    data_len: int
    temporary: bool = False
    exists_today: bool = False
    qualification: TokenAccountQualification | None = None
    lifecycle: EphemeralLifecycleRefs | None = None
    requested_tier: RentSponsorTier | None = None
    note: str = ""

    def __post_init__(self) -> None:
        _require_pubkey(self.address, "route account address")
        _require_non_negative_int(self.data_len, "route account data_len")
        if self.temporary and self.exists_today:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="a temporary account cannot already exist",
                        detail=self.address,
                    ),
                )
            )


@dataclass(frozen=True, slots=True)
class RouteFeeInputs:
    required_signatures: int
    priority_fee_lamports: int
    estimated_compute_units: int

    def __post_init__(self) -> None:
        if type(self.required_signatures) is not int or self.required_signatures < 1:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="required_signatures must be a positive integer",
                    ),
                )
            )
        _require_non_negative_int(self.priority_fee_lamports, "priority_fee_lamports")
        if (
            type(self.estimated_compute_units) is not int
            or not 1 <= self.estimated_compute_units <= MAX_COMPUTE_UNITS
        ):
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message=(
                            "estimated_compute_units must be in "
                            f"[1, {MAX_COMPUTE_UNITS}]"
                        ),
                    ),
                )
            )


@dataclass(frozen=True, slots=True)
class RentSponsorPlanRequest:
    payer: str
    payer_lamports: int
    payer_evidence_slot: int
    accounts: tuple[RouteAccountRequest, ...]
    route_body: tuple[InstructionRef, ...]
    fee_inputs: RouteFeeInputs
    repayment_source: str | None = None
    repayment_source_lamports: int = 0
    slumlord_reserve: SlumlordReserveState | None = None
    sponsor_claim: ProviderSponsorshipClaim | None = None

    def __post_init__(self) -> None:
        _require_pubkey(self.payer, "payer")
        _require_non_negative_int(self.payer_lamports, "payer_lamports")
        _require_non_negative_int(self.payer_evidence_slot, "payer_evidence_slot")
        object.__setattr__(self, "accounts", tuple(self.accounts))
        object.__setattr__(self, "route_body", tuple(self.route_body))
        if not self.accounts:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="a route must request at least one account",
                    ),
                )
            )
        addresses = [account.address for account in self.accounts]
        if len(set(addresses)) != len(addresses):
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="route account addresses must be unique",
                    ),
                )
            )
        labels = [ref.label for ref in self.route_body]
        if len(set(labels)) != len(labels):
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="route body labels must be unique",
                    ),
                )
            )
        for ref in self.route_body:
            if ref.program_id == str(SLUMLORD_PROGRAM_ID):
                raise RentSponsorPlannerError(
                    (
                        RentSponsorRejection(
                            code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                            message=(
                                "route body must not carry Slumlord instructions; "
                                "the planner owns Slumlord placement"
                            ),
                        ),
                    )
                )
        if self.repayment_source is not None:
            _require_pubkey(self.repayment_source, "repayment_source")
            _require_non_negative_int(
                self.repayment_source_lamports, "repayment_source_lamports"
            )
        if self.slumlord_reserve is not None and not isinstance(
            self.slumlord_reserve, SlumlordReserveState
        ):
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="slumlord_reserve must be a SlumlordReserveState",
                    ),
                )
            )


# --- Plan DTOs ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccountTierBinding:
    """Account -> tier mapping with the rent arithmetic for that account."""

    address: str
    tier: RentSponsorTier
    rent_exempt_lamports: int
    newly_funded_lamports: int
    note: str = ""


@dataclass(frozen=True, slots=True)
class LamportFlow:
    kind: LamportFlowKind
    from_address: str
    to_address: str
    lamports: int
    tier: RentSponsorTier


@dataclass(frozen=True, slots=True)
class FeeLine:
    kind: FeeLineKind
    lamports: int
    covered_by: RentSponsorTier
    note: str = ""


@dataclass(frozen=True, slots=True)
class PlanInstructionRef:
    """One unsigned instruction reference in the final planned order."""

    label: str
    program_id: str
    data_len: int
    account_pubkeys: tuple[str, ...]


def assert_rent_capacity_never_execution_ready() -> None:
    """Guard: RentSponsorCapacityStatus must never admit live execution.

    Mirrors the R-03 unsigned-builders contract guard.  Rent-sponsor plans are
    unsigned offline planning artifacts; live qualification is owned by
    downstream simulation/qualification owners.
    """

    forbidden = ("execution_ready", "execution-ready", "live_admitted")
    for member in RentSponsorCapacityStatus.__members__:
        normalized = member.lower()
        if any(token in normalized for token in forbidden):
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message=(
                            "RentSponsorCapacityStatus must never contain an "
                            "execution-ready member"
                        ),
                    ),
                )
            )


@dataclass(frozen=True, slots=True)
class RentSponsorPlan:
    """Unsigned rent/fee plan DTO consumable by planner/simulation owners."""

    payer: str
    account_bindings: tuple[AccountTierBinding, ...]
    lamport_flows: tuple[LamportFlow, ...]
    fee_lines: tuple[FeeLine, ...]
    instruction_sequence: tuple[PlanInstructionRef, ...]
    estimated_message_bytes: int
    estimated_compute_units: int
    net_payer_lamports: int
    transient_repayment_buffer_lamports: int
    provenance: RentSponsorProvenance
    version: str
    planner_version: str
    slumlord_certificate: SlumlordOrderCertificate | None = None
    capacity_status: RentSponsorCapacityStatus = RentSponsorCapacityStatus.NOT_EVALUATED
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_pubkey(self.payer, "plan payer")
        object.__setattr__(self, "account_bindings", tuple(self.account_bindings))
        object.__setattr__(self, "lamport_flows", tuple(self.lamport_flows))
        object.__setattr__(self, "fee_lines", tuple(self.fee_lines))
        object.__setattr__(self, "instruction_sequence", tuple(self.instruction_sequence))
        object.__setattr__(self, "notes", tuple(self.notes))
        if not self.instruction_sequence:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message=(
                            "a built plan must carry a non-empty instruction "
                            "sequence (no fake PASS)"
                        ),
                    ),
                )
            )
        if not self.account_bindings:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="a built plan must carry account bindings",
                    ),
                )
            )
        if not self.fee_lines:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="a built plan must carry explicit fee lines",
                    ),
                )
            )
        _require_non_negative_int(self.estimated_message_bytes, "estimated_message_bytes")
        _require_non_negative_int(self.estimated_compute_units, "estimated_compute_units")
        _require_non_negative_int(self.net_payer_lamports, "net_payer_lamports")
        _require_non_negative_int(
            self.transient_repayment_buffer_lamports,
            "transient_repayment_buffer_lamports",
        )
        if self.estimated_message_bytes > MAX_PACKET_BYTES:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_MESSAGE_BYTES_EXCEEDED,
                        message=(
                            f"plan message bytes {self.estimated_message_bytes} "
                            f"exceed packet limit {MAX_PACKET_BYTES}"
                        ),
                    ),
                )
            )
        if self.estimated_compute_units > MAX_COMPUTE_UNITS:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_CU_BUDGET_EXCEEDED,
                        message=(
                            f"plan compute units {self.estimated_compute_units} "
                            f"exceed budget {MAX_COMPUTE_UNITS}"
                        ),
                    ),
                )
            )
        if self.capacity_status not in RentSponsorCapacityStatus:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="capacity_status is not a planner capacity status",
                    ),
                )
            )
        if self.version != RENT_SPONSOR_CONTRACT_VERSION:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="unsupported rent-sponsor contract version",
                    ),
                )
            )
        if self.planner_version != RENT_SPONSOR_PLANNER_VERSION:
            raise RentSponsorPlannerError(
                (
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message="unsupported planner version",
                    ),
                )
            )
        assert_rent_capacity_never_execution_ready()

    @property
    def build_fingerprint(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class RentSponsorPlanResult:
    """Built plan XOR typed blockers (never both, never neither)."""

    plan: RentSponsorPlan | None
    blockers: tuple[RentSponsorRejection, ...]
    status: RentSponsorPlanStatus
    inactive_tier_notes: tuple[tuple[RentSponsorTier, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "inactive_tier_notes", tuple(self.inactive_tier_notes))
        if self.plan is None:
            if not self.blockers:
                raise RentSponsorPlannerError(
                    (
                        RentSponsorRejection(
                            code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                            message="a blocked result must carry typed blockers",
                        ),
                    )
                )
            if self.status is RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED:
                raise RentSponsorPlannerError(
                    (
                        RentSponsorRejection(
                            code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                            message="a blocked result must not claim a built status",
                        ),
                    )
                )
        else:
            if self.blockers:
                raise RentSponsorPlannerError(
                    (
                        RentSponsorRejection(
                            code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                            message=(
                                "a built result must not carry blockers "
                                "(no fake PASS)"
                            ),
                        ),
                    )
                )
            if self.status is not RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED:
                raise RentSponsorPlannerError(
                    (
                        RentSponsorRejection(
                            code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                            message=(
                                "a built result must use the offline-unqualified status"
                            ),
                        ),
                    )
                )

    @property
    def blocker_codes(self) -> tuple[RentSponsorRejectionCode, ...]:
        return tuple(rejection.code for rejection in self.blockers)

    @property
    def build_fingerprint(self) -> str:
        return canonical_hash(self)


# --- Planner ------------------------------------------------------------------


def _require_non_negative_int(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise RentSponsorPlannerError(
            (
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message=f"{label} must be a non-negative integer",
                ),
            )
        )


def _require_pubkey(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RentSponsorPlannerError(
            (
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message=f"{label} is required",
                ),
            )
        )
    try:
        Pubkey.from_string(value)
    except Exception as exc:
        raise RentSponsorPlannerError(
            (
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message=f"{label} is not a valid base58 pubkey",
                    detail=value,
                ),
            )
        ) from exc


def estimate_message_bytes(
    sequence: Sequence[PlanInstructionRef],
    *,
    required_signatures: int,
) -> int:
    """Conservative upper-bound Solana legacy message byte estimate.

    Every variable-length encoding is charged the worst-case 3-byte
    compact-u16 width, so the estimate never undercounts a conforming
    legacy transaction.  Layout: signatures, header counts, static account
    key table, then per instruction (program index, account count, account
    indices, data length, data).
    """

    unique_accounts: set[str] = set()
    for ref in sequence:
        unique_accounts.update(ref.account_pubkeys)
    total = 3 + 64 * required_signatures  # signature count varint + signatures
    total += 3 * 3  # signed/readonly/total account counts in the header
    total += 3 + 32 * len(unique_accounts)  # static key table
    for ref in sequence:
        total += 3  # program id index varint (conservative width)
        total += 3  # account count varint (conservative width)
        total += 3 * len(ref.account_pubkeys)  # account index varints
        total += 3  # data length varint (conservative width)
        total += ref.data_len
    return total


_PLACEHOLDER_PROGRAM_ID = Pubkey.from_bytes(bytes((0xFF,)) * 32)


class RentSponsorPlanner:
    """Route-level rent/fee sourcing planner (offline, sender-free)."""

    def __init__(
        self,
        provenance: RentSponsorProvenance = RENT_SPONSOR_PROVENANCE,
    ) -> None:
        assert_rent_capacity_never_execution_ready()
        self._provenance = provenance

    def plan(self, request: RentSponsorPlanRequest) -> RentSponsorPlanResult:
        blockers: list[RentSponsorRejection] = []

        inactive_tier_notes: list[tuple[RentSponsorTier, str]] = [
            (RentSponsorTier.PROVIDER_SPONSORED, NOTE_SPONSOR_TIER_INACTIVE)
        ]
        notes: list[str] = [NOTE_FEES_NEVER_SPONSORED]

        # --- Tier 2 decision record: provider sponsorship is verified-only.
        sponsor_profile: ProviderSponsorshipProfile | None = None
        if request.sponsor_claim is not None:
            sponsor_profile = self._resolve_sponsor(
                request.sponsor_claim, blockers
            )

        # --- Per-account tier resolution in strict tier order.
        bindings: list[AccountTierBinding] = []
        flows: list[LamportFlow] = []
        sequence: list[PlanInstructionRef] = []
        slumlord_certificate: SlumlordOrderCertificate | None = None
        required_repayment_lamports = 0
        close_refund_lamports = 0
        transient_repayment_buffer = 0

        temp_accounts = [
            account for account in request.accounts if account.temporary
        ]
        if len(temp_accounts) > 1:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_SLUMLORD_CAPACITY,
                    message=(
                        "Slumlord permits exactly one Borrow/Repay/CheckRepaid "
                        f"per transaction; {len(temp_accounts)} temporary "
                        "accounts were requested"
                    ),
                    detail=temp_accounts[1].address,
                )
            )

        slumlord_used = False
        for account in request.accounts:
            if account.temporary:
                outcome = self._plan_temporary_account(
                    request,
                    account,
                    blockers=blockers,
                    slumlord_used=slumlord_used,
                )
                if outcome is None:
                    continue
                binding, account_flows, account_sequence, certificate = outcome
                if certificate is not None:
                    slumlord_used = True
                    slumlord_certificate = certificate
                    repay_flow = next(
                        (
                            flow
                            for flow in account_flows
                            if flow.kind is LamportFlowKind.SLUMLORD_REPAY_OUT
                        ),
                        None,
                    )
                    required_repayment_lamports = (
                        repay_flow.lamports if repay_flow is not None else 0
                    )
                    borrow_flow = next(
                        (
                            flow
                            for flow in account_flows
                            if flow.kind is LamportFlowKind.RENT_BORROW_IN
                        ),
                        None,
                    )
                    refund_flow = next(
                        (
                            flow
                            for flow in account_flows
                            if flow.kind is LamportFlowKind.RENT_REFUND
                        ),
                        None,
                    )
                    close_refund_lamports = (
                        refund_flow.lamports if refund_flow is not None else 0
                    )
                    if borrow_flow is None or borrow_flow.lamports < (
                        close_refund_lamports
                    ):
                        # Defense in depth: refund must equal the borrowed rent.
                        blockers.append(
                            RentSponsorRejection(
                                code=RentSponsorRejectionCode.RSP_LIFECYCLE_ARITHMETIC_MISMATCH,
                                message=(
                                    "close refund must equal the borrowed rent"
                                ),
                                detail=account.address,
                            )
                        )
                bindings.append(binding)
                flows.extend(account_flows)
                sequence.extend(account_sequence)
                continue

            # Persistent (final output) account path.
            persistent_outcome = self._plan_persistent_account(
                request, account, sponsor_profile, blockers
            )
            if persistent_outcome is None:
                continue
            binding, flow = persistent_outcome
            bindings.append(binding)
            if flow is not None:
                flows.append(flow)

        if slumlord_certificate is None:
            # Without an ephemeral account the planned order is the route
            # body itself (e.g. create-idempotent funded by tier 4).
            sequence = [_from_instruction_ref(ref) for ref in request.route_body]

        # --- Fee lines: always separately funded by the persistent payer.
        signature_fee_lamports = LAMPORTS_PER_SIGNATURE * (
            request.fee_inputs.required_signatures
        )
        fee_lines: list[FeeLine] = [
            FeeLine(
                kind=FeeLineKind.SIGNATURE_FEE,
                lamports=signature_fee_lamports,
                covered_by=RentSponsorTier.PERSISTENT_LOCAL_FUNDING,
                note=NOTE_FEES_NEVER_SPONSORED,
            ),
            FeeLine(
                kind=FeeLineKind.PRIORITY_FEE,
                lamports=request.fee_inputs.priority_fee_lamports,
                covered_by=RentSponsorTier.PERSISTENT_LOCAL_FUNDING,
                note=NOTE_FEES_NEVER_SPONSORED,
            ),
        ]

        # --- Route economics (fail-closed, evaluated even when blocked).
        # Ephemeral borrow lamports are returned by the same-transaction
        # close, so they are not part of the payer's persistent outflow.
        persistent_rent = sum(
            binding.newly_funded_lamports
            for binding in bindings
            if binding.tier is not RentSponsorTier.SLUMLORD_EPHEMERAL
        )
        net_payer_lamports = (
            persistent_rent + signature_fee_lamports
            + request.fee_inputs.priority_fee_lamports
        )
        if (
            request.repayment_source == request.payer
            and required_repayment_lamports > 0
        ):
            transient_repayment_buffer = max(
                0, required_repayment_lamports - close_refund_lamports
            )
        payer_outflow = net_payer_lamports + transient_repayment_buffer
        if payer_outflow > request.payer_lamports:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_ROUTE_UNAFFORDABLE,
                    message=(
                        f"payer needs {payer_outflow} lamports "
                        f"(persistent rent {persistent_rent} + fees "
                        f"{signature_fee_lamports} + "
                        f"{request.fee_inputs.priority_fee_lamports} + transient "
                        f"{transient_repayment_buffer}) but evidence shows only "
                        f"{request.payer_lamports}"
                    ),
                    detail=request.payer,
                )
            )

        if sequence:
            estimated_bytes = estimate_message_bytes(
                sequence, required_signatures=request.fee_inputs.required_signatures
            )
        else:
            estimated_bytes = 0
            if not blockers:
                blockers.append(
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                        message=(
                            "planned instruction sequence is empty "
                            "(no fake PASS)"
                        ),
                    )
                )
        if estimated_bytes > MAX_PACKET_BYTES and not any(
            rejection.code is RentSponsorRejectionCode.RSP_MESSAGE_BYTES_EXCEEDED
            for rejection in blockers
        ):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_MESSAGE_BYTES_EXCEEDED,
                    message=(
                        f"estimated message bytes {estimated_bytes} exceed the "
                        f"{MAX_PACKET_BYTES}-byte packet limit"
                    ),
                )
            )

        if blockers:
            return RentSponsorPlanResult(
                plan=None,
                blockers=tuple(blockers),
                status=self._blocked_status(blockers),
                inactive_tier_notes=tuple(inactive_tier_notes),
            )

        plan = RentSponsorPlan(
            payer=request.payer,
            account_bindings=tuple(bindings),
            lamport_flows=tuple(flows),
            fee_lines=tuple(fee_lines),
            instruction_sequence=tuple(sequence),
            estimated_message_bytes=estimated_bytes,
            estimated_compute_units=request.fee_inputs.estimated_compute_units,
            net_payer_lamports=net_payer_lamports,
            transient_repayment_buffer_lamports=transient_repayment_buffer,
            provenance=self._provenance,
            version=RENT_SPONSOR_CONTRACT_VERSION,
            planner_version=RENT_SPONSOR_PLANNER_VERSION,
            slumlord_certificate=slumlord_certificate,
            capacity_status=RentSponsorCapacityStatus.NOT_EVALUATED,
            notes=tuple(notes),
        )
        return RentSponsorPlanResult(
            plan=plan,
            blockers=(),
            status=RentSponsorPlanStatus.PLANNED_OFFLINE_UNQUALIFIED,
            inactive_tier_notes=tuple(inactive_tier_notes),
        )

    # --- Tier resolution helpers -----------------------------------------

    def _resolve_sponsor(
        self,
        claim: ProviderSponsorshipClaim,
        blockers: list[RentSponsorRejection],
    ) -> ProviderSponsorshipProfile | None:
        profile = KNOWN_PROVIDER_SPONSORS.get(claim.provider)
        if profile is None or not profile.verified_offline:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_SPONSOR_UNVERIFIED,
                    message=(
                        f"sponsor tier claimed for {claim.provider!r} without "
                        "verified offline evidence; tier 2 is inactive"
                    ),
                    detail=claim.provider,
                )
            )
            return None
        return profile

    def _plan_temporary_account(
        self,
        request: RentSponsorPlanRequest,
        account: RouteAccountRequest,
        *,
        blockers: list[RentSponsorRejection],
        slumlord_used: bool,
    ) -> tuple[
        AccountTierBinding,
        list[LamportFlow],
        list[PlanInstructionRef],
        SlumlordOrderCertificate | None,
    ] | None:
        """Attempt tier 3 for one temporary account; append blockers on failure."""

        if account.requested_tier not in (None, RentSponsorTier.SLUMLORD_EPHEMERAL):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,
                    message=(
                        "temporary accounts may only be offered the Slumlord "
                        "ephemeral tier"
                    ),
                    detail=account.address,
                )
            )
            return None
        if slumlord_used:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_SLUMLORD_CAPACITY,
                    message=(
                        "a second temporary account cannot share the single "
                        "Slumlord loan slot"
                    ),
                    detail=account.address,
                )
            )
            return None
        lifecycle = account.lifecycle
        if lifecycle is None or not lifecycle.drains_to_zero or (
            not lifecycle.closes_in_transaction
        ):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_TEMP_NOT_EMPTYABLE,
                    message=(
                        "temporary account must drain to zero and close inside "
                        "the transaction before Slumlord repayment"
                    ),
                    detail=account.address,
                )
            )
            return None
        if request.repayment_source is None:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message=(
                        "ephemeral rent financing requires a repayment source"
                    ),
                    detail=account.address,
                )
            )
            return None
        if request.slumlord_reserve is None:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_SLUMLORD_UNAVAILABLE,
                    message="no Slumlord reserve observation was provided",
                    detail=account.address,
                )
            )
            return None
        if account.address == request.repayment_source:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
                    message=(
                        "temporary account cannot be its own repayment source"
                    ),
                    detail=account.address,
                )
            )
            return None
        if lifecycle.close_refund_destination != request.repayment_source:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
                    message=(
                        "close refund destination must be the Slumlord "
                        "repayment source so the loan is repayable"
                    ),
                    detail=account.address,
                )
            )
            return None

        lifecycle_labels = {
            lifecycle.create_ref.label,
            lifecycle.drain_ref.label,
            lifecycle.close_ref.label,
        }
        body_labels = {ref.label for ref in request.route_body}
        reserved = "slumlord_"
        if any(label.startswith(reserved) for label in lifecycle_labels | body_labels):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message=(
                        f"instruction labels starting with {reserved!r} are "
                        "reserved for planner-owned Slumlord steps"
                    ),
                    detail=account.address,
                )
            )
            return None
        if len(lifecycle_labels) != 3:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_INVALID_INPUT,
                    message=(
                        "create, drain and close lifecycle refs must carry "
                        "distinct labels"
                    ),
                    detail=account.address,
                )
            )
            return None

        assert request.slumlord_reserve is not None
        assert request.repayment_source is not None
        assert lifecycle is not None
        try:
            prepared = prepare_rent_loan(
                request.slumlord_reserve,
                destination=Pubkey.from_string(account.address),
                repayment_source=Pubkey.from_string(request.repayment_source),
            )
        except SlumlordAdapterError as exc:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_SLUMLORD_UNAVAILABLE,
                    message=(
                        "Slumlord adapter rejected the ephemeral rent loan: "
                        f"{exc.code.value}: {exc}"
                    ),
                    detail=account.address,
                )
            )
            return None

        borrow_lamports = prepared.borrow_lamports
        required_repayment = prepared.required_repayment_lamports
        rent_minimum = rent_exempt_minimum_lamports(account.data_len)
        if borrow_lamports < rent_minimum:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_RENT_SHORTFALL,
                    message=(
                        f"Slumlord borrow {borrow_lamports} lamports cannot "
                        f"cover the {rent_minimum} rent-exempt minimum"
                    ),
                    detail=account.address,
                )
            )
            return None
        close_refund_lamports = borrow_lamports
        if (
            lifecycle.declared_close_refund_lamports is not None
            and lifecycle.declared_close_refund_lamports != close_refund_lamports
        ):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_LIFECYCLE_ARITHMETIC_MISMATCH,
                    message=(
                        f"declared close refund "
                        f"{lifecycle.declared_close_refund_lamports} differs "
                        f"from the arithmetic refund {close_refund_lamports} "
                        "(full account balance returns on close)"
                    ),
                    detail=account.address,
                )
            )
            return None
        available_after_refund = (
            request.repayment_source_lamports + close_refund_lamports
        )
        if available_after_refund < required_repayment:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_REPAYMENT_UNCOVERED,
                    message=(
                        f"repayment source holds {request.repayment_source_lamports} "
                        f"lamports; with the {close_refund_lamports} close refund "
                        f"it cannot cover the {required_repayment} Slumlord "
                        "repayment"
                    ),
                    detail=request.repayment_source,
                )
            )
            return None

        # Final order: Borrow -> create -> route body -> drain -> close ->
        # Repay -> CheckRepaid, certified by the Slumlord adapter itself.
        sequence: list[PlanInstructionRef] = [
            _slumlord_ref("slumlord_borrow", prepared.borrow_instruction),
            _from_instruction_ref(lifecycle.create_ref),
            *[_from_instruction_ref(ref) for ref in request.route_body],
            _from_instruction_ref(lifecycle.drain_ref),
            _from_instruction_ref(lifecycle.close_ref),
            _slumlord_ref("slumlord_repay", prepared.repay_instruction),
            _slumlord_ref("slumlord_check_repaid", prepared.check_repaid_instruction),
        ]
        certificate = self._certify_slumlord_order(
            sequence,
            prepared,
            blockers,
            drain_label=lifecycle.drain_ref.label,
            close_label=lifecycle.close_ref.label,
        )
        if certificate is None:
            return None

        binding = AccountTierBinding(
            address=account.address,
            tier=RentSponsorTier.SLUMLORD_EPHEMERAL,
            rent_exempt_lamports=rent_minimum,
            newly_funded_lamports=borrow_lamports,
            note=(
                "ephemeral rent financing: borrowed rent is returned by the "
                "same-transaction close and repaid to Slumlord before "
                "CheckRepaid; not trading capital and never a free-ATA claim"
            ),
        )
        flows = [
            LamportFlow(
                kind=LamportFlowKind.RENT_BORROW_IN,
                from_address=str(SLUMLORD_PDA),
                to_address=account.address,
                lamports=borrow_lamports,
                tier=RentSponsorTier.SLUMLORD_EPHEMERAL,
            ),
            LamportFlow(
                kind=LamportFlowKind.RENT_REFUND,
                from_address=account.address,
                to_address=request.repayment_source,
                lamports=close_refund_lamports,
                tier=RentSponsorTier.SLUMLORD_EPHEMERAL,
            ),
            LamportFlow(
                kind=LamportFlowKind.SLUMLORD_REPAY_OUT,
                from_address=request.repayment_source,
                to_address=str(SLUMLORD_PDA),
                lamports=required_repayment,
                tier=RentSponsorTier.SLUMLORD_EPHEMERAL,
            ),
        ]
        return binding, flows, sequence, certificate

    def _plan_persistent_account(
        self,
        request: RentSponsorPlanRequest,
        account: RouteAccountRequest,
        sponsor_profile: ProviderSponsorshipProfile | None,
        blockers: list[RentSponsorRejection],
    ) -> tuple[AccountTierBinding, LamportFlow | None] | None:
        """Tier order for a final output account: reuse -> sponsor -> persistent."""

        if account.requested_tier is RentSponsorTier.SLUMLORD_EPHEMERAL:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,
                    message=(
                        "persistent account offered to Slumlord: Slumlord is "
                        "rent financing for eligible temporary accounts only "
                        "and never funds accounts that must remain open"
                    ),
                    detail=account.address,
                )
            )
            return None

        rent_minimum = rent_exempt_minimum_lamports(account.data_len)

        # Tier 1: reuse a qualified existing token account.
        if account.exists_today:
            qualification = account.qualification
            if (
                qualification is None
                or not qualification.qualified
                or qualification.data_len != account.data_len
                or qualification.observed_lamports < rent_minimum
            ):
                blockers.append(
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_REUSE_UNQUALIFIED,
                        message=(
                            "existing account lacks qualification evidence "
                            "(observed lamports below the rent-exempt minimum "
                            "or evidence flag unset); unknown is not zero"
                        ),
                        detail=account.address,
                    )
                )
                return None
            if account.requested_tier not in (
                None,
                RentSponsorTier.REUSE_QUALIFIED_EXISTING,
            ):
                blockers.append(
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,
                        message=(
                            "requested tier does not match the resolved reuse "
                            "tier"
                        ),
                        detail=account.address,
                    )
                )
                return None
            binding = AccountTierBinding(
                address=account.address,
                tier=RentSponsorTier.REUSE_QUALIFIED_EXISTING,
                rent_exempt_lamports=rent_minimum,
                newly_funded_lamports=0,
                note=(
                    "reusing evidence-qualified existing token account "
                    f"(observed {qualification.observed_lamports} lamports at "
                    f"slot {qualification.observed_slot} via "
                    f"{qualification.evidence_source})"
                ),
            )
            return binding, None

        # Tier 2: verified provider sponsor (inactive today).
        if sponsor_profile is not None:
            if account.requested_tier not in (
                None,
                RentSponsorTier.PROVIDER_SPONSORED,
            ):
                blockers.append(
                    RentSponsorRejection(
                        code=RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,
                        message=(
                            "requested tier does not match the resolved sponsor "
                            "tier"
                        ),
                        detail=account.address,
                    )
                )
                return None
            binding = AccountTierBinding(
                address=account.address,
                tier=RentSponsorTier.PROVIDER_SPONSORED,
                rent_exempt_lamports=rent_minimum,
                newly_funded_lamports=0,
                note=f"sponsored by verified provider {sponsor_profile.provider}",
            )
            flow = LamportFlow(
                kind=LamportFlowKind.SPONSOR_RENT_FUNDING,
                from_address=sponsor_profile.provider,
                to_address=account.address,
                lamports=rent_minimum,
                tier=RentSponsorTier.PROVIDER_SPONSORED,
            )
            return binding, flow

        # Tier 4: ordinary persistent local funding.
        if account.requested_tier not in (
            None,
            RentSponsorTier.PERSISTENT_LOCAL_FUNDING,
        ):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_TIER_REQUEST_INVALID,
                    message=(
                        "requested tier does not match the resolved persistent "
                        "funding tier"
                    ),
                    detail=account.address,
                )
            )
            return None
        binding = AccountTierBinding(
            address=account.address,
            tier=RentSponsorTier.PERSISTENT_LOCAL_FUNDING,
            rent_exempt_lamports=rent_minimum,
            newly_funded_lamports=rent_minimum,
            note=(
                "final output account must remain open; funded persistently "
                "by the payer (never by Slumlord or a sponsor)"
            ),
        )
        flow = LamportFlow(
            kind=LamportFlowKind.PERSISTENT_RENT_FUNDING,
            from_address=request.payer,
            to_address=account.address,
            lamports=rent_minimum,
            tier=RentSponsorTier.PERSISTENT_LOCAL_FUNDING,
        )
        return binding, flow

    def _certify_slumlord_order(
        self,
        sequence: list[PlanInstructionRef],
        prepared: SlumlordPreparedRentLoan,
        blockers: list[RentSponsorRejection],
        *,
        drain_label: str,
        close_label: str,
    ) -> SlumlordOrderCertificate | None:
        """Certify the final order with the Slumlord adapter's own validator.

        Rebuilds the Slumlord Borrow/Repay/CheckRepaid instructions at their
        planned positions (route references become neutral placeholder
        instructions) and runs ``validate_slumlord_order``.  Also proves the
        drain and close references sit strictly between Borrow and Repay so
        the account is emptied and closed before repayment.
        """

        prepared_by_label = {
            "slumlord_borrow": prepared.borrow_instruction,
            "slumlord_repay": prepared.repay_instruction,
            "slumlord_check_repaid": prepared.check_repaid_instruction,
        }
        solders_sequence: list[Instruction] = []
        drain_index: int | None = None
        close_index: int | None = None
        for index, ref in enumerate(sequence):
            prepared_instruction = prepared_by_label.get(ref.label)
            if prepared_instruction is not None:
                solders_sequence.append(prepared_instruction)
            else:
                solders_sequence.append(
                    Instruction(_PLACEHOLDER_PROGRAM_ID, b"", [])
                )
                if ref.label == drain_label:
                    drain_index = index
                elif ref.label == close_label:
                    close_index = index
        try:
            certificate = validate_slumlord_order(solders_sequence)
        except SlumlordAdapterError as exc:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
                    message=(
                        "Slumlord order certificate failed: "
                        f"{exc.code.value}: {exc}"
                    ),
                )
            )
            return None
        if drain_index is None or close_index is None:
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
                    message=(
                        "drain and close references must exist between Borrow "
                        "and Repay"
                    ),
                )
            )
            return None
        if not (
            certificate.borrow_index < drain_index
            and drain_index < close_index
            and close_index < certificate.repay_index
        ):
            blockers.append(
                RentSponsorRejection(
                    code=RentSponsorRejectionCode.RSP_LIFECYCLE_ORDER_INVALID,
                    message=(
                        "account must be drained and closed strictly after "
                        "Borrow and strictly before Repay"
                    ),
                )
            )
            return None
        return certificate

    @staticmethod
    def _blocked_status(
        blockers: Sequence[RentSponsorRejection],
    ) -> RentSponsorPlanStatus:
        codes = {rejection.code for rejection in blockers}
        if RentSponsorRejectionCode.RSP_INVALID_INPUT in codes:
            return RentSponsorPlanStatus.BLOCKED_INPUT_REQUIRED
        if codes & _POLICY_BLOCKERS:
            return RentSponsorPlanStatus.BLOCKED_POLICY
        if codes & _ECONOMICS_BLOCKERS:
            return RentSponsorPlanStatus.BLOCKED_ECONOMICS
        return RentSponsorPlanStatus.BLOCKED_INPUT_REQUIRED


def _slumlord_ref(label: str, instruction: Instruction) -> PlanInstructionRef:
    return PlanInstructionRef(
        label=label,
        program_id=str(instruction.program_id),
        data_len=len(bytes(instruction.data)),
        account_pubkeys=tuple(str(meta.pubkey) for meta in instruction.accounts),
    )


def _from_instruction_ref(ref: InstructionRef) -> PlanInstructionRef:
    return PlanInstructionRef(
        label=ref.label,
        program_id=ref.program_id,
        data_len=ref.data_len,
        account_pubkeys=ref.account_pubkeys,
    )


__all__ = [
    "ACCOUNT_METADATA_OVERHEAD_BYTES",
    "KNOWN_PROVIDER_SPONSORS",
    "LAMPORTS_PER_BYTE_YEAR",
    "LAMPORTS_PER_SIGNATURE",
    "MAX_COMPUTE_UNITS",
    "MAX_PACKET_BYTES",
    "NOTE_FEES_NEVER_SPONSORED",
    "NOTE_SPONSOR_TIER_INACTIVE",
    "RENT_CONSTANT_PROVENANCE_NOTE",
    "RENT_EXEMPTION_THRESHOLD_YEARS",
    "RENT_EXEMPT_LAMPORTS_PER_BYTE",
    "RENT_SPONSOR_CONTRACT_VERSION",
    "RENT_SPONSOR_PLANNER_VERSION",
    "RENT_SPONSOR_PROVENANCE",
    "SYSTEM_ACCOUNT_DATA_LEN",
    "SYSTEM_ACCOUNT_RENT_EXEMPT_MINIMUM",
    "TOKEN_ACCOUNT_DATA_LEN",
    "TOKEN_ACCOUNT_RENT_EXEMPT_MINIMUM",
    "AccountTierBinding",
    "EphemeralLifecycleRefs",
    "FeeLine",
    "FeeLineKind",
    "InstructionRef",
    "LamportFlow",
    "LamportFlowKind",
    "PlanInstructionRef",
    "ProviderSponsorshipClaim",
    "ProviderSponsorshipProfile",
    "RentSponsorCapacityStatus",
    "RentSponsorPlan",
    "RentSponsorPlanRequest",
    "RentSponsorPlanResult",
    "RentSponsorPlanStatus",
    "RentSponsorPlanner",
    "RentSponsorPlannerError",
    "RentSponsorProvenance",
    "RentSponsorRejection",
    "RentSponsorRejectionCode",
    "RentSponsorTier",
    "RouteAccountRequest",
    "RouteFeeInputs",
    "TokenAccountQualification",
    "assert_rent_capacity_never_execution_ready",
    "estimate_message_bytes",
    "rent_exempt_minimum_lamports",
]
