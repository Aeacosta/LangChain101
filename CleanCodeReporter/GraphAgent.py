"""LangGraph-based Code Smell Analyzer.

Flow (mirrors the Mermaid diagram):

    Inicio
      └─► Leer Archivos
            └─► JSON Valido?
                  ├─ No ──► Leer Archivos   (retry loop)
                  └─ Sí ──► Extraer Reporte
                              ├──► Calificar Reporte  ─┐
                              └──► Escribir Archivo   ─┴─► Merge ──► Crear Issue? ──► Fin

Nodes
-----
read_file_node      — reads the C# file and calls the LLM analyzer.
validate_json_node  — passes the raw response through the JSON formatter and
                      checks whether the result is valid JSON.
extract_report_node — assembles the final report dict (injects prompt_response).
score_report_node   — runs the scorer; writes score_json only.
patch_file_node     — computes a per-finding PatchResult for every finding
                      that carries a diff, each applied independently against
                      the original file content.  Writes disjoint keys only.
merge_node          — recombines score_json + patch data into report after
                      the parallel branches.
create_issue_node   — opens one GitHub Issue listing all findings when the
                      file belongs to a tracked repo.  No branch is created;
                      a human must review and apply the proposed diffs.

LangGraph rule: nodes that run in parallel (fan-out from the same parent) must
write to **disjoint** state keys.  score_report_node owns `score_json`;
patch_file_node owns `patched`, `patch_content`, `patch_diff`,
`patch_original`, and `finding_patches`.
merge_node runs after both branches finish.
"""

from __future__ import annotations

import json
import os

from langgraph.graph import END, START, StateGraph

from .agent_setup import agent as _agent
from .GithubPRAgent import create_issue_per_finding_sync, resolve_repo
from Helpers.FilePatcher import apply_fixes
from Helpers.JsonFormatterAgent import JsonFormatterAgent
from Helpers.LangfuseCallbackHandler import get_callback, trace_name_context
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

    Normalises and packages the raw LLM diff for each finding that carries
    one.  Each diff is taken verbatim from the finding — no hunk matching,
    no file mutation.  Diffs are displayed per-finding on the GitHub issue
    and in the Dash UI, so no merging or disk write is needed here.

    Writes ONLY `patched`, `patch_content`, `patch_diff`, `patch_original`,
    and `finding_patches` — all disjoint from score_report_node.
    """
    _log._logger.info("🔧 patch_file_node")
    report = state.get("report", {})

    try:
        file_path: str = report.get("fileName", "")
        original = ""
        if file_path and os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as fh:
                original = fh.read()
        else:
            _log._logger.warning("patch_file_node — source file not found: %s", file_path)

        # ── Collect raw LLM diffs — no hunk matching, no file mutation ───────
        finding_patches: list[dict] = []
        for finding in sorted(report.get("findings", []), key=lambda f: f.get("id", 0)):
            raw_diff = (finding.get("diff") or "").strip()
            if not raw_diff:
                continue
            # Normalise literal \n escape sequences (common LLM artefact).
            if "\n" not in raw_diff and "\\n" in raw_diff:
                raw_diff = raw_diff.replace("\\n", "\n")
            finding_patches.append({
                "finding_id":   finding.get("id"),
                "smell":        finding.get("smell", ""),
                "unified_diff": raw_diff,
                "errors":       [],
            })
            _log._logger.debug(
                "patch_file_node — finding #%s diff lines: %d",
                finding.get("id"), len(raw_diff.splitlines()),
            )

        _log._logger.info(
            "patch_file_node — %d per-finding diff(s) collected ✓",
            len(finding_patches),
        )

        return {
            "patched":         bool(finding_patches),
            "patch_content":   original,
            "patch_diff":      "",
            "patch_original":  original,
            "finding_patches": finding_patches,
        }

    except Exception as exc:
        _log._logger.error("patch_file_node — error: %s", exc)
        return {
            "patched":         False,
            "patch_content":   "",
            "patch_diff":      "",
            "patch_original":  "",
            "finding_patches": [],
            "error":           str(exc),
        }


def merge_node(state: GraphState) -> dict:
    """Merge node — runs after both parallel branches complete.

    Folds score data, combined patch data, and per-finding patch data into
    the report dict so all downstream consumers (Dash UI, PR node) have a
    single self-contained object.
    """
    _log._logger.info("🔗 merge_node")
    report = dict(state.get("report", {}))

    score_json = state.get("score_json", "")
    if score_json:
        try:
            report["scoreReport"] = json.loads(score_json)
        except Exception as exc:
            _log._logger.error("merge_node — could not fold score: %s", exc)

    # Embed patch data into the report for the Dash UI.
    # Prefer values already embedded by patch_file_node (survive LangGraph fan-in
    # state merging); fall back to top-level state keys as a secondary source.
    report["_patchContent"]  = state.get("patch_content", "")  or report.get("_patchContent", "")
    report["_patchDiff"]     = state.get("patch_diff", "")     or report.get("_patchDiff", "")
    report["_patchOriginal"] = state.get("patch_original", "") or report.get("_patchOriginal", "")
    report["_findingPatches"] = (
        state.get("finding_patches") or report.get("_findingPatches") or []
    )

    return {"report": report}


def create_issue_node(state: GraphState) -> dict:
    """Node: Crear Issue.

    Opens one GitHub Issue listing all findings when the file belongs to a
    tracked repo.  No branch is created and no code is pushed — the proposed
    diffs are embedded in the issue body for human review.

    Writes ONLY `pr_urls` (reusing the existing state key so the Dash UI
    and any downstream consumers remain unchanged).
    """
    file_path = state.get("file_path", "")
    report    = state.get("report", {})

    _log._logger.info("🐙 create_issue_node — file: %s", file_path)

    issue_urls = create_issue_per_finding_sync(report, file_path)

    _log._logger.info("create_issue_node — %d issue(s) created", len(issue_urls))
    for entry in issue_urls:
        _log._logger.info(
            "  issue #%s → %s", entry.get("issue_number"), entry.get("url")
        )

    return {"pr_urls": issue_urls}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_json_valid(state: GraphState) -> str:
    """Conditional edge after validate_json_node."""
    return "valid" if state.get("valid_json") else "retry"


def route_create_issue(state: GraphState) -> str:
    """Conditional edge after merge_node."""
    file_path = state.get("file_path", "")
    return "create_issue" if resolve_repo(file_path) is not None else "skip_issue"


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
    graph.add_node("create_issue",   create_issue_node)

    # Edges
    graph.add_edge(START,            "read_file")
    graph.add_edge("read_file",      "validate_json")

    graph.add_conditional_edges(
        "validate_json",
        route_json_valid,
        {"valid": "extract_report", "retry": "read_file"},
    )

    # Fan-out: both branches run in parallel writing to disjoint keys
    graph.add_edge("extract_report", "score_report")
    graph.add_edge("extract_report", "patch_file")

    # Fan-in: both branches converge at merge
    graph.add_edge("score_report",   "merge")
    graph.add_edge("patch_file",     "merge")

    graph.add_conditional_edges(
        "merge",
        route_create_issue,
        {"create_issue": "create_issue", "skip_issue": END},
    )
    graph.add_edge("create_issue", END)

    return graph


# Compiled graph — import this in Main.py or any other entry point.
compiled_graph = build_graph().compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run(file_path: str) -> dict:
    """Run the full graph for *file_path* and return the final GraphState."""
    initial_state: GraphState = {
        "file_path":       file_path,
        "raw_response":    "",
        "report_json":     "",
        "report":          {},
        "score_json":      "",
        "patched":         False,
        "patch_content":   "",
        "patch_diff":      "",
        "patch_original":  "",
        "finding_patches": [],
        "valid_json":      False,
        "error":           "",
        "pr_urls":         [],
    }
    _cb = get_callback(session_id=file_path)
    _config = {"callbacks": [_cb]} if _cb else {}
    with trace_name_context("CleanCodeReviewer"):
        return compiled_graph.invoke(initial_state, config=_config)
