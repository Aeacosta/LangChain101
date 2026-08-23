"""LangGraph-based Code Smell Analyzer.

Flow (mirrors the Mermaid diagram):

    Inicio
      └─► Leer Archivos
            └─► JSON Valido?
                  ├─ No ──► Leer Archivos   (retry loop)
                  └─ Sí ──► Extraer Reporte
                              ├──► Calificar Reporte  ─┐
                              └──► Escribir Archivo   ─┴─► Merge ──► Fin

Nodes
-----
read_file_node      — reads the C# file and calls the LLM analyzer.
validate_json_node  — passes the raw response through the JSON formatter and
                      checks whether the result is valid JSON.
extract_report_node — assembles the final report dict (injects prompt_response).
score_report_node   — runs the scorer; writes score_json only.
patch_file_node     — applies unified diffs and writes the corrected file; writes patched only.
merge_node          — recombines score_json into report.scoreReport after the parallel branches.

LangGraph rule: nodes that run in parallel (fan-out from the same parent) must
write to **disjoint** state keys.  score_report_node owns `score_json`; patch_file_node
owns `patched`.  merge_node runs after both branches finish and folds the score
data back into `report`.
"""

from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph

from .agent_setup import agent as _agent
from Helpers.FilePatcher import apply_fixes
from Helpers.JsonFormatterAgent import JsonFormatterAgent
from Helpers.Logger import AgentLogger
from Helpers.ScorerAgent import ScorerAgent
from Structures.CodeSmellReport import GraphState

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_log = AgentLogger(name="graph_agent", level="DEBUG")

# Shared helpers — instantiated once, reused across node calls.
_formatter = JsonFormatterAgent(_log)
_scorer    = ScorerAgent(_log)

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def read_file_node(state: GraphState) -> dict:
    """Node: Leer Archivos.

    Delegates to the existing Agent (which owns the full ReAct loop with
    tool execution) so that read_local_file and find_documents are actually
    called and their results fed back to the LLM before producing output.
    """
    file_path = state["file_path"]
    _log._logger.info("📂 read_file_node — analyzing: %s", file_path)

    is_url = file_path.startswith("http://") or file_path.startswith("https://")
    if is_url:
        prompt = (
            f"Que Code Smells detectas en el archivo disponible en esta URL de GitHub? "
            f"Usa la herramienta read_github_url para obtener el contenido. URL: {file_path}"
        )
    else:
        prompt = f"Que Code Smells detectas en este archivo? {file_path}"

    raw = _agent.call_agent(prompt)

    _log._logger.debug("read_file_node — raw response length: %d", len(raw))

    # Return only the keys this node owns; reset downstream fields for clean retries.
    return {
        "raw_response": raw,
        "report_json":  "",
        "report":       {},
        "valid_json":   False,
        "error":        "",
    }


def validate_json_node(state: GraphState) -> dict:
    """Node: JSON Valido?

    Passes the raw response through the JsonFormatterAgent and tries to
    parse the result.  Sets valid_json accordingly.
    """
    _log._logger.info("🔍 validate_json_node")
    raw = state.get("raw_response", "")

    try:
        report_json = _formatter.format(raw)
        json.loads(report_json)          # raises if invalid
        _log._logger.info("validate_json_node — JSON is valid ✓")
        return {"report_json": report_json, "valid_json": True, "error": ""}
    except Exception as exc:
        _log._logger.warning("validate_json_node — invalid JSON: %s", exc)
        return {"report_json": "", "valid_json": False, "error": str(exc)}


def extract_report_node(state: GraphState) -> dict:
    """Node: Extraer Reporte.

    Parses report_json into a dict and injects the original prompt_response
    so the downstream scorer has full context.
    """
    _log._logger.info("📋 extract_report_node")
    report: dict = json.loads(state["report_json"])
    report["prompt_response"] = state.get("raw_response", "")
    return {"report": report}


def score_report_node(state: GraphState) -> dict:
    """Node: Calificar Reporte.

    Calls the ScorerAgent and stores the raw score JSON.
    Writes ONLY `score_json` so it stays disjoint from patch_file_node
    (both run in parallel — they must not touch the same key).
    """
    _log._logger.info("🏆 score_report_node")
    report = dict(state["report"])

    try:
        score_json = _scorer.score(report)
        # Validate that it parses; log grade/score for visibility.
        score_data = json.loads(score_json)
        _log._logger.info(
            "score_report_node — grade: %s  score: %s",
            score_data.get("grade"),
            score_data.get("score"),
        )
        return {"score_json": score_json}
    except Exception as exc:
        _log._logger.error("score_report_node — error: %s", exc)
        return {"score_json": "", "error": str(exc)}


def patch_file_node(state: GraphState) -> dict:
    """Node: Escribir Archivo corregido.

    Applies all unified diffs from the report findings to the source file.
    Writes ONLY `patched` so it stays disjoint from score_report_node.
    """
    _log._logger.info("🔧 patch_file_node")
    report = state.get("report", {})

    try:
        apply_fixes(report, logger=_log)
        _log._logger.info("patch_file_node — file patched ✓")
        return {"patched": True}
    except Exception as exc:
        _log._logger.error("patch_file_node — error: %s", exc)
        return {"patched": False, "error": str(exc)}


def merge_node(state: GraphState) -> dict:
    """Merge node — runs after both parallel branches complete.

    Folds the score data (stored in score_json by score_report_node) back into
    the report dict so callers get a single self-contained report.
    """
    _log._logger.info("🔗 merge_node")
    score_json = state.get("score_json", "")
    if not score_json:
        return {}

    try:
        report = dict(state.get("report", {}))
        report["scoreReport"] = json.loads(score_json)
        return {"report": report}
    except Exception as exc:
        _log._logger.error("merge_node — could not fold score: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_json_valid(state: GraphState) -> str:
    """Conditional edge after validate_json_node.

    Returns 'valid' when the JSON parsed successfully, 'retry' otherwise.
    """
    return "valid" if state.get("valid_json") else "retry"


# ---------------------------------------------------------------------------
# Graph definition
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    # Register nodes
    graph.add_node("read_file",      read_file_node)
    graph.add_node("validate_json",  validate_json_node)
    graph.add_node("extract_report", extract_report_node)
    graph.add_node("score_report",   score_report_node)
    graph.add_node("patch_file",     patch_file_node)
    graph.add_node("merge",          merge_node)

    # Edges — matches the Mermaid flowchart exactly
    graph.add_edge(START,            "read_file")
    graph.add_edge("read_file",      "validate_json")

    # Conditional: JSON Valido? → retry or proceed
    graph.add_conditional_edges(
        "validate_json",
        route_json_valid,
        {"valid": "extract_report", "retry": "read_file"},
    )

    # Fan-out: both branches run in parallel writing to disjoint keys
    graph.add_edge("extract_report", "score_report")
    graph.add_edge("extract_report", "patch_file")

    # Fan-in: both branches converge at merge, then finish
    graph.add_edge("score_report",   "merge")
    graph.add_edge("patch_file",     "merge")
    graph.add_edge("merge",          END)

    return graph


# Compiled graph — import this in Main.py or any other entry point.
compiled_graph = build_graph().compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run(file_path: str) -> dict:
    """Run the full graph for *file_path* and return the final GraphState."""
    initial_state: GraphState = {
        "file_path":    file_path,
        "raw_response": "",
        "report_json":  "",
        "report":       {},
        "score_json":   "",
        "patched":      False,
        "valid_json":   False,
        "error":        "",
    }
    return compiled_graph.invoke(initial_state)
