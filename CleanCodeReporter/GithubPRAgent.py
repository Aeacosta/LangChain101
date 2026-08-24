"""GitHub PR creator — uses the GitHub MCP server via langchain-mcp-adapters.

Workflow per finding
--------------------
For each finding in the report that carries a non-empty ``diff``:
1. Compute the file content with **only that finding's diff** applied.
2. Create a branch  ``codesmell/<stem>-f<id>-<timestamp>``  off ``main``.
3. Push the single-finding-patched file to that branch.
4. Open a pull request from that branch into ``main``.

Returns a list of result dicts, one per finding:
    [{"finding_id": 1, "smell": "...", "branch": "...", "url": "https://..."}, ...]

Supported target repositories
------------------------------
* ``Aeacosta-CenfoTec/CodeSmellExamples`` — local ``Ejemplos/`` files and
  direct GitHub URLs.

``resolve_repo(file_path)`` returns ``(owner, repo, base_branch, repo_file_path)``
or ``None`` when the file doesn't belong to either repo.

Public API
----------
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

from Helpers.FilePatcher import git_apply_patch, preview_patch, preview_patch_single_finding
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
# PR body builder (single finding)
# ---------------------------------------------------------------------------

def _build_pr_body_for_finding(finding: dict, report: dict, file_path: str) -> tuple[str, str]:
    """Return ``(title, body)`` for a single-finding PR."""
    file_name = report.get("fileName") or os.path.basename(file_path)
    fid       = finding.get("id", "?")
    smell     = finding.get("smell", "unknown")
    severity  = finding.get("severity", "Low")
    desc      = finding.get("description", "")
    rec       = finding.get("recommendation", "")
    diff_text = (finding.get("diff") or "").strip()
    rag       = finding.get("ragReference", "")

    title = f"[CodeSmell #{fid}] {smell} in {file_name}"

    loc      = finding.get("location", {})
    loc_parts = [loc.get("fileName", "")]
    if loc.get("className"):
        loc_parts.append(loc["className"])
    if loc.get("methodName"):
        loc_parts.append(loc["methodName"])
    s, e = loc.get("startLine"), loc.get("endLine")
    if s and e:
        loc_parts.append(f"L{s}–{e}")
    elif s:
        loc_parts.append(f"L{s}")
    loc_str = " › ".join(filter(None, loc_parts))

    lines: list[str] = [
        f"## Fix #{fid} — {smell} `[{severity}]`",
        "",
        f"**File:** `{file_name}`",
        f"**Location:** {loc_str}" if loc_str else "",
        "",
        desc,
        "",
    ]

    if rec:
        lines += [f"**Recommendation:** {rec}", ""]

    if diff_text:
        lines += ["### Proposed diff", "", "```diff", diff_text, "```", ""]

    if rag:
        lines += [f"**Reference:** {rag}", ""]

    score = report.get("scoreReport") or {}
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
# Core async function — one PR per finding
# ---------------------------------------------------------------------------

async def create_pr_per_finding(
    report: dict,
    file_path: str,
    finding_patches: list[dict] | None = None,
) -> list[dict]:
    """Create one GitHub branch + PR for every finding that has a diff.

    Parameters
    ----------
    report          : parsed CodeSmellReport dict.
    file_path       : local or GitHub path of the analysed file.
    finding_patches : pre-computed list of per-finding patch results.
                      Each entry: ``{"finding_id": int, "patched": str, ...}``.
                      When ``None`` or empty the function computes them on the fly.

    Returns
    -------
    list[dict]
        One entry per successfully created PR:
        ``{"finding_id": int, "smell": str, "branch": str, "url": str}``.
        Failures are logged and skipped.
    """
    resolved = resolve_repo(file_path)
    if resolved is None:
        _log._logger.info("create_pr_per_finding — no matching repo for: %s", file_path)
        return []

    owner, repo, base_branch, repo_file_path = resolved

    github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    if not github_token:
        _log._logger.error("create_pr_per_finding — GITHUB_PERSONAL_ACCESS_TOKEN not set")
        return []

    # ── Build a lookup: finding_id → patched content ──────────────────────────
    patch_lookup: dict[int, str] = {}
    if finding_patches:
        for fp in finding_patches:
            fid = fp.get("finding_id")
            if fid is not None and fp.get("patched"):
                patch_lookup[fid] = fp["patched"]

    # Also cache the original text stored in the report (set by merge_node) so
    # the on-the-fly fallback never reads from the already-modified disk file.
    original_text: str = report.get("_patchOriginal", "")

    findings = [f for f in report.get("findings", []) if (f.get("diff") or "").strip()]
    if not findings:
        _log._logger.info("create_pr_per_finding — no findings with diffs; nothing to do")
        return []

    stem      = os.path.splitext(os.path.basename(repo_file_path))[0]
    timestamp = int(time.time())

    # ── Open one shared MCP client for all PRs ────────────────────────────────
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

    results: list[dict] = []

    for finding in sorted(findings, key=lambda f: f.get("id", 0)):
        fid   = finding.get("id", 0)
        smell = finding.get("smell", "")

        # ── Resolve patched content for this single finding ───────────────────
        patched_content = patch_lookup.get(fid, "")
        if not patched_content:
            # Fallback: apply this finding's diff against the original text.
            # Never read from disk here — the file may already be combined-patched.
            if original_text:
                _log._logger.warning(
                    "finding #%s — patch_lookup miss; recomputing from _patchOriginal", fid
                )
                pr_result = preview_patch_single_finding(original_text, finding, file_path)
                patched_content = pr_result.patched
            else:
                _log._logger.warning(
                    "finding #%s — patch_lookup miss AND no _patchOriginal; falling back to disk", fid
                )
                single_report = {**report, "findings": [finding]}
                pr_result = preview_patch(single_report)
                patched_content = pr_result.patched if pr_result else ""

            if not patched_content:
                _log._logger.warning(
                    "create_pr_per_finding — could not patch finding #%s; skipping", fid
                )
                continue

        head_branch = f"codesmell/{stem}-f{fid}-{timestamp}"
        title, body = _build_pr_body_for_finding(finding, report, file_path)

        _log._logger.info("🐙 finding #%s — branch: %s", fid, head_branch)

        try:
            # Step 1: create branch
            await _get_tool("create_branch").ainvoke({
                "owner":       owner,
                "repo":        repo,
                "branch":      head_branch,
                "from_branch": base_branch,
            })

            # Step 2: push single-finding-patched file
            await _get_tool("create_or_update_file").ainvoke({
                "owner":   owner,
                "repo":    repo,
                "path":    repo_file_path,
                "message": f"fix: #{fid} {smell} in {repo_file_path}",
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

            _log._logger.info("PR created for finding #%s: %s", fid, pr_url)
            results.append({
                "finding_id": fid,
                "smell":      smell,
                "branch":     head_branch,
                "url":        pr_url,
            })

        except Exception as exc:  # noqa: BLE001
            _log._logger.error("create_pr_per_finding — finding #%s failed: %s", fid, exc)

    return results


# ---------------------------------------------------------------------------
# Sync wrapper
# ---------------------------------------------------------------------------

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
