"""PR-197 sender-free economic execution proof gate.

This module is deliberately offline and side-effect free. It validates evidence that a
candidate flash-loan transaction has a single semantic plan, immutable message
identity, bounded simulation evidence and integer cost accounting before any
signer or sender boundary can consume it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

PR197_SCHEMA_VERSION = "pr197.economic-proof-gate.v1"
MAX_SOLANA_WIRE_BYTES = 1232

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ARTIFACT_HASHES = (
    "rooted_snapshot_hash",
    "route_plan_hash",
    "semantic_firewall_hash",
    "compiled_message_hash",
    "simulation_report_hash",
    "account_delta_hash",
    "fee_quote_hash",
    "economics_hash",
)
_REQUIRED_PLAN_SEQUENCE = (
    "setup",
    "flash_start",
    "borrow",
    "swap_a",
    "swap_b",
    "repay",
    "cleanup",
    "flash_end",
)
_FORBIDDEN_EFFECTS = {
    "system_transfer",
    "token_transfer_unbudgeted",
    "token_approve",
    "token_set_authority",
    "token_close_account_unapproved",
    "delegate_change",
    "authority_change",
}
_REQUIRED_DECODERS = {
    "marginfi",
    "jupiter",
    "system",
    "ata",
    "spl_token",
    "compute_budget",
}


class PR197EconomicProofError(ValueError):
    """Raised when PR-197 economic-proof evidence is malformed."""


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class EconomicProofDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class SemanticFirewallEvidence:
    decoders: frozenset[str]
    deny_unknown_instruction: bool
    exact_account_roles: bool
    exact_amount_binding: bool
    writable_delta_budget_enforced: bool
    forbidden_effect_fixtures: frozenset[str]
    mutation_rejection_coverage: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SemanticFirewallEvidence":
        return cls(
            decoders=frozenset(
                _non_empty(item, field=f"semantic_firewall.decoders[{index}]")
                for index, item in enumerate(
                    _list(raw.get("decoders"), "semantic_firewall.decoders")
                )
            ),
            deny_unknown_instruction=_bool(
                raw.get("deny_unknown_instruction"),
                "semantic_firewall.deny_unknown_instruction",
            ),
            exact_account_roles=_bool(
                raw.get("exact_account_roles"),
                "semantic_firewall.exact_account_roles",
            ),
            exact_amount_binding=_bool(
                raw.get("exact_amount_binding"),
                "semantic_firewall.exact_amount_binding",
            ),
            writable_delta_budget_enforced=_bool(
                raw.get("writable_delta_budget_enforced"),
                "semantic_firewall.writable_delta_budget_enforced",
            ),
            forbidden_effect_fixtures=frozenset(
                _non_empty(
                    item,
                    field=f"semantic_firewall.forbidden_effect_fixtures[{index}]",
                )
                for index, item in enumerate(
                    _list(
                        raw.get("forbidden_effect_fixtures"),
                        "semantic_firewall.forbidden_effect_fixtures",
                    )
                )
            ),
            mutation_rejection_coverage=_bool(
                raw.get("mutation_rejection_coverage"),
                "semantic_firewall.mutation_rejection_coverage",
            ),
        )

    def validate(self) -> tuple[EconomicProofDiagnostic, ...]:
        diagnostics: list[EconomicProofDiagnostic] = []
        missing_decoders = sorted(_REQUIRED_DECODERS - self.decoders)
        if missing_decoders:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "SEMANTIC_DECODER_MISSING",
                    DiagnosticSeverity.ERROR,
                    f"missing semantic decoders: {', '.join(missing_decoders)}",
                    "semantic_firewall.decoders",
                )
            )
        if not self.deny_unknown_instruction:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "UNKNOWN_INSTRUCTION_NOT_DENIED",
                    DiagnosticSeverity.ERROR,
                    "unknown instruction bytes must fail closed",
                    "semantic_firewall.deny_unknown_instruction",
                )
            )
        if not self.exact_account_roles:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ACCOUNT_ROLES_NOT_EXACT",
                    DiagnosticSeverity.ERROR,
                    "instruction account roles must be exact and ordered",
                    "semantic_firewall.exact_account_roles",
                )
            )
        if not self.exact_amount_binding:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "AMOUNT_BINDING_NOT_EXACT",
                    DiagnosticSeverity.ERROR,
                    "borrow, swap and repay amounts must be bound to evidence",
                    "semantic_firewall.exact_amount_binding",
                )
            )
        if not self.writable_delta_budget_enforced:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "WRITABLE_DELTA_BUDGET_MISSING",
                    DiagnosticSeverity.ERROR,
                    "writable account effects need explicit delta budgets",
                    "semantic_firewall.writable_delta_budget_enforced",
                )
            )
        missing_effects = sorted(_FORBIDDEN_EFFECTS - self.forbidden_effect_fixtures)
        if missing_effects:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "FORBIDDEN_EFFECT_FIXTURE_MISSING",
                    DiagnosticSeverity.ERROR,
                    "forbidden effect fixtures are incomplete",
                    "semantic_firewall.forbidden_effect_fixtures",
                )
            )
        if not self.mutation_rejection_coverage:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "MUTATION_REJECTION_COVERAGE_MISSING",
                    DiagnosticSeverity.ERROR,
                    "byte/account-meta mutation fixtures must deterministically reject",
                    "semantic_firewall.mutation_rejection_coverage",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class CompilerEvidence:
    transaction_version: str
    serialized_wire_bytes: int
    immutable_blockhash: bool
    immutable_alt_set: bool
    sign_fully_rechecks_size: bool
    public_apis_enforce_size: bool
    compiled_message_hash: str
    simulated_message_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CompilerEvidence":
        return cls(
            transaction_version=_non_empty(
                raw.get("transaction_version"),
                field="compiler.transaction_version",
            ),
            serialized_wire_bytes=_int(
                raw.get("serialized_wire_bytes"),
                "compiler.serialized_wire_bytes",
            ),
            immutable_blockhash=_bool(
                raw.get("immutable_blockhash"),
                "compiler.immutable_blockhash",
            ),
            immutable_alt_set=_bool(raw.get("immutable_alt_set"), "compiler.immutable_alt_set"),
            sign_fully_rechecks_size=_bool(
                raw.get("sign_fully_rechecks_size"),
                "compiler.sign_fully_rechecks_size",
            ),
            public_apis_enforce_size=_bool(
                raw.get("public_apis_enforce_size"),
                "compiler.public_apis_enforce_size",
            ),
            compiled_message_hash=_sha256(
                raw.get("compiled_message_hash"),
                "compiler.compiled_message_hash",
            ),
            simulated_message_hash=_sha256(
                raw.get("simulated_message_hash"),
                "compiler.simulated_message_hash",
            ),
        )

    def validate(self) -> tuple[EconomicProofDiagnostic, ...]:
        diagnostics: list[EconomicProofDiagnostic] = []
        if self.transaction_version not in {"legacy", "v0"}:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "UNSUPPORTED_TRANSACTION_VERSION",
                    DiagnosticSeverity.ERROR,
                    "only legacy and v0 have the current 1232-byte cap",
                    "compiler.transaction_version",
                )
            )
        if self.serialized_wire_bytes > MAX_SOLANA_WIRE_BYTES:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "WIRE_SIZE_LIMIT_EXCEEDED",
                    DiagnosticSeverity.ERROR,
                    "serialized transaction exceeds 1232 bytes",
                    "compiler.serialized_wire_bytes",
                )
            )
        if self.serialized_wire_bytes <= 0:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "WIRE_SIZE_INVALID",
                    DiagnosticSeverity.ERROR,
                    "serialized transaction size must be positive",
                    "compiler.serialized_wire_bytes",
                )
            )
        if not self.immutable_blockhash:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "BLOCKHASH_NOT_IMMUTABLE",
                    DiagnosticSeverity.ERROR,
                    "blockhash must be bound into immutable message identity",
                    "compiler.immutable_blockhash",
                )
            )
        if not self.immutable_alt_set:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ALT_SET_NOT_IMMUTABLE",
                    DiagnosticSeverity.ERROR,
                    "ALT set must be bound into immutable message identity",
                    "compiler.immutable_alt_set",
                )
            )
        if not self.sign_fully_rechecks_size:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "SIGN_FULLY_SIZE_BYPASS",
                    DiagnosticSeverity.ERROR,
                    "public sign_fully helper must recheck canonical size limit",
                    "compiler.sign_fully_rechecks_size",
                )
            )
        if not self.public_apis_enforce_size:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "PUBLIC_API_SIZE_BYPASS",
                    DiagnosticSeverity.ERROR,
                    "every public compile/sign API must reject oversized messages",
                    "compiler.public_apis_enforce_size",
                )
            )
        if self.compiled_message_hash != self.simulated_message_hash:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "SIMULATION_MESSAGE_MISMATCH",
                    DiagnosticSeverity.ERROR,
                    "simulation must use the exact compiled message hash",
                    "compiler.simulated_message_hash",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class SimulationEvidence:
    min_context_slot: int
    valid_blockhash: bool
    canonical_message_simulated: bool
    expected_invoke_graph_verified: bool
    account_state_bound: bool
    account_snapshots: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SimulationEvidence":
        snapshots = tuple(
            _mapping(item, f"simulation.account_snapshots[{index}]")
            for index, item in enumerate(
                _list(raw.get("account_snapshots"), "simulation.account_snapshots")
            )
        )
        return cls(
            min_context_slot=_int(raw.get("min_context_slot"), "simulation.min_context_slot"),
            valid_blockhash=_bool(raw.get("valid_blockhash"), "simulation.valid_blockhash"),
            canonical_message_simulated=_bool(
                raw.get("canonical_message_simulated"),
                "simulation.canonical_message_simulated",
            ),
            expected_invoke_graph_verified=_bool(
                raw.get("expected_invoke_graph_verified"),
                "simulation.expected_invoke_graph_verified",
            ),
            account_state_bound=_bool(
                raw.get("account_state_bound"),
                "simulation.account_state_bound",
            ),
            account_snapshots=snapshots,
        )

    def validate(self) -> tuple[EconomicProofDiagnostic, ...]:
        diagnostics: list[EconomicProofDiagnostic] = []
        if self.min_context_slot <= 0:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "MIN_CONTEXT_SLOT_INVALID",
                    DiagnosticSeverity.ERROR,
                    "simulation evidence must include a positive minContextSlot",
                    "simulation.min_context_slot",
                )
            )
        if not self.valid_blockhash:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "SIMULATION_BLOCKHASH_INVALID",
                    DiagnosticSeverity.ERROR,
                    "simulation must prove a valid blockhash",
                    "simulation.valid_blockhash",
                )
            )
        if not self.canonical_message_simulated:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "CANONICAL_MESSAGE_NOT_SIMULATED",
                    DiagnosticSeverity.ERROR,
                    "canonical compiled message must be the simulated payload",
                    "simulation.canonical_message_simulated",
                )
            )
        if not self.expected_invoke_graph_verified:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "INVOKE_GRAPH_NOT_VERIFIED",
                    DiagnosticSeverity.ERROR,
                    "expected MarginFi/Jupiter invoke graph must be verified",
                    "simulation.expected_invoke_graph_verified",
                )
            )
        if not self.account_state_bound:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ACCOUNT_STATE_NOT_BOUND",
                    DiagnosticSeverity.ERROR,
                    "economic observations must derive from bound raw account state",
                    "simulation.account_state_bound",
                )
            )
        if not self.account_snapshots:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ACCOUNT_SNAPSHOTS_MISSING",
                    DiagnosticSeverity.ERROR,
                    "simulation must bind account snapshots",
                    "simulation.account_snapshots",
                )
            )
        for index, snapshot in enumerate(self.account_snapshots):
            diagnostics.extend(_validate_account_snapshot(snapshot, index))
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class EconomicLedgerEvidence:
    rpc_total_message_fee_lamports: int
    explained_base_fee_lamports: int
    explained_priority_fee_lamports: int
    rent_lamports: int
    protocol_fee_lamports: int
    swap_fee_lamports: int
    tip_lamports: int
    contingency_lamports: int
    failed_landing_fee_lamports: int
    total_native_cost_lamports: int
    projected_profit_lamports: int

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EconomicLedgerEvidence":
        return cls(
            rpc_total_message_fee_lamports=_int(
                raw.get("rpc_total_message_fee_lamports"),
                "economics.rpc_total_message_fee_lamports",
            ),
            explained_base_fee_lamports=_int(
                raw.get("explained_base_fee_lamports"),
                "economics.explained_base_fee_lamports",
            ),
            explained_priority_fee_lamports=_int(
                raw.get("explained_priority_fee_lamports"),
                "economics.explained_priority_fee_lamports",
            ),
            rent_lamports=_int(raw.get("rent_lamports"), "economics.rent_lamports"),
            protocol_fee_lamports=_int(
                raw.get("protocol_fee_lamports"),
                "economics.protocol_fee_lamports",
            ),
            swap_fee_lamports=_int(raw.get("swap_fee_lamports"), "economics.swap_fee_lamports"),
            tip_lamports=_int(raw.get("tip_lamports"), "economics.tip_lamports"),
            contingency_lamports=_int(
                raw.get("contingency_lamports"),
                "economics.contingency_lamports",
            ),
            failed_landing_fee_lamports=_int(
                raw.get("failed_landing_fee_lamports"),
                "economics.failed_landing_fee_lamports",
            ),
            total_native_cost_lamports=_int(
                raw.get("total_native_cost_lamports"),
                "economics.total_native_cost_lamports",
            ),
            projected_profit_lamports=_int(
                raw.get("projected_profit_lamports"),
                "economics.projected_profit_lamports",
            ),
        )

    def validate(self) -> tuple[EconomicProofDiagnostic, ...]:
        diagnostics: list[EconomicProofDiagnostic] = []
        integer_fields = {
            "rpc_total_message_fee_lamports": self.rpc_total_message_fee_lamports,
            "explained_base_fee_lamports": self.explained_base_fee_lamports,
            "explained_priority_fee_lamports": self.explained_priority_fee_lamports,
            "rent_lamports": self.rent_lamports,
            "protocol_fee_lamports": self.protocol_fee_lamports,
            "swap_fee_lamports": self.swap_fee_lamports,
            "tip_lamports": self.tip_lamports,
            "contingency_lamports": self.contingency_lamports,
            "failed_landing_fee_lamports": self.failed_landing_fee_lamports,
            "total_native_cost_lamports": self.total_native_cost_lamports,
            "projected_profit_lamports": self.projected_profit_lamports,
        }
        for name, value in integer_fields.items():
            if value < 0:
                diagnostics.append(
                    EconomicProofDiagnostic(
                        "NEGATIVE_LAMPORT_VALUE",
                        DiagnosticSeverity.ERROR,
                        f"{name} must be non-negative",
                        f"economics.{name}",
                    )
                )
        explained_total = self.explained_base_fee_lamports + self.explained_priority_fee_lamports
        if explained_total != self.rpc_total_message_fee_lamports:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "MESSAGE_FEE_BREAKDOWN_MISMATCH",
                    DiagnosticSeverity.ERROR,
                    "base + priority explanation must equal RPC total message fee",
                    "economics.rpc_total_message_fee_lamports",
                )
            )
        expected_total = (
            self.rpc_total_message_fee_lamports
            + self.rent_lamports
            + self.protocol_fee_lamports
            + self.swap_fee_lamports
            + self.tip_lamports
            + self.contingency_lamports
            + self.failed_landing_fee_lamports
        )
        if expected_total != self.total_native_cost_lamports:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "NATIVE_COST_TOTAL_MISMATCH",
                    DiagnosticSeverity.ERROR,
                    "total native cost must include RPC total fee exactly once",
                    "economics.total_native_cost_lamports",
                )
            )
        if self.projected_profit_lamports <= self.total_native_cost_lamports:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "PROJECTED_PROFIT_INSUFFICIENT",
                    DiagnosticSeverity.ERROR,
                    "projected profit must exceed worst-case native cost",
                    "economics.projected_profit_lamports",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class PR197EconomicProofEvidence:
    schema_version: str
    artifact_hashes: Mapping[str, str]
    atomic_sequence: tuple[str, ...]
    semantic_firewall: SemanticFirewallEvidence
    compiler: CompilerEvidence
    simulation: SimulationEvidence
    economics: EconomicLedgerEvidence
    raw_state_decoder_is_sole_observation_source: bool
    token_2022_policy_fail_closed: bool
    signer_present: bool
    sender_present: bool
    live_enabled: bool
    raw: Mapping[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PR197EconomicProofEvidence":
        if not isinstance(raw, Mapping):
            raise PR197EconomicProofError("evidence root must be an object")
        schema = _non_empty(raw.get("schema_version"), field="schema_version")
        if schema != PR197_SCHEMA_VERSION:
            raise PR197EconomicProofError("unsupported PR-197 economic-proof schema")
        artifacts = _mapping(raw.get("artifact_hashes"), "artifact_hashes")
        return cls(
            schema_version=schema,
            artifact_hashes={str(key): str(value) for key, value in artifacts.items()},
            atomic_sequence=tuple(
                _non_empty(item, field=f"atomic_sequence[{index}]")
                for index, item in enumerate(_list(raw.get("atomic_sequence"), "atomic_sequence"))
            ),
            semantic_firewall=SemanticFirewallEvidence.from_dict(
                _mapping(raw.get("semantic_firewall"), "semantic_firewall")
            ),
            compiler=CompilerEvidence.from_dict(_mapping(raw.get("compiler"), "compiler")),
            simulation=SimulationEvidence.from_dict(
                _mapping(raw.get("simulation"), "simulation")
            ),
            economics=EconomicLedgerEvidence.from_dict(
                _mapping(raw.get("economics"), "economics")
            ),
            raw_state_decoder_is_sole_observation_source=_bool(
                raw.get("raw_state_decoder_is_sole_observation_source"),
                "raw_state_decoder_is_sole_observation_source",
            ),
            token_2022_policy_fail_closed=_bool(
                raw.get("token_2022_policy_fail_closed"),
                "token_2022_policy_fail_closed",
            ),
            signer_present=_bool(raw.get("signer_present"), "signer_present"),
            sender_present=_bool(raw.get("sender_present"), "sender_present"),
            live_enabled=_bool(raw.get("live_enabled"), "live_enabled"),
            raw=dict(raw),
        )

    def evidence_hash(self) -> str:
        encoded = json.dumps(
            self.raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def validate(self) -> tuple[EconomicProofDiagnostic, ...]:
        diagnostics: list[EconomicProofDiagnostic] = []
        diagnostics.extend(_validate_artifact_hashes(self.artifact_hashes))
        if self.atomic_sequence != _REQUIRED_PLAN_SEQUENCE:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ATOMIC_SEQUENCE_INVALID",
                    DiagnosticSeverity.ERROR,
                    "flash-loan plan sequence must match setup/start/borrow/swaps/repay/cleanup/end",
                    "atomic_sequence",
                )
            )
        diagnostics.extend(self.semantic_firewall.validate())
        diagnostics.extend(self.compiler.validate())
        diagnostics.extend(self.simulation.validate())
        diagnostics.extend(self.economics.validate())
        if not self.raw_state_decoder_is_sole_observation_source:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "CALLER_SUPPLIED_OBSERVATIONS_ALLOWED",
                    DiagnosticSeverity.ERROR,
                    "production reconciliation must derive observations only from raw state decoder",
                    "raw_state_decoder_is_sole_observation_source",
                )
            )
        if not self.token_2022_policy_fail_closed:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "TOKEN_2022_NOT_FAIL_CLOSED",
                    DiagnosticSeverity.ERROR,
                    "Token-2022 must fail closed until extension economics are proven",
                    "token_2022_policy_fail_closed",
                )
            )
        if self.signer_present:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "SIGNER_PRESENT_IN_PR197",
                    DiagnosticSeverity.ERROR,
                    "PR-197 must remain sender-free and signer-free",
                    "signer_present",
                )
            )
        if self.sender_present:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "SENDER_PRESENT_IN_PR197",
                    DiagnosticSeverity.ERROR,
                    "PR-197 must not include sender/submission capability",
                    "sender_present",
                )
            )
        if self.live_enabled:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "LIVE_ENABLED_IN_PR197",
                    DiagnosticSeverity.ERROR,
                    "PR-197 evidence gate cannot enable live execution",
                    "live_enabled",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class PR197EconomicProofReport:
    schema_version: str
    ok: bool
    evidence_hash: str
    diagnostics: tuple[EconomicProofDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "evidence_hash": self.evidence_hash,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "live_capability_allowed": live_capability_allowed(),
            "signer_capability_allowed": signer_capability_allowed(),
            "sender_capability_allowed": sender_capability_allowed(),
        }


def validate_pr197_economic_proof(
    evidence: Mapping[str, Any],
) -> PR197EconomicProofReport:
    parsed = PR197EconomicProofEvidence.from_dict(evidence)
    diagnostics = parsed.validate()
    return PR197EconomicProofReport(
        schema_version=parsed.schema_version,
        ok=not any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics),
        evidence_hash=parsed.evidence_hash(),
        diagnostics=tuple(diagnostics),
    )


def live_capability_allowed() -> bool:
    """PR-197 is a sender-free proof gate and never opens live capability."""

    return False


def signer_capability_allowed() -> bool:
    """PR-197 cannot access private keys or signer backends."""

    return False


def sender_capability_allowed() -> bool:
    """PR-197 cannot submit transactions."""

    return False


def _validate_artifact_hashes(
    artifact_hashes: Mapping[str, str],
) -> tuple[EconomicProofDiagnostic, ...]:
    diagnostics: list[EconomicProofDiagnostic] = []
    for name in _REQUIRED_ARTIFACT_HASHES:
        value = artifact_hashes.get(name)
        if value is None:
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ARTIFACT_HASH_MISSING",
                    DiagnosticSeverity.ERROR,
                    f"required artifact hash {name!r} is missing",
                    f"artifact_hashes.{name}",
                )
            )
            continue
        if not _SHA256_RE.fullmatch(value.lower()):
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ARTIFACT_HASH_INVALID",
                    DiagnosticSeverity.ERROR,
                    f"artifact hash {name!r} must be sha256 hex",
                    f"artifact_hashes.{name}",
                )
            )
    return tuple(diagnostics)


def _validate_account_snapshot(
    snapshot: Mapping[str, Any],
    index: int,
) -> tuple[EconomicProofDiagnostic, ...]:
    diagnostics: list[EconomicProofDiagnostic] = []
    path = f"simulation.account_snapshots[{index}]"
    for key in ("address", "owner", "data_hash"):
        value = snapshot.get(key)
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                EconomicProofDiagnostic(
                    "ACCOUNT_SNAPSHOT_FIELD_MISSING",
                    DiagnosticSeverity.ERROR,
                    f"account snapshot field {key!r} is required",
                    f"{path}.{key}",
                )
            )
    data_hash = snapshot.get("data_hash")
    if isinstance(data_hash, str) and not _SHA256_RE.fullmatch(data_hash.lower()):
        diagnostics.append(
            EconomicProofDiagnostic(
                "ACCOUNT_DATA_HASH_INVALID",
                DiagnosticSeverity.ERROR,
                "account data hash must be sha256 hex",
                f"{path}.data_hash",
            )
        )
    lamports = snapshot.get("lamports")
    if isinstance(lamports, bool) or not isinstance(lamports, int) or lamports < 0:
        diagnostics.append(
            EconomicProofDiagnostic(
                "ACCOUNT_LAMPORTS_INVALID",
                DiagnosticSeverity.ERROR,
                "account lamports must be a non-negative integer",
                f"{path}.lamports",
            )
        )
    return tuple(diagnostics)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PR197EconomicProofError(f"{field} must be an object")
    return value


def _list(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise PR197EconomicProofError(f"{field} must be a list")
    return value


def _sha256(value: object, field: str) -> str:
    text = _non_empty(value, field=field).lower()
    if not _SHA256_RE.fullmatch(text):
        raise PR197EconomicProofError(f"{field} must be sha256 hex")
    return text


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PR197EconomicProofError(f"{field} must be boolean")
    return value


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR197EconomicProofError(f"{field} must be an integer")
    return value


def _non_empty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR197EconomicProofError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "DiagnosticSeverity",
    "EconomicLedgerEvidence",
    "EconomicProofDiagnostic",
    "MAX_SOLANA_WIRE_BYTES",
    "PR197EconomicProofError",
    "PR197EconomicProofEvidence",
    "PR197EconomicProofReport",
    "PR197_SCHEMA_VERSION",
    "SemanticFirewallEvidence",
    "SimulationEvidence",
    "CompilerEvidence",
    "live_capability_allowed",
    "sender_capability_allowed",
    "signer_capability_allowed",
    "validate_pr197_economic_proof",
]
