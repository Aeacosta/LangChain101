"""
XTPGitCommitAgent — Git-commit-driven XTP Bin2Bin generator.

Given two git commit SHAs from the GitHub repository
``Aeacosta-CenfoTec/XTPProgram``, this agent:

  1. Fetches the XTP file content at each SHA directly via the GitHub REST API
     (no LLM involved — deterministic, no MCP indirection).
  2. Computes a unified diff between the two versions (pure Python).
  3. Calls the LLM agent to derive a Bin2Bin yield-transition matrix that
     correlates the two program versions.
  4. Persists Program A, Program B, and the Bin2Bin CSV to disk.

A thin sync wrapper ``invoke_sync`` is provided for callers that cannot drive
an asyncio event loop directly (e.g. the Dash background thread).

Usage (async)
-------------
    agent = XTPGitCommitAgent()
    result = await agent.invoke(sha_a="abc123", sha_b="def456")

Usage (sync, from a background thread)
---------------------------------------
    agent = XTPGitCommitAgent()
    result = agent.invoke_sync(sha_a="abc123", sha_b="def456")
"""

from __future__ import annotations

import asyncio
import base64
import csv
import difflib
import io
import os
import random

import httpx
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger

# ---------------------------------------------------------------------------
# Repository constants
# ---------------------------------------------------------------------------

GITHUB_REPO_OWNER = "Aeacosta-CenfoTec"
GITHUB_REPO_NAME  = "XTPProgram"
GITHUB_XTP_PATH   = "Program.xtp"          # actual filename in the repo

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""
You are an ATE Test Program engineer analysing two versions of an XTP program.

### TASK
You have already been given the full source of Program A and Program B.
Your job is to:

1. Call `compute_xtp_diff` with the two program texts to produce the unified diff.
2. Call `generate_bin2bin_csv` choosing an appropriate `delta_severity`
   ('mild', 'moderate', or 'severe') based on the number of changed lines.

### OUTPUT FORMAT — output exactly three blocks in this order, nothing else:
- Program A in a fenced code block labelled ```xtp
- Program B in a fenced code block labelled ```xtp
- The Bin2Bin CSV content (everything after `CSV_CONTENT:` in the tool result)
  in a fenced code block labelled ```csv
- Do NOT add any explanation, commentary, or extra text outside these three blocks.
"""


# ---------------------------------------------------------------------------
# GitHub REST helper
# ---------------------------------------------------------------------------

def _fetch_file_at_sha(sha: str, token: str | None) -> str:
    """Fetch ``GITHUB_XTP_PATH`` from the repo at the given commit *sha*.

    Uses the GitHub Contents API::

        GET /repos/{owner}/{repo}/contents/{path}?ref={sha}

    Returns the decoded file text.  Raises ``RuntimeError`` on HTTP errors.
    """
    url = (
        f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        f"/contents/{GITHUB_XTP_PATH}?ref={sha}"
    )
    headers = {"User-Agent": "XTPAnalyser"}
    if token:
        headers["Authorization"] = f"token {token}"

    resp = httpx.get(url, headers=headers, timeout=30)
    if resp.status_code == 404:
        raise RuntimeError(
            f"File '{GITHUB_XTP_PATH}' not found at commit {sha[:8]} in "
            f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}. "
            f"Check the SHA and repository path."
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"GitHub API error {resp.status_code} fetching {sha[:8]}: {resp.text[:200]}"
        )

    data = resp.json()
    # GitHub returns base64-encoded content with newlines
    content_b64 = data.get("content", "")
    return base64.b64decode(content_b64).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class XTPGitCommitAgent:
    """Fetches two XTP program versions from GitHub by commit SHA, computes a
    diff, and produces a Bin2Bin yield-transition matrix."""

    def __init__(self, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="xtp_git_commit_agent", level="DEBUG")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_bin2bin_csv(
        self,
        total_dice: int = 1000,
        delta_severity: str = "moderate",
        output_folder: str = "Programas",
    ) -> str:
        """Compute a Bin2Bin CSV, write it to disk, and return the tool response."""
        pass_prime_a   = int(total_dice * 0.80)
        pass_eco_a     = int(total_dice * 0.10)
        leakage_fail_a = int(total_dice * 0.05)
        timing_fail_a  = int(total_dice * 0.05)

        if delta_severity == "mild":
            downbin_rate     = random.uniform(0.02, 0.05)
            timing_fail_rate = random.uniform(0.01, 0.03)
        elif delta_severity == "moderate":
            downbin_rate     = random.uniform(0.10, 0.18)
            timing_fail_rate = random.uniform(0.05, 0.08)
        else:  # severe
            downbin_rate     = random.uniform(0.25, 0.35)
            timing_fail_rate = random.uniform(0.12, 0.20)

        to_eco         = int(pass_prime_a * downbin_rate)
        to_timing_fail = int(pass_prime_a * timing_fail_rate)
        stay_prime     = pass_prime_a - to_eco - to_timing_fail

        rows = [
            ["Prog_A \\ Prog_B", "SB_1001_PassPrime", "SB_1003_EcoPass", "SB_3001_IDDQ_Fail", "SB_4001_TimingFail"],
            ["SB_1001_PassPrime", stay_prime,   to_eco,       0,              to_timing_fail],
            ["SB_1003_EcoPass",   0,             pass_eco_a,   0,              0             ],
            ["SB_3001_IDDQ_Fail", 0,             0,            leakage_fail_a, 0             ],
            ["SB_4001_TimingFail",0,             0,            0,              timing_fail_a ],
        ]

        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        csv_content = buf.getvalue()

        os.makedirs(output_folder, exist_ok=True)
        csv_path = os.path.join(output_folder, "Bin2Bin_Matrix.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            f.write(csv_content)

        return f"CSV_PATH:{csv_path}\nCSV_CONTENT:\n{csv_content}"

    # ------------------------------------------------------------------
    # Async core
    # ------------------------------------------------------------------

    async def invoke(
        self,
        sha_a: str,
        sha_b: str,
        output_folder: str = "Programas",
    ) -> dict[str, str]:
        """Fetch both commits, diff them, produce Bin2Bin.

        Returns a dict with keys:
            ``program_a``  — XTP source at sha_a
            ``program_b``  — XTP source at sha_b
            ``diff``       — unified diff between a and b
            ``csv_path``   — path of the written Bin2Bin CSV
            ``csv_content``— raw CSV text
            ``error``      — non-empty string if anything failed
        """
        token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

        agent_state: dict = {
            "program_a": "", "program_b": "", "diff": "",
            "csv_path": "", "csv_content": "", "error": "",
        }

        # ── Step 1: fetch both file versions directly via REST API ────────
        self._log._logger.info(
            "[XTPGitCommitAgent] Fetching %s at %s …", GITHUB_XTP_PATH, sha_a[:8]
        )
        try:
            content_a = _fetch_file_at_sha(sha_a, token)
            agent_state["program_a"] = content_a
            self._log._logger.info("[XTPGitCommitAgent] Program A fetched (%d chars).", len(content_a))
        except Exception as exc:  # noqa: BLE001
            agent_state["error"] = str(exc)
            return agent_state

        self._log._logger.info(
            "[XTPGitCommitAgent] Fetching %s at %s …", GITHUB_XTP_PATH, sha_b[:8]
        )
        try:
            content_b = _fetch_file_at_sha(sha_b, token)
            agent_state["program_b"] = content_b
            self._log._logger.info("[XTPGitCommitAgent] Program B fetched (%d chars).", len(content_b))
        except Exception as exc:  # noqa: BLE001
            agent_state["error"] = str(exc)
            return agent_state

        # ── Step 2: compute the diff in Python (no LLM needed) ───────────
        lines_a = content_a.splitlines(keepends=True)
        lines_b = content_b.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=f"Program_A@{sha_a[:8]}",
            tofile=f"Program_B@{sha_b[:8]}",
            lineterm="",
        ))
        diff_text = "\n".join(diff_lines) if diff_lines else "(no differences)"
        agent_state["diff"] = diff_text
        self._log._logger.info(
            "[XTPGitCommitAgent] Diff computed (%d changed lines).", len(diff_lines)
        )

        # ── Step 3: generate Bin2Bin CSV via LLM (severity from diff size) ─
        @tool
        def compute_xtp_diff(content_a: str, content_b: str) -> str:  # noqa: F841
            """Return the pre-computed unified diff between Program A and Program B."""
            return agent_state["diff"]

        @tool
        def generate_bin2bin_csv(
            total_dice: int = 1000,
            delta_severity: str = "moderate",
        ) -> str:
            """Compute a Bin2Bin yield-transition matrix and write it to disk.

            Parameters
            ----------
            total_dice     : number of DUTs (default 1000).
            delta_severity : 'mild', 'moderate', or 'severe'.
            """
            result = self._build_bin2bin_csv(
                total_dice=total_dice,
                delta_severity=delta_severity,
                output_folder=output_folder,
            )
            if "CSV_CONTENT:\n" in result:
                agent_state["csv_content"] = result.split("CSV_CONTENT:\n", 1)[1]
            if "CSV_PATH:" in result:
                agent_state["csv_path"] = result.split("CSV_PATH:", 1)[1].split("\n", 1)[0]
            return result

        model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
            temperature=0.1,
        )

        agent = create_react_agent(
            model=model,
            prompt=_SYSTEM_PROMPT,
            tools=[compute_xtp_diff, generate_bin2bin_csv],
        )

        user_message = (
            f"Here are the two XTP program versions to analyse.\n\n"
            f"SHA_A ({sha_a[:8]}) — {len(content_a)} chars\n"
            f"SHA_B ({sha_b[:8]}) — {len(content_b)} chars\n\n"
            f"Diff summary: {len(diff_lines)} diff lines.\n\n"
            f"Call `generate_bin2bin_csv` with an appropriate delta_severity, "
            f"then produce the three fenced code blocks."
        )

        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]}
            )
            agent_state["raw_output"] = result["messages"][-1].content
            self._log._logger.info("[XTPGitCommitAgent] Agent finished.")
        except Exception as exc:  # noqa: BLE001
            self._log._logger.error("[XTPGitCommitAgent] Agent error: %s", exc)
            agent_state["error"] = str(exc)

        return agent_state

    # ------------------------------------------------------------------
    # Sync wrapper (for Dash background threads)
    # ------------------------------------------------------------------

    def invoke_sync(
        self,
        sha_a: str,
        sha_b: str,
        output_folder: str = "Programas",
    ) -> dict[str, str]:
        """Synchronous wrapper around :meth:`invoke`.

        Creates a new event loop so it can be called safely from threads
        that are not already running an asyncio loop (e.g. Dash callbacks).
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.invoke(sha_a, sha_b, output_folder))
        finally:
            loop.close()
