"""OCA-W3 tests: shift-survival, rename records, ambiguity NEEDS_REVIEW."""

from __future__ import annotations

from src.intelligence.logsites import build_manifest, scan_module

MODULE_V1 = b'''"""Emitter module."""

import logging


def process(value: str) -> str:
    logging.info("start %s", value)
    result = value.strip()
    logging.info("done")
    return result
'''

MODULE_V2 = b'''"""Emitter module."""

import logging


def process(value: str) -> str:
    # Several new lines added above the emission sites.
    padded = value + "!"
    stripped = padded.strip()

    logging.info("start %s", stripped)
    result = stripped
    logging.info("done")
    return result
'''


def test_callsite_ids_survive_line_shifts() -> None:
    v1 = scan_module("src/emitter.py", MODULE_V1)
    v2 = scan_module("src/emitter.py", MODULE_V2)
    ids_v1 = [site["callsite_id"] for site in v1["callsites"]]
    ids_v2 = [site["callsite_id"] for site in v2["callsites"]]
    assert v1["resolved_count"] == 2
    assert ids_v1 == ids_v2, "line shifts must not change callsite identity"
    # Raw line numbers are evidence, not identity.
    assert v1["callsites"][0]["lineno"] != v2["callsites"][0]["lineno"]


def test_dynamic_dispatch_is_needs_review() -> None:
    module = b"import emitter\n\n\ndef run(fn):\n    fn.emit(value)\n"
    scanned = scan_module("src/dynamic.py", module)
    assert scanned["needs_review_count"] >= 1
    assert all(
        site["resolution"] == "NEEDS_REVIEW"
        for site in scanned["callsites"]
        if site["target_expr"] == "fn.emit"
    )


def test_producer_mapping_and_manifest_identity() -> None:
    modules = {
        "src/emitter.py": MODULE_V1,
        "src/dynamic.py": b"import logging\nlogging.warning('x')\n",
    }
    manifest_a = build_manifest(modules, blob_by_path={"src/emitter.py": "a" * 64})
    manifest_b = build_manifest(modules, blob_by_path={"src/emitter.py": "a" * 64})
    assert manifest_a == manifest_b
    assert manifest_a["resolved"] >= 3
    # Producer mapping: the W0B symbol convention is reused for callers.
    assert any(
        site["caller_symbol_id"] == "py::src/emitter.py::process"
        for site in manifest_a["entries"]
    )
    assert any(site["blob_sha256"] == "a" * 64 for site in manifest_a["entries"])
