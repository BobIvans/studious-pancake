from pathlib import Path
import subprocess
import pytest

from src.intelligence.repo_snapshot import (
    start_snapshot,
    resume_snapshot,
    verify_snapshot_roundtrip,
)
from src.intelligence.common import load_json
from src.intelligence.repo_source import (
    analyze_source,
    build_import_graph,
    partition_source,
)
from src.intelligence.repo_groups import build_scc_groups
from src.intelligence.context_pack import build_context_pack, continue_context_pack
from src.intelligence.context_archive import (
    build_portable_archive,
    verify_portable_archive,
)
from src.intelligence.context_benchmark import (
    seed_oracle,
    benchmark_exact_retrieval,
    benchmark_context_pack,
)


def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    for name, value in {
        "a.py": b"import b\nx = 'utf8: \xc3\xa9'\n",
        "b.py": b"import a\n",
        ".env": b"PRIVATE_VALUE=do-not-export",
        "binary": bytes(range(255)),
    }.items():
        (repo / name).write_bytes(value)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return repo


def test_pinned_resumable_exact_snapshot_and_binary_pack(tmp_path):
    repo = repository(tmp_path)
    snap = tmp_path / "snap"
    state = start_snapshot(repo, snap, batch_size=1)
    assert state["status"] == "IN_PROGRESS"
    (repo / "a.py").write_text("raise RuntimeError('must never execute')")
    resume_snapshot(repo, snap)
    assert verify_snapshot_roundtrip(snap)["tracked_entries"] == 4
    assert (
        load_json(snap / "manifest.json")["entries"][0]["status"]
        == "SECRET_METADATA_ONLY"
    )
    pack = build_context_pack(snap, budget_bytes=7)
    all_parts = list(pack["parts"])
    while pack["continuation"]:
        assert benchmark_context_pack(snap, pack)["failed"] == 0
        pack = continue_context_pack(snap, pack, budget_bytes=7)
        all_parts += pack["parts"]
    assert sum(p["end_byte"] - p["start_byte"] for p in all_parts) == 288
    assert benchmark_exact_retrieval(snap, seed_oracle(snap))["passed"] == 3
    archive = tmp_path / "snapshot.zip"
    build_portable_archive(snap, archive)
    assert verify_portable_archive(archive)["verified"]
    entry = next(
        e
        for e in load_json(snap / "manifest.json")["entries"]
        if e["status"] == "EXACT"
    )
    (snap / "blobs" / entry["sha256"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        verify_snapshot_roundtrip(snap)


def test_import_cycles_unicode_offsets_and_exact_partition():
    data = "# é\nclass A:\n    def f(self):\n        pass\n".encode()
    analysis = analyze_source("a.py", data)
    symbol = analysis["symbols"][0]
    assert data[symbol["start_byte"] : symbol["end_byte"]].startswith(b"class A:")
    parts = partition_source("a.py", data, max_bytes=3)
    assert b"".join(data[p["start_byte"] : p["end_byte"]] for p in parts) == data
    graph = build_import_graph(
        [analyze_source("a.py", b"import b"), analyze_source("b.py", b"import a")]
    )
    assert build_scc_groups(graph) == [["a.py", "b.py"]]
