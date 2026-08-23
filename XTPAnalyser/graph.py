"""
XTP Analyser — LangGraph Pipeline
==================================
Defines a typed state and a two-node StateGraph that wires the
XTPGeneratorAgent → XTPDeliveryAgent in sequence.

Graph shape
-----------

    [START]
       │
       ▼
   generate          ← XTPGeneratorAgent: select delta, build Bin2Bin CSV,
       │               retrieve RAG docs, produce Program A + B text
       ▼
   deliver           ← XTPDeliveryAgent: parse generator output, write
       │               Program_A.xtp and Program_B.xtp to disk
       ▼
    [END]

Usage
-----
    from XTPAnalyser.graph import build_graph

    app = build_graph(output_folder="Programas")

    # Stream node-by-node events (useful for live UI feedback)
    for chunk in app.stream({"output_folder": "Programas"}):
        print(chunk)

    # Or invoke synchronously for the final state
    final = app.invoke({"output_folder": "Programas"})
    print(final["delivery_result"])
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from Helpers.Logger import AgentLogger


# ---------------------------------------------------------------------------
# Shared pipeline state
# ---------------------------------------------------------------------------

class XTPState(TypedDict, total=False):
    """Typed state that flows through the XTP pipeline graph.

    Fields
    ------
    input_program   : Full text of the XTP program supplied by the caller (Program A).
    output_folder   : Target directory for generated files (set by caller).
    generator_output: Raw text returned by XTPGeneratorAgent (set by *generate* node).
    delivery_result : Confirmation text returned by XTPDeliveryAgent (set by *deliver* node).
    error           : Human-readable error message if any node fails.
    log             : AgentLogger instance shared across all nodes.
    """

    input_program: str
    output_folder: str
    generator_output: str
    delivery_result: str
    error: str
    log: AgentLogger


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _generate_node(state: XTPState) -> XTPState:
    """Call XTPGeneratorAgent to produce Program B + Bin2Bin from the input program."""
    from XTPAnalyser.Agents.XTPGeneratorAgent import XTPGeneratorAgent  # lazy import

    log: AgentLogger = state["log"]
    log._logger.info("▶ Initialising XTPGeneratorAgent …")

    input_program = state.get("input_program", "")
    if not input_program:
        return {**state, "error": "No input XTP program provided."}

    try:
        agent = XTPGeneratorAgent()
        log._logger.info("▶ Running generator (this may take ~30–60 s) …")
        generator_output = agent.invoke(input_program)
        log._logger.info("✓ Generator finished.")
        return {**state, "generator_output": generator_output}
    except Exception as exc:  # noqa: BLE001
        log._logger.error("✗ Generator error: %s", exc)
        return {**state, "error": str(exc)}


def _deliver_node(state: XTPState) -> XTPState:
    """Call XTPDeliveryAgent to write Program A and Program B to disk."""
    from XTPAnalyser.Agents.XTPDeliveryAgent import XTPDeliveryAgent  # lazy import

    log: AgentLogger = state["log"]

    if state.get("error"):
        return state  # skip delivery if generator already failed

    output_folder = state.get("output_folder", "Programas")
    log._logger.info("▶ Initialising XTPDeliveryAgent …")

    try:
        agent = XTPDeliveryAgent()
        log._logger.info("▶ Saving files to %s/ …", output_folder)
        delivery_result = agent.invoke(
            generator_output=state["generator_output"],
            input_program=state.get("input_program", ""),
            output_folder=output_folder,
        )
        log._logger.info("✓ Files saved.")
        log._logger.debug(delivery_result)
        return {**state, "delivery_result": delivery_result}
    except Exception as exc:  # noqa: BLE001
        log._logger.error("✗ Delivery error: %s", exc)
        return {**state, "error": str(exc)}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph(logger: AgentLogger | None = None):
    """Build and compile the XTP pipeline graph.

    Parameters
    ----------
    logger:
        An ``AgentLogger`` instance to share across nodes. If *None* a default
        INFO-level logger named ``"xtp_graph"`` is created automatically.

    Returns a compiled LangGraph app that accepts an ``XTPState`` dict as
    input and produces a fully populated ``XTPState`` dict on completion.
    Pass the same logger instance in the initial state::

        app = build_graph(logger=my_log)
        app.invoke({"output_folder": "Programas", "log": my_log})
    """
    if logger is None:
        logger = AgentLogger(name="xtp_graph", level="INFO")

    graph = StateGraph(XTPState)

    graph.add_node("generate", _generate_node)
    graph.add_node("deliver", _deliver_node)

    graph.add_edge(START, "generate")
    graph.add_edge("generate", "deliver")
    graph.add_edge("deliver", END)

    return graph.compile()
