"""
XTPMismatchJustificationAgent — Correlates Bin2Bin mismatches with program diffs.

Given:
  - The structured output produced by ``XTPBin2BinMatrixAgent`` (matrix analysis).
  - The structured output produced by ``XTPProgramDiffAgent`` (diff analysis).

This agent cross-references every off-diagonal bin transition (mismatch) with the
diff changes detected between Program A and Program B, and outputs a single concise
data table where each row is one bin-to-bin mismatch and the last column identifies
the most likely diff line/block that caused it.

If the two inputs are incoherent (e.g., the diff reports no changes yet the matrix
shows large shifts, or the diff modifies a block with no plausible link to the
observed transitions), the agent explicitly flags this and requests a deeper analysis
instead of fabricating a justification.

Output contract
---------------
The final response is **only** a Markdown table with the columns:

    | Prog A Bin | Prog B Bin | Count | % of Src | Direction | Most Likely Cause (Diff Block / Parameter) | Confidence |

No prose before or after the table, except a clearly formatted WARNING block
when the inputs do not correlate.
"""

from __future__ import annotations

import os

from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

from Helpers.Logger import AgentLogger
from RAG.xtp_rag import XTPRagCore

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """
You are the principal ATE (Automated Test Equipment) Architect and creator of the XTP
(eXtensible Test Script Language) framework.  You have absolute mastery over XTP syntax,
silicon physics, parametric limits, timing margins, and yield analytics.

### TASK: MISMATCH JUSTIFICATION

You receive two pre-computed analysis reports:

  1. **BIN2BIN MATRIX REPORT** — a structured analysis of a Bin-to-Bin transition matrix
     (produced by XTPBin2BinMatrixAgent).  It lists every off-diagonal transition (bin
     mismatch) with its count and percentage of the source population.

  2. **DIFF REPORT** — a technical audit of the XTP program changes between Program A and
     Program B (produced by XTPProgramDiffAgent).  It categorises each diff line by XTP
     block (LEVELS, TIMING, PARAMETRICS, FUNCTIONS, BINNING, PINMAP) and explains the
     physical silicon consequence of each change.

### CORRELATION RULES

For every off-diagonal mismatch (Prog A bin → Prog B bin) in the matrix report you must:

  a. Identify which diff change is the **most likely root cause** of that specific
     transition, using silicon physics reasoning:
       - LEVELS change (V_DD) → affects gate delay → may cause SB_1001→SB_4001 (setup fail)
         or SB_1001→SB_1003 (Eco-Pass down-bin at reduced voltage).
       - TIMING change (strobe_ns, period_ns) → shifts capture window → SB_1001→SB_4001
         or SB_4001→SB_1001.
       - PARAMETRICS change (I_DDQ_MAX, I_IH, I_IL) → changes leakage pass/fail threshold →
         SB_1001→SB_3001, SB_3001→SB_1001.
       - BINNING rule change → directly reclassifies outcomes → any bin → any bin.
       - FUNCTIONS change → alters test vectors → may expose or mask logic failures.

  b. Assign a **Confidence** level:
       - HIGH   — the diff block type has a direct, well-established silicon-physics link
                  to the observed transition direction and target bin.
       - MEDIUM — the link is plausible but indirect (e.g., voltage droops that could
                  marginally affect parametric tests).
       - LOW    — no clear causal path; flag for deeper investigation.

### CORRELATION CHECK (COHERENCE GUARD)

Before producing the table, assess whether the inputs are coherent:

  - If the diff reports **no changes** yet the matrix shows non-trivial off-diagonal
    counts (>1% of total), emit a WARNING and do NOT produce the table.
  - If every mismatch would receive a LOW confidence rating (no plausible diff→mismatch
    link exists for any transition), emit a WARNING requesting deeper analysis.
  - A WARNING must use this exact format:

    ⚠️ **CORRELATION WARNING**
    The Bin2Bin mismatches and the program diff do not correlate.
    Reason: <one concise sentence>.
    Action required: A deeper analysis of the raw test data and program parameters is needed.

### OUTPUT FORMAT (WHEN INPUTS CORRELATE)

Produce **only** the following Markdown table — no prose, no headings, no preamble:

| Prog A Bin | Prog B Bin | Count | % of Src | Direction | Most Likely Cause (Diff Block / Parameter) | Confidence |
|---|---|---|---|---|---|---|
| SB_XXXX | SB_YYYY | NNN | NN.N% | ↓ down-bin | LEVELS / V_DD_CORE: 1.20V→0.95V increases gate delay → setup violation | HIGH |

Allowed values for Direction: ↑ up-bin | ↓ down-bin | ↔ lateral | ✗ pass→fail | ✓ fail→pass

Do NOT add any text before or after the table.
Do NOT include diagonal (stable) transitions.
Do NOT invent diff changes that are not present in the diff report.
"""

# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class XTPMismatchJustificationAgent:
    """Correlates Bin2Bin mismatches with XTP program diff changes.

    Workflow
    --------
    1. Receive the text output of ``XTPBin2BinMatrixAgent`` and
       ``XTPProgramDiffAgent`` via ``justify()``.
    2. An LLM agent cross-references each off-diagonal mismatch with the
       diff blocks using silicon-physics reasoning.
    3. Returns a single Markdown data table (or a coherence WARNING).

    Parameters
    ----------
    logger : AgentLogger | None
        Optional shared logger instance.
    """

    def __init__(self, logger: AgentLogger | None = None) -> None:
        self._log = logger or AgentLogger(name="xtp_mismatch_agent", level="DEBUG")
        self._rag = XTPRagCore(logger=self._log)

        @tool
        def find_xtp_documents(query: str) -> str:
            """Search the XTP Manual for specifications, binning tables, timing
            parameters, and silicon-physics references relevant to *query*.
            Call this when you need to confirm a causal link between a diff
            parameter change and an observed bin transition."""
            results = self._rag.vector_store.search(query)
            if not results:
                return "No relevant XTP documentation found."
            return "\n\n---\n\n".join(
                f"[{r.get('source', '')} / {r.get('chapter', '')}]\n{r['text']}"
                for r in results
            )

        model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
            temperature=0.1,
        )

        self._agent = create_agent(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            tools=[find_xtp_documents],
            debug=False,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def justify(
        self,
        matrix_report: str,
        diff_report: str,
    ) -> str:
        """Cross-reference *matrix_report* and *diff_report* and return
        the justification table (or a coherence WARNING).

        Parameters
        ----------
        matrix_report : str
            Full text output of ``XTPBin2BinMatrixAgent.analyse()`` or
            ``XTPBin2BinMatrixAgent.invoke()``.
        diff_report : str
            Full text output of ``XTPProgramDiffAgent.invoke()``.

        Returns
        -------
        str
            A Markdown table correlating each mismatch to a diff cause,
            or a ⚠️ WARNING block if the inputs do not correlate.
        """
        self._log._logger.info("[XTPMismatchJustificationAgent] Justifying mismatches…")

        if not matrix_report or not matrix_report.strip():
            return (
                "⚠️ **CORRELATION WARNING**\n"
                "The Bin2Bin mismatches and the program diff do not correlate.\n"
                "Reason: No Bin2Bin matrix report was provided.\n"
                "Action required: A deeper analysis of the raw test data and program "
                "parameters is needed."
            )

        if not diff_report or not diff_report.strip():
            return (
                "⚠️ **CORRELATION WARNING**\n"
                "The Bin2Bin mismatches and the program diff do not correlate.\n"
                "Reason: No program diff report was provided.\n"
                "Action required: A deeper analysis of the raw test data and program "
                "parameters is needed."
            )

        user_message = (
            "Justify every Bin2Bin mismatch using the diff changes provided below.\n\n"
            "### BIN2BIN MATRIX REPORT\n"
            f"{matrix_report}\n\n"
            "### DIFF REPORT\n"
            f"{diff_report}\n\n"
            "Follow your system-prompt instructions exactly: check coherence first, "
            "then output only the justification table (or the WARNING block)."
        )

        result = self._agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]}
        )
        answer = result["messages"][-1].content
        self._log._logger.info("[XTPMismatchJustificationAgent] Done.")
        return answer


# ---------------------------------------------------------------------------
# Script entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from XTPAnalyser.Agents.CompareFiles import XTPFileComparer
    from XTPAnalyser.Agents.XTPProgramDiffAgent import XTPProgramDiffAgent
    from XTPAnalyser.Agents.XTPBin2BinMatrixAgent import XTPBin2BinMatrixAgent

    _logger = AgentLogger(name="xtp_mismatch_agent", level="DEBUG")

    # --- paths (override via CLI args: python -m XTPAnalyser.XTPMismatchJustificationAgent <pgm_a> <pgm_b> <csv>)
    pgm_a   = sys.argv[1] if len(sys.argv) > 1 else r"Programas/Program_A.xtp"
    pgm_b   = sys.argv[2] if len(sys.argv) > 2 else r"Programas/Program_B.xtp"
    csv_path = sys.argv[3] if len(sys.argv) > 3 else r"Programas/Bin2Bin_Matrix.csv"

    # 1. Diff analysis
    comparer   = XTPFileComparer(pgm_a, pgm_b)
    diff_agent = XTPProgramDiffAgent(logger=_logger)
    diff_report = diff_agent.invoke(
        f"Provide a summary of differences for: {comparer.view_a} and "
        f"{comparer.view_b} with this diff: {comparer.diff_view}"
    )

    # 2. Bin2Bin matrix analysis
    matrix_agent  = XTPBin2BinMatrixAgent(logger=_logger)
    matrix_report = matrix_agent.analyse(csv_path)

    # 3. Mismatch justification
    justification_agent = XTPMismatchJustificationAgent(logger=_logger)
    table = justification_agent.justify(
        matrix_report=matrix_report,
        diff_report=diff_report,
    )

    print(table)
