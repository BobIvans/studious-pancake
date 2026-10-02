import pytest

from src.mega_context_wave3 import (
    ActionPlan,
    ConnectorHealth,
    ContextEntity,
    EvidenceLink,
    EvidenceWorkspace,
    KnowledgeWorkbench,
    MegaContextError,
    RelationEvidence,
    RepositoryContextEngine,
    SourcePolicy,
    TestReceipt,
)


def make_workbench() -> KnowledgeWorkbench:
    workbench = KnowledgeWorkbench()
    workbench.policies["local"] = SourcePolicy(
        "local",
        visibility="LOCAL_ONLY",
        allow_cloud=False,
        allow_remote_embeddings=False,
    )
    workbench.policies["public"] = SourcePolicy(
        "public",
        visibility="PUBLIC",
        allow_cloud=True,
        allow_remote_embeddings=True,
    )
    return workbench


def test_pack_roundtrip_hidden_sensitive_and_budget() -> None:
    engine = RepositoryContextEngine()
    files = {
        "src/a.py": b"print('x')\r\n",
        "draft.txt": "hello".encode("utf-16"),
        ".env": b"API_KEY=secret",
        "out/report.txt": b"self",
    }
    inventory = engine.inventory(files, output_prefix="out")
    assert {row.path for row in inventory} == {"src/a.py", "draft.txt", ".env"}
    assert next(row for row in inventory if row.path == ".env").export_mode == (
        "METADATA_ONLY"
    )
    roundtrip = engine.verify_archive_roundtrip(
        {key: value for key, value in files.items() if not key.startswith("out/")},
        inventory,
    )
    assert roundtrip["exact"]
    hidden = engine.audit_hidden_material(
        tracked=["src/a.py", ".env"],
        untracked=["draft.txt"],
        ignored=["ignored.md"],
        files=files,
        output_prefix="out",
    )
    assert hidden["secret_values_exported"] is False
    assert next(
        row for row in hidden["rows"] if row["path"] == ".env"
    )["export_mode"] == "METADATA_ONLY"
    budget = engine.enforce_budget(
        [("a", "x" * 200), ("b", "y" * 200)],
        max_chars=120,
    )
    assert budget["within_budget"]
    assert budget["continuation"]


def test_history_snapshot_parser_and_incremental_pack() -> None:
    engine = RepositoryContextEngine()
    history = engine.history_materialization(
        shallow=True,
        missing_lfs=["x"],
        pr_refs_available=False,
    )
    assert not history["history_complete"]
    assert history["current_snapshot_usable"]
    snapshot = engine.seal_snapshot(
        {"a.py": b"x=1"},
        before={"a.py": "1"},
        after={"a.py": "2"},
        symlink_targets={"bad": "../private"},
    )
    assert not snapshot["complete"]
    assert len(snapshot["blockers"]) == 2
    parsed = engine.parse_python("a.py", "import os\ndef f():\n    return 1\n")
    assert parsed["parse_status"] == "PARSED"
    assert parsed["symbols"][0]["name"] == "f"
    chunks = engine.chunk_index(snapshot["inventory"], target_chars=1000)
    rebuilt = engine.incremental_rebuild(
        {"a.py": "old"},
        {"a.py": b"x=2"},
        chunks["file_to_chunk"],
    )
    assert rebuilt["stale"]
    assert rebuilt["affected_chunks"] == (1,)


def test_requirement_evidence_claims_reuse_problem_and_followup() -> None:
    workspace = EvidenceWorkspace()
    cards = workspace.requirement_cards(
        [{"id": "53", "text": "x", "priority": "P0"}],
        authoritative_ids=["53", "54"],
    )
    assert cards[1].text == "SOURCE_DISCREPANCY_MISSING"
    linked = workspace.link_evidence(
        cards[0],
        EvidenceLink("53", "owner", "artifact", False, False),
    )
    assert linked["status"] == "PARTIAL"
    claim = workspace.classify_claim(
        text="all tests pass",
        evidence_present=False,
    )
    assert claim["claim_class"] == "DECLARED"
    conflict = workspace.compare_runtime_states(
        {
            "readme": {"live": True},
            "capabilities": {"live": False},
        }
    )
    assert conflict["status"] == "CANDIDATE_CONFLICT"
    assert conflict["all_sources_preserved"]
    reuse = workspace.reuse_review(
        proposed_owner="new",
        existing_candidates=["src.old"],
    )
    assert reuse["reuse_review_required"]
    assert not reuse["auto_accept_new_owner"]
    problem = workspace.problem_pack(
        problem_id="p",
        evidence=["a"],
        counterevidence=["b"],
        boundaries=["c"],
    )
    assert problem["counterevidence"] == ("b",)
    with pytest.raises(MegaContextError):
        workspace.followup("../private.key", {})


def test_audit_patch_handoff_receipts_ci_and_campaign() -> None:
    workspace = EvidenceWorkspace()
    progress = workspace.audit_progress(
        uploaded=3,
        reviewed=3,
        confirmed=1,
    )
    assert progress["fully_reviewed"]
    assert not progress["fully_confirmed"]
    envelope = workspace.patch_envelope(
        baseline_sha="a",
        patch_baseline_sha="b",
        changed_paths=["x"],
    )
    assert envelope["status"] == "STALE_PATCH"
    assert not envelope["auto_apply_allowed"]
    handoff = workspace.handoff(
        snapshot_id="s",
        goals=["g"],
        blockers=["b"],
        next_actions=["n"],
    )
    assert len(handoff["handoff_hash"]) == 64
    receipt = TestReceipt("a", "b", "c", "pytest", "PASS", 2, 2)
    bound = workspace.bind_test_receipt(
        {
            "code_sha": "x",
            "config_sha": "b",
            "lock_sha": "c",
        },
        receipt,
    )
    assert not bound["closes_gate"]
    ci = workspace.ci_evidence(
        [[{"status": "completed"}]],
        expired_artifacts=["old"],
    )
    assert not ci["complete"]
    assert "EXPIRED_ARTIFACTS" in ci["gaps"]
    outcomes = workspace.normalize_outcomes(
        [
            {"outcome": "PASS"},
            {"outcome": "SKIP"},
            {"outcome": "XFAIL"},
            {"outcome": "wat"},
        ]
    )
    assert outcomes["required_pass_evidence"] == 1
    assert outcomes["NOT_RUN"] == 1
    first = workspace.seal_campaign("c", {"threshold": 1}, "input", 1)
    second = workspace.seal_campaign("c", {"threshold": 2}, "input", 2)
    assert first.contract_hash != second.contract_hash


def test_sender_pipeline_evidence_gate_credentials_delivery_and_blockers() -> None:
    workspace = EvidenceWorkspace()
    assert not workspace.sender_free_boundary(["read", "send"])["sender_free"]
    assert (
        workspace.pipeline_outcome(stage_status="ERROR", item_count=0)
        == "STAGE_BLOCKED"
    )
    assert workspace.evidence_type("fixture")["evidence_type"] == "SYNTHETIC"
    gate = workspace.operator_gate(
        local_pass=True,
        external_inputs_complete=False,
        blockers=["RPC"],
    )
    assert gate["gate"] == "UNKNOWN"
    assert not gate["live"]
    credentials = workspace.isolate_credentials(
        {
            "name": "x",
            "api_key": "secret",
            "cookie": "c",
        }
    )
    assert not credentials["credentials_exported"]
    assert credentials["exported"] == {"name": "x"}
    delivery = workspace.delivery_receipt(
        snapshot_id="s",
        destination="chat",
        included_ids=["a"],
        excluded_count=2,
        policy_hash="p",
    )
    assert len(delivery["receipt_hash"]) == 64
    partition = workspace.blocker_partition(
        [
            {"id": "a", "blocks_release": True},
            {"id": "b", "blocks_release": False},
        ]
    )
    assert [row["id"] for row in partition["release_blockers"]] == ["a"]


def test_library_entities_relation_restrictions_and_inert_rendering() -> None:
    workbench = make_workbench()
    assert not workbench.project_manifest(
        {"schema_version": "v999"}
    )["active_actions"]
    workbench.register_entities(
        [
            ContextEntity("1", "file", "same", "public", 1, 1, "OBSERVED"),
            ContextEntity("2", "file", "same", "public", 1, 1, "DECLARED"),
        ]
    )
    assert len(workbench.entities) == 2
    assert workbench.claim_class("2") == "DECLARED"
    relation = RelationEvidence(
        "r",
        "1",
        "2",
        "import",
        "from x import y",
        ("e",),
    )
    assert workbench.relation(relation)["fragment"].startswith("from")
    child = workbench.inherit_policy("local", "derived")
    assert not child.allow_cloud
    assert not child.allow_remote_embeddings
    rendered = workbench.render_workspace(
        [{"widget": "evil", "text": "<script>alert(1)</script>"}],
        known_widgets={"text"},
    )
    assert rendered[0]["widget"] == "unknown"
    assert "<script>" not in rendered[0]["text"]
    assert not rendered[0]["executable"]


def test_goal_cards_disabled_basket_large_doc_and_destination_preview() -> None:
    workbench = make_workbench()
    cards = workbench.goal_cards(
        [
            {
                "goal_id": "g",
                "required_evidence": ["a", "b"],
                "present_evidence": ["a"],
            }
        ]
    )
    assert cards[0]["missing"] == ("b",)
    assert cards[0]["production_readiness_percent"] is None
    assert workbench.disabled_actions({"api_key": False})["status"] == "DISABLED"
    assert workbench.basket_update(
        add_ids=["a", "b"],
        remove_ids=["a"],
    ) == ("b",)
    big = "x" * 400_000
    view = workbench.viewport(big, limit=2048)
    assert len(view["viewport"]) == 2048
    assert not view["complete_export"]
    preview = workbench.destination_preview(
        [
            {"source_id": "local", "title": "secret"},
            {"source_id": "public", "title": "ok", "token": "x"},
        ],
        destination="cloud",
    )
    assert preview["excluded_count"] == 1
    assert preview["included"] == [{"source_id": "public", "title": "ok"}]


def test_action_policy_plan_exact_grant_and_shared_interfaces() -> None:
    workbench = make_workbench()
    registry = workbench.register_actions(
        [
            {"action_id": "research", "effects": ["read"]},
            {"action_id": "bad", "effects": ["send"]},
            {"action_id": "cmd", "command": "rm -rf /"},
        ]
    )
    assert set(registry) == {"research"}
    plan = workbench.plan_action(
        action_id="research",
        goal_id="g",
        query="q",
        snapshot_id="s",
        requires_network=True,
        estimated_cost_units=1,
    )
    grant = workbench.approve(
        plan,
        principal="u",
        now=1,
        ttl=10,
        max_cost_units=2,
    )
    assert workbench.authorize(
        plan,
        grant,
        now=2,
        current_snapshot_id="s",
        requested_cost_units=1,
    )["authorized"]
    changed = ActionPlan(
        plan.action_id,
        plan.goal_id,
        "different",
        plan.snapshot_id,
        plan.interface,
        plan.requires_network,
        plan.estimated_cost_units,
        plan.effects,
    )
    assert not workbench.authorize(
        changed,
        grant,
        now=2,
        current_snapshot_id="s",
        requested_cost_units=1,
    )["authorized"]
    results = workbench.authorize_interfaces(
        plan,
        {"ui": grant, "cli": grant, "mcp": grant},
        now=2,
        snapshot_id="other",
        cost=1,
    )
    assert all(not result["authorized"] for result in results.values())


def test_permission_retrieval_units_graph_and_citations() -> None:
    workbench = make_workbench()
    items = [
        {"id": "a", "source_id": "local", "private": True},
        {"id": "b", "source_id": "public"},
    ]
    assert [
        row["id"]
        for row in workbench.permission_retrieval(
            items,
            remote_embeddings=True,
        )
    ] == ["b"]
    units = workbench.index_units(
        "abcde" * 1000,
        unit_chars=1000,
        overlap=100,
    )
    assert len(units) > 1
    assert all(len(unit["text"]) <= 1000 for unit in units)
    graph = workbench.expand_graph(
        {"a": ["b"], "b": ["c"]},
        "a",
        unknown_dynamic_calls=["dyn"],
    )
    assert graph["nodes"] == ("a", "b", "c")
    assert not graph["business_correctness_proven"]
    citations = workbench.validate_citations(
        [
            {
                "claim": "payment deadline enforced",
                "support": "url",
                "citation_text": "unrelated content",
            }
        ]
    )
    assert not citations["all_confirmed"]


def test_research_market_connector_evaluation_drift_and_growth() -> None:
    workbench = make_workbench()
    brief = workbench.implementation_brief(
        question="q",
        findings=["f"],
        reuse_owner=None,
        uncertainty=["unknown"],
    )
    assert brief["uncertainty"]
    assert not brief["live_integration_required"]
    lanes = workbench.market_lanes(
        [
            {"lane": "EXECUTION", "kind": "oracle", "id": "o"},
            {"lane": "EXECUTION", "kind": "fill", "id": "f"},
        ]
    )
    assert [row["id"] for row in lanes["EXECUTION"]] == ["f"]
    assert [row["id"] for row in lanes["QUOTE"]] == ["o"]
    health = workbench.connector_health(
        ConnectorHealth("dune", "READ_ONLY", True, True, True)
    )
    assert health["potentially_billable"]
    assert not health["auth_exported"]
    questions = workbench.golden_questions(
        [
            {"q": "?", "ground_truth": "UNKNOWN"},
            {"q": "?", "ground_truth": "NOT_A_BUG"},
        ]
    )
    assert len(questions) == 2
    score = workbench.evidence_completeness(
        required=["a", "b"],
        present=["a"],
        irrelevant_chars=400_000,
    )
    assert score["score"] == 0.5
    assert score["irrelevant_chars_ignored"] == 400_000
    adversarial = workbench.adversarial_ui_policy(
        ["<script>sendTransaction()</script>"]
    )
    assert adversarial["safe"]
    assert adversarial["actions_triggered"] == 0
    drift = workbench.drift(
        prior_hashes={"contract": "1", "view": "1"},
        current_hashes={"contract": "2", "view": "1"},
        dependency_map={"view": ["contract"]},
    )
    assert drift["needs_recheck"] == ("contract", "view")
    assert not workbench.feature_gate(
        duplicate_owner=True,
        measured_benefit=10,
    )["accepted"]
