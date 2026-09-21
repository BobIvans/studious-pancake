"""PR-356 corrective completion adapters for W5 residual requirements."""

from __future__ import annotations

from typing import Any, Mapping

from src.research.pr356_completion_contracts import run_requirement

def bind_hypothesis_economic_semantics(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Bind instruments/rights/resources/cashflows underlying the hypothesis."""
    return run_requirement(
        "W5F-010",
        "bind_hypothesis_economic_semantics",
        "Bind instruments/rights/resources/cashflows underlying the hypothesis.",
        "W5-01",
        payload,
        **kwargs,
    )


def bind_hypothesis_observability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Declare what variables are directly observed, proxied, latent or missing."""
    return run_requirement(
        "W5F-011",
        "bind_hypothesis_observability",
        "Declare what variables are directly observed, proxied, latent or missing.",
        "W5-01",
        payload,
        **kwargs,
    )


def bind_hypothesis_falsification(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Declare null, reject condition, counterexample class and stopping rule."""
    return run_requirement(
        "W5F-012",
        "bind_hypothesis_falsification",
        "Declare null, reject condition, counterexample class and stopping rule.",
        "W5-01",
        payload,
        **kwargs,
    )


def bind_hypothesis_identification_assumptions(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Declare causal/predictive assumptions separately."""
    return run_requirement(
        "W5F-013",
        "bind_hypothesis_identification_assumptions",
        "Declare causal/predictive assumptions separately.",
        "W5-01",
        payload,
        **kwargs,
    )


def bind_hypothesis_cost_and_access(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Declare data, compute, eligibility and operational costs."""
    return run_requirement(
        "W5F-014",
        "bind_hypothesis_cost_and_access",
        "Declare data, compute, eligibility and operational costs.",
        "W5-01",
        payload,
        **kwargs,
    )


def publish_hypothesis_ir(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish content-addressed HypothesisProgram with no execution right."""
    return run_requirement(
        "W5F-016",
        "publish_hypothesis_ir",
        "Publish content-addressed HypothesisProgram with no execution right.",
        "W5-01",
        payload,
        **kwargs,
    )


def retrieve_semantic_prior_hypotheses(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Retrieve prior hypotheses by mechanism/economic semantics, not string similarity only."""
    return run_requirement(
        "W5F-017",
        "retrieve_semantic_prior_hypotheses",
        "Retrieve prior hypotheses by mechanism/economic semantics, not string similarity only.",
        "W5-02",
        payload,
        **kwargs,
    )


def compare_hypothesis_structure(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare variables, horizons, conditions, rights and falsification logic."""
    return run_requirement(
        "W5F-018",
        "compare_hypothesis_structure",
        "Compare variables, horizons, conditions, rights and falsification logic.",
        "W5-02",
        payload,
        **kwargs,
    )


def score_hypothesis_novelty_dimensions(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Score new mechanism, new observable, new regime, new target or new identification strategy separately."""
    return run_requirement(
        "W5F-021",
        "score_hypothesis_novelty_dimensions",
        "Score new mechanism, new observable, new regime, new target or new identification strategy separately.",
        "W5-02",
        payload,
        **kwargs,
    )


def require_novelty_justification(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Require explicit delta over closest prior experiment."""
    return run_requirement(
        "W5F-022",
        "require_novelty_justification",
        "Require explicit delta over closest prior experiment.",
        "W5-02",
        payload,
        **kwargs,
    )


def link_duplicate_to_prior_result(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Redirect semantic duplicates to prior evidence instead of rerunning."""
    return run_requirement(
        "W5F-023",
        "link_duplicate_to_prior_result",
        "Redirect semantic duplicates to prior evidence instead of rerunning.",
        "W5-02",
        payload,
        **kwargs,
    )


def build_symbolic_search_dataset(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Prepare dimensioned variables, transformations and train-only expression search space."""
    return run_requirement(
        "W5F-025",
        "build_symbolic_search_dataset",
        "Prepare dimensioned variables, transformations and train-only expression search space.",
        "W5-03",
        payload,
        **kwargs,
    )


def search_symbolic_relation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Search constrained symbolic expressions under complexity budget."""
    return run_requirement(
        "W5F-027",
        "search_symbolic_relation",
        "Search constrained symbolic expressions under complexity budget.",
        "W5-03",
        payload,
        **kwargs,
    )


def simplify_symbolic_law(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Canonicalize expression and remove redundant terms."""
    return run_requirement(
        "W5F-029",
        "simplify_symbolic_law",
        "Canonicalize expression and remove redundant terms.",
        "W5-03",
        payload,
        **kwargs,
    )


def compare_symbolic_to_blackbox(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare interpretability/utility against simple and learned baselines."""
    return run_requirement(
        "W5F-031",
        "compare_symbolic_to_blackbox",
        "Compare interpretability/utility against simple and learned baselines.",
        "W5-03",
        payload,
        **kwargs,
    )


def publish_symbolic_law_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish domain, valid regimes, counterexamples, uncertainty and expiry."""
    return run_requirement(
        "W5F-032",
        "publish_symbolic_law_card",
        "Publish domain, valid regimes, counterexamples, uncertainty and expiry.",
        "W5-03",
        payload,
        **kwargs,
    )


def define_blackbox_transition_probe(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define safe read/simulation probe and expected observable state transition."""
    return run_requirement(
        "W5F-033",
        "define_blackbox_transition_probe",
        "Define safe read/simulation probe and expected observable state transition.",
        "W5-04",
        payload,
        **kwargs,
    )


def collect_transition_trace(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Collect input/pre-state/output/post-state with exact version and no remote mutation."""
    return run_requirement(
        "W5F-034",
        "collect_transition_trace",
        "Collect input/pre-state/output/post-state with exact version and no remote mutation.",
        "W5-04",
        payload,
        **kwargs,
    )


def infer_transition_guard(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Infer candidate preconditions/caps/thresholds from accepted/rejected traces."""
    return run_requirement(
        "W5F-035",
        "infer_transition_guard",
        "Infer candidate preconditions/caps/thresholds from accepted/rejected traces.",
        "W5-04",
        payload,
        **kwargs,
    )


def infer_state_update_equation(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Infer candidate deterministic or stochastic transition relation."""
    return run_requirement(
        "W5F-036",
        "infer_state_update_equation",
        "Infer candidate deterministic or stochastic transition relation.",
        "W5-04",
        payload,
        **kwargs,
    )


def infer_hidden_shared_resource(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect apparently independent calls constrained by a shared reserve/vault/object."""
    return run_requirement(
        "W5F-037",
        "infer_hidden_shared_resource",
        "Detect apparently independent calls constrained by a shared reserve/vault/object.",
        "W5-04",
        payload,
        **kwargs,
    )


def generate_disambiguating_probe(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Choose next safe simulation/read probe to separate competing mechanism models."""
    return run_requirement(
        "W5F-038",
        "generate_disambiguating_probe",
        "Choose next safe simulation/read probe to separate competing mechanism models.",
        "W5-04",
        payload,
        **kwargs,
    )


def compare_inferred_to_documented_semantics(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Diff behavioral model against docs/source/ABI/IDL."""
    return run_requirement(
        "W5F-039",
        "compare_inferred_to_documented_semantics",
        "Diff behavioral model against docs/source/ABI/IDL.",
        "W5-04",
        payload,
        **kwargs,
    )


def publish_system_identification_dossier(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish candidate state machine, uncertainty, counterexamples and blocked unknowns."""
    return run_requirement(
        "W5F-040",
        "publish_system_identification_dossier",
        "Publish candidate state machine, uncertainty, counterexamples and blocked unknowns.",
        "W5-04",
        payload,
        **kwargs,
    )


def register_causal_question(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define treatment/intervention, outcome, confounders, timing and target population."""
    return run_requirement(
        "W5F-041",
        "register_causal_question",
        "Define treatment/intervention, outcome, confounders, timing and target population.",
        "W5-05",
        payload,
        **kwargs,
    )


def propose_causal_graph(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Propose graph from mechanism knowledge plus observational discovery."""
    return run_requirement(
        "W5F-042",
        "propose_causal_graph",
        "Propose graph from mechanism knowledge plus observational discovery.",
        "W5-05",
        payload,
        **kwargs,
    )


def test_causal_identifiability(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Check whether effect is identifiable under declared assumptions."""
    return run_requirement(
        "W5F-043",
        "test_causal_identifiability",
        "Check whether effect is identifiable under declared assumptions.",
        "W5-05",
        payload,
        **kwargs,
    )


def estimate_effect_with_controls(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate treatment/effect using compatible estimator when assumptions permit."""
    return run_requirement(
        "W5F-044",
        "estimate_effect_with_controls",
        "Estimate treatment/effect using compatible estimator when assumptions permit.",
        "W5-05",
        payload,
        **kwargs,
    )


def estimate_heterogeneous_effect(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate regime/market-specific treatment effects where supported."""
    return run_requirement(
        "W5F-045",
        "estimate_heterogeneous_effect",
        "Estimate regime/market-specific treatment effects where supported.",
        "W5-05",
        payload,
        **kwargs,
    )


def run_causal_refuters(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Run placebo, subset, sensitivity and alternative-graph refutations."""
    return run_requirement(
        "W5F-046",
        "run_causal_refuters",
        "Run placebo, subset, sensitivity and alternative-graph refutations.",
        "W5-05",
        payload,
        **kwargs,
    )


def publish_causal_claim_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish effect, assumptions, uncertainty, refuters and scope."""
    return run_requirement(
        "W5F-048",
        "publish_causal_claim_card",
        "Publish effect, assumptions, uncertainty, refuters and scope.",
        "W5-05",
        payload,
        **kwargs,
    )


def define_experiment_action_space(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Define legal read/sim/data/parameter actions; no live trade action."""
    return run_requirement(
        "W5F-049",
        "define_experiment_action_space",
        "Define legal read/sim/data/parameter actions; no live trade action.",
        "W5-06",
        payload,
        **kwargs,
    )


def estimate_expected_information_gain(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate uncertainty reduction for candidate experiment actions."""
    return run_requirement(
        "W5F-050",
        "estimate_expected_information_gain",
        "Estimate uncertainty reduction for candidate experiment actions.",
        "W5-06",
        payload,
        **kwargs,
    )


def estimate_experiment_cost_vector(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Estimate source/compute/time/license/human cost."""
    return run_requirement(
        "W5F-051",
        "estimate_experiment_cost_vector",
        "Estimate source/compute/time/license/human cost.",
        "W5-06",
        payload,
        **kwargs,
    )


def select_next_experiment_action(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Choose action under budget and integrity constraints."""
    return run_requirement(
        "W5F-052",
        "select_next_experiment_action",
        "Choose action under budget and integrity constraints.",
        "W5-06",
        payload,
        **kwargs,
    )


def apply_early_stopping_rule(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Stop unpromising trials under preregistered rule."""
    return run_requirement(
        "W5F-053",
        "apply_early_stopping_rule",
        "Stop unpromising trials under preregistered rule.",
        "W5-06",
        payload,
        **kwargs,
    )


def audit_adaptive_experiment_bias(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Account for adaptivity/multiple tries and preserve random controls."""
    return run_requirement(
        "W5F-054",
        "audit_adaptive_experiment_bias",
        "Account for adaptivity/multiple tries and preserve random controls.",
        "W5-06",
        payload,
        **kwargs,
    )


def measure_information_gain_realized(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure actual uncertainty/decision reduction after trial."""
    return run_requirement(
        "W5F-055",
        "measure_information_gain_realized",
        "Measure actual uncertainty/decision reduction after trial.",
        "W5-06",
        payload,
        **kwargs,
    )


def publish_experiment_design_card(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish action sequence, costs, adaptivity and final evidence."""
    return run_requirement(
        "W5F-056",
        "publish_experiment_design_card",
        "Publish action sequence, costs, adaptivity and final evidence.",
        "W5-06",
        payload,
        **kwargs,
    )


def enumerate_well_typed_programs(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Enumerate/prune only type-correct research programs under complexity budget."""
    return run_requirement(
        "W5F-058",
        "enumerate_well_typed_programs",
        "Enumerate/prune only type-correct research programs under complexity budget.",
        "W5-07",
        payload,
        **kwargs,
    )


def deduplicate_program_against_strategy_catalog(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect existing strategy/mechanism equivalence."""
    return run_requirement(
        "W5F-061",
        "deduplicate_program_against_strategy_catalog",
        "Detect existing strategy/mechanism equivalence.",
        "W5-07",
        payload,
        **kwargs,
    )


def score_program_research_priority(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Use existing frontier/cost/novelty evidence, not live PnL."""
    return run_requirement(
        "W5F-062",
        "score_program_research_priority",
        "Use existing frontier/cost/novelty evidence, not live PnL.",
        "W5-07",
        payload,
        **kwargs,
    )


def dispatch_program_to_existing_simulator(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Route candidate to canonical simulator/factory without new execution engine."""
    return run_requirement(
        "W5F-063",
        "dispatch_program_to_existing_simulator",
        "Route candidate to canonical simulator/factory without new execution engine.",
        "W5-07",
        payload,
        **kwargs,
    )


def generate_readonly_research_patch(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Generate code limited to allowlisted research interfaces."""
    return run_requirement(
        "W5F-065",
        "generate_readonly_research_patch",
        "Generate code limited to allowlisted research interfaces.",
        "W5-08",
        payload,
        **kwargs,
    )


def static_scan_generated_patch(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Reject network mutation, signer/sender, secret, subprocess and disallowed imports."""
    return run_requirement(
        "W5F-066",
        "static_scan_generated_patch",
        "Reject network mutation, signer/sender, secret, subprocess and disallowed imports.",
        "W5-08",
        payload,
        **kwargs,
    )


def generate_property_tests(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Generate property-based tests from mechanism invariants."""
    return run_requirement(
        "W5F-067",
        "generate_property_tests",
        "Generate property-based tests from mechanism invariants.",
        "W5-08",
        payload,
        **kwargs,
    )


def generate_smt_obligations(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Generate bounded SMT constraints for units, balances, obligations and impossible states."""
    return run_requirement(
        "W5F-068",
        "generate_smt_obligations",
        "Generate bounded SMT constraints for units, balances, obligations and impossible states.",
        "W5-08",
        payload,
        **kwargs,
    )


def run_generated_patch_in_sandbox(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Run deterministic fixtures/replay only."""
    return run_requirement(
        "W5F-069",
        "run_generated_patch_in_sandbox",
        "Run deterministic fixtures/replay only.",
        "W5-08",
        payload,
        **kwargs,
    )


def measure_generated_patch_semantic_error(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compare generated behavior with verified fixtures/source semantics."""
    return run_requirement(
        "W5F-070",
        "measure_generated_patch_semantic_error",
        "Compare generated behavior with verified fixtures/source semantics.",
        "W5-08",
        payload,
        **kwargs,
    )


def require_human_semantic_review(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Require human approval before any repository integration proposal."""
    return run_requirement(
        "W5F-071",
        "require_human_semantic_review",
        "Require human approval before any repository integration proposal.",
        "W5-08",
        payload,
        **kwargs,
    )


def publish_generated_patch_receipt(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish code/test/tool hashes, failures and approval state."""
    return run_requirement(
        "W5F-072",
        "publish_generated_patch_receipt",
        "Publish code/test/tool hashes, failures and approval state.",
        "W5-08",
        payload,
        **kwargs,
    )


def assign_scientific_roles(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Assign proposer/skeptic/statistician/domain/replicator with separated context."""
    return run_requirement(
        "W5F-073",
        "assign_scientific_roles",
        "Assign proposer/skeptic/statistician/domain/replicator with separated context.",
        "W5-09",
        payload,
        **kwargs,
    )


def collect_independent_review(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Collect structured review without revealing other reviewers first."""
    return run_requirement(
        "W5F-074",
        "collect_independent_review",
        "Collect structured review without revealing other reviewers first.",
        "W5-09",
        payload,
        **kwargs,
    )


def detect_review_conflict(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect disagreements in assumptions, data, statistics or semantics."""
    return run_requirement(
        "W5F-075",
        "detect_review_conflict",
        "Detect disagreements in assumptions, data, statistics or semantics.",
        "W5-09",
        payload,
        **kwargs,
    )


def request_targeted_adjudication(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Request new evidence/experiment to resolve specific conflict."""
    return run_requirement(
        "W5F-076",
        "request_targeted_adjudication",
        "Request new evidence/experiment to resolve specific conflict.",
        "W5-09",
        payload,
        **kwargs,
    )


def prevent_consensus_as_truth(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Prevent majority vote from overriding benchmark/evidence failures."""
    return run_requirement(
        "W5F-077",
        "prevent_consensus_as_truth",
        "Prevent majority vote from overriding benchmark/evidence failures.",
        "W5-09",
        payload,
        **kwargs,
    )


def score_review_calibration(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure reviewer error over later verified outcomes."""
    return run_requirement(
        "W5F-078",
        "score_review_calibration",
        "Measure reviewer error over later verified outcomes.",
        "W5-09",
        payload,
        **kwargs,
    )


def retain_dissent_and_counterexample(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Persist minority counterarguments and counterexamples."""
    return run_requirement(
        "W5F-079",
        "retain_dissent_and_counterexample",
        "Persist minority counterarguments and counterexamples.",
        "W5-09",
        payload,
        **kwargs,
    )


def publish_peer_review_record(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish role-separated review and unresolved disputes."""
    return run_requirement(
        "W5F-080",
        "publish_peer_review_record",
        "Publish role-separated review and unresolved disputes.",
        "W5-09",
        payload,
        **kwargs,
    )


def index_counterexample_by_mechanism(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Index by financial motif/rights/resource semantics."""
    return run_requirement(
        "W5F-083",
        "index_counterexample_by_mechanism",
        "Index by financial motif/rights/resource semantics.",
        "W5-10",
        payload,
        **kwargs,
    )


def detect_assumption_revival(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect new proposal that silently reintroduces a disproven assumption."""
    return run_requirement(
        "W5F-085",
        "detect_assumption_revival",
        "Detect new proposal that silently reintroduces a disproven assumption.",
        "W5-10",
        payload,
        **kwargs,
    )


def expire_counterexample_when_semantics_change(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Retire/retag counterexamples after genuine deployment/mechanism changes."""
    return run_requirement(
        "W5F-086",
        "expire_counterexample_when_semantics_change",
        "Retire/retag counterexamples after genuine deployment/mechanism changes.",
        "W5-10",
        payload,
        **kwargs,
    )


def measure_rediscovery_avoidance(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Measure redundant trials avoided and time saved."""
    return run_requirement(
        "W5F-087",
        "measure_rediscovery_avoidance",
        "Measure redundant trials avoided and time saved.",
        "W5-10",
        payload,
        **kwargs,
    )


def distill_mechanism_law(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Distill repeated finding into scoped law with variables/regimes/rights assumptions."""
    return run_requirement(
        "W5F-089",
        "distill_mechanism_law",
        "Distill repeated finding into scoped law with variables/regimes/rights assumptions.",
        "W5-11",
        payload,
        **kwargs,
    )


def register_scientific_claim(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Register claim separately from evidence and model."""
    return run_requirement(
        "W5F-090",
        "register_scientific_claim",
        "Register claim separately from evidence and model.",
        "W5-11",
        payload,
        **kwargs,
    )


def link_supporting_evidence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Link receipts/benchmarks/replications supporting a claim."""
    return run_requirement(
        "W5F-091",
        "link_supporting_evidence",
        "Link receipts/benchmarks/replications supporting a claim.",
        "W5-11",
        payload,
        **kwargs,
    )


def link_refuting_evidence(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Link counterexamples/rejections that limit or refute a claim."""
    return run_requirement(
        "W5F-092",
        "link_refuting_evidence",
        "Link counterexamples/rejections that limit or refute a claim.",
        "W5-11",
        payload,
        **kwargs,
    )


def compute_claim_scope(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Compute markets/regimes/topologies where the claim has direct evidence."""
    return run_requirement(
        "W5F-093",
        "compute_claim_scope",
        "Compute markets/regimes/topologies where the claim has direct evidence.",
        "W5-11",
        payload,
        **kwargs,
    )


def detect_claim_contradiction(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Detect two active claims with overlapping scope and incompatible predictions."""
    return run_requirement(
        "W5F-094",
        "detect_claim_contradiction",
        "Detect two active claims with overlapping scope and incompatible predictions.",
        "W5-11",
        payload,
        **kwargs,
    )


def expire_or_downgrade_claim(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Downgrade after drift/deprecation/contradiction or failed replication."""
    return run_requirement(
        "W5F-095",
        "expire_or_downgrade_claim",
        "Downgrade after drift/deprecation/contradiction or failed replication.",
        "W5-11",
        payload,
        **kwargs,
    )


def publish_mechanism_knowledge_pack(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Publish reusable scientific prior for later MarketPack onboarding."""
    return run_requirement(
        "W5F-096",
        "publish_mechanism_knowledge_pack",
        "Publish reusable scientific prior for later MarketPack onboarding.",
        "W5-11",
        payload,
        **kwargs,
    )


__all__ = [
    'bind_hypothesis_economic_semantics',
    'bind_hypothesis_observability',
    'bind_hypothesis_falsification',
    'bind_hypothesis_identification_assumptions',
    'bind_hypothesis_cost_and_access',
    'publish_hypothesis_ir',
    'retrieve_semantic_prior_hypotheses',
    'compare_hypothesis_structure',
    'score_hypothesis_novelty_dimensions',
    'require_novelty_justification',
    'link_duplicate_to_prior_result',
    'build_symbolic_search_dataset',
    'search_symbolic_relation',
    'simplify_symbolic_law',
    'compare_symbolic_to_blackbox',
    'publish_symbolic_law_card',
    'define_blackbox_transition_probe',
    'collect_transition_trace',
    'infer_transition_guard',
    'infer_state_update_equation',
    'infer_hidden_shared_resource',
    'generate_disambiguating_probe',
    'compare_inferred_to_documented_semantics',
    'publish_system_identification_dossier',
    'register_causal_question',
    'propose_causal_graph',
    'test_causal_identifiability',
    'estimate_effect_with_controls',
    'estimate_heterogeneous_effect',
    'run_causal_refuters',
    'publish_causal_claim_card',
    'define_experiment_action_space',
    'estimate_expected_information_gain',
    'estimate_experiment_cost_vector',
    'select_next_experiment_action',
    'apply_early_stopping_rule',
    'audit_adaptive_experiment_bias',
    'measure_information_gain_realized',
    'publish_experiment_design_card',
    'enumerate_well_typed_programs',
    'deduplicate_program_against_strategy_catalog',
    'score_program_research_priority',
    'dispatch_program_to_existing_simulator',
    'generate_readonly_research_patch',
    'static_scan_generated_patch',
    'generate_property_tests',
    'generate_smt_obligations',
    'run_generated_patch_in_sandbox',
    'measure_generated_patch_semantic_error',
    'require_human_semantic_review',
    'publish_generated_patch_receipt',
    'assign_scientific_roles',
    'collect_independent_review',
    'detect_review_conflict',
    'request_targeted_adjudication',
    'prevent_consensus_as_truth',
    'score_review_calibration',
    'retain_dissent_and_counterexample',
    'publish_peer_review_record',
    'index_counterexample_by_mechanism',
    'detect_assumption_revival',
    'expire_counterexample_when_semantics_change',
    'measure_rediscovery_avoidance',
    'distill_mechanism_law',
    'register_scientific_claim',
    'link_supporting_evidence',
    'link_refuting_evidence',
    'compute_claim_scope',
    'detect_claim_contradiction',
    'expire_or_downgrade_claim',
    'publish_mechanism_knowledge_pack'
]
