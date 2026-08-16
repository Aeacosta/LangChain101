"""
XTPGeneratorAgent — Synthetic XTP program & Bin2Bin matrix generator.

Generates two valid XTP test program scripts (Program A / Program B) with a
controlled parametric delta. The Bin2Bin yield-transition matrix is computed
deterministically in Python and written directly to disk as a CSV — the LLM
is never asked to produce or narrate it.
"""

import csv
import io
import json
import os
import random

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger
from RAG.xtp_rag import XTPRagCore

_SYSTEM_PROMPT = """
    You are an expert ATE Test Program Generator specializing in synthetic XTP (eXtensible Test Script Language) code generation.

### CORE OBJECTIVE
Generate two valid XTP test program scripts (`Program A` and `Program B`) featuring intentional, controlled parametric differences.

### WORKFLOW RULES

1. TOOL EXECUTION FIRST:
   - Call `select_random_xtp_delta()` to select the specific block modification (`LEVELS`, `TIMING`, or `PARAMETRICS`).
   - Call `generate_bin2bin_csv()` to compute and save the Bin2Bin matrix to disk. This tool handles the matrix entirely — do NOT describe, reproduce, or comment on its output.
   - Call `find_xtp_documents` to retrieve relevant XTP syntax examples before writing the programs.

2. PROGRAM GENERATION:
   - Construct complete, syntactically valid XTP scripts for **Program A** (Baseline) and **Program B** (Modified).
   - Ensure both programs contain all 6 mandatory XTP structural blocks: `PINMAP`, `LEVELS`, `TIMING`, `PARAMETRICS`, `FUNCTIONS`, `BINNING`.
   - Embed the target parameter delta explicitly inside Program B's modified block.

3. OUTPUT — XTP PROGRAMS ONLY:
   - Output ONLY **Program A** and **Program B** in standard code blocks. Nothing else.
   - Do NOT include any matrix, table, analysis, summary, physical effect, key transitions, or correlation. The matrix is already saved by the tool.

### XTP SYNTAX REFERENCE
```xtp
PINMAP {
    PIN VDD_CORE TYPE POWER;
    PIN VSS TYPE GROUND;
    PIN CLK TYPE INPUT;
    PIN DATA_OUT TYPE OUTPUT;
}
LEVELS {
    V_DD_CORE = 1.20V;
    V_IH = 0.80V;
    V_IL = 0.20V;
}
TIMING {
    period_ns = 10.0;
    strobe_ns = 4.2;
}
PARAMETRICS {
    I_DDQ_MAX = 15.0mA;
}
BINNING {
    PASS_PRIME -> HB_1, SB_1001;
    PASS_ECO -> HB_1, SB_1003;
    FAIL_LEAKAGE -> HB_3, SB_3001;
    FAIL_TIMING -> HB_4, SB_4001;
}
```
"""


class XTPGeneratorAgent:
    """Generates paired XTP test programs (A/B) with a controlled parametric
    delta and a matching Bin2Bin yield-transition matrix."""

    def __init__(self, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="xtp_generator_agent", level="DEBUG")
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

        @tool
        def generate_bin2bin_csv(
            total_dice: int = 1000,
            delta_severity: str = "moderate",
            output_folder: str = "Programas",
        ) -> str:
            """
            Computes a mathematically consistent Bin2Bin yield transition matrix
            and writes it directly to disk as Bin2Bin_Matrix.csv.
            Returns the file path on success. Do NOT reproduce or narrate the
            matrix contents in your response.

            Parameters:
            - total_dice: Total number of DUTs tested (default 1000).
            - delta_severity: 'mild', 'moderate', or 'severe' shift in test limits.
            - output_folder: Directory to write the CSV (default 'Programas').
            """
            pass_prime_a = int(total_dice * 0.80)
            pass_eco_a   = int(total_dice * 0.10)
            leakage_fail_a = int(total_dice * 0.05)
            timing_fail_a  = int(total_dice * 0.05)

            if delta_severity == "mild":
                downbin_rate      = random.uniform(0.02, 0.05)
                timing_fail_rate  = random.uniform(0.01, 0.03)
            elif delta_severity == "moderate":
                downbin_rate      = random.uniform(0.10, 0.18)
                timing_fail_rate  = random.uniform(0.05, 0.08)
            else:  # severe
                downbin_rate      = random.uniform(0.25, 0.35)
                timing_fail_rate  = random.uniform(0.12, 0.20)

            to_eco         = int(pass_prime_a * downbin_rate)
            to_timing_fail = int(pass_prime_a * timing_fail_rate)
            stay_prime     = pass_prime_a - to_eco - to_timing_fail

            bins = ["SB_1001_PassPrime", "SB_1003_EcoPass", "SB_3001_IDDQ_Fail", "SB_4001_TimingFail"]
            rows = [
                ["Prog_A \\ Prog_B", "SB_1001_PassPrime", "SB_1003_EcoPass", "SB_3001_IDDQ_Fail", "SB_4001_TimingFail"],
                ["SB_1001_PassPrime", stay_prime,   to_eco,       0,              to_timing_fail],
                ["SB_1003_EcoPass",   0,             pass_eco_a,   0,              0             ],
                ["SB_3001_IDDQ_Fail", 0,             0,            leakage_fail_a, 0             ],
                ["SB_4001_TimingFail",0,             0,            0,              timing_fail_a ],
            ]

            os.makedirs(output_folder, exist_ok=True)
            csv_path = os.path.join(output_folder, "Bin2Bin_Matrix.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(rows)

            return f"CSV written to {csv_path}"

        @tool
        def select_random_xtp_delta() -> str:
            """
            Selects a random electrical test change scenario to apply between
            Program A and Program B. Returns the block to modify, the parameter
            name, and the two values (A and B).
            """
            scenarios = [
                {
                    "target_block": "LEVELS",
                    "parameter": "V_DD_CORE",
                    "val_a": "1.20V",
                    "val_b": "0.95V",
                },
                {
                    "target_block": "PARAMETRICS",
                    "parameter": "I_DDQ_MAX",
                    "val_a": "15.0mA",
                    "val_b": "8.0mA",
                },
                {
                    "target_block": "TIMING",
                    "parameter": "strobe_ns",
                    "val_a": "4.2ns",
                    "val_b": "3.1ns",
                },
            ]
            return json.dumps(random.choice(scenarios), indent=2)

        model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
            temperature=0.1,
        )

        self._agent = create_agent(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            tools=[find_xtp_documents, generate_bin2bin_csv, select_random_xtp_delta],
            debug=False,
        )

    def invoke(self, message: str = "Generate 2 Random XTP Programs") -> str:
        """Run the generator agent and return the full formatted response."""
        self._log._logger.info("[XTPGeneratorAgent] Question: %s", message)
        result = self._agent.invoke({"messages": [{"role": "user", "content": message}]})
        return result["messages"][-1].content
