"""
XTPAnalyser — Analysis LangGraph pipeline.

Exposes ``build_analysis_graph()`` which compiles a four-node StateGraph:
    generate_diff → analize_bin2bin → justify_mismatches → extract_justification_table

The returned compiled graph accepts an ``XTPAnalysisState`` dict as input.

Usage
-----
    from XTPAnalyser.AnalysisGraph import XTPAnalysisState, build_analysis_graph

    app = build_analysis_graph()
    result = app.invoke({
        "file_comparer": XTPFileComparer(path_a, path_b),
        "bin2bin_file": csv_path,
        "log": my_logger,
    })
"""

from __future__ import annotations

import os
from typing import TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from Helpers.Logger import AgentLogger
from XTPAnalyser.Agents.CompareFiles import XTPFileComparer
from XTPAnalyser.Agents.XTPBin2BinMatrixAgent import XTPBin2BinMatrixAgent
from XTPAnalyser.Agents.XTPMismatchJustificationAgent import XTPMismatchJustificationAgent
from XTPAnalyser.Agents.XTPProgramDiffAgent import XTPProgramDiffAgent
from XTPAnalyser.Agents.XTPTableExtractor import XTPTableExtractor

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class XTPAnalysisState(TypedDict, total=False):
    file_comparer: XTPFileComparer
    bin2bin_file: str
    log: AgentLogger
    response_xtp_diff: str
    response_bin2bin: str
    justification_table: str
    mismatch_df_json: str   # DataFrame serialised as JSON for the UI
    error: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _generate_xtp_diff_node(state: XTPAnalysisState) -> XTPAnalysisState:
    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP Program Diff Agent …")
    agent = XTPProgramDiffAgent(log)
    response = agent.analyse(state["file_comparer"])
    log._logger.info("✓ XTP Program Diff Agent finished.")
    return {**state, "response_xtp_diff": response}


def _analyze_bin2bin_node(state: XTPAnalysisState) -> XTPAnalysisState:
    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTP Bin2Bin Analyzer Agent …")
    agent = XTPBin2BinMatrixAgent(log)
    bin2bin_answer = agent.analyse(state["bin2bin_file"])
    log._logger.info("✓ XTP Bin2Bin Analyzer Agent finished.")
    return {**state, "response_bin2bin": bin2bin_answer}


def _justify_mismatches_node(state: XTPAnalysisState) -> XTPAnalysisState:
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
        app.invoke({"file_comparer": ..., "bin2bin_file": ..., "log": my_log})
    """
    if logger is None:
        logger = AgentLogger(name="xtp_analysis", level="INFO")

    g = StateGraph(XTPAnalysisState)
    g.add_node("generate_diff",             _generate_xtp_diff_node)
    g.add_node("analize_bin2bin",           _analyze_bin2bin_node)
    g.add_node("justify_mismatches",        _justify_mismatches_node)
    g.add_node("extract_justification_table", _extract_justification_table_node)

    g.add_edge(START,                       "generate_diff")
    g.add_edge("generate_diff",             "analize_bin2bin")
    g.add_edge("analize_bin2bin",           "justify_mismatches")
    g.add_edge("justify_mismatches",        "extract_justification_table")
    g.add_edge("extract_justification_table", END)

    return g.compile()
