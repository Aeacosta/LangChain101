"""
Dash front-end for the Code Smell Analyzer.

Run with:
    python dash_app.py
Then open http://127.0.0.1:8050 in your browser.
"""

import json
import os
import glob as _glob

import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc

from agent_setup import agent
from Helpers.FilePatcher import preview_patch, apply_fixes

# ── File discovery ────────────────────────────────────────────────────────────

def _discover_files() -> list[dict]:
    """Return dropdown options for every .cs file found under Ejemplos/."""
    paths = sorted(_glob.glob("Ejemplos/**/*.cs", recursive=True))
    return [{"label": p.replace("\\", "/"), "value": p.replace("\\", "/")} for p in paths]


# ── Severity colour map ───────────────────────────────────────────────────────

_SEV_COLOR = {
    "Critical": "#dc2626",
    "High":     "#d97706",
    "Medium":   "#ca8a04",
    "Low":      "#16a34a",
}

# ── App ───────────────────────────────────────────────────────────────────────

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Code Smell Analyzer"

app.layout = dbc.Container(
    [
        html.H2("Code Smell Analyzer", className="mt-4 mb-1"),
        html.P(
            "Select a file from the dropdown or type a custom path, then click Analyze.",
            className="text-muted mb-4",
        ),

        dbc.Row(
            [
                dbc.Col(
                    dcc.Dropdown(
                        id="file-dropdown",
                        options=_discover_files(),
                        placeholder="Select a file…",
                        clearable=True,
                    ),
                    width=6,
                ),
                dbc.Col(
                    dbc.Input(
                        id="file-custom",
                        placeholder="…or type a custom path",
                        type="text",
                    ),
                    width=4,
                ),
                dbc.Col(
                    dbc.Button("Analyze", id="btn-analyze", color="primary", n_clicks=0),
                    width=2,
                ),
            ],
            className="mb-3",
        ),

        # Hidden store for the last successful JSON result
        dcc.Store(id="result-store"),

        dbc.Spinner(
            html.Div(id="report-output"),
            color="primary",
            type="border",
        ),

        # ── Patcher section (hidden until a result is available) ──────────
        html.Div(
            id="patcher-section",
            style={"display": "none"},
            children=[
                html.Hr(className="mt-4 mb-3"),
                html.H4("Patch File", className="mb-3"),

                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Button(
                                "⬇ Export Fixed File",
                                id="btn-export",
                                color="success",
                                n_clicks=0,
                            ),
                            width="auto",
                        ),
                        dbc.Col(
                            html.Div(id="export-status"),
                            width=True,
                        ),
                    ],
                    align="center",
                    className="mb-3",
                ),

                dbc.Tabs(
                    [
                        dbc.Tab(
                            html.Pre(
                                id="patch-raw",
                                style={
                                    "fontSize": "0.78rem",
                                    "backgroundColor": "#f7f8fa",
                                    "padding": "12px",
                                    "borderRadius": "4px",
                                    "maxHeight": "500px",
                                    "overflowY": "auto",
                                },
                            ),
                            label="Raw (Patched)",
                            tab_id="tab-raw",
                        ),
                        dbc.Tab(
                            html.Pre(
                                id="patch-diff",
                                style={
                                    "fontSize": "0.78rem",
                                    "backgroundColor": "#f7f8fa",
                                    "padding": "12px",
                                    "borderRadius": "4px",
                                    "maxHeight": "500px",
                                    "overflowY": "auto",
                                },
                            ),
                            label="Diff",
                            tab_id="tab-diff",
                        ),
                        dbc.Tab(
                            html.Div(id="patch-preview"),
                            label="Preview",
                            tab_id="tab-preview",
                        ),
                    ],
                    id="patch-tabs",
                    active_tab="tab-raw",
                ),
            ],
        ),
    ],
    fluid=False,
    style={"maxWidth": "960px"},
)

# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("report-output",   "children"),
    Output("result-store",    "data"),
    Output("patcher-section", "style"),
    Input("btn-analyze", "n_clicks"),
    State("file-dropdown", "value"),
    State("file-custom",   "value"),
    prevent_initial_call=True,
)
def run_analysis(_n_clicks, dropdown_val, custom_val):
    file_path = (custom_val or "").strip() or (dropdown_val or "").strip()
    if not file_path:
        return (
            dbc.Alert("Please select or enter a file path before analyzing.", color="warning"),
            None,
            {"display": "none"},
        )

    raw = agent.call_agent(f"Que Code Smells detectas en este archivo? {file_path}")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return (
            dbc.Alert(
                [html.Strong("Agent returned invalid JSON. Raw output:"), html.Pre(raw)],
                color="danger",
            ),
            None,
            {"display": "none"},
        )

    has_diffs = any(f.get("diff", "").strip() for f in result.get("findings", []))
    patcher_style = {"display": "block"} if has_diffs else {"display": "none"}

    return _render_report(result), result, patcher_style


@app.callback(
    Output("patch-raw",     "children"),
    Output("patch-diff",    "children"),
    Output("patch-preview", "children"),
    Input("result-store", "data"),
    prevent_initial_call=True,
)
def update_patch_views(result: dict):
    if not result:
        return "", "", ""

    pr = preview_patch(result)
    if pr is None:
        msg = "Source file not found or unreadable."
        return msg, msg, dbc.Alert(msg, color="warning")

    # Raw tab — plain patched text
    raw_content = pr.patched

    # Diff tab — coloured unified diff
    diff_lines = []
    for line in pr.unified_diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            diff_lines.append(html.Span(line + "\n", style={"color": "#16a34a"}))
        elif line.startswith("-") and not line.startswith("---"):
            diff_lines.append(html.Span(line + "\n", style={"color": "#dc2626"}))
        elif line.startswith("@@"):
            diff_lines.append(html.Span(line + "\n", style={"color": "#7c5cd8"}))
        else:
            diff_lines.append(html.Span(line + "\n", style={"color": "#57606a"}))

    diff_content = diff_lines or "No changes produced."

    # Preview tab — side-by-side original vs patched
    preview_content = _render_side_by_side(pr.original, pr.patched, pr.errors)

    return raw_content, diff_content, preview_content


@app.callback(
    Output("export-status", "children"),
    Input("btn-export", "n_clicks"),
    State("result-store", "data"),
    prevent_initial_call=True,
)
def export_fixed_file(_n_clicks, result: dict):
    if not result:
        return dbc.Alert("No analysis result available.", color="warning", className="mb-0")

    try:
        apply_fixes(result)
        file_path = result.get("fileName", "unknown")
        return dbc.Alert(
            f"✓ File overwritten with fixes: {file_path}",
            color="success",
            className="mb-0",
            dismissable=True,
        )
    except Exception as exc:
        return dbc.Alert(
            f"Export failed: {exc}",
            color="danger",
            className="mb-0",
            dismissable=True,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_side_by_side(original: str, patched: str, errors: list[str]) -> html.Div:
    """Render a side-by-side original vs patched view."""
    orig_lines   = original.splitlines()
    patched_lines = patched.splitlines()
    max_lines = max(len(orig_lines), len(patched_lines))

    rows = []
    for i in range(max_lines):
        orig_line    = orig_lines[i]   if i < len(orig_lines)   else ""
        patched_line = patched_lines[i] if i < len(patched_lines) else ""
        changed      = orig_line != patched_line
        bg = "#fef9c3" if changed else "transparent"
        rows.append(
            html.Tr([
                html.Td(
                    str(i + 1),
                    style={"color": "#9ca3af", "paddingRight": "8px",
                           "userSelect": "none", "fontSize": "0.72rem"},
                ),
                html.Td(
                    orig_line,
                    style={"fontFamily": "monospace", "fontSize": "0.78rem",
                           "whiteSpace": "pre", "color": "#dc2626" if changed else "inherit"},
                ),
                html.Td(
                    patched_line,
                    style={"fontFamily": "monospace", "fontSize": "0.78rem",
                           "whiteSpace": "pre", "color": "#16a34a" if changed else "inherit",
                           "paddingLeft": "24px"},
                ),
            ], style={"backgroundColor": bg})
        )

    table = html.Table(
        [
            html.Thead(html.Tr([
                html.Th("#",       style={"width": "40px"}),
                html.Th("Original"),
                html.Th("Patched", style={"paddingLeft": "24px"}),
            ])),
            html.Tbody(rows),
        ],
        style={"width": "100%", "borderCollapse": "collapse"},
    )

    children = [
        html.Div(
            table,
            style={
                "overflowX": "auto",
                "overflowY": "auto",
                "maxHeight": "500px",
                "fontSize": "0.78rem",
                "backgroundColor": "#f7f8fa",
                "padding": "12px",
                "borderRadius": "4px",
            },
        )
    ]

    if errors:
        children.insert(0, dbc.Alert(
            [html.Strong("Patch warnings: "), html.Ul([html.Li(e) for e in errors])],
            color="warning",
            className="mb-2",
        ))

    return html.Div(children)


# ── Score card ────────────────────────────────────────────────────────────────

def _render_score_card(score_report: dict) -> dbc.Card:
    score   = score_report.get("score", 0)
    grade   = score_report.get("grade", "?")
    just    = score_report.get("justification", "")
    bdown   = score_report.get("breakdown", [])

    # Grade colour
    grade_colors = {"A": "#16a34a", "B": "#65a30d", "C": "#ca8a04", "D": "#d97706", "F": "#dc2626"}
    grade_color  = grade_colors.get(grade, "#6b7280")

    # Score bar (0–100)
    bar_color = grade_color
    bar = html.Div(
        html.Div(
            style={
                "width":           f"{score}%",
                "height":          "10px",
                "backgroundColor": bar_color,
                "borderRadius":    "5px",
                "transition":      "width 0.4s ease",
            }
        ),
        style={
            "width":         "100%",
            "backgroundColor": "#e5e7eb",
            "borderRadius":  "5px",
            "marginBottom":  "8px",
        },
    )

    # Breakdown table rows
    bdown_rows = [
        html.Tr([
            html.Td(row["severity"],                          style={"color": _SEV_COLOR.get(row["severity"], "#6b7280"), "fontWeight": "600", "paddingRight": "12px"}),
            html.Td(f'×{row["count"]}',                      style={"textAlign": "center", "paddingRight": "12px"}),
            html.Td(f'−{float(row["penalty"]):.1f} pts',     style={"textAlign": "right",  "color": "#dc2626"}),
        ])
        for row in bdown if row.get("count", 0) > 0
    ]

    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Div(
                        grade,
                        style={
                            "fontSize":      "3rem",
                            "fontWeight":    "700",
                            "color":         grade_color,
                            "lineHeight":    "1",
                            "textAlign":     "center",
                        },
                    ),
                    html.Div(
                        "Grade",
                        style={"textAlign": "center", "color": "#57606a", "fontSize": "0.75rem"},
                    ),
                ], width=2),
                dbc.Col([
                    html.Div([
                        html.Span(
                            f"{score}",
                            style={"fontSize": "2rem", "fontWeight": "700", "color": grade_color},
                        ),
                        html.Span(" / 100", style={"color": "#57606a", "fontSize": "1rem"}),
                    ], className="mb-1"),
                    bar,
                    html.P(just, className="mb-2", style={"fontSize": "0.875rem", "color": "#374151"}),
                    html.Table(
                        bdown_rows,
                        style={"fontSize": "0.8rem", "borderCollapse": "collapse"},
                    ) if bdown_rows else None,
                ], width=10),
            ], align="center"),
        ]),
        className="mb-3",
        style={"borderLeft": f"4px solid {grade_color}"},
    )


# ── Report renderer ───────────────────────────────────────────────────────────

def _render_report(data: dict) -> html.Div:
    summary     = data.get("summary", {})
    findings    = data.get("findings", [])
    order       = data.get("refactoringOrder", [])
    score_report = data.get("scoreReport")

    detected = summary.get("smellsDetected", 0)
    priority = summary.get("highestPriority") or "—"
    p_color  = _SEV_COLOR.get(priority, "#6b7280")

    cards = []

    # Score card (shown first if available)
    if score_report:
        cards.append(_render_score_card(score_report))

    # Summary card
    cards.append(
        dbc.Card(
            dbc.CardBody([
                html.H5(f"📄 {data.get('fileName', 'unknown')}", className="card-title"),
                html.P(summary.get("overallAssessment", ""), className="mb-2"),
                dbc.Badge(f"Smells detected: {detected}", color="secondary", className="me-2"),
                dbc.Badge(
                    f"Highest priority: {priority}",
                    style={"backgroundColor": p_color},
                ),
            ]),
            className="mb-3",
        )
    )

    # One card per finding
    for f in findings:
        severity = f.get("severity", "Low")
        color    = _SEV_COLOR.get(severity, "#6b7280")
        loc      = f.get("location", {})

        loc_parts = [loc.get("fileName", "")]
        if loc.get("className"):
            loc_parts.append(loc["className"])
        if loc.get("methodName"):
            loc_parts.append(loc["methodName"])
        s, e = loc.get("startLine"), loc.get("endLine")
        if s and e:
            loc_parts.append(f"L{s}–{e}")
        elif s:
            loc_parts.append(f"L{s}")
        loc_str = " › ".join(filter(None, loc_parts))

        diff_lines = []
        for line in (f.get("diff") or "").strip().splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                diff_lines.append(html.Div(line, style={"color": "#16a34a"}))
            elif line.startswith("-") and not line.startswith("---"):
                diff_lines.append(html.Div(line, style={"color": "#dc2626"}))
            else:
                diff_lines.append(html.Div(line, style={"color": "#6b7280"}))

        cards.append(
            dbc.Card(
                [
                    dbc.CardHeader(
                        dbc.Row([
                            dbc.Col(html.Strong(f"#{f.get('id')} — {f.get('smell', '')}"), width=9),
                            dbc.Col(
                                dbc.Badge(severity, style={"backgroundColor": color}),
                                width=3, className="text-end",
                            ),
                        ])
                    ),
                    dbc.CardBody([
                        html.P(html.Small(f"📍 {loc_str}", className="text-muted"), className="mb-2"),
                        html.P(f.get("description", "")),
                        html.Strong("Impact") if f.get("impact") else None,
                        html.Ul([html.Li(i) for i in f.get("impact", [])]) if f.get("impact") else None,
                        html.Strong("Recommendation") if f.get("recommendation") else None,
                        html.P(f.get("recommendation", "")) if f.get("recommendation") else None,
                        dbc.Alert(
                            [html.Strong("📖 RAG Reference: "), f.get("ragReference", "")],
                            color="light",
                            className="mt-2 mb-2 py-1 px-2",
                            style={"fontSize": "0.85rem", "borderLeft": "3px solid #3b82d4"},
                        ) if f.get("ragReference") else None,
                        html.Div([
                            html.Strong("Diff"),
                            html.Pre(
                                diff_lines,
                                style={
                                    "fontSize": "0.8rem",
                                    "backgroundColor": "#f7f8fa",
                                    "padding": "8px",
                                    "borderRadius": "4px",
                                },
                            ),
                        ]) if diff_lines else None,
                    ]),
                ],
                className="mb-3",
            )
        )

    # Refactoring order
    if order:
        id_map = {f["id"]: f.get("smell", "") for f in findings if "id" in f}
        steps  = " → ".join(
            f"#{item.get('findingId')} {id_map.get(item.get('findingId'), '')}"
            for item in order
            if isinstance(item, dict)
        )
        cards.append(
            dbc.Alert(
                [html.Strong("Suggested refactoring order: "), steps],
                color="info",
            )
        )

    return html.Div(cards)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)
