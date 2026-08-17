"""
XTP Analyser — Main entry point.

Runs the full generate → deliver pipeline via the LangGraph graph,
then streams each node's state updates to stdout.

Usage:
    python -m XTPAnalyser.Main
"""

import os

from dotenv import load_dotenv

from Helpers.Logger import AgentLogger
from XTPAnalyser.Agents.XTPExpertAgent import XTPExpertAgent
from XTPAnalyser.graph import XTPState, build_graph

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

log = AgentLogger(name="xtp_main", level="DEBUG")

# ---------------------------------------------------------------------------
# 1. XTP Expert Agent — standalone RAG Q&A (not part of the graph)
# ---------------------------------------------------------------------------

expert_agent = XTPExpertAgent(logger=log)
expert_answer = expert_agent.invoke(
    "What are the XTP main structural blocks and what are their use?"
)
print("=== XTP Expert Agent ===")
print(expert_answer)

# ---------------------------------------------------------------------------
# 2. Run the LangGraph pipeline (generate → deliver)
# ---------------------------------------------------------------------------

print("\n=== XTP Pipeline (LangGraph) ===")

app = build_graph(logger=log)

initial_state: XTPState = {"output_folder": "Programas", "log": []}

# Each chunk from stream() is {"node_name": node_state_dict} in LangGraph 1.x.
for chunk in app.stream(initial_state):
    for node_name, node_state in chunk.items():
        print(f"\n── Node: {node_name} ──")
        for line in node_state.get("log", []):
            print(f"  {line}")

# Final state
final: XTPState = app.invoke(initial_state)

print("\n=== Generator Output (excerpt) ===")
gen_out = final.get("generator_output", "")
print(gen_out[:500] + ("…" if len(gen_out) > 500 else ""))

print("\n=== Delivery Result ===")
print(final.get("delivery_result", final.get("error", "(none)")))