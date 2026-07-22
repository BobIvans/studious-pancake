"""PR-149 sender-free canonical transaction proof gate.

Side-effect-free review contract for the snapshot-9 PR-149 scope. It does not
compile, simulate, sign, submit or call RPC; it only evaluates immutable evidence
that a later integration layer must produce.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "pr149.transaction-proof.v1"
RESULT_SCHEMA_VERSION = "pr149.transaction-proof-result.v1"
FULL_WIRE_LIMIT_BYTES = 1232
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PUB = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class InstructionFamily(StrEnum):
    SYSTEM = "system"
    ATA = "associated-token-account"
    SPL_TOKEN = "spl-token"
    TOKEN_2022 = "token-2022"
    JUPITER = "jupiter"
    MARGINFI = "marginfi"
    ROUTE = "route-program"


REQUIRED_FAMILIES = frozenset(
    {
        InstructionFamily.SYSTEM,
        InstructionFamily.ATA,
        InstructionFamily.SPL_TOKEN,
        InstructionFamily.TOKEN_2022,
        InstructionFamily.JUPITER,
        InstructionFamily.MARGINFI,
    }
)


class PR149ProofError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _is_sha(value: str | None) -> bool:
    return bool(value and _SHA.fullmatch(value))


def _is_pub(value: str | None) -> bool:
    return bool(value and _PUB.fullmatch(value))


def _sorted(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(values))


@dataclass(frozen=True)
class TransactionContract:
    count: int
    version: str
    full_wire_bytes: int
    expected_payer: str
    observed_payer: str
    expected_signers: tuple[str, ...]
    observed_signers: tuple[str, ...]
    expected_privileges_hash: str
    observed_privileges_hash: str
    expected_alt_hash: str
    observed_alt_hash: str
    alt_active: bool
    blockhash_valid: bool
    blockhash_context_slot: int
    min_context_slot: int
    last_valid_block_height: int
    compute_budget_instruction_count: int
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int
    get_fee_for_message_lamports: int | None
    landing_cost_cap_lamports: int
    estimated_landing_cost_lamports: int
    legacy: bool = False
    caller_adjustable_ceiling: bool = False
    sender_import_present: bool = False
    private_key_material_present: bool = False


@dataclass(frozen=True)
class InstructionContract:
    family: str
    program_id: str
    decoded: bool = True
    allowed: bool = True
    amount_atoms: int | None = None
    expected_amount_atoms: int | None = None
    authority: str | None = None
    expected_authority: str | None = None
    authority_change: bool = False
    arbitrary_transfer: bool = False
    close_or_delegate: bool = False


@dataclass(frozen=True)
class SimulationContract:
    accounts_hash: str
    owners_hash: str
    data_hash: str
    balances_hash: str
    token_balances_hash: str
    loaded_addresses_hash: str
    inner_instructions_hash: str
    logs_hash: str
    return_data_hash: str
    raw_evidence_bytes: int
    truncated: bool
    simulation_err: str | None
    provisional_compute_units: int
    final_compute_units: int


@dataclass(frozen=True)
class CpiContract:
    planned_programs: tuple[str, ...]
    top_level_programs: tuple[str, ...]
    observed_cpi_programs: tuple[str, ...]
    allowed_cpi_programs: tuple[str, ...]
    call_graph_hash: str


@dataclass(frozen=True)
class ReconciliationContract:
    principal_atoms: int
    required_repayment_atoms: int
    actual_repayment_atoms: int
    fees_lamports: int
    token_deltas_hash: str
    native_deltas_hash: str
    unauthorized_account_mutation: bool
    conservative_net_lamports: int


@dataclass(frozen=True)
class TransactionProofEvidence:
    transaction: TransactionContract
    instructions: tuple[InstructionContract, ...]
    simulation: SimulationContract
    cpi: CpiContract
    reconciliation: ReconciliationContract
    expected_route_programs: tuple[str, ...] = ()
    proof_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    def normalized(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transaction": asdict(self.transaction)
            | {
                "expected_signers": _sorted(self.transaction.expected_signers),
                "observed_signers": _sorted(self.transaction.observed_signers),
            },
            "instructions": [asdict(i) for i in self.instructions],
            "simulation": asdict(self.simulation),
            "cpi": asdict(self.cpi)
            | {
                "planned_programs": _sorted(self.cpi.planned_programs),
                "top_level_programs": _sorted(self.cpi.top_level_programs),
                "observed_cpi_programs": _sorted(self.cpi.observed_cpi_programs),
                "allowed_cpi_programs": _sorted(self.cpi.allowed_cpi_programs),
            },
            "reconciliation": asdict(self.reconciliation),
            "expected_route_programs": _sorted(self.expected_route_programs),
        }

    def canonical_hash(self) -> str:
        return sha256_json(self.normalized())


@dataclass(frozen=True)
class TransactionProofDecision:
    schema_version: str
    state: str
    review_ready: bool
    sender_free_transaction_proof_ready: bool
    sender_submission_allowed: bool
    live_claim_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    canonical_proof_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash(blockers: list[str], name: str, value: str | None) -> None:
    if not _is_sha(value):
        blockers.append(f"MALFORMED_SHA256:{name}")


def _eval_tx(tx: TransactionContract, b: list[str]) -> None:
    if tx.count != 1:
        b.append("NOT_ONE_TRANSACTION")
    if tx.version != "v0" or tx.legacy:
        b.append("NOT_CANONICAL_V0")
    if tx.full_wire_bytes <= 0 or tx.full_wire_bytes > FULL_WIRE_LIMIT_BYTES:
        b.append("FULL_WIRE_LIMIT")
    if tx.expected_payer != tx.observed_payer:
        b.append("PAYER_MISMATCH")
    if not _is_pub(tx.expected_payer) or not _is_pub(tx.observed_payer):
        b.append("BAD_PAYER_PUBKEY")
    if _sorted(tx.expected_signers) != _sorted(tx.observed_signers):
        b.append("SIGNER_SET_MISMATCH")
    if not tx.expected_signers or any(
        not _is_pub(s) for s in tx.expected_signers + tx.observed_signers
    ):
        b.append("BAD_SIGNER_SET")
    _hash(b, "expected_privileges_hash", tx.expected_privileges_hash)
    _hash(b, "observed_privileges_hash", tx.observed_privileges_hash)
    if tx.expected_privileges_hash != tx.observed_privileges_hash:
        b.append("ACCOUNT_PRIVILEGES_MISMATCH")
    _hash(b, "expected_alt_hash", tx.expected_alt_hash)
    _hash(b, "observed_alt_hash", tx.observed_alt_hash)
    if tx.expected_alt_hash != tx.observed_alt_hash or not tx.alt_active:
        b.append("ALT_PROOF_INVALID")
    if (
        not tx.blockhash_valid
        or tx.last_valid_block_height <= 0
        or tx.blockhash_context_slot < tx.min_context_slot
    ):
        b.append("BLOCKHASH_PROOF_INVALID")
    if (
        tx.compute_budget_instruction_count != 1
        or tx.compute_unit_limit <= 0
        or tx.compute_unit_price_micro_lamports < 0
    ):
        b.append("COMPUTE_FINALIZATION_INVALID")
    if tx.get_fee_for_message_lamports is None:
        b.append("FINAL_FEE_MISSING")
    if tx.estimated_landing_cost_lamports > tx.landing_cost_cap_lamports:
        b.append("LANDING_COST_CAP_EXCEEDED")
    if tx.caller_adjustable_ceiling:
        b.append("CALLER_ADJUSTABLE_CEILING")
    if tx.sender_import_present:
        b.append("SENDER_IMPORT_PRESENT")
    if tx.private_key_material_present:
        b.append("PRIVATE_KEY_MATERIAL_PRESENT")


def _eval_ix(
    instructions: tuple[InstructionContract, ...], routes: tuple[str, ...], b: list[str]
) -> None:
    seen: set[InstructionFamily] = set()
    if not instructions:
        b.append("INSTRUCTIONS_MISSING")
        return
    for idx, ix in enumerate(instructions):
        prefix = f"IX_{idx}"
        try:
            fam = InstructionFamily(ix.family)
        except ValueError:
            b.append(f"{prefix}_UNKNOWN_FAMILY")
            continue
        seen.add(fam)
        if not _is_pub(ix.program_id):
            b.append(f"{prefix}_BAD_PROGRAM_ID")
        if fam == InstructionFamily.ROUTE and ix.program_id not in routes:
            b.append(f"{prefix}_UNATTESTED_ROUTE_PROGRAM")
        if not ix.decoded:
            b.append(f"{prefix}_UNDECODED")
        if not ix.allowed:
            b.append(f"{prefix}_DISALLOWED")
        if ix.expected_amount_atoms is not None and ix.amount_atoms != ix.expected_amount_atoms:
            b.append(f"{prefix}_AMOUNT_MISMATCH")
        if ix.expected_authority is not None and ix.authority != ix.expected_authority:
            b.append(f"{prefix}_AUTHORITY_MISMATCH")
        if ix.authority_change or ix.arbitrary_transfer or ix.close_or_delegate:
            b.append(f"{prefix}_UNSAFE_MUTATION")
    for fam in sorted(REQUIRED_FAMILIES - seen):
        b.append(f"MISSING_REQUIRED_FAMILY:{fam.value}")


def _eval_sim(sim: SimulationContract, b: list[str]) -> None:
    for name in (
        "accounts_hash",
        "owners_hash",
        "data_hash",
        "balances_hash",
        "token_balances_hash",
        "loaded_addresses_hash",
        "inner_instructions_hash",
        "logs_hash",
        "return_data_hash",
    ):
        _hash(b, name, getattr(sim, name))
    if sim.raw_evidence_bytes <= 0:
        b.append("SIM_RAW_EVIDENCE_MISSING")
    if sim.truncated:
        b.append("SIM_EVIDENCE_TRUNCATED")
    if sim.simulation_err:
        b.append("SIMULATION_ERR")
    if sim.provisional_compute_units <= 0 or sim.final_compute_units <= 0:
        b.append("SIM_COMPUTE_MISSING")


def _eval_cpi(cpi: CpiContract, b: list[str]) -> None:
    planned, top, observed, allowed = map(
        set,
        (
            cpi.planned_programs,
            cpi.top_level_programs,
            cpi.observed_cpi_programs,
            cpi.allowed_cpi_programs,
        ),
    )
    if not planned:
        b.append("CPI_PLANNED_MISSING")
    if any(not _is_pub(p) for p in planned | top | observed | allowed):
        b.append("CPI_BAD_PROGRAM_ID")
    if planned - top:
        b.append("CPI_MISSING_TOP_LEVEL")
    if top - planned:
        b.append("CPI_UNEXPECTED_TOP_LEVEL")
    if observed - allowed:
        b.append("CPI_UNEXPECTED_PROGRAM")
    _hash(b, "call_graph_hash", cpi.call_graph_hash)


def _eval_recon(recon: ReconciliationContract, b: list[str]) -> None:
    if recon.principal_atoms <= 0:
        b.append("PRINCIPAL_MISSING")
    if recon.actual_repayment_atoms < recon.required_repayment_atoms:
        b.append("REPAYMENT_BELOW_REQUIRED")
    if recon.fees_lamports < 0:
        b.append("NEGATIVE_FEES")
    if recon.unauthorized_account_mutation:
        b.append("UNAUTHORIZED_ACCOUNT_MUTATION")
    _hash(b, "token_deltas_hash", recon.token_deltas_hash)
    _hash(b, "native_deltas_hash", recon.native_deltas_hash)


def evaluate_transaction_proof(evidence: TransactionProofEvidence) -> TransactionProofDecision:
    blockers: list[str] = []
    if evidence.schema_version != SCHEMA_VERSION:
        blockers.append("SCHEMA_VERSION_MISMATCH")
    _eval_tx(evidence.transaction, blockers)
    _eval_ix(evidence.instructions, evidence.expected_route_programs, blockers)
    _eval_sim(evidence.simulation, blockers)
    _eval_cpi(evidence.cpi, blockers)
    _eval_recon(evidence.reconciliation, blockers)
    canonical = evidence.canonical_hash()
    if evidence.proof_hash is not None:
        if not _is_sha(evidence.proof_hash):
            blockers.append("PROOF_HASH_MALFORMED")
        elif evidence.proof_hash != canonical:
            blockers.append("PROOF_HASH_MISMATCH")
    ready = not blockers
    return TransactionProofDecision(
        schema_version=RESULT_SCHEMA_VERSION,
        state="transaction-proof-review-ready" if ready else "blocked",
        review_ready=ready,
        sender_free_transaction_proof_ready=ready,
        sender_submission_allowed=False,
        live_claim_allowed=False,
        blockers=tuple(blockers),
        warnings=("PR149_REVIEW_ONLY_RUNTIME_UNCHANGED",),
        canonical_proof_hash=canonical,
    )


def assert_transaction_proof_review_ready(
    evidence: TransactionProofEvidence,
) -> TransactionProofDecision:
    decision = evaluate_transaction_proof(evidence)
    if not decision.review_ready:
        raise PR149ProofError("PR149_BLOCKED:" + ",".join(decision.blockers))
    return decision
