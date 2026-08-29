"""
XTP Analyser — Dash Dashboard
==============================
Three-tab Dash application:

  • Generate    — AI pipeline (XTPGeneratorAgent → XTPDeliveryAgent) that
                  receives an uploaded XTP program (Program A), produces a
                  modified version (Program B) and a Bin2Bin matrix.
  • Analyse     — Analysis pipeline (XTPAnalysisGraph) that diffs two uploaded
                  XTP programs against a Bin2Bin CSV and returns a mismatch
                  justification table.
  • Git Bin2Bin — Enter two commit SHAs from the XTPProgram GitHub repo;
                  the pipeline fetches both program versions, diffs them,
                  produces a Bin2Bin matrix, and runs the Bin2Bin analysis.

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
_gen_state: dict  = {"running": False, "log": [], "done": False, "error": None,
                     "input_program": None}

_anl_lock  = threading.Lock()
_anl_state: dict  = {
    "running": False, "log": [], "done": False, "error": None,
    "mismatch_json": None, "justification_text": None,
    "pr_links_json": None, "pr_summary_md": None,
    "response_xtp_diff": None,
    "sha_a": "", "sha_b": "",
    "program_a": None, "program_b": None, "diff": None,
}

_git_lock  = threading.Lock()
_git_state: dict  = {
    "running": False, "log": [], "done": False, "error": None,
    "sha_a": "", "sha_b": "", "bin2bin_report": None,
    "program_a": None, "program_b": None, "diff": None,
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


def _log_git(msg: str) -> None:
    with _git_lock:
        _git_state["log"].append(msg)


# ---------------------------------------------------------------------------
# XTP syntax highlighter (returns a list of dcc.Markdown / html.Span safe text)
# We keep it simple: return plain text inside a <pre> — the dark theme does the rest.
# ---------------------------------------------------------------------------

def _xtp_viewer(text: str | None) -> html.Div:
    if not text:
        return html.Div("No file loaded", className="empty-state")
    return html.Pre(text, className="xtp-code")


def _diff_viewer(text_a: str | None, text_b: str | None) -> html.Div:
    """Render a coloured unified diff block for two XTP texts."""
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


def _full_diff_panel(
    text_a: str | None,
    text_b: str | None,
    response_xtp_diff: str | None = None,
    pr_summary_md: str | None = None,
) -> html.Div:
    """Render the full Diff panel: coloured unified diff + LLM analysis + PR summary."""
    sections: list = []

    # ── 1. Coloured unified diff ─────────────────────────────────────────────
    sections.append(
        html.Div([
            html.Div("◈ Unified Diff", className="diff-section-title"),
            _diff_viewer(text_a, text_b),
        ], className="diff-section")
    )

    # ── 2. LLM diff analysis (all recommendations) ──────────────────────────
    if response_xtp_diff:
        sections.append(
            html.Div([
                html.Div("◈ XTP Program Diff Analysis", className="diff-section-title"),
                dcc.Markdown(
                    response_xtp_diff,
                    className="diff-analysis-md",
                    dangerously_allow_html=False,
                ),
            ], className="diff-section")
        )

    # ── 3. PR summary ────────────────────────────────────────────────────────
    if pr_summary_md:
        sections.append(
            html.Div([
                html.Div("◈ PR Summary", className="diff-section-title"),
                dcc.Markdown(
                    pr_summary_md,
                    className="diff-analysis-md",
                    dangerously_allow_html=False,
                    link_target="_blank",
                ),
            ], className="diff-section")
        )

    return html.Div(sections, className="full-diff-panel")


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
                dbc.Button(
                    "↓ Export CSV",
                    id="btn-export-bin2bin",
                    size="sm",
                    outline=True,
                    color="secondary",
                    className="ms-auto export-btn",
                    disabled=True,
                ),
                dcc.Download(id="download-bin2bin"),
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
            dbc.Button("✦ Generate Modified Program", id="btn-generate", color="primary",
                       className="btn-action", disabled=True),
            html.Div(className="sep"),
            # Only the input program (Program A) is uploaded by the user.
            # Program B and Bin2Bin are produced by the pipeline and shown read-only.
            _dropzone("a", "Input Program (A)", ".xtp,.txt", "gen"),
            html.Span("→ Program B + Bin2Bin will appear after generation",
                      style={"fontSize": ".72rem", "color": "#475569", "alignSelf": "center"}),
            dbc.Button("↺ Refresh", id="btn-refresh-gen", outline=True,
                       color="secondary", className="ms-auto"),
        ], className="toolbar"),
        _log_modal("gen-modal", "⚙ Modifying XTP Program + Bin2Bin…"),
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
                       className="btn-action", disabled=True),
            html.Div(className="sep"),
            # SHA inputs — same style as the Git Bin2Bin tab
            html.Div([
                dbc.Label("Commit SHA A", html_for="anl-sha-a", className="git-label"),
                dbc.Input(
                    id="anl-sha-a",
                    placeholder="e.g. a1b2c3d…",
                    type="text",
                    className="git-sha-input",
                    debounce=True,
                ),
            ], className="git-sha-group"),
            html.Span("→", className="git-arrow"),
            html.Div([
                dbc.Label("Commit SHA B", html_for="anl-sha-b", className="git-label"),
                dbc.Input(
                    id="anl-sha-b",
                    placeholder="e.g. e4f5g6h…",
                    type="text",
                    className="git-sha-input",
                    debounce=True,
                ),
            ], className="git-sha-group"),
            html.Div(className="sep"),
            _dropzone("bin", "Bin2Bin",   ".csv,.txt", "anl"),
            dbc.Button("↺ Refresh", id="btn-refresh-anl", outline=True,
                       color="secondary", className="ms-auto"),
        ], className="toolbar"),
        _log_modal("anl-modal", "🔬 Running XTP Analysis Pipeline…"),
        dcc.Interval(id="anl-interval", interval=800, disabled=True, n_intervals=0),
    ]),
)

# ---------------------------------------------------------------------------
# Tab: Git Bin2Bin
# ---------------------------------------------------------------------------

_tab_git = dbc.Tab(
    label="⎇ Git Bin2Bin",
    tab_id="tab-git",
    children=html.Div([
        html.Div([
            # SHA inputs
            html.Div([
                dbc.Label("Commit SHA A", html_for="git-sha-a",
                          className="git-label"),
                dbc.Input(
                    id="git-sha-a",
                    placeholder="e.g. a1b2c3d…",
                    type="text",
                    className="git-sha-input",
                    debounce=True,
                ),
            ], className="git-sha-group"),
            html.Span("→", className="git-arrow"),
            html.Div([
                dbc.Label("Commit SHA B", html_for="git-sha-b",
                          className="git-label"),
                dbc.Input(
                    id="git-sha-b",
                    placeholder="e.g. e4f5g6h…",
                    type="text",
                    className="git-sha-input",
                    debounce=True,
                ),
            ], className="git-sha-group"),
            html.Div(className="sep"),
            dbc.Button(
                "⎇ Run Git Bin2Bin",
                id="btn-git",
                color="warning",
                className="btn-action",
                disabled=True,
            ),
            dbc.Button("↺ Refresh", id="btn-refresh-git", outline=True,
                       color="secondary", className="ms-auto"),
        ], className="toolbar"),
        _log_modal("git-modal", "⎇ Fetching commits & computing Bin2Bin…"),
        dcc.Interval(id="git-interval", interval=800, disabled=True, n_intervals=0),
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
        [_tab_generate, _tab_analyse, _tab_git],
        id="main-tabs",
        active_tab="tab-generate",
        className="main-tabs",
    ),

    # ── Single file viewer shared by all tabs ──
    _file_viewer(),

    # ── Analysis results (hidden until pipeline completes) ──
    html.Div(id="anl-results", className="results-panel"),

    # ── Git Bin2Bin results ──
    html.Div(id="git-results", className="results-panel"),

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
.panel-header { display:flex; align-items:center; gap:8px;
  padding:8px 16px; background:#161b27; border-bottom:1px solid #2d3748;
  flex-shrink:0; }
.export-btn { font-size:.70rem !important; padding:2px 10px !important;
  border-radius:5px !important; line-height:1.4 !important; }
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

/* Git Bin2Bin tab — SHA input controls */
.git-sha-group { display:flex; flex-direction:column; gap:3px; }
.git-label { font-size:.70rem; font-weight:600; color:#64748b;
  text-transform:uppercase; letter-spacing:.06em; margin:0; }
.git-sha-input { background:#0c0f1a !important; border:1px solid #334155 !important;
  color:#cbd5e1 !important; font-family:"Cascadia Code","Consolas",monospace;
  font-size:.80rem; border-radius:6px; padding:5px 10px; min-width:200px; }
.git-sha-input:focus { border-color:#7c3aed !important;
  box-shadow:0 0 0 2px rgba(124,58,237,.25) !important; }
.git-arrow { font-size:1.1rem; color:#475569; align-self:center;
  padding:0 4px; margin-top:16px; }

/* Git Bin2Bin report section */
.git-report { font-family:"Cascadia Code","Consolas",monospace; font-size:.76rem;
  color:#cbd5e1; white-space:pre-wrap; line-height:1.6; }

/* Git diff block inside results panel */
.git-diff-block { max-height:340px; overflow:auto; margin-bottom:16px; }

/* Widen the results panel when it contains a diff */
.results-panel { max-height:60vh !important; }

/* Full diff panel — stacked sections inside body-diff */
.full-diff-panel { display:flex; flex-direction:column; gap:0; height:100%; }
.diff-section { display:flex; flex-direction:column; border-bottom:1px solid #1e293b; }
.diff-section:last-child { border-bottom:none; flex:1; min-height:0; }
.diff-section-title { font-size:.70rem; font-weight:700; letter-spacing:.10em;
  text-transform:uppercase; color:#7c5cd8; background:#0f111a;
  padding:5px 16px; border-bottom:1px solid #1e293b; flex-shrink:0; }

/* Markdown rendered inside the diff panel */
.diff-analysis-md { padding:14px 20px; font-size:.80rem; line-height:1.7;
  color:#cbd5e1; overflow:auto; background:#0c0f1a; }
.diff-analysis-md h1,.diff-analysis-md h2,.diff-analysis-md h3 {
  color:#a78bfa; margin:14px 0 6px; font-size:.88rem; }
.diff-analysis-md h4,.diff-analysis-md h5 {
  color:#94a3b8; margin:10px 0 4px; font-size:.82rem; }
.diff-analysis-md strong { color:#e2e8f0; }
.diff-analysis-md table { border-collapse:collapse; width:100%;
  margin:10px 0; font-size:.75rem; }
.diff-analysis-md th { background:#1e293b; color:#a78bfa;
  padding:5px 10px; border:1px solid #2d3748; text-align:left; }
.diff-analysis-md td { padding:4px 10px; border:1px solid #2d3748;
  color:#cbd5e1; background:#0c0f1a; }
.diff-analysis-md tr:nth-child(even) td { background:#111827; }
.diff-analysis-md code { background:#1e293b; color:#f472b6;
  padding:1px 5px; border-radius:3px; font-size:.74rem; }
.diff-analysis-md a { color:#60a5fa; }
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

# ── Upload dropzone — Input Program A (Generate tab) ───────────────────────
# Uploading Program A enables the Generate button.

@callback(
    Output("store-a",          "data",     allow_duplicate=True),
    Output("body-a",           "children", allow_duplicate=True),
    Output("badge-a",          "children", allow_duplicate=True),
    Output("gen-dz-label-a",   "children"),
    Output("gen-dz-a",         "className"),
    Output("btn-generate",     "disabled", allow_duplicate=True),
    Input("gen-dz-a",          "contents"),
    State("gen-dz-a",          "filename"),
    prevent_initial_call=True,
)
def gen_upload_a(contents, filename):
    if not contents:
        return (dash.no_update,) * 6
    text, fname = _save_upload("a", contents, filename)
    lbl, cls = _dz_update("Input Program (A)", ".xtp,.txt", text, fname)
    # Enable the Generate button now that we have an input program
    return text, _xtp_viewer(text), fname, lbl, cls, False


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
    Output("gen-dz-a",         "className", allow_duplicate=True),
    Output("body-diff",        "children", allow_duplicate=True),
    Input("btn-refresh-gen",   "n_clicks"),
    prevent_initial_call=True,
)
def gen_refresh(_):
    a_txt,   a_fn   = _read_slot("a")
    b_txt,   b_fn   = _read_slot("b")
    bin_txt, bin_fn = _read_slot("bin")
    lbl_a, cls_a = _dz_update("Input Program (A)", ".xtp,.txt", a_txt, a_fn)
    return (
        _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
        a_fn or "—", b_fn or "—", bin_fn or "—",
        a_txt, b_txt, bin_txt,
        lbl_a, cls_a,
        _diff_viewer(a_txt, b_txt),
    )


# ── Generate button → open modal + start thread ────────────────────────────

@callback(
    Output("gen-modal",    "is_open", allow_duplicate=True),
    Output("gen-interval", "disabled", allow_duplicate=True),
    Output("btn-generate", "disabled", allow_duplicate=True),
    Input("btn-generate",  "n_clicks"),
    State("store-a",       "data"),
    prevent_initial_call=True,
)
def gen_start(_n, text_a):
    input_program = text_a or (_read_slot("a")[0])
    if not input_program:
        return dash.no_update, dash.no_update, dash.no_update
    with _gen_lock:
        if _gen_state["running"]:
            return dash.no_update, dash.no_update, dash.no_update
        _gen_state.update({
            "running": True, "log": [], "done": False,
            "error": None, "input_program": input_program,
        })
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
    Output("gen-dz-a",         "className", allow_duplicate=True),
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
        lbl_a, cls_a = _dz_update("Input Program (A)", ".xtp,.txt", a_txt, a_fn)
        return (
            log_children, False, True, False,
            _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
            a_fn or "—", b_fn or "—", bin_fn or "—",
            lbl_a, cls_a,
            _diff_viewer(a_txt, b_txt),
        )

    return log_children, True, False, True, *([dash.no_update] * 9)


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

# ── Enable Run Analysis button when both SHAs are non-empty ────────────────

@callback(
    Output("btn-analyse", "disabled"),
    Input("anl-sha-a", "value"),
    Input("anl-sha-b", "value"),
)
def anl_enable_button(sha_a, sha_b):
    return not (bool(sha_a and sha_a.strip()) and bool(sha_b and sha_b.strip()))


# ── Upload dropzone — Bin2Bin CSV (Analyse tab) ────────────────────────────

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
    Output("body-bin",         "children", allow_duplicate=True),
    Output("badge-bin",        "children", allow_duplicate=True),
    Output("store-bin",        "data",     allow_duplicate=True),
    Output("anl-dz-label-bin", "children", allow_duplicate=True),
    Output("anl-dz-bin",       "className", allow_duplicate=True),
    Input("btn-refresh-anl",   "n_clicks"),
    prevent_initial_call=True,
)
def anl_refresh(_):
    bin_txt, bin_fn = _read_slot("bin")
    lbl_bin, cls_bin = _dz_update("Bin2Bin", ".csv,.txt", bin_txt, bin_fn)
    return _csv_viewer(bin_txt), bin_fn or "—", bin_txt, lbl_bin, cls_bin


# ── Analyse button → open modal + start thread ─────────────────────────────

@callback(
    Output("anl-modal",    "is_open", allow_duplicate=True),
    Output("anl-interval", "disabled", allow_duplicate=True),
    Output("btn-analyse",  "disabled", allow_duplicate=True),
    Input("btn-analyse",   "n_clicks"),
    State("anl-sha-a",  "value"),
    State("anl-sha-b",  "value"),
    State("store-bin",  "data"),
    prevent_initial_call=True,
)
def anl_start(_n, sha_a, sha_b, text_bin):
    # Validate — both SHAs and Bin2Bin must be available
    if not sha_a or not sha_b:
        return dash.no_update, dash.no_update, dash.no_update
    bin_txt = text_bin or (_read_slot("bin")[0])
    if not bin_txt:
        return dash.no_update, dash.no_update, dash.no_update

    # Always write the current store content to disk before launching the
    # pipeline so the file at _BIN2BIN matches what the user uploaded, even
    # if the Generate tab has since overwritten the same path.
    _BIN2BIN.write_text(bin_txt, encoding="utf-8")

    with _anl_lock:
        if _anl_state["running"]:
            return dash.no_update, dash.no_update, dash.no_update
        _anl_state.update({
            "running": True, "log": [], "done": False,
            "error": None, "mismatch_json": None, "justification_text": None,
            "pr_links_json": None, "pr_summary_md": None,
            "response_xtp_diff": None,
            "sha_a": sha_a.strip(), "sha_b": sha_b.strip(),
            "program_a": None, "program_b": None, "diff": None,
        })
    threading.Thread(
        target=_run_anl_pipeline,
        args=(sha_a.strip(), sha_b.strip(), str(_BIN2BIN)),
        daemon=True,
    ).start()
    return True, False, True


@callback(
    Output("anl-modal-body",  "children"),
    Output("anl-modal-close", "disabled"),
    Output("anl-interval",    "disabled", allow_duplicate=True),
    Output("btn-analyse",     "disabled", allow_duplicate=True),
    Output("anl-results",     "children"),
    # ── viewer panels: populated once the pipeline finishes ────────────────
    Output("body-a",    "children", allow_duplicate=True),
    Output("body-b",    "children", allow_duplicate=True),
    Output("body-diff", "children", allow_duplicate=True),
    Output("badge-a",   "children", allow_duplicate=True),
    Output("badge-b",   "children", allow_duplicate=True),
    Output("store-a",   "data",     allow_duplicate=True),
    Output("store-b",   "data",     allow_duplicate=True),
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

    _no = dash.no_update
    if done:
        prog_a = state.get("program_a") or ""
        prog_b = state.get("program_b") or ""
        sha_a  = state.get("sha_a", "A")
        sha_b  = state.get("sha_b", "B")
        label_a = f"Program_A@{sha_a[:8]}" if sha_a else "Program A"
        label_b = f"Program_B@{sha_b[:8]}" if sha_b else "Program B"
        return (
            log_children, False, True, False,
            _build_results(state),
            _xtp_viewer(prog_a), _xtp_viewer(prog_b),
            _full_diff_panel(
                prog_a, prog_b,
                response_xtp_diff=state.get("response_xtp_diff"),
                pr_summary_md=state.get("pr_summary_md"),
            ),
            label_a, label_b,
            prog_a or _no, prog_b or _no,
        )

    return log_children, True, False, True, _no, _no, _no, _no, _no, _no, _no, _no


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

        with _gen_lock:
            input_program = _gen_state.get("input_program") or ""

        log = AgentLogger(name="xtp_gen_dash", level="INFO")
        log.add_ui_sink(_log_gen)

        pipeline = build_graph(logger=log)
        initial: XTPState = {
            "input_program": input_program,
            "output_folder": str(OUTPUT_FOLDER),
            "log": log,
        }

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


def _run_anl_pipeline(sha_a: str, sha_b: str, path_bin: str) -> None:
    try:
        from Helpers.Logger import AgentLogger
        from XTPAnalyser.AnalysisGraph import XTPAnalysisState, build_analysis_graph

        log = AgentLogger(name="xtp_anl_dash", level="INFO")
        log.add_ui_sink(_log_anl)

        pipeline = build_analysis_graph(logger=log)

        initial: XTPAnalysisState = {
            "sha_a":        sha_a,
            "sha_b":        sha_b,
            "bin2bin_file": path_bin,
            "log":          log,
        }

        final = pipeline.invoke(initial)

        with _anl_lock:
            _anl_state["mismatch_json"]      = final.get("mismatch_df_json")
            _anl_state["justification_text"] = final.get("justification_table")
            _anl_state["pr_links_json"]      = final.get("pr_links_json")
            _anl_state["pr_summary_md"]      = final.get("pr_summary_md")
            _anl_state["response_xtp_diff"]  = final.get("response_xtp_diff")
            _anl_state["error"]              = final.get("error")
            _anl_state["program_a"]          = final.get("program_a")
            _anl_state["program_b"]          = final.get("program_b")
            _anl_state["diff"]               = final.get("diff")
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


# Column display config: (id, label, markdown)
_MISMATCH_COLS = [
    ("prog_a_bin",        "Prog A Bin",   False),
    ("prog_b_bin",        "Prog B Bin",   False),
    ("count",             "Count",        False),
    ("pct_of_src",        "% of Src",     False),
    ("direction",         "Direction",    False),
    ("most_likely_cause", "Most Likely Cause", False),
    ("confidence",        "Confidence",   False),
    ("pr_links",          "PR(s)",        True),   # clickable hyperlinks
]


def _build_results(state: dict) -> html.Div:
    """Render the analysis results panel from pipeline final state."""
    if state.get("error") and not state.get("mismatch_json") and not state.get("pr_links_json"):
        return html.Div([
            html.H4("⚠ Analysis Warning"),
            html.Pre(state["error"], className="results-warning"),
        ], className="results-panel")

    children: list = [html.H4("🔬 Mismatch Justification Table")]

    # Prefer the PR-enriched JSON (contains pr_links column); fall back to plain mismatch JSON
    raw_json = state.get("pr_links_json") or state.get("mismatch_json")

    if raw_json:
        rows = json.loads(raw_json)
        if rows:
            available = set(rows[0].keys())
            # Build column list: use configured display order, skip absent columns
            col_defs = [
                {"name": label, "id": col_id, "presentation": "markdown"}
                if use_md else
                {"name": label, "id": col_id}
                for col_id, label, use_md in _MISMATCH_COLS
                if col_id in available
            ]
            # Append any extra columns not in the config (future-proof)
            known_ids = {c[0] for c in _MISMATCH_COLS}
            for extra in rows[0].keys():
                if extra not in known_ids:
                    col_defs.append({"name": extra, "id": extra})

            children.append(
                dash_table.DataTable(
                    columns=col_defs,
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
                        {"if": {"column_id": "pr_links"}, "color": "#60a5fa"},
                    ],
                    markdown_options={"html": False, "link_target": "_blank"},
                    page_size=20,
                )
            )
    elif state.get("justification_text"):
        # Fallback: show raw text if extraction failed
        children.append(html.Pre(state["justification_text"], className="results-warning"))

    return html.Div(children)


def _build_git_results(state: dict) -> html.Div:
    """Render the Git Bin2Bin results panel (diff view + LLM report)."""
    if state.get("error") and not state.get("bin2bin_report"):
        return html.Div([
            html.H4("⚠ Git Pipeline Warning"),
            html.Pre(state["error"], className="results-warning"),
        ])

    children: list = []

    # ── Unified diff of the two commit versions ──────────────────────────────
    prog_a = state.get("program_a") or ""
    prog_b = state.get("program_b") or ""
    sha_a  = state.get("sha_a", "A")
    sha_b  = state.get("sha_b", "B")

    children.append(html.H4(f"⎇ Commit Diff  {sha_a[:8]}  →  {sha_b[:8]}"))

    if prog_a or prog_b:
        children.append(_diff_viewer(prog_a, prog_b))
    elif state.get("diff"):
        # Fallback: render the raw diff string directly as coloured spans
        spans: list = []
        for line in state["diff"].splitlines():
            if line.startswith("+++") or line.startswith("---"):
                cls = "diff-header"
            elif line.startswith("@@"):
                cls = "diff-hunk"
            elif line.startswith("+"):
                cls = "diff-add"
            elif line.startswith("-"):
                cls = "diff-del"
            else:
                cls = "diff-ctx"
            spans.append(html.Span(line + "\n", className=cls))
        children.append(html.Pre(spans, className="xtp-code diff-view git-diff-block"))
    else:
        children.append(html.P("No diff data available.", className="empty-state"))

    # ── LLM Bin2Bin analysis report ──────────────────────────────────────────
    report = state.get("bin2bin_report")
    if report:
        children.append(html.H4("⎇ Bin2Bin Analysis Report", style={"marginTop": "18px"}))
        children.append(html.Pre(report, className="git-report"))

    return html.Div(children)


# ===========================================================================
# Callback — Bin2Bin Export
# ===========================================================================

@callback(
    Output("btn-export-bin2bin", "disabled"),
    Input("store-bin", "data"),
)
def bin2bin_export_enable(data):
    """Enable the Export button whenever the store-bin has content."""
    return not bool(data)


@callback(
    Output("download-bin2bin", "data"),
    Input("btn-export-bin2bin", "n_clicks"),
    State("store-bin", "data"),
    prevent_initial_call=True,
)
def bin2bin_export_download(_, data):
    """Serve the Bin2Bin CSV for download when the Export button is clicked."""
    if not data:
        return dash.no_update
    # Prefer the live file on disk (most authoritative); fall back to store data
    if _BIN2BIN.exists():
        content = _BIN2BIN.read_text(encoding="utf-8")
    else:
        content = data
    return dcc.send_string(content, filename="Bin2Bin_Matrix.csv", type="text/csv")


# ===========================================================================
# Callbacks — Git Bin2Bin tab
# ===========================================================================

# ── Enable Run button when both SHAs are non-empty ─────────────────────────

@callback(
    Output("btn-git", "disabled"),
    Input("git-sha-a", "value"),
    Input("git-sha-b", "value"),
)
def git_enable_button(sha_a, sha_b):
    """Enable the Run button only when both SHA fields have content."""
    return not (sha_a and sha_a.strip() and sha_b and sha_b.strip())


# ── Refresh: reload files from disk after a pipeline run ───────────────────

@callback(
    Output("body-a",    "children", allow_duplicate=True),
    Output("body-b",    "children", allow_duplicate=True),
    Output("body-bin",  "children", allow_duplicate=True),
    Output("badge-a",   "children", allow_duplicate=True),
    Output("badge-b",   "children", allow_duplicate=True),
    Output("badge-bin", "children", allow_duplicate=True),
    Output("store-a",   "data",     allow_duplicate=True),
    Output("store-b",   "data",     allow_duplicate=True),
    Output("store-bin", "data",     allow_duplicate=True),
    Output("body-diff", "children", allow_duplicate=True),
    Input("btn-refresh-git", "n_clicks"),
    prevent_initial_call=True,
)
def git_refresh(_):
    a_txt,   a_fn   = _read_slot("a")
    b_txt,   b_fn   = _read_slot("b")
    bin_txt, bin_fn = _read_slot("bin")
    return (
        _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
        a_fn or "—", b_fn or "—", bin_fn or "—",
        a_txt, b_txt, bin_txt,
        _diff_viewer(a_txt, b_txt),
    )


# ── Run button → open modal + start background thread ──────────────────────

@callback(
    Output("git-modal",    "is_open",  allow_duplicate=True),
    Output("git-interval", "disabled", allow_duplicate=True),
    Output("btn-git",      "disabled", allow_duplicate=True),
    Input("btn-git",       "n_clicks"),
    State("git-sha-a",     "value"),
    State("git-sha-b",     "value"),
    prevent_initial_call=True,
)
def git_start(_n, sha_a, sha_b):
    if not sha_a or not sha_b:
        return dash.no_update, dash.no_update, dash.no_update
    with _git_lock:
        if _git_state["running"]:
            return dash.no_update, dash.no_update, dash.no_update
        _git_state.update({
            "running": True, "log": [], "done": False,
            "error": None, "bin2bin_report": None,
            "sha_a": sha_a.strip(), "sha_b": sha_b.strip(),
        })
    threading.Thread(target=_run_git_pipeline, daemon=True).start()
    return True, False, True


# ── Polling — update modal log + populate viewer when done ─────────────────

@callback(
    Output("git-modal-body",  "children"),
    Output("git-modal-close", "disabled"),
    Output("git-interval",    "disabled", allow_duplicate=True),
    Output("btn-git",         "disabled", allow_duplicate=True),
    Output("body-a",          "children", allow_duplicate=True),
    Output("body-b",          "children", allow_duplicate=True),
    Output("body-bin",        "children", allow_duplicate=True),
    Output("badge-a",         "children", allow_duplicate=True),
    Output("badge-b",         "children", allow_duplicate=True),
    Output("badge-bin",       "children", allow_duplicate=True),
    Output("body-diff",       "children", allow_duplicate=True),
    Output("git-results",     "children"),
    Output("store-a",         "data",     allow_duplicate=True),
    Output("store-b",         "data",     allow_duplicate=True),
    Output("store-bin",       "data",     allow_duplicate=True),
    # Auto-switch the shared Raw/Diff toggle to "Diff" when the git pipeline finishes
    Output("view-raw",        "style",    allow_duplicate=True),
    Output("view-diff",       "style",    allow_duplicate=True),
    Output("btn-view-raw",    "className", allow_duplicate=True),
    Output("btn-view-diff",   "className", allow_duplicate=True),
    Input("git-interval",     "n_intervals"),
    State("git-sha-a",        "value"),
    State("git-sha-b",        "value"),
    prevent_initial_call=True,
)
def git_poll(_, sha_a, sha_b):
    with _git_lock:
        state = dict(_git_state)

    log_children = [
        html.P(line, className=_log_class(line))
        for line in state["log"]
    ]
    done = state["done"] or bool(state["error"])

    if done:
        a_txt,   a_fn   = _read_slot("a")
        b_txt,   b_fn   = _read_slot("b")
        bin_txt, bin_fn = _read_slot("bin")
        # Re-enable the button only if SHAs are still filled
        btn_disabled = not (sha_a and sha_a.strip() and sha_b and sha_b.strip())
        return (
            log_children, False, True, btn_disabled,
            _xtp_viewer(a_txt), _xtp_viewer(b_txt), _csv_viewer(bin_txt),
            a_fn or "—", b_fn or "—", bin_fn or "—",
            _diff_viewer(a_txt, b_txt),
            _build_git_results(state),
            a_txt, b_txt, bin_txt,
            # Switch shared viewer to Diff mode automatically
            {"display": "none"},
            {"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0"},
            "view-toggle",
            "view-toggle active",
        )

    return log_children, True, False, True, *([dash.no_update] * 15)


@callback(
    Output("git-modal", "is_open", allow_duplicate=True),
    Input("git-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def git_close_modal(_):
    return False


# ===========================================================================
# Pipeline runner — Git Bin2Bin (background thread)
# ===========================================================================

def _run_git_pipeline() -> None:
    try:
        from Helpers.Logger import AgentLogger
        from XTPAnalyser.GitCommitGraph import GitCommitState, build_git_commit_graph

        with _git_lock:
            sha_a = _git_state.get("sha_a", "")
            sha_b = _git_state.get("sha_b", "")

        log = AgentLogger(name="xtp_git_dash", level="INFO")
        log.add_ui_sink(_log_git)

        pipeline = build_git_commit_graph(logger=log)
        initial: GitCommitState = {
            "sha_a":         sha_a,
            "sha_b":         sha_b,
            "output_folder": str(OUTPUT_FOLDER),
            "log":           log,
        }

        final = pipeline.invoke(initial)

        with _git_lock:
            _git_state["bin2bin_report"] = final.get("bin2bin_report")
            _git_state["program_a"]      = final.get("program_a")
            _git_state["program_b"]      = final.get("program_b")
            _git_state["diff"]           = final.get("diff")
            _git_state["error"]          = final.get("error")
            _git_state["done"]           = True
            _git_state["running"]        = False

    except Exception as exc:  # noqa: BLE001
        _log_git(f"✗ Git pipeline error: {exc}")
        with _git_lock:
            _git_state["error"]   = str(exc)
            _git_state["done"]    = True
            _git_state["running"] = False


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    app.run(debug=False, port=8050, host="0.0.0.0")
