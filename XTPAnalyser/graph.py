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
    output_folder   : Target directory for generated files (set by caller).
    generator_output: Raw text returned by XTPGeneratorAgent (set by *generate* node).
    delivery_result : Confirmation text returned by XTPDeliveryAgent (set by *deliver* node).
    error           : Human-readable error message if any node fails.
    log             : Ordered list of status messages accumulated across nodes.
    """

    output_folder: str
    generator_output: str
    delivery_result: str
    error: str
    log: list[str]


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _generate_node(state: XTPState) -> XTPState:
    """Call XTPGeneratorAgent and store the raw output in state."""
    from XTPAnalyser.XTPGeneratorAgent import XTPGeneratorAgent  # lazy import

    log: list[str] = list(state.get("log", []))
    log.append("▶ Initialising XTPGeneratorAgent …")

    try:
        agent = XTPGeneratorAgent()
        log.append("▶ Running generator (this may take ~30–60 s) …")
        generator_output = agent.invoke("Generate 2 Random XTP Programs and Bin2Bin Matrix File correlating the 2 Programs")
        log.append("✓ Generator finished.")
        return {**state, "generator_output": generator_output, "log": log}
    except Exception as exc:  # noqa: BLE001
        log.append(f"✗ Generator error: {exc}")
        return {**state, "error": str(exc), "log": log}


def _deliver_node(state: XTPState) -> XTPState:
    """Call XTPDeliveryAgent to write Program A and Program B to disk."""
    from XTPAnalyser.XTPDeliveryAgent import XTPDeliveryAgent  # lazy import

    log: list[str] = list(state.get("log", []))

    if state.get("error"):
        return state  # skip delivery if generator already failed

    output_folder = state.get("output_folder", "Programas")
    log.append("▶ Initialising XTPDeliveryAgent …")

    try:
        agent = XTPDeliveryAgent()
        log.append(f"▶ Saving files to {output_folder}/ …")
        delivery_result = agent.invoke(
            generator_output=state["generator_output"],
            output_folder=output_folder,
        )
        log.append("✓ Files saved.")
        log.append(delivery_result)
        return {**state, "delivery_result": delivery_result, "log": log}
    except Exception as exc:  # noqa: BLE001
        log.append(f"✗ Delivery error: {exc}")
        return {**state, "error": str(exc), "log": log}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph(logger: AgentLogger | None = None) -> StateGraph:
    """Build and compile the XTP pipeline graph.

    Returns a compiled LangGraph app that accepts an ``XTPState`` dict as
    input and produces a fully populated ``XTPState`` dict on completion.
    """
    graph = StateGraph(XTPState)

    graph.add_node("generate", _generate_node)
    graph.add_node("deliver", _deliver_node)

    graph.add_edge(START, "generate")
    graph.add_edge("generate", "deliver")
    graph.add_edge("deliver", END)

    return graph.compile()
