"""R05-S: offline unsigned-plan -> exact-simulation seam (read-only).

Converts R-03 unsigned builder plans (Jupiter Lend / Kamino Solana bookends,
NAVI Sui PTBs, and the Kamino ``flash_abi`` golden bytes) into the typed
instruction inputs consumed by the exact simulation owner
(:mod:`src.execution.exact_simulation`) WITHOUT executing anything:

- READ-ONLY: this module never compiles, signs, sends, fetches state, or runs
  :class:`~src.execution.exact_simulation.ExactSimulationFinalizer`. It only
  transforms already-built R-03 evidence into simulation-shaped inputs.
- BYTE-PRESERVATION: instruction data and account-metar order are carried
  verbatim from the R-03 bookend; a sha256 receipt over the exact data bytes
  is computed BEFORE and AFTER conversion and equality is enforced, so no
  code path can silently mutate the unsigned payload.
- TYPED PROVENANCE: every conversion binds the R-03 ``BuilderSourcePin``,
  build fingerprint, contract version and the seam version.
- BUILD ≠ CAPACITY ≠ SIMULATION: a converted input is discovery evidence with
  literal ``execution_authority=False`` semantics — the seam adds no capacity
  claim and no qualification claim.
- FAIL-CLOSED STATE: the live state context required by exact simulation
  (payer identity, recent blockhash, governed RPC state evidence) is
  explicitly MISSING. Every converted record carries ``state_evidence=None``
  and the typed gate reason
  :data:`SIM_SEAM_STATE_EVIDENCE_REQUIRED`. There is NO code path that
  produces a qualified state verdict (mirrors the provider live-capture
  verdicts); R-05 therefore stays BLOCKED and this seam does not pretend
  otherwise.
- SENDER-FREE: the R-03 contract is deliberately sender-free, so the seam
  never fabricates a payer or signers. Solana conversions stop at
  :class:`~src.execution.models.PlannedInstruction` records; assembling a
  full :class:`~src.execution.models.TransactionPlan` (which requires a payer
  and blockhash) is left to a later lane that owns live context — never here.
- SUI SCOPE: the exact simulation owner is Solana/Solders-only. NAVI PTBs are
  converted to evidence-only records under the typed surface state
  ``SUI_PTB_OUT_OF_SOLANA_SIMULATION_SCOPE`` — command payloads are
  fingerprinted, never re-encoded into Solana shapes.
- BLOCKED PLANS: R-03 plans whose ``build_status`` is not
  ``BUILT_OFFLINE_UNQUALIFIED`` carry no instructions to convert; the seam
  refuses to fabricate one and preserves the typed blockers instead.

No signing, no sending, no borrowing, no provider enablement, no boot-path
wiring. Unknown is never zero: an unknown required repayment stays ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path

from solders.instruction import AccountMeta, Instruction as SoldersInstruction
from solders.pubkey import Pubkey

from src.execution.models import PlannedInstruction
from src.lending.unsigned_builders.contract import (
    AccountMetaSpec,
    BookendKind,
    BuildStatus,
    BuilderSourcePin,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    UnsignedSolanaBookend,
    UNSIGNED_BUILDERS_CONTRACT_VERSION,
    canonical_hash,
    PtBuildResult,
)

__all__ = [
    "SIM_SEAM_STATE_EVIDENCE_REQUIRED",
    "SIM_SEAM_VERSION",
    "SimulationSeamError",
    "SimulationSeamErrorCode",
    "SimulationSeamProvenance",
    "SimulationSeamSurfaceState",
    "SimulationStateVerdict",
    "SolanaBookendSimulationInputs",
    "SuiPtbSimulationEvidence",
    "UnsignedPlanSimulationInputs",
    "convert_kamino_golden_fixture",
    "convert_pt_build_result",
    "convert_unsigned_borrow_plan",
    "convert_unsigned_repay_plan",
    "simulation_state_verdict",
]

SIM_SEAM_VERSION = "r05.sim-seam.v1"
#: Typed fail-closed gate reason: the live state context that exact simulation
#: requires (payer, recent blockhash, governed state RPC evidence) is explicitly
#: absent in this slice. No fixture, credential or environment variable can
#: produce it here.
SIM_SEAM_STATE_EVIDENCE_REQUIRED = "SIM_SEAM_STATE_EVIDENCE_REQUIRED"


class SimulationSeamErrorCode(StrEnum):
    """Typed fail-closed seam error codes."""

    INVALID_INPUT = "SIM_SEAM_INVALID_INPUT"
    BYTE_PRESERVATION_VIOLATION = "SIM_SEAM_BYTE_PRESERVATION_VIOLATION"
    NOT_BUILT = "SIM_SEAM_PLAN_NOT_BUILT"
    SUI_OUT_OF_SOLANA_SCOPE = "SIM_SEAM_SUI_OUT_OF_SOLANA_SCOPE"
    STATE_EVIDENCE_REQUIRED = "SIM_SEAM_STATE_EVIDENCE_REQUIRED"
    FIXTURE_SCHEMA_MISMATCH = "SIM_SEAM_FIXTURE_SCHEMA_MISMATCH"


class SimulationSeamError(ValueError):
    """Typed fail-closed seam error."""

    def __init__(self, code: SimulationSeamErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message


class SimulationSeamSurfaceState(StrEnum):
    """Typed conversion surface outcome (build ≠ capacity ≠ simulation)."""

    SOLANA_BOOKEND_CONVERTIBLE = "solana_bookend_convertible"
    SUI_PTB_OUT_OF_SOLANA_SIMULATION_SCOPE = "sui_ptb_out_of_solana_simulation_scope"
    BLOCKED_PLAN_NOT_CONVERTIBLE = "blocked_plan_not_convertible"


@dataclass(frozen=True, slots=True)
class SimulationSeamProvenance:
    """Typed provenance binding every conversion to its R-03 evidence."""

    provider: str
    chain: str
    source_pin: BuilderSourcePin
    build_fingerprint: str
    contract_version: str
    seam_version: str = SIM_SEAM_VERSION
    #: Literal missing-state marker: the live state context is UNKNOWN and is
    #: preserved as unknown, never coerced into a fake evidence value.
    state_evidence: None = None
    gate_reason: str = SIM_SEAM_STATE_EVIDENCE_REQUIRED

    def __post_init__(self) -> None:
        if not isinstance(self.source_pin, BuilderSourcePin):
            raise SimulationSeamError(
                SimulationSeamErrorCode.INVALID_INPUT,
                "provenance requires an R-03 BuilderSourcePin",
            )
        if self.state_evidence is not None:
            raise SimulationSeamError(
                SimulationSeamErrorCode.STATE_EVIDENCE_REQUIRED,
                "seam provenance can never carry state evidence in this slice",
            )
        if self.gate_reason != SIM_SEAM_STATE_EVIDENCE_REQUIRED:
            raise SimulationSeamError(
                SimulationSeamErrorCode.STATE_EVIDENCE_REQUIRED,
                "seam gate reason is frozen to SIM_SEAM_STATE_EVIDENCE_REQUIRED",
            )


@dataclass(frozen=True, slots=True)
class UnsignedPlanSimulationInputs:
    """Simulation-shaped inputs produced from one R-03 plan (read-only).

    ``instructions`` are :class:`~src.execution.models.PlannedInstruction`
    records — the exact instruction payload shape the exact simulation owner
    consumes inside a :class:`~src.execution.models.TransactionPlan`. The
    remaining ``missing_context`` members name the inputs the seam
    deliberately does NOT fabricate (sender-free R-03 contract; live state).
    """

    surface_state: SimulationSeamSurfaceState
    provenance: SimulationSeamProvenance
    instructions: tuple[PlannedInstruction, ...]
    missing_context: tuple[str, ...]
    data_receipts: tuple[str, ...]
    preserved_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.missing_context != _MISSING_CONTEXT:
            raise SimulationSeamError(
                SimulationSeamErrorCode.STATE_EVIDENCE_REQUIRED,
                "the missing-context declaration is frozen (payer, "
                "blockhash_context, state_evidence, rpc_authority)",
            )
        if (
            self.surface_state
            is SimulationSeamSurfaceState.SUI_PTB_OUT_OF_SOLANA_SIMULATION_SCOPE
        ):
            if self.instructions:
                raise SimulationSeamError(
                    SimulationSeamErrorCode.SUI_OUT_OF_SOLANA_SCOPE,
                    "Sui PTBs never re-encode into Solana instruction shapes",
                )

    @property
    def is_qualified_for_exact_simulation(self) -> bool:
        """Literal ``False``: this seam produces discovery inputs only.

        R-05 qualification is owned elsewhere and stays BLOCKED while the
        live state context is missing. There is no code path returning True.
        """
        return False


#: The frozen missing-context declaration. Exact simulation needs a caller
#: identity (payer), a recent-blockhash context, live state evidence and a
#: governed RPC authority — none of which an offline R-03 build can supply.
_MISSING_CONTEXT: tuple[str, ...] = (
    "payer",
    "blockhash_context",
    "state_evidence",
    "rpc_authority",
)


@dataclass(frozen=True, slots=True)
class SolanaBookendSimulationInputs:
    """Byte-preserving conversion of one Solana bookend instruction."""

    bookend_kind: str
    program_id: str
    data_hex: str
    account_metas: tuple[AccountMetaSpec, ...]
    instruction: PlannedInstruction
    data_sha256: str
    required_repayment_base_units: int | None  # None = UNKNOWN, never 0


@dataclass(frozen=True, slots=True)
class SuiPtbSimulationEvidence:
    """Evidence-only record for a Sui PTB (no Solana re-encoding)."""

    provider: str
    package_id: str
    command_fingerprints: tuple[str, ...]
    build_fingerprint: str


@dataclass(frozen=True, slots=True)
class SimulationStateVerdict:
    """Deterministic BLOCKED verdict: always, in this slice."""

    status: str
    reason: str
    seam_version: str
    qualified_plan_count: int


def simulation_state_verdict() -> SimulationStateVerdict:
    """Typed verdict that no converted plan is qualified for exact simulation.

    Mirrors the provider live-capture gates: R-05 qualification requires a
    human-authorized live-state capture lane outside this repository slice.
    No environment variable, credential, fixture or caller argument can flip
    this verdict — there is no code path that returns a qualified verdict.
    """
    return SimulationStateVerdict(
        status="BLOCKED",
        reason=SIM_SEAM_STATE_EVIDENCE_REQUIRED,
        seam_version=SIM_SEAM_VERSION,
        qualified_plan_count=0,
    )


def _data_sha256(data_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(data_hex)).hexdigest()


def _bookend_to_instruction(
    bookend: UnsignedSolanaBookend,
) -> SolanaBookendSimulationInputs:
    """Convert one bookend into a Solders instruction, byte-for-byte.

    ``bytes.fromhex(bookend.data_hex)`` is the SINGLE source of instruction
    data; the same bytes are hashed before conversion and re-hashed from the
    built Solders instruction afterwards — any drift raises a typed
    BYTE_PRESERVATION_VIOLATION instead of passing mutated evidence onward.
    """
    data = bytes.fromhex(bookend.data_hex)
    before = _data_sha256(bookend.data_hex)
    metas = tuple(
        AccountMeta(
            pubkey=Pubkey.from_string(meta.pubkey),
            is_signer=meta.is_signer,
            is_writable=meta.is_writable,
        )
        for meta in bookend.account_metas
    )
    instruction = SoldersInstruction(
        program_id=Pubkey.from_string(bookend.program_id),
        accounts=list(metas),
        data=data,
    )
    after = hashlib.sha256(bytes(instruction.data)).hexdigest()
    if before != after or bytes(instruction.data) != data:
        raise SimulationSeamError(
            SimulationSeamErrorCode.BYTE_PRESERVATION_VIOLATION,
            f"bookend {bookend.kind.value} instruction data drifted during "
            "conversion (byte-preservation violation)",
        )
    if [str(meta.pubkey) for meta in instruction.accounts] != [
        meta.pubkey for meta in bookend.account_metas
    ] or [(meta.is_signer, meta.is_writable) for meta in instruction.accounts] != [
        meta.flags for meta in bookend.account_metas
    ]:
        raise SimulationSeamError(
            SimulationSeamErrorCode.BYTE_PRESERVATION_VIOLATION,
            f"bookend {bookend.kind.value} account metas drifted during "
            "conversion (byte-preservation violation)",
        )
    return SolanaBookendSimulationInputs(
        bookend_kind=bookend.kind.value,
        program_id=bookend.program_id,
        data_hex=bookend.data_hex,
        account_metas=bookend.account_metas,
        instruction=PlannedInstruction(instruction=instruction, role="flash_bookend"),
        data_sha256=before,
        required_repayment_base_units=None,  # set by the caller plan below
    )


def _require_built(
    provider: str,
    build_status: BuildStatus,
    blockers: Sequence[str],
) -> None:
    if build_status is not BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        raise SimulationSeamError(
            SimulationSeamErrorCode.NOT_BUILT,
            f"{provider} plan is not BUILT_OFFLINE_UNQUALIFIED "
            f"(status {build_status.value}); nothing to convert and nothing "
            "may be fabricated — preserved blockers: "
            + (", ".join(blockers) or "none recorded"),
        )


def convert_unsigned_borrow_plan(
    plan: UnsignedBorrowPlan,
) -> UnsignedPlanSimulationInputs:
    """Convert one R-03 borrow plan into read-only simulation inputs.

    Byte-preservation is enforced on the bookend instruction data and account
    metas; an unknown required repayment stays ``None`` (unknown is never
    zero); the missing live-state context is declared, never fabricated.
    """
    blockers = tuple(violation.code.value for violation in plan.blockers)
    _require_built(plan.provider, plan.build_status, blockers)
    if plan.bookend is None:
        raise SimulationSeamError(
            SimulationSeamErrorCode.NOT_BUILT,
            f"{plan.provider} borrow plan carries no bookend (no fake PASS)",
        )
    bookend_inputs = _bookend_to_instruction(plan.bookend)
    inputs = SolanaBookendSimulationInputs(
        bookend_kind=bookend_inputs.bookend_kind,
        program_id=bookend_inputs.program_id,
        data_hex=bookend_inputs.data_hex,
        account_metas=bookend_inputs.account_metas,
        instruction=bookend_inputs.instruction,
        data_sha256=bookend_inputs.data_sha256,
        required_repayment_base_units=plan.required_repayment_base_units,
    )
    return UnsignedPlanSimulationInputs(
        surface_state=SimulationSeamSurfaceState.SOLANA_BOOKEND_CONVERTIBLE,
        provenance=SimulationSeamProvenance(
            provider=plan.provider,
            chain=plan.chain,
            source_pin=plan.source_pin,
            build_fingerprint=plan.build_fingerprint,
            contract_version=plan.contract_version,
        ),
        instructions=(inputs.instruction,),
        missing_context=_MISSING_CONTEXT,
        data_receipts=(inputs.data_sha256,),
        preserved_blockers=(),
    )


def convert_unsigned_repay_plan(
    plan: UnsignedRepayPlan,
) -> UnsignedPlanSimulationInputs:
    """Convert one R-03 repay plan into read-only simulation inputs."""
    blockers = tuple(violation.code.value for violation in plan.blockers)
    _require_built(plan.provider, plan.build_status, blockers)
    repay_bookend = plan.bookend
    if repay_bookend is None:
        raise SimulationSeamError(
            SimulationSeamErrorCode.NOT_BUILT,
            f"{plan.provider} repay plan carries no bookend (no fake PASS)",
        )
    bookend_inputs = _bookend_to_instruction(repay_bookend)
    inputs = SolanaBookendSimulationInputs(
        bookend_kind=bookend_inputs.bookend_kind,
        program_id=bookend_inputs.program_id,
        data_hex=bookend_inputs.data_hex,
        account_metas=bookend_inputs.account_metas,
        instruction=bookend_inputs.instruction,
        data_sha256=bookend_inputs.data_sha256,
        required_repayment_base_units=plan.required_repayment_base_units,
    )
    return UnsignedPlanSimulationInputs(
        surface_state=SimulationSeamSurfaceState.SOLANA_BOOKEND_CONVERTIBLE,
        provenance=SimulationSeamProvenance(
            provider=plan.provider,
            chain=plan.chain,
            source_pin=plan.source_pin,
            build_fingerprint=plan.build_fingerprint,
            contract_version=plan.contract_version,
        ),
        instructions=(inputs.instruction,),
        missing_context=_MISSING_CONTEXT,
        data_receipts=(inputs.data_sha256,),
        preserved_blockers=(),
    )


def convert_pt_build_result(result: PtBuildResult) -> UnsignedPlanSimulationInputs:
    """Convert a Sui PTB build result into EVIDENCE-ONLY seam inputs.

    The exact simulation owner is Solana/Solders-only; a Sui PTB is never
    re-encoded into Solana instruction shapes. The PTB's command payloads are
    preserved as canonical fingerprints (deterministic replay receipts), the
    typed surface state records the scope boundary, and the same missing
    live-state declaration applies.
    """
    blockers = tuple(violation.code.value for violation in result.blockers)
    _require_built(result.provider, result.build_status, blockers)
    if not result.commands:
        raise SimulationSeamError(
            SimulationSeamErrorCode.NOT_BUILT,
            f"{result.provider} PTB result carries no commands (no fake PASS)",
        )
    return UnsignedPlanSimulationInputs(
        surface_state=SimulationSeamSurfaceState.SUI_PTB_OUT_OF_SOLANA_SIMULATION_SCOPE,
        provenance=SimulationSeamProvenance(
            provider=result.provider,
            chain="sui",
            source_pin=result.source_pin,
            build_fingerprint=result.build_fingerprint,
            contract_version=result.contract_version,
        ),
        instructions=(),
        missing_context=_MISSING_CONTEXT,
        data_receipts=tuple(
            hashlib.sha256(canonical_hash(command).encode("utf-8")).hexdigest()
            for command in result.commands
        ),
        preserved_blockers=(),
    )


def convert_kamino_golden_fixture(
    fixture: Mapping[str, object] | str | Path,
) -> tuple[SolanaBookendSimulationInputs, SolanaBookendSimulationInputs]:
    """Convert the pinned Kamino flash-ABI golden bytes into seam inputs.

    The fixture (``tests/fixtures/r03/kamino_flash_abi_golden.json``) carries
    the pinned klend-sdk 13.0.2 generated flashBorrow/flashRepay payloads.
    Both bookends are converted byte-for-byte with discriminator checks and
    sha256 receipts; the on-chain program-settled flash fee is NOT encoded in
    instruction data, so the required repayment stays UNKNOWN (None) —
    unknown is never zero.
    """
    if isinstance(fixture, (str, Path)):
        raw = Path(fixture).read_text(encoding="utf-8")
        payload = json.loads(raw)
    elif isinstance(fixture, Mapping):
        payload = dict(fixture)
    else:
        raise SimulationSeamError(
            SimulationSeamErrorCode.INVALID_INPUT,
            "fixture must be a mapping or a JSON file path",
        )
    if payload.get("schema") != "r03.kamino.flashabi.golden.v1":
        raise SimulationSeamError(
            SimulationSeamErrorCode.FIXTURE_SCHEMA_MISMATCH,
            f"unexpected golden fixture schema {payload.get('schema')!r}",
        )
    program_id = payload.get("program_id")
    accounts = payload.get("accounts")
    expected_metas = payload.get("expected_metas")
    if not isinstance(program_id, str) or not isinstance(accounts, Mapping):
        raise SimulationSeamError(
            SimulationSeamErrorCode.FIXTURE_SCHEMA_MISMATCH,
            "golden fixture requires program_id and an accounts mapping",
        )
    if not isinstance(expected_metas, list) or not expected_metas:
        raise SimulationSeamError(
            SimulationSeamErrorCode.FIXTURE_SCHEMA_MISMATCH,
            "golden fixture requires the ordered expected_metas layout",
        )
    borrow_data = payload.get("borrow_data_hex")
    repay_data = payload.get("repay_data_hex")
    borrow_discriminator = payload.get("borrow_discriminator_hex")
    repay_discriminator = payload.get("repay_discriminator_hex")
    for label, value in (
        ("borrow_data_hex", borrow_data),
        ("repay_data_hex", repay_data),
        ("borrow_discriminator_hex", borrow_discriminator),
        ("repay_discriminator_hex", repay_discriminator),
    ):
        if not isinstance(value, str) or not value:
            raise SimulationSeamError(
                SimulationSeamErrorCode.FIXTURE_SCHEMA_MISMATCH,
                f"golden fixture field {label} is required",
            )
    metas = tuple(
        AccountMetaSpec(
            pubkey=str(meta.get("pubkey")),
            is_signer=bool(meta.get("is_signer")),
            is_writable=bool(meta.get("is_writable")),
        )
        for meta in expected_metas
    )
    borrow_bookend = UnsignedSolanaBookend(
        kind=BookendKind.BORROW,
        program_id=str(program_id),
        discriminator_hex=str(borrow_discriminator),
        data_hex=str(borrow_data),
        account_metas=metas,
    )
    repay_bookend = UnsignedSolanaBookend(
        kind=BookendKind.REPAY,
        program_id=str(program_id),
        discriminator_hex=str(repay_discriminator),
        data_hex=str(repay_data),
        account_metas=metas,
    )
    borrow_inputs = _bookend_to_instruction(borrow_bookend)
    repay_inputs = _bookend_to_instruction(repay_bookend)
    # The pinned fixture records a program-settled flash fee NOT encoded in
    # instruction data; the required repayment is therefore UNKNOWN here.
    return borrow_inputs, repay_inputs
