"""Render a static review report with escaped source values and no remote assets."""

from html import escape
import json


def _value(value) -> str:
    if value is None:
        return '<span class="null">null</span>'
    return '<code>' + escape(json.dumps(value, ensure_ascii=False)) + '</code>'


def _row_details(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return '<span class="muted">Absent</span>'
    result = []
    for row in rows:
        errors = {}
        for error in row["errors"]:
            errors.setdefault(error["column"], []).append(error["message"])
        cells = []
        for name in columns:
            raw = _value(row["raw"][name]) if name in row["raw"] else '<span class="muted">Unavailable</span>'
            typed = _value(row["values"][name]) if name in row["values"] else '<span class="muted">Invalid or unavailable</span>'
            messages = "; ".join(errors.get(name, []))
            cells.append(f'<tr><th scope="row">{escape(name)}</th><td>{raw}</td><td>{typed}</td><td>{escape(messages)}</td></tr>')
        general_errors = "".join(f'<p class="error">{escape(message)}</p>' for message in errors.get(None, []))
        location = f'Record {row["record"]}, lines {row["line_start"]}-{row["line_end"]}'
        original_cells = '<p class="note">Original cells: ' + _value(row["cells"]) + '</p>'
        result.append(f'<details><summary>{escape(location)}</summary>{general_errors}{original_cells}<div class="scroll"><table class="values"><thead><tr><th scope="col">Column</th><th scope="col">Raw</th><th scope="col">Typed</th><th scope="col">Issue</th></tr></thead><tbody>{"".join(cells)}</tbody></table></div></details>')
    return "".join(result)


def _issues(side: str, dataset: dict) -> str:
    if not dataset["issues"]:
        return f'<p class="muted">No {escape(side.lower())} validation issues.</p>'
    rows = []
    for issue in dataset["issues"]:
        column = issue["column"] if issue["column"] is not None else "Entire record"
        rows.append(f'<tr><td class="number">{issue["record"]}</td><td class="number">{issue["line_start"]}-{issue["line_end"]}</td><td>{escape(column)}</td><td>{escape(issue["message"])}</td></tr>')
    return f'<h3>{escape(side)}</h3><div class="scroll"><table><thead><tr><th scope="col">Record</th><th scope="col">Lines</th><th scope="col">Column</th><th scope="col">Issue</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def render_report(report: dict) -> str:
    columns = [column["name"] for column in report["schema"]["columns"]]
    summary = report["summary"]
    complete = report["complete"]
    state = "Comparison complete" if complete else "Review required: provisional comparison"
    explanation = (
        "Every record has a valid key and typed values, and each key occurs at most once per source."
        if complete else
        "Invalid records or duplicate keys prevent a complete comparison. All entries below are provisional. Resolve the issues before relying on this report for an import."
    )
    cards = "".join(f'<div class="metric"><strong>{summary[name]}</strong><span>{name.capitalize()}</span></div>' for name in ("added", "removed", "changed", "unchanged", "ambiguous", "invalid"))
    sources = []
    for side in ("left", "right"):
        dataset = report[side]
        source = dataset["source"]
        sources.append(f'<section><h2>{side.capitalize()} source</h2><p class="source-name">{escape(source["name"])}</p><dl><dt>Records</dt><dd>{dataset["records"]}</dd><dt>Valid records</dt><dd>{dataset["valid_records"]}</dd><dt>Invalid records</dt><dd>{dataset["invalid_records"]}</dd><dt>Unkeyed records</dt><dd>{summary["unkeyed_" + side]}</dd><dt>File bytes</dt><dd>{source["size_bytes"]}</dd></dl><p class="digest">SHA-256: {escape(source["sha256"])}</p></section>')
    entries = []
    for entry in report["entries"]:
        key = " · ".join(_value(value) for value in entry["key"])
        changes = "".join(f'<li><strong>{escape(change["column"])}</strong>: {_value(change["before"])} → {_value(change["after"])}</li>' for change in entry["changes"])
        change_cell = f'<ul class="changes">{changes}</ul>' if changes else '<span class="muted">No field changes reported</span>'
        status = escape(entry["status"])
        entries.append(f'<tr><th scope="row">{key}</th><td><span class="status {status}">{status}</span></td><td>{_row_details(entry["left"],columns)}</td><td>{_row_details(entry["right"],columns)}</td><td>{change_cell}</td></tr>')
    entry_body = "".join(entries) or '<tr><td colspan="5">No keyed records to compare.</td></tr>'
    key_columns = ", ".join(report["schema"]["keys"])
    unkeyed = "".join(
        f'<h3>{side.capitalize()}</h3>{_row_details(report[side]["unkeyed"], columns)}'
        for side in ("left", "right") if report[side]["unkeyed"]
    ) or '<p class="muted">Every record has a usable key.</p>'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rowbridge | {escape(report["left"]["source"]["name"])} and {escape(report["right"]["source"]["name"])}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f7;color:#1b2938;font:15px/1.55 system-ui,sans-serif}}main{{max-width:1440px;margin:auto;padding:32px 24px 52px}}.eyebrow{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:#4b6477}}h1{{font-size:32px;line-height:1.2;margin:10px 0}}h2{{font-size:20px;margin:0 0 12px}}h3{{font-size:16px}}p{{margin:8px 0}}.muted,.note{{color:#5c6977}}.note{{font-size:13px}}.notice{{border-left:4px solid {"#287552" if complete else "#b75a13"};background:{"#edf8f1" if complete else "#fff5e9"};padding:16px 20px;margin:20px 0;border-radius:4px}}.notice strong{{display:block}}
.metrics{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:20px 0}}.metric,section{{background:#fff;border:1px solid #dce3e9;border-radius:9px;padding:18px}}.metric strong{{display:block;font-size:27px;font-variant-numeric:tabular-nums}}.metric span{{font-size:13px;color:#5c6977}}section{{margin:16px 0}}.sources{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.sources section{{min-width:0}}.source-name{{font-weight:600;overflow-wrap:anywhere}}dl{{display:grid;grid-template-columns:1fr 1fr;gap:5px 12px;font-size:13px}}dt{{color:#5c6977}}dd{{margin:0;text-align:right;font-variant-numeric:tabular-nums}}.digest,footer{{font-size:12px;color:#5c6977;overflow-wrap:anywhere}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px;text-align:left}}th,td{{padding:11px 12px;border-bottom:1px solid #e5eaee;vertical-align:top;overflow-wrap:anywhere}}thead th{{background:#f7f9fb;color:#4b6477;font-size:12px}}tbody th{{font-weight:500}}.number{{font-variant-numeric:tabular-nums;white-space:nowrap}}.status{{display:inline-block;padding:2px 8px;border-radius:4px;background:#edf1f5;font-size:12px;font-weight:600;white-space:nowrap}}.added{{background:#e5f4eb;color:#22633d}}.removed{{background:#fce9e8;color:#9c302a}}.changed{{background:#e9f0fc;color:#284f96}}.ambiguous,.invalid{{background:#fff0dc;color:#8b4b12}}code{{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 ui-monospace,monospace}}.null{{font:italic 12px ui-monospace,monospace;color:#856113}}.changes{{padding-left:16px;margin:0}}details{{min-width:160px;margin:0 0 7px}}summary{{cursor:pointer;color:#315779}}.values{{min-width:470px;margin:10px 0}}.values th,.values td{{padding:8px}}.error{{color:#a43b2e;font-size:13px}}
@media(max-width:800px){{main{{padding:24px 14px}}.metrics{{grid-template-columns:repeat(3,1fr)}}.sources{{grid-template-columns:1fr;gap:0}}h1{{font-size:27px}}}}
@media print{{body{{background:white}}main{{padding:0}}.scroll{{overflow:visible}}.metric{{break-inside:avoid}}details{{break-inside:avoid}}}}
</style></head><body><main>
<header><div class="eyebrow">Rowbridge / CSV reconciliation</div><h1>Compare records before importing</h1><p class="muted">Explicit types, stable keys, and the source records behind each result.</p></header>
<div class="notice" role="status"><strong>{state}</strong>{explanation}</div>
<div class="metrics">{cards}</div>
<p class="note">Status counts refer to keys. Unkeyed records are listed separately and remain in the validation issues.</p>
<div class="sources">{"".join(sources)}</div>
<section><h2>Validation issues</h2>{_issues("Left",report["left"])}{_issues("Right",report["right"])}</section>
<section><h2>Unkeyed records</h2><p class="note">These records cannot be assigned a comparison status. Their original cells are preserved for review.</p>{unkeyed}</section>
<section><h2>Records by key</h2><p class="note">Key columns: {escape(key_columns)}. Expand a record to inspect raw and typed values. Quoted empty strings and <span class="null">null</span> are different values.</p><div class="scroll"><table><thead><tr><th scope="col">Key</th><th scope="col">Status</th><th scope="col">Left records</th><th scope="col">Right records</th><th scope="col">Field changes</th></tr></thead><tbody>{entry_body}</tbody></table></div></section>
<footer>Schema SHA-256: {escape(report["schema_sha256"])}<br>This report does not modify either source. Open it directly in a browser; no service or network connection is needed.</footer>
</main></body></html>
'''
