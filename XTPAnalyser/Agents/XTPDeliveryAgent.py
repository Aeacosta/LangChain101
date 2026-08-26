"""
XTPDeliveryAgent — Parses generator output and saves files to disk.

Extracts Program B (XTP) and the Bin2Bin CSV matrix from the upstream
generator response and writes each as a standalone file alongside the
original Program A (passed in separately).
"""

import os
import re
from datetime import datetime

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger
from Helpers.LangfuseCallbackHandler import get_callback, trace_name_context

_SYSTEM_PROMPT = """
You are a File System Management Agent. Your only job is to save three pre-extracted assets to disk.

### WORKFLOW — follow these steps in order

1. Call `get_timestamp` once. Use the returned string as `<TS>` for all three file names.

2. Call `write_file_to_disk` with the PROGRAM_A content provided → file name `Program_A_<TS>.xtp`

3. Call `write_file_to_disk` with the PROGRAM_B content provided → file name `Program_B_<TS>.xtp`

4. Call `write_csv_to_disk` with the BIN2BIN_CSV content provided → file name `Bin2Bin_<TS>.csv`
   - Pass the CSV content EXACTLY as given. Do NOT truncate, summarise, or reformat it.

5. Reply with the three saved file paths and their byte sizes. Nothing else.
"""


class XTPDeliveryAgent:
    """Parses a combined XTP generator response and saves each asset
    (Program A, Program B, Bin2Bin CSV) to the local file system."""

    def __init__(self, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="xtp_delivery_agent", level="DEBUG")

        @tool
        def get_timestamp() -> str:
            """
            Returns the current local date and time as a compact string suitable
            for use in file names (e.g., '20250115_143022').

            No parameters required.
            """
            return datetime.now().strftime("%Y%m%d_%H%M%S")

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

        @tool
        def write_csv_to_disk(folder_path: str, file_name: str, content: str) -> str:
            """
            Saves raw CSV text to a specified directory on the local file system.
            Creates target directories automatically if they do not exist.

            Parameters:
            - folder_path: Target directory path (e.g., './output_xtp/').
            - file_name: Target filename (e.g., 'Bin2Bin_20250115_143022.csv').
            - content: The raw CSV string (no markdown fences, just header + data rows).
            """
            try:
                import re as _re
                content = _re.sub(r"^```[^\n]*\n", "", content.lstrip("\n"))
                content = _re.sub(r"\n```\s*$", "", content)
                content = content.strip("\n") + "\n"
                os.makedirs(folder_path, exist_ok=True)
                full_path = os.path.join(folder_path, file_name)
                with open(full_path, "w", encoding="utf-8", newline="") as f:
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
            tools=[get_timestamp, write_file_to_disk, write_csv_to_disk],
            debug=False,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_blocks(text: str) -> tuple[str, str]:
        """Extract Program B and the Bin2Bin CSV from *text*.

        The generator emits two fenced code blocks in order:
          1. ```xtp  … ```   — Program B (modified)
          2. ```csv  … ```   — Bin2Bin matrix

        Returns (prog_b, csv_content).  Raises ValueError if any
        block cannot be found.
        """
        xtp_blocks = re.findall(r"```xtp\s*\n(.*?)```", text, re.DOTALL)
        csv_blocks = re.findall(r"```csv\s*\n(.*?)```", text, re.DOTALL)

        if not xtp_blocks:
            raise ValueError("No ```xtp block found in generator output.")
        if not csv_blocks:
            raise ValueError("No ```csv block found in generator output.")

        return xtp_blocks[0].strip(), csv_blocks[0].strip()

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def invoke(
        self,
        generator_output: str,
        input_program: str,
        output_folder: str = "Programas",
    ) -> str:
        """Parse *generator_output*, extract assets in Python, then instruct
        the agent to save all three files to *output_folder*.

        Parameters
        ----------
        generator_output:
            Raw text returned by XTPGeneratorAgent (contains Program B + CSV blocks).
        input_program:
            The original XTP program text (saved as Program A).
        output_folder:
            Target directory for the written files.
        """
        self._log._logger.info("[XTPDeliveryAgent] Saving assets to: %s", output_folder)

        try:
            prog_b, csv_content = self._extract_blocks(generator_output)
        except ValueError as exc:
            self._log._logger.error("[XTPDeliveryAgent] Extraction failed: %s", exc)
            return f"ERROR: {exc}"

        self._log._logger.debug(
            "[XTPDeliveryAgent] Extracted blocks — B: %d chars, CSV: %d chars",
            len(prog_b), len(csv_content),
        )

        message = (
            f"Save these three assets to the `{output_folder}` folder.\n\n"
            f"PROGRAM_A:\n{input_program}\n\n"
            f"PROGRAM_B:\n{prog_b}\n\n"
            f"BIN2BIN_CSV:\n{csv_content}"
        )

        _cb = get_callback()
        _callbacks = [_cb] if _cb else []
        with trace_name_context("XTPDeliveryAgent"):
            result = self._agent.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config={"callbacks": _callbacks},
            )
        return result["messages"][-1].content
