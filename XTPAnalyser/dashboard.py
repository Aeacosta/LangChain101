"""
XTP Analyser — Dash Dashboard
==============================
Two-tab Dash application:

  • Generate  — AI pipeline (XTPGeneratorAgent → XTPDeliveryAgent) that
                produces a fresh Program A / B pair and Bin2Bin matrix.
  • Analyse   — Analysis pipeline (XTPAnalysisGraph) that diffs two uploaded
                XTP programs against a Bin2Bin CSV and returns a mismatch
                justification table.

Both tabs share the same upload dropzones for Program A, Program B and
Bin2Bin CSV (whose contents are displayed in a three-panel viewer below).

Usage
-----
    python -m XTPAnalyser.dashboard
    # then open http://127.0.0.1:8050
"""

from __future__ import annotations

import base64
import difflib
import json
import os
import threading
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, ctx, dash_table, dcc, html
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OUTPUT_FOLDER = Path("Programas")
OUTPUT_FOLDER.mkdir(exist_ok=True)

_PROG_A  = OUTPUT_FOLDER / "Program_A.xtp"
_PROG_B  = OUTPUT_FOLDER / "Program_B.xtp"
_BIN2BIN = OUTPUT_FOLDER / "Bin2Bin_Matrix.csv"

# ---------------------------------------------------------------------------
# Thread-safe pipeline state stores
# ---------------------------------------------------------------------------

_gen_lock  = threading.Lock()
_gen_state: dict  = {"running": False, "log": [], "done": False, "error": None}

_anl_lock  = threading.Lock()
_anl_state: dict  = {
    "running": False, "log": [], "done": False, "error": None,
    "mismatch_json": None, "justification_text": None,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_slot(slot: str) -> tuple[str, str] | tuple[None, None]:
    """Return (content, filename) for a slot, or (None, None) if missing."""
    path = {"a": _PROG_A, "b": _PROG_B, "bin": _BIN2BIN}.get(slot)
    if path is None or not path.exists():
        return None, None
    return path.read_text(encoding="utf-8"), path.name


def _save_upload(slot: str, contents: str, filename: str) -> tuple[str, str]:
    """Decode a Dash upload data-URL, save to disk, return (text, filename)."""
    path = {"a": _PROG_A, "b": _PROG_B, "bin": _BIN2BIN}.get(slot)
    if path is None:
        raise ValueError(f"Unknown slot: {slot!r}")
    _content_type, b64 = contents.split(",", 1)
    decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
    path.write_text(decoded, encoding="utf-8")
    return decoded, filename


def _log_gen(msg: str) -> None:
    with _gen_lock:
        _gen_state["log"].append(msg)


def _log_anl(msg: str) -> None:
    with _anl_lock:
        _anl_state["log"].append(msg)


# ---------------------------------------------------------------------------
# XTP syntax highlighter (returns a list of dcc.Markdown / html.Span safe text)
# We keep it simple: return plain text inside a <pre> — the dark theme does the rest.
# ---------------------------------------------------------------------------

def _xtp_viewer(text: str | None) -> html.Div:
    if not text:
        return html.Div("No file loaded", className="empty-state")
    return html.Pre(text, className="xtp-code")


def _diff_viewer(text_a: str | None, text_b: str | None) -> html.Div:
    """Render a unified diff of two XTP texts as a syntax-coloured block."""
    if not text_a and not text_b:
        return html.Div("Load both programs to see the diff", className="empty-state")
    if not text_a:
        return html.Div("Program A not loaded", className="empty-state")
    if not text_b:
        return html.Div("Program B not loaded", className="empty-state")

    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines_a, lines_b,
                                     fromfile="Program A", tofile="Program B"))
    if not diff:
        return html.Div("No differences — programs are identical ✓",
                        className="empty-state diff-identical")

    spans: list = []
    for line in diff:
        line_str = line.rstrip("\n")
        if line_str.startswith("+++") or line_str.startswith("---"):
            cls = "diff-header"
        elif line_str.startswith("@@"):
            cls = "diff-hunk"
        elif line_str.startswith("+"):
            cls = "diff-add"
        elif line_str.startswith("-"):
            cls = "diff-del"
        else:
            cls = "diff-ctx"
        spans.append(html.Span(line_str + "\n", className=cls))

    return html.Pre(spans, className="xtp-code diff-view")


def _csv_viewer(text: str | None) -> html.Div:
    if not text:
        return html.Div("No matrix loaded", className="empty-state")
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return html.Div("Empty file", className="empty-state")
    header = [c.strip() for c in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(",")]
        rows.append({h: c for h, c in zip(header, cells)})
    return dash_table.DataTable(
        columns=[{"name": h, "id": h} for h in header],
        data=rows,
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#1e293b", "color": "#a78bfa",
            "fontWeight": "700", "fontSize": "0.74rem",
        },
        style_data={
            "backgroundColor": "#0c0f1a", "color": "#cbd5e1",
            "fontSize": "0.74rem", "border": "1px solid #2d3748",
        },
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#111827"},
        ],
    )


# ---------------------------------------------------------------------------
# Dropzone component factory
# ---------------------------------------------------------------------------

def _dz_idle(title: str, accept: str) -> list:
    """Default dropzone label — shown when no file is loaded."""
    return [
        html.Span(title, className="dz-title"),
        html.Br(),
        html.Span(f"Drop {accept} or click", className="dz-label"),
    ]


def _dz_loaded(title: str, filename: str, line_count: int) -> list:
    """Dropzone label — shown after a file has been successfully loaded."""
    return [
        html.Span(title, className="dz-title"),
        html.Br(),
        html.Span(f"✓ {filename}", className="dz-filename"),
        html.Br(),
        html.Span(f"{line_count} lines · click to replace", className="dz-label"),
    ]


def _dropzone(slot: str, title: str, accept: str, id_prefix: str) -> dbc.Card:
    return dbc.Card(
        dcc.Upload(
            id=f"{id_prefix}-dz-{slot}",
            children=html.Div(
                _dz_idle(title, accept),
                id=f"{id_prefix}-dz-label-{slot}",
                className="dz-inner",
            ),
            accept=accept,
            className="drop-zone",
            style={"width": "100%"},
        ),
        className="dropzone-card",
    )


# ---------------------------------------------------------------------------
# Pipeline log modal (reusable across both tabs via different IDs)
# ---------------------------------------------------------------------------

def _log_modal(modal_id: str, title: str) -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(title), close_button=False),
            dbc.ModalBody(
                html.Div(id=f"{modal_id}-body", className="log-scroll"),
            ),
            dbc.ModalFooter(
                dbc.Button("Close", id=f"{modal_id}-close", color="secondary",
                           disabled=True, n_clicks=0)
            ),
        ],
        id=modal_id,
        is_open=False,
        size="lg",
        backdrop="static",
    )


# ---------------------------------------------------------------------------
# Three-panel file viewer (shared between tabs via store)
# ---------------------------------------------------------------------------

def _file_viewer() -> html.Div:
    return html.Div([
        # ── Top section: toggle bar + program panels / diff panel ──────────
        html.Div([
            # Toggle header bar (shared across both view modes)
            html.Div([
                html.Div([
                    # Left cluster: program badges
                    html.Div([
                        html.Span("Program A", className="panel-title"),
                        html.Span("—", id="badge-a", className="badge"),
                        html.Span("vs", className="badge-vs"),
                        html.Span("Program B", className="panel-title"),
                        html.Span("—", id="badge-b", className="badge"),
                    ], className="panel-title-group"),
                    # Right cluster: Raw / Diff toggle
                    html.Div([
                        html.Button("Raw", id="btn-view-raw",
                                    className="view-toggle active", n_clicks=0),
                        html.Button("Diff", id="btn-view-diff",
                                    className="view-toggle", n_clicks=0),
                    ], className="view-toggle-group"),
                ], className="top-header-inner"),
            ], className="top-header"),

            # Raw view: two side-by-side panels
            html.Div([
                html.Div(id="body-a", className="panel-body split-panel"),
                html.Div(id="body-b", className="panel-body split-panel split-panel-right"),
            ], id="view-raw", className="split-row"),

            # Diff view: single full-width panel (hidden by default)
            html.Div([
                html.Div(id="body-diff", className="panel-body"),
            ], id="view-diff", className="diff-row", style={"display": "none"}),

        ], className="top-section"),

        # ── Bottom row: Bin2Bin matrix ──────────────────────────────────────
        html.Div([
            html.Div([
                html.Span("Bin2Bin Matrix", className="panel-title"),
                html.Span("—", id="badge-bin", className="badge"),
            ], className="panel-header"),
            html.Div(id="body-bin", className="panel-body"),
        ], className="bottom-row panel"),
    ], className="viewer-layout")


# ---------------------------------------------------------------------------
# Tab: Generate
# ---------------------------------------------------------------------------

_tab_generate = dbc.Tab(
    label="✦ Generate",
    tab_id="tab-generate",
    children=html.Div([
        html.Div([
            dbc.Button("✦ Generate New Pair", id="btn-generate", color="primary",
                       className="btn-action"),
            html.Div(className="sep"),
            _dropzone("a",   "Program A", ".xtp,.txt", "gen"),
            _dropzone("b",   "Program B", ".xtp,.txt", "gen"),
            _dropzone("bin", "Bin2Bin",   ".csv,.txt", "gen"),
            dbc.Button("↺ Refresh", id="btn-refresh-gen", outline=True,
                       color="secondary", className="ms-auto"),
        ], className="toolbar"),
        _log_modal("gen-modal", "⚙ Generating XTP pair + Bin2Bin…"),
        dcc.Interval(id="gen-interval", interval=800, disabled=True, n_intervals=0),
    ]),
)

# ---------------------------------------------------------------------------
# Tab: Analyse
# ---------------------------------------------------------------------------

_tab_analyse = dbc.Tab(
    label="🔬 Analyse",
    tab_id="tab-analyse",
    children=html.Div([
        html.Div([
            dbc.Button("▶ Run Analysis", id="btn-analyse", color="success",
                       className="btn-action"),
            html.Div(className="sep"),
            _dropzone("a",   "Program A", ".xtp,.txt", "anl"),
            _dropzone("b",   "Program B", ".xtp,.txt", "anl"),
            _dropzone("bin", "Bin2Bin",   ".csv,.txt", "anl"),
            dbc.Button("↺ Refresh", id="btn-refresh-anl", outline=True,
                       color="secondary", className="ms-auto"),
        ], className="toolbar"),
        _log_modal("anl-modal", "🔬 Running XTP Analysis Pipeline…"),
        dcc.Interval(id="anl-interval", interval=800, disabled=True, n_intervals=0),
    ]),
)

# ---------------------------------------------------------------------------
# App layout  — single shared viewer lives here, outside the tabs
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.SLATE],
    title="XTP Analyser",
    suppress_callback_exceptions=True,
)

app.layout = html.Div([
    # ── Header ──
    html.Header([
        html.H1("⬡ XTP Analyser"),
        html.Span("ATE Test Program Dashboard"),
    ], className="app-header"),

    # ── Tabs (toolbars + modals only — no viewer here) ──
    dbc.Tabs(
        [_tab_generate, _tab_analyse],
        id="main-tabs",
        active_tab="tab-generate",
        className="main-tabs",
    ),

    # ── Single file viewer shared by both tabs ──
    _file_viewer(),

    # ── Analysis results (hidden until pipeline completes) ──
    html.Div(id="anl-results", className="results-panel"),

    # ── Shared data stores (survive tab switches) ──
    dcc.Store(id="store-a"),
    dcc.Store(id="store-b"),
    dcc.Store(id="store-bin"),
], className="app-root")


# ---------------------------------------------------------------------------
# Custom CSS injected via assets or index_string
# ---------------------------------------------------------------------------

app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system,"Segoe UI",system-ui,sans-serif;
       background:#0f1117; color:#e2e8f0; min-height:100vh; }

.app-root { display:flex; flex-direction:column; height:100vh; overflow:hidden; }

/* Header */
.app-header { display:flex; align-items:center; justify-content:space-between;
  padding:12px 28px; background:#161b27; border-bottom:1px solid #2d3748;
  flex-shrink:0; }
.app-header h1 { font-size:1.05rem; font-weight:700; color:#a78bfa;
  letter-spacing:.04em; margin:0; }
.app-header span { font-size:.78rem; color:#64748b; }

/* Tabs */
.main-tabs { flex-shrink:0; background:#161b27; border-bottom:1px solid #2d3748;
  padding: 0 20px; }
.nav-tabs { border-bottom:none !important; }
.nav-tabs .nav-link { color:#64748b !important; border:none !important;
  padding:10px 18px; font-size:.82rem; font-weight:600; border-radius:0 !important; }
.nav-tabs .nav-link.active { color:#a78bfa !important; background:transparent !important;
  border-bottom:2px solid #7c3aed !important; }
.nav-tabs .nav-link:hover { color:#94a3b8 !important; }
.tab-content { overflow:hidden; display:flex; flex-direction:column; }
.tab-pane { overflow:hidden; display:flex; flex-direction:column; }
.tab-pane > div { display:flex; flex-direction:column; overflow:hidden; }

/* Toolbar */
.toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center;
  padding:12px 24px; background:#161b27; border-bottom:1px solid #2d3748;
  flex-shrink:0; z-index:1; }
.btn-action { font-size:.83rem; font-weight:600 !important; padding:7px 18px !important; }
.sep { width:1px; height:22px; background:#2d3748; }

/* Dropzone cards */
.dropzone-card { background:transparent !important; border:none !important; }
.drop-zone { display:flex; flex-direction:column; align-items:center;
  justify-content:center; gap:0; border:2px dashed #334155 !important;
  border-radius:8px !important; padding:12px 20px; min-width:170px;
  cursor:pointer; transition:border-color .2s, background .2s;
  background:#0f1117 !important; text-align:center; }
.drop-zone:hover { border-color:#7c3aed !important; }
/* loaded state — solid accent border + faint tint */
.drop-zone.dz-loaded { border:2px solid #7c3aed !important;
  background:#130f1f !important; }
.dz-inner { display:flex; flex-direction:column; align-items:center; gap:3px; }
.dz-title { font-size:.80rem; font-weight:700; color:#94a3b8; }
.dz-filename { font-size:.76rem; font-weight:600; color:#a78bfa;
  max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.dz-label { font-size:.70rem; color:#475569; }

/* Three-panel viewer — lives outside tabs, fills remaining height */
.viewer-layout { flex:1; display:flex; flex-direction:column; overflow:hidden; min-height:0; }

/* Top section: contains header bar + raw/diff views */
.top-section { flex:1; display:flex; flex-direction:column; min-height:0; overflow:hidden; }

/* Header bar above the programs */
.top-header { display:flex; align-items:center; background:#161b27;
  border-bottom:1px solid #2d3748; padding:6px 16px; flex-shrink:0; }
.top-header-inner { display:flex; align-items:center;
  justify-content:space-between; width:100%; }
.panel-title-group { display:flex; align-items:center; gap:8px; }
.badge-vs { font-size:.68rem; color:#475569; padding:0 4px; }

/* Raw/Diff toggle buttons */
.view-toggle-group { display:flex; gap:4px; }
.view-toggle { background:#1e293b; color:#64748b; border:1px solid #334155;
  border-radius:6px; padding:4px 14px; font-size:.76rem; font-weight:600;
  cursor:pointer; transition:background .15s, color .15s; }
.view-toggle:hover { background:#2d3748; color:#94a3b8; }
.view-toggle.active { background:#7c3aed; color:#fff; border-color:#7c3aed; }

/* Raw split view */
.split-row { display:grid; grid-template-columns:1fr 1fr;
  flex:1; min-height:0; overflow:hidden; }
.split-panel { overflow:auto; border-right:1px solid #1e293b; }
.split-panel-right { border-right:none; }

/* Diff full-width view */
.diff-row { flex:1; min-height:0; overflow:hidden; display:flex; flex-direction:column; }

/* Bottom matrix row */
.bottom-row { height:220px; border-top:2px solid #2d3748; flex-shrink:0; }
.panel { display:flex; flex-direction:column; overflow:hidden; }
.panel-header { display:flex; align-items:center; justify-content:space-between;
  padding:8px 16px; background:#161b27; border-bottom:1px solid #2d3748;
  flex-shrink:0; }
.panel-title { font-size:.78rem; font-weight:700; letter-spacing:.08em; color:#7c3aed; }
.badge { font-size:.67rem; font-weight:500; color:#64748b; background:#1e293b;
  padding:2px 8px; border-radius:20px; }
.panel-body { flex:1; overflow:auto; }

/* Code / diff viewer */
.xtp-code { margin:0; padding:14px 18px; font-family:"Cascadia Code","Fira Code",
  "Consolas",monospace; font-size:.76rem; line-height:1.65; white-space:pre-wrap;
  word-break:break-word; color:#cbd5e1; background:#0c0f1a;
  min-height:100%; display:block; }
.empty-state { display:flex; align-items:center; justify-content:center;
  height:100%; color:#334155; font-size:.82rem; }
.diff-identical { color:#34d399 !important; }

/* Diff line colours */
.diff-header { color:#94a3b8; font-style:italic; }
.diff-hunk   { color:#7c5cd8; font-weight:600; background:#1a1332;
  display:block; padding:0 2px; border-radius:2px; }
.diff-add    { color:#34d399; background:#0d2a1a; display:block; }
.diff-del    { color:#f87171; background:#2a0f0f; display:block; }
.diff-ctx    { color:#64748b; display:block; }

/* Log modal */
.log-scroll { background:#0c0f1a; border-radius:6px; padding:12px 14px;
  font-family:"Cascadia Code","Consolas",monospace; font-size:.72rem;
  color:#94a3b8; line-height:1.6; max-height:50vh; overflow-y:auto; }
.modal-content { background:#0f1117 !important; border:1px solid #334155 !important; }
.modal-header { border-bottom:1px solid #1e293b !important; }
.modal-header .modal-title { color:#a78bfa; font-size:.9rem; }
.modal-footer { border-top:1px solid #1e293b !important; }

/* Results panel — hidden when empty, visible once analysis populates it */
.results-panel:empty { display:none; }
.results-panel { border-top:2px solid #7c3aed; background:#0c0f1a;
  padding:20px 24px; overflow:auto; max-height:40vh; flex-shrink:0; }
.results-panel h4 { color:#a78bfa; font-size:.88rem; margin-bottom:12px; }
.results-warning { color:#f59e0b; font-size:.82rem; white-space:pre-wrap;
  font-family:"Cascadia Code","Consolas",monospace; }
</style>
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Helpers — dropzone feedback + diff
# ---------------------------------------------------------------------------

def _dz_update(title: str, accept: str, text: str | None, filename: str | None):
    """Return (dz_label_children, dz_className) depending on whether a file is loaded."""
    if text and filename:
        lc = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        return _dz_loaded(title, filename, lc), "drop-zone dz-loaded"
    return _dz_idle(title, accept), "drop-zone"


# ===========================================================================
# Callback — Raw / Diff toggle
# ===========================================================================

@callback(
    Output("view-raw",      "style"),
    Output("view-diff",     "style"),
    Output("btn-view-raw",  "className"),
    Output("btn-view-diff", "className"),
    Input("btn-view-raw",   "n_clicks"),
    Input("btn-view-diff",  "n_clicks"),
    prevent_initial_call=True,
)
def toggle_view(n_raw, n_diff):
    triggered = ctx.triggered_id
    if triggered == "btn-view-diff":
        return (
            {"display": "none"},   # hide raw
            {"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0"},  # show diff
            "view-toggle",         # raw inactive
            "view-toggle active",  # diff active
        )
    # default: raw
    return (
        {},                        # show raw (grid)
        {"display": "none"},       # hide diff
        "view-toggle active",      # raw active
        "view-toggle",             # diff inactive
    )


# ===========================================================================
# Callbacks — Generate tab
# ===========================================================================

# ── Upload dropzones (Generate tab) ────────────────────────────────────────

@callback(
    Output("store-a",          "data",     allow_duplicate=True),
    Output("body-a",           "children", allow_duplicate=True),
    Output("badge-a",          "children", allow_duplicate=True),
    Output("gen-dz-label-a",   "children"),
    Output("gen-dz-a",         "className"),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("gen-dz-a",          "contents"),
    State("gen-dz-a",          "filename"),
    State("store-b",           "data"),
    prevent_initial_call=True,
)
def gen_upload_a(contents, filename, text_b):
    if not contents:
        return (dash.no_update,) * 6
    text, fname = _save_upload("a", contents, filename)
    lbl, cls = _dz_update("Program A", ".xtp,.txt", text, fname)
    other = text_b or _read_slot("b")[0]
    return text, _xtp_viewer(text), fname, lbl, cls, _diff_viewer(text, other)


@callback(
    Output("store-b",          "data",     allow_duplicate=True),
    Output("body-b",           "children", allow_duplicate=True),
    Output("badge-b",          "children", allow_duplicate=True),
    Output("gen-dz-label-b",   "children"),
    Output("gen-dz-b",         "className"),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("gen-dz-b",          "contents"),
    State("gen-dz-b",          "filename"),
    State("store-a",           "data"),
    prevent_initial_call=True,
)
def gen_upload_b(contents, filename, text_a):
    if not contents:
        return (dash.no_update,) * 6
    text, fname = _save_upload("b", contents, filename)
    lbl, cls = _dz_update("Program B", ".xtp,.txt", text, fname)
    other = text_a or _read_slot("a")[0]
    return text, _xtp_viewer(text), fname, lbl, cls, _diff_viewer(other, text)


@callback(
    Output("store-bin",        "data",     allow_duplicate=True),
    Output("body-bin",         "children", allow_duplicate=True),
    Output("badge-bin",        "children", allow_duplicate=True),
    Output("gen-dz-label-bin", "children"),
    Output("gen-dz-bin",       "className"),
    Input("gen-dz-bin",        "contents"),
    State("gen-dz-bin",        "filename"),
    prevent_initial_call=True,
)
def gen_upload_bin(contents, filename):
    if not contents:
        return (dash.no_update,) * 5
    text, fname = _save_upload("bin", contents, filename)
    lbl, cls = _dz_update("Bin2Bin", ".csv,.txt", text, fname)
    return text, _csv_viewer(text), fname, lbl, cls


# ── Refresh (Generate tab) ─────────────────────────────────────────────────

@callback(
    Output("body-a",           "children", allow_duplicate=True),
    Output("body-b",           "children", allow_duplicate=True),
    Output("body-bin",         "children", allow_duplicate=True),
    Output("badge-a",          "children", allow_duplicate=True),
    Output("badge-b",          "children", allow_duplicate=True),
    Output("badge-bin",        "children", allow_duplicate=True),
    Output("store-a",          "data",     allow_duplicate=True),
    Output("store-b",          "data",     allow_duplicate=True),
    Output("store-bin",        "data",     allow_duplicate=True),
    Output("gen-dz-label-a",   "children", allow_duplicate=True),
    Output("gen-dz-label-b",   "children", allow_duplicate=True),
    Output("gen-dz-label-bin", "children", allow_duplicate=True),
    Output("gen-dz-a",         "className", allow_duplicate=True),
    Output("gen-dz-b",         "className", allow_duplicate=True),
    Output("gen-dz-bin",       "className", allow_duplicate=True),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("btn-refresh-gen",   "n_clicks"),
    prevent_initial_call=True,
)
def gen_refresh(_):
    a_txt,   a_fn   = _read_slot("a")
    b_txt,   b_fn   = _read_slot("b")
    bin_txt, bin_fn = _read_slot("bin")
    lbl_a,   cls_a   = _dz_update("Program A", ".xtp,.txt", a_txt,   a_fn)
    lbl_b,   cls_b   = _dz_update("Program B", ".xtp,.txt", b_txt,   b_fn)
    lbl_bin, cls_bin = _dz_update("Bin2Bin",   ".csv,.txt", bin_txt, bin_fn)
    return (
        _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
        a_fn or "—", b_fn or "—", bin_fn or "—",
        a_txt, b_txt, bin_txt,
        lbl_a, lbl_b, lbl_bin,
        cls_a, cls_b, cls_bin,
        _diff_viewer(a_txt, b_txt),
    )


# ── Generate button → open modal + start thread ────────────────────────────

@callback(
    Output("gen-modal",    "is_open", allow_duplicate=True),
    Output("gen-interval", "disabled", allow_duplicate=True),
    Output("btn-generate", "disabled", allow_duplicate=True),
    Input("btn-generate",  "n_clicks"),
    prevent_initial_call=True,
)
def gen_start(_n):
    with _gen_lock:
        if _gen_state["running"]:
            return dash.no_update, dash.no_update, dash.no_update
        _gen_state.update({"running": True, "log": [], "done": False, "error": None})
    threading.Thread(target=_run_gen_pipeline, daemon=True).start()
    return True, False, True   # open modal, enable interval, disable button


@callback(
    Output("gen-modal-body",   "children"),
    Output("gen-modal-close",  "disabled"),
    Output("gen-interval",     "disabled", allow_duplicate=True),
    Output("btn-generate",     "disabled", allow_duplicate=True),
    Output("body-a",           "children", allow_duplicate=True),
    Output("body-b",           "children", allow_duplicate=True),
    Output("body-bin",         "children", allow_duplicate=True),
    Output("badge-a",          "children", allow_duplicate=True),
    Output("badge-b",          "children", allow_duplicate=True),
    Output("badge-bin",        "children", allow_duplicate=True),
    Output("gen-dz-label-a",   "children", allow_duplicate=True),
    Output("gen-dz-label-b",   "children", allow_duplicate=True),
    Output("gen-dz-label-bin", "children", allow_duplicate=True),
    Output("gen-dz-a",         "className", allow_duplicate=True),
    Output("gen-dz-b",         "className", allow_duplicate=True),
    Output("gen-dz-bin",       "className", allow_duplicate=True),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("gen-interval",      "n_intervals"),
    prevent_initial_call=True,
)
def gen_poll(_):
    with _gen_lock:
        state = dict(_gen_state)

    log_children = [
        html.P(line, className=_log_class(line))
        for line in state["log"]
    ]
    done = state["done"] or bool(state["error"])

    if done:
        a_txt,   a_fn   = _read_slot("a")
        b_txt,   b_fn   = _read_slot("b")
        bin_txt, bin_fn = _read_slot("bin")
        lbl_a,   cls_a   = _dz_update("Program A", ".xtp,.txt", a_txt,   a_fn)
        lbl_b,   cls_b   = _dz_update("Program B", ".xtp,.txt", b_txt,   b_fn)
        lbl_bin, cls_bin = _dz_update("Bin2Bin",   ".csv,.txt", bin_txt, bin_fn)
        return (
            log_children, False, True, False,
            _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
            a_fn or "—", b_fn or "—", bin_fn or "—",
            lbl_a, lbl_b, lbl_bin,
            cls_a, cls_b, cls_bin,
            _diff_viewer(a_txt, b_txt),
        )

    return log_children, True, False, True, *([dash.no_update] * 13)


@callback(
    Output("gen-modal", "is_open", allow_duplicate=True),
    Input("gen-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def gen_close_modal(_):
    return False


# ===========================================================================
# Callbacks — Analyse tab
# ===========================================================================

# ── Upload dropzones (Analyse tab) ─────────────────────────────────────────

@callback(
    Output("store-a",          "data",     allow_duplicate=True),
    Output("body-a",           "children", allow_duplicate=True),
    Output("badge-a",          "children", allow_duplicate=True),
    Output("anl-dz-label-a",   "children"),
    Output("anl-dz-a",         "className"),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("anl-dz-a",          "contents"),
    State("anl-dz-a",          "filename"),
    State("store-b",           "data"),
    prevent_initial_call=True,
)
def anl_upload_a(contents, filename, text_b):
    if not contents:
        return (dash.no_update,) * 6
    text, fname = _save_upload("a", contents, filename)
    lbl, cls = _dz_update("Program A", ".xtp,.txt", text, fname)
    other = text_b or _read_slot("b")[0]
    return text, _xtp_viewer(text), fname, lbl, cls, _diff_viewer(text, other)


@callback(
    Output("store-b",          "data",     allow_duplicate=True),
    Output("body-b",           "children", allow_duplicate=True),
    Output("badge-b",          "children", allow_duplicate=True),
    Output("anl-dz-label-b",   "children"),
    Output("anl-dz-b",         "className"),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("anl-dz-b",          "contents"),
    State("anl-dz-b",          "filename"),
    State("store-a",           "data"),
    prevent_initial_call=True,
)
def anl_upload_b(contents, filename, text_a):
    if not contents:
        return (dash.no_update,) * 6
    text, fname = _save_upload("b", contents, filename)
    lbl, cls = _dz_update("Program B", ".xtp,.txt", text, fname)
    other = text_a or _read_slot("a")[0]
    return text, _xtp_viewer(text), fname, lbl, cls, _diff_viewer(other, text)


@callback(
    Output("store-bin",        "data",     allow_duplicate=True),
    Output("body-bin",         "children", allow_duplicate=True),
    Output("badge-bin",        "children", allow_duplicate=True),
    Output("anl-dz-label-bin", "children"),
    Output("anl-dz-bin",       "className"),
    Input("anl-dz-bin",        "contents"),
    State("anl-dz-bin",        "filename"),
    prevent_initial_call=True,
)
def anl_upload_bin(contents, filename):
    if not contents:
        return (dash.no_update,) * 5
    text, fname = _save_upload("bin", contents, filename)
    lbl, cls = _dz_update("Bin2Bin", ".csv,.txt", text, fname)
    return text, _csv_viewer(text), fname, lbl, cls


# ── Refresh (Analyse tab) ──────────────────────────────────────────────────

@callback(
    Output("body-a",           "children", allow_duplicate=True),
    Output("body-b",           "children", allow_duplicate=True),
    Output("body-bin",         "children", allow_duplicate=True),
    Output("badge-a",          "children", allow_duplicate=True),
    Output("badge-b",          "children", allow_duplicate=True),
    Output("badge-bin",        "children", allow_duplicate=True),
    Output("store-a",          "data",     allow_duplicate=True),
    Output("store-b",          "data",     allow_duplicate=True),
    Output("store-bin",        "data",     allow_duplicate=True),
    Output("anl-dz-label-a",   "children", allow_duplicate=True),
    Output("anl-dz-label-b",   "children", allow_duplicate=True),
    Output("anl-dz-label-bin", "children", allow_duplicate=True),
    Output("anl-dz-a",         "className", allow_duplicate=True),
    Output("anl-dz-b",         "className", allow_duplicate=True),
    Output("anl-dz-bin",       "className", allow_duplicate=True),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("btn-refresh-anl",   "n_clicks"),
    prevent_initial_call=True,
)
def anl_refresh(_):
    a_txt,   a_fn   = _read_slot("a")
    b_txt,   b_fn   = _read_slot("b")
    bin_txt, bin_fn = _read_slot("bin")
    lbl_a,   cls_a   = _dz_update("Program A", ".xtp,.txt", a_txt,   a_fn)
    lbl_b,   cls_b   = _dz_update("Program B", ".xtp,.txt", b_txt,   b_fn)
    lbl_bin, cls_bin = _dz_update("Bin2Bin",   ".csv,.txt", bin_txt, bin_fn)
    return (
        _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
        a_fn or "—", b_fn or "—", bin_fn or "—",
        a_txt, b_txt, bin_txt,
        lbl_a, lbl_b, lbl_bin,
        cls_a, cls_b, cls_bin,
        _diff_viewer(a_txt, b_txt),
    )


# ── Analyse button → open modal + start thread ─────────────────────────────

@callback(
    Output("anl-modal",    "is_open", allow_duplicate=True),
    Output("anl-interval", "disabled", allow_duplicate=True),
    Output("btn-analyse",  "disabled", allow_duplicate=True),
    Input("btn-analyse",   "n_clicks"),
    State("store-a",  "data"),
    State("store-b",  "data"),
    State("store-bin","data"),
    prevent_initial_call=True,
)
def anl_start(_n, text_a, text_b, text_bin):
    # Validate — all three files must be available (from disk or store)
    a_txt   = text_a   or (_read_slot("a")[0])
    b_txt   = text_b   or (_read_slot("b")[0])
    bin_txt = text_bin or (_read_slot("bin")[0])
    if not a_txt or not b_txt or not bin_txt:
        return dash.no_update, dash.no_update, dash.no_update

    with _anl_lock:
        if _anl_state["running"]:
            return dash.no_update, dash.no_update, dash.no_update
        _anl_state.update({
            "running": True, "log": [], "done": False,
            "error": None, "mismatch_json": None, "justification_text": None,
        })
    threading.Thread(
        target=_run_anl_pipeline,
        args=(str(_PROG_A), str(_PROG_B), str(_BIN2BIN)),
        daemon=True,
    ).start()
    return True, False, True


@callback(
    Output("anl-modal-body",  "children"),
    Output("anl-modal-close", "disabled"),
    Output("anl-interval",    "disabled", allow_duplicate=True),
    Output("btn-analyse",     "disabled", allow_duplicate=True),
    Output("anl-results",     "children"),
    Input("anl-interval",     "n_intervals"),
    prevent_initial_call=True,
)
def anl_poll(_):
    with _anl_lock:
        state = dict(_anl_state)

    log_children = [
        html.P(line, className=_log_class(line))
        for line in state["log"]
    ]
    done = state["done"] or bool(state["error"])

    results = dash.no_update
    if done:
        results = _build_results(state)
        return log_children, False, True, False, results

    return log_children, True, False, True, dash.no_update


@callback(
    Output("anl-modal", "is_open", allow_duplicate=True),
    Input("anl-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def anl_close_modal(_):
    return False


# ===========================================================================
# Pipeline runners (background threads)
# ===========================================================================

def _run_gen_pipeline() -> None:
    try:
        from Helpers.Logger import AgentLogger
        from XTPAnalyser.graph import XTPState, build_graph

        log = AgentLogger(name="xtp_gen_dash", level="INFO")
        log.add_ui_sink(_log_gen)

        pipeline = build_graph(logger=log)
        initial: XTPState = {"output_folder": str(OUTPUT_FOLDER), "log": log}

        for chunk in pipeline.stream(initial):
            for node_state in chunk.values():
                if node_state.get("error"):
                    raise RuntimeError(node_state["error"])

        with _gen_lock:
            _gen_state["done"] = True
            _gen_state["running"] = False

    except Exception as exc:  # noqa: BLE001
        _log_gen(f"✗ Pipeline error: {exc}")
        with _gen_lock:
            _gen_state["error"] = str(exc)
            _gen_state["done"] = True
            _gen_state["running"] = False


def _run_anl_pipeline(path_a: str, path_b: str, path_bin: str) -> None:
    try:
        from Helpers.Logger import AgentLogger
        from XTPAnalyser.AnalysisGraph import XTPAnalysisState, build_analysis_graph
        from XTPAnalyser.Agents.CompareFiles import XTPFileComparer

        log = AgentLogger(name="xtp_anl_dash", level="INFO")
        log.add_ui_sink(_log_anl)

        comparer  = XTPFileComparer(path_a, path_b)
        pipeline  = build_analysis_graph(logger=log)

        initial: XTPAnalysisState = {
            "file_comparer": comparer,
            "bin2bin_file":  path_bin,
            "log":           log,
        }

        final = pipeline.invoke(initial)

        with _anl_lock:
            _anl_state["mismatch_json"]      = final.get("mismatch_df_json")
            _anl_state["justification_text"] = final.get("justification_table")
            _anl_state["error"]              = final.get("error")
            _anl_state["done"]    = True
            _anl_state["running"] = False

    except Exception as exc:  # noqa: BLE001
        _log_anl(f"✗ Pipeline error: {exc}")
        with _anl_lock:
            _anl_state["error"]   = str(exc)
            _anl_state["done"]    = True
            _anl_state["running"] = False


# ===========================================================================
# Helpers
# ===========================================================================

def _log_class(line: str) -> str:
    if line.startswith("✓") or "SUCCESS" in line:
        return "log-done"
    if line.startswith("✗") or "ERROR" in line:
        return "log-err"
    return "log-line"


def _build_results(state: dict) -> html.Div:
    """Render the analysis results panel from pipeline final state."""
    if state.get("error") and not state.get("mismatch_json"):
        return html.Div([
            html.H4("⚠ Analysis Warning"),
            html.Pre(state["error"], className="results-warning"),
        ], className="results-panel")

    children: list = [html.H4("🔬 Mismatch Justification Table")]

    raw_json = state.get("mismatch_json")
    if raw_json:
        rows = json.loads(raw_json)
        if rows:
            cols = list(rows[0].keys())
            children.append(
                dash_table.DataTable(
                    columns=[{"name": c, "id": c} for c in cols],
                    data=rows,
                    style_table={"overflowX": "auto"},
                    style_header={
                        "backgroundColor": "#1e293b", "color": "#a78bfa",
                        "fontWeight": "700", "fontSize": "0.75rem",
                    },
                    style_data={
                        "backgroundColor": "#0c0f1a", "color": "#cbd5e1",
                        "fontSize": "0.75rem", "border": "1px solid #2d3748",
                        "whiteSpace": "normal", "height": "auto",
                    },
                    style_data_conditional=[
                        {"if": {"row_index": "odd"}, "backgroundColor": "#111827"},
                        {"if": {"column_id": "confidence", "filter_query": '{confidence} = "HIGH"'},
                         "color": "#34d399"},
                        {"if": {"column_id": "confidence", "filter_query": '{confidence} = "MEDIUM"'},
                         "color": "#fbbf24"},
                        {"if": {"column_id": "confidence", "filter_query": '{confidence} = "LOW"'},
                         "color": "#f87171"},
                    ],
                    page_size=20,
                )
            )
    elif state.get("justification_text"):
        # Fallback: show raw text if extraction failed
        children.append(html.Pre(state["justification_text"], className="results-warning"))

    return html.Div(children)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    app.run(debug=False, port=8050, host="0.0.0.0")
