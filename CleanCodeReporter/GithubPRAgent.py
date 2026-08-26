"""GitHub Issue / PR creator — uses the GitHub MCP server via langchain-mcp-adapters.

PR Workflow (legacy — disabled by default due to instability)
-------------------------------------------------------------
1. Take the combined patched file content already computed by patch_file_node
   (stored in report["_patchContent"]) — or read it from disk as a fallback.
2. Create a branch  ``codesmell/<stem>-<timestamp>``  off ``main``.
3. Push the patched file to that branch.
4. Open a pull request from that branch into ``main``.

Issue Workflow (preferred)
--------------------------
For each file analysed, open **one** GitHub Issue that lists all findings with
their diffs.  No branch, no direct code push — the changes are proposed as a
ticket so a human can review them before merging.

Returns a list with one result dict:
    [{"finding_id": "all", "smell": "combined", "issue_number": 42, "url": "https://..."}]

Supported target repositories
------------------------------
* ``Aeacosta-CenfoTec/CodeSmellExamples`` — local ``Ejemplos/`` files and
  direct GitHub URLs.

``resolve_repo(file_path)`` returns ``(owner, repo, base_branch, repo_file_path)``
or ``None`` when the file doesn't belong to either repo.

Public API
----------
    results = await create_issue_per_finding(report, file_path)
    results =       create_issue_per_finding_sync(report, file_path)

    # Legacy PR API (kept for backwards compatibility)
    results = await create_pr_per_finding(report, file_path, finding_patches)
    results =       create_pr_per_finding_sync(report, file_path, finding_patches)
"""

from __future__ import annotations

import asyncio
import os
import re
import time

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

from Helpers.Logger import AgentLogger

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

_log = AgentLogger(name="github_pr_agent", level="DEBUG")

# ---------------------------------------------------------------------------
# Repo registry
# ---------------------------------------------------------------------------

def _local_ejemplos_path(file_path: str) -> str:
    """Strip the leading Ejemplos/ prefix so the path is relative to CodeSmellExamples."""
    normalised = file_path.replace("\\", "/")
    if normalised.startswith("Ejemplos/"):
        return normalised[len("Ejemplos/"):]
    return os.path.basename(normalised)


def _codesmell_examples_path(file_path: str) -> str:
    """Extract the in-repo path from a CodeSmellExamples GitHub URL."""
    match = re.search(r"CodeSmellExamples/blob/[^/]+/(.+)", file_path)
    return match.group(1) if match else os.path.basename(file_path)


_REPO_REGISTRY: list[tuple[str, str, str, object, object]] = [
    (
        "Aeacosta-CenfoTec",
        "CodeSmellExamples",
        "main",
        lambda p: "Aeacosta-CenfoTec/CodeSmellExamples" in p,
        _codesmell_examples_path,
    ),
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
# Body builders
# ---------------------------------------------------------------------------

def _build_issue_body(report: dict, file_path: str) -> tuple[str, str]:
    """Return ``(title, body)`` for a GitHub Issue listing all findings."""
    file_name = report.get("fileName") or os.path.basename(file_path)
    findings  = report.get("findings", [])
    score     = report.get("scoreReport") or {}

    n_findings = len([f for f in findings if (f.get("diff") or "").strip()])
    title = f"[CodeSmell] {n_findings} fix(es) requested in {file_name}"

    lines: list[str] = [
        f"## Code Smell Fixes Requested — `{file_name}`",
        "",
        f"The Code Smell Analyzer detected **{n_findings} issue(s)** in `{file_name}`.",
        "The proposed fixes are listed below for human review before any code change is made.",
        "",
        "### Findings",
        "",
    ]

    for f in sorted(findings, key=lambda x: x.get("id", 0)):
        diff = (f.get("diff") or "").strip()
        if not diff:
            continue
        fid      = f.get("id", "?")
        smell    = f.get("smell", "unknown")
        severity = f.get("severity", "Low")
        desc     = f.get("description", "")
        rec      = f.get("recommendation", "")
        lines.append(f"#### #{fid} — {smell} `[{severity}]`")
        if desc:
            lines += ["", desc]
        if rec:
            lines += ["", f"**Recommendation:** {rec}"]
        lines += ["", "```diff", diff, "```", ""]

    if score:
        grade = score.get("grade", "?")
        pts   = score.get("score", "?")
        lines += [f"**Overall score:** {pts} / 100  |  **Grade:** {grade}", ""]

    lines += [
        "---",
        "*Generated automatically by the Code Smell Analyzer (LangChain101).*",
        "*No code was pushed — please review and apply changes manually or via a PR.*",
    ]

    return title, "\n".join(lines)


def _build_pr_body(report: dict, file_path: str) -> tuple[str, str]:
    """Return ``(title, body)`` for the combined-findings PR."""
    file_name    = report.get("fileName") or os.path.basename(file_path)
    findings     = report.get("findings", [])
    score        = report.get("scoreReport") or {}

    n_findings = len([f for f in findings if (f.get("diff") or "").strip()])
    title = f"[CodeSmell] {n_findings} fix(es) in {file_name}"

    lines: list[str] = [
        f"## Code Smell Fixes — `{file_name}`",
        "",
        f"This PR contains **{n_findings} automated fix(es)** produced by the "
        "Code Smell Analyzer.",
        "",
        "### Findings addressed",
        "",
    ]

    for f in sorted(findings, key=lambda x: x.get("id", 0)):
        if not (f.get("diff") or "").strip():
            continue
        fid      = f.get("id", "?")
        smell    = f.get("smell", "unknown")
        severity = f.get("severity", "Low")
        desc     = f.get("description", "")
        rec      = f.get("recommendation", "")
        lines.append(f"#### #{fid} — {smell} `[{severity}]`")
        if desc:
            lines += ["", desc]
        if rec:
            lines += ["", f"**Recommendation:** {rec}"]
        lines.append("")

    if score:
        grade = score.get("grade", "?")
        pts   = score.get("score", "?")
        lines += [f"**Overall score:** {pts} / 100  |  **Grade:** {grade}", ""]

    lines += [
        "---",
        "*Generated automatically by the Code Smell Analyzer (LangChain101).*",
    ]

    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# Core async functions
# ---------------------------------------------------------------------------

async def create_issue_per_finding(
    report: dict,
    file_path: str,
) -> list[dict]:
    """Open one GitHub Issue listing all findings for the file.

    No branch is created and no code is pushed.  The issue body contains
    every finding's description, recommendation, and proposed unified diff
    so a developer can review and apply the changes manually.

    Parameters
    ----------
    report    : parsed CodeSmellReport dict (with scoreReport already merged).
    file_path : local or GitHub path of the analysed file.

    Returns
    -------
    list[dict]
        One entry on success:
        ``{"finding_id": "all", "smell": "combined", "issue_number": int, "url": str}``.
    """
    resolved = resolve_repo(file_path)
    if resolved is None:
        _log._logger.info("create_issue — no matching repo for: %s", file_path)
        return []

    owner, repo, _base_branch, _repo_file_path = resolved

    github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    if not github_token:
        _log._logger.error("create_issue — GITHUB_PERSONAL_ACCESS_TOKEN not set")
        return []

    findings_with_diff = [f for f in report.get("findings", []) if (f.get("diff") or "").strip()]
    if not findings_with_diff:
        _log._logger.info("create_issue — no findings with diffs; nothing to do")
        return []

    title, body = _build_issue_body(report, file_path)

    _log._logger.info("🐙 create_issue — opening issue in %s/%s", owner, repo)

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
    tools    = await client.get_tools()
    tool_map = {t.name: t for t in tools}
    _log._logger.debug("github_issue_agent — tools: %s", list(tool_map.keys()))

    def _get_tool(name: str):
        if name not in tool_map:
            raise RuntimeError(
                f"GitHub MCP tool '{name}' not found. Available: {list(tool_map.keys())}"
            )
        return tool_map[name]

    try:
        issue_resp = await _get_tool("create_issue").ainvoke({
            "owner": owner,
            "repo":  repo,
            "title": title,
            "body":  body,
        })

        if isinstance(issue_resp, dict):
            issue_url    = issue_resp.get("html_url", "")
            issue_number = issue_resp.get("number", 0)
        else:
            m = re.search(r"https://github\.com/[^\s>\"']+/issues/(\d+)", str(issue_resp))
            issue_url    = m.group(0) if m else str(issue_resp)
            issue_number = int(m.group(1)) if m else 0

        _log._logger.info("Issue created: %s", issue_url)
        return [{
            "finding_id":   "all",
            "smell":        "combined",
            "issue_number": issue_number,
            "url":          issue_url,
        }]

    except Exception as exc:  # noqa: BLE001
        _log._logger.error("create_issue — failed: %s", exc)
        return []


async def create_pr_per_finding(
    report: dict,
    file_path: str,
    finding_patches: list[dict] | None = None,
) -> list[dict]:
    """Create one GitHub branch + PR containing all fixes for the file.

    The patched file content is taken directly from ``report["_patchContent"]``
    (written by patch_file_node) or read from disk as a fallback.  No diff
    application happens here — the file is used as-is.

    Parameters
    ----------
    report          : parsed CodeSmellReport dict.
    file_path       : local or GitHub path of the analysed file.
    finding_patches : unused; kept for API compatibility.

    Returns
    -------
    list[dict]
        One entry on success:
        ``{"finding_id": "all", "smell": "combined", "branch": str, "url": str}``.
    """
    resolved = resolve_repo(file_path)
    if resolved is None:
        _log._logger.info("create_pr — no matching repo for: %s", file_path)
        return []

    owner, repo, base_branch, repo_file_path = resolved

    github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    if not github_token:
        _log._logger.error("create_pr — GITHUB_PERSONAL_ACCESS_TOKEN not set")
        return []

    # ── Resolve patched content ───────────────────────────────────────────────
    # Prefer the content already computed and written by patch_file_node.
    patched_content: str = report.get("_patchContent", "")

    if not patched_content:
        # Fallback: read the file from disk (patch_file_node wrote it there).
        local_path = file_path if os.path.exists(file_path) else ""
        if local_path:
            _log._logger.warning("create_pr — _patchContent missing; reading from disk: %s", local_path)
            with open(local_path, encoding="utf-8") as fh:
                patched_content = fh.read()

    if not patched_content:
        _log._logger.error("create_pr — no patched content available; skipping PR")
        return []

    findings_with_diff = [f for f in report.get("findings", []) if (f.get("diff") or "").strip()]
    if not findings_with_diff:
        _log._logger.info("create_pr — no findings with diffs; nothing to do")
        return []

    stem      = os.path.splitext(os.path.basename(repo_file_path))[0]
    timestamp = int(time.time())
    head_branch = f"codesmell/{stem}-{timestamp}"

    title, body = _build_pr_body(report, file_path)

    _log._logger.info("🐙 create_pr — branch: %s", head_branch)

    # ── Open MCP client ───────────────────────────────────────────────────────
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
    tools    = await client.get_tools()
    tool_map = {t.name: t for t in tools}
    _log._logger.debug("github_pr_agent — tools: %s", list(tool_map.keys()))

    def _get_tool(name: str):
        if name not in tool_map:
            raise RuntimeError(
                f"GitHub MCP tool '{name}' not found. Available: {list(tool_map.keys())}"
            )
        return tool_map[name]

    try:
        # Step 1: create branch
        await _get_tool("create_branch").ainvoke({
            "owner":       owner,
            "repo":        repo,
            "branch":      head_branch,
            "from_branch": base_branch,
        })

        # Step 2: push patched file
        await _get_tool("create_or_update_file").ainvoke({
            "owner":   owner,
            "repo":    repo,
            "path":    repo_file_path,
            "message": f"fix: apply {len(findings_with_diff)} code smell fix(es) in {repo_file_path}",
            "content": patched_content,
            "branch":  head_branch,
        })

        # Step 3: open PR
        pr_resp = await _get_tool("create_pull_request").ainvoke({
            "owner": owner,
            "repo":  repo,
            "title": title,
            "body":  body,
            "head":  head_branch,
            "base":  base_branch,
        })

        if isinstance(pr_resp, dict):
            pr_url = pr_resp.get("html_url", "")
        else:
            m = re.search(r"https://github\.com/[^\s>\"']+/pull/\d+", str(pr_resp))
            pr_url = m.group(0) if m else str(pr_resp)

        _log._logger.info("PR created: %s", pr_url)
        return [{
            "finding_id": "all",
            "smell":      "combined",
            "branch":     head_branch,
            "url":        pr_url,
        }]

    except Exception as exc:  # noqa: BLE001
        _log._logger.error("create_pr — failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Sync wrappers
# ---------------------------------------------------------------------------

def create_issue_per_finding_sync(
    report: dict,
    file_path: str,
) -> list[dict]:
    """Synchronous wrapper around :func:`create_issue_per_finding`."""
    try:
        return asyncio.run(create_issue_per_finding(report, file_path))
    except Exception as exc:
        _log._logger.error("create_issue_per_finding_sync — error: %s", exc)
        return []


def create_pr_per_finding_sync(
    report: dict,
    file_path: str,
    finding_patches: list[dict] | None = None,
) -> list[dict]:
    """Synchronous wrapper around :func:`create_pr_per_finding`."""
    try:
        return asyncio.run(create_pr_per_finding(report, file_path, finding_patches))
    except Exception as exc:
        _log._logger.error("create_pr_per_finding_sync — error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Legacy single-PR helpers kept for backwards compatibility
# ---------------------------------------------------------------------------

async def create_pull_request(
    report: dict,
    file_path: str,
    patched_content: str = "",
) -> str:
    """[Legacy] Create a single PR for the whole report.  Prefer create_pr_per_finding."""
    results = await create_pr_per_finding(report, file_path)
    return results[0]["url"] if results else ""


def create_pull_request_sync(
    report: dict,
    file_path: str,
    patched_content: str = "",
) -> str:
    """[Legacy] Synchronous wrapper around create_pull_request."""
    try:
        return asyncio.run(create_pull_request(report, file_path, patched_content))
    except Exception as exc:
        _log._logger.error("create_pull_request_sync — error: %s", exc)
        return f"Error: {exc}"
