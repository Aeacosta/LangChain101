"""
XTPAnalyser — Git-Commit Bin2Bin LangGraph pipeline.

Graph shape
-----------

    [START]
       │
       ▼
  fetch_commits      ← XTPGitCommitAgent: fetch both commit SHAs from GitHub,
       │               diff them, compute Bin2Bin CSV, write to disk.
       ▼
  save_files         ← Write Program A and Program B to their canonical paths
       │               (Programas/Program_A.xtp / Program_B.xtp) so the shared
       │               viewer and Analyse tab can pick them up immediately.
       ▼
  analyse_bin2bin    ← XTPBin2BinMatrixAgent: load the CSV and produce a
       │               structured Markdown report.
       ▼
    [END]

Usage
-----
    from XTPAnalyser.GitCommitGraph import GitCommitState, build_git_commit_graph

    app = build_git_commit_graph()
    result = app.invoke({
        "sha_a": "abc123",
        "sha_b": "def456",
        "output_folder": "Programas",
        "log": my_logger,
    })
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from Helpers.Logger import AgentLogger


# ---------------------------------------------------------------------------
# Shared pipeline state
# ---------------------------------------------------------------------------

class GitCommitState(TypedDict, total=False):
    """State flowing through the git-commit Bin2Bin pipeline.

    Fields
    ------
    sha_a          : Commit SHA for Program A (baseline).
    sha_b          : Commit SHA for Program B (modified).
    output_folder  : Directory where files will be written (default: 'Programas').
    program_a      : XTP source fetched from GitHub at sha_a.
    program_b      : XTP source fetched from GitHub at sha_b.
    diff           : Unified diff between program_a and program_b.
    csv_path       : Absolute path of the written Bin2Bin CSV.
    csv_content    : Raw CSV text of the Bin2Bin matrix.
    bin2bin_report : Markdown analysis produced by XTPBin2BinMatrixAgent.
    error          : Human-readable error message if any node fails.
    log            : AgentLogger shared across all nodes.
    """

    sha_a: str
    sha_b: str
    output_folder: str
    program_a: str
    program_b: str
    diff: str
    csv_path: str
    csv_content: str
    bin2bin_report: str
    error: str
    log: AgentLogger


# ---------------------------------------------------------------------------
# Node: fetch_commits
# ---------------------------------------------------------------------------

def _fetch_commits_node(state: GitCommitState) -> GitCommitState:
    """Call XTPGitCommitAgent (sync wrapper) to fetch both SHAs and compute Bin2Bin."""
    from XTPAnalyser.Agents.XTPGitCommitAgent import XTPGitCommitAgent  # lazy

    log: AgentLogger = state["log"]
    sha_a         = state.get("sha_a", "").strip()
    sha_b         = state.get("sha_b", "").strip()
    output_folder = state.get("output_folder", "Programas")

    if not sha_a or not sha_b:
        return {**state, "error": "Both SHA_A and SHA_B must be provided."}

    log._logger.info("▶ Fetching commits %s..%s from GitHub …", sha_a[:8], sha_b[:8])

    try:
        agent  = XTPGitCommitAgent(logger=log)
        result = agent.invoke_sync(sha_a=sha_a, sha_b=sha_b, output_folder=output_folder)

        if result.get("error"):
            return {**state, "error": result["error"]}

        log._logger.info("✓ Commits fetched and Bin2Bin matrix written.")
        return {
            **state,
            "program_a":   result.get("program_a", ""),
            "program_b":   result.get("program_b", ""),
            "diff":        result.get("diff", ""),
            "csv_path":    result.get("csv_path", ""),
            "csv_content": result.get("csv_content", ""),
        }
    except Exception as exc:  # noqa: BLE001
        log._logger.error("✗ fetch_commits error: %s", exc)
        return {**state, "error": str(exc)}


# ---------------------------------------------------------------------------
# Node: save_files
# ---------------------------------------------------------------------------

def _save_files_node(state: GitCommitState) -> GitCommitState:
    """Persist Program A and Program B to their canonical disk paths."""
    if state.get("error"):
        return state

    log: AgentLogger = state["log"]
    output_folder = state.get("output_folder", "Programas")
    folder = Path(output_folder)
    folder.mkdir(exist_ok=True)

    try:
        prog_a = state.get("program_a", "")
        prog_b = state.get("program_b", "")

        if prog_a:
            (folder / "Program_A.xtp").write_text(prog_a, encoding="utf-8")
            log._logger.info("✓ Program_A.xtp written (%d chars)", len(prog_a))
        if prog_b:
            (folder / "Program_B.xtp").write_text(prog_b, encoding="utf-8")
            log._logger.info("✓ Program_B.xtp written (%d chars)", len(prog_b))

        return state
    except Exception as exc:  # noqa: BLE001
        log._logger.error("✗ save_files error: %s", exc)
        return {**state, "error": str(exc)}


# ---------------------------------------------------------------------------
# Node: analyse_bin2bin
# ---------------------------------------------------------------------------

def _analyse_bin2bin_node(state: GitCommitState) -> GitCommitState:
    """Run XTPBin2BinMatrixAgent over the freshly written CSV."""
    from XTPAnalyser.Agents.XTPBin2BinMatrixAgent import XTPBin2BinMatrixAgent  # lazy

    if state.get("error"):
        return state

    log: AgentLogger = state["log"]
    csv_path = state.get("csv_path", "")

    if not csv_path:
        # Fallback: use canonical path
        csv_path = str(Path(state.get("output_folder", "Programas")) / "Bin2Bin_Matrix.csv")

    log._logger.info("▶ Analysing Bin2Bin matrix at %s …", csv_path)

    try:
        agent  = XTPBin2BinMatrixAgent(logger=log)
        report = agent.analyse(csv_path)
        log._logger.info("✓ Bin2Bin analysis complete.")
        return {**state, "bin2bin_report": report}
    except Exception as exc:  # noqa: BLE001
        log._logger.error("✗ analyse_bin2bin error: %s", exc)
        return {**state, "error": str(exc)}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_git_commit_graph(logger: AgentLogger | None = None):
    """Build and compile the git-commit Bin2Bin pipeline.

    Parameters
    ----------
    logger:
        Shared ``AgentLogger``.  If *None* a default INFO-level logger named
        ``"xtp_git_graph"`` is created automatically.

    Returns a compiled LangGraph app accepting a ``GitCommitState`` dict::

        app = build_git_commit_graph(logger=my_log)
        result = app.invoke({
            "sha_a": "abc123",
            "sha_b": "def456",
            "output_folder": "Programas",
            "log": my_log,
        })
    """
    if logger is None:
        logger = AgentLogger(name="xtp_git_graph", level="INFO")

    g = StateGraph(GitCommitState)
    g.add_node("fetch_commits",   _fetch_commits_node)
    g.add_node("save_files",      _save_files_node)
    g.add_node("analyse_bin2bin", _analyse_bin2bin_node)

    g.add_edge(START,             "fetch_commits")
    g.add_edge("fetch_commits",   "save_files")
    g.add_edge("save_files",      "analyse_bin2bin")
    g.add_edge("analyse_bin2bin", END)

    return g.compile()
