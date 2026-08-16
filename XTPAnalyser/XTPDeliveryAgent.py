"""
XTPDeliveryAgent — Parses combined generator output and saves files to disk.

Extracts Program A (XTP), Program B (XTP), and the Bin2Bin report from the
upstream generator response and writes each as a standalone file.
"""

import os

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger

_SYSTEM_PROMPT = """
You are an expert Automation & File System Management Agent responsible for parsing generator output and saving XTP program files to disk.

### CORE OBJECTIVE
Extract exactly two XTP test program scripts from the provided input and save each as a standalone file.

### WORKFLOW & PARSING RULES

1. ASSET IDENTIFICATION & SANITIZATION:
   - File 1 (Program A XTP): Extract the first XTP test program script. Strip markdown code fence markers (e.g., ```xtp) so only the raw XTP code remains.
   - File 2 (Program B XTP): Extract the second XTP test program script. Strip markdown code fence markers.

2. FILE SYSTEM EXECUTION:
   - Call `write_file_to_disk` twice — once for each program.
   - Naming convention: `Program_A.xtp` and `Program_B.xtp`.
   - Do NOT write any Bin2Bin or matrix file — that is handled separately.

3. BEHAVIOR & OUTPUT FORMATTING:
   - Execute file writing deterministically using available tools.
   - Do NOT output conversational greetings or verbose confirmations.
   - Confirm the two files saved with their paths and sizes. Nothing else.
"""


class XTPDeliveryAgent:
    """Parses a combined XTP generator response and saves each asset
    (Program A, Program B, Bin2Bin report) to the local file system."""

    def __init__(self, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="xtp_delivery_agent", level="DEBUG")

        @tool
        def write_file_to_disk(folder_path: str, file_name: str, content: str) -> str:
            """
            Saves a text, script, or markdown file to a specified directory on
            the local file system. Creates target directories automatically if
            they do not exist.

            Parameters:
            - folder_path: Target directory path (e.g., './output_xtp/').
            - file_name: Target filename (e.g., 'VisionCore_V1.xtp').
            - content: The raw string content to write to the file.
            """
            try:
                import re as _re
                # Strip markdown code fences (```xtp, ```python, ``` etc.) and
                # any leading/trailing blank lines left behind by the LLM.
                content = _re.sub(r"^```[^\n]*\n", "", content.lstrip("\n"))
                content = _re.sub(r"\n```\s*$", "", content)
                content = content.strip("\n") + "\n"
                os.makedirs(folder_path, exist_ok=True)
                full_path = os.path.join(folder_path, file_name)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                file_size = os.path.getsize(full_path)
                return f"SUCCESS: Written {file_size} bytes to {full_path}"
            except Exception as e:
                return f"ERROR: Failed to write file {file_name}. Details: {str(e)}"

        model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
            temperature=0.5,
        )

        self._agent = create_agent(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            tools=[write_file_to_disk],
            debug=False,
        )

    def invoke(self, generator_output: str, output_folder: str = "Programas") -> str:
        """Parse *generator_output* and save Program A and Program B to *output_folder*."""
        message = (
            f"Extract Program A and Program B from the following generator output "
            f"and save each as an .xtp file in the `{output_folder}` folder: {generator_output}"
        )
        self._log._logger.info("[XTPDeliveryAgent] Saving assets to: %s", output_folder)
        result = self._agent.invoke({"messages": [{"role": "user", "content": message}]})
        return result["messages"][-1].content
