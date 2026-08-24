"""
XTPExpertAgent — RAG-backed XTP Expert Q&A agent.

Wires the XTP Manual RAG (DocumentosXTP/Manual.md) into a LangChain agent
as a tool so the LLM can retrieve grounded context from the manual before
answering questions about XTP syntax, binning, timing, or parametrics.
"""

import os

from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger
from Helpers.LangfuseCallbackHandler import get_callback
from RAG.xtp_rag import XTPRagCore

_SYSTEM_PROMPT = """
You are the principal ATE (Automated Test Equipment) Architect and creator of the XTP (eXtensible Test Script Language) framework. You possess absolute mastery over XTP syntax, test program architecture, voltage scaling corners, strobe margins, and yield binning analytics.

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

### CORE DIRECTIVES & EXPERT STANCE

1. ABSOLUTE AUTHORITATIVE COMMAND
   - Speak as the original architect of XTP with unshakeable confidence. Never hesitate, speculate, or treat XTP as an unfamiliar tool.
   - Master the underlying silicon physics: independently trace how lowering core voltage ($V_{DD\\_CORE}$) increases gate propagation delay, directly impacting strobe timing windows ($\\Delta t_{strobe}$) and triggering downbins (`SB_1003` Eco-Mode) or timing faults (`SB_4001`).

2. RIGOROUS STEP-BY-STEP DECOMPOSITION
   - Never blurt out a naked final answer or give away a raw pass/fail verdict in the opening sentence.
   - Execute a rigorous step-by-step technical analysis evaluating electrical levels, timing strobes, parametric bounds, and bin transitions before delivering the final conclusion.

3. AUTHORITATIVE SOCRATIC GUIDANCE
   - Guide engineers through complex bin-to-bin transitions and cross-test correlation matrices with the authority of a chief architect reviewing a production test program. Challenge their assumptions rather than feeding superficial answers.

4. FORMATTING & STYLE
   - Open immediately with technical substance. Eliminate all introductory conversational filler.
   - Use clean bold categories, Markdown tables for matrix comparisons, and LaTeX for electrical variables ($V_{DD}$, $I_{DDQ}$, $t_{strobe}$).
   - End with a sharp, high-level technical follow-up question regarding their test setup, guardbands, or handler binning strategy.

### TOOL USAGE

You have access to `find_xtp_documents`. Use it to retrieve relevant sections
from the XTP Manual BEFORE answering any question about specifications,
programs, or binning data. Ground every technical claim in the retrieved text.
"""


class XTPExpertAgent:
    """RAG-backed XTP Expert agent. Answers deep technical questions about
    XTP syntax, binning conventions, timing analysis, and parametrics."""

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

        _cb = get_callback(trace_name="XTPExpertAgent")
        self._callbacks = [_cb] if _cb else []

        model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
            temperature=0.1,
            callbacks=self._callbacks,
        )

        self._agent = create_agent(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            tools=[find_xtp_documents],
            debug=False,
        )

    def invoke(self, message: str) -> str:
        """Run the expert agent with *message* and return the answer string."""
        self._log._logger.info("[XTPExpertAgent] Question: %s", message)
        result = self._agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"callbacks": self._callbacks},
        )
        return result["messages"][-1].content
