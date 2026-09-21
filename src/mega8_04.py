"""MEGA8-04 offline assurance, multichain research and release-audit contracts.

PR-209..PR-222 / NF-585..NF-640. This module is an effect-free integration
facade over existing canonical owners. It never loads keys, signs, submits,
mutates remote state, enables live trading, or raises capital permissions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Callable, Iterable, Mapping, Sequence

MEGA804_SCHEMA = "mega8-04.assurance.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_RELEASE_STATUSES = frozenset(
    {
        "MERGED_AND_VERIFIED",
        "COVERED_BY_EXISTING",
        "RESEARCH_ONLY",
        "BLOCKED",
        "DEFERRED",
    }
)
_EFFECT_CAPABILITIES = frozenset(
    {"SIGN", "SEND", "SUBMIT", "PRIVATE_KEY", "CAPITAL_WRITE", "POLICY_WRITE"}
)


class Mega804Error(ValueError):
    """Malformed or unsafe MEGA8-04 evidence."""


class Disposition(StrEnum):
    PASS = "pass"
    RESEARCH_ONLY = "research_only"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class AssuranceEvidence:
    nf_id: str
    disposition: Disposition
    evidence_digest: str
    blockers: tuple[str, ...] = ()
    live_enabled: bool = False
    signing_enabled: bool = False
    submission_enabled: bool = False


@dataclass(frozen=True, slots=True)
class SimulationEngineResult:
    engine: str
    success: bool
    post_state_sha256: str
    net_base_units: int
    trace_sha256: str


@dataclass(frozen=True, slots=True)
class FaultScenario:
    kind: str
    target: str
    generation: str


@dataclass(frozen=True, slots=True)
class DependencyRecord:
    name: str
    version: str
    license_id: str
    source_identity: str
    artifact_sha256: str


@dataclass(frozen=True, slots=True)
class SignedEvidenceRecord:
    sequence: int
    payload_sha256: str
    previous_record_sha256: str | None
    signer_identity: str
    signature_evidence_sha256: str

    @property
    def record_sha256(self) -> str:
        return _digest(
            (
                self.sequence,
                self.payload_sha256,
                self.previous_record_sha256,
                self.signer_identity,
                self.signature_evidence_sha256,
            )
        )


@dataclass(frozen=True, slots=True)
class HsmSignerProfile:
    provider: str
    key_reference_sha256: str
    generation: int
    region: str
    permit_semantics_sha256: str
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class EvmDexAdapter:
    adapter_id: str
    deployment: str
    math_version: str
    source_commit: str
    license_id: str
    research_only: bool = True
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class CallbackSettlementPrimitive:
    primitive_id: str
    deployment: str
    repayment_asset: str
    max_borrow_base_units: int
    research_only: bool = True


@dataclass(frozen=True, slots=True)
class SuiObjectState:
    object_id: str
    version: int
    digest: str
    shared: bool
    mutable: bool


@dataclass(frozen=True, slots=True)
class SuiObjectStateFrame:
    chain_id: str
    checkpoint: int
    objects: tuple[SuiObjectState, ...]
    frame_sha256: str


@dataclass(frozen=True, slots=True)
class CrosschainAssetRight:
    canonical_asset_id: str
    source_chain: str
    destination_chain: str
    custody_model: str
    bridge_identity: str
    finality_model: str
    research_only: bool = True


@dataclass(frozen=True, slots=True)
class VerifiedPrimitive:
    name: str
    capability_sha256: str
    chain: str
    research_only: bool = True


@dataclass(frozen=True, slots=True)
class StrategyDsl:
    version: str
    primitives: tuple[VerifiedPrimitive, ...]
    signer_free: bool = True


@dataclass(frozen=True, slots=True)
class CoverageRow:
    roadmap_pr: int
    status: str
    owner: str
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class Post150Audit:
    covered_count: int
    blocked_prs: tuple[int, ...]
    deferred_prs: tuple[int, ...]
    research_only_prs: tuple[int, ...]
    missing_prs: tuple[int, ...]
    evidence_digest: str
    release_claim_allowed: bool = False
    production_ready: bool = False
    live_enabled: bool = False


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Mega804Error(f"{field} must be lowercase sha256")
    return value


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Mega804Error(f"{field} is required")
    return value


def _uint(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Mega804Error(f"{field} must be a non-negative integer")
    return value


def _ev(
    nf_id: str,
    disposition: Disposition,
    payload: object,
    blockers: Iterable[str] = (),
) -> AssuranceEvidence:
    return AssuranceEvidence(
        nf_id=nf_id,
        disposition=disposition,
        evidence_digest=_digest((MEGA804_SCHEMA, nf_id, payload)),
        blockers=tuple(dict.fromkeys(blockers)),
    )


# PR-209 / VERIFY-01 / NF-585..588
def define_property_financial_invariants() -> tuple[str, ...]:
    return (
        "integer_base_units_only",
        "asset_conservation",
        "repayment_obligation_satisfied",
        "reservation_not_double_spent",
        "unknown_outcome_holds_reservation",
        "finalized_economics_only",
        "no_implicit_live_promotion",
    )


def generate_stateful_test_sequences(
    *, seed: str, operations: Sequence[str], steps: int
) -> tuple[tuple[str, ...], ...]:
    _text(seed, "seed")
    if not operations or not 1 <= steps <= 64:
        raise Mega804Error("operations required and steps must be in [1, 64]")
    ops = tuple(_text(item, "operation") for item in operations)
    rows = []
    for variant in range(min(16, len(ops) * 2)):
        row = []
        for index in range(steps):
            raw = sha256(f"{seed}:{variant}:{index}".encode()).digest()
            row.append(ops[int.from_bytes(raw[:4], "big") % len(ops)])
        rows.append(tuple(row))
    return tuple(rows)


def shrink_failing_economic_case(
    sequence: Sequence[str], *, still_fails: Callable[[tuple[str, ...]], bool]
) -> tuple[str, ...]:
    current = tuple(sequence)
    if not current or not still_fails(current):
        raise Mega804Error("input must reproduce the failure")
    changed = True
    while changed and len(current) > 1:
        changed = False
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1 :]
            if candidate and still_fails(candidate):
                current = candidate
                changed = True
                break
    return current


def promote_invariant_regression(
    *, counterexample_sha256: str, reproductions: int
) -> AssuranceEvidence:
    _sha(counterexample_sha256, "counterexample_sha256")
    blocked = reproductions < 2
    return _ev(
        "NF-588",
        Disposition.BLOCKED if blocked else Disposition.PASS,
        (counterexample_sha256, reproductions),
        ("COUNTEREXAMPLE_NOT_REPRODUCIBLE",) if blocked else (),
    )


# PR-210 / VERIFY-02 / NF-589..592
def mutate_transaction_instructions(
    instructions: Sequence[str], *, mutation_index: int, replacement: str
) -> tuple[str, ...]:
    items = list(instructions)
    if not items or not 0 <= mutation_index < len(items):
        raise Mega804Error("mutation_index outside instruction sequence")
    items[mutation_index] = _text(replacement, "replacement")
    return tuple(items)


def fuzz_account_meta_permissions(
    original: Mapping[str, tuple[bool, bool]],
    mutated: Mapping[str, tuple[bool, bool]],
) -> AssuranceEvidence:
    blockers = []
    for account, (signer, writable) in mutated.items():
        old_signer, old_writable = original.get(account, (False, False))
        if signer and not old_signer:
            blockers.append(f"SIGNER_ESCALATION:{account}")
        if writable and not old_writable:
            blockers.append(f"WRITABLE_ESCALATION:{account}")
    return _ev(
        "NF-590",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        sorted(mutated.items()),
        blockers,
    )


def fuzz_parser_and_decoder_boundaries(
    payload: bytes, *, max_bytes: int
) -> AssuranceEvidence:
    if max_bytes < 1:
        raise Mega804Error("max_bytes must be positive")
    blockers = []
    if len(payload) > max_bytes:
        blockers.append("PARSER_PAYLOAD_LIMIT_EXCEEDED")
    if b"\x00" * 16 in payload:
        blockers.append("SUSPICIOUS_ZERO_RUN")
    return _ev(
        "NF-591",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        (sha256(payload).hexdigest(), len(payload)),
        blockers,
    )


def reject_semantic_mutation(
    *, original_semantic_sha256: str, mutated_semantic_sha256: str
) -> AssuranceEvidence:
    _sha(original_semantic_sha256, "original_semantic_sha256")
    _sha(mutated_semantic_sha256, "mutated_semantic_sha256")
    changed = original_semantic_sha256 != mutated_semantic_sha256
    return _ev(
        "NF-592",
        Disposition.BLOCKED if changed else Disposition.PASS,
        changed,
        ("SEMANTIC_MUTATION_REJECTED",) if changed else (),
    )


# PR-211 / VERIFY-03 / NF-593..596
def model_execution_state_machine() -> Mapping[str, tuple[str, ...]]:
    return {
        "RESERVED": ("PERMITTED", "CANCELLED"),
        "PERMITTED": ("DISPATCHED_UNKNOWN", "CANCELLED"),
        "DISPATCHED_UNKNOWN": ("ACKNOWLEDGED", "FINALIZED", "RECONCILING"),
        "ACKNOWLEDGED": ("FINALIZED", "RECONCILING"),
        "RECONCILING": ("FINALIZED", "QUARANTINED"),
        "FINALIZED": ("SETTLED", "QUARANTINED"),
        "SETTLED": (),
        "CANCELLED": (),
        "QUARANTINED": (),
    }


def verify_safety_liveness_properties(trace: Sequence[str]) -> AssuranceEvidence:
    machine = model_execution_state_machine()
    blockers = []
    if not trace:
        blockers.append("EMPTY_EXECUTION_TRACE")
    for left, right in zip(trace, trace[1:]):
        if right not in machine.get(left, ()):
            blockers.append(f"INVALID_TRANSITION:{left}->{right}")
    if "DISPATCHED_UNKNOWN" in trace:
        tail = trace[trace.index("DISPATCHED_UNKNOWN") :]
        if "CANCELLED" in tail:
            blockers.append("UNKNOWN_OUTCOME_CANNOT_CANCEL_RESERVATION")
    return _ev(
        "NF-594",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        tuple(trace),
        blockers,
    )


def check_crash_recovery_interleavings(
    traces: Iterable[Sequence[str]],
) -> AssuranceEvidence:
    failed = []
    digests = []
    for index, trace in enumerate(traces):
        result = verify_safety_liveness_properties(trace)
        digests.append(result.evidence_digest)
        if result.disposition is Disposition.BLOCKED:
            failed.append(index)
    return _ev(
        "NF-595",
        Disposition.BLOCKED if failed else Disposition.PASS,
        tuple(digests),
        tuple(f"INVALID_INTERLEAVING:{index}" for index in failed),
    )


def export_model_counterexample(
    trace: Sequence[str], *, reason: str
) -> Mapping[str, object]:
    payload = {"trace": tuple(trace), "reason": _text(reason, "reason")}
    return {**payload, "counterexample_sha256": _digest(payload)}


# PR-212 / SIM-04 / NF-597..600
def run_multi_engine_simulation(
    results: Iterable[SimulationEngineResult],
) -> tuple[SimulationEngineResult, ...]:
    rows = tuple(sorted(results, key=lambda item: item.engine))
    if len(rows) < 2:
        raise Mega804Error("simulation quorum requires at least two engines")
    for item in rows:
        _text(item.engine, "engine")
        _sha(item.post_state_sha256, "post_state_sha256")
        _sha(item.trace_sha256, "trace_sha256")
    return rows


def compare_engine_state_deltas(
    results: Iterable[SimulationEngineResult],
) -> Mapping[str, tuple[str, ...]]:
    groups: dict[str, list[str]] = {}
    for item in run_multi_engine_simulation(results):
        key = _digest((item.success, item.post_state_sha256, item.net_base_units))
        groups.setdefault(key, []).append(item.engine)
    return {key: tuple(names) for key, names in sorted(groups.items())}


def classify_simulator_disagreement(
    results: Iterable[SimulationEngineResult],
) -> AssuranceEvidence:
    groups = compare_engine_state_deltas(results)
    blockers = () if len(groups) == 1 else ("SIMULATOR_STATE_DELTA_DISAGREEMENT",)
    return _ev(
        "NF-599",
        Disposition.PASS if not blockers else Disposition.BLOCKED,
        groups,
        blockers,
    )


def gate_on_simulation_quorum(
    results: Iterable[SimulationEngineResult], *, minimum_engines: int = 2
) -> AssuranceEvidence:
    rows = run_multi_engine_simulation(results)
    blockers = []
    if len(rows) < minimum_engines:
        blockers.append("SIMULATION_QUORUM_TOO_SMALL")
    if any(not item.success for item in rows):
        blockers.append("SIMULATION_ENGINE_FAILURE")
    blockers.extend(classify_simulator_disagreement(rows).blockers)
    return _ev(
        "NF-600",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        tuple(item.engine for item in rows),
        blockers,
    )


# PR-213 / CHAOS-01 / NF-601..604
def inject_provider_faults(target: str, generation: str) -> FaultScenario:
    return FaultScenario("provider_fault", _text(target, "target"), generation)


def inject_network_partition(target: str, generation: str) -> FaultScenario:
    return FaultScenario("network_partition", _text(target, "target"), generation)


def inject_storage_corruption(target: str, generation: str) -> FaultScenario:
    return FaultScenario("storage_corruption", _text(target, "target"), generation)


def verify_fail_closed_recovery(
    scenarios: Iterable[FaultScenario], *, recovery_states: Mapping[str, str]
) -> AssuranceEvidence:
    safe = {"SAFE", "BLOCKED", "QUARANTINED", "READ_ONLY"}
    blockers = []
    rows = []
    for scenario in scenarios:
        state = recovery_states.get(scenario.target, "UNKNOWN")
        rows.append((scenario.kind, scenario.target, state))
        if state not in safe:
            blockers.append(f"UNSAFE_RECOVERY:{scenario.target}:{state}")
    return _ev(
        "NF-604",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        rows,
        blockers,
    )


# PR-214 / SUPPLY-01 / NF-605..608
def generate_sbom(records: Iterable[DependencyRecord]) -> Mapping[str, object]:
    components = []
    for item in sorted(records, key=lambda row: (row.name, row.version)):
        _text(item.name, "name")
        _text(item.version, "version")
        _text(item.license_id, "license_id")
        _text(item.source_identity, "source_identity")
        _sha(item.artifact_sha256, "artifact_sha256")
        components.append(
            {
                "type": "library",
                "name": item.name,
                "version": item.version,
                "licenses": [{"license": {"id": item.license_id}}],
                "externalReferences": [{"type": "vcs", "url": item.source_identity}],
                "hashes": [{"alg": "SHA-256", "content": item.artifact_sha256}],
            }
        )
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": components,
    }
    return {**payload, "sbom_sha256": _digest(payload)}


def attest_reproducible_build(
    *, first_artifact_sha256: str, second_artifact_sha256: str
) -> AssuranceEvidence:
    _sha(first_artifact_sha256, "first_artifact_sha256")
    _sha(second_artifact_sha256, "second_artifact_sha256")
    same = first_artifact_sha256 == second_artifact_sha256
    return _ev(
        "NF-606",
        Disposition.PASS if same else Disposition.BLOCKED,
        same,
        () if same else ("REPRODUCIBLE_BUILD_MISMATCH",),
    )


def enforce_license_policy(
    records: Iterable[DependencyRecord], *, allowed_licenses: Iterable[str]
) -> AssuranceEvidence:
    allowed = frozenset(allowed_licenses)
    blockers = sorted(
        f"LICENSE_NOT_ALLOWED:{item.name}:{item.license_id}"
        for item in records
        if item.license_id not in allowed
    )
    return _ev(
        "NF-607",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        sorted(allowed),
        blockers,
    )


def verify_supply_chain_provenance(
    records: Iterable[DependencyRecord],
) -> AssuranceEvidence:
    blockers = []
    rows = []
    for item in records:
        rows.append(
            (item.name, item.version, item.source_identity, item.artifact_sha256)
        )
        if len(item.source_identity) < 7:
            blockers.append(f"SOURCE_IDENTITY_NOT_IMMUTABLE:{item.name}")
        if _SHA256.fullmatch(item.artifact_sha256) is None:
            blockers.append(f"ARTIFACT_HASH_INVALID:{item.name}")
    return _ev(
        "NF-608",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        rows,
        blockers,
    )


# PR-215 / EVIDENCE-02 / NF-609..612
def append_signed_evidence_record(
    records: Sequence[SignedEvidenceRecord], record: SignedEvidenceRecord
) -> tuple[SignedEvidenceRecord, ...]:
    _sha(record.payload_sha256, "payload_sha256")
    _sha(record.signature_evidence_sha256, "signature_evidence_sha256")
    _text(record.signer_identity, "signer_identity")
    if record.sequence != len(records) + 1:
        raise Mega804Error("evidence sequence is not append-only")
    previous = records[-1].record_sha256 if records else None
    if record.previous_record_sha256 != previous:
        raise Mega804Error("evidence hash-chain predecessor mismatch")
    return tuple(records) + (record,)


def build_merkle_evidence_root(leaves: Iterable[str]) -> str:
    level = [_sha(item, "leaf") for item in leaves]
    if not level:
        raise Mega804Error("Merkle tree requires at least one leaf")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            sha256(bytes.fromhex(level[i]) + bytes.fromhex(level[i + 1])).hexdigest()
            for i in range(0, len(level), 2)
        ]
    return level[0]


def verify_evidence_inclusion(
    *, leaf_sha256: str, proof: Sequence[tuple[str, str]], root_sha256: str
) -> bool:
    current = _sha(leaf_sha256, "leaf_sha256")
    _sha(root_sha256, "root_sha256")
    for side, sibling in proof:
        _sha(sibling, "sibling")
        if side == "left":
            current = sha256(
                bytes.fromhex(sibling) + bytes.fromhex(current)
            ).hexdigest()
        elif side == "right":
            current = sha256(
                bytes.fromhex(current) + bytes.fromhex(sibling)
            ).hexdigest()
        else:
            raise Mega804Error("Merkle proof side must be left/right")
    return current == root_sha256


def export_incident_forensic_bundle(
    records: Sequence[SignedEvidenceRecord], *, incident_id: str
) -> Mapping[str, object]:
    if not records:
        raise Mega804Error("forensic bundle requires evidence records")
    payload = {
        "incident_id": _text(incident_id, "incident_id"),
        "records": tuple(item.record_sha256 for item in records),
        "merkle_root": build_merkle_evidence_root(
            item.record_sha256 for item in records
        ),
    }
    return {**payload, "bundle_sha256": _digest(payload)}


# PR-216 / SIGNER-02 / NF-613..616
def enroll_hsm_signer(
    *,
    provider: str,
    key_reference_sha256: str,
    region: str,
    permit_semantics_sha256: str,
) -> HsmSignerProfile:
    return HsmSignerProfile(
        provider=_text(provider, "provider"),
        key_reference_sha256=_sha(key_reference_sha256, "key_reference_sha256"),
        generation=1,
        region=_text(region, "region"),
        permit_semantics_sha256=_sha(
            permit_semantics_sha256, "permit_semantics_sha256"
        ),
        live_enabled=False,
    )


def execute_key_ceremony(
    profile: HsmSignerProfile, *, approvals: Sequence[str], quorum: int
) -> AssuranceEvidence:
    unique = tuple(sorted(set(approvals)))
    blockers = []
    if quorum < 2 or len(unique) < quorum:
        blockers.append("KEY_CEREMONY_APPROVAL_QUORUM_NOT_MET")
    if profile.live_enabled:
        blockers.append("HSM_PROFILE_MUST_REMAIN_DEFAULT_OFF")
    return _ev(
        "NF-614",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        (profile.generation, unique, quorum),
        blockers,
    )


def rotate_remote_signer_generation(profile: HsmSignerProfile) -> HsmSignerProfile:
    return replace(profile, generation=profile.generation + 1, live_enabled=False)


def recover_multi_region_signer(
    primary: HsmSignerProfile, secondary: HsmSignerProfile
) -> AssuranceEvidence:
    blockers = []
    if primary.region == secondary.region:
        blockers.append("SIGNER_RECOVERY_REGION_NOT_INDEPENDENT")
    if primary.permit_semantics_sha256 != secondary.permit_semantics_sha256:
        blockers.append("SIGNER_PERMIT_SEMANTICS_MISMATCH")
    if primary.live_enabled or secondary.live_enabled:
        blockers.append("RECOVERY_PROFILE_MUST_REMAIN_DEFAULT_OFF")
    return _ev(
        "NF-616",
        Disposition.BLOCKED if blockers else Disposition.PASS,
        (primary.region, secondary.region),
        blockers,
    )


# PR-217 / EVM-04 / NF-617..620
def register_evm_dex_math_adapter(
    *,
    adapter_id: str,
    deployment: str,
    math_version: str,
    source_commit: str,
    license_id: str,
) -> EvmDexAdapter:
    if _EVM_ADDRESS.fullmatch(deployment) is None:
        raise Mega804Error("deployment must be a 20-byte hex EVM address")
    return EvmDexAdapter(
        adapter_id=_text(adapter_id, "adapter_id"),
        deployment=deployment.lower(),
        math_version=_text(math_version, "math_version"),
        source_commit=_text(source_commit, "source_commit"),
        license_id=_text(license_id, "license_id"),
    )


def quote_evm_pool_exactly(
    *, reserve_in: int, reserve_out: int, amount_in: int, fee_ppm: int
) -> int:
    for value, field in (
        (reserve_in, "reserve_in"),
        (reserve_out, "reserve_out"),
        (amount_in, "amount_in"),
        (fee_ppm, "fee_ppm"),
    ):
        _uint(value, field)
    if reserve_in == 0 or reserve_out == 0 or amount_in == 0:
        raise Mega804Error("reserves and amount_in must be positive")
    if fee_ppm >= 1_000_000:
        raise Mega804Error("fee_ppm must be below one million")
    net_in = amount_in * (1_000_000 - fee_ppm) // 1_000_000
    return reserve_out * net_in // (reserve_in + net_in)


def build_evm_swap_calldata(
    *, selector_hex: str, amount_in: int, minimum_out: int, recipient: str
) -> bytes:
    if re.fullmatch(r"0x[0-9a-fA-F]{8}", selector_hex) is None:
        raise Mega804Error("selector_hex must be a 4-byte selector")
    if _EVM_ADDRESS.fullmatch(recipient) is None:
        raise Mega804Error("recipient must be an EVM address")
    _uint(amount_in, "amount_in")
    _uint(minimum_out, "minimum_out")
    selector = bytes.fromhex(selector_hex[2:])
    args = amount_in.to_bytes(32, "big") + minimum_out.to_bytes(32, "big")
    args += int(recipient, 16).to_bytes(32, "big")
    return selector + args


def differential_test_evm_math(
    *, local_amount_out: int, reference_amount_out: int
) -> AssuranceEvidence:
    same = local_amount_out == reference_amount_out
    return _ev(
        "NF-620",
        Disposition.PASS if same else Disposition.BLOCKED,
        (local_amount_out, reference_amount_out),
        () if same else ("EVM_MATH_DIFFERENTIAL_MISMATCH",),
    )


# PR-218 / EVM-05 / NF-621..624
def register_callback_settlement_primitive(
    *,
    primitive_id: str,
    deployment: str,
    repayment_asset: str,
    max_borrow_base_units: int,
) -> CallbackSettlementPrimitive:
    if _EVM_ADDRESS.fullmatch(deployment) is None:
        raise Mega804Error("deployment must be a 20-byte hex EVM address")
    if max_borrow_base_units <= 0:
        raise Mega804Error("max_borrow_base_units must be positive")
    return CallbackSettlementPrimitive(
        primitive_id=_text(primitive_id, "primitive_id"),
        deployment=deployment.lower(),
        repayment_asset=_text(repayment_asset, "repayment_asset"),
        max_borrow_base_units=max_borrow_base_units,
    )


def build_collateral_inventory_plan(
    *, debt_base_units: int, collateral_exit_base_units: int, costs_base_units: int
) -> Mapping[str, int]:
    for value, field in (
        (debt_base_units, "debt_base_units"),
        (collateral_exit_base_units, "collateral_exit_base_units"),
        (costs_base_units, "costs_base_units"),
    ):
        _uint(value, field)
    return {
        "debt_base_units": debt_base_units,
        "collateral_exit_base_units": collateral_exit_base_units,
        "costs_base_units": costs_base_units,
        "conservative_net_base_units": (
            collateral_exit_base_units - debt_base_units - costs_base_units
        ),
    }


def simulate_evm_liquidation_callback(
    *, borrowed_base_units: int, repaid_base_units: int, plan: Mapping[str, int]
) -> AssuranceEvidence:
    blockers = []
    if repaid_base_units < borrowed_base_units:
        blockers.append("EVM_CALLBACK_REPAYMENT_SHORTFALL")
    if plan.get("conservative_net_base_units", -1) <= 0:
        blockers.append("EVM_CALLBACK_NONPOSITIVE_NET")
    return _ev(
        "NF-623",
        Disposition.BLOCKED if blockers else Disposition.RESEARCH_ONLY,
        (borrowed_base_units, repaid_base_units, dict(plan)),
        blockers,
    )


def qualify_evm_atomic_strategy(
    simulation: AssuranceEvidence,
    *,
    deployment_verified: bool,
    chain_qualified: bool,
) -> AssuranceEvidence:
    blockers = list(simulation.blockers)
    if not deployment_verified:
        blockers.append("EVM_DEPLOYMENT_UNVERIFIED")
    if not chain_qualified:
        blockers.append("EVM_CHAIN_UNQUALIFIED")
    return _ev(
        "NF-624",
        Disposition.BLOCKED if blockers else Disposition.RESEARCH_ONLY,
        simulation.evidence_digest,
        blockers,
    )


# PR-219 / SUI-02 / NF-625..628
def assemble_sui_object_state_frame(
    *, chain_id: str, checkpoint: int, objects: Iterable[SuiObjectState]
) -> SuiObjectStateFrame:
    if checkpoint < 0:
        raise Mega804Error("checkpoint must be non-negative")
    rows = tuple(sorted(objects, key=lambda item: item.object_id))
    if len({item.object_id for item in rows}) != len(rows):
        raise Mega804Error("duplicate Sui object in state frame")
    for item in rows:
        _text(item.object_id, "object_id")
        _text(item.digest, "digest")
        if item.version < 0:
            raise Mega804Error("Sui object version must be non-negative")
    payload = (
        _text(chain_id, "chain_id"),
        checkpoint,
        tuple(
            (item.object_id, item.version, item.digest, item.shared, item.mutable)
            for item in rows
        ),
    )
    return SuiObjectStateFrame(chain_id, checkpoint, rows, _digest(payload))


def plan_sui_object_locks(
    frame: SuiObjectStateFrame, *, required_mutable_objects: Iterable[str]
) -> AssuranceEvidence:
    by_id = {item.object_id: item for item in frame.objects}
    requested = tuple(required_mutable_objects)
    blockers = []
    if len(set(requested)) != len(requested):
        blockers.append("SUI_DUPLICATE_OBJECT_LOCK")
    for object_id in requested:
        item = by_id.get(object_id)
        if item is None:
            blockers.append(f"SUI_OBJECT_MISSING:{object_id}")
        elif not item.mutable:
            blockers.append(f"SUI_OBJECT_NOT_MUTABLE:{object_id}")
    return _ev(
        "NF-626",
        Disposition.BLOCKED if blockers else Disposition.RESEARCH_ONLY,
        (frame.frame_sha256, requested),
        blockers,
    )


def simulate_ptb_exactly(
    *,
    frame: SuiObjectStateFrame,
    expected_after_sha256: str,
    observed_after_sha256: str,
) -> AssuranceEvidence:
    _sha(expected_after_sha256, "expected_after_sha256")
    _sha(observed_after_sha256, "observed_after_sha256")
    same = expected_after_sha256 == observed_after_sha256
    return _ev(
        "NF-627",
        Disposition.RESEARCH_ONLY if same else Disposition.BLOCKED,
        (frame.frame_sha256, observed_after_sha256),
        () if same else ("SUI_PTB_STATE_DELTA_MISMATCH",),
    )


def reconcile_sui_object_deltas(
    before: SuiObjectStateFrame, after: SuiObjectStateFrame
) -> Mapping[str, tuple[int, int]]:
    if before.chain_id != after.chain_id:
        raise Mega804Error("cannot reconcile Sui frames across chains")
    left = {item.object_id: item.version for item in before.objects}
    right = {item.object_id: item.version for item in after.objects}
    return {
        object_id: (left.get(object_id, -1), right.get(object_id, -1))
        for object_id in sorted(set(left) | set(right))
        if left.get(object_id) != right.get(object_id)
    }


# PR-220 / XCHAIN-01 / NF-629..632
def register_crosschain_asset_rights(
    *,
    canonical_asset_id: str,
    source_chain: str,
    destination_chain: str,
    custody_model: str,
    bridge_identity: str,
    finality_model: str,
) -> CrosschainAssetRight:
    if source_chain == destination_chain:
        raise Mega804Error("cross-chain right requires distinct chains")
    return CrosschainAssetRight(
        canonical_asset_id=_text(canonical_asset_id, "canonical_asset_id"),
        source_chain=_text(source_chain, "source_chain"),
        destination_chain=_text(destination_chain, "destination_chain"),
        custody_model=_text(custody_model, "custody_model"),
        bridge_identity=_text(bridge_identity, "bridge_identity"),
        finality_model=_text(finality_model, "finality_model"),
    )


def model_bridge_finality_latency(
    *, observed_latencies_ms: Sequence[int], required_confirmations: int
) -> Mapping[str, int]:
    if not observed_latencies_ms or required_confirmations < 1:
        raise Mega804Error("bridge latency evidence and confirmations required")
    values = sorted(_uint(item, "latency_ms") for item in observed_latencies_ms)
    index = min(len(values) - 1, (95 * len(values) + 99) // 100 - 1)
    return {
        "sample_count": len(values),
        "max_latency_ms": values[-1],
        "p95_latency_ms": values[index],
        "required_confirmations": required_confirmations,
    }


def optimize_prefunded_inventory(
    *, source_available: int, destination_available: int, required_destination: int
) -> Mapping[str, int]:
    for value, field in (
        (source_available, "source_available"),
        (destination_available, "destination_available"),
        (required_destination, "required_destination"),
    ):
        _uint(value, field)
    return {
        "source_available": source_available,
        "destination_available": destination_available,
        "required_destination": required_destination,
        "prefund_shortfall": max(0, required_destination - destination_available),
    }


def reconcile_crosschain_settlement(
    *,
    source_debit: int,
    destination_credit: int,
    bridge_fee: int,
    finality_proven: bool,
) -> AssuranceEvidence:
    _uint(source_debit, "source_debit")
    _uint(destination_credit, "destination_credit")
    _uint(bridge_fee, "bridge_fee")
    blockers = []
    if not finality_proven:
        blockers.append("CROSSCHAIN_FINALITY_UNPROVEN")
    if destination_credit + bridge_fee != source_debit:
        blockers.append("CROSSCHAIN_VALUE_CONSERVATION_MISMATCH")
    return _ev(
        "NF-632",
        Disposition.BLOCKED if blockers else Disposition.RESEARCH_ONLY,
        (source_debit, destination_credit, bridge_fee),
        blockers,
    )


# PR-221 / DSL-01 / NF-633..636
def define_verified_strategy_dsl(
    *, version: str, primitives: Iterable[VerifiedPrimitive]
) -> StrategyDsl:
    rows = tuple(sorted(primitives, key=lambda item: item.name))
    if not rows or len({item.name for item in rows}) != len(rows):
        raise Mega804Error("DSL requires unique verified primitives")
    for item in rows:
        _sha(item.capability_sha256, "capability_sha256")
    return StrategyDsl(_text(version, "version"), rows, signer_free=True)


def compile_dsl_to_primitive_graph(dsl: StrategyDsl, source: str) -> tuple[str, ...]:
    tokens = tuple(item.strip() for item in source.split("->") if item.strip())
    allowed = {item.name for item in dsl.primitives}
    if not tokens:
        raise Mega804Error("DSL source is empty")
    unknown = [item for item in tokens if item not in allowed]
    if unknown:
        raise Mega804Error(f"unverified DSL primitive: {unknown[0]}")
    return tokens


def sandbox_strategy_plugin(
    *, plugin_id: str, requested_capabilities: Iterable[str]
) -> AssuranceEvidence:
    requested = tuple(sorted(set(requested_capabilities)))
    blocked = sorted(set(requested) & _EFFECT_CAPABILITIES)
    return _ev(
        "NF-635",
        Disposition.BLOCKED if blocked else Disposition.RESEARCH_ONLY,
        (_text(plugin_id, "plugin_id"), requested),
        tuple(f"FORBIDDEN_PLUGIN_CAPABILITY:{item}" for item in blocked),
    )


def verify_plugin_capabilities(
    plugin_evidence: AssuranceEvidence, *, allowed_capabilities: Iterable[str]
) -> AssuranceEvidence:
    allowed = set(allowed_capabilities)
    blockers = list(plugin_evidence.blockers)
    blockers.extend(
        f"POLICY_ALLOWS_FORBIDDEN_CAPABILITY:{item}"
        for item in sorted(allowed & _EFFECT_CAPABILITIES)
    )
    return _ev(
        "NF-636",
        Disposition.BLOCKED if blockers else Disposition.RESEARCH_ONLY,
        (plugin_evidence.evidence_digest, tuple(sorted(allowed))),
        blockers,
    )


# PR-222 / RELEASE-02 / NF-637..640
def audit_post150_coverage(rows: Iterable[CoverageRow]) -> Post150Audit:
    by_pr = {}
    for row in rows:
        if not 151 <= row.roadmap_pr <= 221:
            raise Mega804Error("coverage row outside PR-151..221")
        if row.roadmap_pr in by_pr:
            raise Mega804Error("duplicate post-150 coverage row")
        if row.status not in _RELEASE_STATUSES:
            raise Mega804Error("unsupported post-150 coverage status")
        _text(row.owner, "owner")
        _sha(row.evidence_sha256, "evidence_sha256")
        by_pr[row.roadmap_pr] = row
    required = set(range(151, 222))
    missing = tuple(sorted(required - set(by_pr)))
    blocked = tuple(
        sorted(number for number, row in by_pr.items() if row.status == "BLOCKED")
    )
    deferred = tuple(
        sorted(number for number, row in by_pr.items() if row.status == "DEFERRED")
    )
    research = tuple(
        sorted(number for number, row in by_pr.items() if row.status == "RESEARCH_ONLY")
    )
    payload = tuple(
        (
            number,
            by_pr[number].status,
            by_pr[number].owner,
            by_pr[number].evidence_sha256,
        )
        for number in sorted(by_pr)
    )
    return Post150Audit(
        covered_count=len(by_pr),
        blocked_prs=blocked,
        deferred_prs=deferred,
        research_only_prs=research,
        missing_prs=missing,
        evidence_digest=_digest(payload),
    )


def run_post150_integrated_campaign(
    audit: Post150Audit,
    *,
    code_generation: str,
    data_generation: str,
    model_generation: str,
    deployment_generation: str,
) -> AssuranceEvidence:
    blockers = []
    if audit.missing_prs:
        blockers.append("POST150_COVERAGE_INCOMPLETE")
    if audit.blocked_prs:
        blockers.append("POST150_MANDATORY_BLOCKERS_REMAIN")
    generations = (
        _text(code_generation, "code_generation"),
        _text(data_generation, "data_generation"),
        _text(model_generation, "model_generation"),
        _text(deployment_generation, "deployment_generation"),
    )
    return _ev(
        "NF-638",
        Disposition.BLOCKED if blockers else Disposition.RESEARCH_ONLY,
        (audit.evidence_digest, generations),
        blockers,
    )


def publish_post150_release_verdict(
    audit: Post150Audit,
    campaign: AssuranceEvidence,
    *,
    selected_capabilities: Iterable[str],
    budgets: Mapping[str, int],
    residual_blockers: Iterable[str],
) -> Mapping[str, object]:
    blockers = list(campaign.blockers)
    blockers.extend(residual_blockers)
    if audit.research_only_prs:
        blockers.append("POST150_RESEARCH_ONLY_CAPABILITIES_REMAIN")
    if audit.deferred_prs:
        blockers.append("POST150_DEFERRED_CAPABILITIES_REMAIN")
    clean_budgets = {
        _text(name, "budget_name"): _uint(value, name)
        for name, value in budgets.items()
    }
    payload = {
        "selected_capabilities": tuple(sorted(set(selected_capabilities))),
        "budgets": dict(sorted(clean_budgets.items())),
        "blockers": tuple(dict.fromkeys(blockers)),
        "rollback": (
            "disable new admissions; retain append-only evidence and recover "
            "started operations"
        ),
        "release_claim_allowed": False,
        "production_ready": False,
        "live_enabled": False,
    }
    return {**payload, "verdict_sha256": _digest(payload)}


def schedule_next_evidence_cycle(
    *, current_cycle: int, residual_blockers: Iterable[str]
) -> Mapping[str, object]:
    if current_cycle < 0:
        raise Mega804Error("current_cycle must be non-negative")
    payload = {
        "cycle": current_cycle + 1,
        "targets": tuple(sorted(set(residual_blockers))),
        "automatic_promotion": False,
        "live_enabled": False,
    }
    return {**payload, "cycle_sha256": _digest(payload)}


NF_SYMBOLS: Mapping[str, str] = {
    f"NF-{number:03d}": name
    for number, name in enumerate(
        (
            "define_property_financial_invariants",
            "generate_stateful_test_sequences",
            "shrink_failing_economic_case",
            "promote_invariant_regression",
            "mutate_transaction_instructions",
            "fuzz_account_meta_permissions",
            "fuzz_parser_and_decoder_boundaries",
            "reject_semantic_mutation",
            "model_execution_state_machine",
            "verify_safety_liveness_properties",
            "check_crash_recovery_interleavings",
            "export_model_counterexample",
            "run_multi_engine_simulation",
            "compare_engine_state_deltas",
            "classify_simulator_disagreement",
            "gate_on_simulation_quorum",
            "inject_provider_faults",
            "inject_network_partition",
            "inject_storage_corruption",
            "verify_fail_closed_recovery",
            "generate_sbom",
            "attest_reproducible_build",
            "enforce_license_policy",
            "verify_supply_chain_provenance",
            "append_signed_evidence_record",
            "build_merkle_evidence_root",
            "verify_evidence_inclusion",
            "export_incident_forensic_bundle",
            "enroll_hsm_signer",
            "execute_key_ceremony",
            "rotate_remote_signer_generation",
            "recover_multi_region_signer",
            "register_evm_dex_math_adapter",
            "quote_evm_pool_exactly",
            "build_evm_swap_calldata",
            "differential_test_evm_math",
            "register_callback_settlement_primitive",
            "build_collateral_inventory_plan",
            "simulate_evm_liquidation_callback",
            "qualify_evm_atomic_strategy",
            "assemble_sui_object_state_frame",
            "plan_sui_object_locks",
            "simulate_ptb_exactly",
            "reconcile_sui_object_deltas",
            "register_crosschain_asset_rights",
            "model_bridge_finality_latency",
            "optimize_prefunded_inventory",
            "reconcile_crosschain_settlement",
            "define_verified_strategy_dsl",
            "compile_dsl_to_primitive_graph",
            "sandbox_strategy_plugin",
            "verify_plugin_capabilities",
            "audit_post150_coverage",
            "run_post150_integrated_campaign",
            "publish_post150_release_verdict",
            "schedule_next_evidence_cycle",
        ),
        start=585,
    )
}

if set(NF_SYMBOLS) != {f"NF-{number:03d}" for number in range(585, 641)}:
    raise RuntimeError("MEGA8-04 NF registry must cover NF-585..NF-640 exactly")
