"""
XTPAnalyser — Analysis LangGraph pipeline.

Exposes ``build_analysis_graph()`` which compiles a five-node StateGraph:
    fetch_programs → generate_diff → analize_bin2bin → justify_mismatches → extract_justification_table

The returned compiled graph accepts an ``XTPAnalysisState`` dict as input.

Usage
-----
    from XTPAnalyser.AnalysisGraph import XTPAnalysisState, build_analysis_graph

    app = build_analysis_graph()
    result = app.invoke({
        "sha_a": "abc123",
        "sha_b": "def456",
        "bin2bin_file": csv_path,
        "log": my_logger,
    })
"""

from __future__ import annotations

import difflib
import os
from typing import TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from Helpers.LangfuseCallbackHandler import get_callback
from Helpers.Logger import AgentLogger

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class XTPAnalysisState(TypedDict, total=False):
    sha_a: str
    sha_b: str
    bin2bin_file: str
    log: AgentLogger
    program_a: str
    program_b: str
    diff: str
    response_xtp_diff: str
    response_bin2bin: str
    justification_table: str
    mismatch_df_json: str   # DataFrame serialised as JSON for the UI
    pr_links_json: str      # enriched DataFrame (+ pr_numbers/pr_titles) as JSON
    pr_summary_md: str      # Markdown table linking each mismatch to PR(s)
    error: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _fetch_programs_node(state: XTPAnalysisState) -> XTPAnalysisState:
    """Fetch both XTP program versions from GitHub by commit SHA and compute the unified diff."""
    from XTPAnalyser.Agents.XTPGitCommitAgent import _fetch_file_at_sha  # lazy import

    log: AgentLogger = state["log"]
    sha_a = state.get("sha_a", "").strip()
    sha_b = state.get("sha_b", "").strip()

    if not sha_a or not sha_b:
        return {**state, "error": "Both sha_a and sha_b must be provided."}

    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

    log._logger.info("▶ Fetching Program A at commit %s …", sha_a[:8])
    try:
        content_a = _fetch_file_at_sha(sha_a, token)
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": str(exc)}

    log._logger.info("▶ Fetching Program B at commit %s …", sha_b[:8])
    try:
        content_b = _fetch_file_at_sha(sha_b, token)
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": str(exc)}

    lines_a = content_a.splitlines(keepends=True)
    lines_b = content_b.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"Program_A@{sha_a[:8]}",
        tofile=f"Program_B@{sha_b[:8]}",
        lineterm="",
    ))
    diff_text = "\n".join(diff_lines) if diff_lines else "(no differences)"

    log._logger.info("✓ Programs fetched; diff has %d lines.", len(diff_lines))
    return {**state, "program_a": content_a, "program_b": content_b, "diff": diff_text}


def _generate_xtp_diff_node(state: XTPAnalysisState) -> XTPAnalysisState:
    from XTPAnalyser.Agents.XTPProgramDiffAgent import XTPProgramDiffAgent  # lazy import

    if state.get("error"):
        return state

    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP Program Diff Agent …")
    agent = XTPProgramDiffAgent(log)
    response = agent.analyse(
        diff=state.get("diff", ""),
        program_a=state.get("program_a", ""),
        program_b=state.get("program_b", ""),
    )
    log._logger.info("✓ XTP Program Diff Agent finished.")
    return {**state, "response_xtp_diff": response}


def _analyze_bin2bin_node(state: XTPAnalysisState) -> XTPAnalysisState:
    from XTPAnalyser.Agents.XTPBin2BinMatrixAgent import XTPBin2BinMatrixAgent  # lazy import

    if state.get("error"):
        return state

    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP Bin2Bin Analyzer Agent …")
    agent = XTPBin2BinMatrixAgent(log)
    bin2bin_answer = agent.analyse(state["bin2bin_file"])
    log._logger.info("✓ XTP Bin2Bin Analyzer Agent finished.")
    return {**state, "response_bin2bin": bin2bin_answer}


def _justify_mismatches_node(state: XTPAnalysisState) -> XTPAnalysisState:
    from XTPAnalyser.Agents.XTPMismatchJustificationAgent import XTPMismatchJustificationAgent  # lazy import

    if state.get("error"):
        return state

    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP Mismatch Justification Agent …")
    agent = XTPMismatchJustificationAgent(log)
    justification = agent.justify(
        matrix_report=state["response_bin2bin"],
        diff_report=state["response_xtp_diff"],
    )
    log._logger.info("✓ XTP Mismatch Justification Agent finished.")
    return {**state, "justification_table": justification}


def _extract_justification_table_node(state: XTPAnalysisState) -> XTPAnalysisState:
    from XTPAnalyser.Agents.XTPTableExtractor import XTPTableExtractor  # lazy import

    if state.get("error"):
        return state

    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP Table Extractor …")
    extractor = XTPTableExtractor()
    try:
        df = extractor.extract(state["justification_table"])
        log._logger.info("✓ XTP Table Extractor finished.")
        log._logger.info("=== Mismatch Justification DataFrame ===\n%s", df.to_string(index=False))
        return {**state, "mismatch_df_json": df.to_json(orient="records")}
    except ValueError as exc:
        log._logger.warning("Table extraction skipped: %s", exc)
        return {**state, "error": str(exc)}


def _link_prs_to_justifications_node(state: XTPAnalysisState) -> XTPAnalysisState:
    """Enrich the mismatch DataFrame with matching GitHub PR numbers/titles."""
    from XTPAnalyser.Agents.XTPPRLinkerAgent import XTPPRLinkerAgent  # lazy import
    import io
    import pandas as pd

    if state.get("error"):
        return state

    mismatch_df_json = state.get("mismatch_df_json", "")
    if not mismatch_df_json:
        return {**state, "error": "No mismatch DataFrame available for PR linking."}

    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP PR Linker Agent …")

    df = pd.read_json(io.StringIO(mismatch_df_json))
    agent = XTPPRLinkerAgent(logger=log)
    result = agent.link(df, sha_a=state.get("sha_a", ""), sha_b=state.get("sha_b", ""))

    if result["error"]:
        log._logger.warning("PR linking failed: %s", result["error"])
        return {**state, "error": result["error"]}

    log._logger.info("✓ XTP PR Linker Agent finished.")
    log._logger.info("=== PR-Linked Summary ===\n%s", result["summary_md"])
    return {
        **state,
        "pr_links_json": result["enriched_df"].to_json(orient="records"),
        "pr_summary_md": result["summary_md"],
    }


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_analysis_graph(logger: AgentLogger | None = None):
    """Build and compile the XTP analysis pipeline graph.

    Parameters
    ----------
    logger:
        Shared ``AgentLogger`` instance.  If *None* a default INFO-level
        logger named ``"xtp_analysis"`` is created automatically.

    Returns a compiled LangGraph app that accepts an ``XTPAnalysisState``
    dict as input.  Pass the same logger in the initial state::

        app = build_analysis_graph(logger=my_log)
        app.invoke({"sha_a": "abc123", "sha_b": "def456", "bin2bin_file": ..., "log": my_log})
    """
    if logger is None:
        logger = AgentLogger(name="xtp_analysis", level="INFO")

    g = StateGraph(XTPAnalysisState)
    g.add_node("fetch_programs",                _fetch_programs_node)
    g.add_node("generate_diff",                 _generate_xtp_diff_node)
    g.add_node("analize_bin2bin",               _analyze_bin2bin_node)
    g.add_node("justify_mismatches",            _justify_mismatches_node)
    g.add_node("extract_justification_table",   _extract_justification_table_node)
    g.add_node("link_prs_to_justifications",    _link_prs_to_justifications_node)

    g.add_edge(START,                           "fetch_programs")
    g.add_edge("fetch_programs",                "generate_diff")
    g.add_edge("generate_diff",                 "analize_bin2bin")
    g.add_edge("analize_bin2bin",               "justify_mismatches")
    g.add_edge("justify_mismatches",            "extract_justification_table")
    g.add_edge("extract_justification_table",   "link_prs_to_justifications")
    g.add_edge("link_prs_to_justifications",    END)

    compiled = g.compile()

    # Wrap invoke to automatically attach a Langfuse callback.
    _original_invoke = compiled.invoke

    def _invoke_with_langfuse(input, config=None, **kwargs):  # noqa: A002
        _cb = get_callback(
            session_id=f"{input.get('sha_a','')[:8]}..{input.get('sha_b','')[:8]}",
            trace_name="XTPAnalyser",
        )
        if _cb:
            config = config or {}
            config.setdefault("callbacks", []).append(_cb)
        return _original_invoke(input, config=config, **kwargs)

    compiled.invoke = _invoke_with_langfuse  # type: ignore[method-assign]
    return compiled
