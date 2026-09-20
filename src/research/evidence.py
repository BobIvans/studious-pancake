"""RND-01: reproducible evidence, AI research and development workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .common import (
    EvidenceStatus,
    OFFLINE_RESEARCH_BOUNDARY,
    ResearchDisposition,
    ResearchFailure,
    SourceKind,
    hash_json,
    require_id,
    require_sha256,
    require_text,
    unique_nonempty,
)


@dataclass(frozen=True, slots=True)
class ResearchSource:
    source_id: str
    kind: SourceKind
    version: str
    artifact_sha256: str
    license_id: str | None
    uri: str
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    independent_group: str | None = None

    def __post_init__(self) -> None:
        require_id(self.source_id, "source_id")
        require_text(self.version, "version")
        require_sha256(self.artifact_sha256, "artifact_sha256")
        require_text(self.uri, "uri")
        if self.license_id is not None:
            require_text(self.license_id, "license_id")
        if self.independent_group is not None:
            require_id(self.independent_group, "independent_group")

    @property
    def usable_for_code_import(self) -> bool:
        return (
            self.kind is SourceKind.CODE
            and self.status is EvidenceStatus.VERIFIED
            and self.license_id is not None
        )


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    claim_id: str
    statement: str
    source_ids: tuple[str, ...]
    status: EvidenceStatus

    def __post_init__(self) -> None:
        require_id(self.claim_id, "claim_id")
        require_text(self.statement, "statement")
        if not self.source_ids:
            raise ValueError("source_ids cannot be empty")
        unique_nonempty(self.source_ids, "source_id")


@dataclass(frozen=True, slots=True)
class HypothesisRecord:
    hypothesis_id: str
    question: str
    function_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    disposition: ResearchDisposition = ResearchDisposition.RESEARCH

    def __post_init__(self) -> None:
        require_id(self.hypothesis_id, "hypothesis_id")
        require_text(self.question, "question")
        unique_nonempty(self.function_ids, "function_id")
        unique_nonempty(self.source_ids, "source_id")


@dataclass(frozen=True, slots=True)
class ResearchExperimentManifest:
    experiment_id: str
    hypothesis_id: str
    baseline_id: str
    problem_sha256: str
    dataset_sha256: str
    code_sha256: str
    source_ids: tuple[str, ...]
    compute_budget_units: int
    hidden_data_allowed: bool = False
    signing_allowed: bool = False
    submission_allowed: bool = False

    def __post_init__(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        require_id(self.hypothesis_id, "hypothesis_id")
        require_id(self.baseline_id, "baseline_id")
        require_sha256(self.problem_sha256, "problem_sha256")
        require_sha256(self.dataset_sha256, "dataset_sha256")
        require_sha256(self.code_sha256, "code_sha256")
        unique_nonempty(self.source_ids, "source_id")
        if self.compute_budget_units <= 0:
            raise ValueError("compute_budget_units must be positive")
        if self.hidden_data_allowed:
            raise ValueError("hidden evaluation data cannot be allowed")
        if self.signing_allowed or self.submission_allowed:
            raise ValueError("research experiments cannot grant signing/submission")

    @property
    def manifest_sha256(self) -> str:
        return hash_json("agg14/research-experiment-manifest/v1", asdict(self))


class ResearchEvidenceLibrary:
    """Content-addressed source/claim/hypothesis library for NF-308."""

    def __init__(self) -> None:
        self._sources: dict[str, ResearchSource] = {}
        self._claims: dict[str, ResearchClaim] = {}
        self._hypotheses: dict[str, HypothesisRecord] = {}

    def add_source(self, source: ResearchSource) -> None:
        existing = self._sources.get(source.source_id)
        if existing is not None and existing != source:
            raise ResearchFailure(
                "RESEARCH_SOURCE_ID_CONFLICT",
                stage="library",
                description="source id reused with different immutable identity",
                evidence_refs=(source.source_id,),
            )
        self._sources[source.source_id] = source

    def add_claim(self, claim: ResearchClaim) -> None:
        missing = tuple(s for s in claim.source_ids if s not in self._sources)
        if missing:
            raise ResearchFailure(
                "RESEARCH_CLAIM_SOURCE_MISSING",
                stage="library",
                description="claim references unknown sources",
                dependency_ids=missing,
            )
        existing = self._claims.get(claim.claim_id)
        if existing is not None and existing != claim:
            raise ResearchFailure(
                "RESEARCH_CLAIM_ID_CONFLICT",
                stage="library",
                description="claim id reused with different semantics",
            )
        self._claims[claim.claim_id] = claim

    def add_hypothesis(self, hypothesis: HypothesisRecord) -> None:
        missing = tuple(s for s in hypothesis.source_ids if s not in self._sources)
        if missing:
            raise ResearchFailure(
                "RESEARCH_HYPOTHESIS_SOURCE_MISSING",
                stage="hypothesis",
                description="hypothesis references unknown sources",
                dependency_ids=missing,
            )
        existing = self._hypotheses.get(hypothesis.hypothesis_id)
        if existing is not None and existing != hypothesis:
            raise ResearchFailure(
                "RESEARCH_HYPOTHESIS_ID_CONFLICT",
                stage="hypothesis",
                description="hypothesis id reused with different semantics",
            )
        self._hypotheses[hypothesis.hypothesis_id] = hypothesis

    def source(self, source_id: str) -> ResearchSource:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise ResearchFailure(
                "RESEARCH_SOURCE_MISSING",
                stage="library",
                description="requested source is not registered",
                dependency_ids=(source_id,),
            ) from exc

    def independent_verified_groups(self, claim_id: str) -> tuple[str, ...]:
        claim = self._claims[claim_id]
        groups: set[str] = set()
        for source_id in claim.source_ids:
            source = self._sources[source_id]
            if source.status is not EvidenceStatus.VERIFIED:
                continue
            groups.add(source.independent_group or source.source_id)
        return tuple(sorted(groups))

    def snapshot(self) -> dict[str, object]:
        payload = {
            "sources": [asdict(v) for _, v in sorted(self._sources.items())],
            "claims": [asdict(v) for _, v in sorted(self._claims.items())],
            "hypotheses": [
                asdict(v) for _, v in sorted(self._hypotheses.items())
            ],
            "effect_boundary": asdict(OFFLINE_RESEARCH_BOUNDARY),
        }
        return {
            "schema": "agg14.research-evidence-library.v1",
            "sha256": hash_json("agg14/research-library/v1", payload),
            **payload,
        }


@dataclass(frozen=True, slots=True)
class ResearchCopilotResult:
    question: str
    cited_source_ids: tuple[str, ...]
    suggested_hypotheses: tuple[str, ...]
    suggested_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    credentials_in_context: bool = False
    live_approval_allowed: bool = False
    signing_allowed: bool = False

    def __post_init__(self) -> None:
        require_text(self.question, "question")
        unique_nonempty(self.cited_source_ids, "cited_source_id")
        if self.credentials_in_context or self.live_approval_allowed or self.signing_allowed:
            raise ValueError("research copilot must remain advisory-only")


def build_cited_research_result(
    *,
    library: ResearchEvidenceLibrary,
    question: str,
    cited_source_ids: Iterable[str],
    suggested_hypotheses: Iterable[str] = (),
    suggested_symbols: Iterable[str] = (),
    known_symbols: Iterable[str] = (),
) -> ResearchCopilotResult:
    cited = unique_nonempty(cited_source_ids, "cited_source_id")
    for source_id in cited:
        library.source(source_id)
    known = set(known_symbols)
    symbols = tuple(suggested_symbols)
    missing = tuple(sorted({symbol for symbol in symbols if symbol not in known}))
    return ResearchCopilotResult(
        question=require_text(question, "question"),
        cited_source_ids=cited,
        suggested_hypotheses=tuple(suggested_hypotheses),
        suggested_symbols=symbols,
        missing_symbols=missing,
    )


@dataclass(frozen=True, slots=True)
class DevelopmentWorkflowReceipt:
    task_id: str
    repository: str
    base_sha256: str
    branch: str
    changed_paths: tuple[str, ...]
    test_commands: tuple[str, ...]
    evidence_sha256: str
    reviewed: bool
    user_controlled_login: bool = True
    password_collection_allowed: bool = False
    private_key_access_allowed: bool = False
    merge_permitted_by_receipt: bool = False

    def __post_init__(self) -> None:
        require_id(self.task_id, "task_id")
        require_text(self.repository, "repository")
        require_sha256(self.base_sha256, "base_sha256")
        require_text(self.branch, "branch")
        unique_nonempty(self.changed_paths, "changed_path")
        unique_nonempty(self.test_commands, "test_command")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        if not self.user_controlled_login:
            raise ValueError("browser/login authentication must remain user-controlled")
        if self.password_collection_allowed or self.private_key_access_allowed:
            raise ValueError("developer workflow cannot collect passwords/private keys")


@dataclass(frozen=True, slots=True)
class AgentRoleDecision:
    role: str
    decision: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_id(self.role, "role")
        require_text(self.decision, "decision")
        unique_nonempty(self.evidence_refs, "evidence_ref")


@dataclass(frozen=True, slots=True)
class AgentExperimentPlan:
    experiment_id: str
    budget_units: int
    planner: AgentRoleDecision
    critic: AgentRoleDecision
    runner: AgentRoleDecision
    coordinator_log_sha256: str
    market_proof_count: int = 0
    live_vote_allowed: bool = False

    def __post_init__(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        if self.budget_units <= 0:
            raise ValueError("budget_units must be positive")
        require_sha256(self.coordinator_log_sha256, "coordinator_log_sha256")
        if self.market_proof_count != 0:
            raise ValueError("agent agreement is not independent market proof")
        if self.live_vote_allowed:
            raise ValueError("agents cannot vote themselves into live authority")

    @property
    def disagreement(self) -> bool:
        return len({self.planner.decision, self.critic.decision, self.runner.decision}) > 1


@dataclass(frozen=True, slots=True)
class DefensiveToolBenchmark:
    tool_id: str
    source_id: str
    dataset_sha256: str
    authorized_scope: str
    source_available: bool
    license_reviewed: bool
    true_positives: int
    false_positives: int
    false_negatives: int
    execution_permission: bool = False

    def __post_init__(self) -> None:
        require_id(self.tool_id, "tool_id")
        require_id(self.source_id, "source_id")
        require_sha256(self.dataset_sha256, "dataset_sha256")
        require_text(self.authorized_scope, "authorized_scope")
        for field_name in ("true_positives", "false_positives", "false_negatives"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.execution_permission:
            raise ValueError("defensive research alerts cannot grant execution")

    @property
    def qualified(self) -> bool:
        return self.source_available and self.license_reviewed

    @property
    def measured_false_positive_rate(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        if denominator == 0:
            return None
        return self.false_positives / denominator


__all__ = [
    "AgentExperimentPlan",
    "AgentRoleDecision",
    "DefensiveToolBenchmark",
    "DevelopmentWorkflowReceipt",
    "HypothesisRecord",
    "ResearchClaim",
    "ResearchCopilotResult",
    "ResearchEvidenceLibrary",
    "ResearchExperimentManifest",
    "ResearchSource",
    "build_cited_research_result",
]
