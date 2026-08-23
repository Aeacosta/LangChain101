"""GitHub PR creator — uses the GitHub MCP server via langchain-mcp-adapters.

Workflow per analysis
---------------------
1. Resolve which GitHub repo owns the analysed file.
2. Compute the patched file content (via FilePatcher.preview_patch).
3. Ask the MCP agent to:
   a. Create a branch  ``codesmell/<stem>-<timestamp>``  off ``main``.
   b. Push **only** the patched file to that branch.
   c. Open a pull request from that branch into ``main``.
4. Return the PR HTML URL.

Supported target repositories
------------------------------
* ``Aeacosta/LangChain101``               — local ``Ejemplos/`` files.
* ``Aeacosta-CenfoTec/CodeSmellExamples`` — files from that GitHub repo.

``resolve_repo(file_path)`` returns ``(owner, repo, base_branch, repo_file_path)``
or ``None`` when the file doesn't belong to either repo.

Public API
----------
    pr_url = await create_pull_request(report, file_path)
    pr_url =       create_pull_request_sync(report, file_path)   # sync wrapper
"""

from __future__ import annotations

import asyncio
import os
import re
import time

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

from Helpers.FilePatcher import preview_patch
from Helpers.Logger import AgentLogger

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

_log = AgentLogger(name="github_pr_agent", level="DEBUG")

# ---------------------------------------------------------------------------
# Repo registry
# ---------------------------------------------------------------------------
# Each entry: (owner, repo, base_branch, match_fn, path_resolver)
#
# path_resolver(file_path) -> str
#   Returns the path of the file *inside* the repo (no leading slash).
# ---------------------------------------------------------------------------

def _local_ejemplos_path(file_path: str) -> str:
    """Strip the leading Ejemplos/ prefix so the path is relative to CodeSmellExamples.

    e.g.  "Ejemplos\\CodeSmell1.cs"  ->  "CodeSmell1.cs"
          "Ejemplos/sub/Foo.cs"      ->  "sub/Foo.cs"
    """
    normalised = file_path.replace("\\", "/")
    # Remove the leading "Ejemplos/" folder — the submodule root IS that folder.
    if normalised.startswith("Ejemplos/"):
        return normalised[len("Ejemplos/"):]
    return os.path.basename(normalised)


def _codesmell_examples_path(file_path: str) -> str:
    """Extract the in-repo path from a CodeSmellExamples GitHub URL.

    e.g. https://github.com/Aeacosta-CenfoTec/CodeSmellExamples/blob/main/CodeSmell1.cs
      -> CodeSmell1.cs
    """
    match = re.search(r"CodeSmellExamples/blob/[^/]+/(.+)", file_path)
    return match.group(1) if match else os.path.basename(file_path)


_REPO_REGISTRY: list[tuple[str, str, str, object, object]] = [
    # GitHub URL for CodeSmellExamples
    (
        "Aeacosta-CenfoTec",
        "CodeSmellExamples",
        "main",
        lambda p: "Aeacosta-CenfoTec/CodeSmellExamples" in p,
        _codesmell_examples_path,
    ),
    # Local Ejemplos/ folder — submodule of CodeSmellExamples
    (
        "Aeacosta-CenfoTec",
        "CodeSmellExamples",
        "main",
        lambda p: p.replace("\\", "/").startswith("Ejemplos/")
                  or "/Ejemplos/" in p.replace("\\", "/"),
        _local_ejemplos_path,
    ),
]


def resolve_repo(file_path: str) -> tuple[str, str, str, str] | None:
    """Return ``(owner, repo, base_branch, repo_file_path)`` or ``None``."""
    for owner, repo, base, match, path_fn in _REPO_REGISTRY:
        if match(file_path):
            return owner, repo, base, path_fn(file_path)
    return None


# ---------------------------------------------------------------------------
# PR body builder
# ---------------------------------------------------------------------------

def _build_pr_body(report: dict, file_path: str) -> tuple[str, str]:
    """Return ``(title, body)``."""
    file_name  = report.get("fileName") or os.path.basename(file_path)
    assessment = report.get("summary", {}).get("overallAssessment", "")
    findings   = report.get("findings", [])
    score      = report.get("scoreReport") or {}

    title = f"[CodeSmell] Analysis report for {file_name}"

    lines: list[str] = [
        f"## Code Smell Analysis — `{file_name}`",
        "",
        f"> {assessment}" if assessment else "",
        "",
    ]

    if score:
        grade = score.get("grade", "?")
        pts   = score.get("score", "?")
        lines += [f"**Score:** {pts} / 100  |  **Grade:** {grade}", ""]

    if findings:
        lines += ["### Findings", ""]
        for f in findings:
            sev  = f.get("severity", "Low")
            name = f.get("smell", "")
            desc = f.get("description", "")
            rec  = f.get("recommendation", "")
            lines += [
                f"#### #{f.get('id')} — {name} `[{sev}]`",
                desc,
                f"**Recommendation:** {rec}" if rec else "",
                "",
            ]

    order = report.get("refactoringOrder", [])
    if order:
        id_map = {fnd["id"]: fnd.get("smell", "") for fnd in findings if "id" in fnd}
        steps  = " → ".join(
            f"#{item.get('findingId')} {id_map.get(item.get('findingId'), '')}"
            for item in order if isinstance(item, dict)
        )
        lines += ["### Suggested Refactoring Order", "", steps, ""]

    lines += [
        "---",
        "*Generated automatically by the Code Smell Analyzer (LangChain101).*",
    ]

    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# Core async function
# ---------------------------------------------------------------------------

async def create_pull_request(report: dict, file_path: str) -> str:
    """Create a GitHub PR for the analysis report.

    Calls the GitHub MCP tools directly in order — no LLM agent involved:
    1. ``create_branch``         — creates the feature branch off ``base_branch``.
    2. ``create_or_update_file`` — pushes only the patched file to that branch.
    3. ``create_pull_request``   — opens the PR.

    Returns the PR HTML URL, an empty string if the repo is not matched,
    or an error string on failure.
    """
    resolved = resolve_repo(file_path)
    if resolved is None:
        _log._logger.info("create_pull_request — no matching repo for: %s", file_path)
        return ""

    owner, repo, base_branch, repo_file_path = resolved

    # ── Compute patched content ──────────────────────────────────────────────
    patch_result = preview_patch(report)
    if patch_result is None:
        _log._logger.warning(
            "create_pull_request — preview_patch returned None for %s", file_path
        )
        patched_content = ""
    else:
        patched_content = patch_result.patched

    if not patched_content:
        _log._logger.error("create_pull_request — no patched content; aborting PR")
        return "Error: patched file content is empty."

    # ── Names ────────────────────────────────────────────────────────────────
    stem        = os.path.splitext(os.path.basename(repo_file_path))[0]
    timestamp   = int(time.time())
    head_branch = f"codesmell/{stem}-{timestamp}"
    title, body = _build_pr_body(report, file_path)

    _log._logger.info(
        "🐙 create_pull_request — %s/%s  branch: %s", owner, repo, head_branch
    )

    github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    if not github_token:
        return "Error: GITHUB_PERSONAL_ACCESS_TOKEN is not set."

    # ── Connect to the GitHub MCP server and get tools ───────────────────────
    client = MultiServerMCPClient(
        {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "transport": "stdio",
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": github_token},
            }
        }
    )
    tools = await client.get_tools()

    # Index tools by name for direct lookup.
    tool_map = {t.name: t for t in tools}
    _log._logger.debug(
        "github_pr_agent — available tools: %s", list(tool_map.keys())
    )

    def _get_tool(name: str):
        if name not in tool_map:
            raise RuntimeError(
                f"GitHub MCP tool '{name}' not found. "
                f"Available: {list(tool_map.keys())}"
            )
        return tool_map[name]

    # ── Step 1: create branch ─────────────────────────────────────────────────
    _log._logger.info("Step 1 — create_branch: %s", head_branch)
    branch_result = await _get_tool("create_branch").ainvoke({
        "owner":       owner,
        "repo":        repo,
        "branch":      head_branch,
        "from_branch": base_branch,
    })
    _log._logger.debug("create_branch result: %s", branch_result)

    # ── Step 2: push patched file ─────────────────────────────────────────────
    _log._logger.info("Step 2 — create_or_update_file: %s", repo_file_path)
    file_result = await _get_tool("create_or_update_file").ainvoke({
        "owner":   owner,
        "repo":    repo,
        "path":    repo_file_path,
        "message": f"chore: apply code smell fixes to {repo_file_path}",
        "content": patched_content,
        "branch":  head_branch,
    })
    _log._logger.debug("create_or_update_file result: %s", file_result)

    # ── Step 3: open PR ───────────────────────────────────────────────────────
    _log._logger.info("Step 3 — create_pull_request")
    pr_result = await _get_tool("create_pull_request").ainvoke({
        "owner": owner,
        "repo":  repo,
        "title": title,
        "body":  body,
        "head":  head_branch,
        "base":  base_branch,
    })
    _log._logger.info("create_pull_request result: %s", pr_result)

    # Extract the PR URL from the tool response (dict or JSON string).
    if isinstance(pr_result, dict):
        pr_url = pr_result.get("html_url", "")
    else:
        match = re.search(r"https://github\.com/[^\s>\"']+/pull/\d+", str(pr_result))
        pr_url = match.group(0) if match else str(pr_result)

    return pr_url


# ---------------------------------------------------------------------------
# Sync wrapper (LangGraph nodes are synchronous)
# ---------------------------------------------------------------------------

def create_pull_request_sync(report: dict, file_path: str) -> str:
    """Synchronous wrapper around :func:`create_pull_request`.

    Always spawns a fresh event loop via ``asyncio.run()`` so it works safely
    from any thread — including Dash worker threads which have no event loop.
    """
    try:
        return asyncio.run(create_pull_request(report, file_path))
    except Exception as exc:
        _log._logger.error("create_pull_request_sync — error: %s", exc)
        return f"Error: {exc}"
