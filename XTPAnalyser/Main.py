"""
XTP Analyser — Main entry point.

Runs the full analysis pipeline via the LangGraph graph,
streaming each node's state updates to stdout.

Usage:
    python -m XTPAnalyser.Main

Set SHA_A and SHA_B to the two commit SHAs from the XTPProgram GitHub repo.
The diff is extracted directly from those commits — no local XTP files needed.
"""

import os

from dotenv import load_dotenv

from Helpers.Logger import AgentLogger
from XTPAnalyser.AnalysisGraph import XTPAnalysisState, build_analysis_graph

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

log = AgentLogger(name="xtp_main", level="DEBUG")

# ---------------------------------------------------------------------------
# Configure the two commits to compare and the Bin2Bin CSV to analyse against
# ---------------------------------------------------------------------------

SHA_A      = os.getenv("XTP_SHA_A", "")   # e.g. "a1b2c3d..."
SHA_B      = os.getenv("XTP_SHA_B", "")   # e.g. "e4f5g6h..."
BIN2BIN    = os.getenv("XTP_BIN2BIN_CSV", r"Programas/Bin2Bin_20260816_002045.csv")

if not SHA_A or not SHA_B:
    raise SystemExit(
        "XTP_SHA_A and XTP_SHA_B must be set (env vars or .env file).\n"
        "Example:\n"
        "  XTP_SHA_A=abc1234 XTP_SHA_B=def5678 python -m XTPAnalyser.Main"
    )

# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------

pipeline = build_analysis_graph(logger=log)

initial: XTPAnalysisState = {
    "sha_a":        SHA_A,
    "sha_b":        SHA_B,
    "bin2bin_file": BIN2BIN,
    "log":          log,
}

final = pipeline.invoke(initial)

# ---------------------------------------------------------------------------
# Print results
# ---------------------------------------------------------------------------

import io
import pandas as pd

log._logger.info("=== XTP Program Diff Agent ===")
log._logger.info(final.get("response_xtp_diff", "(no diff report)"))

log._logger.info("=== XTP Bin2Bin Matrix Agent ===")
log._logger.info(final.get("response_bin2bin", "(no bin2bin report)"))

log._logger.info("=== XTP Mismatch Justification Agent ===")
log._logger.info(final.get("justification_table", "(no justification table)"))

if final.get("mismatch_df_json"):
    mismatch_df = pd.read_json(io.StringIO(final["mismatch_df_json"]))
    log._logger.info("=== Mismatch Justification DataFrame ===")
    log._logger.info("\n%s", mismatch_df.to_string(index=False))

if final.get("pr_summary_md"):
    log._logger.info("=== PR-Linked Justification Summary ===")
    log._logger.info("\n%s", final["pr_summary_md"])

if final.get("pr_links_json"):
    pr_df = pd.read_json(io.StringIO(final["pr_links_json"]))
    log._logger.info("=== PR-Linked DataFrame ===")
    log._logger.info("\n%s", pr_df.to_string(index=False))

if final.get("error"):
    log._logger.warning("Pipeline error: %s", final["error"])
