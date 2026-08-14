"""
Dash front-end for the Code Smell Analyzer.

Run with:
    python dash_app.py
Then open http://127.0.0.1:8050 in your browser.
"""

import json
import glob as _glob

import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc

from agent_setup import agent

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

# ── Layout ────────────────────────────────────────────────────────────────────

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

        dbc.Spinner(
            html.Div(id="report-output"),
            color="primary",
            type="border",
        ),
    ],
    fluid=False,
    style={"maxWidth": "900px"},
)

# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("report-output", "children"),
    Input("btn-analyze", "n_clicks"),
    State("file-dropdown", "value"),
    State("file-custom", "value"),
    prevent_initial_call=True,
)
def run_analysis(_n_clicks, dropdown_val, custom_val):
    file_path = (custom_val or "").strip() or (dropdown_val or "").strip()
    if not file_path:
        return dbc.Alert(
            "Please select or enter a file path before analyzing.", color="warning"
        )

    raw = agent.call_agent(f"Que Code Smells detectas en este archivo? {file_path}")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return dbc.Alert(
            [html.Strong("Agent returned invalid JSON. Raw output:"), html.Pre(raw)],
            color="danger",
        )

    return _render_report(result)


# ── Report renderer ───────────────────────────────────────────────────────────

def _render_report(data: dict):
    summary  = data.get("summary", {})
    findings = data.get("findings", [])
    order    = data.get("refactoringOrder", [])

    detected = summary.get("smellsDetected", 0)
    priority = summary.get("highestPriority") or "—"
    p_color  = _SEV_COLOR.get(priority, "#6b7280")

    cards = []

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
