"""
XTPPRLinkerAgent — Associates XTP mismatch justifications with GitHub Pull Requests.

Architecture — three separate agent classes
-------------------------------------------

  XTPPRDiscoveryAgent   (Phase 1)
      Uses create_agent + GitHub MCP tools.
      Calls list_pull_requests on Aeacosta-CenfoTec/XTPProgram to retrieve
      every PR, then uses get_pull_request to enrich each one.
      Filters the list to PRs whose merge_commit_sha falls in the sha_a..sha_b
      range and returns a compact JSON catalogue.

  XTPPRMatcherAgent     (Phase 2)
      Uses create_agent — NO tools.
      Receives the catalogue + one justification row.
      Returns {"pr_numbers": [...], "pr_titles": [...]} JSON.

  XTPPRLinkerAgent      (Orchestrator)
      Runs Phase 1 once, then Phase 2 for every row in the DataFrame.
      Builds the enriched DataFrame and Markdown summary.

Output contract
---------------
``XTPPRLinkerAgent.link(df, sha_a, sha_b)`` returns:
    ``enriched_df``  — original DataFrame + pr_numbers + pr_titles + pr_links
    ``summary_md``   — Markdown table with [#N](url) links in the PR(s) column
    ``error``        — empty string on success, message on failure
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

# ---------------------------------------------------------------------------
# Repository constants
# ---------------------------------------------------------------------------

GITHUB_REPO_OWNER = "Aeacosta-CenfoTec"
GITHUB_REPO_NAME  = "XTPProgram"
GITHUB_PR_BASE    = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/pull"

# ---------------------------------------------------------------------------
# MCP client config  (mirrors test_mcp.py exactly)
# ---------------------------------------------------------------------------

def _mcp_config() -> dict:
    return {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "transport": "stdio",
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", ""),
            },
        }
    }

# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _extract_json_array(text: str) -> str:
    """Return the first well-formed JSON array substring found in *text*.

    Handles models that prepend or append prose around the JSON block, and
    also handles markdown code fences (```json … ```).
    Raises ``ValueError`` if no ``[…]`` block is found.
    """
    # 1. Strip markdown fences first
    clean = re.sub(r"^```[a-z]*\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    clean = re.sub(r"\n?```\s*$", "", clean.strip()).strip()

    # 2. Find the outermost [ … ] by scanning for balanced brackets
    start = clean.find("[")
    if start == -1:
        raise ValueError(f"No JSON array found in text: {text[:200]!r}")
    depth = 0
    for i, ch in enumerate(clean[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return clean[start : i + 1]
    raise ValueError(f"Unbalanced JSON array in text: {text[:200]!r}")


def _extract_json_object(text: str) -> str:
    """Return the first well-formed JSON object substring found in *text*.

    Same approach as :func:`_extract_json_array` but for ``{…}`` blocks.
    Raises ``ValueError`` if no ``{…}`` block is found.
    """
    clean = re.sub(r"^```[a-z]*\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    clean = re.sub(r"\n?```\s*$", "", clean.strip()).strip()

    start = clean.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in text: {text[:200]!r}")
    depth = 0
    for i, ch in enumerate(clean[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return clean[start : i + 1]
    raise ValueError(f"Unbalanced JSON object in text: {text[:200]!r}")


# ---------------------------------------------------------------------------
# Shared LLM factory
# ---------------------------------------------------------------------------

def _build_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        openai_api_key=os.getenv("LLM_API_KEY"),
        openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
        temperature=0.0,
    )

# ===========================================================================
# Phase 1 — PR Discovery Agent
# ===========================================================================

_DISCOVERY_SYSTEM_PROMPT = f"""
You are a GitHub repository analyst with access to the GitHub MCP tools.

Repository : {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}

### YOUR TASK
The user message provides SHA_A (baseline commit) and SHA_B (modified commit).
Use the GitHub MCP tools to retrieve ALL Pull Requests in the repository,
then identify which ones were merged between SHA_A and SHA_B.

### STEPS — follow them in exactly this order:
1. Call `list_pull_requests` with:
     owner = "{GITHUB_REPO_OWNER}"
     repo  = "{GITHUB_REPO_NAME}"
     state = "closed"
   This returns the closed (and merged) PRs.

2. For each PR whose merge_commit_sha is non-null, check whether it belongs to
   the commit range SHA_A..SHA_B.  If you cannot determine this from the
   list alone, call `get_pull_request` for that PR to get the full details
   including merge_commit_sha.

3. A PR is "in range" when its merge_commit_sha equals SHA_B, or when it was
   merged after SHA_A was created and at or before SHA_B.  When in doubt,
   include the PR rather than exclude it.

### OUTPUT FORMAT
Return ONLY a JSON array — no prose, no markdown fences:
[
  {{
    "number": <int>,
    "title":  "<str>",
    "state":  "merged",
    "labels": ["<str>", ...],
    "body":   "<first 600 chars of body, or empty string>"
  }},
  ...
]

If no PRs fall in range, return [].
"""


class XTPPRDiscoveryAgent:
    """Phase 1: uses the GitHub MCP to list all PRs and filter to sha_a..sha_b.

    Parameters
    ----------
    logger : AgentLogger | None
    """

    def __init__(self, logger: AgentLogger | None = None) -> None:
        self._log = logger or AgentLogger(name="xtp_pr_discovery", level="DEBUG")

    async def discover(self, sha_a: str, sha_b: str) -> list[dict]:
        """Return a catalogue of PRs merged in the sha_a..sha_b range.

        Connects to the GitHub MCP server, loads all tools, builds a
        create_agent ReAct loop, and parses the JSON array from the final
        assistant message.

        Returns [] on any error (logged at ERROR level).
        """
        log = self._log._logger

        if not sha_a or not sha_b:
            log.warning("[Discovery] sha_a or sha_b is empty — returning empty catalogue.")
            return []

        log.info("[Discovery] Connecting to GitHub MCP server …")
        mcp_client = MultiServerMCPClient(_mcp_config())
        tools = await mcp_client.get_tools()

        log.info(
            "[Discovery] MCP tools loaded (%d): %s",
            len(tools), [t.name for t in tools],
        )
        if not tools:
            log.error(
                "[Discovery] No MCP tools returned.  Check that npx is in PATH, "
                "@modelcontextprotocol/server-github is accessible, and "
                "GITHUB_PERSONAL_ACCESS_TOKEN is set."
            )
            return []

        model = _build_model()
        log.debug("[Discovery] LLM: %s @ %s", os.getenv("LLM_MODEL"), os.getenv("LLM_API_BASE"))

        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=_DISCOVERY_SYSTEM_PROMPT,
        )

        user_message = (
            f"Retrieve all Pull Requests from {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME} "
            f"and return those merged in the commit range below.\n\n"
            f"SHA_A (baseline) : {sha_a}\n"
            f"SHA_B (modified) : {sha_b}\n\n"
            f"Use list_pull_requests (state=closed) first, then get_pull_request "
            f"for any candidates.  Return the JSON array."
        )
        log.debug("[Discovery] User message:\n%s", user_message)

        raw = ""
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]}
            )

            # ── log every message in the agent conversation ───────────────
            messages = result.get("messages", [])
            log.debug("[Discovery] Agent conversation — %d message(s):", len(messages))
            for i, msg in enumerate(messages):
                role    = getattr(msg, "type", type(msg).__name__)
                content = str(getattr(msg, "content", ""))
                calls   = getattr(msg, "tool_calls", [])
                if calls:
                    log.debug(
                        "[Discovery] [%d] %s → tool_calls: %s",
                        i, role,
                        [{"name": c.get("name"), "args_preview": str(c.get("args",""))[:120]}
                         for c in calls],
                    )
                else:
                    log.debug("[Discovery] [%d] %s: %s", i, role, content[:400])

            raw = messages[-1].content.strip()
            log.debug("[Discovery] Raw final answer (%d chars):\n%s", len(raw), raw[:1200])

            clean = _extract_json_array(raw)
            log.debug("[Discovery] Extracted JSON array (%d chars):\n%s", len(clean), clean[:600])

            catalogue = json.loads(clean)
            if not isinstance(catalogue, list):
                raise ValueError(
                    f"Expected JSON array, got {type(catalogue).__name__}: {clean[:200]}"
                )

            log.info(
                "[Discovery] Parsed %d PR(s): %s",
                len(catalogue),
                [f"#{p.get('number')} — {p.get('title','')[:50]}" for p in catalogue],
            )
            return catalogue

        except json.JSONDecodeError as exc:
            log.error(
                "[Discovery] JSON parse error: %s\nRaw answer was:\n%s",
                exc, raw[:800],
            )
            return []
        except Exception as exc:  # noqa: BLE001
            log.error("[Discovery] Unexpected error: %s", exc, exc_info=True)
            return []


# ===========================================================================
# Phase 2 — PR Matcher Agent
# ===========================================================================

_MATCHING_SYSTEM_PROMPT = f"""
You are an ATE Test-Program Change-Management specialist.

Repository : {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}

You will receive ONE XTP mismatch justification row and a JSON catalogue of
Pull Requests that were merged in the relevant commit range.

Do NOT call any tools — all the data you need is in the catalogue.

### MATCHING RULES
A PR is a match when ANY of these hold:
  - Its title or body mentions the same XTP block (LEVELS, TIMING, PARAMETRICS,
    BINNING, FUNCTIONS, PINMAP) that appears in most_likely_cause.
  - Its title or body mentions the same parameter name (e.g. V_DD_CORE,
    strobe_ns, I_DDQ_MAX) found in most_likely_cause.
  - Its labels match the XTP block category of the cause.
  - Its title describes the same type of change (voltage, timing, leakage, etc.).

### OUTPUT FORMAT
Return ONLY a JSON object — no prose, no markdown fences:
{{
  "pr_numbers": [<int>, ...],
  "pr_titles":  [<str>, ...]
}}

If no PR matches, return {{"pr_numbers": [], "pr_titles": []}}.
"""


class XTPPRMatcherAgent:
    """Phase 2: matches one justification row against a pre-fetched PR catalogue.

    No GitHub tools are used — the catalogue is passed directly in the prompt.

    Parameters
    ----------
    logger : AgentLogger | None
    """

    def __init__(self, logger: AgentLogger | None = None) -> None:
        self._log = logger or AgentLogger(name="xtp_pr_matcher", level="DEBUG")
        model = _build_model()
        self._agent = create_agent(
            model=model,
            tools=[],
            system_prompt=_MATCHING_SYSTEM_PROMPT,
        )

    async def match(
        self,
        row: pd.Series,
        catalogue_json: str,
    ) -> tuple[str, str, str]:
        """Match *row* against *catalogue_json*.

        Returns (pr_numbers_str, pr_titles_str, pr_links_str).
        All three are "—" when no PR matches or on error.
        """
        log = self._log._logger

        prog_a     = row.get("prog_a_bin",       "?")
        prog_b     = row.get("prog_b_bin",        "?")
        cause      = row.get("most_likely_cause", "?")
        direction  = row.get("direction",         "?")
        confidence = row.get("confidence",        "?")

        log.debug(
            "[Matcher] Row: %s → %s | cause: %s",
            prog_a, prog_b, str(cause)[:80],
        )

        user_message = (
            f"## Mismatch row\n"
            f"- Prog A Bin       : {prog_a}\n"
            f"- Prog B Bin       : {prog_b}\n"
            f"- Direction        : {direction}\n"
            f"- Confidence       : {confidence}\n"
            f"- Most Likely Cause: {cause}\n\n"
            f"## PR Catalogue (merged in commit range sha_a..sha_b)\n"
            f"{catalogue_json}\n\n"
            f"Match this row against the catalogue and return the JSON object."
        )

        raw_answer = ""
        try:
            result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]}
            )
            raw_answer = result["messages"][-1].content.strip()
            log.debug("[Matcher] Raw answer: %s", raw_answer[:400])

            clean = _extract_json_object(raw_answer)
            log.debug("[Matcher] Extracted JSON object: %s", clean[:300])

            parsed  = json.loads(clean)
            numbers = parsed.get("pr_numbers", [])
            titles  = parsed.get("pr_titles",  [])

            numbers_str = ", ".join(f"#{n}" for n in numbers) if numbers else "—"
            titles_str  = ", ".join(str(t) for t in titles)   if titles  else "—"
            links_str   = ", ".join(
                f"[#{n}]({GITHUB_PR_BASE}/{n})" for n in numbers
            ) if numbers else "—"

            log.debug(
                "[Matcher] Result: numbers=%s  titles=%s",
                numbers_str, titles_str,
            )
            return numbers_str, titles_str, links_str

        except json.JSONDecodeError as exc:
            log.warning(
                "[Matcher] JSON parse error (%s→%s): %s\nRaw: %s",
                prog_a, prog_b, exc, raw_answer[:400],
            )
            return "—", "—", "—"
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[Matcher] Unexpected error (%s→%s): %s",
                prog_a, prog_b, exc, exc_info=True,
            )
            return "—", "—", "—"


# ===========================================================================
# Orchestrator — XTPPRLinkerAgent
# ===========================================================================

class XTPPRLinkerAgent:
    """Orchestrates XTPPRDiscoveryAgent and XTPPRMatcherAgent to enrich the
    mismatch justification DataFrame with GitHub PR references.

    Usage
    -----
    ::

        agent = XTPPRLinkerAgent()
        result = agent.link(df, sha_a="abc1234", sha_b="def5678")
        print(result["summary_md"])
        enriched = result["enriched_df"]

    Parameters
    ----------
    logger : AgentLogger | None
        Shared logger passed down to both sub-agents.
    """

    def __init__(self, logger: AgentLogger | None = None) -> None:
        self._log      = logger or AgentLogger(name="xtp_pr_linker", level="DEBUG")
        self._discover = XTPPRDiscoveryAgent(logger=self._log)
        self._matcher  = XTPPRMatcherAgent(logger=self._log)

    # ------------------------------------------------------------------
    # Public interface (sync wrapper)
    # ------------------------------------------------------------------

    def link(
        self,
        df: pd.DataFrame,
        sha_a: str = "",
        sha_b: str = "",
    ) -> dict[str, Any]:
        """Enrich *df* with PR references. Synchronous; safe to call from
        LangGraph nodes and Dash background threads.

        Parameters
        ----------
        df    : DataFrame from ``XTPTableExtractor.extract()``.
        sha_a : Baseline commit SHA (Program A).
        sha_b : Modified commit SHA (Program B).

        Returns
        -------
        dict with keys ``enriched_df``, ``summary_md``, ``error``.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._link_async(df, sha_a, sha_b))
        finally:
            loop.close()

    # ------------------------------------------------------------------
    # Async orchestration
    # ------------------------------------------------------------------

    async def _link_async(
        self,
        df: pd.DataFrame,
        sha_a: str,
        sha_b: str,
    ) -> dict[str, Any]:
        log = self._log._logger
        log.info(
            "[Linker] ── START ── sha_a=%s  sha_b=%s  rows=%d",
            sha_a[:8] if sha_a else "(none)",
            sha_b[:8] if sha_b else "(none)",
            len(df),
        )

        # ── Phase 1: discover PRs via MCP ────────────────────────────────
        log.info("[Linker] Phase 1 — PR discovery …")
        pr_catalogue = await self._discover.discover(sha_a, sha_b)
        log.info(
            "[Linker] Phase 1 complete — %d PR(s): %s",
            len(pr_catalogue),
            [f"#{p.get('number')}" for p in pr_catalogue],
        )

        catalogue_json = json.dumps(pr_catalogue, ensure_ascii=False, indent=2)

        # ── Phase 2: match each row ───────────────────────────────────────
        log.info("[Linker] Phase 2 — matching %d justification row(s) …", len(df))

        pr_numbers_col: list[str] = []
        pr_titles_col:  list[str] = []
        pr_links_col:   list[str] = []

        for idx, row in df.iterrows():
            log.debug(
                "[Linker] Matching row %d/%d: %s → %s",
                idx + 1, len(df),
                row.get("prog_a_bin", "?"), row.get("prog_b_bin", "?"),
            )
            numbers_str, titles_str, links_str = await self._matcher.match(
                row, catalogue_json
            )
            pr_numbers_col.append(numbers_str)
            pr_titles_col.append(titles_str)
            pr_links_col.append(links_str)
            log.info(
                "[Linker] Row %d/%d  %s→%s  →  %s",
                idx + 1, len(df),
                row.get("prog_a_bin", "?"), row.get("prog_b_bin", "?"),
                numbers_str,
            )

        enriched = df.copy()
        enriched["pr_numbers"] = pr_numbers_col
        enriched["pr_titles"]  = pr_titles_col
        enriched["pr_links"]   = pr_links_col

        summary_md = self._build_summary_markdown(enriched)
        log.info("[Linker] ── DONE ──")
        return {"enriched_df": enriched, "summary_md": summary_md, "error": ""}

    # ------------------------------------------------------------------
    # Markdown builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary_markdown(df: pd.DataFrame) -> str:
        """Produce a Markdown table with [#N](url) links in the PR(s) column."""
        lines = [
            "| Prog A Bin | Prog B Bin | Most Likely Cause | Direction | Confidence | PR(s) |",
            "|---|---|---|---|---|---|",
        ]
        for _, row in df.iterrows():
            pr_cell = row.get("pr_links", row.get("pr_numbers", "—"))
            lines.append(
                f"| {row.get('prog_a_bin', '?')} "
                f"| {row.get('prog_b_bin', '?')} "
                f"| {row.get('most_likely_cause', '?')} "
                f"| {row.get('direction', '?')} "
                f"| {row.get('confidence', '?')} "
                f"| {pr_cell} |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Script entry-point — self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from XTPAnalyser.Agents.XTPTableExtractor import XTPTableExtractor

    _SAMPLE_TABLE = """
| Prog A Bin | Prog B Bin | Count | % of Src | Direction | Most Likely Cause (Diff Block / Parameter) | Confidence |
|---|---|---|---|---|---|---|
| SB_1001_PassPrime | SB_1003_EcoPass | 103 | 12.9% | ↓ down-bin | LEVELS / V_DD_CORE: 1.20V→0.95V reduces noise margin → Eco-Pass threshold crossed | HIGH |
| SB_1001_PassPrime | SB_4001_TimingFail | 58 | 7.3% | ✗ pass→fail | LEVELS / V_DD_CORE: 1.20V→0.95V increases gate propagation delay → setup-time violation | HIGH |
"""

    _sha_a = sys.argv[1] if len(sys.argv) > 1 else ""
    _sha_b = sys.argv[2] if len(sys.argv) > 2 else ""

    _df     = XTPTableExtractor().extract(_SAMPLE_TABLE)
    _agent  = XTPPRLinkerAgent()
    _result = _agent.link(_df, sha_a=_sha_a, sha_b=_sha_b)

    if _result["error"]:
        print("ERROR:", _result["error"])
    else:
        print("=== Enriched DataFrame ===")
        print(_result["enriched_df"].to_string(index=False))
        print()
        print("=== Summary Markdown ===")
        print(_result["summary_md"])
