"""Local, read-only evidence graph review; no remote assets or live controls."""

from html import escape
from typing import Mapping, Sequence


def render_graph_review(rows: Sequence[Mapping[str, object]], *, frame_id: str) -> str:
    if len(rows) > 512:
        raise ValueError("review edge bound exceeded")
    columns = (
        "route_id",
        "leg",
        "venue",
        "input_asset",
        "output_asset",
        "input_atoms",
        "output_atoms",
        "slot",
        "evaluation_id",
    )
    body = "".join(
        "<tr>"
        + "".join(
            "<td>" + escape(str(row.get(key, "UNKNOWN"))) + "</td>" for key in columns
        )
        + "</tr>"
        for row in rows
    )
    headings = "".join("<th>" + escape(key) + "</th>" for key in columns)
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Shadow evidence graph</title><style>body{font:14px system-ui;margin:24px;background:#101820;color:#edf4ff}table{border-collapse:collapse;width:100%}td,th{border:1px solid #415569;padding:8px;text-align:left;overflow-wrap:anywhere}h1{font-size:24px}p{max-width:900px}</style><h1>Shadow evidence graph</h1><p>MODEL_REPLAY_ONLY · No execution rights · Connected feeds: 0</p><p>Frame: '
        + escape(frame_id)
        + "</p><p>Each row is an independently evaluated integer leg. Stored quote outputs are never scaled. This view contains local supplied state, not verified live market coverage.</p><table><thead><tr>"
        + headings
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></html>"
    )
