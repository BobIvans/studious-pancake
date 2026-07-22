"""PR-155 canonical transaction proof kernel.

Side-effect-free verifier for the renamed snapshot-9 PR-155 transaction proof
scope. It validates proof descriptors only: no compile, signing, RPC, sender or
live path is imported or enabled here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

WIRE_LIMIT_BYTES = 1232
SAFE_PROGRAMS = frozenset(
    {
        "system",
        "compute-budget",
        "associated-token-account",
        "spl-token",
        "token-2022",
        "jupiter",
        "marginfi",
        "route-program",
    }
)


class Decision(StrEnum):
    PROVEN = "PROVEN"
    BLOCKED = "BLOCKED"


class Reason(StrEnum):
    IDENTITY = "identity"
    SHAPE = "shape"
    HASH = "hash"
    INSTRUCTION = "instruction"
    COMPUTE = "compute"
    BLOCKHASH = "blockhash"
    ALT = "alt"
    SIMULATION = "simulation"
    CPI = "cpi"
    RECONCILIATION = "reconciliation"
    SENDER_SURFACE = "sender_surface"


@dataclass(frozen=True, slots=True)
class Failure:
    reason: Reason
    detail: str


@dataclass(frozen=True, slots=True)
class EvidenceHash:
    domain: str
    value: str


@dataclass(frozen=True, slots=True)
class InstructionProof:
    index: int
    program_id: str
    name: str
    source: str | None = None
    destination: str | None = None
    authority: str | None = None
    amount_atoms: int | None = None
    may_close: bool = False
    closes_account: bool = False
    raw_data_hash: EvidenceHash | None = None


@dataclass(frozen=True, slots=True)
class TransactionProof:
    schema_version: str
    cluster_genesis_hash: str
    candidate_hash: EvidenceHash
    plan_hash: EvidenceHash
    message_hash: EvidenceHash
    transaction_count: int
    transaction_version: str
    signed_wire_size_bytes: int
    expected_payer: str
    observed_payer: str
    expected_signers: tuple[str, ...]
    observed_signers: tuple[str, ...]
    planned_instructions: tuple[InstructionProof, ...]
    observed_instructions: tuple[InstructionProof, ...]
    compute_ix_counts: tuple[int, int, int]
    compute_units: int
    final_fee_lamports: int
    blockhash_valid: bool
    blockhash_not_expired: bool
    blockhash_context_ok: bool
    alt_hashes: tuple[EvidenceHash, ...]
    alt_reviewed: bool
    simulation_hashes: tuple[EvidenceHash, ...]
    simulation_units: int
    simulation_err: str | None
    simulation_truncated: bool
    planned_top_level_programs: tuple[str, ...]
    observed_top_level_programs: tuple[str, ...]
    observed_cpi_programs: tuple[str, ...]
    allowed_cpi_programs: tuple[str, ...]
    cpi_graph_hash: EvidenceHash
    principal_lamports: int
    flash_fee_lamports: int
    required_repayment_lamports: int
    conservative_net_lamports: int | None


@dataclass(frozen=True, slots=True)
class TransactionProofReport:
    decision: Decision
    failures: tuple[Failure, ...]
    proof_hash: str

    @property
    def proven(self) -> bool:
        return self.decision is Decision.PROVEN

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "proven": self.proven,
            "proof_hash": self.proof_hash,
            "failures": [asdict(item) for item in self.failures],
        }


def evaluate_transaction_proof(proof: TransactionProof) -> TransactionProofReport:
    failures: list[Failure] = []
    failures.extend(_identity(proof))
    failures.extend(_shape(proof))
    failures.extend(_instructions(proof))
    failures.extend(_compute(proof))
    failures.extend(_blockhash(proof))
    failures.extend(_alts(proof))
    failures.extend(_simulation(proof))
    failures.extend(_cpi(proof))
    failures.extend(_reconcile(proof))
    decision = Decision.BLOCKED if failures else Decision.PROVEN
    return TransactionProofReport(decision, tuple(failures), proof_hash(proof))


def proof_hash(proof: TransactionProof) -> str:
    payload = {"domain": "flashloan-bot/pr155/transaction-proof/v1", "proof": proof}
    encoded = json.dumps(_jsonable(payload), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def scan_for_sender_surface(source: str) -> tuple[Failure, ...]:
    tokens = ("Keypair", "sendTransaction", "send_transaction", "sign_fully")
    return tuple(
        Failure(Reason.SENDER_SURFACE, f"forbidden token: {token}")
        for token in tokens
        if token in source
    )


def _identity(proof: TransactionProof) -> list[Failure]:
    out: list[Failure] = []
    if not proof.schema_version or not proof.cluster_genesis_hash:
        out.append(Failure(Reason.IDENTITY, "schema and genesis are required"))
    for item in (proof.candidate_hash, proof.plan_hash, proof.message_hash):
        out.extend(_bad_hash(item))
    return out


def _shape(proof: TransactionProof) -> list[Failure]:
    out: list[Failure] = []
    if proof.transaction_count != 1:
        out.append(Failure(Reason.SHAPE, "exactly one transaction is required"))
    if proof.transaction_version != "v0":
        out.append(Failure(Reason.SHAPE, "only v0 transaction is accepted"))
    if (
        proof.signed_wire_size_bytes <= 0
        or proof.signed_wire_size_bytes > WIRE_LIMIT_BYTES
    ):
        out.append(Failure(Reason.SHAPE, "full signed wire must be <=1232 bytes"))
    if proof.expected_payer != proof.observed_payer or not proof.expected_payer:
        out.append(Failure(Reason.SHAPE, "payer mismatch"))
    if sorted(proof.expected_signers) != sorted(proof.observed_signers):
        out.append(Failure(Reason.SHAPE, "signer set mismatch"))
    return out


def _instructions(proof: TransactionProof) -> list[Failure]:
    if len(proof.planned_instructions) != len(proof.observed_instructions):
        return [Failure(Reason.INSTRUCTION, "instruction count mismatch")]
    out: list[Failure] = []
    pairs = zip(proof.planned_instructions, proof.observed_instructions)
    fields = (
        "index",
        "program_id",
        "name",
        "source",
        "destination",
        "authority",
        "amount_atoms",
    )
    for planned, observed in pairs:
        if observed.program_id not in SAFE_PROGRAMS:
            out.append(Failure(Reason.INSTRUCTION, "unknown program"))
        for field in fields:
            if getattr(planned, field) != getattr(observed, field):
                out.append(Failure(Reason.INSTRUCTION, f"{field} changed"))
        if observed.closes_account and not planned.may_close:
            out.append(Failure(Reason.INSTRUCTION, "unapproved account close"))
        if observed.raw_data_hash is not None:
            out.extend(_bad_hash(observed.raw_data_hash))
    return out


def _compute(proof: TransactionProof) -> list[Failure]:
    out: list[Failure] = []
    if proof.compute_ix_counts != (1, 1, 1):
        out.append(Failure(Reason.COMPUTE, "duplicate/missing compute ix"))
    if proof.compute_units <= 0 or proof.final_fee_lamports <= 0:
        out.append(Failure(Reason.COMPUTE, "positive compute and fee required"))
    return out


def _blockhash(proof: TransactionProof) -> list[Failure]:
    if (
        proof.blockhash_valid
        and proof.blockhash_not_expired
        and proof.blockhash_context_ok
    ):
        return []
    return [Failure(Reason.BLOCKHASH, "blockhash proof is invalid or stale")]


def _alts(proof: TransactionProof) -> list[Failure]:
    out: list[Failure] = []
    if not proof.alt_reviewed:
        out.append(Failure(Reason.ALT, "ALT evidence is not reviewed"))
    for item in proof.alt_hashes:
        out.extend(_bad_hash(item))
    return out


def _simulation(proof: TransactionProof) -> list[Failure]:
    out: list[Failure] = []
    for item in proof.simulation_hashes:
        out.extend(_bad_hash(item))
    if proof.simulation_err is not None:
        out.append(Failure(Reason.SIMULATION, "simulation returned error"))
    if proof.simulation_truncated:
        out.append(Failure(Reason.SIMULATION, "simulation evidence truncated"))
    if proof.simulation_units <= 0:
        out.append(Failure(Reason.SIMULATION, "simulation units missing"))
    return out


def _cpi(proof: TransactionProof) -> list[Failure]:
    out = _bad_hash(proof.cpi_graph_hash)
    if proof.planned_top_level_programs != proof.observed_top_level_programs:
        out.append(Failure(Reason.CPI, "top-level programs changed"))
    unexpected = set(proof.observed_cpi_programs) - set(proof.allowed_cpi_programs)
    if unexpected:
        out.append(Failure(Reason.CPI, "unexpected CPI program"))
    return out


def _reconcile(proof: TransactionProof) -> list[Failure]:
    expected = proof.principal_lamports + proof.flash_fee_lamports
    out: list[Failure] = []
    if proof.required_repayment_lamports != expected:
        out.append(Failure(Reason.RECONCILIATION, "flash fee not counted once"))
    if proof.conservative_net_lamports is None or proof.conservative_net_lamports < 0:
        out.append(Failure(Reason.RECONCILIATION, "non-negative net required"))
    return out


def _bad_hash(item: EvidenceHash) -> list[Failure]:
    value = item.value.strip().lower()
    bad = {"", "0", "0" * 64, "1" * 64, "todo", "deadbeef"}
    if not item.domain or "/" not in item.domain:
        return [Failure(Reason.HASH, "hash domain must be namespaced")]
    if value in bad or len(value) != 64:
        return [Failure(Reason.HASH, "placeholder hash")]
    try:
        int(value, 16)
    except ValueError:
        return [Failure(Reason.HASH, "hash is not hex sha256")]
    return []


def _jsonable(value: object) -> object:
    if isinstance(value, float):
        raise TypeError("binary float is not accepted in PR-155 proof")
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


CanonicalTransactionProof = TransactionProof

__all__ = [
    "CanonicalTransactionProof",
    "Decision",
    "EvidenceHash",
    "Failure",
    "InstructionProof",
    "Reason",
    "TransactionProof",
    "TransactionProofReport",
    "WIRE_LIMIT_BYTES",
    "evaluate_transaction_proof",
    "proof_hash",
    "scan_for_sender_surface",
]
