from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from Helpers.Logger import AgentLogger

from XTPAnalyser.CompareFiles import XTPFileComparer
from XTPAnalyser.XTPProgramDiffAgent import XTPProgramDiffAgent
from XTPAnalyser.XTPBin2BinMatrixAgent import XTPBin2BinMatrixAgent
from XTPAnalyser.XTPMismatchJustificationAgent import XTPMismatchJustificationAgent
from XTPAnalyser.XTPTableExtractor import XTPTableExtractor


import os

from dotenv import load_dotenv

class XTPAnalysisState(TypedDict):
    file_comparer: XTPFileComparer
    justification_table : str
    bin2bin_file : str
    log: AgentLogger
    response_xtp_diff: str
    response_bin2bin: str
    

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

def _generate_xtp_diff_node(state: XTPAnalysisState) -> XTPAnalysisState:
    log: AgentLogger = state["log"]
    log._logger.info("Initializing XTP Program Diff Agent")
    
    agent = XTPProgramDiffAgent(log)
    response = agent.analyse(state["file_comparer"])
    log._logger.debug(agent.analyse(state["file_comparer"]))
    return {**state, "response_xtp_diff": response}


def _analyze_bin2bin_node(state: XTPAnalysisState) -> XTPAnalysisState:
    log: AgentLogger = state["log"]
    log._logger.info("Initializing XTP Bin2Bin Analyzer Agent")    
    agent = XTPBin2BinMatrixAgent(log)
    
    bin2bin_answer = agent.analyse(state["bin2bin_file"])
    
    log._logger.debug(f"XTP Diff Response: {state["response_xtp_diff"]} \n\n {"-"*64} \n'\n\n Bin2Bin analyzer answer {bin2bin_answer}")
    
    return {**state, "response_bin2bin": bin2bin_answer}

def _justify_mismatches_node(state: XTPAnalysisState) -> XTPAnalysisState:
    log: AgentLogger = state["log"]
    log._logger.info("Initializing XTP Justify Mismatches Agent")    
    
    agent_justification = XTPMismatchJustificationAgent(log)
    
    justification_answer = agent_justification.justify(matrix_report = state["response_bin2bin"], diff_report = state["response_xtp_diff"])
    
    log._logger.debug(justification_answer)
    
    return {**state, "response_xtp_diff": justification_answer}

def _extract_justification_table_node(state: XTPAnalysisState) -> XTPAnalysisState:
    log: AgentLogger = state["log"]
    log._logger.info("Initializing XTP Summary Extractor")
    
    extractor_agent = XTPTableExtractor()
    
    mismatch_df = extractor_agent.extract(state["response_xtp_diff"])
    log._logger.info("=== Mismatch Justification DataFrame ===")
    log._logger.info("\n%s", mismatch_df.to_string(index=False))  

logger = AgentLogger(name="xtp_analysis", level="INFO")

graph = StateGraph(XTPAnalysisState)

graph.add_node("generate_diff", _generate_xtp_diff_node)
graph.add_node("analize_bin2bin", _analyze_bin2bin_node)
graph.add_node("justify_mismatches", _justify_mismatches_node)
graph.add_node("extract_justification_table", _extract_justification_table_node)
graph.add_edge(START, "generate_diff")
graph.add_edge("generate_diff", "analize_bin2bin")
graph.add_edge("analize_bin2bin", "justify_mismatches")
graph.add_edge("justify_mismatches", "extract_justification_table")
graph.add_edge("extract_justification_table", END)

compare_files = XTPFileComparer(r"Programas/Program_A_20260816_002045.xtp", r"Programas/Program_B_20260816_002045.xtp")
file_comparer = XTPAnalysisState(file_comparer=compare_files, bin2bin_file = r"Programas/Bin2Bin_20260816_002045.csv", log = logger)

graph.compile().invoke(file_comparer)

