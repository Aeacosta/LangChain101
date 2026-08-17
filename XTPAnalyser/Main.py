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
from XTPAnalyser.Agents.XTPProgramDiffAgent import XTPProgramDiffAgent
from XTPAnalyser.Agents.CompareFiles import XTPFileComparer
from XTPAnalyser.Agents.XTPBin2BinMatrixAgent import XTPBin2BinMatrixAgent
from XTPAnalyser.Agents.XTPMismatchJustificationAgent import XTPMismatchJustificationAgent
from XTPAnalyser.Agents.XTPTableExtractor import XTPTableExtractor

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

log = AgentLogger(name="xtp_main", level="DEBUG")

compare_files = XTPFileComparer(r"Programas/Program_A_20260816_002045.xtp", r"Programas/Program_B_20260816_002045.xtp")

program_diff_agent = XTPProgramDiffAgent(logger=log)
diff_answer = program_diff_agent.analyse(compare_files)
log._logger.info("=== XTP Program Diff Agent ===")
log._logger.info(diff_answer)

bin2bin_matrix_agent = XTPBin2BinMatrixAgent(logger=log)
bin2bin_answer = bin2bin_matrix_agent.analyse(r"Programas/Bin2Bin_20260816_002045.csv")
log._logger.info("=== XTP Bin2Bin Matrix Agent ===")
log._logger.info(bin2bin_answer)

# ---------------------------------------------------------------------------
# Mismatch justification — correlates every off-diagonal transition with the
# diff changes found above and returns a single justification table.
# ---------------------------------------------------------------------------

mismatch_agent = XTPMismatchJustificationAgent(logger=log)
justification_table = mismatch_agent.justify(
    matrix_report=bin2bin_answer,
    diff_report=diff_answer,
)
log._logger.info("=== XTP Mismatch Justification Agent ===")
log._logger.info(justification_table)

# ---------------------------------------------------------------------------
# Table extraction — parse the Markdown justification table into a DataFrame.
# ---------------------------------------------------------------------------

extractor = XTPTableExtractor()
try:
    mismatch_df = extractor.extract(justification_table)
    log._logger.info("=== Mismatch Justification DataFrame ===")
    log._logger.info("\n%s", mismatch_df.to_string(index=False))
except ValueError as exc:
    log._logger.warning("Could not extract table: %s", exc)

