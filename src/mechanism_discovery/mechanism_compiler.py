"""RND-10 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

discover_mechanism_surface = make_research_function("discover_mechanism_surface", "RND-10")
extract_mechanism_state_schema = make_research_function("extract_mechanism_state_schema", "RND-10")
infer_rights_obligations_timing = make_research_function("infer_rights_obligations_timing", "RND-10")
compile_candidate_financial_primitives = make_research_function("compile_candidate_financial_primitives", "RND-10")
generate_decoder_adapter_skeleton = make_research_function("generate_decoder_adapter_skeleton", "RND-10")
generate_mechanism_test_vectors = make_research_function("generate_mechanism_test_vectors", "RND-10")
validate_primitives_against_traces = make_research_function("validate_primitives_against_traces", "RND-10")
publish_mechanism_dossier = make_research_function("publish_mechanism_dossier", "RND-10")

__all__ = [
    "discover_mechanism_surface",
    "extract_mechanism_state_schema",
    "infer_rights_obligations_timing",
    "compile_candidate_financial_primitives",
    "generate_decoder_adapter_skeleton",
    "generate_mechanism_test_vectors",
    "validate_primitives_against_traces",
    "publish_mechanism_dossier"
]
