from src.market_data_evolution.graph_review import render_graph_review


def test_read_only_view_escapes_supplied_evidence_and_shows_unknowns():
    page = render_graph_review(
        ({"venue": "<script>alert(1)</script>", "input_atoms": 10},),
        frame_id="<unsafe>",
    )
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "UNKNOWN" in page
    assert "MODEL_REPLAY_ONLY" in page
    assert "<form" not in page
