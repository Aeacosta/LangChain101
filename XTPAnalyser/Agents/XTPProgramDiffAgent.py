"""
XTPProgramDiffAgent — Audits and summarises deltas between two XTP programs.

Wires the XTP Manual RAG (DocumentosXTP/Manual.md) into a LangChain agent
as a tool so the LLM can retrieve grounded context from the manual before
answering questions about XTP syntax, binning, timing, or parametrics.
"""

import os

from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger
from Helpers.LangfuseCallbackHandler import get_callback, trace_name_context
from RAG.xtp_rag import XTPRagCore

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

_SYSTEM_PROMPT = """
You are the principal ATE (Automated Test Equipment) Architect and creator of the XTP (eXtensible Test Script Language) framework. You possess absolute mastery over XTP syntax, test program architecture, diff parsing, voltage scaling corners, strobe margins, and yield impact analytics.

### XTP FRAMEWORK ARCHITECTURE & SPECIFICATION

You own and enforce the six core structural blocks of XTP:
1. PINMAP: Device pin declarations and physical signal directions (`POWER`, `GROUND`, `INPUT`, `OUTPUT`, `INOUT`).
2. LEVELS: Operating voltage levels and logic thresholds ($V_{DD}$, $V_{IH}$, $V_{IL}$, $V_{OH}$, $V_{OL}$).
3. TIMING: Master period clock and pin drive/strobe phases (`period_ns`, `drive_high_ns`, `drive_low_ns`, `strobe_ns`).
4. PARAMETRICS: Analog leakage and quiescent current thresholds ($I_{IH}$, $I_{IL}$, $I_{DDQ}$).
5. FUNCTIONS: Cycle-by-cycle digital logic vector sequences `(CLK, DATA_IN, DATA_OUT)`.
6. BINNING: Mapping execution outcomes to physical handler destinations (`HardBin`) and software classifications (`SoftBin`).

### STANDARD BINNING CONVENTION

- Hard Bins: `HB_1` (Pass), `HB_2` (Continuity/Diode Fail), `HB_3` (Parametric Fail), `HB_4` (Logic/Timing Fail).
- Soft Bins: `SB_1001` (Pass Prime), `SB_1002` / `SB_1003` (Grade-B / Eco-Mode Pass), `SB_2001` (Open/Short Fail), `SB_3001` / `SB_3002` (Leakage / $I_{DDQ}$ Fail), `SB_4001` (Vector Mismatch / Strobe Delay Fail).

### CORE DIRECTIVES & DIFF ANALYSIS STANCE

1. DIFF-FOCUSED TECHNICAL AUDIT
   - Analyze line-by-line diffs or side-by-side program comparisons (`Program A` vs. `Program B`) with complete technical authority. 
   - Categorize all deltas strictly by their affected XTP block (`PINMAP`, `LEVELS`, `TIMING`, `PARAMETRICS`, `FUNCTIONS`, or `BINNING`).

2. SILICON PHYSICS & PARAMETRIC IMPACT
   - Do NOT just list syntax additions/deletions; explain the physical silicon consequences of every delta.
   - Trace how parameter shifts affect device execution (e.g., a drop in $V_{DD\\_CORE}$ increases gate propagation delay, narrowing setup/hold margins and risking timing faults in `SB_4001` or forcing downbins into `SB_1003`).

3. RIGOROUS STEP-BY-STEP DECOMPOSITION
   - Open immediately with technical substance. Eliminate all conversational filler (e.g., "Here is the diff analysis...").
   - Execute a step-by-step evaluation starting from structural code changes down to expected silicon behavior and binning rule alterations.

4. FORMATTING & STRUCTURE
   - **Summary Table:** Use a Markdown Table at the top detailing `Block Modified`, `Original Value (Program A)`, `New Value (Program B)`, and `Parameter Type`.
   - **Impact Breakdown:** Use standalone bold headers (**Section Header**) to detail physical effects ($V_{DD}$, $I_{DDQ}$, $\Delta t_{strobe}$).
   - **Binning & Yield Projection:** Predict expected bin shifts resulting directly from the diff.
"""


class XTPProgramDiffAgent:
    """Agent responsible for auditing, comparing, and summarizing deltas between two XTP test programs.

    This agent analyses a unified diff (and optionally the full source of both programs)
    to identify parameter shifts across the six core XTP structural blocks: PINMAP, LEVELS,
    TIMING, PARAMETRICS, FUNCTIONS, and BINNING.

    Key Capabilities:
    -----------------
    - Structural Diff Parsing: Isolates line-level additions, deletions, and modifications.
    - Silicon Physics Evaluation: Maps electrical changes (e.g., V_DD scaling, strobe_ns shifts)
      to physical effects like gate propagation delay, setup/hold violations, and thermal leakage.
    - Yield Shift Prediction: Correlates script deltas with expected binning transitions
      (e.g., SB_1001 Pass Prime downbinned to SB_1003 Eco-Mode or failing into SB_4001).
    - Structured Reporting: Outputs structured Markdown comparison tables and risk assessments.
    """

    def __init__(self, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="xtp_expert_agent", level="DEBUG")
        self._rag = XTPRagCore(logger=self._log)

        @tool
        def find_xtp_documents(query: str) -> str:
            """Search the XTP Manual for specifications, binning tables, timing
            parameters, and program examples that are relevant to *query*.
            Always call this before answering questions about XTP syntax, voltage
            corners, Bin2Bin transitions, or parametric limits."""
            results = self._rag.vector_store.search(query)
            if not results:
                return "No relevant documentation found."
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

    def analyse(
        self,
        diff: str,
        program_a: str = "",
        program_b: str = "",
    ) -> str:
        """Run a full diff analysis from raw diff text and optional program sources.

        Parameters
        ----------
        diff:
            Unified diff between Program A and Program B.
        program_a:
            Full source text of Program A (optional, provides extra context).
        program_b:
            Full source text of Program B (optional, provides extra context).

        Returns
        -------
        str
            Structured Markdown analysis produced by the agent.
        """
        parts = ["Provide a summary of differences based on the following unified diff:\n\n", diff]
        if program_a:
            parts += ["\n\nProgram A (baseline):\n", program_a]
        if program_b:
            parts += ["\n\nProgram B (modified):\n", program_b]
        return self.invoke("".join(parts))

    def invoke(self, message: str) -> str:
        """Run the expert agent with *message* and return the answer string."""
        self._log._logger.debug("[XTPProgramDiffAgent] Question: %s", message)
        _cb = get_callback()
        _callbacks = [_cb] if _cb else []
        with trace_name_context("XTPProgramDiffAgent"):
            result = self._agent.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config={"callbacks": _callbacks},
            )
        return result["messages"][-1].content

