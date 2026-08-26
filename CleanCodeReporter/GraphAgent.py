"""LangGraph-based Code Smell Analyzer.

Flow (mirrors the Mermaid diagram):

    Inicio
      └─► Leer Archivos
            └─► JSON Valido?
                  ├─ No ──► Leer Archivos   (retry loop)
                  └─ Sí ──► Extraer Reporte
                              ├──► Calificar Reporte  ─┐
                              └──► Escribir Archivo   ─┴─► Merge ──► Crear PRs? ──► Fin

Nodes
-----
read_file_node      — reads the C# file and calls the LLM analyzer.
validate_json_node  — passes the raw response through the JSON formatter and
                      checks whether the result is valid JSON.
extract_report_node — assembles the final report dict (injects prompt_response).
score_report_node   — runs the scorer; writes score_json only.
patch_file_node     — applies unified diffs and writes the corrected file.
                      Computes both the combined patch (all findings) and a
                      per-finding patch list; writes disjoint keys only.
merge_node          — recombines score_json + patch data into report after
                      the parallel branches.
create_pr_node      — creates one GitHub branch + PR per finding when the
                      file belongs to a tracked repo.

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
from .GithubPRAgent import create_pr_per_finding_sync, resolve_repo
from Helpers.FilePatcher import (
    apply_fixes,
    git_apply_patch,
    preview_patch,
    preview_patch_single_finding,
)
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

    1. Reads the original file once.
    2. Computes a per-finding PatchResult for every finding that has a diff.
    3. Computes the combined PatchResult (all findings applied sequentially).
    4. Writes the combined-patched content to disk.

    Writes ONLY `patched`, `patch_content`, `patch_diff`, `patch_original`,
    and `finding_patches` — all disjoint from score_report_node.
    """
    _log._logger.info("🔧 patch_file_node")
    report = state.get("report", {})

    try:
        # ── Read original file ────────────────────────────────────────────────
        file_path: str = report.get("fileName", "")
        if not file_path or not os.path.exists(file_path):
            _log._logger.warning("patch_file_node — source file not found: %s", file_path)
            return {
                "patched":         False,
                "patch_content":   "",
                "patch_diff":      "",
                "patch_original":  "",
                "finding_patches": [],
            }

        with open(file_path, encoding="utf-8") as fh:
            original = fh.read()

        # ── Per-finding patches (each applied to original independently) ──────
        finding_patches: list[dict] = []
        for finding in sorted(report.get("findings", []), key=lambda f: f.get("id", 0)):
            if not (finding.get("diff") or "").strip():
                continue
            pr = preview_patch_single_finding(original, finding, file_path)
            finding_patches.append({
                "finding_id":   finding.get("id"),
                "smell":        finding.get("smell", ""),
                "patched":      pr.patched,
                "unified_diff": pr.unified_diff,
                "errors":       pr.errors,
            })
            _log._logger.debug(
                "patch_file_node — finding #%s diff lines: %d",
                finding.get("id"), len(pr.unified_diff.splitlines()),
            )

        # ── Combined patch (all findings applied sequentially) ────────────────
        combined_pr = git_apply_patch(report, logger=_log) or preview_patch(report)
        if combined_pr is None:
            _log._logger.warning("patch_file_node — combined patch returned None")
            report["_patchOriginal"]  = original
            report["_findingPatches"] = finding_patches
            return {
                "report":          report,
                "patched":         False,
                "patch_content":   original,
                "patch_diff":      "",
                "patch_original":  original,
                "finding_patches": finding_patches,
            }

        # Write combined-patched content to disk.
        with open(combined_pr.file_path, "w", encoding="utf-8") as fh:
            fh.write(combined_pr.patched)

        _log._logger.info(
            "patch_file_node — combined patch written ✓  (%d per-finding patches)",
            len(finding_patches),
        )

        # Embed patch metadata directly into report so merge_node and
        # create_pr_node always have access regardless of LangGraph fan-in
        # state-key merging behaviour.
        report["_patchOriginal"]  = original
        report["_findingPatches"] = finding_patches

        return {
            "report":          report,
            "patched":         True,
            "patch_content":   combined_pr.patched,
            "patch_diff":      combined_pr.unified_diff,
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


def create_pr_node(state: GraphState) -> dict:
    """Node: Crear PRs.

    Creates one feature branch + PR per finding when the file belongs to a
    tracked GitHub repo.  Uses pre-computed per-finding patch content so the
    PR diff for each finding shows only that finding's changes.

    Writes ONLY `pr_urls`.
    """
    file_path = state.get("file_path", "")
    report    = state.get("report", {})

    # Prefer the list embedded in report by merge_node (_findingPatches), which
    # is guaranteed to be present regardless of LangGraph fan-in state merging.
    # Fall back to the raw state key as a secondary source.
    finding_patches = (
        report.get("_findingPatches")
        or state.get("finding_patches")
        or []
    )

    _log._logger.info(
        "🐙 create_pr_node — file: %s  finding_patches: %d",
        file_path, len(finding_patches),
    )

    pr_urls = create_pr_per_finding_sync(report, file_path, finding_patches)

    _log._logger.info(
        "create_pr_node — %d PR(s) created", len(pr_urls)
    )
    for entry in pr_urls:
        _log._logger.info(
            "  finding #%s → %s", entry.get("finding_id"), entry.get("url")
        )

    return {"pr_urls": pr_urls}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_json_valid(state: GraphState) -> str:
    """Conditional edge after validate_json_node."""
    return "valid" if state.get("valid_json") else "retry"


def route_create_pr(state: GraphState) -> str:
    """Conditional edge after merge_node."""
    file_path = state.get("file_path", "")
    return "create_pr" if resolve_repo(file_path) is not None else "skip_pr"


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
    graph.add_node("create_pr",      create_pr_node)

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
        route_create_pr,
        {"create_pr": "create_pr", "skip_pr": END},
    )
    graph.add_edge("create_pr", END)

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
